"""JSON and CSV-ready report assembly."""

from __future__ import annotations

from typing import Any, Dict, Mapping

import pandas as pd

from chiller_app.diagnosis.rules import diagnose_frame


def build_report(frame: pd.DataFrame, *, source_name: str, model_name: str) -> Dict[str, Any]:
    diagnosis = diagnose_frame(frame)
    return {
        "source": source_name,
        "model": model_name,
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "diagnosis": diagnosis,
        "limitations": [
            "Results depend on input units, sensor quality and available flow measurements.",
            "A data-driven model trained on ASHRAE is not evidence that a separate machine has the same calibration.",
        ],
    }
