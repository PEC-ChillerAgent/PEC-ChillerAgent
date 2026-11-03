"""Explicit source contracts and immutable dataset snapshots."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from chiller_app.api.workbench import MAX_ROWS, WorkbenchSchema


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class SourceSchema(WorkbenchSchema):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    temperature_unit: Literal["K", "C", "F"]
    flow_unit: Literal["kg/s", "m3/s", "m3/h", "us_gpm"]
    power_unit: Literal["W", "kW"]


class SourceInfo(Contract):
    kind: Literal["inline", "upload", "file"] = "inline"
    name: str | None = None
    sheet: str | None = None


class DatasetCreate(Contract):
    asset_id: str = Field(min_length=1, max_length=128)
    records: list[dict[str, JsonValue]] = Field(min_length=1, max_length=MAX_ROWS)
    data_schema: SourceSchema = Field(alias="schema")
    source: SourceInfo = Field(default_factory=SourceInfo)

    @field_validator("asset_id")
    @classmethod
    def nonempty_asset(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("asset_id must be nonempty and have no surrounding whitespace")
        return value

    @field_validator("records")
    @classmethod
    def scalar_records(cls, records: list[dict]) -> list[dict]:
        for ordinal, row in enumerate(records, 1):
            for column, value in row.items():
                if isinstance(value, (dict, list)):
                    raise ValueError(f"Row {ordinal}, {column}: only JSON scalar measurements are supported")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"Row {ordinal}, {column}: non-finite values must be represented as null")
        return records


class DatasetInfo(Contract):
    dataset_id: str
    version: int = 1
    asset_id: str
    created_at: str
    row_count: int
    columns: list[str]
    source: SourceInfo
    source_schema: SourceSchema
    effective_schema: WorkbenchSchema
    quality: dict[str, JsonValue] = Field(default_factory=dict)


class DatasetSnapshot(Contract):
    info: DatasetInfo
    records: list[dict[str, JsonValue]]
