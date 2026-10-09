"""Taught-mode wrapper keeps the installed IK and its remaining constraints."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taught_station import TaughtPicker
import taught_approach


class OriginalPicker:
    def __init__(self, result=None):
        self.cfg = {"side_reach_r_m": [.37, .49], "side_min_tip_z_mm": 10,
                    "max_roll_jump_deg": 20, "nested": {"preserve": [1, 2]}}
        self.joint_map = {"shoulder_pan": {"sign": -1, "offset_deg": 2}}
        self.result = result or {"ok": True, "approach": {"fixture": 1}, "grasp": {"fixture": 2}}
        self.calls = []
        self.dry_run = True

    def plan(self, loc):
        self.calls.append({"instance": self, "loc": loc, "cfg": copy.deepcopy(self.cfg)})
        self.cfg["nested"]["preserve"].append(99)  # Exercise a planner writing its private copy.
        return copy.deepcopy(self.result)


def test_only_coarse_lower_reach_bound_changes_on_a_private_picker_copy():
    original = OriginalPicker()
    before = copy.deepcopy(original.cfg)
    loc = {"found": True, "box_center_on_table_cam_mm": [344, 0, 0]}
    result = TaughtPicker(original, {}).plan(loc)
    assert len(original.calls) == 1
    call = original.calls[0]
    assert call["instance"] is not original and call["loc"] is loc
    assert call["cfg"] == {**before, "side_reach_r_m": [0.0, .49]}
    assert original.cfg == before
    assert result["ok"] is True
    assert result["approach"] == original.result["approach"]
    assert result["grasp"] == original.result["grasp"]
    assert result["pick_path_mode"] == "taught_home_lower"
    assert result["strict_vertical"] is False
    assert result["reach_policy"] == {"minimum": "existing_ik", "previous_minimum_m": .37, "maximum_m": .49}


@pytest.mark.parametrize("maximum", [.41, .49, .60])
def test_configured_outer_boundary_is_never_increased(maximum):
    original = OriginalPicker()
    original.cfg["side_reach_r_m"] = [.37, maximum]
    result = TaughtPicker(original, {}).plan({})
    assert original.calls[0]["cfg"]["side_reach_r_m"] == [0.0, maximum]
    assert original.cfg["side_reach_r_m"] == [.37, maximum]
    assert result["reach_policy"]["maximum_m"] == maximum


@pytest.mark.parametrize("reason", ["grasp 역기구학 해 없음", "관절 변화가 너무 큼", "끝 최소 높이 조건 실패"])
def test_ik_and_downstream_rejections_remain_rejections(reason):
    original = OriginalPicker({"ok": False, "reason": reason})
    result = TaughtPicker(original, {}).plan({"found": True})
    assert result["ok"] is False and result["reason"] == reason
    assert "approach" not in result and "grasp" not in result
    assert original.cfg["side_reach_r_m"] == [.37, .49]


def test_original_plan_exception_is_not_replaced_by_a_taught_fallback():
    class Broken(OriginalPicker):
        def plan(self, loc):
            raise ValueError("invalid actual model")
    with pytest.raises(ValueError, match="invalid actual model"):
        TaughtPicker(Broken(), {}).plan({})


def test_home_path_uses_recorded_snapshot_and_existing_vision_endpoints(monkeypatch):
    original = OriginalPicker()
    teaching = {"home_joints": {"sample": "home"}, "taught_lower_joints": {"sample": "lower"}}
    wrapper = TaughtPicker(original, teaching)
    snapshot = copy.deepcopy(teaching)
    teaching["taught_lower_joints"]["sample"] = "changed after construction"
    calls = []
    expected = {"descend": [{"recorded": True}], "forward": [{"vision": True}]}
    def planner(*args):
        calls.append(args)
        return expected
    monkeypatch.setattr(taught_approach, "plan_taught_approach", planner)
    home = {"seed": "selected HOME"}
    vision = {"approach": {"a": 1}, "grasp": {"g": 2}}
    assert wrapper.plan_home_path(vision, home) is expected
    args = calls[0]
    assert args == (snapshot, home, vision["approach"], vision["grasp"], original.joint_map)
    assert args[1] is home and args[2] is vision["approach"] and args[3] is vision["grasp"]
    assert wrapper.dry_run is True


def test_home_preflight_checks_recorded_lower_without_substituting_it(monkeypatch):
    original = OriginalPicker()
    teaching = {"taught_lower_joints": {"captured": 1}}
    wrapper = TaughtPicker(original, teaching)
    calls = []
    monkeypatch.setattr(taught_approach, "plan_taught_approach", lambda *args: calls.append(args))
    home = {"home": 1}
    result = wrapper.validate_home_path_start(home)
    assert result == {"ok": True, "mode": "taught_home_lower"}
    assert calls[0] == (teaching, home, teaching["taught_lower_joints"],
                        teaching["taught_lower_joints"], original.joint_map)


def test_home_path_failure_propagates_before_any_command(monkeypatch):
    def reject(*args):
        raise ValueError("sampled TCP below table")
    monkeypatch.setattr(taught_approach, "plan_taught_approach", reject)
    wrapper = TaughtPicker(OriginalPicker(), {"taught_lower_joints": {}})
    with pytest.raises(ValueError, match="below table"):
        wrapper.plan_home_path({"approach": {}, "grasp": {}}, {})
