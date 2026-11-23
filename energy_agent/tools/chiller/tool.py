"""Deterministic chiller tool; numerical work stays in chiller_app."""

from __future__ import annotations

from collections import defaultdict
import math
from uuid import uuid4

from chiller_app.model.electric_eir import performance
from energy_agent.contracts.datasets import DatasetSnapshot
from energy_agent.contracts.tools import (
    ChillerAnalysisRequest, Comparison, Diagnostic, Evidence, Metric, MissingInput,
    ModelValidity, ToolResult,
)
from energy_agent.storage.repository import Repository, utc_now
from .backend import run_model

PHYSICS_TARGETS = {
    "cooling_capacity_kW": ["TEI_K", "TEO_K", "evap_flow_kg_s"],
    "condenser_heat_kW": ["TCI_K", "TCO_K", "cond_flow_kg_s"],
    "COP": ["TEI_K", "TEO_K", "evap_flow_kg_s", "P_W"],
    "energy_balance_error_kW": ["TEI_K", "TEO_K", "TCI_K", "TCO_K", "evap_flow_kg_s", "cond_flow_kg_s", "P_W"],
}
MODEL_TARGETS = ["simulated_TEO_C", "simulated_TCO_C", "simulated_cooling_capacity_kW", "simulated_power_kW", "simulated_COP"]


class AssetMismatch(ValueError):
    pass


def finite(value) -> bool:
    return isinstance(value, (float, int)) and math.isfinite(value)


def source_row_examples(rows: list[dict]) -> list[int]:
    return list(dict.fromkeys(int(row["source_row"]) for row in rows))[:10]


def normalized_column(field: str) -> str:
    return "power_kW" if field == "P_W" else field[:-2] + "_C" if field.endswith("_K") else field


def missing_for(target: str, fields: list[str], rows: list[dict], *, positive=False) -> MissingInput | None:
    bad_rows, absent = [], set()
    for row in rows:
        missing = [field for field in fields if not finite(row.get(normalized_column(field)))
                   or (positive and field.endswith("_kg_s") and row[normalized_column(field)] <= 0)
                   or (target == "COP" and field == "P_W" and row["power_kW"] <= 0)]
        if missing:
            bad_rows.append(row)
            absent.update(missing)
    return MissingInput(target=target, fields=sorted(absent), count=len(bad_rows), source_row_examples=source_row_examples(bad_rows)) if bad_rows else None


def stable_mean(values: list[float]) -> float:
    scale = max(abs(value) for value in values)
    return scale * (math.fsum(value / scale for value in values) / len(values)) if scale else 0.0


def stable_rmse(values: list[float]) -> float:
    scale = max(abs(value) for value in values)
    return scale * math.sqrt(math.fsum((value / scale) ** 2 for value in values) / len(values)) if scale else 0.0


def invalid_model(row: dict) -> bool:
    return any(finite(row.get(key)) and row[key] < 0 for key in ("EIRFunT", "EIRFunPLR", "simulated_power_kW"))


class ChillerTool:
    name = "chiller_analyze"

    def __init__(self, repository: Repository):
        self.repository = repository

    def execute(self, request: ChillerAnalysisRequest) -> ToolResult:
        dataset = self.repository.get_dataset(request.dataset_id)
        if dataset.info.asset_id != request.asset_id:
            raise AssetMismatch("asset_id does not match the dataset's registered equipment")
        base_request = {"operation": "calculate", "records": dataset.records,
                        "schema": dataset.info.effective_schema.model_dump(),
                        "source_unit_policy":dataset.info.source_unit_policy}
        physical = run_model(base_request)
        missing = [entry for target, fields in PHYSICS_TARGETS.items()
                   if (entry := missing_for(target, fields, physical["records"])) is not None]
        errors = []
        output = physical
        status = "success"
        if request.task != "physics":
            missing = self._simulation_missing(request, physical)
            if missing:
                status = "needs_input"
            else:
                try:
                    settings = request.simulation
                    performance(settings.record_id, settings.performance)
                    output = run_model({**base_request, "operation": "simulate", "simulation": settings.model_dump()})
                except (ValueError, TypeError, KeyError, OverflowError, RuntimeError) as exc:
                    message = str(exc)
                    solver_failed = any(token in message for token in ("求解失败", "有效根", "非有限结果"))
                    status = "failed" if solver_failed else "needs_input"
                    errors.append(Diagnostic(code="MODEL_EXECUTION_FAILED" if solver_failed else "INVALID_SIMULATION_INPUT", message=message))
        result = self._summarize(request, dataset, output, missing, errors, status)
        self.repository.save_run(result.model_dump(mode="json"), output)
        return result

    @staticmethod
    def _simulation_missing(request: ChillerAnalysisRequest, physical: dict) -> list[MissingInput]:
        rows, mapping = physical["records"], physical["metadata"]["schema"]["column_map"]
        missing = []
        item = missing_for("simulation", ["TEI_K", "TCI_K", "evap_flow_kg_s", "cond_flow_kg_s"], rows, positive=True)
        if item:
            missing.append(item)
        for field in ("TSet_K", "operating_status"):
            if field in mapping:
                item = missing_for("simulation", [field], rows)
                if item:
                    missing.append(item)
            elif field == "TSet_K" and request.simulation.setpoint is None:
                missing.append(MissingInput(target="simulation", fields=[field], count=len(rows), source_row_examples=source_row_examples(rows)))
        if request.task == "compare" and not any(finite(row.get(key)) for row in rows for key in ("power_kW", "TEO_C", "TCO_C")):
            missing.append(MissingInput(target="comparison", fields=["P_W", "TEO_K", "TCO_K"], count=len(rows), source_row_examples=source_row_examples(rows)))
        return missing

    def _summarize(self, request, dataset, output, missing, errors, status) -> ToolResult:
        rows = output["records"]
        simulated = output["metadata"]["operation"] == "simulate"
        run_id = "run_" + uuid4().hex
        warnings = [Diagnostic(code="MODEL_WARNING" if simulated else "PHYSICS_WARNING", message=w["message"],
                               count=w["count"], source_row_examples=list(dict.fromkeys(w["rows"]))[:10]) for w in output["warnings"]]
        groups = defaultdict(list)
        for issue in output["issues"]:
            groups[issue["field"]].append(issue["row"])
        warnings += [Diagnostic(code="INVALID_MEASUREMENT", message=f"{field}: invalid inputs were left null",
                                count=len(indices), source_row_examples=list(dict.fromkeys(indices))[:10]) for field, indices in groups.items()]
        inference = dataset.info.quality.get("input_inference")
        if inference and (inference.get('auto_mapped_columns') or inference.get('assumed_source_units')):
            warnings.append(Diagnostic(code="SOURCE_SCHEMA_INFERRED", message="Workbench ASHRAE header inference changed or completed the supplied schema; inspect source_schema and effective_schema", count=dataset.info.row_count))
        validity = ModelValidity()
        if simulated:
            outside = [row for row in rows if row.get("curve_out_of_range", 0) > 0]
            validity.curve_out_of_range_count = len(outside)
            validity.curve_out_of_range_source_row_examples = source_row_examples(outside)
            validity.invalid_model_rows = sum(invalid_model(row) for row in rows)
            per = output["metadata"]["performance_parameters"]
            validity.curve_limits_C = {key: per[key] - 273.15 for key in ("TEvaLvgMin", "TEvaLvgMax", "TConEntMin", "TConEntMax")}
            if outside:
                warnings.append(Diagnostic(code="CURVE_OUT_OF_RANGE", message="Extrapolated model records are retained; comparison statistics exclude them", count=len(outside), source_row_examples=source_row_examples(outside)))
        result = ToolResult(
            run_id=run_id, created_at=utc_now(), asset_id=request.asset_id,
            dataset_id=request.dataset_id, dataset_version=dataset.info.version, task=request.task,
            status=status, request=request, input_rows=dataset.info.row_count, output_rows=len(rows),
            missing_inputs=missing, errors=errors, warnings=warnings,
            notes=output["notes"] + ["Summary metrics are arithmetic means of valid output points, not period COP or energy.",
                                     "Model suitability for this physical equipment has not been assessed."],
            model_validity=validity, metadata=output["metadata"], preview_records=rows[:request.preview_rows], artifact_id=run_id,
        )
        for column in ["power_kW", *PHYSICS_TARGETS, *(MODEL_TARGETS if simulated else [])]:
            is_model = column in MODEL_TARGETS
            valid = [row for row in rows if finite(row.get(column)) and not (is_model and invalid_model(row))]
            eid = f"{run_id}:{column}"
            result.evidence.append(Evidence(evidence_id=eid, artifact_id=run_id, columns=[column],
                                            selection="finite_valid_model" if is_model else "finite_values",
                                            valid_count=len(valid), source_row_examples=source_row_examples(valid)))
            result.metrics[column] = Metric(value=stable_mean([row[column] for row in valid]) if valid else None,
                                            unit=output["metadata"]["output_units"][column],
                                            origin="model" if is_model else "measured" if column == "power_kW" else "measured_derived",
                                            valid_count=len(valid), evidence_id=eid)
        if request.task == "compare" and simulated:
            self._compare(result, rows)
            mapping = dataset.info.effective_schema.column_map
            for field in ("P_W", "TEO_K", "TCO_K"):
                if field in mapping:
                    item = missing_for(f"comparison:{field}", [field], rows)
                    if item:
                        result.missing_inputs.append(item)
            result.notes.append("Each comparison target uses its own valid in-range pairs; sample counts can differ. Explicitly mapped missing targets are disclosed.")
        if status == "success":
            targets = list(PHYSICS_TARGETS) if request.task == "physics" else MODEL_TARGETS
            if request.task == "compare":
                available = [comparison for comparison in result.comparisons.values() if comparison.n]
                if not available:
                    result.status = "needs_input"
                    result.errors.append(Diagnostic(code="NO_VALID_COMPARISON_PAIRS", message="No measured/model pairs within the curve range and physical validity limits"))
                elif result.missing_inputs or any(comparison.n < len(rows) for comparison in available) or warnings:
                    result.status = "partial"
            elif not any(result.metrics[key].valid_count for key in targets):
                result.status = "needs_input"
            elif missing or warnings or any(result.metrics[key].valid_count < len(rows) for key in targets):
                result.status = "partial"
        return result

    @staticmethod
    def _compare(result: ToolResult, rows: list[dict]) -> None:
        for measured, predicted, unit in (("power_kW", "simulated_power_kW", "kW"),
                                          ("TEO_C", "simulated_TEO_C", "°C"), ("TCO_C", "simulated_TCO_C", "°C")):
            valid = [row for row in rows if finite(row.get(measured)) and finite(row.get(predicted))
                     and row.get("curve_out_of_range", 0) == 0 and not invalid_model(row)]
            error = [row[predicted] - row[measured] for row in valid]
            eid = f"{result.run_id}:comparison:{measured}"
            result.evidence.append(Evidence(evidence_id=eid, artifact_id=result.run_id, columns=[measured, predicted],
                                            selection="paired_in_range", valid_count=len(valid), source_row_examples=source_row_examples(valid)))
            result.comparisons[measured] = Comparison(measured_column=measured, predicted_column=predicted, unit=unit,
                                                      n=len(valid), mae=stable_mean([abs(value) for value in error]) if valid else None,
                                                      rmse=stable_rmse(error) if valid else None,
                                                      bias=stable_mean(error) if valid else None, evidence_id=eid)
