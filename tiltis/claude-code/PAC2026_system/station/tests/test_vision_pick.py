"""방식 C(깊이로 상자 손잡이를 찾아 집기)를 가상 hand-eye·가상 깊이 결과로 시험한다. 로봇 불필요."""
import numpy as np
import pytest

import grasp
import handeye
import kinematics as K
from robot import MockRobot
from sequencer import Sequencer


def rot(axis, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return {"x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), "y": np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            "z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


# 가상 설치: 깊이 카메라가 로봇 앞 오른쪽 위에서 비스듬히 내려다본다
R_CAM = rot("z", -100) @ rot("x", -130)
T_CAM = np.array([0.35, -0.10, 0.45])
HE = {"R": R_CAM, "t": T_CAM, "rms_mm": 3.0}


def fake_locate(top_center_robot_m, yaw_deg, size=(60.0, 25.0), normal=(0, 0, 1.0)):
    """로봇 좌표의 손잡이 윗면 → 센서가 돌려줄 깊이 카메라 좌표 결과."""
    inv = R_CAM.T
    y = np.radians(yaw_deg)
    return {"found": True, "top_center_cam_mm": (inv @ (np.asarray(top_center_robot_m) - T_CAM) * 1000).tolist(),
            "top_size_mm": list(size), "table_normal_cam": (inv @ np.asarray(normal, float)).tolist(),
            "short_axis_cam": (inv @ np.array([np.cos(y), np.sin(y), 0])).tolist(),
            "long_axis_cam": (inv @ np.array([-np.sin(y), np.cos(y), 0])).tolist()}


def test_handeye_fit_recovers_transform():
    rng = np.random.default_rng(0)
    rob = rng.uniform([0.14, -0.1, 0.0], [0.26, 0.1, 0.08], (6, 3))
    cam_mm = (rob - T_CAM) @ R_CAM * 1000 + rng.normal(0, 1.0, (6, 3))
    res = handeye.fit(cam_mm, rob)
    assert res["rms_mm"] < 3
    assert np.allclose(np.array(res["R"]), R_CAM, atol=0.03) and np.allclose(np.array(res["t"]), T_CAM, atol=0.005)
    with pytest.raises(ValueError):
        handeye.fit([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 0, 0], [0.001, 0, 0], [0.002, 0, 0]])


def test_plan_reaches_tab_with_correct_yaw():
    top = np.array([0.20, 0.03, 0.07])  # 상자 윗면 50mm + 손잡이 20mm
    p = grasp.plan(fake_locate(top, 30), HE)
    assert p["ok"], p
    q = K.from_lerobot(p["grasp"])
    T = K.SO101().fk(q)
    assert np.linalg.norm(T[:3, 3] - (top - [0, 0, 0.01])) < 0.002  # 손잡이 높이 가운데
    assert T[2, 2] < -0.99                                             # 집게가 아래를 향함
    closing = T[:3, 0] / np.linalg.norm(T[:3, 0])
    assert abs(abs(closing @ np.array([np.cos(np.radians(30)), np.sin(np.radians(30)), 0])) - 1) < 0.01
    za = K.SO101().fk(K.from_lerobot(p["approach"]))[2, 3]
    assert abs(za - (T[2, 3] + 0.025)) < 0.002


@pytest.mark.parametrize("loc, why", [
    ({"found": False, "reason": "no_box_shaped_object"}, "상자를 찾지 못함"),
    ("box_top", "손잡이 크기가 아님"),
    ("far", "허용"),
    ("tilted", "법선"),
    ("too_high", "역기구학"),
])
def test_plan_rejects_with_reason(loc, why):
    if loc == "box_top":
        loc = fake_locate([0.2, 0, 0.05], 0, size=(160, 130))
    elif loc == "far":
        loc = fake_locate([0.34, 0, 0.07], 0)
    elif loc == "tilted":
        loc = fake_locate([0.2, 0, 0.07], 0, normal=(np.sin(np.radians(30)), 0, np.cos(np.radians(30))))
    elif loc == "too_high":
        loc = fake_locate([0.2, 0, 0.16], 0)
    p = grasp.plan(loc, HE)
    assert not p["ok"] and why in p["reason"], p


class FakePicker:
    def __init__(self, loc, dry_run=False):
        self.loc, self.dry_run = loc, dry_run

    def locate(self):
        return self.loc

    def plan(self, loc):
        return grasp.plan(loc, HE)


class OkSensor:
    def inspect(self, session, specimen_id, face, attempt):
        return {"status": "ok", "specimen_id": specimen_id, "face": face, "attempt": attempt, "verdict": "review",
                "reasons": ["defect_rules_unavailable"], "features": {"simulated": True}, "images": {},
                "capture_id": f"{specimen_id}_{face}", "elapsed_ms": 1}


def calls_of(robot, kind):
    return [a for c, a in robot.calls if c == kind]


def test_sequence_vision_pick_order():
    robot = MockRobot(speed=0)
    r = Sequencer(robot, OkSensor(), settle_timeout_s=0.1,
                  picker=FakePicker(fake_locate([0.2, 0.0, 0.07], 0))).run("S01", "t")
    assert r["state"] == "done", r["error"]
    seq = [(c, a if c != "move_joints" else "joints") for c, a in robot.calls if c in ("move_to", "move_joints", "gripper")]
    i = seq.index(("move_joints", "joints"))
    assert seq[i:i + 4] == [("move_joints", "joints"), ("move_joints", "joints"), ("gripper", "closed"), ("move_joints", "joints")]
    assert ("move_to", "pick") not in seq and r["pick"]["mode"] == "vision" and r["pick"]["plan"]["ok"]


def test_sequence_vision_locate_failure_stops_before_grasp():
    robot = MockRobot(speed=0)
    r = Sequencer(robot, OkSensor(), settle_timeout_s=0.1,
                  picker=FakePicker({"found": False, "reason": "pick_area_has_no_depth"})).run("S02", "t")
    assert r["state"] == "error" and "비전 집기 계획 실패" in r["error"]
    assert ("gripper", "closed") not in robot.calls and not calls_of(robot, "move_joints") and robot.stopped


def test_sequence_vision_dry_run_stops_at_approach():
    robot = MockRobot(speed=0)
    r = Sequencer(robot, OkSensor(), settle_timeout_s=0.1,
                  picker=FakePicker(fake_locate([0.2, 0.0, 0.07], 0), dry_run=True)).run("S03", "t")
    assert r["state"] == "dry_run_done" and r["final_verdict"] is None
    assert len(calls_of(robot, "move_joints")) == 1 and ("gripper", "closed") not in robot.calls
    assert robot.calls[-1] == ("move_to", "home")


def test_app_refuses_vision_mode_without_handeye(monkeypatch, tmp_path):
    from app import create_app
    monkeypatch.setenv("PICK_MODE", "vision")
    monkeypatch.setenv("HANDEYE", str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeError, match="hand-eye"):
        create_app(robot=MockRobot(speed=0), sensor_url="http://127.0.0.1:9", db_path=tmp_path / "t.db")


def test_plan_cube_without_tab_uses_grasp_depth():
    # 10-09 시편: 70mm 정육면체(손잡이 없음). grasp_depth_mm만큼 윗면 아래를 집고, 접근은 그 위 25mm
    top = np.array([0.20, 0.0, 0.07])
    loc = fake_locate(top, 0, size=(70.0, 70.0))
    loc["mode"] = "front_face_model"
    cfg = dict(grasp.DEFAULTS, tab_height_mm=0.0, grasp_depth_mm=22.0)
    p = grasp.plan(loc, HE, cfg=cfg)
    assert p["ok"], p
    T = K.SO101().fk(K.from_lerobot(p["grasp"]))
    assert np.linalg.norm(T[:3, 3] - (top - [0, 0, 0.022])) < 0.002
    za = K.SO101().fk(K.from_lerobot(p["approach"]))[2, 3]
    assert abs(za - (T[2, 3] + 0.025)) < 0.002
    # grasp_depth_mm가 없으면 예전처럼 손잡이 높이의 절반
    p2 = grasp.plan(loc, HE, cfg=dict(grasp.DEFAULTS, tab_height_mm=20.0, grasp_depth_mm=None))
    T2 = K.SO101().fk(K.from_lerobot(p2["grasp"]))
    assert abs(T2[2, 3] - (0.07 - 0.01)) < 0.002


def test_plan_grasp_depth_from_box_height_reaches_both_specimens():
    # 10-09 시편 둘: 흰 70×70×90(깊이 35mm로 잘림), 갈색 80×80×45(20mm로 올림). 접근 20mm. 로봇 앞 16~24cm 전부 풀려야 한다
    cfg = dict(grasp.DEFAULTS, tab_height_mm=0.0, grasp_depth_mm=None, grasp_depth_frac=0.4, approach_mm=20.0, lift_mm=20.0)
    for h_mm, want_depth in ((90.0, 35.0), (45.0, 20.0)):
        for r in (0.16, 0.20, 0.24):
            loc = fake_locate(np.array([r, 0.0, h_mm / 1000]), 45)
            loc.update(mode="front_face_model", top_height_mm=h_mm)
            p = grasp.plan(loc, HE, cfg=cfg)
            assert p["ok"], (h_mm, r, p)
            assert p["grasp_depth_mm"] == want_depth
            T = K.SO101().fk(K.from_lerobot(p["grasp"]))
            assert abs(T[2, 3] - (h_mm - want_depth) / 1000) < 0.002
    # 90mm 상자에 접근 25mm(기본)는 수직 도달 한계를 넘어 거부되어야 한다(추측해서 움직이지 않음)
    loc = fake_locate(np.array([0.20, 0.0, 0.09]), 0)
    loc.update(mode="front_face_model", top_height_mm=90.0)
    p = grasp.plan(loc, HE, cfg=dict(grasp.DEFAULTS, tab_height_mm=0.0, grasp_depth_mm=22.0, approach_mm=25.0))
    assert not p["ok"] and "역기구학" in p["reason"]


def _side_loc(center_robot_m, height_mm, box_angle_deg=0):
    """로봇 좌표의 상자 바닥 중심 → 센서 front 모드 결과(카메라 좌표)."""
    inv = R_CAM.T
    c = np.asarray(center_robot_m, float)
    a = np.radians(box_angle_deg)
    return {"found": True, "mode": "front_face_model", "top_height_mm": height_mm, "box_mm": [70, 70, height_mm],
            "box_center_on_table_cam_mm": (inv @ (c - T_CAM) * 1000).tolist(),
            "top_center_cam_mm": (inv @ (c + [0, 0, height_mm / 1000] - T_CAM) * 1000).tolist(),
            "table_normal_cam": (inv @ np.array([0, 0, 1.0])).tolist(), "top_size_mm": None,
            "short_axis_cam": (inv @ np.array([np.cos(a), np.sin(a), 0])).tolist(),
            "long_axis_cam": (inv @ np.array([-np.sin(a), np.cos(a), 0])).tolist()}


def test_side_grasp_plans_horizontal_approach_in_reach_band():
    cfg = dict(grasp.DEFAULTS, grasp_mode="side")
    for r, h in ((0.40, 90.0), (0.42, 45.0), (0.44, 90.0)):
        p = grasp.plan(_side_loc([r, 0.05, 0.0], h, np.degrees(np.arctan2(.05, r))), HE, cfg=cfg)
        assert p["ok"] and p["grasp_mode"] == "side", (r, h, p)
        Tg = K.SO101().fk(K.from_lerobot(p["grasp"]))
        assert abs(Tg[2, 3] - h / 2000) < 0.003            # 집는 점 높이 = 상자 높이 절반
        assert abs(Tg[2, 2]) < 0.05                          # 도구 축 수평(옆에서 접근)
        Ta = K.SO101().fk(K.from_lerobot(p["approach"]))
        assert np.hypot(*Ta[:2, 3]) < np.hypot(*Tg[:2, 3]) - 0.015  # 접근점은 로봇 쪽으로 2~5cm 뒤(가까우면 자동으로 줄임)
        Tl = K.SO101().fk(K.from_lerobot(p["lift"]))
        assert abs(Tl[2, 3] - (Tg[2, 3] + 0.10)) < 0.003     # 들기 10cm
    # 너무 가까우면(20cm) 수평 접근이 안 풀리므로 이유와 함께 거부
    p = grasp.plan(_side_loc([0.20, 0.0, 0.0], 90.0), HE, cfg=cfg)
    assert not p["ok"] and "옆집기 허용" in p["reason"]
    # 중심·높이가 없는 결과(top 모드)는 거부
    p = grasp.plan({"found": True, "mode": "top", "table_normal_cam": [0, 0, 1]}, HE, cfg=cfg)
    assert not p["ok"] and "상자 중심" in p["reason"]


def test_box_type_from_depth_height():
    cfg = dict(grasp.DEFAULTS)
    assert grasp.box_type_for({"top_height_mm": 91.2}, cfg) == "white"
    assert grasp.box_type_for({"top_height_mm": 44.0}, cfg) == "brown"
    assert grasp.box_type_for({"top_height_mm": 70.0}, cfg) == ""
    assert grasp.box_type_for({}, cfg) == ""


def test_vision_regrasp_once_when_first_grasp_misses():
    # 첫 집기에서 빈손이면 열고 다시 찾아 한 번 더 집는다. MockRobot은 grasp_miss_once로 첫 닫힘만 놓친다
    from robot import MockRobot as _MR

    class MissOnce(_MR):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.closes = 0

        def set_gripper(self, state):
            super().set_gripper(state)
            if state == "closed":
                self.closes += 1
                if self.closes == 1:
                    self._holding = False  # 첫 번째만 놓침

    class Picker:
        dry_run = False
        retry_grasp = True

        def __init__(self):
            self.locates = 0

        def locate(self):
            self.locates += 1
            return {"found": True, "top_height_mm": 45.0, "box_center_on_table_cam_mm": [0, 0, 400]}

        def plan(self, loc):
            return {"ok": True, "approach": {}, "grasp": {}, "lift": {}}

        def box_type_for(self, loc):
            return "brown"

    robot = MissOnce(speed=0)
    picker = Picker()
    from test_sequencer import FakeSensor
    seq = Sequencer(robot, FakeSensor(), settle_timeout_s=0.1, picker=picker)
    r = seq.run("RG1", "t")
    assert r["state"] == "done", r
    assert picker.locates == 2 and robot.closes == 2
    assert [g["holding"] for g in r["grasp_checks"]][:2] == [False, True]
    assert r["pick"]["retry"]["plan"]["ok"] is True and r["box_type"] == "brown"
