"""책상 위 상자 위치 찾기를 광선 추적으로 만든 가상 깊이 영상으로 시험한다."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import locate  # noqa: E402

INTR = {"fx": 613.9, "fy": 613.9, "cx": 636.4, "cy": 401.1}
W, H = 1280, 800


def render(cam_h=200.0, box=((-80, 80), (300, 380)), box_h=60.0, tilt_deg=12.0, wall=None):
    """카메라가 책상 위 cam_h(mm)에서 아래로 tilt_deg 기울여 본 깊이(mm). box: (x 범위, 깊이 z 범위)."""
    v, u = np.mgrid[0:H, 0:W]
    d = np.stack([(u - INTR["cx"]) / INTR["fx"], (v - INTR["cy"]) / INTR["fy"], np.ones((H, W))], -1)
    t = np.radians(tilt_deg)
    R = np.array([[1, 0, 0], [0, np.cos(t), np.sin(t)], [0, -np.sin(t), np.cos(t)]])  # 카메라→월드(아래로 기울임)
    dw = d @ R.T
    best = np.full((H, W), np.inf)
    with np.errstate(divide="ignore", invalid="ignore"):
        tp = cam_h / dw[..., 1]  # 책상: 월드 y = cam_h (y 아래 방향)
        best = np.where((tp > 0) & np.isfinite(tp), tp, best)
        lo = np.array([box[0][0], cam_h - box_h, box[1][0]])
        hi = np.array([box[0][1], cam_h, box[1][1]])
        t1, t2 = (lo - 0) / dw, (hi - 0) / dw
        tmin = np.nanmax(np.minimum(t1, t2), -1)
        tmax = np.nanmin(np.maximum(t1, t2), -1)
        hit = (tmax >= tmin) & (tmax > 0)
        best = np.where(hit & (tmin < best), tmin, best)
        if wall is not None:  # 왼쪽 가구 옆면(얇은 띠 모양)
            tw = wall / dw[..., 0]
            yw = tw * dw[..., 1]
            best = np.where((tw > 0) & (yw > cam_h - 160) & (yw < cam_h) & (tw < best), tw, best)
    z = best * d[..., 2] / np.linalg.norm(d, axis=-1) * np.linalg.norm(d, axis=-1)  # 광선 매개변수 = 카메라 z
    z = np.where(np.isfinite(z) & (z < 3000), z, 0)
    return z + np.random.default_rng(0).normal(0, 1.0, z.shape) * (z > 0)


def test_finds_box_size_height_and_center():
    r = locate.locate_box(render(), INTR)
    assert r["found"], r
    assert abs(r["top_height_mm"] - 60) < 4
    L, S = r["top_size_mm"]
    assert abs(L - 160) < 8 and abs(S - 80) < 8, r["top_size_mm"]
    assert abs(r["long_axis_cam"][0]) > 0.95  # 긴 변이 화면 좌우 방향


def test_ignores_thin_furniture_edge():
    r = locate.locate_box(render(wall=-150.0), INTR)
    assert r["found"] and abs(r["top_height_mm"] - 60) < 4


def test_empty_table_reports_not_found():
    r = locate.locate_box(render(box=((-1, 0), (5000, 5001))), INTR)
    assert not r["found"]


def test_front_face_model_with_upright_camera():
    # 카메라를 세워 둔(12° 아래) 상태에서 160x130x50 상자: 앞면 + 알려진 크기로 중심을 계산
    cam_h, tilt = 190.0, 12.0
    box = ((-80, 80), (300, 430))
    r = locate.public(locate.locate_box_front(render(cam_h=cam_h, box=box, box_h=50.0, tilt_deg=tilt), INTR,
                                              box_mm=(160, 130, 50), tab_height_mm=20, pick_roi=[0, 0, W, H]))
    assert r["found"] and r["mode"] == "front_face_model", r
    assert abs(r["front_face_len_mm"] - 160) < 6 and r["facing_side_mm"] == 160
    t = np.radians(tilt)
    Rcw = np.array([[1, 0, 0], [0, np.cos(t), np.sin(t)], [0, -np.sin(t), np.cos(t)]])  # 카메라→월드
    truth_world = np.array([0.0, cam_h, 365.0])  # 상자 바닥 중심(책상 위)
    truth_cam = Rcw.T @ truth_world
    assert np.linalg.norm(np.array(r["box_center_on_table_cam_mm"]) - truth_cam) < 6, (r["box_center_on_table_cam_mm"], truth_cam)
    tab_world = np.array([0.0, cam_h - 70.0, 365.0])  # 손잡이 윗면 = 상자 50 + 손잡이 20
    assert np.linalg.norm(np.array(r["top_center_cam_mm"]) - Rcw.T @ tab_world) < 6


def test_front_face_model_rejects_wrong_box():
    r = locate.locate_box_front(render(box=((-50, 50), (300, 380)), box_h=50.0), INTR, box_mm=(160, 130, 50),
                                pick_roi=[0, 0, W, H])
    assert not r["found"] and "앞면 길이" in r["reason"]


def test_front_face_model_70mm_cube_without_tab():
    # 10-09 시편: 약 70mm 정육면체, 손잡이 없음(tab 0). 현재 설치(책상 위 190mm, 14° 아래)에서 350mm 앞, 30° 돌아간 상자
    cam_h, tilt = 190.0, 14.0
    mm = render(cam_h=cam_h, box=((-35, 35), (315, 385)), box_h=70.0, tilt_deg=tilt)
    r = locate.public(locate.locate_box_front(mm, INTR, box_mm=(70, 70, 70), tab_height_mm=0, pick_roi=[0, 0, W, H]))
    assert r["found"] and r["mode"] == "front_face_model", r
    assert abs(r["front_face_len_mm"] - 70) < 8 and abs(r["top_height_mm"] - 70) < 6
    t = np.radians(tilt)
    Rcw = np.array([[1, 0, 0], [0, np.cos(t), np.sin(t)], [0, -np.sin(t), np.cos(t)]])
    assert np.linalg.norm(np.array(r["top_center_cam_mm"]) - Rcw.T @ np.array([0.0, cam_h - 70.0, 350.0])) < 8
    assert np.linalg.norm(np.array(r["box_center_on_table_cam_mm"]) - Rcw.T @ np.array([0.0, cam_h, 350.0])) < 8


def test_front_face_model_picks_candidate_by_height():
    # 10-09 시편 둘: 흰 70×70×90, 갈색 80×80×45. 높이로 어느 상자인지 고른다
    cands = [(70, 70, 90), (80, 80, 45)]
    white = render(cam_h=190.0, box=((-35, 35), (315, 385)), box_h=90.0, tilt_deg=14.0)
    r = locate.public(locate.locate_box_front_any(white, INTR, cands, tab_height_mm=0, pick_roi=[0, 0, W, H]))
    assert r["found"] and r["box_mm"] == [70.0, 70.0, 90.0], r
    assert abs(r["top_height_mm"] - 90) < 6
    brown = render(cam_h=190.0, box=((-40, 40), (310, 390)), box_h=45.0, tilt_deg=14.0)
    r = locate.public(locate.locate_box_front_any(brown, INTR, cands, tab_height_mm=0, pick_roi=[0, 0, W, H]))
    assert r["found"] and r["box_mm"] == [80.0, 80.0, 45.0], r
    assert abs(r["front_face_len_mm"] - 80) < 8
    # 둘 다 아닌 상자(60mm 높이 120mm)는 후보별 이유와 함께 거부
    other = render(cam_h=190.0, box=((-60, 60), (300, 420)), box_h=60.0, tilt_deg=14.0)
    r = locate.public(locate.locate_box_front_any(other, INTR, cands, tab_height_mm=0, pick_roi=[0, 0, W, H]))
    assert not r["found"] and r["reason"] == "no_candidate_box_matched" and len(r["candidates"]) == 2
