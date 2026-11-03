"""Physical invariants, controller limits and end-to-end ElectricEIR contracts."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from chiller_app.api.fastapi_app import app
from chiller_app.model.electric_eir import DEFAULT_RECORD, ElectricEIR, catalogue, performance
from chiller_app.model.eir_calibration import calibrated_performance, fit_power_scale

client = TestClient(app)


def ideal_per(**changes):
    return performance(DEFAULT_RECORD).model_copy(update={
        "QEva_flow_nominal": -100000, "COP_nominal": 5., "capFunT": (1., 0., 0., 0., 0., 0.),
        "EIRFunT": (1., 0., 0., 0., 0., 0.), "EIRFunPLR": (0., 1., 0.), **changes})


def test_energy_power_at_part_load_overload_cycling_and_off():
    engine = ElectricEIR(ideal_per(etaMotor=.9), cp=4000)
    for demand, expected_cooling, expected_power in [(50000, 50000, 10000), (200000, 100000, 23000), (5000, 5000, 1000)]:
        r = engine.evaluate(280, 285, 300, 10, 285-demand/40000)
        assert r["simulated_cooling_capacity_kW"]*1000 == pytest.approx(expected_cooling)
        assert r["simulated_power_kW"]*1000 == pytest.approx(expected_power, rel=2e-8)
        assert r["QCon_flow_W"] == pytest.approx(-r["QEva_flow_W"]+.9*r["simulated_power_kW"]*1000)
    off = engine.evaluate(280, 285, 300, 10, 278, False)
    assert all(value == 0 for value in off.values())


def test_steady_and_dynamic_thermal_balance_with_known_solution():
    engine = ElectricEIR(ideal_per(), cp=4000)
    frame = pd.DataFrame([dict(TEI_K=285., TCI_K=300., evap_flow_kg_s=10., cond_flow_kg_s=20.,
                               TSet_K=283.75, operating_status=1, elapsed_s=t) for t in (0, 60, 6000)])
    steady = engine.simulate(frame, mode="steady")
    assert steady.simulated_TEO_C.iloc[-1]+273.15 == pytest.approx(283.75)
    assert steady.simulated_TCO_C.iloc[-1]+273.15 == pytest.approx(300.75)
    assert steady.evap_storage_kW.abs().max() < 1e-7
    assert steady.cond_storage_kW.abs().max() < 1e-7
    dynamic = engine.simulate(frame, initial_teo_K=280, initial_tco_K=298)
    expected = 283.75 + (280-283.75)*np.exp(-10*60/(engine.per.mEva_flow_nominal*30))
    assert dynamic.simulated_TEO_C.iloc[1]+273.15 == pytest.approx(expected, abs=1e-5)
    assert dynamic.simulated_TEO_C.iloc[-1] == pytest.approx(steady.simulated_TEO_C.iloc[-1], abs=1e-5)


def payload(records=None, **settings):
    records = records or [{"TEI_K": 13.89, "TCI_K": 26.67, "evap_flow_kg_s": 10.35, "cond_flow_kg_s": 19.24}]
    return {"operation": "simulate", "records": records,
            "schema": {"column_map": {k:k for k in records[0]}, "temperature_unit":"C", "water_specific_heat_J_kgK":4184},
            "simulation": {"setpoint":8.89,"duration_s":120,"interval_s":60, **settings}}


def test_api_without_power_or_outlet_measurements_and_catalogue():
    data = client.get("/workbench/eir/catalogue").json()
    assert len(data["records"]) == 158
    assert all(r["condenser_medium"] == "water" for r in data["records"])
    for r in data["records"]:
        performance(r["id"])
    response = client.post("/model/electric-eir/simulate", json=payload(mode="steady"))
    assert response.status_code == 200, response.text
    result = response.json()
    row = result["records"][-1]
    assert row["simulated_TEO_C"] == pytest.approx(8.89, abs=1e-6)
    assert row["simulated_power_kW"] > 0
    assert row["power_kW"] is None
    assert row["COP"] is None
    assert result["metadata"]["performance_record"] == DEFAULT_RECORD


def test_measurements_do_not_drive_eir_states_and_power():
    original = payload()
    a = client.post("/workbench/run", json=original).json()
    b = payload([dict(original["records"][0], P_W=999999, TEO_K=20, TCO_K=45)])
    b = client.post("/workbench/run", json=b).json()
    for x,y in zip(a["records"],b["records"]):
        for key in ("simulated_TEO_C", "simulated_TCO_C", "simulated_power_kW"):
            assert x[key] == y[key]


def test_series_controls_previous_hold_and_run_reset():
    base = payload()["records"][0]
    records = [dict(base, timestamp=t, run_id=run, TSet_K=8.89, operating_status=on)
               for run,t,on in [("a",0,1),("a",60,0),("a",120,0),("b",0,1),("b",60,1)]]
    response = client.post("/workbench/run",json=payload(records, kind="series",time_mode="seconds"))
    assert response.status_code == 200, response.text
    rows = response.json()["records"]
    assert rows[0]["simulated_TEO_C"] == pytest.approx(5)
    assert rows[1]["simulated_power_kW"] == 0
    assert rows[2]["simulated_TEO_C"] > rows[1]["simulated_TEO_C"]
    assert rows[3]["simulated_TEO_C"] == rows[0]["simulated_TEO_C"]
    assert rows[4]["simulated_TEO_C"] == rows[1]["simulated_TEO_C"]


@pytest.mark.parametrize("change", [{"TSet_K":None},{"TSet_K":"bad"},{"operating_status":2},{"operating_status":"on"},{"evap_flow_kg_s":0}])
def test_invalid_control_column_not_replaced_by_default(change):
    record = dict(payload()["records"][0],TSet_K=8.89,operating_status=1,**{})
    record.update(change)
    response = client.post("/workbench/run",json=payload([record]))
    assert response.status_code == 422


def test_custom_parameters_and_out_of_range_warning():
    response = client.post("/workbench/run",json=payload([dict(payload()["records"][0], TCI_K=40)], performance=ideal_per().model_dump(), mode="steady",setpoint=2))
    assert response.status_code == 200,response.text
    assert response.json()["metadata"]["performance_record"] == "custom"
    assert any("外推" in w["message"] for w in response.json()["warnings"])
    bad = payload(performance={**ideal_per().model_dump(), "PLRMin":1.5})
    assert client.post("/workbench/run",json=bad).status_code == 422


def test_control_units_fahrenheit_match_kelvin_and_steady_ignores_initial():
    base = payload(mode="steady", initial_teo=999, initial_tco=-999)
    base["records"][0]["TSet_K"] = 8.89
    base["schema"]["column_map"]["TSet_K"] = "TSet_K"
    expected = client.post("/workbench/run",json=base)
    assert expected.status_code == 200, expected.text
    base["schema"]["temperature_unit"] = "F"
    for field in ("TEI_K","TCI_K","TSet_K"):
        base["records"][0][field] = base["records"][0][field]*1.8+32
    actual = client.post("/workbench/run",json=base)
    assert actual.status_code == 200, actual.text
    for field in ("simulated_TEO_C","simulated_TCO_C","simulated_power_kW"):
        assert actual.json()["records"][-1][field] == pytest.approx(expected.json()["records"][-1][field])


def test_model_registry_lists_only_electric_eir_and_removed_routes_are_unavailable():
    assert client.get("/model/definition").json()["name"] == "buildings_electric_eir"
    assert [m["name"] for m in client.get("/models").json()["models"]] == ["buildings_electric_eir"]
    paths = client.get("/openapi.json").json()["paths"]
    for route in ("/model/simulate", "/model/calibrate"):
        assert route not in paths
        assert client.post(route, json={}).status_code == 404
    assert "/model/electric-eir/simulate" in paths
    assert "/model/electric-eir/calibrate" in paths


@pytest.mark.parametrize("settings", [
    {"engine": "legacy_greybox"},
    {"C_evap_J_K": 2e7},
    {"C_cond_J_K": 2e7},
    {"capacity_to_power_ratio": 4},
])
def test_removed_simulation_engine_and_parameters_are_rejected(settings):
    for route in ("/workbench/run", "/model/electric-eir/simulate"):
        response = client.post(route, json=payload(**settings))
        assert response.status_code == 422, response.text


def test_web_page_and_script_expose_only_current_simulation_model():
    page = client.get("/").text
    script = client.get("/static/app.js").text
    assert "ElectricEIR" in page
    for obsolete in ("legacy_greybox", "legacy-settings", "capacity_to_power_ratio", "sim-engine"):
        assert obsolete not in page
        assert obsolete not in script


def test_data_validation_uses_eir_inputs_without_measured_power_or_outlets():
    request = payload()
    request["records"][0]["TSet_K"] = 8.89
    request["schema"]["column_map"]["TSet_K"] = "TSet_K"
    response = client.post("/data/validate", json={
        "records": request["records"], "schema": request["schema"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["missing_for_dynamic_simulation"] == []
    request["records"][0].pop("TSet_K")
    request["schema"]["column_map"].pop("TSet_K")
    response = client.post("/data/validate", json={
        "records": request["records"], "schema": request["schema"],
    })
    assert response.json()["missing_for_dynamic_simulation"] == ["TSet_K"]


def test_single_power_scale_calibration_scales_power_without_changing_evaporator_balance():
    per = ideal_per()
    calibrated = calibrated_performance(per, 1.25)
    engine, cal_engine = ElectricEIR(per, cp=4000), ElectricEIR(calibrated, cp=4000)
    args = (280., 285., 300., 10., 283.75)
    a, b = engine.evaluate(*args), cal_engine.evaluate(*args)
    assert b["simulated_power_kW"] == pytest.approx(a["simulated_power_kW"] * 1.25)
    assert b["QEva_flow_W"] == pytest.approx(a["QEva_flow_W"])


def test_eir_calibration_api_requires_declared_health_and_steady_data():
    records = [dict(TEI_K=13.89, TCI_K=26.67, evap_flow_kg_s=10.35, cond_flow_kg_s=19.24,
                    TSet_K=8.89, operating_status=1, P_W=p) for p in (39000, 40000, 41000)]
    body = {"records": records, "schema": {"column_map": {k:k for k in records[0]},
            "temperature_unit":"C", "flow_unit":"kg/s", "power_unit":"W"}}
    denied = client.post("/model/electric-eir/calibrate", json=body)
    assert denied.status_code == 422
    body.update(healthy_training_confirmed=True, steady_state_confirmed=True)
    accepted = client.post("/model/electric-eir/calibrate", json=body)
    assert accepted.status_code == 200, accepted.text
    report = accepted.json()
    assert report["power_scale"] > 0
    assert report["training_after_kW"]["mae"] < report["training_before_kW"]["mae"]
