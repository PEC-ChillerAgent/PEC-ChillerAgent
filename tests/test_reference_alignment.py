"""Event alignment must select the actual post-event record within time tolerance."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location("compare_eir", Path(__file__).parent / "reference/compare_eir.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_event_epsilon_uses_last_row_without_accepting_nearby_non_tick():
    source = pd.DataFrame({"time": [0, 180, 180 + 4e-10, 180 + 4e-10, 180.001, 240],
                           "power": [1, 10, 10, 0, 999, 0]})
    result = module.right_limit_ticks(source, np.array([0., 180., 240.]))
    assert result.power.tolist() == [1, 0, 0]
    assert result.time.tolist() == [0, 180, 240]
    with pytest.raises(ValueError, match="Missing"):
        module.right_limit_ticks(source, np.array([60.]))


def test_independent_modelica_comparison_report_passes():
    report = module.compare(Path(__file__).parent / "reference")
    assert report["passed"] is True
    assert report["modes"]["dynamic"]["metrics"]["chi.P"]["max_abs"] < 1
