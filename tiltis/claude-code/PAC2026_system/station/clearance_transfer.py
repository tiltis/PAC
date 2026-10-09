"""Offline SO-101 lift/transfer/place planning; importing this module opens no device.

The caller must supply the measured table, box dimensions and calibrated jaw offset.
The TCP-centred bounding sphere is conservative during transit, assuming the box
centre is at the configured jaw point and the grasp does not slip. This is model
validation, not proof of physical collision avoidance, tracking or stable placement.
The taught release pose is preserved; object tilt/contact at release is a separate
check. The existing home route is deliberately outside this planner.
"""
from __future__ import annotations

import math

import numpy as np

import kinematics as K


_POSITION_TOL_M = 0.0001
_ORIENTATION_TOL_DEG = 0.1
_VERTICAL_XY_TOL_M = 0.001
_STEP_M = 0.010
_MAX_SPAN_DEG = 120.0


def _vector(value, size, label):
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: finite {size}-vector required") from exc
    if result.shape != (size,) or not np.all(np.isfinite(result)):
        raise ValueError(f"{label}: finite {size}-vector required")
    return result


def _scalar(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: finite value required") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label}: finite value required")
    return result


def _q(joints, joint_map, label):
    if not isinstance(joints, dict):
        raise ValueError(f"{label}: joint dictionary required")
    arm = {}
    for name in K.ARM_JOINTS:
        key = f"{name}.pos"
        if key not in joints:
            raise ValueError(f"{label}: missing {key}")
        arm[key] = _scalar(joints[key], f"{label}.{key}")
    return K.from_lerobot(arm, joint_map)


def _validate_joint_map(joint_map):
    if joint_map is None:
        return {}
    if not isinstance(joint_map, dict):
        raise ValueError("joint_map: dictionary required")
    for name, entry in joint_map.items():
        if name not in K.ARM_JOINTS or not isinstance(entry, dict):
            raise ValueError("joint_map: invalid arm joint")
        if _scalar(entry.get("sign", 1), f"joint_map.{name}.sign") not in (-1, 1):
            raise ValueError("joint_map: sign must be -1 or +1")
        _scalar(entry.get("offset_deg", 0), f"joint_map.{name}.offset_deg")
    return joint_map


def _rotation_error_deg(first, second):
    return float(np.degrees(np.arccos(np.clip((np.trace(first.T @ second) - 1) / 2, -1, 1))))


def _check_limits(model, q, label):
    if not np.all(np.isfinite(q)) or np.any(q < model.lower - 1e-9) or np.any(q > model.upper + 1e-9):
        raise ValueError(f"{label}: joint limit violation")


def _sample_joint_segment(start, end):
    """Model the actual joint-linear interpolation at no more than 1 degree."""
    count = max(1, int(math.ceil(float(np.max(np.abs(np.degrees(end - start)))))))
    return [start + (end - start) * (i / count) for i in range(count + 1)]


def _full_pose_ik(model, position, rotation, seed, label):
    """Constrain the complete rotation, including roll, using the existing FK."""
    def residual(q):
        frame = model.fk(q)
        return np.r_[frame[:3, 3] - position, 0.2 * (frame[:3, :3] - rotation).ravel()]

    q = seed.copy()
    for _ in range(500):
        frame = model.fk(q)
        if (np.linalg.norm(frame[:3, 3] - position) <= _POSITION_TOL_M
                and _rotation_error_deg(frame[:3, :3], rotation) <= _ORIENTATION_TOL_DEG):
            _check_limits(model, q, label)
            return q
        r = residual(q)
        jacobian = np.column_stack([
            (residual(q + np.eye(5)[i] * 1e-6) - r) / 1e-6 for i in range(5)
        ])
        step = -np.linalg.solve(jacobian.T @ jacobian + 1e-4 * np.eye(5), jacobian.T @ r)
        q = np.clip(q + np.clip(step, -0.1, 0.1), model.lower, model.upper)
        if np.linalg.norm(step) < 1e-9:
            break
    raise ValueError(f"{label}: full-pose IK unavailable")


def _up_pose_name(joints, name):
    candidates = [name + "_up"]
    for suffix in ("_brown", "_white"):
        if name.endswith(suffix):
            base = name[:-len(suffix)]
            candidates = [base + "_up" + suffix, name + "_up", base + "_up"]
            break
    for candidate in candidates:
        if candidate in joints:
            return candidate
    raise ValueError(f"{name}: taught upper pose required ({', '.join(candidates)})")


def _vertical(model, start, target_z, rotation, label, final=None):
    """Cartesian samples whose individual joint segments are subsequently checked."""
    frame = model.fk(start)
    position = frame[:3, 3].copy()
    count = max(1, int(math.ceil(abs(target_z - position[2]) / _STEP_M)))
    waypoints, previous = [], start
    for i in range(1, count + 1):
        goal = position.copy()
        goal[2] += (target_z - position[2]) * (i / count)
        if final is not None and i == count:
            current = final.copy()
        else:
            current = _full_pose_ik(model, goal, rotation, previous, label)
        waypoints.append(current)
        previous = current
    return waypoints


def plan_transfer(current_joints, poses, bin_pose_name, joint_map=None, initial_lift_mm=15.0,
                  *, box_dimensions_mm=None, jaw_offset_m=None, table_z_m=None, clearance_mm=10.0,
                  max_span_deg=120.0):
    """Return arm-only waypoints for lift, travel, lower and retract, or raise.

    No movement or calibration writes occur. A caller must finish this function
    successfully before moving, retain its own strict measured-arrival checks,
    and open the gripper only after executing the complete lower stage.
    """
    joint_map = _validate_joint_map(joint_map)
    dimensions = _vector(box_dimensions_mm, 3, "box_dimensions_mm")
    offset = _vector(jaw_offset_m, 3, "jaw_offset_m")
    table = _scalar(table_z_m, "table_z_m")
    lift_mm = _scalar(initial_lift_mm, "initial_lift_mm")
    margin_mm = _scalar(clearance_mm, "clearance_mm")
    span_limit = _scalar(max_span_deg, "max_span_deg")
    if np.any(dimensions <= 0) or lift_mm <= 0 or margin_mm < 0:
        raise ValueError("box dimensions and lift must be positive; clearance must be nonnegative")
    if not 0 < span_limit <= _MAX_SPAN_DEG:
        raise ValueError(f"max_span_deg must be positive and at most {_MAX_SPAN_DEG:g}")
    if not isinstance(poses, dict) or not isinstance(poses.get("joints"), dict):
        raise ValueError("poses.joints: dictionary required")
    joints = poses["joints"]
    if not isinstance(bin_pose_name, str) or bin_pose_name not in joints:
        raise ValueError("taught release pose missing")
    up_name = _up_pose_name(joints, bin_pose_name)
    model = K.SO101()
    start = _q(current_joints, joint_map, "current")
    release = _q(joints[bin_pose_name], joint_map, "release")
    taught_up = _q(joints[up_name], joint_map, "upper")
    for name, q in (("current", start), ("release", release), ("upper", taught_up)):
        _check_limits(model, q, name)
    current_frame, release_frame, taught_up_frame = (model.fk(q) for q in (start, release, taught_up))
    if taught_up_frame[2, 3] <= release_frame[2, 3] + _POSITION_TOL_M:
        raise ValueError("upper pose must be above release")
    if np.linalg.norm(taught_up_frame[:2, 3] - release_frame[:2, 3]) > _VERTICAL_XY_TOL_M:
        raise ValueError("upper pose must share release XY")
    sphere_m = float(np.linalg.norm(dimensions) / 2000 + np.linalg.norm(offset))
    minimum_z = table + sphere_m + margin_mm / 1000
    lifted_z = max(current_frame[2, 3] + lift_mm / 1000, taught_up_frame[2, 3])
    lift = _vertical(model, start, lifted_z, current_frame[:3, :3], "lift")
    # Preserve the taught RELEASE orientation, rather than the approximate roll
    # in an old generated upper pose. Its measured XY/Z are retained.
    upper_position = release_frame[:3, 3].copy()
    upper_position[2] = taught_up_frame[2, 3]
    upper = _full_pose_ik(model, upper_position, release_frame[:3, :3], taught_up, "upper")
    lower = _vertical(model, upper, release_frame[2, 3], release_frame[:3, :3], "lower", final=release)
    retract = [q.copy() for q in reversed([upper] + lower[:-1])]
    stages = {"lift": lift, "travel": [upper], "lower": lower, "retract": retract}
    minimum_by_stage = {}
    joint_span_by_stage, joint_path_by_stage = {}, {}
    previous = start
    for name, waypoints in stages.items():
        stage_points = np.array([previous] + waypoints)
        joint_span_by_stage[name] = float(np.max(np.degrees(np.ptp(stage_points, axis=0))))
        joint_path_by_stage[name] = float(np.sum(np.max(np.abs(np.degrees(np.diff(stage_points, axis=0))), axis=1)))
        if joint_span_by_stage[name] > span_limit:
            raise ValueError(f"{name}: joint span exceeds {span_limit:g} degrees")
        minimum_by_stage[name] = math.inf
        vertical = name != "travel"
        reference = current_frame if name == "lift" else release_frame
        last_z = float(model.fk(previous)[2, 3])
        for waypoint in waypoints:
            for q in _sample_joint_segment(previous, waypoint):
                _check_limits(model, q, name)
                frame = model.fk(q)
                z = float(frame[2, 3])
                minimum_by_stage[name] = min(minimum_by_stage[name], z)
                if name in ("lift", "travel") and z < minimum_z - 1e-9:
                    raise ValueError(f"{name}: box transit clearance below minimum")
                if vertical:
                    if np.linalg.norm(frame[:2, 3] - reference[:2, 3]) > _VERTICAL_XY_TOL_M:
                        raise ValueError(f"{name}: vertical XY error exceeds 1 mm")
                    if _rotation_error_deg(frame[:3, :3], reference[:3, :3]) > 2.0:
                        raise ValueError(f"{name}: orientation error exceeds 2 degrees")
                    direction = -1 if name == "lower" else 1
                    if direction * (z - last_z) < -_POSITION_TOL_M:
                        raise ValueError(f"{name}: nonmonotonic vertical segment")
                    last_z = z
            previous = waypoint
    return {
        **{name: [K.to_lerobot(q, joint_map) for q in waypoints] for name, waypoints in stages.items()},
        "metadata": {
            "frame": "base_link", "units": "m", "release_pose": bin_pose_name, "upper_pose": up_name,
            "initial_lift_m": float(model.fk(lift[-1])[2, 3] - current_frame[2, 3]),
            "box_dimensions_mm": dimensions.tolist(), "jaw_offset_m": offset.tolist(), "table_z_m": table,
            "box_bound_radius_m": sphere_m, "required_transit_tcp_z_m": minimum_z, "transit_floor_m": minimum_z,
            "minimum_tcp_z_m": minimum_by_stage, "sample_max_joint_step_deg": 1.0,
            "max_span_deg": span_limit, "max_joint_delta_deg": joint_span_by_stage,
            "joint_path_length_deg": joint_path_by_stage,
            "model_only": True, "physical_collision_verified": False,
        },
    }
