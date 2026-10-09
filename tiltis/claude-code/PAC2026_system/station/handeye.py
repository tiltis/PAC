"""깊이 카메라 좌표(mm) → 로봇 base 좌표(m) 강체 변환(카메라가 로봇 밖에 고정된 eye-to-hand).

현장 절차(teach.py --handeye): 손잡이 붙은 상자를 여러 곳(6곳 권장, 넓게 퍼뜨림)에 놓고
 1) 센서가 깊이로 손잡이 중심을 찾는다(카메라 좌표)
 2) 토크를 끈 팔로 그리퍼가 손잡이를 잡게 맞추면, 관절값 → 정기구학으로 집게 끝 위치(로봇 좌표)
두 점 쌍을 Kabsch로 맞춘다. 카메라나 로봇 바닥을 움직이면 다시 해야 한다.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np

CALIB_DIR = Path(__file__).parent / "calib"
PATH = CALIB_DIR / "handeye.json"


def fit(cam_pts_mm, robot_pts_m):
    """R, t: robot = R @ (cam_mm / 1000) + t. 점 3개 이상, 같은 직선 위에 있으면 안 된다."""
    A = np.asarray(cam_pts_mm, float) / 1000.0
    B = np.asarray(robot_pts_m, float)
    if len(A) < 3 or A.shape != B.shape:
        raise ValueError("점 쌍이 3개 이상 필요")
    ca, cb = A.mean(0), B.mean(0)
    U, S, Vt = np.linalg.svd((A - ca).T @ (B - cb))
    if S[1] < 1e-6:
        raise ValueError("점들이 한 직선 위에 있어 방향을 정할 수 없음. 위치를 넓게 퍼뜨릴 것")
    D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])  # 반사 해 방지
    R = Vt.T @ D @ U.T
    t = cb - R @ ca
    res = np.linalg.norm((A @ R.T + t) - B, axis=1) * 1000
    return {"R": R.tolist(), "t": t.tolist(), "n": int(len(A)),
            "rms_mm": round(float(np.sqrt((res ** 2).mean())), 2), "max_mm": round(float(res.max()), 2),
            "residuals_mm": [round(float(r), 2) for r in res]}


def save(result, cam_pts_mm, robot_pts_m, path=None):
    path = Path(path or PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(result, created=dt.datetime.now().isoformat(timespec="seconds"),
               cam_points_mm=np.asarray(cam_pts_mm).round(2).tolist(), robot_points_m=np.asarray(robot_pts_m).round(5).tolist())
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(path=None):
    path = Path(path or PATH)
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"R": np.array(d["R"]), "t": np.array(d["t"]), "rms_mm": d.get("rms_mm"), "n": d.get("n")}


def point(he, p_cam_mm):
    return he["R"] @ (np.asarray(p_cam_mm, float) / 1000.0) + he["t"]


def vector(he, v_cam):
    return he["R"] @ np.asarray(v_cam, float)
