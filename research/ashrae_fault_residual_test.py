"""Exploratory file-held-out residual detection on RP-1043 steady tests."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ashrae_model_comparison import read_steady, model_frame
from chiller_app.model.electric_eir import DEFAULT_RECORD, ElectricEIR, performance
from chiller_app.model.eir_calibration import fit_power_scale, calibrated_performance
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FAULT_FILES = {
    "condenser_fouling_cf12": ("Condenser fouling/cf12.xls", "Condenser fouling"),
    "condenser_flow_fwc20": ("Reduced condenser water flow/fwc20.xls", "Reduced condenser flow"),
    "evaporator_flow_fwe20": ("Reduced evaporator water flow/fwe20.xls", "Reduced evaporator flow"),
    "refrigerant_leak_rl20": ("Refrigerant leak/rl20.xls", "Refrigerant leak"),
}

def xcols(raw):
    x = pd.DataFrame({name: (raw[src]-32)*(5/9) for name,src in {"TEI_C":"TEI","TEO_C":"TEO","TCI_C":"TCI","TCO_C":"TCO","TSet_C":"TWE_set"}.items()})
    x["deltaTe_C"] = x.TEI_C - x.TEO_C
    return x

def main(root: Path, out: Path):
    base = root / "Benchmark Tests"
    tr = read_steady(base/"normal.xls"); va = read_steady(base/"normal1.xls"); te = read_steady(base/"normal2.xls")
    per = performance(DEFAULT_RECORD)
    fit = fit_power_scale(model_frame(tr), per, allow_extrapolation=True)
    eir = ElectricEIR(calibrated_performance(per,fit["power_scale"]))
    features = ["TEO_C","TCI_C","deltaTe_C"]
    model = make_pipeline(StandardScaler(),Ridge(alpha=.1)).fit(xcols(tr)[features],tr["kW"])
    def pred(raw):
        f = model_frame(raw); p = eir.simulate(f,mode="steady").simulated_power_kW.to_numpy()
        q = model.predict(xcols(raw)[features]); return p,q
    _, pv = pred(va)
    threshold = float(np.quantile(np.abs(va["kW"].to_numpy()-pv),.95,method="higher"))
    datasets = {"healthy_final_test":te}; labels = {"healthy_final_test":"healthy"}
    for key,(rel,label) in FAULT_FILES.items():
        datasets[key] = read_steady(root/rel); labels[key] = label
    results = {}
    for key,raw in datasets.items():
        pe,ps = pred(raw); y = raw["kW"].to_numpy(); re=pe-y; rs=ps-y
        results[key] = {"label":labels[key],"n":len(raw),
            "eir_power_error_kW":{"mae":float(np.mean(np.abs(re))),"bias":float(np.mean(re)),"mape_pct":float(np.mean(np.abs(re/y))*100)},
            "sparse_linear_power_error_kW":{"mae":float(np.mean(np.abs(rs))),"bias":float(np.mean(rs)),"mape_pct":float(np.mean(np.abs(rs/y))*100)},
            "sparse_linear_abs_residual_detection":{"threshold_kW":threshold,"detected_fraction":float(np.mean(np.abs(rs)>threshold)),"median_abs_residual_kW":float(np.median(np.abs(rs)))}}
    report = {"purpose":"Exploratory steady-state fault residual test; no fault-onset times, no online delay claim",
        "train":"normal.xls","threshold_validation":"normal1.xls; 95th percentile abs sparse-linear power residual",
        "final_healthy_test":"normal2.xls","eir_scale":fit["power_scale"],"sparse_linear_features":features,
        "validation_threshold_kW":threshold,"files":results,
        "limitations":["One file per selected injected-fault level; no group uncertainty estimate","Experiments/date/protocol differ; match reference conditions before drawing conclusions","Residual detection is not unique fault diagnosis","EIR may extrapolate outside performance temperature range","Steady summary rows only"]}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("data_dir",type=Path);parser.add_argument("--output",type=Path,default=Path("artifacts/ashrae_fault_residual_test.json"));args=parser.parse_args();main(args.data_dir,args.output)
