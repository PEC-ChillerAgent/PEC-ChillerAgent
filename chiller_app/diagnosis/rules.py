"""Explainable engineering checks used by the report and page."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def diagnose_frame(frame: pd.DataFrame) -> Dict[str, Any]:
    """Return rule-based warnings and summary statistics."""

    warnings: List[str] = []
    recommendations: List[str] = []
    if "delta_evap_K" in frame and (frame["delta_evap_K"] <= 0).any():
        warnings.append("冷冻水进出水温差方向异常，优先检查传感器、单位和水流方向。")
    if "delta_cond_K" in frame and (frame["delta_cond_K"] <= 0).any():
        warnings.append("冷却水进出水温差方向异常，优先检查传感器、单位和水流方向。")
    if "evap_flow_kg_s" in frame:
        low_flow = frame["evap_flow_kg_s"].notna() & (frame["evap_flow_kg_s"] <= 0)
        if low_flow.any():
            warnings.append("存在非正冷冻水流量，不能把对应冷量/COP作为有效结果。")
    if "COP" in frame:
        cop = frame["COP"].dropna()
        if len(cop) and (cop < 2.0).mean() > 0.1:
            warnings.append("超过 10% 的记录 COP 低于 2，建议检查负荷、流量、换热器和功率计量。")
            recommendations.append("检查冷凝器污堵、冷却水温度和压缩机运行点。")
    if "energy_balance_error_kW" in frame and "cooling_capacity_kW" in frame:
        valid = frame[["energy_balance_error_kW", "cooling_capacity_kW", "power_kW"]].dropna()
        if len(valid):
            relative = valid["energy_balance_error_kW"].abs() / (valid["cooling_capacity_kW"].abs() + valid["power_kW"].abs()).clip(lower=1e-6)
            if (relative > 0.1).mean() > 0.1:
                warnings.append("超过 10% 的记录能量平衡偏差大于 10%，请核查测点同步和流量口径。")
    summary = {}
    for column in ["cooling_capacity_kW", "power_kW", "COP", "energy_balance_error_kW"]:
        if column in frame and frame[column].notna().any():
            summary[column] = float(frame[column].mean())
    return {
        "warnings": warnings,
        "recommendations": recommendations,
        "summary_means": summary,
        "rows": int(len(frame)),
    }
