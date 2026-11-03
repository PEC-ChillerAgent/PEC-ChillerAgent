"""One identifiable steady-state power correction; no curve or flow fitting."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .electric_eir import EIRPerformance, ElectricEIR


def error_metrics(actual, predicted) -> dict:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics require matching finite observations and predictions")
    if not actual.size:
        raise ValueError("Metrics require at least one observation")
    error = predicted - actual
    return {"n": int(actual.size), "mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error**2))), "bias": float(np.mean(error)),
            "mape_pct": float(100 * np.mean(np.abs(error / actual))) if (actual > 0).all() else None}


def calibrated_performance(per: EIRPerformance, power_scale: float) -> EIRPerformance:
    if not np.isfinite(power_scale) or power_scale <= 0:
        raise ValueError("power_scale must be finite and positive")
    values = per.model_dump()
    values["COP_nominal"] /= power_scale
    return EIRPerformance.model_validate(values)


def fit_power_scale(frame: pd.DataFrame, per: EIRPerformance, *, cp: float = 4184,
                    bounds: tuple[float, float] = (.25, 4.0),
                    allow_extrapolation: bool = False) -> dict:
    """Fit s in P_measured=s*P_reference. Caller supplies health-only training data.

    In this EIR cooling branch steady evaporator temperature does not depend on
    COP_nominal. Changing COP_nominal to COP_nominal/s scales P consistently and
    also updates condenser heat/temperature; never just edit an output column.
    """
    if len(frame) < 3 or "P_W" not in frame:
        raise ValueError("At least three healthy steady observations with measured P_W are required")
    y = pd.to_numeric(frame.P_W, errors="coerce").to_numpy(dtype=float) / 1000
    if not np.isfinite(y).all() or (y <= 0).any():
        raise ValueError("Calibration requires finite positive measured power")
    lo, hi = bounds
    if not np.isfinite([lo, hi]).all() or not 0 < lo < hi:
        raise ValueError("Invalid power scale bounds")
    base = ElectricEIR(per, cp).simulate(frame, mode="steady")
    x = base.simulated_power_kW.to_numpy()
    if not np.isfinite(x).all() or (x <= 0).any():
        raise ValueError("Calibration requires positive reference power in every row")
    out = int(base.curve_out_of_range.sum())
    if out and not allow_extrapolation:
        raise ValueError("Training conditions outside reference curve range; explicitly permit extrapolation or choose a supported record")
    unconstrained = float(x @ y / (x @ x))
    scale = float(np.clip(unconstrained, lo, hi))
    corrected = calibrated_performance(per, scale)
    prediction = ElectricEIR(corrected, cp).simulate(frame, mode="steady")
    return {"method": "bounded one-parameter least squares, no intercept",
            "power_scale": scale, "unconstrained_power_scale": unconstrained,
            "bounds": list(bounds), "at_bound": bool(scale in bounds),
            "rows": len(frame), "extrapolated_training_rows": out,
            "training_before_kW": error_metrics(y, x),
            "training_after_kW": error_metrics(y, prediction.simulated_power_kW),
            "performance_parameters": corrected.model_dump(),
            "meaning": "effective power correction, COP_nominal divided by scale; not independently identified actual nominal COP",
            "limitations": ["Health status and steady-state suitability are supplied by caller, not inferred",
                            "Training fit is not independent validation; use separate files",
                            "Power calibration cannot repair capacity curve or operating range mismatch"]}
