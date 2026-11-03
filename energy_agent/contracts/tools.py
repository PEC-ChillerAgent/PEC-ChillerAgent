"""Versioned tool request, summary and evidence contracts."""

from typing import Literal

from pydantic import AliasChoices, Field, JsonValue, model_validator

from chiller_app.api.workbench import SimulationSettings
from energy_agent.contracts.datasets import Contract


class SelectedSimulation(SimulationSettings):
    record_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_custom_record(self):
        if (self.record_id == "custom") != (self.performance is not None):
            raise ValueError("Custom parameters require record_id='custom'; catalogue records use their explicit ID")
        return self


class ChillerAnalysisRequest(Contract):
    asset_id: str = Field(min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1)
    task: Literal["physics", "simulate", "compare"] = "physics"
    simulation: SelectedSimulation | None = None
    preview_rows: int = Field(default=5, ge=0, le=100)

    @model_validator(mode="after")
    def task_settings(self):
        if self.task == "physics" and self.simulation is not None:
            raise ValueError("physics does not accept simulation settings")
        if self.task != "physics" and self.simulation is None:
            raise ValueError("simulate/compare require explicit simulation settings and record_id")
        if self.task == "compare" and self.simulation.kind != "series":
            raise ValueError("compare requires kind='series', one prediction per source row")
        return self


class Diagnostic(Contract):
    code: str
    message: str
    count: int = 0
    source_row_examples: list[int] = Field(default_factory=list, max_length=10, validation_alias=AliasChoices("source_row_examples", "source_rows"))


class MissingInput(Contract):
    target: str
    fields: list[str]
    count: int
    source_row_examples: list[int] = Field(max_length=10, validation_alias=AliasChoices("source_row_examples", "source_rows"))


class Evidence(Contract):
    evidence_id: str
    artifact_id: str
    columns: list[str]
    selection: Literal["finite_values", "finite_valid_model", "paired_in_range"]
    valid_count: int
    source_row_examples: list[int] = Field(max_length=10, validation_alias=AliasChoices("source_row_examples", "source_rows"), description="At most ten unique one-based source row examples; replay selection on artifact for the complete set")


class Metric(Contract):
    value: float | None
    unit: str
    origin: Literal["measured", "measured_derived", "model"]
    aggregation: Literal["sample_mean"] = "sample_mean"
    valid_count: int
    evidence_id: str


class Comparison(Contract):
    measured_column: str
    predicted_column: str
    unit: str
    n: int
    mae: float | None
    rmse: float | None
    bias: float | None
    evidence_id: str


class ModelValidity(Contract):
    curve_out_of_range_count: int = 0
    curve_out_of_range_source_row_examples: list[int] = Field(default_factory=list, max_length=10, validation_alias=AliasChoices("curve_out_of_range_source_row_examples", "curve_out_of_range_source_rows"))
    invalid_model_rows: int = 0
    curve_limits_C: dict[str, float] = Field(default_factory=dict)
    equipment_validation: Literal["not_assessed"] = "not_assessed"


class ToolResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    tool_name: Literal["chiller_analyze"] = "chiller_analyze"
    tool_version: str = "1.0.0"
    run_id: str
    created_at: str
    asset_id: str
    dataset_id: str
    dataset_version: int
    task: Literal["physics", "simulate", "compare"]
    status: Literal["success", "partial", "needs_input", "failed"]
    request: ChillerAnalysisRequest
    input_rows: int
    output_rows: int
    metrics: dict[str, Metric] = Field(default_factory=dict)
    comparisons: dict[str, Comparison] = Field(default_factory=dict)
    missing_inputs: list[MissingInput] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)
    errors: list[Diagnostic] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    model_validity: ModelValidity = Field(default_factory=ModelValidity)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    preview_records: list[dict[str, JsonValue]] = Field(default_factory=list)
    artifact_id: str
