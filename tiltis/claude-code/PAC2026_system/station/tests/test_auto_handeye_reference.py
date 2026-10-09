"""Calibration point must match the jaw center, independently of measured opening."""
import numpy as np
import pytest


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_calibration_keeps_height_fraction_and_matches_jaw_reference(monkeypatch, mode):
    import grasp
    import handeye
    import kinematics as K
    import sensor_client
    import teach

    cfg = dict(grasp.DEFAULTS, grasp_mode="side", side_jaw_offset_frame_m=[-.0281, .019, -.0347])
    monkeypatch.setattr(grasp, "load_config", lambda: cfg)
    tool = np.eye(4)
    tool[:3, 3] = [.42, 0, .03]

    class Model:
        def ik(self, *args, **kwargs): return np.zeros(5)
        def fk(self, *args): return tool.copy()

    class Sensor:
        def __init__(self, *args): pass
        def close(self): pass
        def locate(self):
            return {"found": True, "box_mm": [80, 80, 45], "top_height_mm": 45,
                    "table_normal_cam": [0, 0, -1], "box_center_on_table_cam_mm": [0, 0, 500]}

    class Robot:
        def enable_torque(self): pass
        def disable_torque(self): pass
        def set_gripper(self, *args): pass
        def move_joints(self, *args): pass
        def move_to(self, *args): pass
        def wait_settled(self, *args): return True
        def current_joints(self): return K.to_lerobot(np.zeros(5), {})
        def gripper_reading(self): return {"open": 100, "closed": 0, "pos": 80}

    monkeypatch.setattr(K, "SO101", Model)
    monkeypatch.setattr(K, "load_joint_map", lambda: {})
    monkeypatch.setattr(sensor_client, "SensorClient", Sensor)
    monkeypatch.setattr(teach.time, "sleep", lambda _: None)
    replies = iter([""] * (7 if mode == "auto" else 6) + ["y"])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    captured = {}
    def fit(cam, rob):
        captured.update(cam=np.array(cam), rob=np.array(rob))
        return {"rms_mm": 0, "max_mm": 0, "residuals_mm": [0] * 6}
    monkeypatch.setattr(handeye, "fit", fit)
    monkeypatch.setattr(handeye, "save", lambda *args: "mock-only")
    monkeypatch.setattr(teach, "_hold_loop", lambda *args: None)
    if mode == "auto":
        teach.calibrate_handeye_auto(Robot(), "mock")
    else:
        teach.calibrate_handeye(Robot(), "mock", 6)
    assert len(captured["cam"]) == 6
    # 80% opening must not replace the configured 50% box height.
    assert np.allclose(captured["cam"], [0, 0, 477.5])
    assert np.allclose(captured["rob"], tool[:3, 3] + cfg["side_jaw_offset_frame_m"])
