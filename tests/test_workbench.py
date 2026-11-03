from io import BytesIO

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest

from chiller_app.api.fastapi_app import app
from chiller_app.api.workbench import WorkbenchRequest, run_workbench
from chiller_app.data.schema import DataSchema, apply_schema
from chiller_app.model.electric_eir import DEFAULT_RECORD

client = TestClient(app)


def test_unsupported_upload_returns_validation_error():
    response = client.post("/workbench/upload", files={"file": ("manual.txt", b"temperature,power\n10,100")})
    assert response.status_code == 422
    assert "CSV" in response.json()["detail"]


def test_excel_upload_lists_sheets_and_reads_selected_sheet():
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"TEI": [60], "FWE": [100]}).to_excel(writer, sheet_name="Complete", index=False)
        pd.DataFrame({"TEI": [61], "FWE": [101]}).to_excel(writer, sheet_name="Steady States", index=False)
    content = buffer.getvalue()
    default = client.post("/workbench/upload", files={"file": ("normal1.xlsx", content)})
    selected = client.post("/workbench/upload?sheet_name=Steady%20States", files={"file": ("normal1.xlsx", content)})
    assert default.status_code == selected.status_code == 200
    assert default.json()["sheets"] == ["Complete", "Steady States"]
    assert default.json()["selected_sheet"] == "Complete"
    assert selected.json()["selected_sheet"] == "Steady States"
    assert selected.json()["records"][0]["TEI"] == 61


def test_explicit_us_gpm_conversion_and_ashrae_dynamic_inputs():
    schema = DataSchema(column_map={"evap_flow_kg_s": "FWE", "cond_flow_kg_s": "FWC"},
                        flow_unit="us_gpm", water_density_kg_m3=995.586)
    converted = apply_schema(pd.DataFrame({"FWE": [100], "FWC": [200]}), schema)
    assert converted.evap_flow_kg_s.iloc[0] == pytest.approx(100 * 3.785411784e-3 * 995.586 / 60)
    assert converted.cond_flow_kg_s.iloc[0] == pytest.approx(200 * 3.785411784e-3 * 995.586 / 60)

    records = [{"Time": 0, "TEI": 60, "TCI": 85, "FWE": 100, "FWC": 200, "TWE_set": 44, "Unit Status": 1},
               {"Time": 10, "TEI": 60, "TCI": 85, "FWE": 100, "FWC": 200, "TWE_set": 44, "Unit Status": 1}]
    response = client.post("/workbench/run", json={
        "operation": "simulate", "records": records,
        "schema": {"column_map": {"timestamp": "Time", "TEI_K": "TEI", "TCI_K": "TCI",
                                    "evap_flow_kg_s": "FWE", "cond_flow_kg_s": "FWC",
                                    "TSet_K": "TWE_set", "operating_status": "Unit Status"},
                   "temperature_unit": "F", "flow_unit": "us_gpm", "power_unit": "kW",
                   "water_density_kg_m3": 995.586},
        "simulation": {"engine": "electric_eir", "kind": "series", "time_mode": "seconds",
                       "mode": "dynamic", "record_id": DEFAULT_RECORD},
    })
    assert response.status_code == 200, response.text
    assert response.json()["records"][0]["evap_flow_kg_s"] == pytest.approx(converted.evap_flow_kg_s.iloc[0])


def test_ashrae_headers_are_recovered_when_frontend_omits_flow_mapping():
    records = [{"Time": 10, "TEI": 60, "TCI": 85, "FWE": 100, "FWC": 200, "TWE_set": 44, "kW": 45},
               {"Time": 20, "TEI": 60, "TCI": 85, "FWE": 100, "FWC": 200, "TWE_set": 44, "kW": 45}]
    response = client.post("/workbench/run", json={
        "operation": "simulate", "records": records,
        "schema": {"column_map": {}, "temperature_unit": "C", "flow_unit": "m3/h", "power_unit": "W"},
        "simulation": {"engine": "electric_eir", "kind": "series", "time_mode": "interval",
                       "setpoint": 44},
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["metadata"]["schema"]["flow_unit"] == "us_gpm"
    assert payload["metadata"]["schema"]["temperature_unit"] == "F"
    assert payload["metadata"]["input_inference"]["auto_mapped_columns"]["evap_flow_kg_s"] == "FWE"
    assert [row["elapsed_s"] for row in payload["records"]] == [0, 10]


def test_ashrae_headers_with_parenthesized_units_are_recovered():
    records = [
        {"Time (seconds)": 0, "TEI (°F)": 60, "TCI (°F)": 85,
         "FWE (gpm)": 100, "FWC (US gpm)": 200, "TWE_set": 44},
        {"Time (seconds)": 10, "TEI (°F)": 60, "TCI (°F)": 85,
         "FWE (gpm)": 100, "FWC (US gpm)": 200, "TWE_set": 44},
    ]
    response = client.post("/workbench/run", json={
        "operation": "simulate", "records": records,
        "schema": {"column_map": {}, "temperature_unit": "C", "flow_unit": "m3/h", "power_unit": "W"},
        "simulation": {"engine": "electric_eir", "kind": "series", "time_mode": "interval"},
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    schema = payload["metadata"]["schema"]
    inference = payload["metadata"]["input_inference"]
    assert schema["temperature_unit"] == "F"
    assert schema["flow_unit"] == "us_gpm"
    assert inference["auto_mapped_columns"]["evap_flow_kg_s"] == "FWE (gpm)"
    assert inference["auto_mapped_columns"]["cond_flow_kg_s"] == "FWC (US gpm)"
    assert payload["records"][0]["evap_flow_kg_s"] == pytest.approx(
        100 * 3.785411784e-3 * 995.586 / 60
    )
    assert [row["elapsed_s"] for row in payload["records"]] == [0, 10]


@pytest.mark.parametrize("status", [-1, 2, 6, 0.5])
def test_calculation_marks_nonbinary_status_as_invalid(status):
    response = client.post("/workbench/run", json={
        "operation": "calculate",
        "records": [{"status": status}],
        "schema": {"column_map": {"operating_status": "status"}},
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["records"][0]["operating_status"] is None
    assert any(issue["field"] == "operating_status" for issue in result["issues"])
BASE = {"TEI_K": 10, "TEO_K": 5, "TCI_K": 30, "TCO_K": 35,
        "evap_flow_kg_s": 72, "cond_flow_kg_s": 90, "P_W": 100}


def request(records=None, operation="calculate", **simulation):
    simulation.setdefault("engine", "electric_eir")
    simulation.setdefault("setpoint", 5)
    records = records if records is not None else [BASE.copy()]
    return {"records": records, "operation": operation,
            "schema": {"column_map": {k: k for k in records[0]}, "temperature_unit": "C", "flow_unit": "m3/h", "power_unit": "kW", "water_specific_heat_J_kgK":4180, "water_density_kg_m3":1000},
            "simulation": simulation}


def test_page_and_assets():
    assert client.get("/").status_code == 200
    assert "单条工况" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/upload-review.css").status_code == 200


def test_manual_physics_and_partial_observations():
    response = client.post("/workbench/run", json=request())
    assert response.status_code == 200, response.text
    row = response.json()["records"][0]
    assert row["cooling_capacity_kW"] == pytest.approx(418)
    assert row["condenser_heat_kW"] == pytest.approx(522.5)
    assert row["COP"] == pytest.approx(4.18)
    assert row["energy_balance_error_kW"] == pytest.approx(4.5)
    assert row["evap_flow_kg_s"] == pytest.approx(20)
    partial = request([{"TEI_K": 10, "TEO_K": 5, "P_W": 100}])
    row = client.post("/workbench/run", json=partial).json()["records"][0]
    assert row["cooling_capacity_kW"] is None
    assert row["COP"] is None
    assert row["power_kW"] == 100


def test_dynamic_simulation_preserves_explicit_initial_state_and_converges():
    payload = request(operation="simulate", duration_s=6000, interval_s=600,
                      initial_teo=6, initial_tco=34)
    response = client.post("/workbench/run", json=payload)
    assert response.status_code == 200, response.text
    rows = response.json()["records"]
    assert rows[0]["simulated_TEO_C"] == pytest.approx(6)
    assert rows[0]["simulated_TCO_C"] == pytest.approx(34)
    steady = client.post("/workbench/run", json=request(operation="simulate", mode="steady"))
    assert steady.status_code == 200, steady.text
    final = steady.json()["records"][-1]
    for field in ("simulated_TEO_C", "simulated_TCO_C", "simulated_power_kW"):
        assert rows[-1][field] == pytest.approx(final[field], abs=1e-4)
    assert rows[-1]["evap_storage_kW"] == pytest.approx(0, abs=1e-5)


def test_time_series_resets_runs_without_using_measured_outlets_as_initial_state():
    records = [dict(BASE, timestamp=t, run_id="a") for t in (1000, 1060, 1120)]
    records += [dict(BASE, timestamp=0, run_id="b", TEO_K=7), dict(BASE, timestamp=60, run_id="b")]
    response = client.post("/workbench/run", json=request(records, "simulate", kind="series", time_mode="seconds"))
    assert response.status_code == 200, response.text
    rows = response.json()["records"]
    assert [r["elapsed_s"] for r in rows] == [0, 60, 120, 0, 60]
    assert rows[0]["simulated_TEO_C"] == pytest.approx(5)
    assert rows[3]["simulated_TEO_C"] == rows[0]["simulated_TEO_C"]
    assert rows[4]["simulated_TEO_C"] == rows[1]["simulated_TEO_C"]


def test_numeric_minute_time_column_converts_to_elapsed_seconds():
    records = [dict(BASE, timestamp=value) for value in [2, 3]]
    payload = request(records, "simulate", kind="series", time_mode="minutes")
    response = client.post("/workbench/run", json=payload)
    assert response.status_code == 200, response.text
    assert [row["elapsed_s"] for row in response.json()["records"]] == [0, 60]


@pytest.mark.parametrize("time_mode,times", [("seconds", [0, 0]), ("seconds", [10, 5]), ("datetime", ["bad", "bad"])])
def test_invalid_times_rejected(time_mode, times):
    records = [dict(BASE, timestamp=t) for t in times]
    response = client.post("/workbench/run", json=request(records, "simulate", kind="series", time_mode=time_mode))
    assert response.status_code == 422


def test_datetime_and_missing_outlets():
    record = {k: v for k, v in BASE.items() if k not in {"TEO_K", "TCO_K"}}
    records = [dict(record, timestamp=t) for t in ["2026-01-01T00:00:00", "2026-01-01T00:01:00"]]
    response = client.post("/workbench/run", json=request(records, "simulate", kind="series", time_mode="datetime"))
    assert response.status_code == 200, response.text
    rows = response.json()["records"]
    assert rows[1]["elapsed_s"] == 60
    assert rows[0]["simulated_TEO_C"] == pytest.approx(5)
    assert rows[0]["TEO_C"] is None


def test_bad_input_and_zero_flow():
    for change in ({"evap_flow_kg_s": 0}, {"cond_flow_kg_s": 0}, {"TEI_K": "bad"}):
        response = client.post("/workbench/run", json=request([dict(BASE, **change)], "simulate"))
        assert response.status_code == 422
    response = client.post("/workbench/run", json=request([dict(BASE, TEI_K="bad")]))
    assert response.status_code == 200
    assert response.json()["issues"][0]["row"] == 1
    assert response.json()["records"][0]["cooling_capacity_kW"] is None


def test_simulation_missing_input_error_identifies_unmapped_signals():
    records = [{"inlet_e": 10, "inlet_c": 30, "flow_e": 50, "flow_c": 60}]
    response = client.post("/workbench/run", json={
        "operation": "simulate", "records": records,
        "schema": {"column_map": {"TEI_K": "inlet_e", "TCI_K": "inlet_c"}, "temperature_unit": "C"},
        "simulation": {"engine": "electric_eir", "kind": "series", "setpoint": 5},
    })
    assert response.status_code == 422
    assert "冷冻水流量（尚未映射来源列）" in response.json()["detail"]
    assert "冷却水流量（尚未映射来源列）" in response.json()["detail"]


@pytest.mark.parametrize("extension,encoding", [("csv", "utf-8-sig"), ("csv", "gb18030"), ("xlsx", None)])
def test_upload_and_run(extension, encoding):
    frame = pd.DataFrame({"冷冻水进水温度": [10], "冷冻水出水温度": [5], "冷冻水流量": [72], "机组功率": [100]})
    if extension == "csv":
        content = frame.to_csv(index=False).encode(encoding)
    else:
        buffer = BytesIO()
        frame.to_excel(buffer, index=False)
        content = buffer.getvalue()
    response = client.post("/workbench/upload", files={"file": ("test."+extension, content)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["row_count"] == 1
    payload = {"records": data["records"], "schema": {"column_map": {"TEI_K": "冷冻水进水温度", "TEO_K": "冷冻水出水温度", "evap_flow_kg_s": "冷冻水流量", "P_W": "机组功率"}, "temperature_unit": "C", "flow_unit": "m3/h", "power_unit": "kW", "water_specific_heat_J_kgK":4180, "water_density_kg_m3":1000}}
    result = client.post("/workbench/run", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["records"][0]["COP"] == pytest.approx(4.18)


def test_explicit_mapping_ignores_unselected_flow_alias():
    schema = DataSchema(column_map={"evap_flow_kg_s": "myflow"})
    result = apply_schema(pd.DataFrame({"myflow": [20], "evap_flow_m3_h": [9999]}), schema)
    assert result.evap_flow_kg_s.iloc[0] == 20


def test_duration_endpoint_and_explicit_initial_units():
    payload = request(operation="simulate", duration_s=125, interval_s=60, initial_teo=6, initial_tco=34)
    rows = run_workbench(WorkbenchRequest.model_validate(payload))["records"]
    assert [row["elapsed_s"] for row in rows] == [0, 60, 120, 125]
    assert rows[0]["simulated_TEO_C"] == pytest.approx(6)


def test_temperature_reference_warning_counts_points_and_reports_ranges():
    payload = request(operation="simulate", duration_s=120, interval_s=60, initial_teo=-3)
    response = client.post("/workbench/run", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    expected = sum(r["simulated_TEO_C"] < 0 or r["simulated_TCO_C"] > 60 for r in result["records"])
    warning = next(w for w in result["warnings"] if "temperature_ranges_C" in w)
    assert warning["count"] == expected
    assert warning["temperature_ranges_C"]["TEO_min"] == pytest.approx(-3)
    assert result["metadata"]["temperature_reference_checks_C"]["simulated_TCO_C_max"] == 60
