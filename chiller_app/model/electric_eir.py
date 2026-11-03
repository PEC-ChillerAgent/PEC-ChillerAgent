"""Buildings 13.0.0 ElectricEIR cooling-mode equations, ported to Python.

See BUILDINGS_LICENSE.txt. Water has constant cp and density; positive imposed
flows replace the Modelica hydraulic network. No refrigerant-cycle solver.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

DEFAULT_RECORD = "ElectricEIRChiller_McQuay_WSC_471kW_5_89COP_Vanes"


class EIRPerformance(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    QEva_flow_nominal: float = Field(lt=0)
    COP_nominal: float = Field(gt=0)
    PLRMin: float = Field(gt=0)
    PLRMinUnl: float = Field(ge=0)
    PLRMax: float = Field(gt=0)
    etaMotor: float = Field(ge=0, le=1)
    mEva_flow_nominal: float = Field(gt=0)
    mCon_flow_nominal: float = Field(gt=0)
    TEvaLvg_nominal: float = Field(ge=200, le=400)
    TConEnt_nominal: float = Field(ge=200, le=400)
    TEvaLvgMin: float = Field(ge=200, le=400)
    TEvaLvgMax: float = Field(ge=200, le=400)
    TConEntMin: float = Field(ge=200, le=400)
    TConEntMax: float = Field(ge=200, le=400)
    capFunT: tuple[float, float, float, float, float, float]
    EIRFunT: tuple[float, float, float, float, float, float]
    EIRFunPLR: tuple[float, float, float]

    @model_validator(mode="after")
    def valid_limits(self):
        if not self.PLRMin <= self.PLRMinUnl < self.PLRMax:
            raise ValueError("须满足 0 < PLRMin ≤ PLRMinUnl < PLRMax")
        if self.TEvaLvgMin > self.TEvaLvgMax or self.TConEntMin > self.TConEntMax:
            raise ValueError("性能曲线温度下限不能大于上限")
        return self


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads(Path(__file__).with_name("buildings_eir_catalogue.json").read_text(encoding="utf-8"))


def performance(record_id: str, custom: EIRPerformance | None = None) -> EIRPerformance:
    if custom is not None:
        return custom
    for record in catalogue()["records"]:
        if record["id"] == record_id:
            if record["condenser_medium"] != "water":
                raise ValueError("此应用仅实现水冷模式，不能选择风冷机组参数")
            return EIRPerformance.model_validate(record["parameters"])
    raise ValueError(f"未找到机组参数记录：{record_id}")


def biquadratic(a, x, y):
    return a[0] + x * (a[1] + a[2] * x) + y * (a[3] + a[4] * y) + a[5] * x * y


def reg_step(x, y1, y2, width):
    if x > width:
        return y1
    if x < -width:
        return y2
    if width == 0:
        return (y1 + y2) / 2
    z = x / width
    return z * (z * z - 3) * (y2 - y1) / 4 + (y1 + y2) / 2


def smooth_max(a, b, width):
    return reg_step(a - b, a, b, width)


def smooth_min(a, b, width):
    return reg_step(b - a, a, b, width)


class ElectricEIR:
    def __init__(self, per: EIRPerformance, cp: float = 4184.0):
        if not np.isfinite(cp) or cp <= 0:
            raise ValueError("比热必须为有限正数")
        self.per, self.cp = per, cp

    def evaluate(self, teo: float, tei: float, tci: float, flow: float,
                 tset: float, on: bool = True) -> dict[str, float]:
        """Literal cooling branch of PartialElectric, with signed heat flows (W)."""
        p = self.per
        small = p.QEva_flow_nominal * 1e-9
        cap = smooth_max(1e-6, biquadratic(p.capFunT, teo - 273.15, tci - 273.15), 1e-7) if on else 0.0
        eir_t = biquadratic(p.EIRFunT, teo - 273.15, tci - 273.15) if on else 0.0
        available = p.QEva_flow_nominal * cap
        requested = smooth_min(flow * self.cp * (tset - tei), small, -small / 100) if on else 0.0
        plr1 = smooth_min(requested / (available + small), p.PLRMax, p.PLRMax / 100) if on else 0.0
        plr2 = smooth_max(p.PLRMinUnl, plr1, p.PLRMinUnl / 100) if on else 0.0
        cr = smooth_min(plr1 / p.PLRMin, 1, .001) if on else 0.0
        eir_plr = p.EIRFunPLR[0] + p.EIRFunPLR[1] * plr2 + p.EIRFunPLR[2] * plr2**2 if on else 0.0
        power = -available / p.COP_nominal * eir_t * eir_plr * cr
        qe = smooth_max(requested, available, -small / 10) if on else 0.0
        qc = -qe + power * p.etaMotor
        if power == small:
            raise ValueError("性能曲线导致 COP 分母为零，请校准或更换曲线")
        cop = -qe / (power - small) if on else 0.0
        return dict(QEva_flow_ava_W=available, QEva_flow_set_W=requested, QEva_flow_W=qe,
                    QCon_flow_W=qc, simulated_power_kW=power / 1000,
                    simulated_cooling_capacity_kW=-qe / 1000, simulated_condenser_heat_kW=qc / 1000,
                    simulated_COP=cop, PLR1=plr1, PLR2=plr2, CR=cr,
                    capFunT=cap, EIRFunT=eir_t, EIRFunPLR=eir_plr)

    def simulate(self, frame: pd.DataFrame, *, mode: Literal["dynamic", "steady"] = "dynamic",
                 tau_evap_s: float = 30, tau_cond_s: float = 30,
                 initial_teo_K: float = 278.15, initial_tco_K: float = 298.15,
                 default_dt_s: float = 60) -> pd.DataFrame:
        required = ["TEI_K", "TCI_K", "evap_flow_kg_s", "cond_flow_kg_s", "TSet_K", "operating_status"]
        data = frame.reset_index(drop=True).copy()
        if data.empty or not set(required).issubset(data):
            raise ValueError("ElectricEIR 需要两侧进水温度、正流量、设定温度和启停状态")
        if not np.isfinite(data[required].to_numpy(dtype=float)).all():
            raise ValueError("ElectricEIR 输入存在空值或非有限值")
        if (data[["evap_flow_kg_s", "cond_flow_kg_s"]] <= 0).any().any():
            raise ValueError("ElectricEIR 当前只支持两侧正向且非零流量")
        if not data.operating_status.isin([0, 1]).all():
            raise ValueError("启停状态只能是 0 或 1")
        if mode not in {"dynamic", "steady"}:
            raise ValueError("未知的仿真模式")
        if not all(np.isfinite(x) and x > 0 for x in (tau_evap_s, tau_cond_s, default_dt_s)):
            raise ValueError("时间常数和时间间隔必须为有限正数")
        if not all(np.isfinite(x) and 200 <= x <= 400 for x in (initial_teo_K, initial_tco_K)):
            raise ValueError("初始温度必须为 200–400 K 内的有限值")
        if "run_id" not in data:
            data["run_id"] = "default"
        if data.run_id.isna().any():
            raise ValueError("run_id 不能留空")
        ce = self.per.mEva_flow_nominal * tau_evap_s * self.cp
        cc = self.per.mCon_flow_nominal * tau_cond_s * self.cp
        output = data.copy()
        for _, group in data.groupby("run_id", sort=False):
            if "elapsed_s" in group:
                times = pd.to_numeric(group.elapsed_s, errors="coerce").to_numpy(dtype=float)
            elif "timestamp" in group:
                dates = pd.to_datetime(group.timestamp, errors="coerce", utc=True)
                times = (dates - dates.iloc[0]).dt.total_seconds().to_numpy()
            else:
                times = np.arange(len(group)) * default_dt_s
            times = times - times[0]
            if not np.isfinite(times).all() or (np.diff(times) <= 0).any():
                raise ValueError("每个 run_id 内的时间必须完整、严格递增")
            state = np.array([initial_teo_K, initial_tco_K])
            previous = None
            for pos, (index, row) in enumerate(group.iterrows()):
                def evaluate(teo, inputs):
                    return self.evaluate(teo, inputs.TEI_K, inputs.TCI_K, inputs.evap_flow_kg_s,
                                         inputs.TSet_K, bool(inputs.operating_status))
                if mode == "steady":
                    def residual(teo):
                        return row.evap_flow_kg_s * self.cp * (row.TEI_K - teo) + evaluate(teo, row)["QEva_flow_W"]
                    # Positive cooling flow puts the root between setpoint and inlet,
                    # apart from the source's tiny no-load regularization.
                    lo, hi = min(row.TSet_K, row.TEI_K) - .01, row.TEI_K + .01
                    if residual(lo) * residual(hi) > 0:
                        raise ValueError(f"第 {index+1} 行稳态温度方程未找到有效根，请检查曲线和工况")
                    state[0] = brentq(residual, lo, hi, xtol=1e-10)
                    heat = evaluate(state[0], row)["QCon_flow_W"]
                    state[1] = row.TCI_K + heat / (row.cond_flow_kg_s * self.cp)
                elif previous is not None:
                    def rhs(_, y):
                        loads = evaluate(y[0], previous)
                        return [(previous.evap_flow_kg_s * self.cp * (previous.TEI_K - y[0]) + loads["QEva_flow_W"]) / ce,
                                (previous.cond_flow_kg_s * self.cp * (previous.TCI_K - y[1]) + loads["QCon_flow_W"]) / cc]
                    solution = solve_ivp(rhs, (0, times[pos] - times[pos-1]), state,
                                         method="BDF", rtol=1e-9, atol=1e-9)
                    if not solution.success:
                        raise ValueError(f"动态求解失败：{solution.message}")
                    state = solution.y[:, -1]
                loads = evaluate(state[0], row)
                values = dict(loads, elapsed_s=times[pos], simulated_TEO_C=state[0]-273.15,
                              simulated_TCO_C=state[1]-273.15,
                              simulated_evap_water_kW=row.evap_flow_kg_s*self.cp*(row.TEI_K-state[0])/1000,
                              simulated_cond_water_kW=row.cond_flow_kg_s*self.cp*(state[1]-row.TCI_K)/1000)
                values["evap_storage_kW"] = values["simulated_evap_water_kW"] - values["simulated_cooling_capacity_kW"]
                values["cond_storage_kW"] = values["simulated_condenser_heat_kW"] - values["simulated_cond_water_kW"]
                values["curve_out_of_range"] = float(not (self.per.TEvaLvgMin <= state[0] <= self.per.TEvaLvgMax and self.per.TConEntMin <= row.TCI_K <= self.per.TConEntMax))
                if not np.isfinite(list(values.values())).all():
                    raise ValueError("性能曲线或状态产生非有限结果")
                for key, value in values.items():
                    output.loc[index, key] = value
                previous = row
        return output


def eir_model_definition() -> dict:
    return {"name": "buildings_electric_eir", "version": "Buildings-13.0.0-python-1",
            "components": ["Evaporator water side", "Condenser water side", "ElectricEIR performance curves", "Water-side thermal capacitances"],
            "states": ["TEvaLvg_K", "TConLvg_K"],
            "parameters": {"performance": "Selected water-cooled ElectricEIR record or explicit custom parameters",
                           "tau_evap_s": {"default": 30, "unit": "s"},
                           "tau_cond_s": {"default": 30, "unit": "s"},
                           "water_cp_J_kgK": {"default": 4184, "unit": "J/(kg K)"}},
            "solver": {"steady": "Brent scalar energy-balance root",
                       "dynamic": "SciPy BDF, rtol=1e-9, atol=1e-9 K",
                       "input_hold": "zero-order hold; independent initial state per run_id"},
            "inputs": ["TEI_K", "TCI_K", "evap_flow_kg_s", "cond_flow_kg_s", "TSet_K", "operating_status"],
            "outputs": ["simulated_TEO_C", "simulated_TCO_C", "simulated_cooling_capacity_kW", "simulated_power_kW", "simulated_COP", "PLR1", "PLR2", "CR"],
            "equations": ["QEva_ava = QEva_nominal * capFunT(TEvaLvg_C,TConEnt_C)",
                          "P = -QEva_ava/COP_nominal * EIRFunT * EIRFunPLR(PLR2) * CR",
                          "QCon = -QEva + etaMotor*P", "COP = -QEva/(P-Q_small)",
                          "C_e*dTEvaLvg/dt = m_e*cp*(TEvaEnt-TEvaLvg)+QEva",
                          "C_c*dTConLvg/dt = m_c*cp*(TConEnt-TConLvg)+QCon",
                          "C = m_flow_nominal*tau*cp"],
            "limitations": ["仅 ElectricEIR 水冷制冷模式；不含热回收切换、风冷、水力压降、流向反转或其他 Chillers 模型。",
                            "现有参考工况已通过 OpenModelica 数值对照；其他机组、工况与初始化设置仍需独立验证。",
                            "数据记录只适用于对应机组及有效工况；新机组须提供或校准曲线。"],
            "source_sha256": catalogue()["source_sha256"]}
