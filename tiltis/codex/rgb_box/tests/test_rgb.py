import io
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector import candidates
from source import fetch_rgb, rgb_panel
from segment import mask_geometry


def test_same_box_text_duplicates_merged_but_second_object_retained():
    boxes = [[10, 30, 80, 95], [12, 31, 79, 94], [140, 20, 200, 90]]
    found = candidates(boxes, [.6, .5, .7], ["cardboard box", "white box", "box"], (240, 100))
    assert len(found) == 2 and {tuple(v["bbox_px"]) for v in found} == {(10, 30, 80, 95), (140, 20, 200, 90)}


def test_weak_detections_not_used_as_confirmed_boxes():
    assert candidates([[10, 10, 20, 20]], [.1], ["box"], (100, 100)) == []


@pytest.mark.parametrize("box,score", [([1, 2, float("nan"), 10], .5),
                                     ([-1, 2, 10, 10], .5), ([1, 2, 101, 10], .5),
                                     ([1, 2, 10, 10], float("inf"))])
def test_invalid_model_coordinates_refused(box, score):
    with pytest.raises(ValueError):
        candidates([box], [score], ["box"], (100, 100))


def test_thermal_and_depth_pixels_never_enter_rgb_detector():
    image = Image.new("RGB", (1440, 360), "red")
    image.paste("green", (480, 0, 960, 360))
    image.paste("blue", (960, 0, 1440, 360))
    data = io.BytesIO()
    image.save(data, format="PNG")
    crop = rgb_panel(data.getvalue(), 480)
    assert crop.size == (480, 360) and crop.getpixel((479, 359)) == (255, 0, 0)


def test_failed_sensor_request_cannot_reuse_previous_picture():
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    with client, pytest.raises(httpx.HTTPStatusError):
        fetch_rgb(client, "http://test/live.jpg")


def test_mask_pixels_reported_in_same_rgb_frame():
    mask = np.zeros((100, 240), dtype=bool)
    mask[30:60, 80:120] = True
    assert mask_geometry(mask, (240, 100)) == {"mask_area_px": 1200, "mask_center_px": [99.5, 44.5],
                                              "mask_bbox_px": [80, 30, 120, 60]}


@pytest.mark.parametrize("mask", [np.zeros((100, 240), dtype=bool), np.ones((240, 100), dtype=bool),
                                  np.ones((100, 240), dtype=float)])
def test_empty_or_wrong_frame_masks_not_accepted(mask):
    with pytest.raises(ValueError):
        mask_geometry(mask, (240, 100))
