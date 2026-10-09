"""3카메라 같은 물체 확인을 가상 장면으로 시험한다(카메라 불필요)."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import objects  # noqa: E402

# 작업면 좌표(0~1) → 카메라 픽셀: 카메라마다 배율·위치가 다르다(실제처럼 화각이 다름)
CAMS = {"rgb": ((1600, 1200), (300, 200, 1000, 800)), "lwir": ((320, 256), (20, 10, 280, 230)),
        "depth": ((1280, 800), (380, 150, 640, 500))}


def to_px(cam, u, v):
    (w, h), (x0, y0, sx, sy) = CAMS[cam]
    return x0 + u * sx, y0 + v * sy


def scene(u=None, v=None, size=0.18, rng=None, lwir_delta=-80.0):
    """물체(상자)를 작업면 (u, v)에 놓은 세 카메라 영상. u=None이면 빈 장면."""
    rng = rng or np.random.default_rng(0)
    rgb = np.full((1200, 1600, 3), 60, np.uint8)
    rgb[:, :, 1] = 70
    lw = np.full((256, 320), 22000.0, np.float32) + rng.normal(0, 3, (256, 320))
    dep = np.full((800, 1280), 1500.0, np.float32) + rng.normal(0, 4, (800, 1280))
    if u is not None:
        for cam, img, val in (("rgb", rgb, (40, 140, 200)), ("lwir", lw, None), ("depth", dep, None)):
            (w, h), (x0, y0, sx, sy) = CAMS[cam]
            a, b = to_px(cam, u - size / 2, v - size / 2)
            c, d = to_px(cam, u + size / 2, v + size / 2)
            sl = (slice(int(b), int(d)), slice(int(a), int(c)))
            if cam == "rgb":
                img[sl] = val
            elif cam == "lwir":
                img[sl] += lwir_delta
            else:
                img[sl] = 900.0
    return rgb, lw, dep


@pytest.fixture
def calib_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(objects, "CALIB_DIR", tmp_path)
    monkeypatch.setattr(objects, "BG_DIR", tmp_path / "background")
    monkeypatch.setattr(objects, "MAP_PATH", tmp_path / "object_map.json")
    rgb, lw, dep = scene()
    objects.save_background(rgb, lw, dep)
    return objects.load_background()


def test_detect_each_camera(calib_tmp):
    rgb, lw, dep = scene(0.5, 0.5)
    dets = objects.detect_all(calib_tmp, rgb, lw, dep)
    for cam in ("rgb", "lwir", "depth"):
        d = dets[cam]
        assert d.found, cam
        ex, ey = to_px(cam, 0.5, 0.5)
        w = CAMS[cam][0][0]
        assert abs(d.center[0] - ex) < 0.02 * w and abs(d.center[1] - ey) < 0.02 * w, (cam, d.center, ex, ey)
    assert dets["lwir"].extra["polarity"] == "colder"
    assert 850 < dets["depth"].extra["distance_mm"] < 950


def test_empty_scene_finds_nothing(calib_tmp):
    rgb, lw, dep = scene(rng=np.random.default_rng(5))
    dets = objects.detect_all(calib_tmp, rgb, lw, dep)
    assert not any(d.found for d in dets.values())


def test_map_then_same_object_and_mismatch(calib_tmp):
    for u, v in ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8), (0.5, 0.4)):
        m, msg = objects.add_map_point(objects.detect_all(calib_tmp, *scene(u, v)))
        assert m is not None, msg
    assert m["fit_err_px_lwir"] < 3 and m["fit_err_px_depth"] < 10
    cmap = objects.load_map()
    sizes = {"lwir": (320, 256), "depth": (1280, 800)}
    dets = objects.detect_all(calib_tmp, *scene(0.35, 0.65))
    assert objects.associate(dets, cmap, sizes)["status"] == "same_object"

    # 열화상에서 다른 위치의 물체가 보이면 불일치
    rgb, _, dep = scene(0.3, 0.3)
    _, lw_other, _ = scene(0.75, 0.75)
    dets = objects.detect_all(calib_tmp, rgb, lw_other, dep)
    a = objects.associate(dets, cmap, sizes)
    assert a["status"] == "mismatch" and a["cams"]["lwir"]["status"] == "mismatch"


def test_room_temperature_box_partial_without_thermal(calib_tmp):
    # 실온 상자: 열화상에 안 보이면 partial로 남는다(같은 물체라고 단정하지 않음)
    for u, v in ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)):
        objects.add_map_point(objects.detect_all(calib_tmp, *scene(u, v)))
    dets = objects.detect_all(calib_tmp, *scene(0.5, 0.5, lwir_delta=0.0))
    a = objects.associate(dets, objects.load_map(), {"lwir": (320, 256), "depth": (1280, 800)})
    assert a["status"] == "partial" and a["cams"]["lwir"]["status"] == "not_found"


def test_without_map_is_unverified(calib_tmp):
    dets = objects.detect_all(calib_tmp, *scene(0.5, 0.5))
    assert objects.associate(dets, None, {"lwir": (320, 256), "depth": (1280, 800)})["status"] == "unverified"


def test_depth_band_without_background(calib_tmp):
    # 배경 없이 깊이 거리 범위(0.2~1.0m)만으로 물체를 찾는다. 뒤의 먼 장면(1.5m)은 무시
    rgb, lw, dep = scene(0.5, 0.5)
    dets = objects.detect_all(None, rgb, lw, dep)
    assert not dets["rgb"].found and dets["rgb"].extra["error"] == "no_background"
    assert dets["depth"].found and dets["depth"].extra["mode"] == "band"
    assert objects.associate(dets, None, {"lwir": (320, 256), "depth": (1280, 800)})["status"] == "depth_only"


def test_roi_ignores_change_outside(calib_tmp):
    # 검사 영역 밖(예: 뒤로 지나가는 사람)의 변화는 무시
    rgb, lw, dep = scene(0.15, 0.15)
    cfg = objects.load_config()
    x0, y0 = to_px("rgb", 0.4, 0.4)
    x1, y1 = to_px("rgb", 0.9, 0.9)
    cfg["roi"]["rgb"] = [x0, y0, x1, y1]
    assert not objects.detect_all(calib_tmp, rgb, lw, dep, cfg)["rgb"].found
    cfg["roi"]["rgb"] = None
    assert objects.detect_all(calib_tmp, rgb, lw, dep, cfg)["rgb"].found
