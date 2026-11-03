import copy

import pytest
from pydantic import ValidationError

from chiller_app.model.electric_eir import DEFAULT_RECORD
from energy_agent.contracts.tools import ChillerAnalysisRequest
from energy_agent.runtime import AgentRuntime
from energy_agent.tools.chiller.backend import run_model
from energy_agent.tools.chiller.tool import AssetMismatch


def simulation_source(**changes):
    row = {"tei": 13.89, "tci": 26.67, "me": 10.35, "mc": 19.24, **changes}
    mapping = {"TEI_K": "tei", "TCI_K": "tci", "evap_flow_kg_s": "me", "cond_flow_kg_s": "mc"}
    mapping.update({canonical: source for canonical, source in
                    (("P_W", "p"), ("TEO_K", "teo"), ("TCO_K", "tco"),
                     ("TSet_K", "setpoint"), ("timestamp", "time"), ("operating_status", "enabled")) if source in row})
    return {"asset_id": "chiller_01", "records": [row], "schema": {
        "column_map": mapping, "temperature_unit": "C", "flow_unit": "kg/s", "power_unit": "kW"}}


def analyze(runtime, dataset, task="physics", **extra):
    return runtime.analyze({"asset_id": dataset.asset_id, "dataset_id": dataset.dataset_id, "task": task, **extra})


def settings(**changes):
    return {"record_id": DEFAULT_RECORD, "mode": "steady", "kind": "series", "setpoint": 8.89, **changes}


def test_physics_matches_workbench_and_has_reproducible_evidence(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(physics_source)
    result = analyze(runtime, dataset)
    assert result.status == "success"
    assert result.metrics["cooling_capacity_kW"].value == 418
    assert result.metrics["COP"].value == 4.18
    assert result.metrics["COP"].origin == "measured_derived"
    artifact = runtime.repository.get_run(result.run_id)
    reference = run_model({"operation": "calculate", "records": physics_source["records"], "schema": physics_source["schema"]})
    assert artifact["model_output"] == reference
    assert result.model_dump(mode="json") == artifact["result"]
    evidence = {entry.evidence_id: entry for entry in result.evidence}
    assert evidence[result.metrics["COP"].evidence_id].source_row_examples == [1]
    assert all(entry.artifact_id == result.artifact_id for entry in result.evidence)


def test_missing_flow_produces_partial_without_filling(data_dir, physics_source):
    del physics_source["schema"]["column_map"]["evap_flow_kg_s"]
    runtime = AgentRuntime(data_dir)
    result = analyze(runtime, runtime.register_dataset(physics_source))
    assert result.status == "partial"
    assert result.metrics["COP"].value is None
    assert result.metrics["cooling_capacity_kW"].value is None
    assert result.metrics["condenser_heat_kW"].value == 522.5
    assert any("evap_flow_kg_s" in entry.fields for entry in result.missing_inputs)
    assert result.preview_records[0]["COP"] is None


def test_only_power_cannot_support_physics_targets(data_dir):
    source = {"asset_id": "a", "records": [{"p": 100}], "schema": {
        "column_map": {"P_W": "p"}, "temperature_unit": "C", "flow_unit": "kg/s", "power_unit": "kW"}}
    runtime = AgentRuntime(data_dir)
    result = analyze(runtime, runtime.register_dataset(source))
    assert result.status == "needs_input"
    assert result.metrics["power_kW"].value == 100
    assert len(result.missing_inputs) == 4


def test_incomplete_rows_are_retained_and_preview_is_bounded(data_dir, physics_source):
    physics_source["records"].append({**physics_source["records"][0], "me": None})
    runtime = AgentRuntime(data_dir)
    result = analyze(runtime, runtime.register_dataset(physics_source), preview_rows=1)
    assert result.status == "partial"
    assert result.output_rows == result.input_rows == 2
    assert len(result.preview_records) == 1
    records = runtime.repository.get_run(result.run_id)["model_output"]["records"]
    assert [row["source_row"] for row in records] == [1, 2]
    assert records[1]["COP"] is None
    assert result.metrics["COP"].valid_count == 1


@pytest.mark.parametrize("mode", ["steady", "dynamic"])
def test_simulation_matches_existing_engine(data_dir, mode):
    source = simulation_source(time=0, setpoint=8.89, enabled=1)
    source["records"] += [dict(source["records"][0], time=60, enabled=0), dict(source["records"][0], time=120)]
    config = settings(mode=mode, time_mode="seconds")
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(source)
    result = analyze(runtime, dataset, "simulate", simulation=config)
    actual = runtime.repository.get_run(result.run_id)["model_output"]
    expected = run_model({"operation": "simulate", "records": source["records"], "schema": source["schema"], "simulation": config})
    assert actual == expected
    assert result.metrics["simulated_power_kW"].origin == "model"
    assert result.metrics["COP"].value is None
    assert result.output_rows == 3


def test_out_of_range_preserves_values_and_marks_partial(data_dir):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source(tci=40))
    result = analyze(runtime, dataset, "simulate", simulation=settings())
    assert result.status == "partial"
    assert result.model_validity.curve_out_of_range_count == 1
    assert result.model_validity.curve_out_of_range_source_row_examples == [1]
    assert any(w.code == "CURVE_OUT_OF_RANGE" for w in result.warnings)
    assert result.metrics["simulated_power_kW"].value is not None


def test_constant_simulation_warnings_use_unique_source_row_examples(data_dir):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source(tci=40))
    result = analyze(runtime, dataset, "simulate", simulation=settings(kind="constant", duration_s=120, interval_s=60))
    assert result.output_rows == 3
    assert result.model_validity.curve_out_of_range_count == 3
    assert all(w.source_row_examples in ([], [1]) for w in result.warnings)


@pytest.mark.parametrize("change", [{"me": 0}, {"me": None}, {"setpoint": None}, {"enabled": 2}])
def test_required_simulation_inputs_cannot_be_filled_from_defaults(data_dir, change):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source(**change))
    result = analyze(runtime, dataset, "simulate", simulation=settings())
    assert result.status == "needs_input"
    assert result.missing_inputs
    assert "simulated_power_kW" not in result.metrics


def test_invalid_time_returns_needs_input_without_sorting(data_dir):
    source = simulation_source(time=10)
    source["records"].append(dict(source["records"][0], time=5))
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(source)
    result = analyze(runtime, dataset, "simulate", simulation=settings(mode="dynamic", time_mode="seconds"))
    assert result.status == "needs_input"
    assert result.errors[0].code == "INVALID_SIMULATION_INPUT"
    assert [r["time"] for r in runtime.repository.get_dataset(dataset.dataset_id).records] == [10, 5]


def test_compare_reports_independent_measured_power_error_and_excludes_extrapolation(data_dir):
    runtime = AgentRuntime(data_dir)
    source = simulation_source(p=45)
    dataset = runtime.register_dataset(source)
    simulation = analyze(runtime, dataset, "simulate", simulation=settings())
    predicted = simulation.preview_records[0]["simulated_power_kW"]
    result = analyze(runtime, dataset, "compare", simulation=settings())
    comparison = result.comparisons["power_kW"]
    assert result.status == "success"
    assert comparison.n == 1
    assert comparison.mae == pytest.approx(abs(predicted - 45))
    assert comparison.bias == pytest.approx(predicted - 45)
    source["records"][0]["tci"] = 40
    outside = analyze(runtime, runtime.register_dataset(source), "compare", simulation=settings())
    assert outside.status == "needs_input"
    assert outside.comparisons["power_kW"].n == 0
    assert outside.errors[0].code == "NO_VALID_COMPARISON_PAIRS"


def test_compare_requires_measurements_and_series(data_dir):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source())
    result = analyze(runtime, dataset, "compare", simulation=settings())
    assert result.status == "needs_input"
    assert any(entry.target == "comparison" for entry in result.missing_inputs)
    with pytest.raises(ValidationError, match="series"):
        analyze(runtime, dataset, "compare", simulation=settings(kind="constant"))


def test_explicit_model_and_equipment_identity_required(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(physics_source)
    with pytest.raises(AssetMismatch):
        runtime.analyze({"asset_id": "another", "dataset_id": dataset.dataset_id})
    with pytest.raises(ValidationError):
        analyze(runtime, dataset, "simulate", simulation={"setpoint": 5})
    result = analyze(runtime, dataset, "simulate", simulation=settings(record_id="does_not_exist"))
    assert result.status == "needs_input"
    assert result.errors


def test_inferred_ashrae_schema_is_saved_and_disclosed(data_dir):
    source = {"asset_id": "a", "records": [{"TEI": 60, "TCI": 85, "FWE": 100, "FWC": 200}], "schema": {
        "column_map": {}, "temperature_unit": "C", "flow_unit": "m3/h", "power_unit": "kW"}}
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(source)
    assert dataset.source_schema.temperature_unit == "C"
    assert dataset.effective_schema.temperature_unit == "F"
    result = analyze(runtime, dataset)
    assert any(w.code == "SOURCE_SCHEMA_INFERRED" for w in result.warnings)


def test_registry_exposes_contract_and_rejects_unknown_task(data_dir, physics_source):
    runtime = AgentRuntime(data_dir)
    assert runtime.registry.definitions()[0]["name"] == "chiller_analyze"
    assert "dataset_id" in runtime.registry.definitions()[0]["input_schema"]["properties"]
    dataset = runtime.register_dataset(physics_source)
    with pytest.raises(ValidationError):
        analyze(runtime, dataset, "train")


def test_compare_discloses_entirely_missing_explicit_target(data_dir):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source(p=45, teo=None))
    result = analyze(runtime, dataset, "compare", simulation=settings())
    assert result.status == "partial"
    assert result.comparisons["power_kW"].n == 1
    assert result.comparisons["TEO_C"].n == 0
    assert any(entry.target == "comparison:TEO_K" and entry.fields == ["TEO_K"] for entry in result.missing_inputs)


@pytest.mark.parametrize("enabled", [True, False])
def test_boolean_controls_match_workbench(data_dir, enabled):
    runtime = AgentRuntime(data_dir)
    source = simulation_source(enabled=enabled)
    result = analyze(runtime, runtime.register_dataset(source), "simulate", simulation=settings())
    assert result.status in {"success", "partial"}
    expected = run_model({"operation": "simulate", "records": source["records"], "schema": source["schema"], "simulation": settings()})
    assert runtime.repository.get_run(result.run_id)["model_output"] == expected


def test_large_finite_error_uses_stable_rmse_and_saves_result(data_dir):
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source(p=1e200))
    result = analyze(runtime, dataset, "compare", simulation=settings())
    comparison = result.comparisons["power_kW"]
    assert comparison.rmse == pytest.approx(1e200)
    assert comparison.mae == pytest.approx(1e200)
    assert runtime.repository.get_run(result.run_id)["result"]["run_id"] == result.run_id


def test_evidence_row_examples_are_explicit_and_full_selection_is_replayable(data_dir, physics_source):
    physics_source["records"] *= 12
    runtime = AgentRuntime(data_dir)
    result = analyze(runtime, runtime.register_dataset(physics_source))
    evidence = next(entry for entry in result.evidence if entry.evidence_id == result.metrics["COP"].evidence_id)
    assert evidence.valid_count == 12
    assert evidence.source_row_examples == list(range(1, 11))
    records = runtime.repository.get_run(evidence.artifact_id)["model_output"]["records"]
    selected = [row for row in records if row["COP"] is not None]
    assert len(selected) == evidence.valid_count
    assert sum(row["COP"] for row in selected) / len(selected) == pytest.approx(result.metrics["COP"].value)


def test_solver_failure_is_persisted_without_model_predictions(data_dir, monkeypatch):
    from energy_agent.tools.chiller import tool
    original = tool.run_model
    def failing_backend(request):
        if request["operation"] == "simulate":
            raise ValueError("动态求解失败：test solver failure")
        return original(request)
    runtime = AgentRuntime(data_dir)
    dataset = runtime.register_dataset(simulation_source())
    monkeypatch.setattr(tool, "run_model", failing_backend)
    result = analyze(runtime, dataset, "simulate", simulation=settings())
    assert result.status == "failed"
    assert result.errors[0].code == "MODEL_EXECUTION_FAILED"
    assert "simulated_power_kW" not in result.metrics
    assert runtime.repository.get_run(result.run_id)["result"]["status"] == "failed"
