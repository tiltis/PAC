"""Rotation must change approach and jaws together, independent of box position."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import station_path
station_path()
import grasp

HE = {"R": np.diag([1.0, -1.0, -1.0]), "t": np.array([0.2, 0, 0.5])}


def edges(angle):
    a = np.radians(angle)
    return {"long_axis_cam": [np.cos(a), np.sin(a), 0], "short_axis_cam": [-np.sin(a), np.cos(a), 0],
            "table_normal_cam": [0,0,-1]}


@pytest.mark.parametrize("angle", [-70, -30, 20, 70])
def test_rotated_box_sets_perpendicular_edge_aligned_approach_and_jaws(angle):
    loc = edges(angle)
    approach, jaw, yaw, _ = grasp.side_box_alignment(loc, HE, [.42, 0, .04])
    expected = [HE["R"] @ loc[key] for key in ("long_axis_cam", "short_axis_cam")]
    assert max(abs(np.dot(approach, axis)) for axis in expected) > .99999
    assert max(abs(np.dot(jaw, axis)) for axis in expected) > .99999
    assert abs(np.dot(approach, jaw)) < 1e-6 and approach[0] > 0
    assert np.allclose([np.cos(yaw), np.sin(yaw), 0], jaw)
    assert abs(np.dot(approach, [1, 0, 0])) < .99  # previously ignored box angle and always used radial


def test_side_plan_passes_same_box_orientation_to_approach_grasp_and_lift_ik():
    class IKSolver:
        def __init__(self):
            self.calls = []

        def ik(self, position, down, yaw, q0):
            self.calls.append((position.copy(), down.copy(), yaw))
            return np.zeros(5)

        def error(self, *args):
            return [0, 0]

    model = IKSolver()
    loc = dict(edges(20), top_height_mm=45, table_normal_cam=[0, 0, -1],
               box_center_on_table_cam_mm=[220, 0, 500], top_center_cam_mm=[220, 0, 455])
    cfg = dict(grasp.DEFAULTS, grasp_mode="side", side_alignment='box')
    result = grasp.plan_side(loc, HE, model, cfg)
    assert result["ok"] and result["orientation_source"] == "depth_camera_box_axes", result
    assert len(model.calls) == 3
    approach = np.array(result["approach_axis_base"])
    for _, direction, yaw in model.calls:
        assert np.allclose(direction, approach, atol=1e-6)
        assert abs(np.degrees(yaw) - result["yaw_deg"]) < .1
    # Field planner solves grasp first, then searches a raised approach near that IK branch.
    delta = model.calls[0][0] - model.calls[1][0]
    assert np.isclose(np.dot(delta, approach), .05, atol=1e-6)
    assert np.isclose(delta[2], -result["approach_back_mm"][1] / 1000, atol=1e-6)


@pytest.mark.parametrize("bad", [None, [0, 0, 0], [0, 0, 1], [float("nan"), 1, 0], [1, 0, 0], [0,1,1]])
def test_invalid_or_parallel_axes_cannot_generate_a_gripper_angle(bad):
    loc = dict(edges(0), short_axis_cam=bad)
    with pytest.raises((ValueError, TypeError)):
        grasp.side_box_alignment(loc, HE, [.42, 0, .04])


def test_180_degree_axis_sign_change_is_same_jaw_and_approach():
    a = grasp.side_box_alignment(edges(20), HE, [.42, 0, .04])
    b = grasp.side_box_alignment(edges(200), HE, [.42, 0, .04])
    assert np.allclose(a[0], b[0]) and abs(np.dot(a[1], b[1])) > .99999


def test_unreachable_box_aligned_orientation_is_refused_without_radial_fallback():
    import kinematics as K
    loc = dict(edges(30), top_height_mm=45, table_normal_cam=[0,0,-1],
               box_center_on_table_cam_mm=[220,0,500], top_center_cam_mm=[220,0,455])
    result = grasp.plan_side(loc, HE, K.SO101(), dict(grasp.DEFAULTS, grasp_mode='side', side_alignment='box'))
    assert result['ok'] is False and 'approach' not in result


def test_jaw_tcp_correction_does_not_rotate_away_from_measured_box_edges():
    class Solver:
        def __init__(self): self.positions = []
        def ik(self, p, down, yaw, q0=None):
            self.positions.append((p.copy(), down.copy(), yaw))
            return np.zeros(5)
        def error(self, *args): return [0, 0]
    model = Solver()
    loc = dict(edges(20), top_height_mm=90, box_center_on_table_cam_mm=[220, 0, 500])
    offset = [-.0281, .019, -.0347]
    p = grasp.plan_side(loc, HE, model, dict(grasp.DEFAULTS, grasp_mode="side", side_alignment='box', side_jaw_offset_frame_m=offset))
    assert p["ok"], p
    tip, direction, yaw = model.positions[0]
    jaw = np.array([np.cos(yaw), np.sin(yaw), 0])
    R = np.column_stack([jaw, np.cross(direction, jaw), direction])
    # Reconstructed jaw center, rather than the fingertip, must hit the measured box center.
    assert np.allclose(tip + R @ offset, [.42, 0, .045])
    assert abs(np.dot(jaw, HE["R"] @ loc["short_axis_cam"])) > .999
