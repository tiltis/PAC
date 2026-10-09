"""Gemini's own color/depth pair, without claiming Arducam registration.

Factory calibration is exported with its provenance and no invented RMS.
Native depth remains unchanged for the existing locator/hand-eye transform.
"""
from __future__ import annotations

import time

import cv2
import numpy as np


def intrinsic(profile):
    i = profile.get_intrinsic()
    return {k: float(getattr(i, k)) for k in ("fx", "fy", "cx", "cy", "width", "height")}


def rectification(profile):
    i = intrinsic(profile)
    d = profile.get_distortion()
    coefficients = [float(getattr(d, k)) for k in ("k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6")]
    if not np.isfinite(coefficients).all():
        raise ValueError("nonfinite factory distortion")
    model = str(d.model).split(".")[-1]
    if model not in ("NONE", "BROWN_CONRADY", "BROWN_CONRADY_K6"):
        raise ValueError(f"unsupported factory distortion model: {model}")
    if model == "NONE" and np.any(coefficients):
        raise ValueError("nonzero coefficients with no distortion model")
    K = np.array([[i["fx"], 0, i["cx"]], [0, i["fy"], i["cy"]], [0, 0, 1.]])
    size = (int(i["width"]), int(i["height"]))
    return i, cv2.initUndistortRectifyMap(K, np.asarray(coefficients), np.eye(3), K, size, cv2.CV_32FC1), coefficients


def color_image(frame):
    w, h = frame.get_width(), frame.get_height()
    data = np.frombuffer(frame.get_data(), dtype=np.uint8)
    fmt = str(frame.get_format()).split(".")[-1]
    if fmt == "MJPG":
        out = cv2.imdecode(data, cv2.IMREAD_COLOR)
    elif fmt in ("RGB", "RGB888", "BGR", "BGR888"):
        out = data.reshape(h, w, 3).copy()
        if fmt.startswith("RGB"):
            out = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    elif fmt == "YUYV":
        out = cv2.cvtColor(data.reshape(h, w, 2), cv2.COLOR_YUV2BGR_YUYV)
    else:
        raise ValueError(f"unsupported Gemini color format: {fmt}")
    if out is None or out.shape != (h, w, 3):
        raise ValueError("invalid Gemini color buffer")
    return out


class NativeRgbd:
    def __init__(self, sdk, pipeline, config, depth_profile, device_info):
        colors = pipeline.get_stream_profile_list(sdk.OBSensorType.COLOR_SENSOR)
        profile = colors.get_default_video_stream_profile().as_video_stream_profile()
        config.enable_stream(profile)
        pipeline.enable_frame_sync()
        self.depth_intrinsics, self.depth_maps, dd = rectification(depth_profile.as_video_stream_profile())
        self.rgb_intrinsics, self.rgb_maps, rd = rectification(profile)
        ext = depth_profile.get_extrinsic_to(profile)
        R = np.asarray(ext.rot, float).reshape(3, 3)
        # pyorbbecsdk 2.1.2 exposes the mm translation as `transform`.
        t = np.asarray(ext.transform, float).reshape(3)
        if not np.isfinite(t).all() or not np.allclose(R.T @ R, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(R), 1):
            raise ValueError("invalid Gemini factory extrinsic")
        serial = device_info["serial_number"]
        self.registration = {
            "source_id": f"orbbec-factory:{serial}", "validation_basis": "device_factory",
            "validated": False, "field_reprojection_checked": False, "rms_px": None,
            "from_frame": "depth_camera_mm", "to_frame": "rgb_camera_mm", "units": "mm",
            "R": R.tolist(), "t_mm": t.tolist(),
            "rgb_camera_id": f"{serial}:color", "depth_camera_id": f"{serial}:depth",
            "rgb_intrinsics": self.rgb_intrinsics, "depth_intrinsics": self.depth_intrinsics,
            "rgb_rectified": True, "depth_rectified": True,
            "rgb_distortion": rd, "depth_distortion": dd,
            "note": "Factory parameters; field reprojection RMS has not been measured. Arducam is separate."
        }
        self.latest = None
        self.error = None
        self.last_timing = None
        self.observation = None
        self._last_device_clocks = None
        self._clock_progress = 0

    def receive(self, frames, depth_observation):
        color = frames.get_color_frame()
        if color is None:
            self.latest = None
            self.observation = None
            self._clock_progress = 0
            self._last_device_clocks = None
            self.error = "paired color missing"
            return
        now = time.time()
        depth = frames.get_depth_frame()
        dc = float(depth.get_system_timestamp()) / 1000.
        rc = float(color.get_system_timestamp()) / 1000.
        self.last_timing = {"depth_sdk_host_s": dc, "rgb_sdk_host_s": rc,
                            "received_at_s": now, "skew_ms": round(abs(dc - rc) * 1000, 3)}
        if not np.isfinite([dc, rc]).all() or min(now - dc, now - rc) < -.1 or max(now - dc, now - rc) > 2:
            self.latest = None
            self.observation = None
            self.error = "SDK host receive clocks unavailable or stale"
            return
        # System timestamps are host ARRIVAL times, not exposure times. Only
        # progressive device timestamps mapped by the SDK to the host clock
        # can certify a capture pair (Gemini on Windows needs UVC metadata).
        clocks = [float(getattr(f, "get_timestamp_us", lambda: 0)()) for f in (depth, color)]
        progressing = (min(clocks) > 0 and self._last_device_clocks is not None and
                       all(a > b for a, b in zip(clocks, self._last_device_clocks)))
        self._clock_progress = self._clock_progress + 1 if progressing else 0
        self._last_device_clocks = clocks
        captures = [float(getattr(f, "get_global_timestamp_us", lambda: 0)()) / 1e6 for f in (depth, color)]
        verified = (self._clock_progress >= 3 and np.isfinite(captures).all() and
                    min(captures) > 0 and min(now - v for v in captures) >= 0 and
                    max(now - v for v in captures) <= 2 and abs(captures[0] - captures[1]) <= .1)
        self.last_timing.update(device_timestamp_us=clocks, global_timestamp_s=captures,
                                capture_time_verified=bool(verified))
        rgb = cv2.remap(color_image(color), *self.rgb_maps, cv2.INTER_LINEAR)
        mm = cv2.remap(depth_observation.raw.astype(np.float32) * depth_observation.scale_mm,
                       *self.depth_maps, cv2.INTER_NEAREST)
        self.observation = {
            "rgb_bgr": rgb, "depth_mm": mm,
            "metadata": {"registration": self.registration, "rgb_intrinsics": self.rgb_intrinsics,
                         "depth_intrinsics": self.depth_intrinsics,
                         "captures": {kind: {"captured_at_s": capture if verified else None,
                                              "received_at_s": stamp, "clock": "host_unix_seconds",
                                              "timestamp_basis": "sdk_global_exposure" if verified else "sdk_host_arrival_only",
                                              "capture_time_verified": bool(verified),
                                              "camera_id": self.registration[f"{kind}_camera_id"]}
                                      for kind, stamp, capture in (("rgb", rc, captures[1]), ("depth", dc, captures[0]))},
                         "received_at_s": now, "depth_frame_index": depth_observation.frame_index,
                         "rgb_frame_index": int(color.get_index()), "hardware_motion_verified": False,
                         "motion_enabled": False, "hardware_synchronized": False}
        }
        self.latest = self.observation if verified else None
        self.error = None if verified else "device capture synchronization unverified; preview only"
