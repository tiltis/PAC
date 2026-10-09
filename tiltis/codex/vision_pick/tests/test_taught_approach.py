import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taught_approach import load_teaching, plan_taught_approach, validate_joint_segment
import kinematics as K


def arm(values):
    result = K.to_lerobot(np.radians(values))
    result["gripper.pos"] = 57.5
    return result


@pytest.fixture
def taught():
    # Recorded endpoint regression fixture; it is not an automatic safe pose.
    home = arm([-3.120879120879121, -84.3076923076923, 40.747252747252745,
                45.142857142857146, -92.17582417582418])
    lower = arm([-13.582417582417582, 49.67032967032967, 53.23076923076923,
                 -90.06593406593407, -92])
    return {"schema": "pac-home-descent-teaching-v1", "units": {"arm": "deg"},
            "home_joints": home, "taught_lower_joints": lower,
            "hardware_motion_validated": False}


def plan(taught, approach=None, grasp=None, **kwargs):
    lower = taught["taught_lower_joints"]
    return plan_taught_approach(taught, taught["home_joints"],
                               lower if approach is None else approach,
                               lower if grasp is None else grasp, **kwargs)


def test_preserves_taught_endpoints_and_declares_joint_path(taught):
    before = copy.deepcopy(taught)
    result = plan(taught)
    assert taught == before
    assert result["descend"][-1] == {k: v for k, v in taught["taught_lower_joints"].items() if k != "gripper.pos"}
    assert result["forward"][-1] == result["descend"][-1]
    meta = result["metadata"]
    assert meta["strict_vertical"] is False
    assert meta["interpolation"] == "joint_linear"
    assert meta["transit_floor_m"] == 0
    assert 0 < meta["minimum_tcp_z_m"]["descend"] < .001
    assert meta["max_joint_delta_deg"]["descend"] > 130
    assert meta["final_grasp_checked"] and not meta["final_grasp_changed"]
    assert not meta["hardware_motion_validated"]
    assert len(meta["sampled_path_xyz_m"]) > 135


def test_home_seed_must_match_recording(taught):
    seed = copy.deepcopy(taught["home_joints"])
    seed["shoulder_pan.pos"] += .1
    with pytest.raises(ValueError, match="home seed differs"):
        plan_taught_approach(taught, seed, taught["taught_lower_joints"], taught["taught_lower_joints"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "57"])
def test_saved_six_joint_observations_must_be_finite_numbers(taught, value):
    taught["taught_lower_joints"]["gripper.pos"] = value
    with pytest.raises(ValueError, match="finite numeric"):
        plan(taught)


def test_model_joint_limits_are_not_relaxed(taught):
    taught["taught_lower_joints"]["wrist_roll.pos"] = -163.38
    with pytest.raises(ValueError, match="wrist_roll.*outside model joint limits"):
        plan(taught)


def test_final_grasp_is_validated_before_returning_any_route(taught):
    grasp = copy.deepcopy(taught["taught_lower_joints"])
    grasp["shoulder_lift.pos"] += 3
    with pytest.raises(ValueError, match="below table"):
        plan(taught, grasp=grasp)


def test_loader_preserves_file_and_rejects_conflicting_duplicate_observation(tmp_path, taught):
    path = tmp_path / "teaching.json"
    payload = json.dumps(taught).encode()
    path.write_bytes(payload)
    loaded = load_teaching(path)
    assert len(loaded["_source_sha256"]) == 64
    loaded["home_joints"]["wrist_roll.pos"] = 0
    assert path.read_bytes() == payload
    taught["home"] = {"joints": dict(taught["home_joints"])}
    taught["home"]["joints"]["shoulder_pan.pos"] += 1
    path.write_text(json.dumps(taught))
    with pytest.raises(ValueError, match="inconsistent duplicated home"):
        load_teaching(path)


def test_joint_mapping_used_without_changing_observation(taught):
    expected = plan(taught)
    mapping = {"shoulder_pan": {"sign": -1, "offset_deg": 10}}
    for key in ("home_joints", "taught_lower_joints"):
        taught[key]["shoulder_pan.pos"] = -taught[key]["shoulder_pan.pos"] + 10
    result = plan(taught, joint_map=mapping)
    assert np.allclose(result["metadata"]["path_xyz_m"], expected["metadata"]["path_xyz_m"])


def test_no_gripper_commands_are_generated(taught):
    result = plan(taught)
    assert set(result["descend"][0]) == {f"{name}.pos" for name in K.ARM_JOINTS}
    assert set(result["forward"][0]) == {f"{name}.pos" for name in K.ARM_JOINTS}


def test_initial_or_return_segment_validates_whole_joint_curve(taught):
    result = validate_joint_segment(taught["home_joints"], taught["taught_lower_joints"])
    assert 0 < result["minimum_tcp_z_m"] < .001
    assert result["max_joint_delta_deg"] > 130
    with pytest.raises(ValueError, match="required floor"):
        validate_joint_segment(taught["home_joints"], taught["taught_lower_joints"], min_tip_z_m=.01)


def test_positive_endpoints_do_not_hide_below_table_interpolation():
    start = arm([32.14807709, 3.14218679, 68.65811349, 81.76202169, 61.64237193])
    end = arm([-78.58196208, -50.67902291, -20.37866370, -10.78222914, -51.93029510])
    model = K.SO101()
    assert model.fk(K.from_lerobot(start))[2, 3] > .02
    assert model.fk(K.from_lerobot(end))[2, 3] > .02
    with pytest.raises(ValueError, match="below table"):
        validate_joint_segment(start, end)


@pytest.mark.parametrize("floor", [float("nan"), -.01, True])
def test_segment_floor_cannot_be_negative_or_nonfinite(taught, floor):
    with pytest.raises(ValueError, match="nonnegative"):
        validate_joint_segment(taught["home_joints"], taught["taught_lower_joints"], min_tip_z_m=floor)


def test_segment_ignores_optional_gripper_but_requires_all_arm_joints(taught):
    start = copy.deepcopy(taught["home_joints"])
    start["gripper.pos"] = float("nan")
    assert validate_joint_segment(start, taught["taught_lower_joints"])["model_only"]
    del start["wrist_roll.pos"]
    with pytest.raises(ValueError, match="all five arm"):
        validate_joint_segment(start, taught["taught_lower_joints"])
