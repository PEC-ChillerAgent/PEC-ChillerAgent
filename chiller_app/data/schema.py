"""Explicit source-column and unit contract for arbitrary chiller datasets."""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pipeline import standardize_frame


FieldName = Literal[
    "timestamp", "run_id", "sample_id", "TEI_K", "TEO_K", "TCI_K", "TCO_K", "TSet_K",
    "evap_flow_kg_s", "cond_flow_kg_s", "P_W", "compressor_frequency_Hz",
    "valve_opening_pct", "operating_status", "ambient_dry_K", "ambient_wet_K",
    "suction_pressure_Pa", "discharge_pressure_Pa", "alarm_code", "label", "fault_name",
]


class DataSchema(BaseModel):
    """Maps source headers to canonical signals and defines source units."""

    model_config = ConfigDict(extra="forbid")
    column_map: dict[FieldName, str] = Field(
        description="Canonical signal -> exact source header, e.g. TEI_K -> chilled_in"
    )
    temperature_unit: Literal["K", "C", "F"] = "K"
    flow_unit: Literal["kg/s", "m3/s", "m3/h", "us_gpm"] = "kg/s"
    power_unit: Literal["W", "kW"] = "W"
    pressure_unit: Literal["Pa", "kPa", "MPa", "bar", "psi"] = "Pa"
    water_specific_heat_J_kgK: float = Field(default=4180.0, gt=0)
    water_density_kg_m3: float = Field(default=1000.0, gt=0)

    @model_validator(mode="after")
    def require_unique_source_columns(self) -> "DataSchema":
        if len(set(self.column_map.values())) != len(self.column_map):
            raise ValueError("Each source column may map to only one canonical field")
        return self


def apply_schema(frame: pd.DataFrame, schema: DataSchema) -> pd.DataFrame:
    missing = [source for source in schema.column_map.values() if source not in frame.columns]
    if missing:
        raise ValueError(f"Mapped source columns not found: {missing}")
    # Explicit mapping is authoritative: unrelated alias-like columns must not
    # override a selected signal (for example another m3/h flow column).
    mapped = frame.loc[:, list(schema.column_map.values())].rename(
        columns={source: canonical for canonical, source in schema.column_map.items()}
    )
    standardized = standardize_frame(
        mapped,
        temperature_unit=schema.temperature_unit,
        flow_unit=schema.flow_unit,
        power_unit=schema.power_unit,
        pressure_unit=schema.pressure_unit,
        water_density_kg_m3=schema.water_density_kg_m3,
    )
    return standardized
