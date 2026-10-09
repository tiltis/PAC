import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from depth import DepthFrame, OrbbecDepthSource, from_sdk_frame, load_depth_capture, summarize


class SDKFrame:
    def __init__(self, timestamp=1234, scale=0.1, data=None, format="Y16"):
        self.raw = np.array([[0, 1000], [2000, 3000]], np.uint16)
        self.timestamp, self.scale, self.format = timestamp, scale, format
        self.data = self.raw.tobytes() if data is None else data
    def get_width(self): return 2
    def get_height(self): return 2
    def get_data(self): return self.data
    def get_format(self): return self.format
    def get_depth_scale(self): return self.scale
    def get_timestamp(self): return self.timestamp


def test_sdk_units_and_clock_domains_are_not_confused():
    observation = from_sdk_frame(SDKFrame(), received_at_s=1700000000.0)
    result = summarize(observation, 1700000000.1)
    assert result["unit"] == "mm" and result["median_mm"] == 200.0
    assert result["valid_fraction"] == 0.75 and result["device_timestamp_ms"] == 1234
    assert result["status"] == "valid" and result["age_s"] == 0.1
    assert result["coordinate_frame"] == "depth_pixels_unaligned_to_rgb"


@pytest.mark.parametrize("kwargs", [{"format": "MJPG"}, {"data": b"00"}, {"scale": 0},
    {"scale": float("nan")}, {"timestamp": -1}])
def test_invalid_sdk_frame_is_rejected(kwargs):
    with pytest.raises(ValueError): from_sdk_frame(SDKFrame(**kwargs), 1700000000.0)


@pytest.mark.parametrize("raw, received, expected", [
    (np.zeros((2, 2), np.uint16), 100.0, "invalid"),
    (np.ones((2, 2), np.uint16), 90.0, "stale"),
    (np.ones((2, 2), np.uint16), 101.0, "invalid"),
])
def test_missing_values_old_frames_and_future_clock(raw, received, expected):
    assert summarize(DepthFrame(raw, 1, received), 100.0)["status"] == expected


def test_only_explicit_measured_depth_policy_can_gate_pose():
    frame = DepthFrame(np.full((4, 4), 500, np.uint16), 1, 100)
    policy = {"validated": True, "source_id": "synthetic-test-only", "roi_xyxy": [1, 1, 3, 3],
              "distance_mm": [450, 550], "min_valid_fraction": 0.9}
    result = summarize(frame, 100.1, policy=policy)
    assert result["pose_gate"] == "within_range" and result["roi_pixels"] == 4
    result = summarize(frame, 100.1, policy={**policy, "distance_mm": [600, 700]})
    assert result["pose_gate"] == "out_of_range" and result["reasons"] == ["pose_out_of_range"]
    result = summarize(frame, 100.1, policy={**policy, "validated": False})
    assert result["pose_gate"] == "unvalidated" and result["reasons"] == []


@pytest.mark.parametrize("update", [{"roi_xyxy": [0, 0, 99, 99]}, {"distance_mm": [550, 450]},
    {"min_valid_fraction": 0}, {"roi_xyxy": None}])
def test_bad_depth_policy_is_not_silently_applied(update):
    policy = {"validated": True, "source_id": "test", "roi_xyxy": [0, 0, 2, 2],
              "distance_mm": [400, 600], "min_valid_fraction": 0.9, **update}
    with pytest.raises(ValueError):
        summarize(DepthFrame(np.ones((2, 2), np.uint16), 1, 100), 100, policy=policy)


def test_saved_replay_preserves_old_timestamp_and_never_claims_live(tmp_path):
    np.savez_compressed(tmp_path / "depth_raw.npz", raw=np.full((2, 2), 1000, np.uint16))
    (tmp_path / "meta.json").write_text(json.dumps({"depth": {"scale_mm_per_unit": 0.1,
        "received_at_s": 100.0, "device_timestamp_ms": 12.0}}))
    frame = load_depth_capture(tmp_path)
    result = summarize(frame, 200.0)
    assert result["median_mm"] == 100 and result["status"] == "stale"
    assert result["simulated"] is True and result["source"] == "saved-replay"


def test_sdk_source_owns_only_its_pipeline_and_does_not_set_device_properties():
    calls = []
    class Pipeline:
        def __init__(self, device): pass
        def get_stream_profile_list(self, sensor):
            return SimpleNamespace(get_video_stream_profile=lambda *args: calls.append(("profile", args)) or "profile")
        def start(self, config): calls.append(("start",))
        def wait_for_frames(self, timeout):
            time.sleep(0.005)
            return SimpleNamespace(get_depth_frame=lambda: SDKFrame(timestamp=time.monotonic() * 1000))
        def stop(self): calls.append(("stop",))
    class Config:
        def enable_stream(self, profile): calls.append(("enable", profile))
    info = SimpleNamespace(get_name=lambda: "Gemini 2", get_serial_number=lambda: "SYNTHETIC",
                           get_firmware_version=lambda: "fixture")
    device = SimpleNamespace(get_device_info=lambda: info)
    devices = SimpleNamespace(get_count=lambda: 1, get_device_by_index=lambda index: device)
    sdk = SimpleNamespace(Context=lambda: SimpleNamespace(query_devices=lambda: devices),
                          Pipeline=Pipeline, Config=Config, OBSensorType=SimpleNamespace(DEPTH_SENSOR="depth"),
                          OBFormat=SimpleNamespace(Y16="Y16"))
    source = OrbbecDepthSource(sdk=sdk, timeout_s=0.2)
    try:
        requested = time.time()
        source.start()
        frame = source.next_after(requested)
        assert frame.received_at_s > requested and source.health()
        assert source.device_info["serial_number"] == "SYNTHETIC"
    finally:
        source.close()
    assert calls.count(("start",)) == calls.count(("stop",)) == 1
    assert ("profile", (0, 0, "Y16", 0)) in calls


def test_repeated_hardware_timestamp_is_rejected():
    source = OrbbecDepthSource()
    source._last_device_timestamp_ms = 1234
    class Pipeline:
        def wait_for_frames(self, timeout):
            source._stop.set()
            return SimpleNamespace(get_depth_frame=lambda: SDKFrame(timestamp=1234))
    source._pipeline = Pipeline()
    source._receive()
    assert "timestamp" in source._error
    assert not source.health()


def test_timeout_does_not_reuse_previous_object_frame():
    source = OrbbecDepthSource(timeout_s=0.01)
    source._frame = DepthFrame(np.ones((2, 2), np.uint16), 1, 100)
    with pytest.raises(TimeoutError): source.next_after(200)


@pytest.mark.parametrize("count", [0, 2])
def test_sdk_source_does_not_guess_device_when_missing_or_multiple(count):
    devices = SimpleNamespace(get_count=lambda: count)
    sdk = SimpleNamespace(Context=lambda: SimpleNamespace(query_devices=lambda: devices))
    source = OrbbecDepthSource(sdk=sdk)
    with pytest.raises(RuntimeError, match="1대"):
        source.start()
    source.close()


def test_constant_device_timestamp_uses_frame_index():
    # Gemini 2 실측: 장치 시각은 고정, 프레임 번호만 증가. 번호로 순서를 판단해야 프레임을 버리지 않는다.
    import numpy as np
    import depth as dmod

    class Frame:
        def __init__(self, i):
            self.i = i
        def get_width(self): return 2
        def get_height(self): return 2
        def get_data(self): return np.array([1, 2, 3, 4], np.uint16).tobytes()
        def get_format(self): return "OBFormat.Y16"
        def get_depth_scale(self): return 1.0
        def get_timestamp(self): return 292057776
        def get_index(self): return self.i

    frames = [dmod.from_sdk_frame(Frame(i)) for i in (1, 2, 3)]
    assert [f.frame_index for f in frames] == [1, 2, 3]
    assert len({f.device_timestamp_ms for f in frames}) == 1
    summary = dmod.summarize(frames[-1], frames[-1].received_at_s)
    assert summary["order_key"] == "frame_index" and summary["frame_index"] == 3
