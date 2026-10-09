import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location("robot_status", Path(__file__).resolve().parents[1] / "robot_status.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


class ReadBus:
    motors = {"shoulder_pan": object(), "gripper": object()}

    def __init__(self, matched=True, fail=None):
        self.is_connected = False
        self.is_calibrated = matched
        self.calls = []
        self.fail = fail

    def connect(self, *, handshake):
        self.calls.append(("connect", handshake))
        self.is_connected = True
        if self.fail == "handshake":
            raise RuntimeError("missing motor")

    def sync_read(self, name, *, normalize):
        self.calls.append(("read", name, normalize))
        if self.fail == "read":
            raise RuntimeError("read timeout")
        if self.fail == "missing":
            return {"gripper": 0}
        if self.fail == "nan":
            return {"shoulder_pan": float("nan"), "gripper": 0}
        if name == "Torque_Enable":
            return {"shoulder_pan": 1, "gripper": 1}
        return {"shoulder_pan": 5.0 if normalize else 2050, "gripper": 35.0 if normalize else 1000}

    def disconnect(self, *, disable_torque):
        assert disable_torque is False
        self.calls.append(("disconnect", disable_torque))
        self.is_connected = False

    def __getattr__(self, name):
        raise AssertionError(f"unexpected SDK operation: {name}")


class StatusTests(unittest.TestCase):
    def robot(self, bus):
        return SimpleNamespace(bus=bus, config=SimpleNamespace(port="TEST"), id="test_robot",
                               calibration_fpath=Path(tempfile.gettempdir()) / "pac_missing_calibration.json")

    def test_metadata_never_opens_port(self):
        bus = ReadBus()
        result = status.metadata(self.robot(bus))
        self.assertFalse(result["hardware_queried"])
        self.assertEqual(bus.calls, [])

    def test_read_calibrated_without_motion_or_torque_writes(self):
        bus = ReadBus()
        result = status.read_status(self.robot(bus))
        self.assertEqual(result["raw_position_ticks"]["shoulder_pan"], 2050)
        self.assertEqual(result["joint_positions"]["shoulder_pan.pos"], 5.0)
        self.assertEqual(result["joint_units"]["gripper.pos"], "gripper_0_100")
        self.assertEqual(result["motion_readiness"], "not_verified")
        self.assertEqual(bus.calls, [("connect", True), ("read", "Present_Position", False),
                                    ("read", "Torque_Enable", False), ("read", "Present_Position", True),
                                    ("disconnect", False)])

    def test_uncalibrated_never_normalizes_position(self):
        bus = ReadBus(matched=False)
        result = status.read_status(self.robot(bus))
        self.assertIsNone(result["joint_positions"])
        self.assertNotIn(("read", "Present_Position", True), bus.calls)

    def test_failure_closes_port_without_torque_change(self):
        for failure in ("handshake", "read", "missing", "nan"):
            with self.subTest(failure=failure):
                bus = ReadBus(fail=failure)
                with self.assertRaises(RuntimeError):
                    status.read_status(self.robot(bus))
                self.assertFalse(bus.is_connected)
                self.assertEqual(bus.calls[-1], ("disconnect", False))

    def test_preconnected_bus_is_not_closed(self):
        bus = ReadBus()
        bus.is_connected = True
        with self.assertRaises(RuntimeError):
            status.read_status(self.robot(bus))
        self.assertTrue(bus.is_connected)
        self.assertEqual(bus.calls, [])


if __name__ == "__main__":
    unittest.main()
