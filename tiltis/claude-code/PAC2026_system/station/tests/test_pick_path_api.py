import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import kinematics as K
from pick_path_api import HomePathPicker, PathSettings, PickPathService, home_info
from robot import MockRobot
from sequencer import BusyError, Sequencer


def arm():
    return K.to_lerobot(np.zeros(5))


def service(tmp_path):
    robot = MockRobot(poses={"joints": {"home": arm(), "face_B": arm()}, "gripper": {"open": 100}}, speed=0)
    robot.poses_path = tmp_path / "poses.json"
    robot.poses_path.write_text(json.dumps(robot.poses))
    seq = Sequencer(robot, None)
    return PickPathService(seq, tmp_path / "calib/pick_path.json")


def request(mode="home_descend_forward", **kw):
    return PathSettings(mode=mode, **kw)


@pytest.mark.parametrize("offset", [float("nan"), float("inf"), -10.01, 30.01])
def test_invalid_height_rejected(offset):
    with pytest.raises(ValidationError):
        request(height_offset_mm=offset)


def test_unknown_mode_rejected():
    with pytest.raises(ValidationError):
        request("diagonal")


def test_invalid_saved_home_explained_without_clamping():
    joints = arm()
    joints["wrist_roll.pos"] = -163.3846
    info = home_info(joints)
    assert not info["valid"]
    assert "wrist_roll" in info["reason"] and "-163.38" in info["reason"]
    assert joints["wrist_roll.pos"] == -163.3846


def test_legacy_delegates_without_changing_existing_config():
    original = SimpleNamespace(plan=lambda loc: {"ok": True, "loc": loc})
    wrapper = HomePathPicker(original, lambda: {"mode": "legacy"})
    assert wrapper.plan(123) == {"ok": True, "loc": 123}
    assert wrapper.validate_home_path_start(None) is None
    assert wrapper.plan_home_path({}, None) is None


def test_preview_rejects_home_before_camera_or_motion(tmp_path):
    s = service(tmp_path)
    s.seq.robot.poses["joints"]["home"]["wrist_roll.pos"] = -163.38
    calls = []
    original = SimpleNamespace(joint_map={}, cfg={"grasp_mode": "side", "side_use_absolute_z": True},
                               locate=lambda: calls.append("camera"))
    s.picker = HomePathPicker(original, lambda: s.value)
    result = s.preview_path(request())
    assert result["ok"] is False and result["hardware_moved"] is False
    assert "wrist_roll" in result["reason"] and not calls
    assert s.seq._configuration_active is False


def test_preview_does_not_enable_or_persist_settings(tmp_path, monkeypatch):
    s = service(tmp_path)
    original = SimpleNamespace(joint_map={}, cfg={"grasp_mode": "side", "side_use_absolute_z": True}, he={}, locate=lambda: {})
    s.picker = HomePathPicker(original, lambda: s.value)
    monkeypatch.setattr(HomePathPicker, "plan", lambda *a: {"ok": True, "grasp_point_m": [0.4, 0, 0.03]})
    monkeypatch.setattr(HomePathPicker, "plan_home_path", lambda *a: {"descend": [arm()], "forward": [arm()], "metadata": {}})
    result = s.preview_path(request(height_offset_mm=2))
    assert result["ok"] and result["preview_id"]
    assert s.value["mode"] == "legacy" and not s.path.exists()
    assert result["hardware_moved"] is False
    applied = s.apply(request(height_offset_mm=2, preview_id=result["preview_id"]))
    assert applied["mode"] == "home_descend_forward"
    assert json.loads(s.path.read_text())["height_offset_mm"] == 2


@pytest.mark.parametrize("case", ["missing", "wrong_token", "changed_input", "changed_home", "expired"])
def test_invalid_preview_cannot_activate(tmp_path, case):
    s = service(tmp_path)
    import time
    s.preview = ("token", {"mode": "home_descend_forward", "height_offset_mm": 0.0}, s.fingerprint(), time.monotonic())
    token, offset = "token", 0
    if case == "missing": s.preview = None
    if case == "wrong_token": token = "old"
    if case == "changed_input": offset = 2
    if case == "changed_home": s.seq.robot.poses["joints"]["home"]["wrist_roll.pos"] += 1
    if case == "expired": s.preview = (*s.preview[:3], time.monotonic() - 121)
    with pytest.raises(HTTPException) as e:
        s.apply(request(height_offset_mm=offset, preview_id=token))
    assert e.value.status_code == 409
    assert s.value["mode"] == "legacy" and not s.path.exists()


def test_sequence_and_settings_are_mutually_exclusive(tmp_path):
    s = service(tmp_path)
    with s.idle():
        with pytest.raises(BusyError): s.seq._begin("test", "demo")
        with pytest.raises(HTTPException): s.apply(request("legacy"))
    s.seq._busy = True
    with pytest.raises(HTTPException): s.record_home()
    assert not s.seq._configuration_active


def test_record_home_reads_only_existing_owner_and_preserves_poses(tmp_path):
    s = service(tmp_path)
    old = copy.deepcopy(s.seq.robot.poses)
    calls = []
    candidate = arm()
    candidate["wrist_roll.pos"] = 20
    s.seq.robot.current_joints = lambda: (calls.append("read") or candidate)
    s.record_home()
    saved = json.loads(s.seq.robot.poses_path.read_text())
    assert saved["joints"]["home"] == candidate
    assert saved["joints"]["face_B"] == old["joints"]["face_B"]
    assert saved["gripper"] == old["gripper"]
    assert calls == ["read"] and len(list(tmp_path.glob("*.bak"))) == 1


def test_invalid_current_pose_does_not_overwrite_home(tmp_path):
    s = service(tmp_path)
    before = s.seq.robot.poses_path.read_bytes()
    bad = arm()
    bad["wrist_roll.pos"] = -170
    s.seq.robot.current_joints = lambda: bad
    with pytest.raises(HTTPException): s.record_home()
    assert s.seq.robot.poses_path.read_bytes() == before


def test_changed_home_blocks_enabled_path_even_after_service_reload(tmp_path):
    s = service(tmp_path)
    original = SimpleNamespace(joint_map={}, cfg={"grasp_mode":"side", "side_use_absolute_z":True}, he={})
    s.bind_picker(original)
    s.value = {"mode":"home_descend_forward", "height_offset_mm":0.0}
    s.accepted_geometry = s.fingerprint()
    assert s.picker.validate_home_path_start(arm()) == {"ok":True}
    s.seq.robot.current_joints = arm
    s.record_home()
    assert s.settings()["needs_preview"]
    with pytest.raises(ValueError, match="미리보기"):
        s.picker.validate_home_path_start(arm())
    reloaded = PickPathService(s.seq, s.path)
    assert reloaded.settings()["mode"] == "home_descend_forward"
    assert reloaded.settings()["needs_preview"]
    with pytest.raises(ValueError, match="미리보기"):
        reloaded.picker.validate_home_path_start(arm())


def test_rebinding_optional_picker_keeps_settings_and_execution_together(tmp_path):
    s = service(tmp_path)
    original = SimpleNamespace(joint_map={}, cfg={}, he={}, plan=lambda loc: {"origin":"replacement"})
    s.bind_picker(original)
    assert s.seq.picker is s.picker
    assert s.seq.picker.plan({}) == {"origin":"replacement"}
    assert s.seq.picker.original is original
