import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from native_rgbd import NativeRgbd, color_image, rectification


def test_missing_color_discards_previous_preview_and_clock_progress():
    source=NativeRgbd.__new__(NativeRgbd)
    source.latest=source.observation={'previous':'frame'}
    source._clock_progress=8
    source._last_device_clocks=[10,20]
    source.receive(SimpleNamespace(get_color_frame=lambda:None),None)
    assert source.latest is source.observation is source._last_device_clocks is None
    assert source._clock_progress==0 and source.error=='paired color missing'


class Color:
    def __init__(self, stamp, fmt="RGB"):
        self.stamp, self.fmt = stamp, fmt
    def get_width(self): return 4
    def get_height(self): return 3
    def get_format(self): return self.fmt
    def get_data(self): return np.tile([210, 40, 20], (12, 1)).astype(np.uint8).tobytes()
    def get_system_timestamp(self): return self.stamp * 1000
    def get_global_timestamp_us(self): return self.stamp * 1e6
    def get_timestamp_us(self): return self.stamp * 1e6
    def get_index(self): return 12


def pair():
    p = NativeRgbd.__new__(NativeRgbd)
    yy, xx = np.indices((3, 4), dtype=np.float32)
    p.rgb_maps = p.depth_maps = (xx, yy)
    p.rgb_intrinsics = p.depth_intrinsics = {"width": 4, "height": 3}
    p.registration = {"validated": False, "rms_px": None,
                      "rgb_camera_id": "actual-device:color", "depth_camera_id": "actual-device:depth"}
    p.latest = p.error = None
    p.observation = None
    p._last_device_clocks = [0, 0]
    p._clock_progress = 3
    return p


def receive(p, rgb_stamp, depth_stamp):
    c = Color(rgb_stamp)
    f = SimpleNamespace(get_color_frame=lambda: c,
                        get_depth_frame=lambda: Color(depth_stamp))
    observation = SimpleNamespace(raw=np.full((3, 4), 600, np.uint16), scale_mm=.5, frame_index=11)
    p.receive(f, observation)
    return observation


def test_rgb_bytes_are_bgr_without_changing_camera_dimensions():
    assert color_image(Color(time.time()))[0, 0].tolist() == [20, 40, 210]


def test_native_pair_uses_sdk_capture_clocks_and_does_not_invent_registration_validation():
    p = pair(); stamp = time.time() - .05
    original = receive(p, stamp, stamp + .01)
    m = p.latest["metadata"]
    assert m["captures"]["rgb"]["captured_at_s"] == pytest.approx(stamp)
    assert m["captures"]["depth"]["captured_at_s"] == pytest.approx(stamp + .01)
    assert m["registration"]["validated"] is False and m["registration"]["rms_px"] is None
    assert np.all(p.latest["depth_mm"] == 300) and np.all(original.raw == 600)


@pytest.mark.parametrize("rgb_delta,depth_delta", [(10, 10), (-10, -10), (-.05, -.3)])
def test_stale_future_or_skewed_pairs_are_not_retimestamped(rgb_delta, depth_delta):
    p = pair(); now = time.time()
    receive(p, now + rgb_delta, now + depth_delta)
    assert p.latest is None and p.error


def test_host_arrival_timestamps_cannot_certify_exposure_sync():
    p = pair()
    receive(p, time.time() - .01, time.time() - .12)
    assert p.latest is None
    assert p.observation is not None
    assert not p.observation["metadata"]["captures"]["rgb"]["capture_time_verified"]


def test_frozen_device_clock_blocks_pair_even_with_plausible_global_time():
    p = pair(); now = time.time() - .01
    p._last_device_clocks = [now * 1e6, now * 1e6]
    receive(p, now, now)
    assert p.latest is None and p.observation


def test_unknown_color_format_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        color_image(Color(time.time(), "COMPRESSED_UNKNOWN"))


def test_inverse_distortion_cannot_be_interpreted_as_opencv_brown():
    distortion = SimpleNamespace(**dict.fromkeys(("k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6"), 0.),
                                 model="INVERSE_BROWN_CONRADY")
    i = SimpleNamespace(fx=100., fy=100., cx=2., cy=1., width=4, height=3)
    profile = SimpleNamespace(get_intrinsic=lambda: i, get_distortion=lambda: distortion)
    with pytest.raises(ValueError, match="unsupported factory distortion model"):
        rectification(profile)
