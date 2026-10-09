import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from preview_server import create_preview_app


def test_preview_handles_old_sensor_contract_without_motion_or_invented_calibration(tmp_path):
    class Sensor:
        def locate(self): return {"found": False, "reason": "box_not_found"}
    client = TestClient(create_preview_app(tmp_path, sensor=Sensor()))
    assert client.get("/").status_code == 200
    data = client.get("/api/preview").json()
    assert data["motion_enabled"] is False and data["sam_live_connected"] is False
    assert data["readiness"] == {"ok": False, "reason": "handeye_calibration_missing"}
    assert client.post("/api/run").status_code == 404
