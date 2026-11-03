"""Measured water-side heat balance and efficiency calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import pandas as pd



@dataclass(frozen=True)
class PhysicsConstants:
    water_cp_J_kgK: float = 4180.0
    water_density_kg_m3: float = 1000.0


def _as_float(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)


def calculate_heat_balance(
    record: Mapping[str, Any],
    constants: PhysicsConstants = PhysicsConstants(),
) -> Dict[str, Optional[float]]:
    """Calculate Qe, Qc, COP and balance error from one canonical record."""

    required = ["TEI_K", "TEO_K", "TCI_K", "TCO_K"]
    missing = [field for field in required if _as_float(record.get(field)) is None]
    if missing:
        raise ValueError(f"Heat balance requires measurements: {missing}")

    tei = float(record["TEI_K"])
    teo = float(record["TEO_K"])
    tci = float(record["TCI_K"])
    tco = float(record["TCO_K"])
    evap_flow = _as_float(record.get("evap_flow_kg_s"))
    cond_flow = _as_float(record.get("cond_flow_kg_s"))
    power = _as_float(record.get("P_W"))
    delta_evap = tei - teo
    delta_cond = tco - tci
    result: Dict[str, Optional[float]] = {
        "delta_evap_K": delta_evap,
        "delta_cond_K": delta_cond,
        "temperature_lift_K": tco - teo,
        "cooling_capacity_kW": None,
        "condenser_heat_kW": None,
        "power_kW": power / 1000.0 if power is not None else None,
        "COP": None,
        "energy_balance_error_kW": None,
    }
    if evap_flow is not None:
        result["cooling_capacity_kW"] = evap_flow * constants.water_cp_J_kgK * delta_evap / 1000.0
    if cond_flow is not None:
        result["condenser_heat_kW"] = cond_flow * constants.water_cp_J_kgK * delta_cond / 1000.0
    if result["cooling_capacity_kW"] is not None and power is not None and power > 0:
        result["COP"] = result["cooling_capacity_kW"] / (power / 1000.0)
    if (
        result["cooling_capacity_kW"] is not None
        and result["condenser_heat_kW"] is not None
        and power is not None
    ):
        result["energy_balance_error_kW"] = (
            result["condenser_heat_kW"] - result["cooling_capacity_kW"] - power / 1000.0
        )
    return result


def calculate_heat_balance_frame(
    frame: pd.DataFrame,
    constants: PhysicsConstants = PhysicsConstants(),
) -> pd.DataFrame:
    """Apply heat-balance equations row by row and retain all inputs."""

    outputs = pd.DataFrame(
        [calculate_heat_balance(row, constants) for row in frame.to_dict("records")]
    )
    base = frame.reset_index(drop=True).drop(
        columns=[column for column in outputs.columns if column in frame.columns],
        errors="ignore",
    )
    return pd.concat([base, outputs], axis=1)
