from pathlib import Path
import shutil
from uuid import uuid4

import pytest


@pytest.fixture
def data_dir():
    root = (Path(__file__).resolve().parents[2] / "outputs" / "agent_test_runs").resolve()
    directory = root / uuid4().hex
    directory.mkdir(parents=True)
    yield directory
    # Only remove this test's UUID directory under the verified workspace root.
    resolved = directory.resolve()
    assert resolved.is_relative_to(root) and resolved != root
    shutil.rmtree(resolved)


@pytest.fixture
def physics_source():
    return {
        "asset_id": "chiller_01",
        "records": [{"tei": 10, "teo": 5, "tci": 30, "tco": 35, "me": 72, "mc": 90, "p": 100}],
        "schema": {
            "column_map": {"TEI_K": "tei", "TEO_K": "teo", "TCI_K": "tci", "TCO_K": "tco",
                           "evap_flow_kg_s": "me", "cond_flow_kg_s": "mc", "P_W": "p"},
            "temperature_unit": "C", "flow_unit": "m3/h", "power_unit": "kW",
            "water_specific_heat_J_kgK": 4180, "water_density_kg_m3": 1000,
        },
    }
