"""Controlled sparse-measurement and virtual-flow experiment.

Complete workbook flow/power channels are retained as evaluation reference and
hidden from the virtual-flow inversion itself. Only healthy normal1 is used in
this first experiment; no fault claims or event-delay estimates are made.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import xlrd
from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chiller_app.model.electric_eir import DEFAULT_RECORD, ElectricEIR, performance
from chiller_app.model.eir_calibration import calibrated_performance, error_metrics

CP, RHO = 4184., 995.586
GPM_TO_KGS = 3.785411784e-3 * RHO / 60


def read_complete(path: Path) -> pd.DataFrame:
    book = xlrd.open_workbook(str(path), on_demand=True)
    sheet_name = next((name for name in book.sheet_names() if name.lower().startswith("complete")), None)
    if sheet_name is None:
        raise ValueError(f"No complete-data sheet in {path.name}: {book.sheet_names()}")
    sheet = book.sheet_by_name(sheet_name)
    frame = pd.DataFrame([sheet.row_values(i) for i in range(1, sheet.nrows)], columns=sheet.row_values(0))
    frame = frame.apply(pd.to_numeric, errors="coerce")
    needed = ["Time", "TWE_set", "TEI", "TEO", "TCI", "TCO", "kW", "FWE", "FWC"]
    frame = frame.dropna(subset=needed).copy()
    frame = frame[(frame.FWE > 1) & (frame.FWC > 1) & (frame.kW > 1)]
    frame = frame.sort_values("Time", kind="stable").drop_duplicates("Time", keep="last")
    return frame.reset_index(drop=True)


def make_input(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "TEI_K": (raw.TEI-32)*(5/9)+273.15,
        "TCI_K": (raw.TCI-32)*(5/9)+273.15,
        "evap_flow_kg_s": raw.FWE*GPM_TO_KGS,
        "cond_flow_kg_s": raw.FWC*GPM_TO_KGS,
        "TSet_K": (raw.TWE_set-32)*(5/9)+273.15,
        "operating_status": 1,
        "elapsed_s": raw.Time.to_numpy(dtype=float),
    })


def virtual_flows(raw: pd.DataFrame, per, cp=CP) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Use only hand-copy-available four water temperatures, setpoint and P.

    Measured FWE/FWC are withheld. Estimate FWE by solving the ElectricEIR
    power equation at measured TEO; estimate FWC from predicted condenser duty
    and measured TCO. Both estimates are then scored against held-back flows.
    Since power enters the inversion, power residual is deliberately not scored.
    """
    engine = ElectricEIR(per, cp)
    me_hat, mc_hat, valid, condenser_delta_c = [], [], [], []
    for row in raw.itertuples(index=False):
        tei=(row.TEI-32)*(5/9)+273.15
        teo=(row.TEO-32)*(5/9)+273.15
        tci=(row.TCI-32)*(5/9)+273.15
        tco=(row.TCO-32)*(5/9)+273.15
        tset=(row.TWE_set-32)*(5/9)+273.15
        pobs=row.kW
        def residual(me):
            return engine.evaluate(teo, tei, tci, me, tset, True)["simulated_power_kW"] - pobs
        lo=max(.01, per.mEva_flow_nominal*.05)
        hi=per.mEva_flow_nominal*3
        try:
            flo, fhi=residual(lo), residual(hi)
            if flo*fhi > 0:
                me=np.nan; mc=np.nan; ok=False
                condenser_delta_c.append(tco-tci)
            else:
                me=brentq(residual,lo,hi,xtol=1e-8)
                loads=engine.evaluate(teo,tei,tci,me,tset,True)
                delta=tco-tci
                condenser_delta_c.append(delta)
                mc=loads["QCon_flow_W"]/(cp*delta) if delta>0 else np.nan
                ok=bool(np.isfinite(me) and np.isfinite(mc) and mc>0)
        except (ValueError, ZeroDivisionError, OverflowError):
            me=np.nan;mc=np.nan;ok=False
            condenser_delta_c.append(np.nan)
        me_hat.append(me);mc_hat.append(mc);valid.append(ok)
    return np.array(me_hat),np.array(mc_hat),np.array(valid),np.array(condenser_delta_c)


def flow_metrics(actual, predicted, mask) -> dict:
    a=np.asarray(actual)[mask];p=np.asarray(predicted)[mask]
    if not len(a): return {"n":0,"coverage":0.}
    result=error_metrics(a,p);result["coverage"]=float(len(a)/len(mask))
    result["mae_pct_of_median_actual"]=float(100*np.mean(np.abs(p-a))/np.median(a))
    result["median_absolute_error"]=float(np.median(np.abs(a-p)))
    result["p90_absolute_error"]=float(np.quantile(np.abs(a-p),.9))
    return result


def run(data_dir: Path, output: Path) -> dict:
    raw=read_complete(data_dir/"Benchmark Tests"/"normal1.xls")
    # Keep points that are on or near the default curves for an interpretable
    # first baseline; report exclusions explicitly, never silently score them.
    frame=make_input(raw)
    per=performance(DEFAULT_RECORD)
    all_pred=ElectricEIR(per,CP).simulate(frame,mode="steady")
    in_range=all_pred.curve_out_of_range.to_numpy()==0
    raw=raw.loc[in_range].reset_index(drop=True);frame=frame.loc[in_range].reset_index(drop=True)
    base_input=make_input(raw)
    base_pred=ElectricEIR(per,CP).simulate(base_input,mode="steady")
    power_scale=1.3216745567092523 # frozen from normal.xls calibration; no normal1 refit
    fit_per=calibrated_performance(per,power_scale)
    fitted_pred=ElectricEIR(fit_per,CP).simulate(base_input,mode="steady")
    fwe_hat,fwc_hat,valid,delta_cond=virtual_flows(raw,fit_per)
    valid_delta=valid & (delta_cond>=1.)
    report={"purpose":"healthy normal1 sparse observability only; power inversion uses measured power, so no independent power-residual claim",
            "source":"Benchmark Tests/normal1.xls Complete",
            "quality":{"usable_after_basic_cleaning":len(frame),"excluded_outside_default_curve":int((~in_range).sum()),
                        "assumed_source_interval_s":10,"deduplicated_time_rows":int(len(frame)<len(all_pred))},
            "frozen_normal_scale":power_scale,
            "full_measurement_power_baseline":{"default":error_metrics(raw.kW,base_pred.simulated_power_kW),
                                               "calibrated":error_metrics(raw.kW,fitted_pred.simulated_power_kW)},
            "virtual_flow":{"available_rows":int(valid.sum()),"total_rows":len(raw),
                             "evaporator_kg_s":flow_metrics(raw.FWE.to_numpy()*GPM_TO_KGS,fwe_hat,valid),
                             "condenser_kg_s_all_positive_dT":flow_metrics(raw.FWC.to_numpy()*GPM_TO_KGS,fwc_hat,valid),
                             "condenser_kg_s_deltaT_at_least_1C":flow_metrics(raw.FWC.to_numpy()*GPM_TO_KGS,fwc_hat,valid_delta),
                             "condenser_deltaT_C":{"min":float(np.nanmin(delta_cond)),"median":float(np.nanmedian(delta_cond)),
                                                      "under_1C_count":int(np.sum(valid & (delta_cond<1.))) }},
            "downsampling":{},
            "limits":["Excludes points outside the default curve domain; findings do not cover those field conditions",
                        "Single benchmark experiment; not independent field validation",
                        "Virtual evaporator flow uses measured power and measured TEO; its flow error is the score, not power error",
                        "The dataset-derived power correction was calibrated on normal.xls and frozen before this analysis"]}
    # Examine retained measurement density. For each requested cadence, retain
    # nearest preceding original row within half a cadence; report count/coverage.
    times=raw.Time.to_numpy(dtype=float)
    for minutes in (1,5,15):
        cadence=minutes*60
        targets=np.arange(times[0],times[-1]+1e-9,cadence)
        indices=np.searchsorted(times,targets,side="left")
        indices=np.clip(indices,0,len(times)-1)
        keep=np.unique(indices)
        selected=raw.iloc[keep]
        report["downsampling"][f"{minutes}_min"]={"retained_points":len(keep),
            "observed_span_h":float((times[-1]-times[0])/3600),
            "cadence_minutes":minutes,
            "flow_virtual_sample":{"note":"recompute inverse flow using only retained rows; point accuracy, not interpolation accuracy"}}
        shat,chat,smask,sdelta=virtual_flows(selected,fit_per)
        smask_delta=smask & (sdelta>=1.)
        report["downsampling"][f"{minutes}_min"]["virtual_flow"]={
            "evaporator_kg_s":flow_metrics(selected.FWE.to_numpy()*GPM_TO_KGS,shat,smask),
            "condenser_kg_s_all_positive_dT":flow_metrics(selected.FWC.to_numpy()*GPM_TO_KGS,chat,smask),
            "condenser_kg_s_deltaT_at_least_1C":flow_metrics(selected.FWC.to_numpy()*GPM_TO_KGS,chat,smask_delta),
            "condenser_deltaT_under_1C_count":int(np.sum(smask & (sdelta<1.))),
            "successful_inversions":int(smask.sum())}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("data_dir",type=Path)
    parser.add_argument("--output",type=Path,default=Path("artifacts/ashrae_sparse_observability.json"))
    args=parser.parse_args();run(args.data_dir,args.output)
