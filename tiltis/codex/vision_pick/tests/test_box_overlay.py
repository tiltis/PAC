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


def test_two_eligible_boxes_are_ambiguous_and_leave_whole_frame_unchanged():
    frame = _frame()
    cv2.rectangle(frame, (40, 150), (135, 240), _brown(), -1)
    cv2.rectangle(frame, (280, 170), (380, 280), _brown(), -1)
    # A plausible cardboard object on the depth panel must be ignored entirely.
    cv2.rectangle(frame, (1000, 80), (1200, 300), _brown(), -1)
    original = frame.copy()
    annotated, count = annotate_collage(frame)
    assert count == 0
    assert np.array_equal(frame, original)
    assert np.array_equal(annotated, original)


def test_one_eligible_box_gets_red_outline_without_editing_input_or_other_panels():
    frame = _frame()
    cv2.rectangle(frame, (220, 170), (320, 280), _brown(), -1)
    cv2.rectangle(frame, (1000, 80), (1200, 300), _brown(), -1)
    original = frame.copy()
    annotated, count = annotate_collage(frame)
    assert count == 1
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
    cv2.rectangle(frame, (170, 85), (239, 155), _brown(), -1)
    annotated, count = annotate_collage(frame, rgb_width=240)
    assert count == 1
    assert np.array_equal(annotated[:, 240:], frame[:, 240:])


def test_background_candidate_above_workspace_is_ignored_for_table_target():
    frame = _frame()
    cv2.rectangle(frame, (40, 25), (135, 115), _brown(), -1)
    cv2.rectangle(frame, (280, 180), (380, 280), _brown(), -1)
    annotated, count = annotate_collage(frame)
    assert count == 1
    assert np.array_equal(annotated[:140], frame[:140])
    assert not np.array_equal(annotated[170:290, 270:390], frame[170:290, 270:390])


def test_candidate_crossing_workspace_boundary_is_not_clipped_into_a_target():
    frame = _frame()
    cv2.rectangle(frame, (40, 130), (135, 240), _brown(), -1)
    cv2.rectangle(frame, (280, 180), (380, 280), _brown(), -1)
    annotated, count = annotate_collage(frame)
    assert count == 1
    assert np.array_equal(annotated[:, :200], frame[:, :200])


@pytest.mark.parametrize("zone_color", [(255, 0, 0), (0, 0, 255)], ids=["blue", "red"])
def test_output_zone_box_is_excluded_and_only_remaining_table_target_is_outlined(zone_color):
    frame = _frame()
    cv2.rectangle(frame, (10, 150), (155, 350), zone_color, -1)
    cv2.rectangle(frame, (35, 185), (120, 280), _brown(), -1)
    cv2.rectangle(frame, (280, 180), (380, 280), _brown(), -1)
    original = frame.copy()
    annotated, count = annotate_collage(frame)
    assert count == 1
    assert np.array_equal(annotated[:, :200], original[:, :200])
    assert np.array_equal(frame, original)
    assert not np.array_equal(annotated[170:290, 270:390], original[170:290, 270:390])


def test_boxes_in_both_output_zones_get_no_target_outline():
    frame = _frame()
    cv2.rectangle(frame, (5, 145), (165, 350), (255, 0, 0), -1)
    cv2.rectangle(frame, (35, 185), (135, 280), _brown(), -1)
    cv2.rectangle(frame, (320, 145), (479, 350), (0, 0, 255), -1)
    cv2.rectangle(frame, (340, 185), (440, 280), _brown(), -1)
    annotated, count = annotate_collage(frame)
    assert count == 0
    assert np.array_equal(annotated, frame)


def test_custom_normalized_workspace_selects_only_fully_contained_candidate():
    frame = _frame()
    cv2.rectangle(frame, (40, 180), (140, 280), _brown(), -1)
    cv2.rectangle(frame, (280, 180), (380, 280), _brown(), -1)
    annotated, count = annotate_collage(frame, workspace_roi=(0.5, 0.4, 1, 1))
    assert count == 1
    assert np.array_equal(annotated[:, :240], frame[:, :240])


def test_ambiguous_jpeg_is_returned_byte_for_byte_without_selecting_largest_box():
    frame = _frame()
    cv2.rectangle(frame, (30, 165), (185, 320), _brown(), -1)
    cv2.rectangle(frame, (280, 185), (350, 255), _brown(), -1)
    ok, encoded = cv2.imencode('.jpg', frame)
    assert ok
    raw = encoded.tobytes()
    annotated, count = annotate_jpeg(raw)
    assert count == 0
    assert annotated == raw


@pytest.mark.parametrize("roi", [None, (0, 0, 1), (0, 0, 1, 1, 1), (-0.1, 0, 1, 1),
                                  (0, 0.4, 1.1, 1), (0.5, 0.4, 0.5, 1),
                                  (0, 1, 1, 0.4), (0, float('nan'), 1, 1),
                                  (0, 0, float('inf'), 1)])
def test_invalid_workspace_roi_is_rejected(roi):
    with pytest.raises(ValueError):
        annotate_collage(_frame(), workspace_roi=roi)
