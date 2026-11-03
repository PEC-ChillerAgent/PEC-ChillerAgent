"""Steady-state performance model with physically meaningful targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split


PERFORMANCE_FEATURES = [
    "TEI_K",
    "TCI_K",
    "TCO_K",
    "evap_flow_kg_s",
    "cond_flow_kg_s",
    "compressor_frequency_Hz",
    "ambient_dry_K",
]
PERFORMANCE_TARGETS = [
    "cooling_capacity_kW",
    "P_W",
    "TEO_K",
    "COP",
]


@dataclass
class PerformanceTrainingResult:
    model_path: str
    report: Dict[str, Any]


def _available_features(frame: pd.DataFrame) -> list[str]:
    available = [column for column in PERFORMANCE_FEATURES if column in frame]
    if len(available) < 3:
        raise ValueError("Performance model needs at least TEI_K, TCI_K and TCO_K.")
    return available


def _available_targets(frame: pd.DataFrame) -> list[str]:
    return [column for column in PERFORMANCE_TARGETS if column in frame and frame[column].notna().any()]


def train_performance_model(
    frame: pd.DataFrame,
    model_path: str | Path,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
) -> PerformanceTrainingResult:
    """Train one regressor per available steady-state output."""

    features = _available_features(frame)
    targets = _available_targets(frame)
    if not targets:
        raise ValueError("No performance targets are available. Provide power, flow or outlet temperature data.")
    complete = frame.dropna(subset=features + targets).reset_index(drop=True)
    if len(complete) < 20:
        raise ValueError("At least 20 complete rows are required for performance training.")
    train_idx, test_idx = train_test_split(
        np.arange(len(complete)), test_size=test_size, random_state=random_state
    )
    models: Dict[str, RandomForestRegressor] = {}
    metrics: Dict[str, Dict[str, float]] = {}
    for target in targets:
        model = RandomForestRegressor(
            n_estimators=300, min_samples_leaf=2, random_state=random_state, n_jobs=1
        )
        model.fit(complete.loc[train_idx, features], complete.loc[train_idx, target])
        prediction = model.predict(complete.loc[test_idx, features])
        actual = complete.loc[test_idx, target]
        metrics[target] = {
            "mae": float(mean_absolute_error(actual, prediction)),
            "rmse": float(np.sqrt(mean_squared_error(actual, prediction))),
            "r2": float(r2_score(actual, prediction)) if actual.nunique() > 1 else float("nan"),
        }
        models[target] = model
    report = {
        "rows": int(len(complete)),
        "features": features,
        "targets": targets,
        "metrics": metrics,
        "test_size": test_size,
        "random_state": random_state,
        "limitations": [
            "Statistical steady-state baseline; no transient states or control optimization are inferred.",
            "Cooling capacity and COP require flow and power measurements.",
        ],
    }
    bundle = {"models": models, "feature_columns": features, "targets": targets, "report": report}
    destination = Path(model_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, destination)
    return PerformanceTrainingResult(str(destination), report)


def predict_performance(frame: pd.DataFrame, bundle: Mapping[str, Any]) -> pd.DataFrame:
    features = list(bundle["feature_columns"])
    missing = [column for column in features if column not in frame]
    if missing:
        raise ValueError(f"Performance prediction is missing features: {missing}")
    result = frame.copy()
    valid = frame[features].notna().all(axis=1)
    for target, model in bundle["models"].items():
        result.loc[valid, f"predicted_{target}"] = model.predict(frame.loc[valid, features])
    if "predicted_cooling_capacity_kW" in result and "predicted_P_W" in result:
        result["predicted_COP"] = result["predicted_cooling_capacity_kW"] / (result["predicted_P_W"] / 1000.0).replace(0, np.nan)
    return result
