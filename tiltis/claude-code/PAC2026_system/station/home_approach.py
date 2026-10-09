"""Pure, complete-before-motion home descent then horizontal approach planning.

The tool reference is gripper_frame_link, in base_link metres. Descent keeps
home XY and the complete home orientation. Forward travel follows a straight
horizontal XY line and interpolates the complete rotation towards the target.
An unreachable orientation/path fails; there is no diagonal or free-rotation
fallback. The target can be the existing pre-grasp pose; its later grasp leg
must be validated by the caller. This module connects no hardware and does not
establish physical obstacle clearance or end-effector tracking accuracy.
"""
from __future__ import annotations

import math

import numpy as np

import kinematics as K
from clearance_transfer import (
    _full_pose_ik, _q, _rotation_error_deg, _sample_joint_segment,
    _scalar, _validate_joint_map,
)


_CARTESIAN_STEP_M = 0.010
_PATH_TOL_M = 0.001
_ROTATION_STEP_DEG = 5.0
_MAX_STAGE_SPAN_DEG = 120.0


def _limits(model, q, label):
    if not np.isfinite(q).all():
        raise ValueError(f"{label}: nonfinite joint angle")
    for index, name in enumerate(K.ARM_JOINTS):
        if q[index] < model.lower[index] - 1e-9 or q[index] > model.upper[index] + 1e-9:
            raise ValueError(
                f"{label}: {name} {np.degrees(q[index]):.4f} deg outside "
                f"[{np.degrees(model.lower[index]):.4f}, {np.degrees(model.upper[index]):.4f}] deg"
            )


def _rotation_path(start, end):
    """Return a shortest SO(3) path, including the numerically difficult pi case."""
    relative = start.T @ end
    angle = float(np.arccos(np.clip((np.trace(relative) - 1) / 2, -1, 1)))
    # FK roundoff can produce acos(1-epsilon) while the skew vector is zero.
    if angle < 1e-7:
        return lambda fraction: start.copy()
    if math.pi - angle < 1e-5:
        values, vectors = np.linalg.eig(relative)
        axis = np.real(vectors[:, np.argmin(np.abs(values - 1))])
    else:
        axis = np.array([relative[2, 1] - relative[1, 2],
                         relative[0, 2] - relative[2, 0],
                         relative[1, 0] - relative[0, 1]])
    axis /= np.linalg.norm(axis)

    def at(fraction):
        if fraction >= 1:
            return end.copy()
        return start @ K._axis_angle(axis, angle * fraction)
    return at


def plan_home_approach(home_joints, grasp_joints, joint_map=None, *, table_z_m,
                       min_tip_clearance_mm, descent_z_m=None, taught_lower_joints=None):
    """Return ``descend``, ``forward`` arm waypoints and JSON-safe metadata.

    table_z_m and min_tip_clearance_mm are explicit installation inputs. Optional
    descent height or a taught lower pose must agree with the target height to
    within 1 mm. Taught lower XY/orientation must agree with home (1 mm/0.1 deg).
    The exact target Z determines the horizontal plane, avoiding an added final
    diagonal segment. The taught target joints themselves are the final waypoint.
    """
    joint_map = _validate_joint_map(joint_map)
    table = _scalar(table_z_m, "table_z_m")
    clearance = _scalar(min_tip_clearance_mm, "min_tip_clearance_mm")
    if clearance < 0:
        raise ValueError("min_tip_clearance_mm must be nonnegative")
    model = K.SO101()
    home = _q(home_joints, joint_map, "home")
    target = _q(grasp_joints, joint_map, "target")
    _limits(model, home, "home")
    _limits(model, target, "target")
    home_frame, target_frame = model.fk(home), model.fk(target)
    target_z = float(target_frame[2, 3])
    if target_z >= home_frame[2, 3] - 0.0001:
        raise ValueError("target must be lower than home for vertical descent")
    if descent_z_m is not None:
        requested_z = _scalar(descent_z_m, "descent_z_m")
        if abs(requested_z - target_z) > _PATH_TOL_M:
            raise ValueError("descent_z_m differs from target height; forward leg would not be horizontal")
    else:
        requested_z = None
    if taught_lower_joints is not None:
        lower = _q(taught_lower_joints, joint_map, "taught_lower")
        _limits(model, lower, "taught_lower")
        lower_frame = model.fk(lower)
        if np.linalg.norm(lower_frame[:2, 3] - home_frame[:2, 3]) > _PATH_TOL_M:
            raise ValueError("taught_lower must retain home XY")
        if _rotation_error_deg(lower_frame[:3, :3], home_frame[:3, :3]) > 0.1:
            raise ValueError("taught_lower must retain complete home orientation")
        if abs(lower_frame[2, 3] - target_z) > _PATH_TOL_M:
            raise ValueError("taught_lower differs from target height; forward leg would not be horizontal")
        if requested_z is not None and abs(lower_frame[2, 3] - requested_z) > _PATH_TOL_M:
            raise ValueError("taught_lower and descent_z_m disagree")
    minimum_tip_z = table + clearance / 1000
    if target_z < minimum_tip_z:
        raise ValueError("target is below the required table/tip clearance")

    stages = {"descend": [], "forward": []}
    start_position = home_frame[:3, 3].copy()
    lower_position = start_position.copy()
    lower_position[2] = target_z
    descend_count = max(1, int(math.ceil((start_position[2] - target_z) / _CARTESIAN_STEP_M)))
    previous = home
    for i in range(1, descend_count + 1):
        goal = start_position + (lower_position - start_position) * (i / descend_count)
        previous = _full_pose_ik(model, goal, home_frame[:3, :3], previous, "home descend")
        stages["descend"].append(previous)

    delta_xy = target_frame[:2, 3] - lower_position[:2]
    distance_xy = float(np.linalg.norm(delta_xy))
    rotation = _rotation_path(home_frame[:3, :3], target_frame[:3, :3])
    rotation_degrees = _rotation_error_deg(home_frame[:3, :3], target_frame[:3, :3])
    forward_count = max(1, int(math.ceil(distance_xy / _CARTESIAN_STEP_M)),
                        int(math.ceil(rotation_degrees / _ROTATION_STEP_DEG)))
    for i in range(1, forward_count + 1):
        fraction = i / forward_count
        goal = lower_position.copy()
        goal[:2] += delta_xy * fraction
        if i == forward_count:
            current = target.copy()  # Preserve the existing target, including its IK branch.
        else:
            current = _full_pose_ik(model, goal, rotation(fraction), previous, "home forward")
        stages["forward"].append(current)
        previous = current

    previous = home
    minimum_by_stage, span_by_stage, path_by_stage = {}, {}, {}
    for stage, points in stages.items():
        all_points = np.array([previous] + points)
        span = float(np.max(np.degrees(np.ptp(all_points, axis=0))))
        if span > _MAX_STAGE_SPAN_DEG:
            raise ValueError(f"{stage}: joint span exceeds {_MAX_STAGE_SPAN_DEG:g} degrees")
        span_by_stage[stage] = span
        path_by_stage[stage] = float(np.sum(np.max(np.abs(np.degrees(np.diff(all_points, axis=0))), axis=1)))
        minimum_by_stage[stage] = math.inf
        last_z = float(model.fk(previous)[2, 3])
        last_progress = 0.0
        for index, endpoint in enumerate(points):
            samples = _sample_joint_segment(previous, endpoint)
            for sample_index, q in enumerate(samples):
                _limits(model, q, stage)
                frame = model.fk(q)
                position = frame[:3, 3]
                minimum_by_stage[stage] = min(minimum_by_stage[stage], float(position[2]))
                if position[2] < minimum_tip_z - 1e-9:
                    raise ValueError(f"{stage}: table/tip clearance violated along joint interpolation")
                if stage == "descend":
                    if np.linalg.norm(position[:2] - start_position[:2]) > _PATH_TOL_M:
                        raise ValueError("descend: home XY changed by more than 1 mm")
                    if position[2] > last_z + 0.0001:
                        raise ValueError("descend: nonmonotonic vertical descent")
                    expected_rotation = home_frame[:3, :3]
                    last_z = float(position[2])
                else:
                    if abs(position[2] - target_z) > _PATH_TOL_M:
                        raise ValueError("forward: horizontal height changed by more than 1 mm")
                    fraction = (index + sample_index / max(1, len(samples) - 1)) / len(points)
                    if distance_xy > 1e-9:
                        progress = float(np.dot(position[:2] - lower_position[:2], delta_xy) / distance_xy ** 2)
                        closest = lower_position[:2] + np.clip(progress, 0, 1) * delta_xy
                        if np.linalg.norm(position[:2] - closest) > _PATH_TOL_M:
                            raise ValueError("forward: XY line error exceeds 1 mm")
                        if (progress - last_progress) * distance_xy < -0.0001:
                            raise ValueError("forward: nonmonotonic horizontal path")
                        last_progress = progress
                    elif np.linalg.norm(position[:2] - lower_position[:2]) > _PATH_TOL_M:
                        raise ValueError("forward: in-place XY error exceeds 1 mm")
                    expected_rotation = rotation(fraction)
                if _rotation_error_deg(frame[:3, :3], expected_rotation) > 2.0:
                    raise ValueError(f"{stage}: complete orientation interpolation error exceeds 2 degrees")
            previous = endpoint
    return {
        **{name: [K.to_lerobot(q, joint_map) for q in points] for name, points in stages.items()},
        "metadata": {
            "frame": "base_link", "tool_frame": "gripper_frame_link", "units": "m",
            "home_xyz_m": start_position.tolist(), "lower_xyz_m": lower_position.tolist(),
            "target_xyz_m": target_frame[:3, 3].tolist(), "descent_z_m": target_z,
            "requested_descent_z_m": requested_z, "taught_lower_supplied": taught_lower_joints is not None,
            "table_z_m": table, "minimum_tip_z_m": minimum_tip_z,
            "transit_floor_m": minimum_tip_z,
            "path_xyz_m": [model.fk(q)[:3, 3].tolist() for q in [home] + stages["descend"] + stages["forward"]],
            "minimum_tcp_z_m": minimum_by_stage, "max_joint_delta_deg": span_by_stage,
            "joint_path_length_deg": path_by_stage, "sample_max_joint_step_deg": 1.0,
            "model_only": True, "physical_collision_verified": False,
        },
    }
