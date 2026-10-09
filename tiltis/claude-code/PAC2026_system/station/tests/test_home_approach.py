"""Offline home XY descent / level forward contract and rejection regressions."""
import copy

import numpy as np
import pytest

import clearance_transfer as C
import home_approach as H
import kinematics as K


def joints(degrees):
    return K.to_lerobot(np.radians(degrees))


@pytest.fixture
def poses():
    # Numerically reachable regression examples, never loaded as field defaults.
    return {
        "home": joints([-7.75722324, 34.71307183, -.61248035, -28.38633618, -87.10757421]),
        "target": joints([-7.7572, 48.0246, -9.8922, -32.4183, -87.1076]),
    }


def plan(poses, **kwargs):
    cfg = {"table_z_m": 0, "min_tip_clearance_mm": 10}
    cfg.update(kwargs)
    return H.plan_home_approach(poses["home"], poses["target"], **cfg)


def test_descend_then_forward_exact_endpoints_no_input_mutation(poses):
    before = copy.deepcopy(poses)
    out = plan(poses)
    assert list(out) == ["descend", "forward", "metadata"]
    assert out["descend"] and out["forward"]
    assert out["forward"][-1] == pytest.approx(poses["target"])
    assert poses == before
    model = K.SO101()
    home = model.fk(K.from_lerobot(poses["home"]))
    lowered = model.fk(K.from_lerobot(out["descend"][-1]))
    target = model.fk(K.from_lerobot(poses["target"]))
    assert np.linalg.norm(home[:2, 3] - lowered[:2, 3]) < .001
    assert abs(target[2, 3] - lowered[2, 3]) < .001
    assert home[2, 3] - lowered[2, 3] == pytest.approx(.03, abs=.0002)
    assert C._rotation_error_deg(home[:3, :3], lowered[:3, :3]) < .1
    metadata = out["metadata"]
    assert len(metadata["path_xyz_m"]) == 1 + len(out["descend"]) + len(out["forward"])
    assert metadata["transit_floor_m"] == .01
    assert metadata["frame"] == "base_link" and metadata["units"] == "m"
    assert metadata["model_only"] and not metadata["physical_collision_verified"]


def test_commanded_interpolation_keeps_vertical_then_horizontal(poses):
    out = plan(poses)
    model = K.SO101()
    previous = K.from_lerobot(poses["home"])
    home_xy = model.fk(previous)[:2, 3]
    level = out["metadata"]["descent_z_m"]
    for stage in ("descend", "forward"):
        for target in out[stage]:
            current = K.from_lerobot(target)
            # Denser independent sampling than the planner's <=1 degree checks.
            for ratio in np.linspace(0, 1, 101):
                point = model.fk(previous + (current - previous) * ratio)[:3, 3]
                assert point[2] >= .01
                if stage == "descend":
                    assert np.linalg.norm(point[:2] - home_xy) < .001
                else:
                    assert abs(point[2] - level) < .001
            previous = current


def test_forward_can_interpolate_full_orientation_without_changing_height(poses):
    poses["target"] = joints([-7.751472965337213, 47.95849327907101, -23.065492091807553,
                              -9.179869514419115, -87.10762273772339])
    out = plan(poses)
    assert len(out["forward"]) >= 2
    assert out["forward"][-1] == pytest.approx(poses["target"])


def test_current_field_home_reports_exact_offending_joint(poses):
    poses["home"] = joints([11.20879121, -22.94505495, -27.56043956, 56.13186813, -163.38461538])
    with pytest.raises(ValueError, match=r"home: wrist_roll -163\.3846 deg outside.*-157\.2110"):
        plan(poses)


def test_optional_descent_height_must_preserve_horizontal_leg(poses):
    z = K.SO101().fk(K.from_lerobot(poses["target"]))[2, 3]
    out = plan(poses, descent_z_m=z)
    assert out["metadata"]["requested_descent_z_m"] == z
    with pytest.raises(ValueError, match="would not be horizontal"):
        plan(poses, descent_z_m=z + .01)


def test_taught_lower_is_validated_without_overriding_final_target(poses):
    original = plan(poses)
    taught = original["descend"][-1]
    out = plan(poses, taught_lower_joints=taught)
    assert out["metadata"]["taught_lower_supplied"]
    assert out["forward"][-1] == pytest.approx(poses["target"])
    moved = dict(taught)
    moved["shoulder_pan.pos"] += 3
    with pytest.raises(ValueError, match="retain home XY"):
        plan(poses, taught_lower_joints=moved)


def test_taught_lower_wrong_rotation_is_rejected(poses):
    taught = plan(poses)["descend"][-1]
    taught["wrist_roll.pos"] += .5
    with pytest.raises(ValueError, match="complete home orientation"):
        plan(poses, taught_lower_joints=taught)


def test_no_diagonal_fallback_when_vertical_leg_is_unreachable(poses):
    # A valid target pose exists, but keeping this high home's full pose during
    # the requested vertical descent is not possible under the joint limits.
    poses["home"] = joints([0, -60, 60, -80, 0])
    with pytest.raises(ValueError, match="IK unavailable"):
        plan(poses)


def test_target_above_home_does_not_become_an_upward_route(poses):
    poses["home"], poses["target"] = poses["target"], poses["home"]
    with pytest.raises(ValueError, match="target must be lower"):
        plan(poses)


def test_missing_table_or_tip_clearance_has_no_default(poses):
    with pytest.raises(TypeError):
        H.plan_home_approach(poses["home"], poses["target"])


@pytest.mark.parametrize("key,value", [("table_z_m", None), ("table_z_m", float("nan")),
                                      ("min_tip_clearance_mm", -1), ("descent_z_m", float("inf"))])
def test_invalid_installation_input_is_rejected(poses, key, value):
    with pytest.raises(ValueError):
        plan(poses, **{key: value})


def test_tool_clearance_is_required_before_any_route_is_returned(poses):
    with pytest.raises(ValueError, match="required table/tip clearance"):
        plan(poses, table_z_m=.1)


def test_target_joint_limits_are_checked_before_ik(poses):
    poses["target"]["elbow_flex.pos"] = 180
    with pytest.raises(ValueError, match="target: elbow_flex.*outside"):
        plan(poses)


def test_no_gripper_commands_and_joint_map_is_respected(poses):
    mapping = {"shoulder_pan": {"sign": -1, "offset_deg": 3}}
    for pose in poses.values():
        pose["shoulder_pan.pos"] = -pose["shoulder_pan.pos"] + 3
        pose["gripper.pos"] = 55
    out = plan(poses, joint_map=mapping)
    for stage in ("descend", "forward"):
        assert all("gripper.pos" not in point for point in out[stage])
    assert out["forward"][-1]["shoulder_pan.pos"] == pytest.approx(poses["target"]["shoulder_pan.pos"])


def test_rotation_interpolation_remains_valid_at_180_degrees():
    start, end = np.eye(3), K._axis_angle([1, 0, 0], np.pi)
    at = H._rotation_path(start, end)
    for ratio in (0, .25, .5, .75, 1):
        result = at(ratio)
        assert np.allclose(result.T @ result, np.eye(3))
        assert np.linalg.det(result) == pytest.approx(1)
    assert np.allclose(at(1), end)


def test_identical_fk_rotations_do_not_normalize_a_zero_axis():
    model = K.SO101()
    for q in np.random.default_rng(12).uniform(model.lower, model.upper, (30, 5)):
        rotation = model.fk(q)[:3, :3]
        midpoint = H._rotation_path(rotation, rotation)(.5)
        assert np.isfinite(midpoint).all()
        assert np.allclose(midpoint, rotation)
