import cv2
import numpy as np
import pytest

from guided_top import agreement, prompts
from top_tape import inspect_top


def image(edges=(0, 1, 2)):
    rgb = np.full((280, 280, 3), [70, 140, 170], np.uint8)
    quad = [[20, 20], [259, 20], [259, 259], [20, 259]]
    mask = np.zeros((280, 280), bool)
    mask[20:260, 20:260] = True
    patches = [(100, 20, 170, 75), (20, 100, 75, 170), (100, 205, 170, 260), (205, 100, 260, 170)]
    for edge in edges:
        x0, y0, x1, y1 = patches[edge]
        rgb[y0:y1, x0:x1] = [130, 180, 30]
    return rgb, quad, mask


def test_three_wrapped_attachments_remain_three_when_green_regions_merge():
    rgb, quad, mask = image()
    # Connect all three attachments in the interior: one component, 3 edges.
    cv2.line(rgb, (125, 45), (45, 125), (130, 180, 30), 12)
    cv2.line(rgb, (45, 125), (125, 230), (130, 180, 30), 12)
    result, _, green = inspect_top(rgb, quad, mask, top_confirmed=True)
    assert cv2.connectedComponents(green.astype(np.uint8))[0] == 2
    assert result["observed_wrapped_edges"] == 3
    assert result["verdict"] == "no_anomaly"


def test_two_attachments_are_not_promoted_by_area_or_expected_count():
    rgb, quad, mask = image((0, 2))
    result, _, _ = inspect_top(rgb, quad, mask, top_confirmed=True)
    assert result["observed_wrapped_edges"] == 2 and result["verdict"] == "suspect"


def test_unconfirmed_face_or_occluded_edge_requires_another_view():
    rgb, quad, mask = image()
    result, _, _ = inspect_top(rgb, quad, mask)
    assert result["verdict"] == "unmeasurable"
    visible = mask.copy(); visible[20:75, 100:160] = False
    result, _, _ = inspect_top(rgb, quad, mask, top_confirmed=True, visible_mask=visible)
    assert result["verdict"] == "unmeasurable" and result["needs_another_view"]


def test_entire_green_face_is_ambiguous_and_cannot_impersonate_tapes():
    rgb, quad, mask = image()
    rgb[mask] = [130, 180, 30]
    result, _, _ = inspect_top(rgb, quad, mask, top_confirmed=True)
    assert result["verdict"] == "unmeasurable"


def test_sampler_handles_top_quads_at_any_camera_rotation():
    rgb, quad, mask = image()
    for turns in range(4):
        result, _, _ = inspect_top(np.rot90(rgb, turns).copy(), quad, np.rot90(mask, turns), top_confirmed=True)
        assert result["observed_wrapped_edges"] == 3
    assert agreement(mask, quad)["scene_corner_agreement_rms_px"] == 0


def test_self_crossing_prompt_is_rejected():
    with pytest.raises(ValueError, match="convex"):
        prompts([[20, 20], [200, 200], [200, 20], [20, 200]], (280, 280))
