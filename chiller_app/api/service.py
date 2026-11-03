"""Application service layer shared by FastAPI, CLI and other front ends.

The service deliberately works on canonical records.  A source system may use
any language or header names, but it must either provide an explicit
``DataSchema`` or use the conservative alias-based adapter in ``pipeline``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from chiller_app.data.pipeline import clean_measurements, engineer_features, standardize_frame
from chiller_app.data.schema import DataSchema, apply_schema
from chiller_app.diagnosis.rules import diagnose_frame
from chiller_app.model.model_definition import default_model_definition
from chiller_app.model.physics_model import calculate_heat_balance_frame
from chiller_app.model.performance_model import predict_performance, train_performance_model
from chiller_app.model.optimization import optimize_power


def standardize_records(
    records: list[Mapping[str, Any]],
    *,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> pd.DataFrame:
    """Convert arbitrary source records into the internal SI schema."""

    source = pd.DataFrame(records)
    if source.empty:
        raise ValueError("records must contain at least one row")
    if schema is not None:
        return apply_schema(source, schema)
    return standardize_frame(
        source,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )


def prepare_records(
    records: list[Mapping[str, Any]],
    *,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    standardized = standardize_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    cleaned = clean_measurements(standardized)
    features = engineer_features(cleaned.frame)
    return features, cleaned.report


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value) if not isinstance(value, (dict, list, tuple)) else False:
        return None
    return value


def validate_records(
    records: list[Mapping[str, Any]],
    *,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> dict[str, Any]:
    """Return a non-destructive data contract report for a source."""

    source = pd.DataFrame(records)
    canonical = standardize_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    required_physics = ["TEI_K", "TEO_K", "TCI_K", "TCO_K"]
    required_dynamic = ["TEI_K", "TCI_K", "evap_flow_kg_s", "cond_flow_kg_s", "TSet_K"]
    return _json_ready({
        "rows": int(len(source)),
        "source_columns": [str(column) for column in source.columns],
        "canonical_columns": [str(column) for column in canonical.columns],
        "missing_for_physics": [column for column in required_physics if column not in canonical],
        "missing_for_dynamic_simulation": [column for column in required_dynamic if column not in canonical],
        "numeric_missing_values": {
            column: int(pd.to_numeric(canonical[column], errors="coerce").isna().sum())
            for column in canonical.columns
            if column not in {"timestamp", "run_id", "operating_status", "alarm_code", "label", "fault_name"}
        },
        "units_after_normalization": {"temperature": "K", "flow": "kg/s", "power": "W"},
        "schema_mode": "explicit" if schema is not None else "alias_adapter",
    })


def clean_records(
    records: list[Mapping[str, Any]],
    *,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> dict[str, Any]:
    """Return canonical cleaned records before any model is selected."""

    frame, report = prepare_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    return _json_ready({"cleaning": report, "rows": frame.to_dict("records")})


def analyze_records(
    records: list[Mapping[str, Any]],
    *,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> dict[str, Any]:
    """Normalize records, calculate physics and return operator-facing output."""

    features, cleaning_report = prepare_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    physics = calculate_heat_balance_frame(features)
    return _json_ready({
        "model_definition": default_model_definition(),
        "cleaning": cleaning_report,
        "rows": physics.to_dict("records"),
        "diagnosis": diagnose_frame(physics),
    })



def train_records(
    records: list[Mapping[str, Any]],
    *,
    model_path: str | Path,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> dict[str, Any]:
    frame, cleaning_report = prepare_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    result = train_performance_model(frame, model_path)
    return _json_ready({"model_path": result.model_path, "cleaning": cleaning_report, "report": result.report})


def predict_records(
    records: list[Mapping[str, Any]],
    *,
    model_path: str | Path,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> dict[str, Any]:
    frame, cleaning_report = prepare_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    bundle = joblib.load(model_path)
    predicted = predict_performance(frame, bundle)
    return _json_ready({
        "model_path": str(model_path),
        "feature_columns": list(bundle["feature_columns"]),
        "cleaning": cleaning_report,
        "rows": predicted.to_dict("records"),
    })


def validate_model_records(
    records: list[Mapping[str, Any]],
    *,
    model_path: str | Path,
    schema: DataSchema | None = None,
    temperature_unit: str = "K",
    flow_unit: str = "kg/s",
    power_unit: str = "W",
    pressure_unit: str = "Pa",
) -> dict[str, Any]:
    """Score a saved steady-state model on a separate dataset."""

    frame, cleaning_report = prepare_records(
        records,
        schema=schema,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
    )
    bundle = joblib.load(model_path)
    predicted = predict_performance(frame, bundle)
    metrics: dict[str, Any] = {}
    for measured, predicted_name in [
        ("P_W", "predicted_P_W"),
        ("TEO_K", "predicted_TEO_K"),
        ("cooling_capacity_kW", "predicted_cooling_capacity_kW"),
        ("COP", "predicted_COP"),
    ]:
        if measured not in predicted or predicted_name not in predicted:
            continue
        valid = predicted[[measured, predicted_name]].dropna()
        if valid.empty:
            continue
        error = valid[predicted_name] - valid[measured]
        metrics[measured] = {
            "rows": int(len(valid)),
            "mae": float(mean_absolute_error(valid[measured], valid[predicted_name])),
            "rmse": float(np.sqrt(mean_squared_error(valid[measured], valid[predicted_name]))),
            "r2": float(r2_score(valid[measured], valid[predicted_name])) if valid[measured].nunique() > 1 else None,
            "bias": float(error.mean()),
        }
    return _json_ready({
        "model_path": str(model_path),
        "feature_columns": list(bundle["feature_columns"]),
        "cleaning": cleaning_report,
        "metrics": metrics,
        "rows": predicted.to_dict("records"),
        "limitations": [] if metrics else ["No measured target columns were available for external scoring."],
    })


def optimize_records(
    *,
    model_path: str | Path,
    base_input: Mapping[str, float],
    bounds: Mapping[str, tuple[float, float]],
    outlet_target_K: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Return an offline constrained recommendation from a saved model."""

    bundle = joblib.load(model_path)
    result = optimize_power(bundle, base_input, bounds, outlet_target_K=outlet_target_K)
    return _json_ready({"model_path": str(model_path), **result})
