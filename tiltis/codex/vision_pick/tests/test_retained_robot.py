"""Retained attachment must never use SDK connect/configure or write registers."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / "claude-code" / "PAC2026_system" / "station"))
sys.path.insert(0, str(HERE.parents[1]))
import retained_robot as module

MOTORS = set(module._MOTORS)


class Bus:
    def __init__(self):
        self.motors = {key: object() for key in MOTORS}
        self.is_connected = False
        self.is_calibrated = True
        self.calls = []
        self.samples = {
            "Torque_Enable": dict.fromkeys(MOTORS, 1),
            "Operating_Mode": dict.fromkeys(MOTORS, 0),
            "Present_Position": dict.fromkeys(MOTORS, 12.5),
        }
        self.handshake_error = False

    def connect(self, *, handshake):
        self.calls.append(("connect", handshake))
        self.is_connected = True
        if self.handshake_error:
            raise RuntimeError("handshake failed")

    def sync_read(self, register, *, normalize):
        self.calls.append(("read", register, normalize))
        return self.samples[register]

    def disconnect(self, *, disable_torque):
        assert disable_torque is False
        self.calls.append(("disconnect", disable_torque))
        self.is_connected = False

    def __getattr__(self, name):
        pytest.fail(f"Unexpected bus operation: {name}")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    bus = Bus()
    reader = SimpleNamespace(bus=bus)
    factory = []

    def make_reader(port, robot_id):
        factory.append((port, robot_id))
        return reader

    monkeypatch.setattr(module, "make_reader", make_reader)
    path = tmp_path / "poses.json"
    path.write_text(json.dumps({"joints": {"home": {"wrist_roll.pos": -163.38}}}), encoding="utf-8")
    robot = module.RetainedSo101Robot("FAKE", "test-arm", poses_path=path)
    return robot, bus, reader, factory


def test_attach_reads_only_and_preserves_torque_on_disconnect(setup):
    robot, bus, reader, factory = setup
    robot.connect()
    assert factory == [("FAKE", "test-arm")]
    assert robot._robot is reader
    assert robot._target == {key + ".pos": 12.5 for key in MOTORS}
    assert robot.poses["joints"]["home"]["wrist_roll.pos"] == -163.38
    assert bus.calls == [("connect", True), ("read", "Torque_Enable", False),
                         ("read", "Operating_Mode", False), ("read", "Present_Position", True)]
    robot.disconnect()
    robot.disconnect()
    assert bus.calls[-1] == ("disconnect", False)
    assert robot._robot is None and robot._target == {}


@pytest.mark.parametrize("register,value", [("Torque_Enable", 0), ("Operating_Mode", 1),
                                             ("Torque_Enable", True), ("Operating_Mode", False),
                                             ("Present_Position", float("nan")),
                                             ("Present_Position", float("inf")),
                                             ("Present_Position", "12.5")])
def test_bad_state_refuses_attachment_and_closes_without_torque_change(setup, register, value):
    robot, bus, _, _ = setup
    bus.samples[register][next(iter(MOTORS))] = value
    with pytest.raises(module.RobotError):
        robot.connect()
    assert robot._robot is None and robot._target == {}
    assert bus.calls[-1] == ("disconnect", False)


@pytest.mark.parametrize("register", ["Torque_Enable", "Operating_Mode", "Present_Position"])
def test_incomplete_motor_sample_fails_closed(setup, register):
    robot, bus, _, _ = setup
    bus.samples[register].pop(next(iter(MOTORS)))
    with pytest.raises(module.RobotError):
        robot.connect()
    assert bus.calls[-1] == ("disconnect", False)
    assert robot._robot is None


@pytest.mark.parametrize("failure", ["calibration", "handshake"])
def test_failure_before_first_sample_closes_bus(setup, failure):
    robot, bus, _, _ = setup
    if failure == "calibration":
        bus.is_calibrated = False
    else:
        bus.handshake_error = True
    with pytest.raises(module.RobotError):
        robot.connect()
    assert bus.calls == [("connect", True), ("disconnect", False)]
    assert robot._robot is None


def test_preexisting_bus_is_not_claimed_or_closed(setup):
    robot, bus, _, _ = setup
    bus.is_connected = True
    with pytest.raises(module.RobotError):
        robot.connect()
    assert bus.calls == [] and bus.is_connected


def test_second_connect_preserves_owned_connection(setup):
    robot, bus, reader, factory = setup
    robot.connect()
    before = list(bus.calls)
    with pytest.raises(module.RobotError):
        robot.connect()
    assert robot._robot is reader and bus.calls == before and len(factory) == 1


def test_wrong_motor_configuration_never_opens_port(setup):
    robot, bus, _, _ = setup
    bus.motors.pop(next(iter(MOTORS)))
    with pytest.raises(module.RobotError):
        robot.connect()
    assert bus.calls == []


def test_sdk_version_failure_never_opens_port(setup, monkeypatch):
    robot, bus, _, _ = setup
    monkeypatch.setattr(module, "make_reader", module._status.make_reader)
    monkeypatch.setattr(module._status.importlib.metadata, "version", lambda _: "unsupported")
    with pytest.raises(module.RobotError, match="0.6.1"):
        robot.connect()
    assert bus.calls == [] and robot._robot is None
