"""Offline validation of the explicitly selected hand-taught approach mode.

This is JOINT interpolation through the recorded HOME and LOWER, not Cartesian
vertical descent. Its scoped table clearance is zero metres, as explicitly
accepted for this taught path; the usual 10 mm rule elsewhere is not modified.
No robot, camera, file-write, torque or calibration API is used here. Endpoints
and the existing vision grasp are preserved exactly. Sampled model checks do
not establish physical contact/collision safety or actual joint tracking.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from numbers import Real
from pathlib import Path

import numpy as np

from bootstrap import station_path

station_path()
import kinematics as K
from clearance_transfer import _sample_joint_segment, _validate_joint_map


ARM_KEYS = tuple(f"{name}.pos" for name in K.ARM_JOINTS)
OBSERVATION_KEYS = set(ARM_KEYS) | {"gripper.pos"}


def _joints(value, label, *, observation=False):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: joint dictionary required")
    expected = OBSERVATION_KEYS if observation else set(ARM_KEYS)
    if observation and set(value) != expected:
        raise ValueError(f"{label}: six recorded joints required")
    if not expected <= set(value):
        raise ValueError(f"{label}: all five arm joints required")
    for key in expected:
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, Real) or not math.isfinite(number):
            raise ValueError(f"{label}: finite numeric {key} required")
    return {key: float(value[key]) for key in ARM_KEYS}


def _recorded(teaching):
    if not isinstance(teaching, dict) or teaching.get("schema") != "pac-home-descent-teaching-v1":
        raise ValueError("unsupported or missing teaching schema")
    units = teaching.get("units")
    if not isinstance(units, dict) or units.get("arm") != "deg":
        raise ValueError("teaching arm units must be degrees")
    result = {}
    for section, flat in (("home", "home_joints"), ("lower", "taught_lower_joints")):
        nested = teaching.get(section)
        nested = nested.get("joints") if isinstance(nested, dict) else None
        primary = teaching.get(flat, nested)
        result[section] = _joints(primary, f"recorded {section}", observation=True)
        if nested is not None and flat in teaching:
            _joints(nested, f"nested {section}", observation=True)
            if any(abs(float(primary[key]) - float(nested[key])) > 1e-9 for key in OBSERVATION_KEYS):
                raise ValueError(f"inconsistent duplicated {section} observations")
    return result


def load_teaching(path):
    """Read an independent snapshot; no mutation of the teaching file occurs."""
    path = Path(path)
    payload = path.read_bytes()
    data = json.loads(payload.decode("utf-8-sig"))
    _recorded(data)
    data["_source_sha256"] = hashlib.sha256(payload).hexdigest()
    data["_source_path"] = str(path.resolve())
    return data


def _within_limits(model, q, label):
    if not np.isfinite(q).all():
        raise ValueError(f"{label}: nonfinite joint angle")
    for i, name in enumerate(K.ARM_JOINTS):
        if q[i] < model.lower[i] - 1e-9 or q[i] > model.upper[i] + 1e-9:
            raise ValueError(f"{label}: {name} {np.degrees(q[i]):.4f} deg outside model joint limits")


def validate_joint_segment(start_joints, target_joints, joint_map=None, min_tip_z_m=0.0):
    """Check an actual start->target joint-linear leg without moving hardware.

    Five arm joints are mandatory; a gripper entry is ignored. This helper is
    also suitable for the initial taught HOME and the empty return leg. The
    caller chooses where this scoped zero-clearance teaching policy applies.
    """
    if (isinstance(min_tip_z_m, bool) or not isinstance(min_tip_z_m, Real)
            or not math.isfinite(min_tip_z_m) or min_tip_z_m < 0):
        raise ValueError("min_tip_z_m must be a finite nonnegative number")
    joint_map = _validate_joint_map(joint_map)
    start = K.from_lerobot(_joints(start_joints, "segment start"), joint_map)
    target = K.from_lerobot(_joints(target_joints, "segment target"), joint_map)
    model = K.SO101()
    _within_limits(model, start, "segment start")
    _within_limits(model, target, "segment target")
    minimum, path = math.inf, []
    for q in _sample_joint_segment(start, target):
        _within_limits(model, q, "segment")
        point = model.fk(q)[:3, 3]
        if not np.isfinite(point).all():
            raise ValueError("segment: nonfinite FK point")
        z = float(point[2])
        if z < min_tip_z_m:
            raise ValueError(f"segment: sampled TCP below table/required floor ({z * 1000:.3f} mm)")
        minimum = min(minimum, z)
        path.append(point.tolist())
    span = float(np.max(np.abs(np.degrees(target - start))))
    return {"minimum_tcp_z_m": minimum, "min_tip_z_m": float(min_tip_z_m),
            "max_joint_delta_deg": span, "joint_path_length_deg": span,
            "sampled_path_xyz_m": path, "sample_max_joint_step_deg": 1.0,
            "model_only": True}


def plan_taught_approach(teaching, home_joints, approach_joints, grasp_joints, joint_map=None):
    """Validate HOME -> taught LOWER -> existing approach -> existing grasp.

    Returns only descend/forward commands because the existing sequencer owns
    the final grasp command. That final leg is still checked before any command
    is returned. The caller must separately confirm arrival and grip state.
    The home seed must exactly match the recorded arm joints; recording does
    not silently replace the installation's existing HOME or vision settings.
    """
    teaching = copy.deepcopy(teaching)
    recorded = _recorded(teaching)
    joint_map = _validate_joint_map(joint_map)
    seed = _joints(home_joints, "home seed")
    if any(abs(seed[key] - recorded["home"][key]) > 1e-6 for key in ARM_KEYS):
        raise ValueError("home seed differs from recorded HOME")
    targets = {
        "home": recorded["home"], "descend": recorded["lower"],
        "forward": _joints(approach_joints, "vision approach"),
        "grasp": _joints(grasp_joints, "vision grasp"),
    }
    model = K.SO101()
    q = {name: K.from_lerobot(joints, joint_map) for name, joints in targets.items()}
    for name, angles in q.items():
        _within_limits(model, angles, name)
    minimum, spans, joint_lengths, sampled_path = {}, {}, {}, []
    previous = q["home"]
    for stage in ("descend", "forward", "grasp"):
        endpoint = q[stage]
        samples = _sample_joint_segment(previous, endpoint)
        minimum[stage] = math.inf
        spans[stage] = float(np.max(np.abs(np.degrees(endpoint - previous))))
        joint_lengths[stage] = spans[stage]  # One explicitly taught joint-linear segment.
        for angles in samples:
            _within_limits(model, angles, stage)
            point = model.fk(angles)[:3, 3]
            if not np.isfinite(point).all():
                raise ValueError(f"{stage}: nonfinite FK point")
            z = float(point[2])
            if z < 0:
                raise ValueError(f"{stage}: sampled TCP below table Z=0 ({z * 1000:.3f} mm)")
            minimum[stage] = min(minimum[stage], z)
            sampled_path.append(point.tolist())
        previous = endpoint
    return {
        "descend": [dict(targets["descend"])],
        "forward": [dict(targets["forward"])],
        "metadata": {
            "mode": "taught_waypoints", "interpolation": "joint_linear",
            "strict_vertical": False, "frame": "base_link", "tool_frame": "gripper_frame_link", "units": "m",
            "transit_floor_m": 0.0, "minimum_tip_z_m": 0.0, "table_z_m": 0.0,
            "clearance_exception_scope": "user_selected_taught_home_lower_and_vision_approach_only",
            "minimum_tcp_z_m": minimum, "max_joint_delta_deg": spans,
            "joint_path_length_deg": joint_lengths, "sample_max_joint_step_deg": 1.0,
            "path_xyz_m": [model.fk(q[name])[:3, 3].tolist() for name in ("home", "descend", "forward", "grasp")],
            "sampled_path_xyz_m": sampled_path,
            "home_xyz_m": model.fk(q["home"])[:3, 3].tolist(),
            "lower_xyz_m": model.fk(q["descend"])[:3, 3].tolist(),
            "target_xyz_m": model.fk(q["forward"])[:3, 3].tolist(),
            "teaching_sha256": teaching.get("_source_sha256"),
            "final_grasp_checked": True, "final_grasp_changed": False,
            "model_only": True, "hardware_motion_validated": False,
        },
    }
