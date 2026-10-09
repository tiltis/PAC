import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guided_top import agreement, prompts, quad_mask


def test_prompts_cover_materials_but_keep_side_negatives_outside():
    q = np.array([[20,20],[120,20],[120,120],[20,120]],float)
    batches = np.asarray(prompts(q,(160,160)))
    assert batches.shape == (3,13,2)
    assert ((batches[:,:9] > 20) & (batches[:,:9] < 120)).all()
    assert ((batches[:,9:] < 20) | (batches[:,9:] > 120)).any(axis=2).all()


def test_top_agreement_rejects_whole_box_and_small_tape():
    q = [[20,20],[120,20],[120,120],[20,120]]
    top = quad_mask(q,(170,170))
    result = agreement(top,q)
    assert result['depth_prompt_iou'] == 1 and result['motion_enabled'] is False
    whole = quad_mask([[20,20],[120,20],[120,165],[20,165]],top.shape)
    assert agreement(whole,q) is None
    tape = np.zeros_like(top); tape[50:70,40:100] = True
    assert agreement(tape,q) is None


@pytest.mark.parametrize('q',[[[0,0],[10,0],[0,10],[10,10]], [[-1,1],[20,1],[20,20],[1,20]]])
def test_invalid_prompt_rejected(q):
    with pytest.raises(ValueError):
        prompts(q,(100,100))
