"""Find and import peer station modules without copying the controller."""
import os
import sys
from pathlib import Path


def station_path(system_dir=None):
    root = Path(system_dir or os.environ.get("PAC_SYSTEM_DIR") or
                (Path(__file__).resolve().parents[2] / "claude-code" / "PAC2026_system"))
    station = root / "station"
    if not (station / "grasp.py").is_file():
        raise ValueError(f"station/grasp.py missing: {root}")
    sys.path.insert(0, str(station))
    return station
