"""선택 뎁스 취득과 거리 기록. 기본 실행은 카메라를 열거나 설정하지 않는다.

Orbbec SDK 2.1.2의 DepthFrame.get_depth_scale()을 mm/raw-count로 사용한다.
자체 RGB 정렬과 Arducam RGB 정렬은 서로 다르다. 여기서는 깊이 픽셀 좌표만 쓴다.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class DepthFrame:
    raw: np.ndarray
    scale_mm: float
    received_at_s: float
    device_timestamp_ms: float | None = None
    source: str = "orbbec"
    simulated: bool = False
    device_clock_epoch: int = 0
    frame_index: int | None = None  # SDK 프레임 번호. 순서 판단에 우선 사용

    def validate(self):
        if not isinstance(self.raw, np.ndarray) or self.raw.dtype != np.uint16 or self.raw.ndim != 2 or not self.raw.size:
            raise ValueError("depth는 비어 있지 않은 uint16 2D 배열이어야 함")
        if not math.isfinite(self.scale_mm) or self.scale_mm <= 0:
            raise ValueError("depth scale_mm은 유한한 양수여야 함")
        if not math.isfinite(self.received_at_s) or self.received_at_s <= 0:
            raise ValueError("depth host timestamp 누락/잘못됨")
        if self.device_timestamp_ms is not None and (
                not math.isfinite(self.device_timestamp_ms) or self.device_timestamp_ms < 0):
            raise ValueError("depth device timestamp 잘못됨")


def from_sdk_frame(frame, received_at_s=None):
    # uint16 버퍼가 아닌 압축 프레임을 길이/형식 확인 없이 해석하지 않는다.
    if str(frame.get_format()).split(".")[-1] != "Y16":
        raise ValueError("Orbbec depth Y16 프레임이 아님")
    w, h = frame.get_width(), frame.get_height()
    raw = np.frombuffer(frame.get_data(), dtype=np.uint16)
    if w <= 0 or h <= 0 or raw.size != w * h:
        raise ValueError("Orbbec depth 버퍼 크기 불일치")
    # Gemini 2(펌웨어 1.4.92, Windows)는 장치 시각이 모든 프레임에서 같은 값으로 고정된다(2026-10-06 실측).
    # 프레임 번호는 1씩 증가하므로 순서 판단은 번호로 한다. 장치 시각은 기록만 한다.
    index = frame.get_index() if hasattr(frame, "get_index") else None
    result = DepthFrame(raw.reshape(h, w).copy(), float(frame.get_depth_scale()),
                        time.time() if received_at_s is None else received_at_s,
                        float(frame.get_timestamp()), frame_index=None if index is None else int(index))
    result.validate()
    return result


def load_depth_capture(path):
    """저장 재생. 획득 시각을 현재 시각으로 바꾸거나 실장비 입력으로 꾸미지 않는다."""
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))["depth"]
    with np.load(path / "depth_raw.npz") as archive:
        raw = archive["raw"]
    frame = DepthFrame(raw, meta["scale_mm_per_unit"], meta["received_at_s"],
                       meta.get("device_timestamp_ms"), "saved-replay", True, meta.get("device_clock_epoch", 0))
    frame.validate()
    return frame


def summarize(frame, now_s, max_age_s=2.0, policy=None):
    """거리값 기록. 면별 실측 policy가 있을 때만 자세 허용범위를 적용한다."""
    frame.validate()
    if not math.isfinite(now_s) or not math.isfinite(max_age_s) or max_age_s <= 0:
        raise ValueError("depth freshness 설정 잘못됨")
    policy = policy or {}
    raw = frame.raw
    roi = policy.get("roi_xyxy")
    if roi is not None:
        if not isinstance(roi, list) or len(roi) != 4 or not all(type(x) is int for x in roi):
            raise ValueError("depth ROI는 깊이 픽셀 좌표 [x0,y0,x1,y1]")
        x0, y0, x1, y1 = roi
        if not (0 <= x0 < x1 <= raw.shape[1] and 0 <= y0 < y1 <= raw.shape[0]):
            raise ValueError("depth ROI가 프레임 범위를 벗어남")
        raw = raw[y0:y1, x0:x1]
    valid = raw > 0  # SDK의 무효값 0을 거리 통계에서 제외. 표시 범위를 측정 범위로 만들지 않는다.
    values = raw[valid].astype(np.float64) * frame.scale_mm
    if values.size and not np.isfinite(values).all():
        raise ValueError("depth mm 변환값이 유한하지 않음")
    age = now_s - frame.received_at_s
    status = "valid"
    reasons = []
    if age < 0:
        status, reasons = "invalid", ["depth_clock_mismatch"]
    elif age > max_age_s:
        status, reasons = "stale", ["depth_stale"]
    elif not values.size:
        status, reasons = "invalid", ["depth_invalid"]
    result = {"enabled": True, "status": status, "unit": "mm", "raw_unit": "device_counts",
              "coordinate_frame": "depth_pixels_unaligned_to_rgb", "source": frame.source,
              "simulated": frame.simulated, "shape": list(frame.raw.shape),
              "scale_mm_per_unit": frame.scale_mm, "received_at_s": frame.received_at_s,
              "device_timestamp_ms": frame.device_timestamp_ms, "device_clock_epoch": frame.device_clock_epoch,
              "frame_index": frame.frame_index,
              "order_key": "frame_index" if frame.frame_index is not None else "device_timestamp",
              "timestamp_clock": "host_unix_seconds", "device_clock": "device_milliseconds",
              "age_s": round(age, 6), "roi_xyxy": roi, "roi_pixels": int(raw.size),
              "measurement_region": "configured_depth_roi" if roi is not None else "whole_depth_frame",
              "valid_fraction": round(float(valid.mean()), 6),
              "median_mm": round(float(np.median(values)), 3) if values.size else None,
              "min_mm": round(float(values.min()), 3) if values.size else None,
              "max_mm": round(float(values.max()), 3) if values.size else None,
              "pose_gate": "not_configured", "reasons": reasons}
    if policy:
        if policy.get("validated") is not True or not isinstance(policy.get("source_id"), str) or not policy["source_id"].strip():
            result["pose_gate"] = "unvalidated"
        else:
            bounds = policy.get("distance_mm")
            fraction = policy.get("min_valid_fraction")
            if roi is None or not isinstance(bounds, list) or len(bounds) != 2 or not all(
                    type(v) in (int, float) and math.isfinite(v) for v in bounds) or not (0 < bounds[0] < bounds[1]):
                raise ValueError("검증된 depth policy에는 ROI와 실측 distance_mm 하한/상한이 필요")
            if type(fraction) not in (int, float) or not math.isfinite(fraction) or not 0 < fraction <= 1:
                raise ValueError("검증된 depth policy에는 실측 min_valid_fraction이 필요")
            result.update(policy_source_id=policy["source_id"], pose_gate="unavailable")
            if status == "valid":
                if result["valid_fraction"] < fraction:
                    result.update(status="invalid", reasons=["depth_insufficient_valid_pixels"])
                else:
                    inside = bounds[0] <= result["median_mm"] <= bounds[1]
                    result["pose_gate"] = "within_range" if inside else "out_of_range"
                    if not inside:
                        result["reasons"] = ["pose_out_of_range"]
    return result


class OrbbecDepthSource:
    """--depth에서만 시작하는 독립 취득기. 레이저·노출·보정·펌웨어 설정을 쓰지 않는다."""
    def __init__(self, timeout_s=3.0, sdk=None):
        self.timeout_s = timeout_s
        self._sdk = sdk
        self._pipeline = None
        self.device_info = {}
        self._started = False
        self._frame = None
        self._error = None
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread = None
        self._last_device_timestamp_ms = None
        self._reset_candidate_ms = None
        self._reset_progress_count = 0
        self._device_clock_epoch = 0
        self.intrinsics = None

    def start(self):
        if self._sdk is None:
            if sys.platform == "win32":
                # Orbbec SDK가 먼저 COM을 다른 방식으로 초기화하면 나중에 카메라 이름 조회(comtypes)가
                # "스레드 모드가 설정된 후에는 바꿀 수 없습니다"로 실패한다. comtypes를 먼저 초기화한다.
                import comtypes  # noqa: F401
            import pyorbbecsdk
            self._sdk = pyorbbecsdk
        sdk = self._sdk
        # Context를 붙잡아 두지 않으면 바로 해제돼 장치 목록이 깨진다("NULL pointer ... deviceMgr")
        self._context = sdk.Context()
        devices = self._context.query_devices()
        if devices.get_count() != 1:
            raise RuntimeError("뎁스 자동 연결에는 Orbbec 장치가 정확히 1대 필요(다른 장치를 임의 선택하지 않음)")
        device = devices.get_device_by_index(0)
        info = device.get_device_info()
        if "gemini2" not in info.get_name().lower().replace(" ", ""):
            raise RuntimeError("선택된 뎁스 장치가 PAC의 Gemini 2가 아님")
        try:  # USB3 여부. 연장선·무전원 허브를 거치면 USB2로 떨어질 수 있다
            connection = str(info.get_connection_type())
        except Exception:
            connection = None
        self.device_info = {"name": info.get_name(), "serial_number": info.get_serial_number(), "connection": connection,
                            "firmware": info.get_firmware_version()}
        self._pipeline = sdk.Pipeline(device)
        profiles = self._pipeline.get_stream_profile_list(sdk.OBSensorType.DEPTH_SENSOR)
        # SDK가 디코딩한 Y16만 요청. 호환 프로파일이 없으면 오류이며 추측하지 않는다.
        profile = profiles.get_video_stream_profile(0, 0, sdk.OBFormat.Y16, 0)
        self.intrinsics = None  # 상자 3D 위치 계산용(fx, fy, cx, cy). 못 읽으면 None
        try:
            i = profile.as_video_stream_profile().get_intrinsic()
            self.intrinsics = {k: float(getattr(i, k)) for k in ("fx", "fy", "cx", "cy", "width", "height")}
        except Exception:
            pass
        config = sdk.Config()
        config.enable_stream(profile)
        self._pipeline.start(config)
        self._started = True
        self._thread = threading.Thread(target=self._receive, daemon=True)
        self._thread.start()

    def _receive(self):
        while not self._stop.is_set():
            try:
                frames = self._pipeline.wait_for_frames(100)
                if frames is None:
                    continue
                frame = frames.get_depth_frame()
                if frame is None:
                    continue
                observation = from_sdk_frame(frame)
                # 순서 키: 프레임 번호가 있으면 번호, 없으면 장치 시각(변수 이름은 기존 그대로)
                stamp = observation.frame_index if observation.frame_index is not None else observation.device_timestamp_ms
                if self._last_device_timestamp_ms is not None and stamp <= self._last_device_timestamp_ms:
                    # Quarantine all reset candidates; three increasing lower timestamps establish
                    # a new device clock epoch. Duplicates/out-of-order frames cannot reset it.
                    progressing = (stamp < self._last_device_timestamp_ms and
                                   (self._reset_candidate_ms is None or stamp > self._reset_candidate_ms))
                    self._reset_progress_count = self._reset_progress_count + 1 if progressing else 0
                    self._reset_candidate_ms = stamp if stamp < self._last_device_timestamp_ms else None
                    with self._condition:
                        self._frame = None
                    if self._reset_progress_count >= 3:
                        self._last_device_timestamp_ms = stamp
                        self._device_clock_epoch += 1
                        self._reset_candidate_ms = None
                        self._reset_progress_count = 0
                    raise ValueError("depth device timestamp reset/repeated frame quarantined")
                self._last_device_timestamp_ms = stamp
                self._reset_candidate_ms = None
                self._reset_progress_count = 0
                observation.device_clock_epoch = self._device_clock_epoch
                with self._condition:
                    self._frame, self._error = observation, None
                    self._condition.notify_all()
            except Exception as e:
                with self._condition:
                    self._error = f"{type(e).__name__}: {e}"
                    self._condition.notify_all()
                self._stop.wait(0.05)

    def next_after(self, requested_at_s):
        deadline = time.monotonic() + self.timeout_s
        with self._condition:
            while True:
                if not self._error and self._frame and self._frame.received_at_s > requested_at_s:
                    return self._frame
                left = deadline - time.monotonic()
                if left <= 0 or self._stop.is_set():
                    if self._error:
                        raise RuntimeError(self._error)
                    raise TimeoutError("depth 새 프레임 수신 시간 초과")
                self._condition.wait(left)

    def latest(self):
        """미리보기용 최신 프레임(없으면 None). 촬영 기록에는 next_after()를 쓴다."""
        with self._condition:
            return None if self._error else self._frame

    def health(self, max_age_s=2.0):
        with self._condition:
            return bool(self._frame and not self._error and 0 <= time.time() - self._frame.received_at_s <= max_age_s)

    def close(self):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread:
            self._thread.join(2)
        if self._pipeline and self._started:
            self._pipeline.stop()  # 이 객체가 시작한 depth 파이프라인만 종료한다.
            self._started = False
