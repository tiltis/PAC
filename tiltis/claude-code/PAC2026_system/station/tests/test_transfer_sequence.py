"""검사 후 바닥을 긁지 않도록 분리한 분류 이동 순서와 실패 시 정지를 검증한다."""
import copy
import threading

import pytest

from robot import JOINT_KEYS, MockRobot, RobotError
from sequencer import Sequencer


def arm_target(marker):
    return {key: float(marker) for key in JOINT_KEYS if key != "gripper.pos"}


def route_plan():
    return {
        "lift": [arm_target(1), arm_target(2)],
        "travel": [arm_target(3), arm_target(4)],
        "lower": [arm_target(5), arm_target(6)],
        "retract": [arm_target(7), arm_target(8)],
        "clearance_m": 0.12,
    }


class Sensor:
    def __init__(self, verdict="no_anomaly"):
        self.verdict = verdict

    def inspect(self, session, specimen_id, face, attempt):
        return {
            "status": "ok", "specimen_id": specimen_id, "face": face,
            "attempt": attempt, "verdict": self.verdict, "reasons": [],
            "features": {"defect_inspected": True, "defect_rules_version": "test-transfer",
                         "simulated": True},
        }


class TransferRobot(MockRobot):
    def __init__(self, *, plan=None, plan_error=None, fail_marker=None,
                 unsettle_marker=None, drop_marker=None, on_waypoint=None, poses=None):
        super().__init__(speed=0, poses=poses)
        self.plan = route_plan() if plan is None else plan
        self.plan_error = plan_error
        self.fail_marker = fail_marker
        self.unsettle_marker = unsettle_marker
        self.drop_marker = drop_marker
        self.on_waypoint = on_waypoint
        self.marker = None
        self.current_target = arm_target(0)

    def plan_transfer(self, pose_name):
        self.calls.append(("plan_transfer", pose_name))
        if self.plan_error:
            raise self.plan_error
        return copy.deepcopy(self.plan)

    def move_to(self, pose_name, duration_s):
        self.marker = None
        super().move_to(pose_name, duration_s)

    def move_joints(self, target, duration_s):
        self.marker = target["shoulder_pan.pos"]
        self.calls.append(("waypoint", self.marker, duration_s))
        if self.marker == self.fail_marker:
            raise RobotError("waypoint failed")
        self.current_target = dict(target)
        if self.marker == self.drop_marker:
            self._holding = False
        if self.on_waypoint:
            self.on_waypoint(self.marker)

    def current_joints(self):
        return dict(self.current_target)

    def moves(self):
        return [call[1] for call in self.calls if call[0] == "move_to"]

    def wait_settled(self, timeout_s):
        self.calls.append(("settled", self.marker))
        return self.marker != self.unsettle_marker if self.marker is not None else True

    def is_still(self):
        # A stationary arm short of the requested height must not be treated as safe.
        self.calls.append(("is_still", None))
        return True


class ReleasePicker:
    dry_run = False

    def __init__(self, robot, release_ok=True):
        self.robot = robot
        self.release_ok = release_ok

    def locate(self):
        return {"found": True, "id": "observed-box"}

    def plan(self, loc):
        return {"ok": True, "approach": arm_target(101), "grasp": arm_target(102),
                "lift": arm_target(103)}

    def capture_held_box(self, loc, joints):
        self.robot.calls.append(("capture_held_box", loc["id"]))
        return {"ok": True}

    def verify_at_release(self, bin_name, joints):
        self.robot.calls.append(("verify_at_release", bin_name, joints))
        return {"ok": self.release_ok, "reason": "test_release_result"}


class VerifyingRobot(TransferRobot):
    def __init__(self, *, bad_stage=None, response=None):
        super().__init__()
        self.bad_stage = bad_stage
        self.response = response

    def verify_transfer_stage(self, stage, plan):
        self.calls.append(("verify_transfer_stage", stage, self.marker))
        assert plan == route_plan()
        return self.response if stage == self.bad_stage else {"ok": True}


def waypoints(robot):
    return [call[1] for call in robot.calls if call[0] == "waypoint" and call[1] < 100]


def release_count(robot):
    return robot.calls.count(("gripper", "open"))


@pytest.mark.parametrize("verdict, bin_name", [("no_anomaly", "ok"), ("suspect", "human")])
def test_lift_travel_lower_release_retract_home_in_both_zones(verdict, bin_name):
    robot = TransferRobot()
    picker = ReleasePicker(robot)
    result = Sequencer(robot, Sensor(verdict), picker=picker).run("S1", "test")
    assert result["state"] == "done", result
    assert result["placed_bin"] == bin_name and result["routing_status"] == "complete"
    assert result["transfer_plan"] == route_plan()
    assert ("plan_transfer", f"bin_{bin_name}") in robot.calls
    assert not any(name.startswith("bin_") for name in robot.moves())
    assert waypoints(robot) == list(range(1, 9))
    assert [(call[1], call[2]) for call in robot.calls if call[0] == "waypoint" and call[1] < 100] == [
        (1, 1), (2, 1), (3, 2), (4, 2), (5, 1.5), (6, 1.5), (7, 1.5), (8, 1.5)]
    lowered = robot.calls.index(("settled", 6))
    assert robot.calls[lowered + 1] == ("verify_at_release", bin_name, arm_target(6))
    assert robot.calls[lowered + 2] == ("gripper", "open")
    assert robot.calls[lowered + 3] == ("waypoint", 7, 1.5)
    assert robot.calls[-2:] == [("settled", 8), ("move_to", "home")]
    assert ("capture_held_box", "observed-box") in robot.calls
    checks = {entry["where"] for entry in result["grasp_checks"]}
    assert {"transfer_lift", "transfer_travel"} <= checks
    assert not any(call[0] == "is_still" for call in robot.calls)


@pytest.mark.parametrize("error", [ValueError("no clearance route"), RobotError("unknown bin pose")])
def test_planning_error_stops_before_any_routing_or_release(error):
    robot = TransferRobot(plan_error=error)
    result = Sequencer(robot, Sensor()).run("FAIL", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == [] and release_count(robot) == 1
    assert result["placed_bin"] is None
    assert not any(name.startswith("bin_") for name in robot.moves())


@pytest.mark.parametrize("bad_plan", [
    {},
    {**route_plan(), "retract": []},
    {**route_plan(), "lower": [dict(arm_target(6), **{"gripper.pos": 100})]},
    {**route_plan(), "travel": [{"shoulder_pan.pos": 3}]},
    {**route_plan(), "lift": [dict(arm_target(1), **{"wrist_roll.pos": float("nan")})]},
    {**route_plan(), "lift": [dict(arm_target(1), **{"wrist_roll.pos": True})]},
    {**route_plan(), "lift": [dict(arm_target(1), **{"wrist_roll.pos": "3"})]},
    {**route_plan(), "metadata": object()},
])
def test_invalid_entire_plan_rejected_before_first_waypoint(bad_plan):
    robot = TransferRobot(plan=bad_plan)
    result = Sequencer(robot, Sensor()).run("BAD", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == [] and release_count(robot) == 1


@pytest.mark.parametrize("duration", [0, -1, float("inf"), "3", True])
def test_invalid_duration_rejected_before_first_waypoint(duration):
    robot = TransferRobot()
    result = Sequencer(robot, Sensor(), durations={"transfer_retract": duration}).run("TIME", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == [] and release_count(robot) == 1


@pytest.mark.parametrize("marker", [1, 4, 5])
def test_routing_move_failure_keeps_gripper_closed(marker):
    robot = TransferRobot(fail_marker=marker)
    result = Sequencer(robot, Sensor()).run("MOVE", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == list(range(1, marker + 1))
    assert release_count(robot) == 1 and result["placed_bin"] is None
    assert robot.moves().count("home") == 1


@pytest.mark.parametrize("marker", [2, 4, 6])
def test_strict_settle_failure_keeps_gripper_closed_even_when_still(marker):
    robot = TransferRobot(unsettle_marker=marker)
    result = Sequencer(robot, Sensor()).run("SETTLE", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == list(range(1, marker + 1))
    assert release_count(robot) == 1 and result["placed_bin"] is None
    assert not any(call[0] == "is_still" for call in robot.calls)


@pytest.mark.parametrize("marker", [2, 4])
def test_lost_grasp_stops_at_lift_or_travel(marker):
    robot = TransferRobot(drop_marker=marker)
    result = Sequencer(robot, Sensor()).run("DROP", "test")
    assert result["state"] == "error" and "nothing_held" in result["error"] and robot.stopped
    assert waypoints(robot) == list(range(1, marker + 1))
    assert release_count(robot) == 1


def test_release_verifier_failure_prevents_open_and_retract():
    robot = TransferRobot()
    result = Sequencer(robot, Sensor(), picker=ReleasePicker(robot, release_ok=False)).run("POSE", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == list(range(1, 7))
    assert release_count(robot) == 1 and result["placed_bin"] is None


def test_actual_position_verified_after_every_settle():
    robot = VerifyingRobot()
    result = Sequencer(robot, Sensor()).run("VERIFY", "test")
    assert result["state"] == "done", result
    for stage, marker in (("lift", 2), ("travel", 4), ("lower", 6), ("retract", 8)):
        index = robot.calls.index(("settled", marker))
        assert robot.calls[index + 1] == ("verify_transfer_stage", stage, marker)
    assert [check["stage"] for check in result["transfer_checks"]] == ["lift", "travel", "lower", "retract"]


@pytest.mark.parametrize("stage, last_marker", [("lift", 2), ("travel", 4), ("lower", 6), ("retract", 8)])
@pytest.mark.parametrize("response", [None, {"ok": False, "reason": "height_short"}, {"ok": 1}])
def test_actual_position_verification_failure_stops(stage, last_marker, response):
    robot = VerifyingRobot(bad_stage=stage, response=response)
    result = Sequencer(robot, Sensor()).run("VERIFYFAIL", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == list(range(1, last_marker + 1))
    assert release_count(robot) == (2 if stage == "retract" else 1)
    assert result["placed_bin"] == ("ok" if stage == "retract" else None)
    assert robot.moves().count("home") == 1


@pytest.mark.parametrize("mode", ["move", "settle"])
def test_retract_failure_records_release_but_does_not_move_home(mode):
    robot = TransferRobot(fail_marker=7 if mode == "move" else None,
                          unsettle_marker=8 if mode == "settle" else None)
    result = Sequencer(robot, Sensor()).run("RETRACT", "test")
    assert result["state"] == "error" and robot.stopped
    assert result["placed_bin"] == "ok" and result["routing_status"] == "error"
    assert release_count(robot) == 2 and robot.moves().count("home") == 1


def test_abort_checked_between_route_waypoints():
    robot = TransferRobot()
    seq = Sequencer(robot, Sensor())
    robot.on_waypoint = lambda marker: seq.request_abort() if marker == 1 else None
    result = seq.run("ABORT", "test")
    assert result["state"] == "aborted" and waypoints(robot) == [1] and robot.stopped
    assert release_count(robot) == 1 and robot.moves().count("home") == 1


def test_pause_checked_between_route_waypoints():
    paused = threading.Event()
    robot = TransferRobot()
    seq = Sequencer(robot, Sensor())

    def pause_after_first(marker):
        if marker == 1:
            seq.request_pause()
            paused.set()

    robot.on_waypoint = pause_after_first
    seq.start("PAUSE", "test")
    try:
        assert paused.wait(3)
        assert waypoints(robot) == [1] and release_count(robot) == 1
        assert seq.snapshot()["paused"] and seq.busy
    finally:
        seq.resume()
        seq.wait(3)
    assert seq.snapshot()["state"] == "done" and waypoints(robot) == list(range(1, 9))


@pytest.mark.parametrize("box_type", ["", "brown"])
def test_plan_receives_selected_box_pose(box_type):
    robot = TransferRobot(poses={"joints": {"bin_ok_brown": arm_target(9)}})
    result = Sequencer(robot, Sensor()).run("VARIANT", "test", box_type=box_type)
    assert result["state"] == "done", result
    assert ("plan_transfer", "bin_ok_brown" if box_type else "bin_ok") in robot.calls


@pytest.mark.parametrize("box_type", ["", "brown"])
def test_legacy_adapter_preserves_taught_bin_retract(box_type):
    up = "bin_ok_up_brown" if box_type else "bin_ok_up"
    robot = MockRobot(speed=0, poses={"joints": {up: arm_target(8)}})
    result = Sequencer(robot, Sensor()).run("OLD", "test", box_type=box_type)
    assert result["state"] == "done", result
    assert robot.calls[-3:] == [("gripper", "open"), ("move_to", up), ("move_to", "home")]
    assert "transfer_plan" not in result


def test_legacy_adapter_accepts_up_after_box_suffix():
    robot = MockRobot(speed=0, poses={"joints": {
        "bin_ok_brown": arm_target(6), "bin_ok_brown_up": arm_target(8), "bin_ok_up": arm_target(9)}})
    result = Sequencer(robot, Sensor()).run("OLDVAR", "test", box_type="brown")
    assert result["state"] == "done", result
    assert robot.calls[-3:] == [("gripper", "open"), ("move_to", "bin_ok_brown_up"), ("move_to", "home")]


def test_transfer_obeys_adapter_minimum_time_without_speeding_up():
    robot = TransferRobot()
    robot.transfer_duration = lambda target, base: base + 2.0
    result = Sequencer(robot, Sensor()).run("SLOW", "test")
    assert result["state"] == "done"
    assert all(call[2] >= 3.0 for call in robot.calls if call[0] == "waypoint")


@pytest.mark.parametrize("invalid", [0, float("nan"), -1])
def test_invalid_rate_time_stops_without_release(invalid):
    robot = TransferRobot()
    robot.transfer_duration = lambda target, base: invalid
    result = Sequencer(robot, Sensor()).run("RATEFAIL", "test")
    assert result["state"] == "error" and robot.stopped
    assert waypoints(robot) == []
    assert release_count(robot) == 1  # Opening before the initial pick only.
