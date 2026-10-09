"""Portable offline checks of the field-shaped route; these move no hardware."""
import copy

import numpy as np
import pytest

import kinematics as K
import clearance_transfer as CT


def joints(values):
    return {f"{name}.pos": value for name, value in zip(K.ARM_JOINTS, values)}


@pytest.fixture
def field():
    # Numerical regression samples, not calibrated defaults or deployment data.
    return {
        "joints": {
            "face_B": joints([-7.69230769, 19.65934066, -37.45054945, 73.71428571, -77.23076923]),
            "face_C": joints([-6.02197802, 65.19780220, -40.46153846, -93.31868132, -77.14285714]),
            "bin_ok": joints([19.29670330, 76.30769231, -46.72527473, -14.98901099, -86.37362637]),
            "bin_ok_up": joints([19.29717733, 46.42434255, -44.19646846, 12.36552323, -87.15744563]),
            "bin_human": joints([-28.17532496, 66.20231364, -34.29549646, -13.97274910, -87.13118543]),
            "bin_human_up": joints([-28.17532483, 42.65387396, -44.30708721, 19.58727166, -87.20317089]),
        }
    }


def plan(field, source="face_B", destination="bin_ok", **kwargs):
    config = dict(box_dimensions_mm=[80, 80, 45], jaw_offset_m=[-.0281, .019, -.0347], table_z_m=0)
    config.update(kwargs)
    return CT.plan_transfer(field["joints"][source], field, destination, **config)


@pytest.mark.parametrize("box_dimensions_mm", [[80, 80, 45], [70, 70, 90]])
@pytest.mark.parametrize("destination", ["bin_ok", "bin_human"])
def test_lift_travel_lower_release_and_reverse_retract(field, destination, box_dimensions_mm):
    source = "face_B"
    before = copy.deepcopy(field)
    result = plan(field, source, destination, box_dimensions_mm=box_dimensions_mm)
    stages = {name: result[name] for name in ("lift", "travel", "lower", "retract")}
    assert list(stages) == ["lift", "travel", "lower", "retract"]
    assert all(stages.values())
    assert field == before
    assert stages["lower"][-1] == pytest.approx(field["joints"][destination])
    assert stages["retract"][-1] == stages["travel"][-1]
    model = K.SO101()
    initial = model.fk(K.from_lerobot(field["joints"][source]))
    lifted = model.fk(K.from_lerobot(stages["lift"][-1]))
    assert lifted[2, 3] >= initial[2, 3] + .0148
    assert np.linalg.norm(lifted[:2, 3] - initial[:2, 3]) < .001
    assert CT._rotation_error_deg(lifted[:3, :3], initial[:3, :3]) < .1
    for name in ("lift", "travel"):
        assert result["metadata"]["minimum_tcp_z_m"][name] >= result["metadata"]["required_transit_tcp_z_m"]
    assert all(set(q) == {f"{name}.pos" for name in K.ARM_JOINTS} for points in stages.values() for q in points)


@pytest.mark.parametrize("destination", ["bin_ok", "bin_human"])
def test_face_c_transit_clearance_and_explicit_span_limit(field, destination):
    result = plan(field, source="face_C", destination=destination)
    metadata = result["metadata"]
    assert 90 < metadata["max_joint_delta_deg"]["travel"] <= 120
    assert metadata["minimum_tcp_z_m"]["travel"] >= metadata["transit_floor_m"]
    assert metadata["joint_path_length_deg"]["travel"] >= metadata["max_joint_delta_deg"]["travel"]
    with pytest.raises(ValueError, match="travel: joint span"):
        plan(field, source="face_C", destination=destination, max_span_deg=90)


def test_vertical_path_samples_interpolation_not_just_endpoints(field):
    result = plan(field)
    model = K.SO101()
    previous = K.from_lerobot(result["travel"][-1])
    release = model.fk(K.from_lerobot(field["joints"]["bin_ok"]))
    for waypoint in result["lower"]:
        current = K.from_lerobot(waypoint)
        for sample in CT._sample_joint_segment(previous, current):
            frame = model.fk(sample)
            assert np.linalg.norm(frame[:2, 3] - release[:2, 3]) < .001
            assert CT._rotation_error_deg(frame[:3, :3], release[:3, :3]) < 2
        previous = current


@pytest.mark.parametrize("variant", ["bin_ok_up_brown", "bin_ok_brown_up", "bin_ok_up"])
def test_box_specific_up_pose_resolution(field, variant):
    field["joints"]["bin_ok_brown"] = field["joints"]["bin_ok"]
    upper = field["joints"].pop("bin_ok_up")
    field["joints"][variant] = upper
    assert plan(field, destination="bin_ok_brown")["metadata"]["upper_pose"] == variant


def test_no_upper_pose_rejects_without_fallback(field):
    del field["joints"]["bin_ok_up"]
    with pytest.raises(ValueError, match="upper pose required"):
        plan(field)


@pytest.mark.parametrize("key,value", [("box_dimensions_mm", None), ("jaw_offset_m", None), ("table_z_m", None),
                                       ("box_dimensions_mm", [80, float("nan"), 45]), ("initial_lift_mm", 0)])
def test_missing_or_invalid_geometry_is_rejected(field, key, value):
    with pytest.raises(ValueError):
        plan(field, **{key: value})


def test_too_large_lift_cannot_silently_rotate_or_move_sideways(field):
    with pytest.raises(ValueError, match="IK unavailable"):
        plan(field, initial_lift_mm=60)


def test_insufficient_box_clearance_rejects_entire_route(field):
    with pytest.raises(ValueError, match="clearance below minimum"):
        plan(field, box_dimensions_mm=[160, 160, 160])


@pytest.mark.parametrize("value", [float("nan"), 999])
def test_nonfinite_or_outside_joint_limits_rejected(field, value):
    field["joints"]["face_B"]["shoulder_pan.pos"] = value
    with pytest.raises(ValueError):
        plan(field)


def test_joint_jump_is_rejected_without_wrapping_roll(field):
    field["joints"]["face_B"]["wrist_roll.pos"] += 180
    with pytest.raises(ValueError, match="joint span|IK unavailable|clearance"):
        plan(field)


def test_span_cap_cannot_be_raised_beyond_120_degrees(field):
    with pytest.raises(ValueError, match="max_span_deg"):
        plan(field, max_span_deg=121)


def test_joint_map_conversion_and_no_gripper_output(field):
    mapped = copy.deepcopy(field)
    joint_map = {"shoulder_pan": {"sign": -1, "offset_deg": 5}}
    for pose in mapped["joints"].values():
        pose["shoulder_pan.pos"] = -pose["shoulder_pan.pos"] + 5
        pose["gripper.pos"] = 50
    result = plan(mapped, joint_map=joint_map)
    assert result["lower"][-1]["shoulder_pan.pos"] == pytest.approx(mapped["joints"]["bin_ok"]["shoulder_pan.pos"])
    assert all("gripper.pos" not in q for name in ("lift", "travel", "lower", "retract") for q in result[name])


def test_misplaced_upper_xy_rejected(field):
    field["joints"]["bin_ok_up"]["shoulder_pan.pos"] += 3
    with pytest.raises(ValueError, match="share release XY"):
        plan(field)
