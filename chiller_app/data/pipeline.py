"""Input, cleaning and feature engineering for chiller measurements.

The canonical internal convention is:

* temperatures: kelvin;
* power: watt;
* mass flow: kg/s;
* time: pandas datetime with one ``run_id`` per continuous experiment.

The loader accepts the compact ASHRAE files and richer field-data columns. It
does not silently invent missing flows, pressures or timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


CANONICAL_COLUMNS = [
    "timestamp",
    "run_id",
    "sample_id",
    "TEI_K",
    "TEO_K",
    "TCI_K",
    "TCO_K",
    "evap_flow_kg_s",
    "cond_flow_kg_s",
    "P_W",
    "compressor_frequency_Hz",
    "valve_opening_pct",
    "operating_status",
    "ambient_dry_K",
    "ambient_wet_K",
    "suction_pressure_Pa",
    "discharge_pressure_Pa",
    "alarm_code",
    "label",
    "fault_name",
]

TEMP_FIELDS = {"TEI_K", "TEO_K", "TCI_K", "TCO_K", "TSet_K", "ambient_dry_K", "ambient_wet_K"}
FLOW_FIELDS = {"evap_flow_kg_s", "cond_flow_kg_s"}
PRESSURE_FIELDS = {"suction_pressure_Pa", "discharge_pressure_Pa"}

ALIASES: Mapping[str, Sequence[str]] = {
    "timestamp": ("timestamp", "time", "datetime", "date_time", "时间", "日期时间"),
    "run_id": ("run_id", "run", "test_id", "experiment_id", "试验编号", "序列"),
    "sample_id": ("sample_id", "id", "index", "样本编号"),
    "TEI_K": ("TEI_K", "TEI", "evaporator_inlet_temp", "chilled_water_inlet_temp", "冷冻水进水温度"),
    "TEO_K": ("TEO_K", "TEO", "evaporator_outlet_temp", "chilled_water_outlet_temp", "冷冻水出水温度"),
    "TCI_K": ("TCI_K", "TCI", "condenser_inlet_temp", "cooling_water_inlet_temp", "冷却水进水温度"),
    "TCO_K": ("TCO_K", "TCO", "condenser_outlet_temp", "cooling_water_outlet_temp", "冷却水出水温度"),
    "TSet_K": ("TSet_K", "TSet", "TWE_set", "冷冻水出水设定温度"),
    "evap_flow_kg_s": ("evap_flow_kg_s", "evaporator_flow_kg_s", "冷冻水质量流量"),
    "cond_flow_kg_s": ("cond_flow_kg_s", "condenser_flow_kg_s", "冷却水质量流量"),
    "evap_flow_m3_h": ("evap_flow_m3_h", "evaporator_flow_m3_h", "冷冻水流量"),
    "cond_flow_m3_h": ("cond_flow_m3_h", "condenser_flow_m3_h", "冷却水流量"),
    "evap_flow_m3_s": ("evap_flow_m3_s", "evaporator_flow_m3_s"),
    "cond_flow_m3_s": ("cond_flow_m3_s", "condenser_flow_m3_s"),
    "evap_flow_gpm": ("evap_flow_gpm", "FWE", "evaporator_flow_gpm"),
    "cond_flow_gpm": ("cond_flow_gpm", "FWC", "condenser_flow_gpm"),
    "P_W": ("P_W", "power_W", "power", "compressor_power_W", "机组功率"),
    "kW": ("kW", "power_kW", "compressor_power_kW", "机组功率_kW"),
    "compressor_frequency_Hz": ("compressor_frequency_Hz", "frequency_Hz", "compressor_frequency", "压缩机频率"),
    "valve_opening_pct": ("valve_opening_pct", "valve_opening", "valve_position", "阀门开度"),
    "operating_status": ("operating_status", "status", "运行状态"),
    "ambient_dry_K": ("ambient_dry_K", "ambient_dry", "dry_bulb", "干球温度"),
    "ambient_wet_K": ("ambient_wet_K", "ambient_wet", "wet_bulb", "湿球温度"),
    "suction_pressure_Pa": ("suction_pressure_Pa", "suction_pressure", "low_pressure", "低压"),
    "discharge_pressure_Pa": ("discharge_pressure_Pa", "discharge_pressure", "high_pressure", "高压"),
    "alarm_code": ("alarm_code", "alarm", "alarm_status", "报警状态"),
    "label": ("label", "fault_label", "fault", "class", "故障标签"),
    "fault_name": ("fault_name", "fault_type", "故障名称"),
}


@dataclass
class CleaningResult:
    frame: pd.DataFrame
    report: Dict[str, Any]


def _key(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "").replace("-", "_")


def read_table(source: str | Path | Any) -> pd.DataFrame:
    """Read CSV/Excel from a path or uploaded file-like object."""

    name = getattr(source, "name", str(source))
    suffix = Path(name).suffix.lower()
    if hasattr(source, "seek"):
        source.seek(0)
    if suffix == ".csv":
        return pd.read_csv(source)
    if suffix in {".xls", ".xlsx"}:
        return pd.read_excel(source)
    raise ValueError(f"Unsupported table format: {suffix or 'unknown'}")


def _find_column(columns: Iterable[Any], aliases: Sequence[str]) -> Optional[Any]:
    by_key = {_key(column): column for column in columns}
    for alias in aliases:
        if _key(alias) in by_key:
            return by_key[_key(alias)]
    return None


def _temperature_to_kelvin(values: pd.Series, unit: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if unit == "K":
        return numeric
    if unit in {"C", "°C"}:
        return numeric + 273.15
    if unit in {"F", "°F"}:
        return (numeric - 32.0) * (5.0 / 9.0) + 273.15
    raise ValueError(f"Unsupported temperature unit: {unit}")


def _flow_to_kg_s(values: pd.Series, unit: str, density_kg_m3: float = 1000.0) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if unit == "kg/s":
        return numeric
    if unit == "m3/s":
        return numeric * density_kg_m3
    if unit == "m3/h":
        return numeric * density_kg_m3 / 3600.0
    if unit == "us_gpm":
        return numeric * 3.785411784e-3 * density_kg_m3 / 60.0
    raise ValueError(f"Unsupported flow unit: {unit}")


def _pressure_to_pa(values: pd.Series, unit: str) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    factors = {"Pa": 1.0, "kPa": 1.0e3, "MPa": 1.0e6, "bar": 1.0e5, "psi": 6894.757293168}
    if unit not in factors:
        raise ValueError(f"Unsupported pressure unit: {unit}")
    return numeric * factors[unit]


def _infer_temperature_unit(source_name: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    name = str(source_name).lower()
    if "_k" in name or name.endswith("k"):
        return "K"
    if "_c" in name or "celsius" in name:
        return "C"
    # The original ASHRAE workbook uses TEI/TEO/TCI/TCO in °F.
    if str(source_name).strip().upper() in {"TEI", "TEO", "TCI", "TCO"}:
        return "F"
    return "K"


def standardize_frame(
    frame: pd.DataFrame,
    *,
    temperature_unit: str = "auto",
    flow_unit: str = "auto",
    power_unit: str = "auto",
    pressure_unit: str = "Pa",
    water_density_kg_m3: float = 1000.0,
) -> pd.DataFrame:
    """Map source names and units to the canonical internal schema."""

    source = frame.copy()
    source.columns = [str(column).strip() for column in source.columns]
    result = pd.DataFrame(index=source.index)

    for canonical, aliases in ALIASES.items():
        column = _find_column(source.columns, aliases)
        if column is None:
            continue
        if canonical in TEMP_FIELDS:
            unit = _infer_temperature_unit(column, temperature_unit)
            result[canonical] = _temperature_to_kelvin(source[column], unit)
        elif canonical in FLOW_FIELDS:
            unit = flow_unit if flow_unit != "auto" else "kg/s"
            result[canonical] = _flow_to_kg_s(source[column], unit, water_density_kg_m3)
        elif canonical in {"evap_flow_gpm", "cond_flow_gpm"}:
            target = "evap_flow_kg_s" if canonical == "evap_flow_gpm" else "cond_flow_kg_s"
            result[target] = _flow_to_kg_s(source[column], "us_gpm", water_density_kg_m3)
        elif canonical == "P_W":
            unit = power_unit if power_unit != "auto" else "W"
            values = pd.to_numeric(source[column], errors="coerce")
            result[canonical] = values if unit == "W" else values * 1000.0
        elif canonical == "kW":
            if "P_W" not in result:
                values = pd.to_numeric(source[column], errors="coerce")
                result["P_W"] = values * 1000.0
        elif canonical == "timestamp":
            result[canonical] = pd.to_datetime(source[column], errors="coerce")
        elif canonical in PRESSURE_FIELDS:
            result[canonical] = _pressure_to_pa(source[column], pressure_unit)
        elif canonical in {"run_id", "sample_id", "operating_status", "alarm_code", "label", "fault_name"}:
            result[canonical] = source[column]
        else:
            result[canonical] = pd.to_numeric(source[column], errors="coerce")

    # Explicit unit-bearing flow columns take precedence over a generic flow.
    for field, unit in (("evap_flow_m3_h", "m3/h"), ("cond_flow_m3_h", "m3/h"),
                        ("evap_flow_m3_s", "m3/s"), ("cond_flow_m3_s", "m3/s")):
        column = _find_column(source.columns, ALIASES[field])
        if column is not None:
            target = "evap_flow_kg_s" if field.startswith("evap") else "cond_flow_kg_s"
            result[target] = _flow_to_kg_s(source[column], unit, water_density_kg_m3)

    if "run_id" not in result:
        result["run_id"] = "default"
    if "sample_id" not in result:
        result["sample_id"] = np.arange(len(result))
    if "label" in result:
        inverse_labels = {
            "normal": 1,
            "excess_oil_14pct": 2,
            "condenser_water_flow_reduced_10pct": 3,
            "evaporator_water_flow_reduced_10pct": 4,
            "refrigerant_undercharge_10pct": 5,
            "noncondensable_nitrogen_1pct": 6,
            "refrigerant_overcharge_10pct": 7,
            "condenser_fouling_12pct": 8,
        }
        numeric = pd.to_numeric(result["label"], errors="coerce")
        named = result["label"].astype(str).str.strip().str.lower().map(inverse_labels)
        result["label"] = numeric.fillna(named)
    return result


def clean_measurements(
    frame: pd.DataFrame,
    *,
    deduplicate: bool = True,
    reject_physical_outliers: bool = True,
) -> CleaningResult:
    """Clean without silently filling missing measurements."""

    result = frame.copy()
    original_rows = len(result)
    numeric_columns = [column for column in CANONICAL_COLUMNS if column in result and column not in {"label", "sample_id"}]
    for column in numeric_columns:
        if column not in {"timestamp", "run_id", "operating_status", "fault_name"}:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    if "timestamp" in result:
        result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce")
        result = result.sort_values(["run_id", "timestamp"], kind="stable")
    if deduplicate:
        before = len(result)
        keys = [column for column in ["run_id", "timestamp", "sample_id"] if column in result]
        if keys:
            result = result.drop_duplicates(subset=keys, keep="first")
        deduplicated = before - len(result)
    else:
        deduplicated = 0

    invalid_counts: Dict[str, int] = {}
    if reject_physical_outliers:
        bounds = {
            "TEI_K": (200.0, 400.0), "TEO_K": (200.0, 400.0),
            "TCI_K": (200.0, 400.0), "TCO_K": (200.0, 400.0),
            "ambient_dry_K": (200.0, 400.0), "ambient_wet_K": (200.0, 400.0),
            "P_W": (0.0, np.inf), "evap_flow_kg_s": (0.0, np.inf),
            "cond_flow_kg_s": (0.0, np.inf),
        }
        for column, (lower, upper) in bounds.items():
            if column not in result:
                continue
            invalid = result[column].notna() & ((result[column] < lower) | (result[column] > upper))
            invalid_counts[column] = int(invalid.sum())
            result.loc[invalid, column] = np.nan

    missing_counts = {column: int(result[column].isna().sum()) for column in CANONICAL_COLUMNS if column in result}
    result = result.reset_index(drop=True)
    report = {
        "input_rows": int(original_rows),
        "output_rows": int(len(result)),
        "deduplicated_rows": int(deduplicated),
        "invalidated_values": invalid_counts,
        "missing_values": missing_counts,
        "has_timestamp": bool("timestamp" in result and result["timestamp"].notna().any()),
        "has_multiple_runs": bool("run_id" in result and result["run_id"].nunique(dropna=True) > 1),
    }
    return CleaningResult(result, report)


def engineer_features(frame: pd.DataFrame, cp_water: float = 4180.0) -> pd.DataFrame:
    """Add temperature, heat-balance and efficiency features."""

    result = frame.copy()
    required = ["TEI_K", "TEO_K", "TCI_K", "TCO_K"]
    missing = [column for column in required if column not in result]
    if missing:
        raise ValueError(f"Feature engineering requires columns: {missing}")
    result["delta_evap_K"] = result["TEI_K"] - result["TEO_K"]
    result["delta_cond_K"] = result["TCO_K"] - result["TCI_K"]
    result["temperature_lift_K"] = result["TCO_K"] - result["TEO_K"]
    result["mean_evap_temp_K"] = (result["TEI_K"] + result["TEO_K"]) / 2.0
    result["mean_cond_temp_K"] = (result["TCI_K"] + result["TCO_K"]) / 2.0
    if "P_W" in result:
        result["power_kW"] = result["P_W"] / 1000.0
    if "evap_flow_kg_s" in result:
        result["cooling_capacity_kW"] = result["evap_flow_kg_s"] * cp_water * result["delta_evap_K"] / 1000.0
    if "cond_flow_kg_s" in result:
        result["condenser_heat_kW"] = result["cond_flow_kg_s"] * cp_water * result["delta_cond_K"] / 1000.0
    if "cooling_capacity_kW" in result and "power_kW" in result:
        result["COP"] = result["cooling_capacity_kW"] / result["power_kW"].replace(0, np.nan)
    if "cooling_capacity_kW" in result and "condenser_heat_kW" in result and "power_kW" in result:
        result["energy_balance_error_kW"] = result["condenser_heat_kW"] - result["cooling_capacity_kW"] - result["power_kW"]
    return result


def prepare_source(
    source: str | Path | Any,
    *,
    temperature_unit: str = "auto",
    flow_unit: str = "auto",
    power_unit: str = "auto",
    pressure_unit: str = "Pa",
    water_density_kg_m3: float = 1000.0,
) -> CleaningResult:
    """Read, standardize, clean and engineer one source."""

    loaded = read_table(source)
    standardized = standardize_frame(
        loaded,
        temperature_unit=temperature_unit,
        flow_unit=flow_unit,
        power_unit=power_unit,
        pressure_unit=pressure_unit,
        water_density_kg_m3=water_density_kg_m3,
    )
    cleaned = clean_measurements(standardized)
    cleaned.frame = engineer_features(cleaned.frame)
    return cleaned
