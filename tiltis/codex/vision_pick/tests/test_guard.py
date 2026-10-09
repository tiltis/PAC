import copy
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import station_path

station_path()
import grasp
import kinematics as K
from guard import GuardedVisionPicker, Limits, calibration_error, observation_error
from robot import MockRobot
from sequencer import Sequencer


HE = {"R": np.diag([1.0, -1.0, -1.0]), "t": np.array([0.20, 0, 0.5]), "n": 6, "rms_mm": 1.2}
TEST_CFG = dict(grasp.DEFAULTS, workspace={"frame": "base_link", "units": "m",
                                        "min": [0.14, -0.1, 0.01], "max": [0.26, 0.1, 0.12]})


def observation(**changes):
    loc = {"found": True, "frame": "depth_camera_mm", "candidate_count": 1,
           "captured_at_s": 999.8, "top_center_cam_mm": [20.0, 0, 430.0],
           "intrinsics": {"width": 1280, "height": 800}, "bbox_px": [520, 360, 700, 540],
           "top_size_mm": [60.0, 25.0], "top_height_mm": 70.0,
           "table_normal_cam": [0, 0, -1.0], "short_axis_cam": [1.0, 0, 0]}
    loc.update(changes)
    return loc


class Sensor:
    def __init__(self, changes=None, repeated=False):
        self.count = 0
        self.changes = changes or (lambda i: {})
        self.repeated = repeated

    def locate(self):
        self.count += 1
        return observation(captured_at_s=999.8 + (0 if self.repeated else self.count * 0.01),
                           **self.changes(self.count))


def picker(sensor=None, he=None, **kwargs):
    return GuardedVisionPicker(sensor or Sensor(), HE if he is None else he,
                              cfg=copy.deepcopy(TEST_CFG), clock=lambda: 1000.0, **kwargs)


def test_stable_box_uses_existing_ik_planner_at_measured_position():
    p = picker()
    loc = p.locate()
    result = p.plan(loc)
    assert loc["stability_samples"] == 3 and result["ok"], result
    assert result["grasp_point_m"] == [0.22, 0.0, 0.06]
    assert result["hardware_motion_verified"] is False


@pytest.mark.parametrize("changes,reason", [
    ({"found": False, "reason": "no_box"}, "no_box"),
    ({"frame": "rgb_pixels"}, "unexpected_depth_frame_or_units"),
    ({"candidate_count": 2}, "single_box_not_confirmed"),
    ({"captured_at_s": None}, "missing_capture_timestamp"),
    ({"captured_at_s": 997.0}, "depth_observation_stale_or_clock_mismatch"),
    ({"captured_at_s": 1005.0}, "depth_observation_stale_or_clock_mismatch"),
    ({"top_center_cam_mm": [float("nan"), 0, 430]}, "invalid_depth_geometry"),
    ({"table_normal_cam": [0, 0, 0]}, "invalid_depth_geometry"),
    ({"short_axis_cam": [0, 0, 1]}, "box_axis_not_on_table_plane"),
    ({"top_size_mm": [-1, 25]}, "invalid_box_size"),
    ({"top_height_mm": float("inf")}, "invalid_box_height"),
    ({"bbox_px": [76, 4, 242, 124]}, "box_near_image_edge"),
    ({"intrinsics": {}}, "depth_image_bounds_missing"),
])
def test_invalid_observations_refused(changes, reason):
    assert observation_error(observation(**changes), 1000, Limits()) == reason


@pytest.mark.parametrize("changes,reason", [
    ({"R": np.diag([1, 1, -1])}, "handeye_rotation_invalid"),
    ({"R": np.eye(3) * 2}, "handeye_rotation_invalid"),
    ({"t": [float("nan"), 0, 0]}, "handeye_calibration_invalid"),
    ({"rms_mm": 20}, "handeye_residual_missing_or_excessive"),
    ({"rms_mm": None}, "handeye_residual_missing_or_excessive"),
    ({"n": 3}, "handeye_not_enough_points"),
])
def test_bad_calibration_refused(changes, reason):
    assert calibration_error(dict(HE, **changes), Limits()) == reason


def test_missing_calibration_refused_without_ik():
    p = picker()
    p.he = None
    assert p.plan(p.locate())["reason"] == "handeye_calibration_missing"


def test_moving_box_not_averaged_into_an_invented_target():
    p = picker(Sensor(lambda i: {"top_center_cam_mm": [20 + i * 6, 0, 430]}))
    assert p.locate() == {"found": False, "reason": "box_moved"}


def test_rotating_box_refused():
    p = picker(Sensor(lambda i: {"short_axis_cam": [np.cos(i * 0.4), np.sin(i * 0.4), 0]}))
    assert p.locate()["reason"] == "box_rotated"


def test_axis_sign_flip_is_same_gripper_orientation():
    p = picker(Sensor(lambda i: {"short_axis_cam": [(-1.0) ** i, 0, 0]}))
    assert p.locate()["found"]


def test_repeated_sensor_frame_refused():
    assert picker(Sensor(repeated=True)).locate()["reason"] == "depth_frame_repeated"


def test_sensor_disconnect_becomes_failed_locate():
    class Broken:
        def locate(self):
            raise ConnectionError("disconnected")
    assert picker(Broken()).locate()["found"] is False


def test_single_observation_not_accepted_by_plan():
    assert picker().plan(observation())["reason"] == "box_stability_not_confirmed"


def test_workspace_has_no_guessed_physical_default():
    p = picker()
    p.cfg.pop("workspace")
    assert p.plan(p.locate())["reason"] == "workspace_not_measured"


def test_approach_outside_workspace_refused_even_when_grasp_is_inside():
    p = picker()
    p.cfg["workspace"]["max"][2] = 0.07
    assert p.plan(p.locate())["reason"] == "approach_outside_measured_workspace"


@pytest.mark.parametrize("workspace", [
    {"frame": "camera", "units": "m", "min": [0, 0, 0], "max": [1, 1, 1]},
    {"frame": "base_link", "units": "mm", "min": [0, 0, 0], "max": [1, 1, 1]},
    {"frame": "base_link", "units": "m", "min": [None, 0, 0], "max": [1, 1, 1]},
    {"frame": "base_link", "units": "m", "min": [1, 0, 0], "max": [0, 1, 1]},
])
def test_invalid_workspace_does_not_reach_ik(workspace, monkeypatch):
    p = picker()
    p.cfg["workspace"] = workspace
    def forbidden(*args, **kwargs):
        raise AssertionError("IK must not run")
    monkeypatch.setattr(grasp.VisionPicker, "plan", forbidden)
    assert p.plan(p.locate())["ok"] is False


def test_ik_calculation_cannot_hide_aged_input(monkeypatch):
    clock = [1000.0]
    p = picker()
    p.clock = lambda: clock[0]
    loc = p.locate()
    def slow_plan(self, loc):
        clock[0] += 3
        return {"ok": True}
    monkeypatch.setattr(grasp.VisionPicker, "plan", slow_plan)
    assert p.plan(loc)["reason"] == "depth_observation_stale_or_clock_mismatch"


def test_box_moved_after_approach_stops_before_grasp():
    sensor = Sensor(lambda i: {"top_center_cam_mm": [20 if i <= 3 else 40, 0, 430]})
    p = picker(sensor)
    robot = MockRobot(speed=0)
    result = Sequencer(robot, sensor, picker=p, settle_timeout_s=0.1).run("S01", "test")
    assert result["state"] == "error" and "box_moved" in result["error"], result
    assert len([c for c, _ in robot.calls if c == "move_joints"]) == 1
    assert ("gripper", "closed") not in robot.calls and robot.stopped


def test_grasp_point_matches_calibration_for_boxes_without_handles():
    cfg = dict(grasp.DEFAULTS, tab_height_mm=0, grasp_depth_frac=0.4)
    for height, depth in [(90, 35), (45, 20)]:
        point, actual = grasp.camera_grasp_point(observation(top_height_mm=height), cfg)
        assert actual == depth
        assert np.allclose(point, [20, 0, 430 + depth])


def test_preview_endpoint_sends_no_motion_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("ROBOT", "mock")
    monkeypatch.setenv("PICK_MODE", "taught")
    monkeypatch.setenv("DB", str(tmp_path / "preview.db"))
    from fastapi.testclient import TestClient
    import station_app
    station_app.preview_picker.sensor = Sensor()
    station_app.preview_picker.he = copy.deepcopy(HE)
    station_app.preview_picker.cfg = copy.deepcopy(TEST_CFG)
    station_app.preview_picker.clock = lambda: 1000.0
    with TestClient(station_app.app) as client:
        result = client.get("/api/pick/preview")
        assert result.status_code == 200 and result.json()["motion_enabled"] is False
        assert result.json()["plan"]["ok"], result.json()
        ready = client.get("/api/pick/readiness").json()
        assert ready["pick_mode"] == "taught" and ready["recomputes_pick_each_cycle"] is False
        assert ready["readiness"]["ok"] and ready["motion_enabled"] is False
        assert not any(c in ("move_to", "move_joints", "gripper") for c, _ in station_app.seq.robot.calls)


def test_vision_entry_installs_guard_in_shared_sequencer(monkeypatch, tmp_path):
    import importlib
    import app as shared
    import handeye
    import station_app
    monkeypatch.setenv("PICK_MODE", "vision")
    monkeypatch.setenv("HANDEYE", str(tmp_path / "synthetic-handeye.json"))
    monkeypatch.setattr(handeye, "load", lambda path: copy.deepcopy(HE))
    configured = shared.create_app(robot=MockRobot(speed=0), db_path=tmp_path / "guarded.db")
    monkeypatch.setattr(shared, "app", configured)
    wrapped = importlib.reload(station_app)
    try:
        assert isinstance(configured.state.sequencer.picker, GuardedVisionPicker)
        assert wrapped.app is configured
        assert wrapped.seq.robot.is_mock
    finally:
        configured.state.sequencer.sensor.close()


class RelocatingSensor(Sensor):
    """Synthetic camera: same installation, newly placed box for each cycle."""
    def set_box(self, xyz, height, retake=False):
        self.xyz, self.height, self.retake = np.asarray(xyz, float), height, retake

    def locate(self):
        self.count += 1
        inv = HE["R"].T
        base = inv @ (self.xyz - HE["t"]) * 1000
        top = inv @ (self.xyz + [0, 0, self.height / 1000] - HE["t"]) * 1000
        return observation(mode="front_face_model", captured_at_s=999.8 + self.count * 0.01,
                           box_center_on_table_cam_mm=base.tolist(), top_center_cam_mm=top.tolist(),
                           top_height_mm=self.height, box_mm=[80, 80, self.height])

    def inspect(self, session, specimen_id, face, attempt):
        verdict = "unmeasurable" if self.retake and face == "A" and attempt == 0 else "no_anomaly"
        return {"status": "ok", "specimen_id": specimen_id, "face": face, "attempt": attempt,
                "verdict": verdict, "reasons": [], "features": {"simulated": True,
                "defect_inspected": True, "defect_rules_version": "test-1"}, "images": {}}


class FixedInspectionRobot(MockRobot):
    def __init__(self):
        # Only inspection/destination poses. Deliberately no taught pick or lift.
        super().__init__(speed=0, poses={"joints": {p: {} for p in
                         ("home", "face_A", "face_B", "face_C", "bin_ok", "bin_human")},
                         "gripper": {"held_white": 45, "held_brown": 55}})

    def move_to(self, name, duration_s):
        assert name in self.poses["joints"], f"Unexpected fixed picking pose: {name}"
        super().move_to(name, duration_s)


def side_picker(sensor):
    # Virtual bounds for model testing, never copied to the physical station.
    cfg = dict(grasp.DEFAULTS, grasp_mode="side", workspace={"frame": "base_link", "units": "m",
               "min": [0.30, -0.12, 0.005], "max": [0.48, 0.12, 0.18]})
    return GuardedVisionPicker(sensor, copy.deepcopy(HE), cfg=cfg, joint_map={}, clock=lambda: 1000.0)


@pytest.mark.parametrize("height,box", [(45, "brown"), (90, "white")])
def test_each_cycle_recomputes_pick_for_shifted_box_without_teaching(height, box):
    sensor, robot = RelocatingSensor(), FixedInspectionRobot()
    p = side_picker(sensor)
    he_before = copy.deepcopy(p.he)
    seq = Sequencer(robot, sensor, picker=p, faces="A,B,C", settle_timeout_s=0.1)
    targets = []
    for i, xy in enumerate(((0.40, -0.025), (0.42, 0.0), (0.44, 0.025))):
        sensor.set_box([*xy, 0], height)
        start = len(robot.calls)
        result = seq.run(f"S{i}", "relocated")
        assert result["state"] == "done", result["error"]
        assert result["box_type"] == box and result["box_type_source"] == "depth_height"
        assert result["placed_bin"] == "ok" and result["destination"]["color"] == "blue"
        moves = [v for k, v in robot.calls[start:] if k == "move_joints"]
        assert len(moves) == 3  # current approach, grasp, lift; no saved pick/lift positions
        target = result["pick"]["plan"]["grasp_point_m"]
        assert np.allclose(target, [*xy, height / 2000], atol=0.0001)
        actual = K.SO101().fk(K.from_lerobot(moves[1]))[:3, 3]
        assert np.linalg.norm(actual - target) < 0.003
        cam_point, h = grasp.camera_grasp_point(sensor.locate(), p.cfg)
        assert np.allclose(p.he["R"] @ cam_point / 1000 + p.he["t"], target)
        assert h == height / 2
        targets.append(target)
    assert len({tuple(v) for v in targets}) == 3
    assert np.array_equal(p.he["R"], he_before["R"]) and np.array_equal(p.he["t"], he_before["t"])
    assert sensor.count == 21  # 3 locate + 3 after approach + 1 test observation, per cycle


def test_vision_retake_uses_current_computed_lift_without_taught_lift():
    sensor, robot = RelocatingSensor(), FixedInspectionRobot()
    sensor.set_box([0.42, 0, 0], 45, retake=True)
    result = Sequencer(robot, sensor, picker=side_picker(sensor), settle_timeout_s=0.1).run("R", "test")
    assert result["state"] == "done" and result["retakes_used"] == 1, result
    moves = [v for k, v in robot.calls if k == "move_joints"]
    assert len(moves) == 4 and moves[3] == moves[2]


@pytest.mark.parametrize("missing", ["calibration", "workspace"])
def test_unready_installation_rejected_before_home_or_gripper_commands(missing):
    p = picker()
    if missing == "calibration":
        p.he = None
    else:
        p.cfg.pop("workspace")
    robot = MockRobot(speed=0)
    result = Sequencer(robot, p.sensor, picker=p).run("X", "test")
    assert result["state"] == "error" and robot.stopped
    assert not any(k in ("move_to", "move_joints", "gripper") for k, _ in robot.calls)
    assert p.sensor.count == 0


def test_side_table_center_must_be_finite_before_ik(monkeypatch):
    sensor = RelocatingSensor()
    sensor.set_box([0.42, 0, 0], 45)
    p = side_picker(sensor)
    loc = p.locate()
    loc["box_center_on_table_cam_mm"][0] = float("nan")
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid side geometry must not reach IK")
    monkeypatch.setattr(grasp.VisionPicker, "plan", forbidden)
    assert p.plan(loc)["reason"] == "invalid_side_grasp_geometry"


def test_regrasp_after_empty_gripper_rechecks_box_before_second_close():
    sensor = Sensor(lambda i: {"top_center_cam_mm": [20 if i <= 9 else 40, 0, 430]})
    robot = MockRobot(speed=0, fail_on={"grasp_miss"})
    result = Sequencer(robot, sensor, picker=picker(sensor)).run("RETRY", "test")
    assert result["state"] == "error" and "box_moved" in result["error"], result
    assert len([v for k, v in robot.calls if k == "move_joints"]) == 4
    assert robot.calls.count(("gripper", "closed")) == 1 and robot.stopped
