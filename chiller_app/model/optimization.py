"""Constrained operating-point optimization prototype.

This module deliberately returns a recommendation, not a control command. It
can only optimize variables represented by the trained performance model and
bounded by the caller. A real plant controller must add actuator limits,
interlocks, ramp rates and a closed-loop safety layer.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def optimize_power(
    performance_bundle: Mapping[str, Any],
    base_input: Mapping[str, float],
    bounds: Mapping[str, tuple[float, float]],
    *,
    outlet_target_K: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Minimize predicted power subject to a predicted outlet-temperature band."""

    features = list(performance_bundle["feature_columns"])
    control_features = {
        "compressor_frequency_Hz",
        "valve_opening_pct",
        "evap_flow_kg_s",
        "cond_flow_kg_s",
    }
    variable_names = [
        name for name in features
        if name in control_features and name in bounds and name in base_input
    ]
    if not variable_names:
        raise ValueError(
            "No optimizable control feature has both a base value and bounds. "
            "Do not optimize measured temperatures directly; train with frequency, valve or flow controls."
        )
    x0 = np.array([float(base_input[name]) for name in variable_names], dtype=float)
    limits = [bounds[name] for name in variable_names]

    def row_from_x(x: Sequence[float]) -> pd.DataFrame:
        row = dict(base_input)
        row.update({name: float(value) for name, value in zip(variable_names, x)})
        return pd.DataFrame([row])

    def predict(x: Sequence[float]) -> dict[str, float]:
        row = row_from_x(x)
        values: dict[str, float] = {}
        for target, model in performance_bundle["models"].items():
            values[target] = float(model.predict(row[features])[0])
        return values

    def objective(x: Sequence[float]) -> float:
        prediction = predict(x)
        return prediction.get("P_W", np.inf)

    constraints = []
    if outlet_target_K is not None and "TEO_K" in performance_bundle["models"]:
        lower, upper = outlet_target_K
        constraints.append({"type": "ineq", "fun": lambda x: predict(x)["TEO_K"] - lower})
        constraints.append({"type": "ineq", "fun": lambda x: upper - predict(x)["TEO_K"]})
    result = minimize(objective, x0, method="SLSQP", bounds=limits, constraints=constraints)
    optimal_input = dict(base_input)
    optimal_input.update({name: float(value) for name, value in zip(variable_names, result.x)})
    prediction = predict(result.x)
    return {
        "success": bool(result.success),
        "message": str(result.message),
        "optimized_features": optimal_input,
        "prediction": prediction,
        "baseline_prediction": predict(x0),
        "power_reduction_W": float(predict(x0).get("P_W", np.nan) - prediction.get("P_W", np.nan)),
        "variables": variable_names,
        "bounds": {name: list(bounds[name]) for name in variable_names},
        "safety_note": "Recommendation only. Validate actuator limits, interlocks and plant response before implementation.",
    }
