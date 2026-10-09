"""집기 확인: 그리퍼가 끝까지 닫히면(빈손) 검사하지 않고 멈춘다."""
from robot import MockRobot, So101Robot
from sequencer import Sequencer, judge_grasp
from test_sequencer import FakeSensor


def run(**robot_kw):
    robot = MockRobot(speed=0, **robot_kw)
    sensor = FakeSensor()
    return robot, sensor, Sequencer(robot, sensor, settle_timeout_s=0.1).run("S01", "t")


def test_judge_grasp():
    assert judge_grasp(35, 100, 0)[0] is True
    assert judge_grasp(2, 100, 0) == (False, {"pos": 2.0, "frac": 0.02, "threshold_frac": 0.1, "reason": "nothing_held"})
    assert judge_grasp(-3, 100, 0)[1]["reason"] == "nothing_held"          # 닫힘 값보다 더 조여져도 빈손
    assert judge_grasp(95, 100, 0)[1]["reason"] == "gripper_not_closed"
    assert judge_grasp(60, 10, 60)[0] is False and judge_grasp(40, 10, 60)[0] is True  # 열림 값이 더 작은 방향도
    assert judge_grasp(5, 0, 0)[0] is None and judge_grasp(5, None, 0)[0] is None     # 가르치지 않음
    assert judge_grasp(15, 100, 0, held_v=40)[0] is False                  # 물린 값 40 → 기준 20
    assert judge_grasp(25, 100, 0, held_v=40)[0] is True


def test_holding_runs_and_records_checks():
    robot, sensor, r = run()
    assert r["state"] == "done" and r["bin"] == "ok"
    assert [c["where"] for c in r["grasp_checks"]] == ["pick", "lift", "face_A", "face_B"]
    assert all(c["holding"] for c in r["grasp_checks"])


def test_missed_grasp_stops_before_any_inspection():
    robot, sensor, r = run(fail_on={"grasp_miss"})
    assert r["state"] == "error" and "집기 실패(pick)" in r["error"] and "nothing_held" in r["error"]
    assert sensor.calls == [] and robot.stopped
    assert robot.moves() == ["home", "pick_approach", "pick"]               # 빈손으로 들어 올리지 않는다
    assert r["bin"] is None and r["final_verdict"] is None


def test_drop_during_move_stops_before_that_face():
    robot, sensor, r = run(fail_on={"drop:face_B"})
    assert r["state"] == "error" and "집기 실패(face_B)" in r["error"]
    assert sensor.calls == [("A", 0)]                                       # B는 빈 화면을 찍지 않는다
    assert r["bin"] is None


def test_robot_without_reading_is_refused():
    class NoReading(MockRobot):
        is_mock = False

        def gripper_reading(self):
            raise NotImplementedError

    robot = NoReading(speed=0)
    r = Sequencer(robot, FakeSensor(), settle_timeout_s=0.1).run("S01", "t")
    assert r["state"] == "error" and "집기 확인 불가" in r["error"]


def test_untaught_gripper_on_real_robot_is_refused():
    class Untaught(MockRobot):
        is_mock = False

        def gripper_reading(self):
            return {"pos": 0.0, "open": 0.0, "closed": 0.0, "held": None}  # poses.example.json 그대로

    robot = Untaught(speed=0)
    sensor = FakeSensor()
    r = Sequencer(robot, sensor, settle_timeout_s=0.1).run("S01", "t")
    assert r["state"] == "error" and "gripper_untaught" in r["error"] and "teach.py" in r["error"]
    assert sensor.calls == [] and r["grasp_checks"][0]["holding"] is None


def test_so101_reading_waits_until_gripper_stops():
    robot = So101Robot(port="X")
    robot.poses = {"gripper": {"open": 80.0, "closed": 2.0, "held": 30.0}}
    seq = iter([60.0, 40.0, 31.0, 30.2, 30.1, 30.0, 30.0, 30.0])
    robot._robot = object()
    robot.current_joints = lambda: {"gripper.pos": next(seq)}
    r = robot.gripper_reading(timeout_s=2.0)
    assert abs(r["pos"] - 30.0) < 0.3 and r["closed"] == 2.0 and r["held"] == 30.0
