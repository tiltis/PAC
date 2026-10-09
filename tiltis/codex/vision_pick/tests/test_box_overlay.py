import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from box_overlay import annotate_collage, annotate_jpeg


def _brown():
    return tuple(int(x) for x in cv2.cvtColor(np.uint8([[[15, 115, 180]]]),
                                           cv2.COLOR_HSV2BGR)[0, 0])


def _frame():
    return np.full((360, 1506, 3), 225, dtype=np.uint8)


def test_two_separate_boxes_get_red_rgb_outlines_without_editing_input_or_other_panels():
    frame = _frame()
    cv2.rectangle(frame, (40, 150), (135, 240), _brown(), -1)
    cv2.rectangle(frame, (280, 110), (380, 210), _brown(), -1)
    # A plausible cardboard object on the depth panel must be ignored entirely.
    cv2.rectangle(frame, (1000, 80), (1200, 300), _brown(), -1)
    original = frame.copy()
    annotated, count = annotate_collage(frame)
    assert count == 2
    assert np.array_equal(frame, original)
    assert np.array_equal(annotated[:, 480:], original[:, 480:])
    assert np.any((annotated[:, :480, 2] == 255) & (annotated[:, :480, 1] == 0))


def test_edge_outline_does_not_bleed_into_thermal_panel():
    frame = _frame()
    cv2.rectangle(frame, (410, 150), (479, 270), _brown(), -1)
    annotated, count = annotate_collage(frame)
    assert count == 1
    assert np.array_equal(annotated[:, 480:], frame[:, 480:])


def test_depth_only_box_produces_no_rgb_overlay_and_keeps_jpeg_exactly():
    frame = _frame()
    cv2.rectangle(frame, (970, 120), (1130, 260), _brown(), -1)
    ok, encoded = cv2.imencode('.jpg', frame)
    assert ok
    raw = encoded.tobytes()
    result, count = annotate_jpeg(raw)
    assert count == 0 and result == raw


def test_missing_frames_and_truncated_rgb_panel_rejected():
    for raw in (b'', b'not an image', None):
        with pytest.raises(ValueError):
            annotate_jpeg(raw)
    with pytest.raises(ValueError):
        annotate_collage(np.zeros((360, 479, 3), np.uint8))


def test_small_noise_and_brown_background_are_not_called_boxes():
    frame = _frame()
    cv2.rectangle(frame, (10, 10), (18, 18), _brown(), -1)
    cv2.rectangle(frame, (0, 140), (479, 359), _brown(), -1)
    _, count = annotate_collage(frame)
    assert count == 0


def test_green_tape_does_not_cut_holes_into_box_outline():
    frame = _frame()
    cv2.rectangle(frame, (50, 170), (190, 290), _brown(), -1)
    green = tuple(int(x) for x in cv2.cvtColor(np.uint8([[[80, 170, 180]]]),
                                            cv2.COLOR_HSV2BGR)[0, 0])
    cv2.rectangle(frame, (80, 175), (115, 275), green, -1)
    annotated, count = annotate_collage(frame)
    assert count == 1
    assert np.array_equal(annotated[190:250, 85:110], frame[190:250, 85:110])


def test_explicit_rgb_width_supports_alternate_layout():
    frame = np.full((180, 800, 3), 225, dtype=np.uint8)
    cv2.rectangle(frame, (170, 50), (239, 135), _brown(), -1)
    annotated, count = annotate_collage(frame, rgb_width=240)
    assert count == 1
    assert np.array_equal(annotated[:, 240:], frame[:, 240:])
