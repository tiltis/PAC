"""선택적 홈 수직 하강/전진 경로의 순서, 재시도, 실패 정지 계약."""
import copy
import threading

import pytest

from robot import JOINT_KEYS, MockRobot, RobotError
from sequencer import BusyError, Sequencer


def target(value):
    return {key: float(value) for key in JOINT_KEYS if key != "gripper.pos"}


def home_path(attempt=1):
    first = attempt * 10
    return {"descend": [target(first + 1), target(first + 2)],
            "forward": [target(first + 3), target(first + 4)],
            "metadata": {"transit_floor_m": 0.01}}


class Sensor:
    def inspect(self, session, specimen_id, face, attempt):
        return {"status": "ok", "specimen_id": specimen_id, "face": face, "attempt": attempt,
                "verdict": "review", "reasons": [], "features": {"simulated": True}}


class HomeRobot(MockRobot):
    def __init__(self, *, fail_settle=None, fail_verify=None, first_miss=False, fail_move=None):
        super().__init__(speed=0, poses={"joints": {"home": target(0), "home_brown": target(9)}})
        self.events = []
        self.actual = target(0)
        self.marker = 0
        self.fail_settle = fail_settle
        self.fail_verify = fail_verify
        self.fail_move = fail_move
        self.first_miss = first_miss
        self.closes = 0
        self.on_waypoint = None

    def move_to(self, name, duration_s):
        super().move_to(name, duration_s)
        self.actual = dict(self.poses["joints"].get(name, target(99)))
        self.marker = self.actual["shoulder_pan.pos"]
        self.events.append(("pose", name))

    def move_joints(self, joints, duration_s):
        value = joints["shoulder_pan.pos"]
        self.events.append(("waypoint", value, duration_s))
        if self.fail_move == value:
            raise RobotError("waypoint failure")
        super().move_joints(joints, duration_s)
        self.actual, self.marker = dict(joints), value
        if self.on_waypoint:
            self.on_waypoint(value)

    def current_joints(self):
        return dict(self.actual)

    def set_gripper(self, state):
        super().set_gripper(state)
        self.events.append(("grip", state))
        if state == "closed":
            self.closes += 1
            if self.first_miss and self.closes == 1:
                self._holding = False

    def transfer_duration(self, joints, minimum_s):
        self.events.append(("rate", joints["shoulder_pan.pos"], minimum_s))
        return minimum_s + 0.5

    def wait_settled(self, timeout_s):
        self.events.append(("settle", self.marker))
        return self.marker != self.fail_settle

    def verify_transfer_stage(self, stage, plan):
        self.events.append(("verify", stage, self.marker))
        return {"ok": stage != self.fail_verify and self.actual == plan[stage][-1],
                "reason": "test_actual_position"}


class Picker:
    dry_run = False
    dry_hold_s = 0.0
    dry_stage = "approach"

    def __init__(self, robot, *, configured=True, start_result=None, start_error=None,
                 path_override=None, path_error=None):
        self.robot = robot
        self.configured = configured
        self.start_result = {"ok": True} if start_result is None and configured else start_result
        self.start_error = start_error
        self.path_override = path_override
        self.path_error = path_error
        self.attempt = 0
        self.homes = []

    def validate_home_path_start(self, home):
        self.robot.events.append(("preflight", copy.deepcopy(home)))
        if self.start_error:
            raise self.start_error
        return self.start_result

    def locate(self):
        self.attempt += 1
        return {"found": True, "attempt": self.attempt}

    def plan(self, loc):
        first = loc["attempt"] * 10
        return {"ok": True, "attempt": loc["attempt"], "approach": target(first + 4),
                "grasp": target(first + 5), "lift": target(first + 6)}

    def plan_home_path(self, plan, home):
        self.robot.events.append(("plan_home_path", plan["attempt"]))
        self.homes.append(copy.deepcopy(home))
        if self.path_error:
            raise self.path_error
        if not self.configured:
            return None
        return copy.deepcopy(self.path_override) if self.path_override is not None else home_path(plan["attempt"])

    def capture_held_box(self, loc, joints):
        self.robot.events.append(("capture_held", loc["attempt"]))
        return {"ok": True}


def joint_markers(robot):
    return [event[1] for event in robot.events if event[0] == "waypoint"]


def test_home_descends_then_advances_before_grasp_and_preserves_held_hook():
    robot = HomeRobot()
    picker = Picker(robot)
    result = Sequencer(robot, Sensor(), picker=picker).run("HOME", "test")
    assert result["state"] == "done", result
    assert robot.events[0] == ("preflight", target(0))
    assert robot.events[1] == ("pose", "home")
    assert joint_markers(robot) == [11, 12, 13, 14, 15, 16]
    assert [(event[1], event[2]) for event in robot.events if event[0] == "waypoint"][:4] == [
        (11, 2), (12, 2), (13, 2), (14, 2)]
    assert picker.homes == [target(0)]
    assert result["home_path_plans"][0]["home_start"] == [target(0)]
    assert [check["stage"] for check in result["home_path_checks"]] == ["home_start", "descend", "forward"]
    for stage, marker in (("home_start", 0), ("descend", 12), ("forward", 14)):
        index = robot.events.index(("verify", stage, marker))
        assert robot.events[index - 1] == ("settle", marker)
    assert robot.events.index(("verify", "forward", 14)) < robot.events.index(("grip", "closed"))
    assert ("capture_held", 1) in robot.events
    moves = [step["step"] for step in result["steps"] if step["step"].startswith("move:")]
    assert moves[:4] == ["move:home", "move:home_descend", "move:home_forward", "move:vision_grasp"]


def test_unconfigured_hook_preserves_original_approach_moves():
    robot = HomeRobot()
    result = Sequencer(robot, Sensor(), picker=Picker(robot, configured=False)).run("OLD", "test")
    assert result["state"] == "done", result
    assert joint_markers(robot) == [14, 15, 16]
    assert "home_path_plans" not in result and "home_path_checks" not in result
    assert not any(event[0] == "verify" for event in robot.events)


def test_absent_hooks_preserve_original_approach_moves():
    robot = HomeRobot()
    picker = Picker(robot)
    picker.plan_home_path = None
    picker.validate_home_path_start = None
    result = Sequencer(robot, Sensor(), picker=picker).run("OLD", "test")
    assert result["state"] == "done", result
    assert joint_markers(robot) == [14, 15, 16]
    assert not any(event[0] in ("verify", "preflight", "plan_home_path") for event in robot.events)


@pytest.mark.parametrize("start_result", [{"ok": False, "reason": "home_out_of_limits"}, False, {"ok": 1}])
def test_invalid_preflight_prevents_initial_home_motion(start_result):
    robot = HomeRobot()
    result = Sequencer(robot, Sensor(), picker=Picker(robot, start_result=start_result)).run("BADHOME", "test")
    assert result["state"] == "error" and robot.stopped
    assert robot.moves() == [] and joint_markers(robot) == [] and robot.closes == 0
    assert ("gripper", "open") not in robot.calls


def test_preflight_exception_prevents_initial_home_motion():
    robot = HomeRobot()
    picker = Picker(robot, start_error=ValueError("home wrist out of limit"))
    result = Sequencer(robot, Sensor(), picker=picker).run("BADHOME", "test")
    assert result["state"] == "error" and robot.stopped
    assert robot.moves() == [] and joint_markers(robot) == []


@pytest.mark.parametrize("invalid", [
    {},
    {**home_path(), "descend": []},
    {**home_path(), "forward": []},
    {**home_path(), "forward": [{"shoulder_pan.pos": 14}]},
    {**home_path(), "descend": [{**target(11), "gripper.pos": 0}]},
    {**home_path(), "descend": [{**target(11), "wrist_roll.pos": True}]},
    {**home_path(), "forward": [{**target(14), "wrist_roll.pos": float("nan")}]},
    {**home_path(), "metadata": {}},
    {**home_path(), "metadata": {"transit_floor_m": True}},
])
def test_malformed_path_rejected_before_first_approach_waypoint(invalid):
    robot = HomeRobot()
    result = Sequencer(robot, Sensor(), picker=Picker(robot, path_override=invalid)).run("BADPATH", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == [] and robot.closes == 0
    assert robot.moves() == ["home"]


def test_path_planning_failure_never_falls_back_to_legacy_approach():
    robot = HomeRobot()
    result = Sequencer(robot, Sensor(), picker=Picker(robot, path_error=ValueError("cannot descend"))).run("NOPATH", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == [] and robot.closes == 0


@pytest.mark.parametrize("marker, expected", [(11, [11]), (13, [11, 12, 13])])
def test_home_waypoint_command_failure_stops_without_grasp(marker, expected):
    robot = HomeRobot(fail_move=marker)
    result = Sequencer(robot, Sensor(), picker=Picker(robot)).run("MOVEFAIL", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == expected and robot.closes == 0


@pytest.mark.parametrize("marker, expected", [(0, []), (12, [11, 12]), (14, [11, 12, 13, 14])])
def test_home_start_descend_forward_require_strict_settle(marker, expected):
    robot = HomeRobot(fail_settle=marker)
    robot.is_still = lambda: True
    result = Sequencer(robot, Sensor(), picker=Picker(robot)).run("UNSETTLED", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == expected and robot.closes == 0


@pytest.mark.parametrize("stage, expected", [("home_start", []), ("descend", [11, 12]), ("forward", [11, 12, 13, 14])])
def test_home_start_descend_forward_require_actual_position_verification(stage, expected):
    robot = HomeRobot(fail_verify=stage)
    result = Sequencer(robot, Sensor(), picker=Picker(robot)).run("ACTUAL", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == expected and robot.closes == 0


def test_hardware_cannot_execute_home_path_without_actual_position_verifier():
    robot = HomeRobot()
    robot.is_mock = False
    robot.verify_transfer_stage = None
    result = Sequencer(robot, Sensor(), picker=Picker(robot)).run("NOVERIFIER", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == [] and robot.closes == 0


def test_mock_may_execute_path_without_actual_position_verifier():
    robot = HomeRobot()
    robot.verify_transfer_stage = None
    result = Sequencer(robot, Sensor(), picker=Picker(robot)).run("MOCK", "test")
    assert result["state"] == "done", result
    assert joint_markers(robot) == [11, 12, 13, 14, 15, 16]


def test_retry_replans_home_path_with_fresh_grasp_and_preserves_retreat():
    robot = HomeRobot(first_miss=True)
    picker = Picker(robot)
    result = Sequencer(robot, Sensor(), picker=picker).run("RETRY", "test")
    assert result["state"] == "done", result
    assert joint_markers(robot) == [11, 12, 13, 14, 15, 14, 21, 22, 23, 24, 25, 26]
    assert [event for event in robot.events if event[0] == "plan_home_path"] == [
        ("plan_home_path", 1), ("plan_home_path", 2)]
    assert len(result["home_path_plans"]) == 2
    assert picker.homes == [target(0), target(0)]
    assert ("capture_held", 2) in robot.events and ("capture_held", 1) not in robot.events
    retry_home = [i for i, event in enumerate(robot.events) if event == ("pose", "home")][1]
    assert robot.events[retry_home - 1] == ("waypoint", 14, 2.5)


def test_dry_approach_finishes_after_forward_without_grasp():
    robot = HomeRobot()
    picker = Picker(robot)
    picker.dry_run = True
    result = Sequencer(robot, Sensor(), picker=picker).run("DRY", "test")
    assert result["state"] == "dry_run_done", result
    assert joint_markers(robot) == [11, 12, 13, 14] and robot.closes == 0
    assert robot.moves() == ["home", "home"]  # Existing dry-run return-home behavior.


def test_home_variant_selected_for_start_guard_and_planning():
    robot = HomeRobot()
    picker = Picker(robot)
    result = Sequencer(robot, Sensor(), picker=picker).run("BOXHOME", "test", box_type="brown")
    assert result["state"] == "done", result
    assert robot.events[0] == ("preflight", target(9))
    assert picker.homes == [target(9)]
    assert result["home_path_plans"][0]["home_start"] == [target(9)]


@pytest.mark.parametrize("invalid_time", [0, float("nan"), False, -1])
def test_home_path_rejects_invalid_adapter_duration_before_move(invalid_time):
    robot = HomeRobot()
    robot.transfer_duration = lambda target, minimum_s: invalid_time
    result = Sequencer(robot, Sensor(), picker=Picker(robot)).run("SPEED", "test")
    assert result["state"] == "error" and robot.stopped
    assert joint_markers(robot) == [] and robot.closes == 0


def test_abort_between_home_waypoints_holds_before_next_step():
    robot = HomeRobot()
    seq = Sequencer(robot, Sensor(), picker=Picker(robot))
    robot.on_waypoint = lambda marker: seq.request_abort() if marker == 11 else None
    result = seq.run("ABORT", "test")
    assert result["state"] == "aborted" and robot.stopped
    assert joint_markers(robot) == [11] and robot.closes == 0


def test_pause_between_home_waypoints_blocks_until_resume():
    paused = threading.Event()
    robot = HomeRobot()
    seq = Sequencer(robot, Sensor(), picker=Picker(robot))

    def pause(marker):
        if marker == 11:
            seq.request_pause()
            paused.set()

    robot.on_waypoint = pause
    seq.start("PAUSE", "test")
    try:
        assert paused.wait(3)
        assert joint_markers(robot) == [11] and robot.closes == 0
        assert seq.snapshot()["paused"] and seq.busy
    finally:
        seq.resume()
        seq.wait(3)
    assert seq.snapshot()["state"] == "done"


def test_configuration_mutex_prevents_start_without_mutating_run_state():
    robot = HomeRobot()
    seq = Sequencer(robot, Sensor(), picker=Picker(robot))
    assert seq._configuration_active is False
    with seq._lock:
        seq._configuration_active = True
    with pytest.raises(BusyError):
        seq.run("BUSY", "test")
    assert not seq.busy and seq.snapshot()["current"] is None and not robot.calls
    with seq._lock:
        seq._configuration_active = False
    assert seq.run("READY", "test")["state"] == "done"
