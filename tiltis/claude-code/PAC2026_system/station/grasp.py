"""손잡이(파지부)가 붙은 상자를 위에서 집는 경로 계산 (방식 C).

입력: 센서 /object/locate 결과(깊이 카메라 좌표). locate는 가장 높은 직사각형 윗면을 찾으므로
손잡이가 있으면 손잡이 윗면이 잡힌다. hand-eye로 로봇 좌표로 바꾼 뒤
 - 집는 점 = 손잡이 윗면 중심에서 손잡이 높이의 절반만큼 아래(책상 법선 방향)
 - 집게 닫힘 방향 = 손잡이 짧은 변 방향(수평)
 - 접근·들어올림 = 집는 점에서 위로 approach_mm / lift_mm
각 점을 수직 하강 자세로 역기구학을 풀고, 한 가지라도 실패하면 이유와 함께 거부한다(추측해서 움직이지 않음).

SO-101이 수직으로 내려 잡을 수 있는 높이는 로봇에서 18~22cm 떨어진 곳에서 약 90mm가 한계다(kinematics 계산).
그래서 상자는 로봇 앞 약 20cm에 두고, 접근 높이는 집는 점 위 25mm로 낮게 잡는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import handeye
import kinematics as K

CONFIG_PATH = Path(__file__).parent / "calib" / "grasp_config.json"
DEFAULTS = {
    "tab_size_mm": [60.0, 25.0],   # 손잡이 윗면 (긴 변, 짧은 변)
    "tab_height_mm": 20.0,
    "tab_size_tol_mm": 15.0,
    "grasp_depth_mm": None,        # 윗면에서 아래로 집는 점까지 거리(고정값). None이면 아래 frac 또는 손잡이 높이의 절반
    "grasp_depth_frac": None,      # 상자 높이(locate의 top_height_mm)의 비율로 집는 깊이를 정한다. 예 0.4
    "grasp_depth_min_mm": 20.0,    # frac 결과를 이 범위로 자른다(낮은 상자는 책상에 닿지 않게, 높은 상자는 너무 깊지 않게)
    "grasp_depth_max_mm": 35.0,
    "approach_mm": 25.0,
    "lift_mm": 25.0,
    # 옆집기: 수평 접근. 아래 반경은 모델의 IK 후보 범위이며 실측 workspace와 별도로 검사한다.
    # 실제 개구 폭·상자 회전·닫힐 때 정렬되는지는 실기 확인이 필요하다.
    "grasp_mode": "top",            # "top": 위에서 수직(손잡이용) / "side": 옆에서 수평
    "side_height_frac": 0.5,
    "side_tcp_offset_mm": 0.0,
    "side_approach_mm": 50.0,
    "side_lift_mm": 100.0,
    "side_reach_r_m": [0.37, 0.47],
    "box_types_by_height_mm": {"white": 90, "brown": 45},  # locate가 잰 높이로 상자 종류 자동 선택(±15mm)
    "reach_r_m": [0.14, 0.26],     # 로봇 중심에서 수평 거리 허용 범위
    "max_normal_tilt_deg": 15.0,   # 책상 법선이 로봇 z축과 이루는 각(크면 hand-eye 이상)
    "max_joint_jump_deg": 45.0,    # 접근→집기 사이 관절 변화 한계
}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def camera_grasp_point(loc, cfg):
    """Shared camera-mm tool point. Offset: side height above table / top depth below top."""
    n = np.asarray(loc["table_normal_cam"], float)
    if n.shape != (3,) or not np.isfinite(n).all() or np.linalg.norm(n) < 1e-6:
        raise ValueError("invalid table normal")
    n = n / np.linalg.norm(n)
    if cfg.get("grasp_mode") == "side":
        height = float(loc["top_height_mm"])
        if not np.isfinite(height) or height <= 10:
            raise ValueError("invalid side grasp height")
        base = loc.get("box_center_on_table_cam_mm")
        if base is None:
            base = np.asarray(loc["top_center_cam_mm"], float) - n * height
        base = np.asarray(base, float)
        if base.shape != (3,) or not np.isfinite(base).all():
            raise ValueError("invalid box table center")
        h = float(np.clip(cfg["side_height_frac"] * height + cfg["side_tcp_offset_mm"], 5, height - 5))
        if not np.isfinite(h):
            raise ValueError("invalid side grasp offset")
        return base + n * h, h
    depth_mm = cfg.get("grasp_depth_mm")
    if depth_mm is None and cfg.get("grasp_depth_frac") is not None and loc.get("top_height_mm") is not None:
        depth_mm = float(np.clip(cfg["grasp_depth_frac"] * float(loc["top_height_mm"]),
                                 cfg["grasp_depth_min_mm"], cfg["grasp_depth_max_mm"]))
    if depth_mm is None:
        depth_mm = cfg["tab_height_mm"] / 2.0
    return np.asarray(loc["top_center_cam_mm"], float) - n * depth_mm, float(depth_mm)


def plan(loc, he, robot=None, cfg=None, joint_map=None):
    """성공: {"ok": True, "approach"/"grasp"/"lift": LeRobot 관절 dict, ...}. 실패: {"ok": False, "reason": ...}"""
    cfg = cfg or load_config()
    robot = robot or K.SO101()
    if not loc or not loc.get("found"):
        return {"ok": False, "reason": f"상자를 찾지 못함: {(loc or {}).get('reason')}"}
    if he is None:
        return {"ok": False, "reason": "hand-eye 보정 없음"}
    if cfg.get("grasp_mode") == "side":
        return plan_side(loc, he, robot, cfg, joint_map)
    if loc.get("mode") != "front_face_model":  # 앞면 모델 방식은 센서가 상자 앞면 길이·높이로 이미 확인했다
        L, S = loc["top_size_mm"]
        tL, tS = cfg["tab_size_mm"]
        if abs(L - tL) > cfg["tab_size_tol_mm"] or abs(S - tS) > cfg["tab_size_tol_mm"]:
            return {"ok": False, "reason": f"가장 높은 윗면이 손잡이 크기가 아님: {L:.0f}x{S:.0f}mm (기대 {tL:.0f}x{tS:.0f})"}
    n = handeye.vector(he, loc["table_normal_cam"])
    n /= np.linalg.norm(n)
    tilt = np.degrees(np.arccos(np.clip(n[2], -1, 1)))
    if tilt > cfg["max_normal_tilt_deg"]:
        return {"ok": False, "reason": f"책상 법선이 로봇 z축과 {tilt:.0f}° 어긋남 (hand-eye 확인)"}
    grasp_cam, depth_mm = camera_grasp_point(loc, cfg)
    grasp_p = handeye.point(he, grasp_cam)
    approach_p = grasp_p + n * cfg["approach_mm"] / 1000.0
    lift_p = grasp_p + n * cfg["lift_mm"] / 1000.0
    r = float(np.hypot(grasp_p[0], grasp_p[1]))
    if not cfg["reach_r_m"][0] <= r <= cfg["reach_r_m"][1]:
        return {"ok": False, "reason": f"로봇에서 수평 거리 {r * 1000:.0f}mm: 허용 {cfg['reach_r_m'][0] * 1000:.0f}~{cfg['reach_r_m'][1] * 1000:.0f}mm 밖"}
    s = handeye.vector(he, loc["short_axis_cam"])
    s = s - np.dot(s, [0, 0, 1]) * np.array([0, 0, 1.0])
    yaw = float(np.arctan2(s[1], s[0]))  # 집게 닫힘 방향 = 손잡이 짧은 변
    down = -n
    qs = {}
    seed = None
    for name, p in (("approach", approach_p), ("grasp", grasp_p), ("lift", lift_p)):
        q = robot.ik(p, down=down, yaw=yaw, q0=seed)
        if q is None:
            return {"ok": False, "reason": f"{name} 위치({p[0]*1000:.0f}, {p[1]*1000:.0f}, {p[2]*1000:.0f})mm 역기구학 해 없음"}
        qs[name] = q
        seed = q
    jump = np.degrees(np.abs(qs["grasp"] - qs["approach"])).max()
    if jump > cfg["max_joint_jump_deg"]:
        return {"ok": False, "reason": f"접근→집기 관절 변화 {jump:.0f}°가 너무 큼(자세가 뒤집힌 해)"}
    errs = {k: [round(v, 2) for v in robot.error(qs[k], p, down, np.array([np.cos(yaw), np.sin(yaw), 0]))]
            for k, p in (("approach", approach_p), ("grasp", grasp_p), ("lift", lift_p))}
    return {"ok": True, "approach": K.to_lerobot(qs["approach"], joint_map), "grasp": K.to_lerobot(qs["grasp"], joint_map),
            "lift": K.to_lerobot(qs["lift"], joint_map),
            "grasp_point_m": grasp_p.round(4).tolist(), "grasp_depth_mm": round(float(depth_mm), 1), "radius_mm": round(r * 1000, 1), "yaw_deg": round(np.degrees(yaw), 1),
            "table_tilt_deg": round(float(tilt), 1), "ik_error_mm_deg": errs, "handeye_rms_mm": he.get("rms_mm")}


def plan_side(loc, he, robot, cfg, joint_map=None):
    """옆집기: 상자 중심(책상 위) + 법선×집는 높이 = 집는 점. 접근은 로봇 쪽에서 수평으로, 닫힘 방향은 접근과 직각(수평)."""
    if loc.get("top_height_mm") is None or (loc.get("box_center_on_table_cam_mm") is None and loc.get("top_center_cam_mm") is None):
        return {"ok": False, "reason": "옆집기에는 상자 중심·높이(locate 결과)가 필요"}
    if loc.get("box_center_on_table_cam_mm") is None:  # top 모드: 윗면 중심에서 법선×높이만큼 내려 책상 위 중심
        n_cam = np.asarray(loc["table_normal_cam"], float)
        n_cam = n_cam / np.linalg.norm(n_cam)
        loc = dict(loc, box_center_on_table_cam_mm=(np.asarray(loc["top_center_cam_mm"], float) - n_cam * float(loc["top_height_mm"])).tolist())
    n = handeye.vector(he, loc["table_normal_cam"])
    n /= np.linalg.norm(n)
    tilt = np.degrees(np.arccos(np.clip(n[2], -1, 1)))
    if tilt > cfg["max_normal_tilt_deg"]:
        return {"ok": False, "reason": f"책상 법선이 로봇 z축과 {tilt:.0f}° 어긋남 (hand-eye 확인)"}
    try:
        grasp_cam, h_mm = camera_grasp_point(loc, cfg)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "reason": f"옆집기 좌표 오류: {e}"}
    grasp_p = handeye.point(he, grasp_cam)
    horiz = np.array([grasp_p[0], grasp_p[1], 0.0])
    r = float(np.linalg.norm(horiz))
    lo, hi = cfg["side_reach_r_m"]
    if not lo <= r <= hi:
        return {"ok": False, "reason": f"로봇에서 수평 거리 {r * 1000:.0f}mm: 옆집기 허용 {lo * 1000:.0f}~{hi * 1000:.0f}mm 밖(상자를 더 {'멀리' if r < lo else '가까이'})"}
    radial = horiz / r
    approach_p = grasp_p - radial * cfg["side_approach_mm"] / 1000.0
    lift_p = grasp_p + n * cfg["side_lift_mm"] / 1000.0
    yaw = float(np.arctan2(radial[1], radial[0]) + np.pi / 2)  # 닫힘 방향 = 접근과 직각. 실기에서 개구 폭/회전 허용 범위를 확인한다.
    qs, seed = {}, None
    for name, p in (("approach", approach_p), ("grasp", grasp_p), ("lift", lift_p)):
        q = robot.ik(p, down=radial, yaw=yaw, q0=seed)
        if q is None:
            return {"ok": False, "reason": f"{name} 위치({p[0]*1000:.0f}, {p[1]*1000:.0f}, {p[2]*1000:.0f})mm 역기구학 해 없음(옆집기)"}
        qs[name] = q
        seed = q
    jump = np.degrees(np.abs(qs["grasp"] - qs["approach"])).max()
    if jump > cfg["max_joint_jump_deg"]:
        return {"ok": False, "reason": f"접근→집기 관절 변화 {jump:.0f}°가 너무 큼(자세가 뒤집힌 해)"}
    errs = {k: [round(v, 2) for v in robot.error(qs[k], p, radial, np.array([np.cos(yaw), np.sin(yaw), 0]))]
            for k, p in (("approach", approach_p), ("grasp", grasp_p), ("lift", lift_p))}
    return {"ok": True, "grasp_mode": "side", "approach": K.to_lerobot(qs["approach"], joint_map), "grasp": K.to_lerobot(qs["grasp"], joint_map),
            "lift": K.to_lerobot(qs["lift"], joint_map),
            "grasp_point_m": grasp_p.round(4).tolist(), "grasp_height_mm": round(h_mm, 1), "radius_mm": round(r * 1000, 1),
            "yaw_deg": round(np.degrees(yaw), 1), "table_tilt_deg": round(float(tilt), 1), "ik_error_mm_deg": errs,
            "handeye_rms_mm": he.get("rms_mm")}


def box_type_for(loc, cfg=None):
    """locate가 잰 상자 높이로 상자 종류(white/brown)를 고른다. 15mm 안에 맞는 게 없으면 ""."""
    cfg = cfg or load_config()
    h = (loc or {}).get("top_height_mm")
    if h is None:
        return ""
    best = min(cfg.get("box_types_by_height_mm", {}).items(), key=lambda kv: abs(kv[1] - h), default=None)
    return best[0] if best and abs(best[1] - h) <= 15 else ""


class VisionPicker:
    """시연 순서(sequencer)에서 쓰는 비전 집기. dry_run이면 접근 위치까지만 가고 멈춘다."""

    def __init__(self, sensor, he, dry_run=False, cfg=None, joint_map=None):
        self.sensor, self.he, self.dry_run = sensor, he, dry_run
        self.cfg = cfg or load_config()
        self.joint_map = K.load_joint_map() if joint_map is None else joint_map
        self.robot = K.SO101()

    def locate(self, retries=3, wait_s=0.4):
        """깊이 한 묶음(5프레임)으로 못 찾으면 잠깐 뒤 다시 받는다(서버 시작 직후·프레임 흔들림 대비, 10-09 라이브 4/5 → 재시도로 보완).
        끝까지 못 찾으면 마지막 결과(이유 포함)를 그대로 돌려줘 계획 단계가 거부한다."""
        import time
        loc = None
        for i in range(max(1, retries)):
            loc = self.sensor.locate()
            if isinstance(loc, dict) and loc.get("found"):
                if i:
                    loc["retries"] = i
                return loc
            time.sleep(wait_s)
        return loc

    def plan(self, loc):
        return plan(loc, self.he, self.robot, self.cfg, self.joint_map)

    def box_type_for(self, loc):
        return box_type_for(loc, self.cfg)
