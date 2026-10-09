import importlib.util
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence
import server
from depth import DepthFrame
from fake_rig import FakeRig
from rig import RigConfig


class FakeDepth:
    def __init__(self, old=False, missing=False, invalid=False):
        self.old, self.missing, self.invalid = old, missing, invalid
        self.closed = False
    def start(self): pass
    def next_after(self, requested):
        if self.missing: raise TimeoutError("synthetic depth unavailable")
        raw = np.full((8, 10), 0 if self.invalid else 5000, np.uint16)
        return DepthFrame(raw, 0.1, requested - 0.1 if self.old else time.time(), 1234,
                          "synthetic-test", True)
    def health(self, max_age_s=2): return not self.missing
    def close(self): self.closed = True


def sensor_app(tmp_path, source=None, **kwargs):
    return server.create_app(lambda: FakeRig(RigConfig(vis_width=800, vis_height=600, data_root=tmp_path)),
                             (lambda: source) if source else None, **kwargs)


def test_raw_unit_temperature_and_non_pixel_association_are_explicit(tmp_path, monkeypatch):
    calib = tmp_path / "calib"; calib.mkdir()
    monkeypatch.setattr(server, "CALIB_DIR", calib)
    (calib / "timing_policy.json").write_text(json.dumps({"validated": True, "source_id": "synthetic-test-only",
        "max_rgb_lwir_skew_s": 5.0, "max_depth_rgb_skew_s": 5.0}))
    source = FakeDepth()
    with TestClient(sensor_app(tmp_path / "captures", source)) as client:
        result = client.post("/inspect", json={"specimen_id": "S01", "session": "t", "face": "A",
            "trigger_id": "trigger-1", "single_stationary_specimen": True}).json()
        assert result["status"] == "ok" and result["verdict"] == "review"
        data = result["sensor_data"]
        assert data["depth"]["median_mm"] == 500 and data["depth"]["unit"] == "mm"
        assert data["lwir"]["unit"] == "raw_counts" and data["lwir"]["target_temperature_c"] is None
        assert data["association"]["status"] == "linked_under_stationary_specimen_precondition"
        assert data["association"]["same_object_independently_verified"] is False
        assert data["registration"]["rgb_lwir_aligned"] is False  # 픽셀 정합 없이도 요청·시각 연결 가능
        raw = client.get(result["artifacts"]["depth_raw"]).content
        with np.load(io.BytesIO(raw)) as archive: assert archive["raw"].dtype == np.uint16
        meta = client.get(result["artifacts"]["metadata"]).json()
        assert meta["trigger_id"] == "trigger-1" and meta["depth"]["scale_mm_per_unit"] == 0.1
    assert source.closed


@pytest.mark.parametrize("kwargs, reason", [({"old": True}, "depth_before_trigger"),
    ({"missing": True}, "depth_missing"), ({"invalid": True}, "depth_invalid")])
def test_required_depth_missing_old_invalid_is_unmeasurable(tmp_path, kwargs, reason):
    with TestClient(sensor_app(tmp_path, FakeDepth(**kwargs), depth_required=True)) as client:
        result = client.post("/inspect", json={"specimen_id": "S01", "face": "A"}).json()
        assert result["status"] == "ok" and result["verdict"] == "unmeasurable"
        assert reason in result["reasons"]


def test_optional_depth_missing_is_recorded_without_pretending_present(tmp_path):
    with TestClient(sensor_app(tmp_path, FakeDepth(missing=True))) as client:
        assert client.get("/health").json()["ok"] is True
        result = client.post("/inspect", json={"specimen_id": "S01", "face": "A"}).json()
        assert result["verdict"] == "review" and result["sensor_data"]["depth"]["status"] == "missing"
        assert "depth_raw" not in result["artifacts"]


def test_other_specimen_capture_metadata_is_not_relabelled(tmp_path):
    class OtherRig(FakeRig):
        def capture_pair(self, *args, **kwargs):
            out, meta = super().capture_pair(*args, **kwargs)
            meta["specimen_id"] = "OTHER"
            return out, meta
    app = server.create_app(lambda: OtherRig(RigConfig(data_root=tmp_path)))
    with TestClient(app) as client:
        result = client.post("/inspect", json={"specimen_id": "S01", "face": "A"}).json()
        assert result["status"] == "error" and result["verdict"] is None
        assert "불일치" in result["error"]


def test_reused_saved_capture_trigger_is_rejected(tmp_path):
    class CachedRig(FakeRig):
        def capture_pair(self, *args, **kwargs):
            out, meta = super().capture_pair(*args, **kwargs)
            meta["trigger_id"] = "OLD-TRIGGER"
            return out, meta
    with TestClient(server.create_app(lambda: CachedRig(RigConfig(data_root=tmp_path)))) as client:
        result = client.post("/inspect", json={"specimen_id": "S01", "face": "A", "trigger_id": "NEW"}).json()
        assert result["status"] == "error" and "다른 트리거" in result["error"]


def test_rgb_frame_from_before_trigger_is_unmeasurable(tmp_path):
    class OldRig(FakeRig):
        def capture_pair(self, *args, **kwargs):
            out, meta = super().capture_pair(*args, **kwargs)
            meta["vis"]["ts"] -= 10
            return out, meta
    with TestClient(server.create_app(lambda: OldRig(RigConfig(data_root=tmp_path)))) as client:
        result = client.post("/inspect", json={"specimen_id": "S01", "face": "A"}).json()
        assert result["verdict"] == "unmeasurable" and "frame_outside_trigger_window" in result["reasons"]


def test_timing_limits_are_explicit_and_device_clocks_not_used_as_host_time():
    vis = np.ones((8, 8, 3), np.uint8)
    stack = np.full((2, 256, 320), 22000, np.uint16)
    meta = {"vis": {"ts": 100.0}, "lwir": {"ts_first": 101.0, "ts_last": 101.2, "fpa_temp_c": 44.2}}
    data = evidence.build(vis, stack, meta, {"received_at_s": 100.0, "device_timestamp_ms": 9999}, "/captures/t/id")
    assert data["timing"]["status"] == "unvalidated" and data["timing"]["depth_rgb_skew_s"] == 0
    assert data["lwir"]["fpa_sensor_temperature_c"] == 44.2 and data["lwir"]["target_temperature_c"] is None
    policy = {"validated": True, "source_id": "synthetic-test-only", "max_rgb_lwir_skew_s": 0.1}
    data = evidence.build(vis, stack, meta, {}, "/captures/t/id", policy)
    assert data["timing"]["status"] == "invalid" and data["timing"]["reasons"] == ["sensor_time_skew"]


def test_full_sensor_http_station_store_path_preserves_units_and_trigger_per_repeat(tmp_path):
    station = Path(__file__).resolve().parents[2] / "station"
    sys.path.insert(0, str(station))
    from app import create_app
    from robot import MockRobot
    source = FakeDepth()
    with TestClient(sensor_app(tmp_path / "captures", source, depth_required=True)) as sensor_client:
        app = create_app(robot=MockRobot(speed=0), sensor_url="http://testserver", db_path=tmp_path / "station.db")
        app.state.sequencer.sensor._http.close()
        app.state.sequencer.sensor._http = sensor_client
        with TestClient(app) as client:
            triggers = set()
            for _ in range(2):
                assert client.post("/api/run", json={"specimen_id": "S01", "session": "t"}).status_code == 200
                app.state.sequencer.wait(5)
                result = client.get("/api/status").json()["last_result"]
                assert result["state"] == "done" and result["final_verdict"] == "review"
                assert result["bin"] == "human" and result["retakes_used"] == 0
                run_id = client.get("/api/runs").json()[0]["id"]
                entries = client.get(f"/api/runs/{run_id}/inspections").json()
                assert len(entries) == 2
                for entry in entries:
                    assert entry["trigger_id"] not in triggers
                    triggers.add(entry["trigger_id"])
                    data = entry["sensor_data"]
                    assert data["depth"]["median_mm"] == 500 and data["lwir"]["unit"] == "raw_counts"
                    assert data["association"]["trigger_id"] == entry["trigger_id"]
                    resource = client.get("/sensor-img", params={"path": entry["artifacts"]["depth_raw"]})
                    assert resource.status_code == 200 and resource.content[:2] == b"PK"
            assert len(triggers) == 4


@pytest.mark.parametrize("recover", [True, False])
def test_required_depth_retry_keeps_face_attempt_and_trigger_distinct(tmp_path, recover):
    station = Path(__file__).resolve().parents[2] / "station"
    sys.path.insert(0, str(station))
    from robot import MockRobot
    from sensor_client import SensorClient
    from sequencer import Sequencer
    class MissingSource(FakeDepth):
        calls = 0
        def next_after(self, requested):
            self.calls += 1
            if self.calls == 1 or not recover:
                raise TimeoutError("synthetic missing frame")
            return super().next_after(requested)
    source = MissingSource()
    with TestClient(sensor_app(tmp_path, source, depth_required=True)) as client:
        sensor = SensorClient("http://testserver")
        sensor._http.close(); sensor._http = client
        result = Sequencer(MockRobot(speed=0), sensor).run("S01", "t")
    assert result["state"] == "done" and result["bin"] == "human" and result["retakes_used"] == 1
    assert result["final_verdict"] == ("review" if recover else "unmeasurable")
    assert [(i["face"], i["attempt"]) for i in result["inspections"]] == [("A", 0), ("A", 1), ("B", 0)]
    assert len({i["trigger_id"] for i in result["inspections"]}) == 3
