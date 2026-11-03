"""Compare independent OpenModelica CSVs at requested ticks, after events."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from chiller_app.model.electric_eir import DEFAULT_RECORD, ElectricEIR, performance


def right_limit_ticks(actual: pd.DataFrame, ticks: np.ndarray) -> pd.DataFrame:
    """OM emits t, t+epsilon(pre), t+epsilon(post); exact dedup is insufficient."""
    rows = []
    for tick in ticks:
        matches = actual.loc[np.isclose(actual.time, tick, rtol=0, atol=1e-7)]
        if matches.empty:
            raise ValueError(f"Missing OpenModelica tick {tick}")
        rows.append(matches.iloc[-1].copy())
    result = pd.DataFrame(rows).reset_index(drop=True)
    result["time"] = ticks
    return result


def compare(directory: Path, report_dir: Path | None = None) -> dict:
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
    report = {"record_id": DEFAULT_RECORD, "reference": "OpenModelica v1.27.0 / Buildings 13.0.0 / Modelica 4.1.0",
              "alignment": "11 ticks 0..600 s; absolute 1e-7 s matching, last CSV row = right event limit",
              "cases": ["part load", "off at 180s", "restart at 300s", "low load at 360s",
                        "over-capacity at 420s", "condenser inlet step at 480s"],
              "modes": {}, "passed": True}
    columns = {"chi.TEvaLvg": ("simulated_TEO_C", 1., 273.15, 1e-4, "K"),
               "chi.TConLvg": ("simulated_TCO_C", 1., 273.15, 1e-4, "K"),
               "chi.P": ("simulated_power_kW", 1000., 0., 1., "W"),
               "chi.QEva_flow": ("QEva_flow_W", 1., 0., 1., "W"),
               "chi.QCon_flow": ("QCon_flow_W", 1., 0., 1., "W"),
               "chi.COP": ("simulated_COP", 1., 0., 1e-4, "1")}
    for mode in ("dynamic", "steady"):
        path = directory / f"eir_{mode}_res.csv"
        if not path.is_file():
            raise FileNotFoundError(f"OpenModelica reference missing: {path}")
        ticks = np.arange(0., 601., 60.)
        actual = right_limit_ticks(pd.read_csv(path), ticks)
        inputs = pd.DataFrame({"elapsed_s": ticks, "TEI_K": 287.04,
                               "TCI_K": np.where(ticks < 480, 299.82, 298.15),
                               "evap_flow_kg_s": 10.35, "cond_flow_kg_s": 19.24,
                               "TSet_K": 273.15 + np.where(ticks < 360, 8.89, np.where(ticks < 420, 13.5, 2)),
                               "operating_status": ((ticks < 180) | (ticks >= 300)).astype(int)})
        for ref, key in (("chi.TSet", "TSet_K"), ("con.T_in", "TCI_K"), ("chi.on", "operating_status")):
            if not np.allclose(actual[ref], inputs[key], rtol=0, atol=1e-8):
                raise ValueError(f"Reference input differs at event: {ref}")
        result = ElectricEIR(performance(DEFAULT_RECORD), cp=4184).simulate(inputs, mode=mode)
        mode_report = {"points": len(ticks), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "metrics": {}}
        details = pd.DataFrame({"time_s": ticks})
        for original, (python_key, factor, offset, tolerance, unit) in columns.items():
            predicted = result[python_key].to_numpy() * factor + offset
            measured = actual[original].to_numpy()
            error = predicted - measured
            passed = bool(np.isfinite(error).all() and np.max(np.abs(error)) <= tolerance)
            mode_report["metrics"][original] = {"mae": float(np.mean(np.abs(error))),
                "max_abs": float(np.max(np.abs(error))), "tolerance_abs": tolerance, "unit": unit, "passed": passed}
            details[original + "_modelica"] = measured
            details[original + "_python"] = predicted
            details[original + "_error"] = error
            report["passed"] &= passed
        if report_dir is not None:
            details.to_csv(report_dir / f"{mode}_comparison.csv", index=False)
        report["modes"][mode] = mode_report
    if report_dir is not None:
        (report_dir / "alignment_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--report-dir", type=Path, default=Path(__file__).resolve().parents[2] / "artifacts/eir_validation")
    args = parser.parse_args()
    sys.exit(0 if compare(args.directory, args.report_dir)["passed"] else 1)
