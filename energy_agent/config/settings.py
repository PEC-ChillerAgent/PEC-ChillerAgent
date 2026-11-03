"""Local service settings; no language-model credentials are needed."""

import os
from pathlib import Path


def default_data_dir() -> Path:
    configured = os.environ.get("ENERGY_AGENT_DATA_DIR")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "outputs" / "energy_agent"
