"""Factory RGB/depth projection for read-only SAM prompts, never motor input.

This does not turn factory parameters or host arrival times into field-validated
registration/exposure timing. The strict sam_depth control adapter stays closed.
"""
from __future__ import annotations

import numpy as np

from sam_depth import _intrinsics, sensor_module


def top_preview(bundle, models_mm, near_far=(200, 700), pick_roi=None, table_roi=None):
    mm, rgb = bundle["depth_mm"], bundle["rgb_bgr"]
    meta = bundle["metadata"]
    reg = meta["registration"]
    if reg.get("validation_basis") != "device_factory" or not reg.get("source_id", "").startswith("orbbec-factory:"):
        raise ValueError("explicit factory camera calibration required for preview")
    if reg.get("units") != "mm" or reg.get("from_frame") != "depth_camera_mm" or reg.get("to_frame") != "rgb_camera_mm":
        raise ValueError("invalid factory frame/units")
    if reg.get("rgb_rectified") is not True or reg.get("depth_rectified") is not True:
        raise ValueError("rectified preview required")
    di = meta["depth_intrinsics"]
    ri = _intrinsics(meta["rgb_intrinsics"], rgb.shape[:2])
    _intrinsics(di, mm.shape)
    R, t = np.asarray(reg["R"], float), np.asarray(reg["t_mm"], float)
    if R.shape != (3, 3) or t.shape != (3,) or not np.isfinite([*R.ravel(), *t]).all():
        raise ValueError("invalid factory extrinsics")
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(R), 1):
        raise ValueError("invalid factory rotation")
    loc = sensor_module().locate_box_top_any(mm, di, models_mm, near_far=near_far,
                                           pick_roi=pick_roi, table_roi=table_roi)
    loc.pop("_internal", None)
    result = {"motion_enabled": False, "robot_ready": False, "preview_only": True,
              "registration_field_checked": reg.get("field_reprojection_checked") is True,
              "capture_time_verified": all(c.get("capture_time_verified") is True for c in meta["captures"].values()),
              "location": loc}
    if not loc.get("found"):
        return result
    c = np.asarray(loc["top_center_cam_mm"])
    a, b = np.asarray(loc["long_axis_cam"]), np.asarray(loc["short_axis_cam"])
    L, S = np.asarray(loc["top_size_mm"]) / 2
    corners = np.array([c + x * L * a + y * S * b for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    Q = corners @ R.T + t
    if np.any(Q[:, 2] <= 0):
        raise ValueError("projected top behind RGB camera")
    quad = np.column_stack((Q[:, 0] * ri[0] / Q[:, 2] + ri[2], Q[:, 1] * ri[1] / Q[:, 2] + ri[3]))
    if np.any(quad < 0) or np.any(quad[:, 0] >= rgb.shape[1]) or np.any(quad[:, 1] >= rgb.shape[0]):
        raise ValueError("top not fully visible in Gemini RGB")
    result["projected_top_quad_rgb_px"] = quad.round(3).tolist()
    return result
