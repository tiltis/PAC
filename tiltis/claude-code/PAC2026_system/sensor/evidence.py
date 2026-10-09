"""센서 관측값의 단위·시계·정합 한계를 명시한다. 결함 임계값은 만들지 않는다."""
import math

import numpy as np


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def build(vis, stack, meta, depth, prefix, timing_policy=None, registration=None):
    if vis.dtype != np.uint8 or vis.ndim != 3 or vis.shape[2] != 3:
        raise ValueError("RGB uint8 BGR 형식 오류")
    if stack.dtype != np.uint16 or stack.ndim != 3 or stack.shape[1:] != (256, 320) or stack.shape[0] < 2:
        raise ValueError("열화상은 최소 2개의 Y16 uint16 256x320 원시 프레임이 필요")
    vr = meta.get("vis", {})
    lr = meta.get("lwir", {})
    rgb_ts, first, last = vr.get("ts"), lr.get("ts_first"), lr.get("ts_last")
    timestamps_valid = all(_number(t) and t > 0 for t in (rgb_ts, first, last)) and first <= last
    timing = {"clock": "host_unix_seconds", "hardware_synchronized": False,
              "status": "unvalidated" if timestamps_valid else "missing",
              "rgb_lwir_skew_s": round(rgb_ts - (first + last) / 2, 6) if timestamps_valid else None,
              "lwir_reference": "acquisition_window_midpoint",
              "depth_rgb_skew_s": None, "reasons": []}
    if _number(depth.get("received_at_s")) and _number(rgb_ts):
        timing["depth_rgb_skew_s"] = round(depth["received_at_s"] - rgb_ts, 6)
    policy = timing_policy or {}
    if policy:
        if policy.get("validated") is not True or not isinstance(policy.get("source_id"), str) or not policy["source_id"].strip():
            raise ValueError("타이밍 policy에는 현장 검증 source_id와 validated=true가 필요")
        limits = {k: policy[k] for k in ("max_rgb_lwir_skew_s", "max_depth_rgb_skew_s") if k in policy}
        if not limits or any(not _number(v) or v < 0 for v in limits.values()):
            raise ValueError("타이밍 policy의 시간 차 허용값이 잘못됨")
        timing.update(policy_source_id=policy["source_id"], status="within_limit")
        for key, limit in limits.items():
            measurement = timing[key.removeprefix("max_")]
            if measurement is None:
                timing["reasons"].append("sensor_timestamp_missing")
            elif abs(measurement) > limit:
                timing["reasons"].append("sensor_time_skew")
        if timing["reasons"]:
            timing["status"] = "invalid"
    simulated = meta.get("software") == "fake-rig" or depth.get("simulated") is True
    data = {"schema_version": "pac-sensors-1", "simulated": simulated,
            "rgb": {"status": "valid", "unit": "uint8_intensity", "shape": list(vis.shape),
                    "received_at_s": rgb_ts, "image": prefix + "/vis.png"},
            "lwir": {"status": "valid", "unit": "raw_counts", "radiometric": False,
                     "target_temperature_c": None, "fpa_sensor_temperature_c": lr.get("fpa_temp_c"),
                     "shape": list(stack.shape), "received_first_s": first, "received_last_s": last,
                     "raw_min": int(stack.min()), "raw_max": int(stack.max()),
                     "raw_mean": round(float(stack.mean()), 4), "raw_file": prefix + "/lwir_y16.npz",
                     "preview": prefix + "/lwir_preview.png", "preview_is_relative_colormap": True,
                     "ffc_mode": lr.get("ffc_mode", "manual" if meta.get("ffc_manual") else "unknown"),
                     "ffc_completed_at_s": lr.get("ffc_ts")},
            "depth": depth, "timing": timing,
            "registration": registration or {"status": "missing", "rgb_lwir_aligned": False,
                                              "depth_rgb_aligned": False},
            "assessment": {"defect_rules_available": False, "defect_inspected": False,
                           "depth_role": "distance_observation_and_optional_measured_pose_gate",
                           "lid_height_defect_rule_available": False}}
    return data
