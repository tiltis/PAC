"""Validate depth observations around the existing station grasp/IK controller.

No serial access or motor calls. Thresholds are software checks, not certification
of the real workspace, collision clearance, speed or emergency stop.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

import grasp
import kinematics as K


@dataclass(frozen=True)
class Limits:
    samples: int = 3
    max_age_s: float = 2.0
    max_shift_mm: float = 5.0
    max_rotation_deg: float = 10.0
    max_handeye_rms_mm: float = 10.0
    min_handeye_points: int = 4
    image_edge_margin_px: int = 8

    def __post_init__(self):
        if type(self.samples) is not int or self.samples < 2:
            raise ValueError("at least two independent observations required")
        values = (self.max_age_s, self.max_shift_mm, self.max_rotation_deg, self.max_handeye_rms_mm)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("limits must be finite and positive")
        if type(self.min_handeye_points) is not int or self.min_handeye_points < 4:
            raise ValueError("at least four calibration points required")
        if type(self.image_edge_margin_px) is not int or self.image_edge_margin_px < 1:
            raise ValueError("positive image edge margin required")


def _vector(value):
    a = np.asarray(value, dtype=float)
    if a.shape != (3,) or not np.isfinite(a).all():
        raise ValueError("expected a finite 3D vector")
    return a


def observation_error(loc, now, limits):
    if not isinstance(loc, dict) or loc.get("found") is not True:
        return (loc.get("reason") or "box_not_found") if isinstance(loc, dict) else "invalid_observation"
    if loc.get("frame") != "depth_camera_mm":
        return "unexpected_depth_frame_or_units"
    if loc.get("candidate_count") != 1:
        return "single_box_not_confirmed"
    stamp = loc.get("captured_at_s")
    if isinstance(stamp, bool) or not isinstance(stamp, (float, int)) or not math.isfinite(stamp):
        return "missing_capture_timestamp"
    if stamp > now + 0.1 or now - stamp > limits.max_age_s:
        return "depth_observation_stale_or_clock_mismatch"
    try:
        intr = loc.get("intrinsics", {})
        dims = np.asarray([intr.get("width"), intr.get("height")], dtype=float)
        bbox = np.asarray(loc.get("bbox_px"), dtype=float)
        if dims.shape != (2,) or not np.isfinite(dims).all() or np.any(dims <= 0) or bbox.shape != (4,) or not np.isfinite(bbox).all():
            return "depth_image_bounds_missing"
        x0, y0, x1, y1 = bbox
        width, height = dims
        m = limits.image_edge_margin_px
        if x0 < m or y0 < m or x1 > width - m or y1 > height - m:
            return "box_near_image_edge"
        if not (x0 < x1 and y0 < y1):
            return "invalid_depth_image_bounds"
        center = _vector(loc.get("top_center_cam_mm"))
        n = _vector(loc.get("table_normal_cam"))
        s = _vector(loc.get("short_axis_cam"))
        if center[2] <= 0 or np.linalg.norm(n) < 1e-6 or np.linalg.norm(s) < 1e-6:
            return "invalid_depth_geometry"
        if abs(np.dot(n, s) / (np.linalg.norm(n) * np.linalg.norm(s))) > 0.1:
            return "box_axis_not_on_table_plane"
        if loc.get("mode") != "front_face_model":
            size = np.asarray(loc.get("top_size_mm"), dtype=float)
            if size.shape != (2,) or not np.isfinite(size).all() or np.any(size <= 0):
                return "invalid_box_size"
        height = loc.get("top_height_mm")
        if height is not None and (isinstance(height, bool) or not isinstance(height, (float, int))
                                   or not math.isfinite(height) or height <= 0):
            return "invalid_box_height"
    except (ValueError, TypeError):
        return "invalid_depth_geometry"
    return None


def workspace_error(cfg):
    """Require a measured Cartesian target volume; no guessed physical default."""
    workspace = cfg.get("workspace")
    if not isinstance(workspace, dict):
        return "workspace_not_measured"
    if workspace.get("frame") != "base_link" or workspace.get("units") != "m":
        return "workspace_frame_or_units_invalid"
    try:
        lo, hi = _vector(workspace.get("min")), _vector(workspace.get("max"))
        if np.any(lo >= hi):
            return "workspace_bounds_invalid"
    except (ValueError, TypeError):
        return "workspace_bounds_invalid"
    return None


def calibration_error(he, limits):
    if he is None:
        return "handeye_calibration_missing"
    try:
        R = np.asarray(he["R"], dtype=float)
        _vector(he["t"])
        if R.shape != (3, 3) or not np.isfinite(R).all() or not np.allclose(R.T @ R, np.eye(3), atol=1e-5):
            return "handeye_rotation_invalid"
        if not np.isclose(np.linalg.det(R), 1, atol=1e-5):
            return "handeye_rotation_invalid"
        rms = he.get("rms_mm")
        n = he.get("n")
        if isinstance(rms, bool) or not isinstance(rms, (int, float)) or not math.isfinite(rms) or not 0 <= rms <= limits.max_handeye_rms_mm:
            return "handeye_residual_missing_or_excessive"
        if type(n) is not int or n < limits.min_handeye_points:
            return "handeye_not_enough_points"
    except (KeyError, TypeError, ValueError):
        return "handeye_calibration_invalid"
    return None


def change_error(before, after, limits):
    if before.get("box_mm") != after.get("box_mm"):
        return "box_model_changed"
    shift = float(np.linalg.norm(_vector(after["top_center_cam_mm"]) - _vector(before["top_center_cam_mm"])))
    if shift > limits.max_shift_mm:
        return "box_moved"
    a, b = _vector(before["short_axis_cam"]), _vector(after["short_axis_cam"])
    # Parallel gripper closing axes are symmetric under 180 degrees.
    angle = float(np.degrees(np.arccos(np.clip(abs(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b)), 0, 1))))
    if angle > limits.max_rotation_deg:
        return "box_rotated"
    a, b = _vector(before["table_normal_cam"]), _vector(after["table_normal_cam"])
    tilt = float(np.degrees(np.arccos(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))))
    if tilt > limits.max_rotation_deg:
        return "table_plane_changed"
    return None


class GuardedVisionPicker(grasp.VisionPicker):
    """Same locate()/plan() contract as station VisionPicker; reuse its IK planner."""

    def __init__(self, sensor, he, dry_run=False, cfg=None, joint_map=None, limits=None, clock=time.time):
        super().__init__(sensor, he, dry_run=dry_run, cfg=cfg, joint_map=joint_map)
        self.limits = limits or Limits()
        self.clock = clock

    def locate(self):
        first = last = None
        for _ in range(self.limits.samples):
            try:
                loc = self.sensor.locate()
            except Exception as e:
                return {"found": False, "reason": f"sensor_connection_failed: {type(e).__name__}"}
            err = observation_error(loc, self.clock(), self.limits)
            if err:
                return {"found": False, "reason": err}
            if last is not None:
                if loc["captured_at_s"] <= last["captured_at_s"]:
                    return {"found": False, "reason": "depth_frame_repeated"}
                err = change_error(first, loc, self.limits)
                if err:
                    return {"found": False, "reason": err}
            first = first or loc
            last = loc
        return dict(last, stability_samples=self.limits.samples)

    def plan(self, loc):
        err = (observation_error(loc, self.clock(), self.limits) or calibration_error(self.he, self.limits)
               or workspace_error(self.cfg))
        if err:
            return {"ok": False, "reason": err}
        if loc.get("stability_samples", 0) < self.limits.samples:
            return {"ok": False, "reason": "box_stability_not_confirmed"}
        try:
            result = super().plan(loc)
        except (KeyError, ValueError, TypeError, FloatingPointError) as e:
            return {"ok": False, "reason": f"invalid_grasp_input: {type(e).__name__}"}
        err = observation_error(loc, self.clock(), self.limits)
        if err:
            return {"ok": False, "reason": err}
        if result.get("ok"):
            workspace = self.cfg["workspace"]
            lo, hi = _vector(workspace["min"]), _vector(workspace["max"])
            for name in ("approach", "grasp", "lift"):
                point = self.robot.fk(K.from_lerobot(result[name], self.joint_map))[:3, 3]
                if not np.isfinite(point).all() or np.any(point < lo) or np.any(point > hi):
                    return {"ok": False, "reason": f"{name}_outside_measured_workspace"}
        # Even a successful IK solution is only a mathematical candidate.
        return dict(result, hardware_motion_verified=False)

    def verify_at_grasp(self, planned_loc):
        """New depth observations after approach; refuse moving targets, never chase."""
        current = self.locate()
        err = observation_error(current, self.clock(), self.limits)
        if not err:
            err = change_error(planned_loc, current, self.limits)
        return {"ok": err is None, "reason": err}
