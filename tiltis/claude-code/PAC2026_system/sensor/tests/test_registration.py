"""가상 타깃 영상으로 정합 코드를 검증한다. 실제 타깃 없이 돌릴 수 있다.

두 카메라(RGB 1600x1200, 열화상 320x256, 기준선 40mm)가 450mm 앞의 기울어진 판을 본다고 가정하고,
판 → 각 영상의 참 호모그래피로 타깃을 그린 뒤, 검출·추정한 정합이 참값과 맞는지 본다.
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import registration as reg  # noqa: E402

PX_PER_MM = 4.0
BOARD_MM = (300.0, 220.0)


def board_image(sq_val, bg_val, board_val, dtype):
    """판 좌표(mm×4)에 그린 타깃. 판 밖은 bg_val."""
    w, h = round(BOARD_MM[0] * PX_PER_MM), round(BOARD_MM[1] * PX_PER_MM)
    img = np.full((h, w), board_val, np.float32)
    cols, rows = reg.PATTERN
    x0 = (BOARD_MM[0] - (cols - 1) * reg.SPACING_MM) / 2
    y0 = (BOARD_MM[1] - (rows - 1) * reg.SPACING_MM) / 2
    half = reg.SQUARE_MM / 2
    for r in range(rows):
        for c in range(cols):
            cx, cy = x0 + c * reg.SPACING_MM, y0 + r * reg.SPACING_MM
            cv2.rectangle(img, (round((cx - half) * PX_PER_MM), round((cy - half) * PX_PER_MM)),
                          (round((cx + half) * PX_PER_MM), round((cy + half) * PX_PER_MM)), float(sq_val), -1)
    return img


def plane_to_image(K, R, t):
    """판 영상 픽셀 → 카메라 영상 픽셀 호모그래피. 판 중심이 원점."""
    S = np.array([[1 / PX_PER_MM, 0, -BOARD_MM[0] / 2], [0, 1 / PX_PER_MM, -BOARD_MM[1] / 2], [0, 0, 1]])
    return K @ np.column_stack([R[:, 0], R[:, 1], t]) @ S


def render(H, board, size, bg_val):
    return cv2.warpPerspective(board, H, size, flags=cv2.INTER_AREA, borderValue=float(bg_val))


@pytest.fixture
def synthetic_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "CALIB_DIR", tmp_path / "calib")  # 실제 보정 파일을 읽지 않게
    rng = np.random.default_rng(0)
    R, _ = cv2.Rodrigues(np.array([0.12, -0.18, 0.05]))
    t = np.array([0.0, 0.0, 450.0])
    Kv = np.array([[1300, 0, 800], [0, 1300, 600], [0, 0, 1]], float)
    Kl = np.array([[343, 0, 160], [0, 343, 128], [0, 0, 1]], float)
    Hv = plane_to_image(Kv, R, t)
    Hl = plane_to_image(Kl, R, t + np.array([-40.0, 0, 0]))  # 열화상 카메라는 RGB 오른쪽 40mm

    vis = render(Hv, board_image(210, 110, 25, np.uint8), (1600, 1200), 110)
    vis = np.clip(vis + rng.normal(0, 3, vis.shape), 0, 255).astype(np.uint8)
    vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)

    lw = render(Hl, board_image(21700, 22100, 22000, np.uint16), (320, 256), 22100)  # 알루미늄은 차갑게 보임
    lw = cv2.GaussianBlur(lw, (0, 0), 0.7)
    stack = np.stack([np.clip(lw + rng.normal(0, 3, lw.shape), 0, 65535).astype(np.uint16) for _ in range(8)])

    cap = tmp_path / "cap"
    cap.mkdir()
    cv2.imwrite(str(cap / "vis.png"), vis)
    np.savez_compressed(cap / "lwir_y16.npz", stack=stack)
    return cap, Hv @ np.linalg.inv(Hl)


def test_detect_and_fit_matches_truth(synthetic_capture):
    cap, H_true = synthetic_capture
    vis, lwir = reg.load_capture(cap)
    pv, pl = reg.detect_capture(vis, lwir)
    assert pv is not None and pl is not None
    r, _, stats = reg.new_registration("A", pl, pv, cap)
    assert stats["loo_max_lwir_px"] < 1.0

    # 열화상 화면 전체의 격자점에서 추정 정합과 참 정합의 차이(열화상 px)
    xs, ys = np.meshgrid(np.linspace(40, 280, 7), np.linspace(30, 226, 5))
    pts = np.stack([xs.ravel(), ys.ravel()], 1)
    vis_true = reg.apply_h(H_true, pts)
    back = r.vis_to_lwir(vis_true)
    assert np.abs(back - pts).max() < 0.5


def test_saved_registration_round_trip(synthetic_capture):
    cap, _ = synthetic_capture
    vis, lwir = reg.load_capture(cap)
    pv, pl = reg.detect_capture(vis, lwir)
    r, _, _ = reg.new_registration("B", pl, pv, cap)
    r.save()
    r2 = reg.Registration.load("B")
    pts = np.array([[100.0, 80.0], [200.0, 150.0]])
    assert np.allclose(r2.vis_to_lwir(r2.lwir_to_vis(pts)), pts, atol=1e-6)


def test_rotated_grid_order_is_resolved(synthetic_capture):
    cap, H_true = synthetic_capture
    vis, lwir = reg.load_capture(cap)
    pv, pl = reg.detect_capture(vis, lwir)
    H, _, _ = reg.fit_homography(pl[::-1].copy(), pv)  # 열화상 점 순서가 180° 뒤집혀 들어와도
    pts = np.array([[160.0, 128.0], [60.0, 60.0]])
    assert np.abs(reg.apply_h(H, pts) - reg.apply_h(H_true, pts)).max() < 3.0  # RGB px


def test_distort_undistort_inverse():
    K = np.array([[343, 0, 160], [0, 343, 128], [0, 0, 1]], float)
    dist = np.array([-0.3, 0.1, 0, 0, 0], float)
    pts = np.array([[20.0, 20.0], [160.0, 128.0], [300.0, 240.0]])
    u = reg.undistort_pts(pts, (K, dist))
    assert np.allclose(reg.distort_pts(u, (K, dist)), pts, atol=0.05)


def test_calibration_cli_saves_and_checks_face_c(synthetic_capture, monkeypatch):
    import calib

    cap, truth = synthetic_capture
    monkeypatch.setattr(sys, "argv", ["calib.py", "homography", "--capture", str(cap), "--face", "C"])
    calib.main()
    saved = reg.Registration.load("C")
    pts = np.array([[160.0, 128.0], [60.0, 60.0]])
    assert np.abs(saved.lwir_to_vis(pts) - reg.apply_h(truth, pts)).max() < 3.0
    monkeypatch.setattr(sys, "argv", ["calib.py", "check", "--capture", str(cap), "--face", "C"])
    calib.main()
    assert (cap / "calib_check_faceC.png").exists()
