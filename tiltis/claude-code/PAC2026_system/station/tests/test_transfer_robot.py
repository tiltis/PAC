"""SO-101 transfer adapter checks without connecting or moving any hardware."""
import json
import sys
from types import ModuleType

import numpy as np
import pytest

import kinematics as K
from robot import RobotError, So101Robot


# Recorded face_A from the shared poses.json; this is an offline FK fixture,
# not a command to a robot. Keep the fixture independent of later reteaching.
CURRENT = {
    "shoulder_pan.pos": -7.75722323972503,
    "shoulder_lift.pos": 34.713071833011405,
    "elbow_flex.pos": -0.6124803526222483,
    "wrist_flex.pos": -28.386336177802153,
    "wrist_roll.pos": -87.1075742124377,
    "gripper.pos": 54.94125777470629,
}


@pytest.fixture
def offline_robot(tmp_path, monkeypatch):
    station = tmp_path / "station"
    (station / "calib").mkdir(parents=True)
    (tmp_path / "sensor/calib").mkdir(parents=True)
    robot = So101Robot("TEST_PORT_NEVER_CONNECTED", poses_path=station / "poses.json")
    robot.poses = {"joints": {"bin_ok": dict(CURRENT), "bin_human": dict(CURRENT)}}
    monkeypatch.setattr(robot, "current_joints", lambda: dict(CURRENT))
    monkeypatch.setattr(K, "load_joint_map", lambda: {})
    def never_move(*args, **kwargs):
        pytest.fail("Transfer planning/verification must not move the robot")
    monkeypatch.setattr(robot, "_move_joints", never_move)
    monkeypatch.setattr(robot, "connect", never_move)
    return robot


@pytest.fixture
def planner_spy(monkeypatch):
    """Isolate the adapter contract from the separately tested route planner."""
    module = ModuleType("clearance_transfer")
    calls = []
    sentinel = {"route": "offline planner result"}
    def plan_transfer(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel
    module.plan_transfer = plan_transfer
    monkeypatch.setitem(sys.modules, "clearance_transfer", module)
    return calls, sentinel, module


def write_config(robot, boxes=None, absolute_z=True):
    root = robot.poses_path.parent.parent
    cfg = {"side_use_absolute_z": absolute_z,
           "side_jaw_offset_frame_m": [-0.0281, 0.019, -0.0347]}
    objects = {"boxes_mm": [[80, 80, 45], [70, 70, 90], [160, 130, 50]]
               if boxes is None else boxes}
    (root / "station/calib/grasp_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "sensor/calib/object_config.json").write_text(json.dumps(objects), encoding="utf-8")
    return root, cfg, objects


def test_plan_reuses_loaded_pose_actual_reading_and_largest_configured_box(offline_robot, planner_spy):
    calls, sentinel, _ = planner_spy
    _, cfg, _ = write_config(offline_robot)
    assert offline_robot.plan_transfer("bin_human") is sentinel
    args, kwargs = calls[0]
    assert args == (CURRENT, offline_robot.poses, "bin_human")
    assert args[1] is offline_robot.poses
    assert kwargs["box_dimensions_mm"] == [160, 130, 50]
    assert kwargs["jaw_offset_m"] == cfg["side_jaw_offset_frame_m"]
    assert kwargs["joint_map"] == {} and kwargs["table_z_m"] == 0.0
    assert offline_robot._robot is None


def test_plan_accepts_single_box_configuration(offline_robot, planner_spy):
    root, _, _ = write_config(offline_robot)
    (root / "sensor/calib/object_config.json").write_text(
        json.dumps({"box_mm": [92, 83, 61]}), encoding="utf-8")
    offline_robot.plan_transfer("bin_ok")
    assert planner_spy[0][0][1]["box_dimensions_mm"] == [92, 83, 61]


@pytest.mark.parametrize("missing", ["station/calib/grasp_config.json", "sensor/calib/object_config.json"])
def test_plan_requires_both_installation_configs(offline_robot, planner_spy, missing):
    root, _, _ = write_config(offline_robot)
    (root / missing).unlink()
    with pytest.raises(RobotError):
        offline_robot.plan_transfer("bin_ok")
    assert planner_spy[0] == []


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_plan_rejects_unconfirmed_absolute_height(offline_robot, planner_spy, value):
    write_config(offline_robot, absolute_z=value)
    with pytest.raises(RobotError):
        offline_robot.plan_transfer("bin_ok")
    assert planner_spy[0] == []


@pytest.mark.parametrize("boxes", [[[80, 80, float("nan")]], [[80, 0, 45]],
                                  [[80, -2, 45]], [[80, True, 45]],
                                  [[80, 45]], [[80, "80", 45]], []])
def test_plan_rejects_invalid_or_missing_dimensions(offline_robot, planner_spy, boxes):
    write_config(offline_robot, boxes=boxes)
    with pytest.raises(RobotError):
        offline_robot.plan_transfer("bin_ok")
    assert planner_spy[0] == []


def test_planner_rejection_is_reported_without_motion(offline_robot, planner_spy):
    write_config(offline_robot)
    def reject(*args, **kwargs):
        raise ValueError("no collision-free route")
    planner_spy[2].plan_transfer = reject
    with pytest.raises(RobotError, match="no collision-free route"):
        offline_robot.plan_transfer("bin_ok")
    assert offline_robot._robot is None


def route(stage="travel", floor=0.10, target=None):
    return {stage: [dict(CURRENT) if target is None else target],
            "metadata": {"transit_floor_m": floor}}


@pytest.mark.parametrize("stage", ["lift", "travel", "lower", "retract"])
def test_actual_pose_reaches_stage_target(offline_robot, stage):
    result = offline_robot.verify_transfer_stage(stage, route(stage))
    assert result["ok"] is True
    assert result["position_error_mm"] == 0.0
    assert result["orientation_error_deg"] == 0.0
    assert result["tcp_z_mm"] > 100


@pytest.mark.parametrize("stage", ["lift", "travel", "retract"])
def test_target_reached_but_actual_tcp_below_transit_floor_is_rejected(offline_robot, stage):
    # Exact target match still cannot authorize sideways travel below the floor.
    result = offline_robot.verify_transfer_stage(stage, route(stage, floor=0.11))
    assert result["position_error_mm"] == 0
    assert result["orientation_error_deg"] == 0
    assert result["ok"] is False


def test_lower_may_reach_taught_placement_below_transit_floor(offline_robot):
    result = offline_robot.verify_transfer_stage("lower", route("lower", floor=0.20))
    assert result["ok"] is True
    assert result["tcp_z_mm"] < 200


@pytest.mark.parametrize("joint,delta,ok,exceeded", [
    ("shoulder_pan.pos", 0.7, True, None),
    ("shoulder_pan.pos", 0.8, False, "position_error_mm"),
    ("wrist_roll.pos", 4.9, True, None),
    ("wrist_roll.pos", 5.1, False, "orientation_error_deg"),
])
def test_actual_pose_has_independent_5mm_and_5degree_limits(offline_robot, monkeypatch, joint, delta, ok, exceeded):
    actual = dict(CURRENT)
    actual[joint] += delta
    monkeypatch.setattr(offline_robot, "current_joints", lambda: actual)
    result = offline_robot.verify_transfer_stage("travel", route())
    assert result["ok"] is ok
    if exceeded:
        assert result[exceeded] > 5
        other = "orientation_error_deg" if exceeded == "position_error_mm" else "position_error_mm"
        assert result[other] < 5
    else:
        assert result["position_error_mm"] < 5 and result["orientation_error_deg"] < 5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_actual_observation_cannot_pass(offline_robot, monkeypatch, value):
    actual = dict(CURRENT, **{"wrist_roll.pos": value})
    monkeypatch.setattr(offline_robot, "current_joints", lambda: actual)
    assert offline_robot.verify_transfer_stage("lower", route("lower"))["ok"] is False


@pytest.mark.parametrize("stage", ["travel", "lower"])
def test_nonfinite_target_cannot_pass(offline_robot, stage):
    target = dict(CURRENT, **{"wrist_roll.pos": float("nan")})
    assert offline_robot.verify_transfer_stage(stage, route(stage, target=target))["ok"] is False


@pytest.mark.parametrize("stage", ["travel", "lower"])
def test_nan_floor_is_rejected_even_for_lowering(offline_robot, stage):
    assert offline_robot.verify_transfer_stage(stage, route(stage, floor=float("nan")))["ok"] is False


def test_verification_uses_configured_joint_mapping(offline_robot, monkeypatch):
    mapping = {"shoulder_lift": {"sign": -1, "offset_deg": 12.0}}
    monkeypatch.setattr(K, "load_joint_map", lambda: mapping)
    expected_z = float(K.SO101().fk(K.from_lerobot(CURRENT, mapping))[2, 3])
    result = offline_robot.verify_transfer_stage("lower", route("lower", floor=expected_z + 0.01))
    assert result["ok"] is True
    assert result["tcp_z_mm"] == pytest.approx(expected_z * 1000, abs=0.011)
    assert not np.isclose(expected_z, K.SO101().fk(K.from_lerobot(CURRENT))[2, 3])


@pytest.mark.parametrize("source", ["actual", "target"])
def test_transfer_duration_rejects_nan_joint_values_without_motion(offline_robot, monkeypatch, source):
    target = dict(CURRENT)
    if source == "actual":
        actual = dict(CURRENT, **{"shoulder_lift.pos": float("nan")})
        monkeypatch.setattr(offline_robot, "current_joints", lambda: actual)
    else:
        target["shoulder_lift.pos"] = float("nan")
    with pytest.raises(RobotError):
        offline_robot.transfer_duration(target, 0.2)
    assert offline_robot._robot is None


def test_transfer_duration_respects_joint_rate_and_caller_minimum(offline_robot):
    target = dict(CURRENT)
    target["wrist_roll.pos"] += 60.0
    duration = offline_robot.transfer_duration(target, 0.2)
    assert duration >= 60.0 / 20.0 - 1e-12
    assert offline_robot.transfer_duration(target, 8.0) == pytest.approx(8.0)
    assert offline_robot._robot is None


def test_transfer_duration_reads_actual_joints_each_time(offline_robot, monkeypatch):
    target = dict(CURRENT, **{"wrist_roll.pos": CURRENT["wrist_roll.pos"] + 60})
    first = offline_robot.transfer_duration(target, 0.1)
    actual = dict(CURRENT, **{"wrist_roll.pos": target["wrist_roll.pos"] - 10})
    monkeypatch.setattr(offline_robot, "current_joints", lambda: actual)
    second = offline_robot.transfer_duration(target, 0.1)
    assert first >= 3 - 1e-12 and second >= 0.5 - 1e-12
    assert second < first


def test_vertical_transfer_duration_covers_cartesian_distance_at_50mm_per_second(offline_robot):
    # Use independent existing IK to construct an offline 30mm vertical pair.
    # This checks commanded/model duration, not measured physical robot speed.
    model = K.SO101()
    start_q = K.from_lerobot(CURRENT)
    start = model.fk(start_q)
    end_q = model.ik(start[:3, 3] + [0, 0, 0.03], down=start[:3, 2],
                     q0=start_q, seeds=0, iters=100, tol_mm=0.01, tol_deg=0.1)
    assert end_q is not None
    end = model.fk(end_q)
    assert np.linalg.norm(end[:2, 3] - start[:2, 3]) < 0.0001
    distance_m = float(np.linalg.norm(end[:3, 3] - start[:3, 3]))
    assert distance_m == pytest.approx(0.03, abs=0.0001)
    duration = offline_robot.transfer_duration(K.to_lerobot(end_q), 0.1)
    assert duration >= distance_m / 0.05
    assert offline_robot._robot is None


def test_transfer_duration_rejects_nan_minimum(offline_robot):
    with pytest.raises(RobotError):
        offline_robot.transfer_duration(dict(CURRENT), float("nan"))
