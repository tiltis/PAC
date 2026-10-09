"""Read live depth/plan only. Never import app or open a robot port."""
from __future__ import annotations

import argparse
import json
import sys

from bootstrap import station_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--system-dir", help="existing PAC2026_system directory")
    ap.add_argument("--sensor-url", default="http://127.0.0.1:8001")
    ap.add_argument("--handeye", help="measured hand-eye JSON; no synthetic default")
    args = ap.parse_args(argv)
    station = station_path(args.system_dir)
    import handeye
    from sensor_client import SensorClient
    from guard import GuardedVisionPicker

    sensor = SensorClient(args.sensor_url)
    try:
        he = handeye.load(args.handeye or station / "calib" / "handeye.json")
        picker = GuardedVisionPicker(sensor, he, dry_run=True)
        loc = picker.locate()
        plan = picker.plan(loc)
        print(json.dumps({"mode": "preview_only", "motion_enabled": False,
                          "system_dir": str(station.parent), "locate": loc, "plan": plan},
                         ensure_ascii=True, indent=2, allow_nan=False))
        return 0 if plan.get("ok") else 2
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({"mode": "preview_only", "motion_enabled": False,
                          "error": f"{type(e).__name__}: {e}"}, ensure_ascii=True))
        return 2
    finally:
        sensor.close()


if __name__ == "__main__":
    sys.exit(main())
