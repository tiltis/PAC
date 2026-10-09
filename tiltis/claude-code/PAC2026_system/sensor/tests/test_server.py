"""센서 서버를 가짜 Rig로 시험한다(카메라 불필요)."""
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality  # noqa: E402
import server  # noqa: E402
from fake_rig import FakeRig  # noqa: E402
from rig import RigConfig  # noqa: E402
import pytest


def client(tmp_path, **kw):
    cfg = RigConfig(vis_width=800, vis_height=600, data_root=tmp_path)
    return TestClient(server.create_app(lambda: FakeRig(cfg, **kw)))


def test_health_and_inspect_ok(tmp_path):
    with client(tmp_path) as c:
        h = c.get("/health").json()
        assert h["ok"] and h["ffc_mode"] == "manual"
        r = c.post("/inspect", json={"session": "t", "specimen_id": "S01", "face": "A", "attempt": 0}).json()
        assert r["status"] == "ok" and r["verdict"] == "review"
        assert r["reasons"] == ["defect_rules_unavailable"]
        assert r["features"]["rgb_sharpness"] > quality.DEFAULTS["rgb_sharpness_min"]
        img = c.get(r["images"]["rgb"])
        assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
        assert c.get(r["images"]["lwir"]).status_code == 200


def test_blurred_face_is_unmeasurable(tmp_path):
    with client(tmp_path, blur_faces=("B",)) as c:
        r = c.post("/inspect", json={"specimen_id": "S02", "face": "B"}).json()
        assert r["status"] == "ok" and r["verdict"] == "unmeasurable" and "rgb_blur" in r["reasons"]


def test_capture_failure_is_status_error(tmp_path):
    class Broken(FakeRig):
        def capture_pair(self, *a, **k):
            raise TimeoutError("LWIR: 5초 동안 새 프레임 없음")
    cfg = RigConfig(data_root=tmp_path)
    with TestClient(server.create_app(lambda: Broken(cfg))) as c:
        r = c.post("/inspect", json={"specimen_id": "S03", "face": "A"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "error" and "프레임" in body["error"] and body["verdict"] is None


def test_frozen_lwir_detected():
    vis = np.random.default_rng(0).integers(0, 255, (600, 800, 3), dtype=np.uint8)
    frozen = np.full((8, 256, 320), 22000, np.uint16)
    verdict, reasons, _ = quality.judge(vis, frozen)
    assert verdict == "unmeasurable" and "lwir_frozen" in reasons


def test_roi_features_identity_registration():
    class Ident:  # RGB 좌표 = 열화상 좌표
        def vis_to_lwir(self, pts):
            return pts
    lw = np.full((256, 320), 100.0, np.float32)
    lw[50:100, 50:100] = 80.0
    f = quality.roi_features(lw, Ident(), {"inspect": [[55, 55], [95, 55], [95, 95], [55, 95]],
                                           "reference": [[200, 200], [240, 200], [240, 240], [200, 240]]})
    assert f["lwir_roi_delta"] == -20.0


def test_dark_rgb_reported_as_dark_not_blur():
    dark = np.full((600, 800, 3), 2, np.uint8)
    stack = (22000 + np.random.default_rng(1).normal(0, 3, (8, 256, 320))).astype(np.uint16)
    verdict, reasons, f = quality.judge(dark, stack)
    assert verdict == "unmeasurable" and reasons == ["rgb_dark"] and f["rgb_mean"] < 15


def test_quality_only_sensor_to_station_routes_both_faces_to_human(tmp_path):
    import importlib.util
    station = Path(__file__).resolve().parents[2] / "station"
    def load(name):
        spec = importlib.util.spec_from_file_location(f"integration_{name}", station / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    robot = load("robot").MockRobot(speed=0)
    with client(tmp_path) as c:
        sensor = load("sensor_client").SensorClient("http://testserver")
        sensor._http.close()
        sensor._http = c  # HTTP 응답 검증까지 실제 SensorClient를 통과시킨다.
        result = load("sequencer").Sequencer(robot, sensor).run("QUALITY", "t")
    assert result["state"] == "done" and result["final_verdict"] == "review"
    assert result["bin"] == "human" and result["retakes_used"] == 0
    assert [i["face"] for i in result["inspections"]] == ["A", "B"]
    assert all(i["reasons"] == ["defect_rules_unavailable"] for i in result["inspections"])
    assert "bin_human" in robot.moves() and "bin_ok" not in robot.moves()


@pytest.mark.parametrize("value", ["../other", "a/b", "a\\b", "C:other", "CON", ".hidden", "x.", "x..y"])
def test_sensor_rejects_bad_capture_names_before_capture(tmp_path, value):
    with client(tmp_path) as c:
        for field in ("session", "specimen_id"):
            body = {"specimen_id": "S01", "session": "t", "face": "A", field: value}
            assert c.post("/inspect", json=body).status_code == 422
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("attempt", [-1, 2])
def test_sensor_rejects_attempt_outside_contract(tmp_path, attempt):
    with client(tmp_path) as c:
        assert c.post("/inspect", json={"specimen_id": "S01", "face": "A", "attempt": attempt}).status_code == 422


def test_repeated_capture_and_unicode_names_keep_distinct_records(tmp_path):
    with client(tmp_path) as c:
        body = {"specimen_id": "시료-01", "session": "시험_1.2", "face": "A"}
        first = c.post("/inspect", json=body).json()
        second = c.post("/inspect", json=body).json()
        assert first["status"] == second["status"] == "ok", (first.get("error"), second.get("error"))
        assert first["capture_id"] != second["capture_id"]
        assert c.get(first["images"]["rgb"]).status_code == 200
        assert c.get(second["images"]["rgb"]).status_code == 200


def test_image_encoding_failure_is_sensor_error(tmp_path, monkeypatch):
    import cv2
    monkeypatch.setattr(cv2, "imencode", lambda *args: (False, None))
    with client(tmp_path) as c:
        result = c.post("/inspect", json={"specimen_id": "S01", "face": "A"}).json()
        assert result["status"] == "error" and "이미지 인코딩 실패" in result["error"]
        assert result["verdict"] is None and result["images"] == {}


def test_live_jpg_and_marker_recorded(tmp_path):
    with client(tmp_path) as c:
        r = c.get("/live.jpg", params={"specimen_id": "S01"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
        body = c.post("/inspect", json={"session": "t", "specimen_id": "S01", "face": "A", "attempt": 0,
                                        "trigger_id": "trig-live-1"}).json()
        f = body["features"]
        assert f["marker_ids"] == [] and f["marker_expected"] == 1 and f["marker_match"] is None


def test_marker_check_logic():
    import cv2
    import marker
    canvas = np.full((600, 800, 3), 255, np.uint8)
    canvas[100:300, 100:300] = cv2.cvtColor(cv2.aruco.generateImageMarker(marker.DICT, 3, 200), cv2.COLOR_GRAY2BGR)
    assert marker.check(canvas, "S03")[0]["marker_match"] is True
    assert marker.check(canvas, "S04")[0]["marker_match"] is False
    assert marker.check(canvas, "TEST")[0]["marker_match"] is None


def test_object_endpoints_with_fake_rig(tmp_path, monkeypatch):
    import objects
    monkeypatch.setattr(objects, "CALIB_DIR", tmp_path / "calib")
    monkeypatch.setattr(objects, "BG_DIR", tmp_path / "calib" / "background")
    monkeypatch.setattr(objects, "MAP_PATH", tmp_path / "calib" / "object_map.json")
    with client(tmp_path) as c:
        assert c.get("/object/status").json() == {"background": False}
        assert c.post("/object/background").json()["ok"] is True
        st = c.get("/object/status").json()
        assert st["background"] is True and st["association"]["status"] == "no_object"
        assert c.post("/object/map-point").json()["ok"] is False  # 물체가 없으면 대응점 추가 안 함
        assert c.get("/live.jpg").status_code == 200
        body = c.post("/inspect", json={"session": "t", "specimen_id": "S01", "face": "A", "attempt": 0,
                                        "trigger_id": "trig-obj-1"}).json()
        assert body["status"] == "ok" and "object_status" in body["features"]


def test_object_locate_requires_depth(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/object/locate").status_code == 409


@pytest.mark.parametrize("samples, expected_mm", [
    ([400, 401, 0, 399, 0], 400),  # 유효한 3/5 프레임의 중앙값을 유지
    ([400, 0, 0, 399, 0], 0),    # 유효 깊이가 과반 미만이면 거부
    ([400, 401, 398, 399, 402], 400),
    ([0, 0, 0, 0, 0], 0),
])
def test_object_locate_aggregates_only_valid_depth(tmp_path, monkeypatch, samples, expected_mm):
    from types import SimpleNamespace
    from test_sensor_evidence import FakeDepth, sensor_app

    class SampleDepth(FakeDepth):
        intrinsics = {"fx": 1.0, "fy": 1.0, "cx": 0.0, "cy": 0.0}

        def __init__(self):
            super().__init__()
            self.samples = iter(samples)

        def next_after(self, requested):
            return SimpleNamespace(raw=np.full((8, 10), next(self.samples), np.uint16),
                                   scale_mm=1.0, received_at_s=requested + 0.01)

    received = []

    def inspect_depth(mm, *args, **kwargs):
        received.append(mm.copy())
        return {"found": False, "reason": "synthetic_aggregation_test"}

    monkeypatch.setattr(server.locate, "locate_box_front_any", inspect_depth)
    with TestClient(sensor_app(tmp_path, SampleDepth())) as c:
        response = c.get("/object/locate?frames=5")
        assert response.status_code == 200
        assert response.json()["frames"] == 5
    assert len(received) == 1
    np.testing.assert_array_equal(received[0], np.full((8, 10), expected_mm))
