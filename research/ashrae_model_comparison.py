"""File-level healthy-baseline experiment for ASHRAE RP-1043 steady sheets.

Reads original workbooks only. No random row split: normal.xls calibrates,
normal1/normal2 are file-level transfer checks. These are exploratory because
their dates/control histories differ.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import xlrd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sklearn.linear_model import Ridge
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from chiller_app.model.electric_eir import DEFAULT_RECORD, ElectricEIR, performance
from chiller_app.model.eir_calibration import error_metrics, fit_power_scale, calibrated_performance


def read_steady(path: Path) -> pd.DataFrame:
    sheet = xlrd.open_workbook(str(path), on_demand=True).sheet_by_name("Steady States")
    frame = pd.DataFrame([sheet.row_values(i) for i in range(1, sheet.nrows)], columns=sheet.row_values(0))
    frame = frame.apply(pd.to_numeric, errors="coerce")
    required = ["TEI", "TEO", "TCI", "TCO", "TWE_set", "FWE", "FWC", "kW"]
    return frame.dropna(subset=required).reset_index(drop=True)


def model_frame(raw: pd.DataFrame) -> pd.DataFrame:
    # Workbook temperatures are °F; FWE/FWC are US gpm (source audit).
    return pd.DataFrame({
        "TEI_K": (raw.TEI - 32) * (5/9) + 273.15,
        "TCI_K": (raw.TCI - 32) * (5/9) + 273.15,
        "evap_flow_kg_s": raw.FWE * 3.785411784e-3 * 995.586 / 60,
        "cond_flow_kg_s": raw.FWC * 3.785411784e-3 * 995.586 / 60,
        "TSet_K": (raw.TWE_set - 32) * (5/9) + 273.15,
        "operating_status": 1, "P_W": raw["kW"] * 1000,
    })


def evaluate_eir(frame: pd.DataFrame, per, cp=4184) -> dict:
    predicted = ElectricEIR(per, cp).simulate(frame, mode="steady")
    return {"power": error_metrics(frame.P_W / 1000, predicted.simulated_power_kW),
            "predicted_power_kW": predicted.simulated_power_kW.tolist(),
            "curve_out_of_range_rows": int(predicted.curve_out_of_range.sum()),
            "rows": len(frame)}


def compare(data_dir: Path, out_path: Path) -> dict:
    per = performance(DEFAULT_RECORD)
    train_raw = read_steady(data_dir / "Benchmark Tests" / "normal.xls")
    train = model_frame(train_raw)
    fit = fit_power_scale(train, per, allow_extrapolation=True)
    fitted = calibrated_performance(per, fit["power_scale"])

    # Candidate low-order models use measured water temperatures and setpoint;
    # degree/regularization are selected on normal1, normal2 stays untouched.
    feature_sources = {"TEI_C": "TEI", "TEO_C": "TEO", "TCI_C": "TCI",
                       "TCO_C": "TCO", "TSet_C": "TWE_set"}
    x_train = pd.DataFrame({name: (train_raw[column] - 32) * (5/9)
                            for name, column in feature_sources.items()})
    x_train["deltaTe_C"] = x_train.TEI_C - x_train.TEO_C
    y_train = train_raw["kW"].to_numpy()
    validation_raw = read_steady(data_dir / "Benchmark Tests" / "normal1.xls")
    x_validation = pd.DataFrame({name: (validation_raw[column] - 32) * (5/9)
                                 for name, column in feature_sources.items()})
    x_validation["deltaTe_C"] = x_validation.TEI_C - x_validation.TEO_C
    # A deliberately small water-side grey-box: measured evaporator heat load,
    # plus a load × lift correction. This requires a measured flow.
    def physical_features(raw):
        tei=(raw.TEI-32)*(5/9);teo=(raw.TEO-32)*(5/9);tci=(raw.TCI-32)*(5/9)
        me=raw.FWE*3.785411784e-3*995.586/60
        qe=me*4184*(tei-teo)/1000
        lift=tci-teo
        return pd.DataFrame({"cooling_load_kW":qe,"load_times_lift":qe*lift})
    xg_train=physical_features(train_raw)
    xg_validation=physical_features(validation_raw)
    greybox=LinearRegression().fit(xg_train,y_train)
    greybox_val_pred=greybox.predict(xg_validation)
    # Fixed, deployment-oriented low-complexity model: four manually recordable
    # temperatures/setpoint-derived features; no flow or internal sensors.
    simple_features=["TEO_C","TCI_C","deltaTe_C"]
    simple=make_pipeline(StandardScaler(),Ridge(alpha=.1))
    simple.fit(x_train[simple_features],y_train)
    simple_validation=error_metrics(validation_raw["kW"],simple.predict(x_validation[simple_features]))
    candidates = []
    feature_sets = {"linear_4": ["TEO_C", "TCI_C", "deltaTe_C", "TSet_C"],
                    "linear_3": ["TEO_C", "TCI_C", "deltaTe_C"],
                    "linear_5": ["TEI_C", "TEO_C", "TCI_C", "TCO_C", "TSet_C"],
                    "quadratic_4": ["TEO_C", "TCI_C", "deltaTe_C", "TSet_C"]}
    for feature_set_name, features in feature_sets.items():
      for degree in ((1, 2) if feature_set_name == "quadratic_4" else (1,)):
        for alpha in (.01, .1, 1., 10.):
            candidate = make_pipeline(PolynomialFeatures(degree=degree, include_bias=False),
                                      StandardScaler(), Ridge(alpha=alpha))
            candidate.fit(x_train[features], y_train)
            val_pred = candidate.predict(x_validation[features])
            candidates.append({"name": feature_set_name, "features": features, "degree": degree, "alpha": alpha,
                               "validation": error_metrics(validation_raw["kW"], val_pred),
                               "model": candidate})
    selected = min(candidates, key=lambda item: item["validation"]["mae"])
    regression = selected["model"]
    report = {"purpose": "Exploratory file-level baseline transfer; do not treat as final device validation",
              "units": {"temperature_source": "F", "temperature_internal": "K/C as noted",
                          "flow_source": "US gpm", "power_source": "kW"},
              "split": {"training_and_calibration_file": "Benchmark Tests/normal.xls",
                         "validation_and_model_selection_file": "Benchmark Tests/normal1.xls",
                         "final_test_file": "Benchmark Tests/normal2.xls",
                         "rows_train": len(train), "modelica_record": DEFAULT_RECORD},
              "eir_fit": {k:v for k,v in fit.items() if k != "performance_parameters"},
              "interpretable_regression": {"candidate": selected["name"], "features": selected["features"],
                              "selected_degree": selected["degree"],
                              "selected_ridge_alpha": selected["alpha"],
                              "validation_metrics": selected["validation"],
                              "validation_candidates": [{k:v for k,v in item.items() if k != "model"} for item in candidates],
                              "limitations": ["low-order statistical comparison only", "coefficients are not unique physical mechanisms"]},
              "water_side_greybox": {"equation": "P_kW = b0 + b1*Qe_kW + b2*Qe_kW*(TCI-TEO)_C",
                   "features": ["measured evaporator flow and temperature difference", "condenser-to-evaporator temperature lift"],
                   "validation_metrics": error_metrics(validation_raw["kW"],greybox_val_pred),
                   "coefficients": {"intercept":float(greybox.intercept_),**dict(zip(xg_train.columns,greybox.coef_.tolist()))},
                   "limitation": "Requires measured evaporator flow; not available in a no-flow-meter deployment"},
              "sparse_field_linear_model": {"equation": "P_kW = b0 + b1*TEO_C + b2*TCI_C + b3*(TEI-TEO)_C",
                   "features": simple_features,"validation_metrics": simple_validation,
                   "standardized_coefficients": simple[-1].coef_.tolist(),
                   "feature_means_C": simple[0].mean_.tolist(),
                   "feature_scales_C": simple[0].scale_.tolist(),
                   "intercept_kW": float(simple[-1].intercept_),
                   "limitation": "Empirical low-order baseline, not a causal fault model"},
              "files": {}}
    for filename in ["normal.xls", "normal1.xls", "normal2.xls"]:
        raw = train_raw if filename == "normal.xls" else read_steady(data_dir / "Benchmark Tests" / filename)
        frame = train if filename == "normal.xls" else model_frame(raw)
        base = evaluate_eir(frame, per)
        calibrated = evaluate_eir(frame, fitted)
        x = pd.DataFrame({name: (raw[column] - 32) * (5/9) for name, column in feature_sources.items()})
        x["deltaTe_C"] = x.TEI_C - x.TEO_C
        pred = regression.predict(x[selected["features"]])
        pg=greybox.predict(physical_features(raw))
        ps=simple.predict(x[simple_features])
        row = {"n": len(raw), "default_eir": base["power"],
               "default_curve_out_of_range_rows": base["curve_out_of_range_rows"],
               "calibrated_eir": calibrated["power"],
               "calibrated_curve_out_of_range_rows": calibrated["curve_out_of_range_rows"],
               "temperature_only_interpretable_regression": error_metrics(raw["kW"], pred)}
        row["water_side_greybox"] = error_metrics(raw["kW"],pg)
        row["sparse_field_linear_model"] = error_metrics(raw["kW"],ps)
        row["role"] = {"normal.xls": "training/calibration", "normal1.xls": "validation/model selection",
                           "normal2.xls": "final test"}[filename]
        names = regression[0].get_feature_names_out(selected["features"]).tolist()
        row["interpretable_model_terms"] = dict(zip(names, regression[-1].coef_.tolist()))
        row["interpretable_model_intercept"] = float(regression[-1].intercept_)
        row["water_side_greybox_coefficients"] = {"intercept":float(greybox.intercept_),**dict(zip(xg_train.columns,greybox.coef_.tolist()))}
        report["files"][filename] = row
    report["warning"] = ("The uncalibrated default curve is outside its temperature domain for many rows;"
                            " extrapolated EIR metrics are diagnostic only. Calibration and tests are from different"
                            " experiment dates/programs; inspect protocol history before drawing general conclusions.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path, help="ASHRAE RP-1043 Chiller Data directory")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ashrae_model_comparison.json"))
    args = parser.parse_args()
    compare(args.data_dir, args.output)
