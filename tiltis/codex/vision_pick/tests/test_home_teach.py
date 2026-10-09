"""Manual observations are saved without trajectory replay or a second COM owner."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import home_teach
from home_teach import KEYS, TeachSession, create_app


def joints(value=0.0):
    return {key: float(value + index) for index, key in enumerate(KEYS)}


class Robot:
    robot_id = "fake-manual-arm"

    def __init__(self):
        self.calls = []
        self.observed = joints()

    def connect(self):
        self.calls.append("connect")

    def disable_torque(self):
        self.calls.append("disable_torque")

    def hold(self):
        self.calls.append("hold")

    def current_joints(self):
        self.calls.append("current_joints")
        return dict(self.observed)

    def move_to(self, *args, **kwargs):
        pytest.fail("manual teaching must never move_to")

    def move_joints(self, *args, **kwargs):
        pytest.fail("manual teaching must never move_joints")


@pytest.fixture
def session(tmp_path):
    result = TeachSession(Robot(), tmp_path / "calib" / "home_path_teaching.json")
    result.station_running = lambda: False
    return result


def capture_both(session):
    session.release(True)
    session.capture("home")
    session.robot.observed = joints(20)
    session.capture("lower")


def test_creation_and_status_never_connect_or_move(session):
    state = session.snapshot()
    assert session.robot.calls == []
    assert not state["connected"] and not state["free"] and not state["saved"]
    assert state["home"] is state["lower"] is state["file"] is None
    assert state["hardware_motion_validated"] is False and state["warning"]


@pytest.mark.parametrize("supported", [False, None, 1, "true"])
def test_release_requires_explicit_true_before_connect(session, supported):
    with pytest.raises(ValueError):
        session.release(supported)
    assert session.robot.calls == [] and session.connected is False


def test_running_station_blocks_second_robot_connection(session):
    session.station_running = lambda: True
    with pytest.raises(ValueError):
        session.release(True)
    assert session.robot.calls == [] and not session.connected


def test_uncertain_station_status_blocks_robot_connection(session):
    def unknown():
        raise RuntimeError("cannot confirm station is stopped")
    session.station_running = unknown
    with pytest.raises(RuntimeError):
        session.release(True)
    assert session.robot.calls == [] and not session.connected


def test_windows_delayed_refusal_uses_five_second_budget_and_means_stopped(tmp_path, monkeypatch):
    session = TeachSession(Robot(), tmp_path / "manual.json")
    seen = []

    def refused(address, *, timeout):
        seen.append((address, timeout))
        # A real Windows 10061 refusal can arrive after ~2 seconds. No sleep/network here.
        assert timeout >= 5
        raise ConnectionRefusedError(10061, "No connection could be made")

    monkeypatch.setattr(home_teach.socket, "create_connection", refused)
    assert session.station_running() is False
    assert seen == [(("127.0.0.1", 8000), 5)]
    assert not session.robot.calls


def test_station_listener_is_detected_and_probe_socket_closed(tmp_path, monkeypatch):
    session = TeachSession(Robot(), tmp_path / "manual.json")
    seen = []

    class Probe:
        def __enter__(self):
            seen.append("opened")
            return self

        def __exit__(self, *args):
            seen.append("closed")

    def listening(address, *, timeout):
        assert address == ("127.0.0.1", 8000) and timeout >= 5
        return Probe()

    monkeypatch.setattr(home_teach.socket, "create_connection", listening)
    assert session.station_running() is True
    assert seen == ["opened", "closed"] and not session.robot.calls


@pytest.mark.parametrize("error", [TimeoutError("probe timed out"), OSError(10051, "network unavailable")])
def test_probe_timeout_or_unknown_os_error_never_means_stopped(tmp_path, monkeypatch, error):
    session = TeachSession(Robot(), tmp_path / "manual.json")

    def unknown(address, *, timeout):
        assert address == ("127.0.0.1", 8000) and timeout >= 5
        raise error

    monkeypatch.setattr(home_teach.socket, "create_connection", unknown)
    with pytest.raises(RuntimeError) as result:
        session.release(True)
    assert result.value.__cause__ is error
    assert not session.connected and not session.robot.calls


def test_repeated_release_connects_once_and_hold_delegates_to_current_pose(session):
    assert session.release(True)["free"] is True
    assert session.hold()["free"] is False
    assert session.release(True)["free"] is True
    assert session.robot.calls == ["connect", "disable_torque", "hold", "disable_torque"]


def test_station_restart_blocks_even_an_existing_teaching_session(session):
    session.release(True)
    session.station_running = lambda: True
    with pytest.raises(ValueError):
        session.release(True)
    assert session.robot.calls == ["connect", "disable_torque"]


@pytest.mark.parametrize("operation", ["hold", "capture", "save"])
def test_commands_require_explicitly_started_session(session, operation):
    with pytest.raises(ValueError):
        getattr(session, operation)("home") if operation == "capture" else getattr(session, operation)()
    assert session.robot.calls == []


def test_connection_failure_does_not_mark_session_connected(session):
    def disconnected():
        raise OSError("COM unavailable")
    session.robot.connect = disconnected
    with pytest.raises(OSError):
        session.release(True)
    assert not session.connected and not session.free and session.robot.calls == []


@pytest.mark.parametrize("name", ["lower", "pick", "HOME", "../poses.json"])
def test_capture_requires_valid_name_and_home_before_lower(session, name):
    session.release(True)
    with pytest.raises(ValueError):
        session.capture(name)
    assert "current_joints" not in session.robot.calls
    assert session.home is None and session.lower is None


@pytest.mark.parametrize("bad", [
    {key: value for key, value in joints().items() if key != "gripper.pos"},
    {**joints(), "extra.pos": 1.0},
    {**joints(), "wrist_roll.pos": float("nan")},
    {**joints(), "wrist_roll.pos": float("inf")},
    {**joints(), "wrist_roll.pos": True},
    {**joints(), "wrist_roll.pos": "30"},
])
def test_capture_rejects_incomplete_or_nonfinite_observation(session, bad):
    session.release(True)
    session.robot.observed = bad
    with pytest.raises(ValueError):
        session.capture("home")
    assert session.home is None and session.lower is None


def test_raw_out_of_model_bounds_capture_is_not_motion_approval(session):
    session.release(True)
    session.robot.observed = joints(300)
    state = session.capture("home")
    assert state["home"]["joints"] == joints(300)
    assert isinstance(state["home"]["recorded_at"], (int, float))
    assert state["hardware_motion_validated"] is False
    assert state["free"] is True  # Capturing an observation does not alter torque.


def test_recapturing_home_discards_previous_lower_and_save_state(session):
    capture_both(session)
    assert session.save()["saved"] is True
    session.robot.observed = joints(40)
    state = session.capture("home")
    assert state["home"]["joints"] == joints(40)
    assert state["lower"] is None and not state["saved"]
    with pytest.raises(ValueError):
        session.save()


@pytest.mark.parametrize("with_home", [False, True])
def test_save_requires_both_observations(session, with_home):
    session.release(True)
    if with_home:
        session.capture("home")
    with pytest.raises(ValueError):
        session.save()
    assert not session.output_path.exists() and not session.saved


def test_save_writes_raw_pair_without_overwriting_active_poses(session, tmp_path):
    active_poses = tmp_path / "poses.json"
    active_poses.write_bytes(b'{"active": "unchanged"}')
    capture_both(session)
    state = session.save()
    saved = json.loads(session.output_path.read_text(encoding="utf-8"))
    assert saved["schema"] == "pac-home-descent-teaching-v1"
    assert saved["home"]["joints"] == saved["home_joints"] == joints()
    assert saved["lower"]["joints"] == saved["taught_lower_joints"] == joints(20)
    assert saved["robot_id"] == "fake-manual-arm" and saved["hardware_motion_validated"] is False
    assert state["saved"] is True and state["file"] == str(session.output_path)
    assert active_poses.read_bytes() == b'{"active": "unchanged"}'
    assert session.robot.calls == ["connect", "disable_torque", "current_joints", "current_joints"]


def test_save_preserves_previous_teaching_file_in_backup(session):
    session.output_path.parent.mkdir(parents=True)
    previous = b'{"schema":"previous-manual-record"}'
    session.output_path.write_bytes(previous)
    capture_both(session)
    session.save()
    backups = list(session.output_path.parent.glob(session.output_path.name + ".*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == previous
    assert json.loads(session.output_path.read_text())["schema"] == "pac-home-descent-teaching-v1"
    assert not list(session.output_path.parent.glob("*.tmp"))


def test_failed_atomic_replace_keeps_original_record_and_cleans_temp(session, monkeypatch):
    session.output_path.parent.mkdir(parents=True)
    previous = b'{"schema":"previous-manual-record"}'
    session.output_path.write_bytes(previous)
    capture_both(session)

    def denied(source, destination):
        raise OSError("replace denied")
    monkeypatch.setattr(home_teach.os, "replace", denied)
    with pytest.raises(OSError):
        session.save()
    assert session.output_path.read_bytes() == previous and not session.saved
    assert not list(session.output_path.parent.glob("*.tmp"))


def test_api_surfaces_errors_and_never_starts_motion(session):
    client = TestClient(create_app(session))
    assert client.get("/api/status").json()["connected"] is False
    assert client.post("/api/release", json={"supported": False}).status_code == 409
    assert client.get("/api/status").json()["error"]
    assert not session.robot.calls
    assert client.post("/api/release", json={"supported": True}).status_code == 200
    assert client.get("/api/status").json()["error"] is None
    assert client.post("/api/hold").status_code == 200
    assert client.post("/api/capture/home").status_code == 200
    session.robot.observed = joints(20)
    assert client.post("/api/capture/lower").status_code == 200
    result = client.post("/api/save")
    assert result.status_code == 200 and result.json()["saved"] is True
    assert result.json()["hardware_motion_validated"] is False
    for unsupported in ("/api/run", "/api/move", "/api/replay"):
        assert client.post(unsupported).status_code == 404
