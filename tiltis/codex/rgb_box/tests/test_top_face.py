import sys
from pathlib import Path
import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from top_face import face_prompts, face_geometry


def test_quad_angles_follow_rotated_face_in_y_down_image_without_robot_yaw():
    mask = np.zeros((180, 220), bool)
    quad = np.rint(cv2.boxPoints(((110, 65), (80, 32), 27))).astype(int)
    tmp = mask.astype('uint8')
    cv2.fillConvexPoly(tmp, quad, 1)
    mask = tmp.astype(bool)
    whole = np.zeros_like(mask)
    whole[20:160, 45:175] = True
    result = face_geometry(mask, whole, [[110, 65], [110, 145], [50, 110], [170, 110]])
    assert result and result['top_confirmed'] is False and result['robot_yaw_deg'] is None
    assert sorted(result['edge_angles_image_deg']) == pytest.approx([27, 117], abs=2)


def test_whole_box_or_side_prompt_is_not_a_face_candidate():
    whole = np.zeros((150, 150), bool)
    whole[10:140, 10:140] = True
    assert face_geometry(whole, whole, [[75, 25], [75, 125], [25, 90], [125, 90]]) is None


@pytest.mark.parametrize('box', [[0,0,230,100], [1,1,1,20], [1,float('nan'),20,30]])
def test_prompts_reject_invalid_bounds(box):
    with pytest.raises(ValueError):
        face_prompts(box, (220, 180))
