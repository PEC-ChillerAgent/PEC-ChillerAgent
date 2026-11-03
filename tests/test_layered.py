import numpy as np
import pandas as pd

from chiller_app.data.pipeline import engineer_features, standardize_frame
from chiller_app.data.schema import DataSchema, apply_schema
from chiller_app.diagnosis.rules import diagnose_frame
from chiller_app.model.physics_model import calculate_heat_balance


def test_standardize_ashrae_temperature_and_power_units():
    source = pd.DataFrame({"TEI": [60.68], "TEO": [50.68], "TCI": [85.49], "TCO": [94.95], "kW": [82.55]})
    result = standardize_frame(source, temperature_unit="auto", power_unit="auto")
    assert np.isclose(result.loc[0, "TEI_K"], 289.083333, atol=1e-5)
    assert np.isclose(result.loc[0, "P_W"], 82550.0)


def test_heat_balance_with_flow():
    record = {
        "TEI_K": 289.15,
        "TEO_K": 283.15,
        "TCI_K": 300.15,
        "TCO_K": 305.15,
        "evap_flow_kg_s": 20.0,
        "cond_flow_kg_s": 25.0,
        "P_W": 50000.0,
    }
    result = calculate_heat_balance(record)
    assert np.isclose(result["cooling_capacity_kW"], 501.6)
    assert result["COP"] > 0


def test_diagnosis_flags_bad_temperature_direction():
    frame = pd.DataFrame({"delta_evap_K": [-1.0], "delta_cond_K": [5.0]})
    result = diagnose_frame(frame)
    assert result["warnings"]


def test_explicit_schema_accepts_arbitrary_headers_and_units():
    source = pd.DataFrame({
        "time": ["2026-01-01T00:00:00"],
        "chilled_in": [10.0],
        "chilled_out": [5.0],
        "condenser_in": [30.0],
        "condenser_out": [35.0],
        "chilled_flow": [72.0],
        "condenser_flow": [90.0],
        "power": [100.0],
    })
    schema = DataSchema(
        column_map={
            "timestamp": "time", "TEI_K": "chilled_in", "TEO_K": "chilled_out",
            "TCI_K": "condenser_in", "TCO_K": "condenser_out",
            "evap_flow_kg_s": "chilled_flow", "cond_flow_kg_s": "condenser_flow",
            "P_W": "power",
        },
        temperature_unit="C", flow_unit="m3/h", power_unit="kW",
    )
    result = apply_schema(source, schema)
    assert np.isclose(result.loc[0, "TEI_K"], 283.15)
    assert np.isclose(result.loc[0, "evap_flow_kg_s"], 20.0)
    assert np.isclose(result.loc[0, "P_W"], 100000.0)
