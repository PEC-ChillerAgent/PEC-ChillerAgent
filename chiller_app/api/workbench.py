"""Untrained, explicit-unit calculation and simulation for the web workbench."""
from __future__ import annotations

from io import BytesIO, StringIO
import math
from pathlib import Path
from typing import Any, Literal
from zipfile import BadZipFile

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from chiller_app.data.schema import DataSchema, apply_schema
from chiller_app.model.electric_eir import DEFAULT_RECORD, EIRPerformance, ElectricEIR, biquadratic, catalogue, performance, eir_model_definition

router = APIRouter(prefix="/workbench", tags=["网页工作台"])
MAX_ROWS = 20000
MAX_BYTES = 10 * 1024 * 1024
SIGNALS = ["TEI_K", "TEO_K", "TCI_K", "TCO_K", "evap_flow_kg_s", "cond_flow_kg_s", "P_W", "TSet_K", "operating_status"]
UNITS = {
    "elapsed_s": "s", "TEI_C": "°C", "TEO_C": "°C", "TCI_C": "°C", "TCO_C": "°C",
    "evap_flow_kg_s": "kg/s", "cond_flow_kg_s": "kg/s", "power_kW": "kW",
    "cooling_capacity_kW": "kW", "condenser_heat_kW": "kW", "COP": "1",
    "energy_balance_error_kW": "kW", "simulated_TEO_C": "°C", "simulated_TCO_C": "°C",
    "simulated_cooling_capacity_kW": "kW", "simulated_condenser_heat_kW": "kW",
    "simulated_evap_water_kW": "kW", "simulated_cond_water_kW": "kW",
    "evap_storage_kW": "kW", "cond_storage_kW": "kW",
    "TSet_C": "°C", "operating_status": "1", "simulated_power_kW": "kW", "simulated_COP": "1",
    "PLR1": "1", "PLR2": "1", "CR": "1", "capFunT": "1", "EIRFunT": "1", "EIRFunPLR": "1",
    "QEva_flow_ava_W": "W", "QEva_flow_set_W": "W", "QEva_flow_W": "W", "QCon_flow_W": "W",
    "curve_out_of_range": "1",
}


class SimulationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["constant", "series"] = "constant"
    duration_s: float = Field(default=3600, gt=0, le=604800)
    interval_s: float = Field(default=60, gt=0)
    time_mode: Literal["interval", "seconds", "minutes", "datetime"] = "interval"
    engine: Literal["electric_eir"] = "electric_eir"
    mode: Literal["dynamic", "steady"] = "dynamic"
    record_id: str = DEFAULT_RECORD
    performance: EIRPerformance | None = None
    tau_evap_s: float = Field(default=30, gt=0)
    tau_cond_s: float = Field(default=30, gt=0)
    # Input temperature unit applies here as well. A mapped TSet_K overrides it.
    setpoint: float | None = None
    enabled: bool = True
    initial_teo: float | None = None
    initial_tco: float | None = None


class WorkbenchSchema(DataSchema):
    water_specific_heat_J_kgK: float = Field(default=4184.0, gt=0)
    water_density_kg_m3: float = Field(default=995.586, gt=0)


class WorkbenchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    operation: Literal["calculate", "simulate"] = "calculate"
    records: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_ROWS)
    data_schema: WorkbenchSchema = Field(alias="schema")
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


@router.post("/upload")
async def upload(file: UploadFile, sheet_name: str | None = None) -> dict[str, Any]:
    """Read in memory; never use an uploaded name as a local filesystem path."""
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "文件不能超过 10 MB。请分批上传。")
    suffix = Path(file.filename or "").suffix.lower()
    try:
        if suffix == ".csv":
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    decoded = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("CSV 编码无法识别，请另存为 UTF-8 CSV。")
            frame = pd.read_csv(StringIO(decoded), nrows=MAX_ROWS + 1)
        elif suffix in {".xlsx", ".xls"}:
            workbook = pd.ExcelFile(BytesIO(content))
            sheets = workbook.sheet_names
            if sheet_name is not None and sheet_name not in sheets:
                raise ValueError(f"找不到工作表“{sheet_name}”；可选工作表：{', '.join(sheets)}")
            selected_sheet = sheet_name or sheets[0]
            frame = pd.read_excel(workbook, sheet_name=selected_sheet, nrows=MAX_ROWS + 1)
        else:
            raise ValueError("请上传 CSV、XLSX 或 XLS 文件。")
        if frame.empty or len(frame) > MAX_ROWS:
            raise ValueError(f"文件须有 1–{MAX_ROWS} 行数据；超过时请分批上传。")
        frame.columns = [str(c) for c in frame.columns]
        if suffix == ".csv":
            sheets, selected_sheet = [], None
        return json_safe({"filename": file.filename, "columns": list(frame.columns),
                          "row_count": len(frame), "records": frame.to_dict("records"),
                          "sheets": sheets, "selected_sheet": selected_sheet,
                          "sheet": f"工作表：{selected_sheet}" if selected_sheet else "CSV 首行是表头。"})
    except (ValueError, ImportError, OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(422, f"读取文件失败：{exc}") from exc


def _normalize(request: WorkbenchRequest) -> tuple[pd.DataFrame, list[dict[str, Any]], WorkbenchSchema, dict[str, Any]]:
    source = pd.DataFrame(request.records)
    mapping = dict(request.data_schema.column_map)
    header_key = lambda value: "".join(char for char in str(value).casefold() if char.isalnum())
    source_headers = {header_key(column): str(column) for column in source.columns}
    # ASHRAE RP-1043 workbooks use stable short headers and fixed source units.
    # Resolve these server-side as well as in the UI so a stale browser script
    # cannot silently omit the two flow columns from a simulation request.
    def is_flow_header(prefix: str) -> bool:
        # RP-1043 files may append the source unit to the short header, e.g.
        # ``FWE (gpm)`` or ``FWC (US gpm)``. ``header_key`` removes the
        # punctuation, so accept the normalized spellings as well as FWE/FWC.
        return any(name in source_headers for name in (prefix, prefix + "gpm", prefix + "usgpm"))

    ashrae_signature = (
        any(name in source_headers for name in ("tei", "teif", "teic", "teik"))
        and any(name in source_headers for name in ("tci", "tcif", "tcic", "tcik"))
        and is_flow_header("fwe")
        and is_flow_header("fwc")
    )
    inferred_columns: dict[str, str] = {}
    automatic_units: dict[str, str] = {}
    if ashrae_signature:
        source_aliases = {
            "timestamp": ("time", "times", "timeseconds", "timeminutes"),
            "TEI_K": ("tei", "teif", "teic", "teik"),
            "TEO_K": ("teo", "teof", "teoc", "teok"),
            "TCI_K": ("tci", "tcif", "tcic", "tcik"),
            "TCO_K": ("tco", "tcof", "tcoc", "tcok"),
            "evap_flow_kg_s": ("fwe", "fwegpm", "fweusgpm"),
            "cond_flow_kg_s": ("fwc", "fwcgpm", "fwcusgpm"),
            "TSet_K": ("tweset", "twesetf", "twesetc", "twesetk"), "P_W": ("kw",),
        }
        for canonical, aliases in source_aliases.items():
            if canonical not in mapping:
                match = next((source_headers[alias] for alias in aliases if alias in source_headers), None)
                if match is not None:
                    mapping[canonical] = match
                    inferred_columns[canonical] = match
        tei_header = next((name for name in ("teif", "teic", "teik", "tei") if name in source_headers), "tei")
        inferred_temperature_unit = {"teif": "F", "teic": "C", "teik": "K", "tei": "F"}[tei_header]
        automatic_units = {"temperature_unit": inferred_temperature_unit, "flow_unit": "us_gpm"}
        if mapping.get("P_W") and header_key(mapping["P_W"]) == "kw":
            automatic_units["power_unit"] = "kW"
    if not any(k in mapping for k in SIGNALS):
        raise ValueError("请至少映射一个温度、流量或功率字段。")
    resolved_schema = request.data_schema.model_copy(update={
        "column_map": mapping,
        **automatic_units,
    })
    numeric_schema = request.data_schema.model_copy(update={
        "column_map": {k: v for k, v in mapping.items() if k != "timestamp"},
        **automatic_units,
    })
    frame = apply_schema(source, numeric_schema)
    # Keep the original time signal: pandas must not interpret elapsed seconds
    # as nanoseconds since epoch. Time interpretation is an explicit UI choice.
    if "timestamp" in mapping:
        frame["timestamp"] = source[mapping["timestamp"]]
    frame["source_row"] = np.arange(1, len(frame) + 1)
    issues = []
    for field in SIGNALS:
        if field not in frame:
            frame[field] = np.nan
            continue
        numeric = pd.to_numeric(frame[field], errors="coerce")
        supplied = source[mapping[field]].notna() & source[mapping[field]].astype(str).str.strip().ne("")
        invalid = supplied & ~np.isfinite(numeric)
        if field.endswith("_K"):
            invalid |= numeric.notna() & ~numeric.between(200, 400)
        elif field == "operating_status":
            invalid |= numeric.notna() & ~numeric.isin([0, 1])
        else:
            invalid |= numeric.notna() & (numeric < 0)
        for i in frame.index[invalid]:
            issues.append({"row": int(i + 1), "field": field, "message": "非数值、非有限值或超出物理范围，已留空。"})
        frame[field] = numeric.mask(invalid)
    for field in ("run_id", "sample_id"):
        if frame[field].isna().any():
            raise ValueError(f"已映射的 {field} 不能留空。")
    input_inference: dict[str, Any] = {}
    if inferred_columns:
        input_inference["auto_mapped_columns"] = inferred_columns
    if automatic_units:
        input_inference["assumed_source_units"] = automatic_units
    return frame, issues, resolved_schema, input_inference


def _calculate(frame: pd.DataFrame, cp: float) -> pd.DataFrame:
    result = frame.copy()
    result["power_kW"] = frame.P_W / 1000
    result["cooling_capacity_kW"] = frame.evap_flow_kg_s * cp * (frame.TEI_K - frame.TEO_K) / 1000
    result["condenser_heat_kW"] = frame.cond_flow_kg_s * cp * (frame.TCO_K - frame.TCI_K) / 1000
    result["COP"] = result.cooling_capacity_kW / result.power_kW.where(result.power_kW > 0)
    result["energy_balance_error_kW"] = result.condenser_heat_kW - result.cooling_capacity_kW - result.power_kW
    return result


def _simulate(frame: pd.DataFrame, request: WorkbenchRequest) -> tuple[pd.DataFrame, dict[str, Any]]:
    cfg = request.simulation
    required = ["TEI_K", "TCI_K", "evap_flow_kg_s", "cond_flow_kg_s"]
    bad = frame[required].isna().any(axis=1) | (frame.evap_flow_kg_s <= 0) | (frame.cond_flow_kg_s <= 0)
    if bad.any():
        rows = frame.loc[bad, "source_row"].tolist()
        source_names = {"TEI_K": "冷冻水进水温度", "TCI_K": "冷却水进水温度",
                        "evap_flow_kg_s": "冷冻水流量", "cond_flow_kg_s": "冷却水流量", "P_W": "机组功率"}
        problems = []
        for field in required:
            invalid = frame[field].isna()
            if field in {"evap_flow_kg_s", "cond_flow_kg_s"}:
                invalid |= frame[field] <= 0
            if invalid.any():
                source = request.data_schema.column_map.get(field)
                label = source_names[field] + (f"（列 {source}）" if source else "（尚未映射来源列）")
                examples = frame.loc[invalid, "source_row"].head(5).tolist()
                problems.append(f"{label} {int(invalid.sum())} 行无效，示例行 {examples}")
        raise ValueError("仿真输入检查未通过：" + "；".join(problems) + f"。请核对工作表、列映射和单位；问题行示例 {rows[:10]}。")
    if cfg.kind == "constant":
        if len(frame) != 1:
            raise ValueError("恒定工况仿真只接受一条输入；多行文件请选择时间序列仿真。")
        count = math.ceil(cfg.duration_s / cfg.interval_s) + 1
        if count > MAX_ROWS:
            raise ValueError(f"输出超过 {MAX_ROWS} 点，请增大输出间隔。")
        times = np.minimum(np.arange(count) * cfg.interval_s, cfg.duration_s)
        frame = pd.concat([frame] * count, ignore_index=True)
        frame = frame.drop(columns="timestamp", errors="ignore")
        frame["elapsed_s"] = times
    elif cfg.time_mode != "interval":
        if "timestamp" not in frame:
            raise ValueError("请映射时间列，或选择按固定采样间隔生成时间。")
        frame = frame.copy()
        if cfg.time_mode in {"seconds", "minutes"}:
            frame["elapsed_s"] = pd.to_numeric(frame.timestamp, errors="coerce") * (60 if cfg.time_mode == "minutes" else 1)
        else:
            frame["timestamp"] = pd.to_datetime(frame.timestamp, errors="coerce", utc=True, format="mixed")
    else:
        # An explicitly selected fixed interval takes precedence over timestamps.
        frame = frame.drop(columns="timestamp", errors="ignore")
    def to_kelvin(value: float | None) -> float | None:
        if value is None:
            return None
        unit = request.data_schema.temperature_unit
        result = value if unit == "K" else value + 273.15 if unit == "C" else (value - 32) * 5 / 9 + 273.15
        if not 200 <= result <= 400:
            raise ValueError("初始温度应在 200–400 K 对应的范围内。")
        return result
    cp = request.data_schema.water_specific_heat_J_kgK
    per = performance(cfg.record_id, cfg.performance)
    # A supplied column must be complete. Never conceal a failed mapping
    # or invalid row behind a default controller input.
    if "TSet_K" not in request.data_schema.column_map:
        if cfg.setpoint is None:
            raise ValueError("ElectricEIR 需要出水温度设定值：请填写设定温度或映射 TSet_K 列。")
        frame["TSet_K"] = to_kelvin(cfg.setpoint)
    if "operating_status" not in request.data_schema.column_map:
        frame["operating_status"] = int(cfg.enabled)
    if frame[["TSet_K", "operating_status"]].isna().any().any():
        raise ValueError("设定温度列须完整，启停状态列只能包含 0 或 1；不自动填补缺失控制输入。")
    initial_e = to_kelvin(cfg.initial_teo) if cfg.mode == "dynamic" else None
    initial_c = to_kelvin(cfg.initial_tco) if cfg.mode == "dynamic" else None
    result = ElectricEIR(per, cp).simulate(
        frame, mode=cfg.mode, tau_evap_s=cfg.tau_evap_s, tau_cond_s=cfg.tau_cond_s,
        initial_teo_K=278.15 if initial_e is None else initial_e,
        initial_tco_K=298.15 if initial_c is None else initial_c, default_dt_s=cfg.interval_s)
    return result, {"model_version": "Buildings-13.0.0-ElectricEIR-python-1", "engine": cfg.engine,
                    "solver": "SciPy BDF，rtol=1e-9，atol=1e-9 K" if cfg.mode == "dynamic" else "Brent 标量稳态能量方程求根",
                    "settings": cfg.model_dump(), "performance_record": "custom" if cfg.performance else cfg.record_id,
                    "performance_parameters": per.model_dump(), "source_sha256": catalogue()["source_sha256"],
                    "effective_capacitances_J_K": {"evaporator": per.mEva_flow_nominal*cfg.tau_evap_s*cp, "condenser": per.mCon_flow_nominal*cfg.tau_cond_s*cp},
                    "initial_state": "每个 run_id 独立固定初态；未填时冷冻出水 5°C、冷却出水 25°C，不从测量自动初始化。稳态模式不使用初态。",
                    "time_rule": "输入在 t_i 至 t_(i+1) 零阶保持；t0 输出初态，不外推末点。稳态模式逐行独立求解。"}


def run_workbench(request: WorkbenchRequest) -> dict[str, Any]:
    schema = request.data_schema
    if not all(math.isfinite(v) for v in (schema.water_specific_heat_J_kgK, schema.water_density_kg_m3)):
        raise ValueError("比热和密度必须为有限正数。")
    frame, issues, resolved_schema, input_inference = _normalize(request)
    effective_request = request.model_copy(update={"data_schema": resolved_schema})
    if input_inference.get("assumed_source_units") and effective_request.simulation.kind == "series" and effective_request.simulation.time_mode == "interval":
        time_column = resolved_schema.column_map.get("timestamp")
        if time_column:
            normalized_time = "".join(char for char in time_column.casefold() if char.isalnum())
            inferred_time_mode = "minutes" if "minute" in normalized_time else "seconds"
            effective_request = effective_request.model_copy(update={
                "simulation": effective_request.simulation.model_copy(update={"time_mode": inferred_time_mode})
            })
            input_inference["assumed_time_mode"] = inferred_time_mode
    schema = resolved_schema
    metadata: dict[str, Any] = {"operation": request.operation, "model_version": "water-side-physics-1.0", "schema": schema.model_dump(),
                               "input_rows": len(frame), "output_units": UNITS,
                               "equations": ["Qe = m_e × cp × (TEI − TEO)", "Qc = m_c × cp × (TCO − TCI)",
                                             "COP = Qe / P", "balance = Qc − Qe − P"]}
    notes = ["表格中的“—”表示该项缺少必要测量，无法计算，不代表数值为零。文件按原始顺序处理，不自动插值、删除重复点或把不同试验拼成一条序列。"]
    if input_inference:
        metadata["input_inference"] = input_inference
        notes.append("本次请求使用了 ASHRAE 标准表头的后端自动映射；列名和单位假设已记录在运行参数中，请核对来源工作表。")
    if request.operation == "simulate":
        frame, simulation_meta = _simulate(frame, effective_request)
        metadata.update(simulation_meta)
        metadata["equations"] += eir_model_definition()["equations"]
        notes += ["本次使用 Buildings 13.0.0 ElectricEIR 水冷制冷模式：机组参数和三条性能曲线计算冷量、压缩机功率与 COP；实测功率只用于对照，不驱动仿真。功率不含水泵、风机。",
                  "动态热容 C = 额定质量流量 × 时间常数 × 比热；温度控制为源码中的理想设定值控制，低负荷启停使用平均循环比，不模拟实际开停脉冲。",
                  "仅对齐所列 ElectricEIR 源码方程；不含水力网络、反向/零流量、热回收切换或其他冷水机组模型。已通过现有参考工况的 OpenModelica 数值对照；目标机组仍需独立验证。",
                  "动态过程水侧换热与模型冷量的差值进入储热项，不应直接视为稳态能量失衡。曲线温度范围仅用于提示，不自动截断。"]
    result = _calculate(frame, schema.water_specific_heat_J_kgK)
    for field in ("TEI", "TEO", "TCI", "TCO", "TSet"):
        result[field + "_C"] = result.pop(field + "_K") - 273.15
    result = result.drop(columns="P_W")
    warnings = []
    def warn(mask: pd.Series, message: str) -> None:
        if mask.any():
            warnings.append({"count": int(mask.sum()), "rows": result.loc[mask, "source_row"].head(10).tolist(), "message": message})
    warn(result.TEI_C < result.TEO_C, "冷冻水温差方向异常，请检查传感器、映射和运行模式。")
    warn(result.TCO_C < result.TCI_C, "冷却水温差方向异常，请检查进出水定义。")
    warn((result.evap_flow_kg_s == 0) | (result.cond_flow_kg_s == 0), "存在零流量，请核实停机状态或流量传感器。")
    scale = result.condenser_heat_kW.abs().clip(lower=1)
    if request.operation == "calculate":
        warn(result.energy_balance_error_kW.abs() / scale > 0.15, "水侧稳态能量平衡偏差超过冷凝热的 15%；检查单位、测量同步和是否处于稳态。该提示不能单独诊断故障。")
    else:
        per = metadata["performance_parameters"]
        nominal_cap = biquadratic(per["capFunT"], per["TEvaLvg_nominal"]-273.15, per["TConEnt_nominal"]-273.15)
        if not .9 <= nominal_cap <= 1.1:
            warnings.append({"count":1,"rows":[],"message":f"额定工况 capFunT={nominal_cap:.5g} 超出源码检查范围 0.9–1.1，请检查性能曲线系数。"})
        warn(result.curve_out_of_range > 0, "工况超出所选机组的性能曲线温度范围，当前使用外推；请核实机组参数和输入工况。")
        warn((result.EIRFunT < 0) | (result.EIRFunPLR < 0) | (result.simulated_power_kW < 0), "性能曲线产生负能耗系数或负功率，结果不具备可信物理意义；请更换或校准曲线。")
        temperature_mask = (result.simulated_TEO_C < 0) | (result.simulated_TCO_C > 60)
        metadata["temperature_reference_checks_C"] = {"simulated_TEO_C_min": 0, "simulated_TCO_C_max": 60,
                                                      "meaning": "参考阈值，不是机组额定运行边界；只提示，不触发停机或限制温度。"}
        warn(temperature_mask, "模拟温度触发参考检查：冷冻水出水低于 0°C，或冷却水出水高于 60°C。这不等于真实机组发生故障；请核对温度/流量单位、初始温度和模型参数。当前模型没有防冻停机或高温保护逻辑，触发提示后仍会继续计算。")
        if temperature_mask.any():
            warnings[-1]["temperature_ranges_C"] = {
                "TEO_min": float(result.simulated_TEO_C.min()), "TEO_max": float(result.simulated_TEO_C.max()),
                "TCO_min": float(result.simulated_TCO_C.min()), "TCO_max": float(result.simulated_TCO_C.max()),
            }
    missing_outputs = [name for name in ("cooling_capacity_kW", "condenser_heat_kW", "COP", "energy_balance_error_kW") if result[name].isna().any()]
    if missing_outputs:
        notes.append("部分实测计算结果缺少输入：" + "、".join(missing_outputs) + "。制冷量需要冷冻侧温差与流量；COP 还需要正功率。")
    metadata["output_rows"] = len(result)
    return json_safe({"metadata": metadata, "records": result.to_dict("records"),
                      "issues": issues, "warnings": warnings, "notes": notes})


@router.get("/eir/catalogue")
def eir_catalogue() -> dict[str, Any]:
    data = catalogue()
    return {**data, "default_record_id": DEFAULT_RECORD,
            "records": [record for record in data["records"] if record["condenser_medium"] == "water"]}


@router.post("/run")
def run(request: WorkbenchRequest) -> dict[str, Any]:
    try:
        return run_workbench(request)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(422, str(exc)) from exc
