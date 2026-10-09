"""Verified RGB SAM mask -> native depth top plane -> existing station locate contract.

The current live preview lacks the required calibration/capture metadata. This
adapter rejects it; it never guesses a pixel match or opens hardware.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np


def sensor_module():
    root = Path(os.environ.get("PAC_SYSTEM_DIR") or
                Path(__file__).resolve().parents[2] / "claude-code/PAC2026_system")
    sensor = root / "sensor"
    if not (sensor / "locate.py").is_file():
        raise ValueError("existing sensor/locate.py missing")
    sys.path.insert(0, str(sensor))
    import locate
    return locate


def _intrinsics(intr, shape):
    values = np.asarray([intr[k] for k in ("fx", "fy", "cx", "cy", "width", "height")], float)
    if not np.isfinite(values).all() or np.any(values[:2] <= 0) or tuple(values[4:][::-1]) != tuple(shape):
        raise ValueError("intrinsics do not match rectified image resolution")
    return values


def project_sam_mask(mask, mm, depth_intr, rgb_intr, registration):
    """Depth points projected into rectified RGB, with nearest-depth occlusion check."""
    mask, mm = np.asarray(mask), np.asarray(mm)
    if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any() or mm.ndim != 2 or not mm.size:
        raise ValueError("nonempty boolean RGB mask and depth mm image required")
    source_id = registration.get("source_id")
    if registration.get("validated") is not True or not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("RGB-depth registration not validated")
    if (registration.get("from_frame"), registration.get("to_frame"), registration.get("units")) != (
            "depth_camera_mm", "rgb_camera_mm", "mm"):
        raise ValueError("registration frame or units invalid")
    if registration.get("rgb_rectified") is not True or registration.get("depth_rectified") is not True:
        raise ValueError("rectified images not confirmed")
    error = registration.get("rms_px")
    if type(error) not in (int, float) or not np.isfinite(error) or not 0 <= error <= 2:
        raise ValueError("registration reprojection residual missing or excessive")
    di, ri = _intrinsics(depth_intr, mm.shape), _intrinsics(rgb_intr, mask.shape)
    if not np.allclose(di, _intrinsics(registration["depth_intrinsics"], mm.shape), atol=1e-6, rtol=0):
        raise ValueError("depth intrinsics changed since registration")
    if not np.allclose(ri, _intrinsics(registration["rgb_intrinsics"], mask.shape), atol=1e-6, rtol=0):
        raise ValueError("RGB intrinsics changed since registration")
    R, t = np.asarray(registration["R"], float), np.asarray(registration["t_mm"], float)
    if R.shape != (3, 3) or not np.isfinite(R).all() or not np.allclose(R.T @ R, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(R), 1):
        raise ValueError("registration rotation invalid")
    if t.shape != (3,) or not np.isfinite(t).all():
        raise ValueError("registration translation invalid")
    mm = np.where(np.isfinite(mm) & (mm > 0), mm, 0).astype(float)
    P = sensor_module().deproject(mm, depth_intr)
    Q = P @ R.T + t
    valid = (mm > 0) & (Q[..., 2] > 0)
    v, u = np.where(valid)
    q = Q[v, u]
    projected = np.column_stack((q[:, 0] * ri[0] / q[:, 2] + ri[2], q[:, 1] * ri[1] / q[:, 2] + ri[3]))
    inside = (projected[:, 0] >= 0) & (projected[:, 0] < mask.shape[1] - .5) & (projected[:, 1] >= 0) & (projected[:, 1] < mask.shape[0] - .5)
    v, u, q = v[inside], u[inside], q[inside]
    xy = np.rint(projected[inside]).astype(int)
    ids = xy[:, 1] * mask.shape[1] + xy[:, 0]
    z_buffer = np.full(mask.size, np.inf)
    np.minimum.at(z_buffer, ids, q[:, 2])
    accepted = mask[xy[:, 1], xy[:, 0]] & (q[:, 2] <= z_buffer[ids] + 4)
    selected = np.zeros(mm.shape, bool)
    selected[v[accepted], u[accepted]] = True
    if selected.sum() < 100:
        raise ValueError("SAM mask has insufficient associated depth")
    return selected


def locate_sam_top(mask, mm, depth_intr, rgb_intr, registration, captures, now_s, *, box_count,
                   table_roi, box_models_mm, max_age_s=2.0, max_skew_s=.1, size_tol_mm=10):
    """No motor calls. Return (station-compatible observation, native-depth top mask)."""
    empty = np.zeros(np.asarray(mm).shape, bool)
    try:
        if type(box_count) is not int or box_count != 1:
            raise ValueError("single RGB box not confirmed")
        if not np.isfinite([now_s, max_age_s, max_skew_s]).all() or min(max_age_s, max_skew_s) <= 0:
            raise ValueError("invalid capture timing limits")
        stamps = []
        for kind in ("rgb", "depth"):
            cap = captures[kind]
            if cap.get("capture_time_verified") is not True or cap.get("clock") != "host_unix_seconds":
                raise ValueError("capture timestamps not verified on a common clock")
            if not registration.get(f"{kind}_camera_id") or cap.get("camera_id") != registration[f"{kind}_camera_id"]:
                raise ValueError("camera changed since registration")
            stamp = cap.get("captured_at_s")
            if type(stamp) not in (int, float) or not np.isfinite(stamp) or not 0 <= now_s - stamp <= max_age_s:
                raise ValueError("RGB or depth capture stale or clock mismatch")
            stamps.append(stamp)
        if abs(stamps[0] - stamps[1]) > max_skew_s:
            raise ValueError("RGB-depth capture skew excessive")
        if table_roi is None:
            raise ValueError("measured table ROI required")
        models = np.asarray(box_models_mm, float)
        if models.ndim != 2 or models.shape[1] != 3 or not len(models) or not np.isfinite(models).all() or (models <= 0).any():
            raise ValueError("measured box dimensions [long, short, height] mm required")
        if not np.isfinite(size_tol_mm) or size_tol_mm <= 0:
            raise ValueError("invalid measured box dimension tolerance")
        associated = project_sam_mask(mask, mm, depth_intr, rgb_intr, registration)
        locator = sensor_module()
        loc = locator.locate_box(mm, depth_intr, table_roi=table_roi, object_mask=associated)
        if not loc.get("found"):
            return dict(loc, motion_enabled=False, robot_ready=False), empty
        internal = loc.pop("_internal")
        measured = np.array([*loc["top_size_mm"], loc["top_height_mm"]])
        matches = models[(np.abs(models - measured) <= size_tol_mm).all(axis=1)]
        if len(matches) != 1:
            raise ValueError("visible top does not uniquely match measured box dimensions")
        top = internal["mask"] & (np.abs(internal["h"] - loc["top_height_mm"]) < 8)
        points = internal["P"][top]
        if len(points) < 100:
            raise ValueError("insufficient visible top plane")
        # Reuse the existing RANSAC/SVD fit. A vertical tape/front face cannot
        # pass the top-plane normal test even if SAM reports a high IoU score.
        n, d, _ = locator.fit_plane(points, np.random.default_rng(0), iters=100, tol=4)
        if n @ internal["n"] < 0:
            n, d = -n, -d
        residual = np.abs(points @ n + d)
        tilt = float(np.degrees(np.arccos(np.clip(n @ internal["n"], -1, 1))))
        if tilt > 10 or np.mean(residual <= 4) < .85 or float(np.sqrt(np.mean(residual ** 2))) > 4:
            raise ValueError("top plane not flat and parallel to table")
        # Refuse a largely missing face: a narrow visible strip is not a full
        # measured footprint and cannot establish the grasp center safely.
        if loc.get("far_edge_invalid_frac") is not None and loc["far_edge_invalid_frac"] > .2:
            raise ValueError("top far edge lacks depth")
        return dict(loc, mode="sam_depth_top", intrinsics=depth_intr, captured_at_s=min(stamps),
                    box_mm=matches[0].tolist(),
                    rgb_captured_at_s=stamps[0], depth_captured_at_s=stamps[1],
                    registration_source_id=registration["source_id"],
                    top_normal_cam=n.round(6).tolist(), top_plane_tilt_deg=round(tilt, 3),
                    top_plane_rms_mm=round(float(np.sqrt(np.mean(residual ** 2))), 3),
                    orientation_source="sam_mask_registered_depth_top_plane",
                    motion_enabled=False, robot_ready=False), top
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError) as e:
        return {"found": False, "reason": str(e), "motion_enabled": False, "robot_ready": False}, empty


class SamDepthSensorAdapter:
    """Reuse station inspect API; caller must supply verified, fresh paired frames."""
    def __init__(self, inspection_sensor, paired_frame_reader, registration, table_roi, box_models_mm, clock):
        self.inspection_sensor, self.reader = inspection_sensor, paired_frame_reader
        self.registration, self.table_roi, self.clock = registration, table_roi, clock
        self.box_models_mm = box_models_mm

    def locate(self):
        b = self.reader()
        result = locate_sam_top(b["sam_mask"], b["depth_mm"], b["depth_intrinsics"], b["rgb_intrinsics"],
                                self.registration, b["captures"], self.clock(), box_count=b["box_count"],
                                table_roi=self.table_roi, box_models_mm=self.box_models_mm)[0]
        if result.get("found") and not 0 <= self.clock() - result["captured_at_s"] <= 2:
            return {"found": False, "reason": "capture became stale during top-plane processing",
                    "motion_enabled": False, "robot_ready": False}
        return result

    def inspect(self, *args, **kwargs):
        return self.inspection_sensor.inspect(*args, **kwargs)

    def close(self):
        return self.inspection_sensor.close()
