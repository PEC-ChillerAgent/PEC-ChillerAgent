"""FastAPI boundary for the generic, Modelica-inspired chiller service.

FastAPI is the integration boundary: a web page, desktop client, PLC gateway
or another service can all send the same JSON contract. Streamlit remains an
optional operator/research UI and is not required to run the model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from chiller_app.data.schema import DataSchema
from chiller_app.data.schema import apply_schema
from chiller_app.model.electric_eir import EIRPerformance, ElectricEIR, DEFAULT_RECORD, performance
from chiller_app.model.eir_calibration import fit_power_scale, error_metrics
from chiller_app.model.model_definition import default_model_definition
from .workbench import router as workbench_router, WorkbenchRequest, run_workbench
from energy_agent.api.routes import router as agent_router
from energy_agent.api.chat import page_router as chat_page_router, router as chat_router
from energy_agent.api.student_analysis import router as student_analysis_router
from energy_agent.api.focused_analysis import router as focused_analysis_router

from .service import (
    analyze_records,
    clean_records,
    predict_records,
    optimize_records,
    train_records,
    validate_model_records,
    validate_records,
)


class RecordsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    records: list[dict[str, Any]] = Field(min_length=1)
    data_schema: DataSchema | None = Field(default=None, alias="schema")
    temperature_unit: Literal["K", "C", "F"] = "K"
    flow_unit: Literal["kg/s", "m3/s", "m3/h", "us_gpm"] = "kg/s"
    power_unit: Literal["W", "kW"] = "W"
    pressure_unit: Literal["Pa", "kPa", "MPa", "bar", "psi"] = "Pa"


class EIRCalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    records: list[dict[str, Any]] = Field(min_length=3, max_length=20000)
    validation_records: list[dict[str, Any]] | None = Field(default=None, min_length=1, max_length=20000)
    data_schema: DataSchema = Field(alias="schema")
    record_id: str = DEFAULT_RECORD
    performance: EIRPerformance | None = None
    healthy_training_confirmed: bool = False
    steady_state_confirmed: bool = False
    allow_extrapolation: bool = False


class ModelFileRequest(RecordsRequest):
    model_path: str = Field(min_length=1)


class ModelValidationRequest(ModelFileRequest):
    pass


class OptimizationRequest(BaseModel):
    model_path: str = Field(min_length=1)
    base_input: dict[str, float]
    bounds: dict[str, tuple[float, float]]
    outlet_target_K: tuple[float, float] | None = None


app = FastAPI(
    title="Generic Chiller Model API",
    version="0.5.0",
    description=(
        "A configuration-driven chiller analysis service. It normalizes arbitrary "
        "source columns into SI signals, evaluates water-side energy equations, "
        "simulates/calibrates ElectricEIR, and exposes explainable outputs."
    ),
)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.include_router(workbench_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(student_analysis_router)
app.include_router(focused_analysis_router)
app.include_router(chat_page_router)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def workbench_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


def _call(function: Any, **kwargs: Any) -> Any:
    try:
        return function(**kwargs)
    except (ValueError, FileNotFoundError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _record_kwargs(request: RecordsRequest) -> dict[str, Any]:
    return {
        "records": request.records,
        "schema": request.data_schema,
        "temperature_unit": request.temperature_unit,
        "flow_unit": request.flow_unit,
        "power_unit": request.power_unit,
        "pressure_unit": request.pressure_unit,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "generic-chiller-model"}


@app.get("/models")
def models() -> dict[str, Any]:
    return {"models": [default_model_definition()]}


@app.get("/model/definition")
def model_definition() -> dict[str, Any]:
    return default_model_definition()


@app.post("/data/validate")
def validate(request: RecordsRequest) -> dict[str, Any]:
    return _call(validate_records, **_record_kwargs(request))


@app.post("/data/clean")
def clean(request: RecordsRequest) -> dict[str, Any]:
    return _call(clean_records, **_record_kwargs(request))


@app.post("/physics/calculate")
def physics(request: RecordsRequest) -> dict[str, Any]:
    return _call(analyze_records, **_record_kwargs(request))


@app.post("/analyze", deprecated=True)
def analyze(request: RecordsRequest) -> dict[str, Any]:
    """Backward-compatible alias for ``/physics/calculate``."""

    return physics(request)


@app.post("/model/electric-eir/simulate")
def simulate_electric_eir(request: WorkbenchRequest) -> dict[str, Any]:
    settings = request.simulation.model_copy(update={"engine": "electric_eir"})
    return _call(run_workbench, request=request.model_copy(update={"operation": "simulate", "simulation": settings}))


@app.post("/model/electric-eir/calibrate", summary="健康稳态数据：ElectricEIR 单参数功率校准")
def calibrate_electric_eir(request: EIRCalibrationRequest) -> dict[str, Any]:
    if not request.healthy_training_confirmed or not request.steady_state_confirmed:
        raise HTTPException(422, "须明确数据属于健康训练集和稳态工况；本接口不自动判定健康或稳态。")
    def run_fit():
        import pandas as pd
        schema = request.data_schema
        # Steady rows are independent observations: do not fabricate chronology.
        frame = apply_schema(pd.DataFrame(request.records), schema)
        if "operating_status" not in frame:
            frame["operating_status"] = 1
        per = performance(request.record_id, request.performance)
        report = fit_power_scale(frame, per, cp=schema.water_specific_heat_J_kgK,
                                 allow_extrapolation=request.allow_extrapolation)
        report["record_id"] = request.record_id if request.performance is None else "custom"
        if request.validation_records is not None:
            validation = apply_schema(pd.DataFrame(request.validation_records), schema)
            if "operating_status" not in validation:
                validation["operating_status"] = 1
            fitted = EIRPerformance.model_validate(report["performance_parameters"])
            prediction = ElectricEIR(fitted, schema.water_specific_heat_J_kgK).simulate(validation, mode="steady")
            report["validation_kW"] = error_metrics(validation.P_W.to_numpy() / 1000, prediction.simulated_power_kW)
            report["validation_extrapolated_rows"] = int(prediction.curve_out_of_range.sum())
        return report
    return _call(run_fit)


@app.post("/model/train")
def train(request: ModelFileRequest) -> dict[str, Any]:
    kwargs = _record_kwargs(request)
    kwargs["model_path"] = Path(request.model_path)
    return _call(train_records, **kwargs)


@app.post("/model/predict")
def predict(request: ModelFileRequest) -> dict[str, Any]:
    kwargs = _record_kwargs(request)
    kwargs["model_path"] = Path(request.model_path)
    return _call(predict_records, **kwargs)


@app.post("/model/validate")
def validate_model(request: ModelValidationRequest) -> dict[str, Any]:
    kwargs = _record_kwargs(request)
    kwargs["model_path"] = Path(request.model_path)
    return _call(validate_model_records, **kwargs)


@app.post("/model/optimize")
def optimize(request: OptimizationRequest) -> dict[str, Any]:
    bounds = {name: (float(values[0]), float(values[1])) for name, values in request.bounds.items()}
    return _call(
        optimize_records,
        model_path=Path(request.model_path),
        base_input=request.base_input,
        bounds=bounds,
        outlet_target_K=request.outlet_target_K,
    )
