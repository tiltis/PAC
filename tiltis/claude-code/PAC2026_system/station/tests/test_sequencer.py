import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from robot import MockRobot
from sequencer import BusyError, Sequencer


class FakeSensor:
    """script: {(face, attempt): verdict}. 없는 항목은 no_anomaly. 'error'면 센서 오류."""

    def __init__(self, script=None, on_call=None):
        self.script = script or {}
        self.calls = []
        self.on_call = on_call

    def inspect(self, session, specimen_id, face, attempt):
        self.calls.append((face, attempt))
        if self.on_call:
            self.on_call(face, attempt)
        v = self.script.get((face, attempt), "no_anomaly")
        base = {"specimen_id": specimen_id, "face": face, "attempt": attempt,
                "reasons": [], "features": {"defect_inspected": True,
                    "defect_rules_version": "mock-only-0.1", "simulated": True},
                "capture_id": f"{specimen_id}_{face}", "images": {},
                "elapsed_ms": 1}
        if v == "error":
            return {**base, "status": "error", "error": "카메라 오류", "verdict": None}
        return {**base, "status": "ok", "error": None, "verdict": v}


def make(script=None, **robot_kw):
    robot = MockRobot(speed=0, **robot_kw)
    sensor = FakeSensor(script)
    return robot, sensor, Sequencer(robot, sensor, settle_timeout_s=0.1)


def test_all_ok():
    robot, sensor, seq = make()
    r = seq.run("S01", "t")
    assert r["state"] == "done"
    assert r["final_verdict"] == "no_anomaly" and r["bin"] == "ok"
    assert r["retakes_used"] == 0
    assert sensor.calls == [("A", 0), ("B", 0)]
    assert robot.moves() == ["home", "pick_approach", "pick", "lift", "face_A", "face_B",
                             "bin_ok", "home"]
    assert robot.calls[1] == ("gripper", "open") and ("gripper", "closed") in robot.calls
    assert r["elapsed_ms"] >= 0 and r["steps"]


@pytest.mark.parametrize("verdict, bin_name, color, pose, label", [
    ("no_anomaly", "ok", "blue", "bin_ok", "파랑 영역"),
    ("suspect", "human", "red", "bin_human", "빨강 영역"),
    ("review", "human", "red", "bin_human", "빨강 영역"),
    ("unmeasurable", "human", "red", "bin_human", "빨강 영역"),
])
def test_three_face_sorting_to_color_zone_and_release(verdict, bin_name, color, pose, label):
    robot = MockRobot(speed=0)
    sensor = FakeSensor({("C", 0): verdict, ("C", 1): verdict})
    seq = Sequencer(robot, sensor, settle_timeout_s=0.1, faces="A,B,C")
    result = seq.run("COLOR", "mock")
    expected = {"bin": bin_name, "color": color, "pose": pose, "label": label}
    assert result["state"] == "done" and result["destination"] == expected
    assert result["bin"] == result["placed_bin"] == bin_name
    assert result["routing_status"] == "complete"
    assert {face for face, _ in sensor.calls} == {"A", "B", "C"}
    calls = robot.calls
    drop_index = next(i for i, call in enumerate(calls) if call[:2] == ("move_to", pose))
    assert calls[drop_index + 1] == ("gripper", "open")
    assert calls[drop_index + 2][:2] == ("move_to", "home")
    assert [move for move in robot.moves() if move.startswith("bin_")] == [pose]
    snapshot = seq.snapshot()
    assert snapshot["robot_mode"] == "mock"
    assert snapshot["last_result"]["destination"] == expected
    assert snapshot["zones"][bin_name] == {k: v for k, v in expected.items() if k != "bin"}


def test_suspect_on_b_still_inspects_both():
    robot, sensor, seq = make({("B", 0): "suspect"})
    r = seq.run("S02", "t")
    assert r["final_verdict"] == "suspect" and r["bin"] == "human"
    assert sensor.calls == [("A", 0), ("B", 0)]
    assert "bin_human" in robot.moves() and "bin_ok" not in robot.moves()


def test_suspect_on_a_is_not_erased_by_b_ok():
    _, sensor, seq = make({("A", 0): "suspect"})
    r = seq.run("S02", "t")
    assert r["final_verdict"] == "suspect" and r["bin"] == "human"
    assert sensor.calls == [("A", 0), ("B", 0)]


def test_unmeasurable_once_then_ok():
    robot, sensor, seq = make({("A", 0): "unmeasurable"})
    r = seq.run("S03", "t")
    assert r["retakes_used"] == 1
    assert r["final_verdict"] == "no_anomaly" and r["bin"] == "ok"
    assert sensor.calls == [("A", 0), ("A", 1), ("B", 0)]
    m = robot.moves()
    assert m[m.index("face_A"):m.index("face_B")] == ["face_A", "lift", "face_A"]


def test_unmeasurable_twice_and_budget_shared():
    robot, sensor, seq = make({("A", 0): "unmeasurable", ("A", 1): "unmeasurable",
                               ("B", 0): "unmeasurable"})
    r = seq.run("S04", "t")
    assert r["retakes_used"] == 1
    assert r["final_verdict"] == "unmeasurable" and r["bin"] == "human"
    assert sensor.calls == [("A", 0), ("A", 1), ("B", 0)]  # B는 재촬영 없음


def test_sensor_error_stops_without_bin_move():
    robot, sensor, seq = make({("A", 0): "error"})
    r = seq.run("S05", "t")
    assert r["state"] == "error" and "카메라" in r["error"]
    assert robot.stopped
    assert not any(m.startswith("bin_") for m in robot.moves())
    assert sensor.calls == [("A", 0)]
    assert robot.moves()[-1] == "face_A"  # 이후 이동 없음


def test_robot_failure_at_pick():
    robot, sensor, seq = make(fail_on={"pick"})
    r = seq.run("S06", "t")
    assert r["state"] == "error" and "pick" in r["error"]
    assert robot.stopped
    assert robot.moves() == ["home", "pick_approach", "pick"]
    assert sensor.calls == []


def test_settle_timeout_is_error():
    robot, sensor, seq = make(settle_ok=False)
    r = seq.run("S07", "t")
    assert r["state"] == "error" and robot.stopped and sensor.calls == []


def test_pause_blocks_motion_until_resume():
    robot, sensor, seq = make()
    seq.request_pause()
    seq.start("S08", "t")
    time.sleep(0.3)
    assert robot.moves() == []  # 일시정지 중에는 움직이지 않는다
    assert seq.snapshot()["paused"] and seq.busy
    seq.resume()
    seq.wait(5)
    assert seq.snapshot()["state"] == "done" and robot.moves()[0] == "home"


def test_abort_ends_at_step_boundary():
    robot = MockRobot(speed=0)
    holder = {}
    sensor = FakeSensor(on_call=lambda f, a: holder["seq"].request_abort())
    seq = holder["seq"] = Sequencer(robot, sensor)
    r = seq.run("S09", "t")
    assert r["state"] == "aborted"
    assert sensor.calls == [("A", 0)]
    assert not any(m.startswith("bin_") for m in robot.moves())


def test_only_one_run_at_a_time():
    robot, sensor, seq = make()
    seq.request_pause()
    seq.start("S10", "t")
    with pytest.raises(BusyError):
        seq.start("S11", "t")
    seq.request_abort()
    seq.wait(5)


# ---- app.py + mock_sensor (실제 uvicorn으로 모의 센서 서버를 띄운다) ----

@pytest.fixture()
def mock_sensor_url():
    import mock_sensor
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    mock_sensor.state["latency_s"] = 0.0
    server = uvicorn.Server(uvicorn.Config(mock_sensor.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def run_via_api(client, specimen, timeout=10):
    assert client.post("/api/run", json={"specimen_id": specimen, "session": "t"}).status_code == 200
    end = time.time() + timeout
    while time.time() < end:
        st = client.get("/api/status").json()
        if st["state"] in ("done", "error", "aborted") and st["last_result"]:
            return st
        time.sleep(0.1)
    raise AssertionError("시간 초과")


def test_app_end_to_end(mock_sensor_url, tmp_path):
    from app import create_app
    httpx.post(mock_sensor_url + "/mock/scenario", json={"name": "suspect_B"})
    app = create_app(robot=MockRobot(speed=0), sensor_url=mock_sensor_url, db_path=tmp_path / "t.db")
    with TestClient(app) as client:
        st = run_via_api(client, "S01")
        assert st["robot_mode"] == "mock"
        assert st["zones"]["ok"]["color"] == "blue"
        assert st["zones"]["human"]["pose"] == "bin_human"
        assert st["last_result"]["destination"]["color"] == "red"
        assert st["last_result"]["final_verdict"] == "suspect"
        runs = client.get("/api/runs").json()
        assert len(runs) == 1 and runs[0]["specimen_id"] == "S01"
        assert runs[0]["final_verdict"] == "suspect" and runs[0]["bin"] == "human"
        assert "S01" in client.get("/api/runs.csv").text
        assert client.get("/api/sensor/health").json()["ok"] is True
        img = st["last_result"]["inspections"][0]["images"]["rgb"]
        r = client.get("/sensor-img", params={"path": img})
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
        assert client.get("/sensor-img", params={"path": "/health"}).status_code == 400
        assert client.get("/sensor-img", params={"path": "/captures/../x"}).status_code == 400
        assert client.post("/api/pause").status_code == 409  # 실행 중이 아님
        httpx.post(mock_sensor_url + "/mock/scenario", json={"name": "all_ok"})
        st = run_via_api(client, "S02")
        assert st["last_result"]["final_verdict"] == "no_anomaly"
        assert [r["specimen_id"] for r in client.get("/api/runs").json()] == ["S02", "S01"]


def test_app_sensor_error(mock_sensor_url, tmp_path):
    from app import create_app
    httpx.post(mock_sensor_url + "/mock/scenario", json={"name": "sensor_error"})
    robot = MockRobot(speed=0)
    app = create_app(robot=robot, sensor_url=mock_sensor_url, db_path=tmp_path / "t.db")
    with TestClient(app) as client:
        st = run_via_api(client, "S03")
        assert st["state"] == "error" and robot.stopped
        assert client.get("/api/runs").json()[0]["state"] == "error"


def test_decide_never_passes_unknown_verdict():
    import pytest as _pytest
    from sequencer import SequenceError, decide
    assert decide({"A": "no_anomaly", "B": "no_anomaly"}) == ("no_anomaly", "ok")
    with _pytest.raises(SequenceError):
        decide({"A": "no_anomaly", "B": None})
    with _pytest.raises(SequenceError):
        decide({})


@pytest.mark.parametrize("finals", [
    {"A": "no_anomaly"}, {"A": "suspect", "B": None},
    {"A": "unmeasurable", "B": "bogus"},
    {"A": "no_anomaly", "B": "no_anomaly", "C": "no_anomaly"},
])
def test_decide_requires_both_valid_faces(finals):
    from sequencer import SequenceError, decide
    with pytest.raises(SequenceError):
        decide(finals)


@pytest.mark.parametrize("other, expected", [
    ("review", "review"), ("no_anomaly", "review"),
    ("suspect", "suspect"), ("unmeasurable", "unmeasurable"),
])
def test_review_goes_to_human_without_wasting_retake(other, expected):
    robot, sensor, seq = make({("A", 0): "review", ("B", 0): other, ("B", 1): other})
    r = seq.run("REVIEW", "t")
    assert r["state"] == "done" and r["final_verdict"] == expected and r["bin"] == "human"
    assert ("A", 1) not in sensor.calls
    assert "bin_ok" not in robot.moves()
    from advisor import rule_action
    assert rule_action({"verdict": "review"}, 1) == "human"


@pytest.mark.parametrize("sensor_script", [None, {("A", 0): "error"}])
def test_save_failure_is_visible_and_releases_busy(sensor_script):
    robot, sensor, seq = make(sensor_script)
    def fail_save(result):
        assert seq.busy
        raise OSError("disk full")
    seq.on_finish = fail_save
    result = seq.run("SAVE", "t")
    assert result["state"] == "error" and "disk full" in result["persistence_error"]
    assert "기록 저장 실패" in result["error"] and not seq.busy
    assert seq.snapshot()["last_result"] == result
    assert result["events"][-1]["status"] == "error"
    if sensor_script:
        assert "카메라" in result["error"] and result["bin"] is None
    else:
        assert result["bin"] == "ok"  # 이미 완료된 실제 분류 이력은 보존
    seq.on_finish = None
    assert seq.run("NEXT", "t")["state"] in ("done", "error")


def test_app_save_failure_visible_via_status(mock_sensor_url, tmp_path):
    from app import create_app
    httpx.post(mock_sensor_url + "/mock/scenario", json={"name": "all_ok"})
    app = create_app(robot=MockRobot(speed=0), sensor_url=mock_sensor_url, db_path=tmp_path / "fail.db")
    def fail_save(result):
        raise OSError("database unavailable")
    app.state.sequencer.on_finish = fail_save
    with TestClient(app) as client:
        status = run_via_api(client, "FAIL")
        assert status["state"] == "error"
        assert "database unavailable" in status["last_result"]["persistence_error"]
        assert client.get("/api/runs").json() == []


def test_legacy_quality_only_sensor_cannot_route_to_ok():
    class LegacySensor(FakeSensor):
        def inspect(self, *args):
            result = super().inspect(*args)
            result["features"]["rules_version"] = "quality-only-0.2"
            return result
    robot = MockRobot(speed=0)
    result = Sequencer(robot, LegacySensor()).run("LEGACY", "t")
    assert result["final_verdict"] == "review" and result["bin"] == "human"
    assert result["retakes_used"] == 0 and "bin_ok" not in robot.moves()
    assert all(i["sensor_verdict"] == "no_anomaly" for i in result["inspections"])


def test_app_save_blocks_next_run_and_controls_until_committed(mock_sensor_url, tmp_path):
    from app import create_app
    entered, release = threading.Event(), threading.Event()
    httpx.post(mock_sensor_url + "/mock/scenario", json={"name": "all_ok"})
    app = create_app(robot=MockRobot(speed=0), sensor_url=mock_sensor_url, db_path=tmp_path / "save.db")
    def save(result):
        entered.set()
        assert release.wait(5)
        app.state.store.save_run(result)
    app.state.sequencer.on_finish = save
    with TestClient(app) as client:
        assert client.post("/api/run", json={"specimen_id": "FIRST"}).status_code == 200
        try:
            assert entered.wait(5)
            status = client.get("/api/status").json()
            assert status["state"] == "saving" and status["busy"]
            assert client.post("/api/run", json={"specimen_id": "SECOND"}).status_code == 409
            for action in ("pause", "resume", "abort"):
                assert client.post("/api/" + action).status_code == 409
            assert client.get("/api/runs").json() == []
        finally:
            release.set()
            app.state.sequencer.wait(5)
        assert not client.get("/api/status").json()["busy"]
        assert client.get("/api/runs").json()[0]["state"] == "done"
        assert run_via_api(client, "SECOND")["state"] == "done"


@pytest.mark.parametrize("value", ["../other", "a/b", "a\\b", "C:other", "CON", ".hidden", "x.", "x..y"])
def test_station_rejects_bad_identifier_before_robot_motion(tmp_path, value):
    from app import create_app
    robot = MockRobot(speed=0)
    app = create_app(robot=robot, sensor_url="http://127.0.0.1:9", db_path=tmp_path / "invalid.db")
    with TestClient(app) as client:
        for field in ("session", "specimen_id"):
            body = {"specimen_id": "S01", "session": "t", field: value}
            assert client.post("/api/run", json=body).status_code == 422
        assert robot.moves() == [] and not app.state.sequencer.busy


def test_retake_on_a_leaves_no_budget_for_b():
    # A는 재촬영 후 정상, B가 측정 불가여도 포장당 1회 예산을 이미 써서 재촬영하지 않는다
    _, sensor, seq = make({("A", 0): "unmeasurable", ("B", 0): "unmeasurable"})
    r = seq.run("S09", "t")
    assert r["retakes_used"] == 1
    assert sensor.calls == [("A", 0), ("A", 1), ("B", 0)]
    assert r["final_verdict"] == "unmeasurable" and r["bin"] == "human"


def test_retake_available_for_b_when_a_needed_none():
    _, sensor, seq = make({("B", 0): "unmeasurable"})
    r = seq.run("S10", "t")
    assert sensor.calls == [("A", 0), ("B", 0), ("B", 1)]
    assert r["retakes_used"] == 1 and r["final_verdict"] == "no_anomaly"


class FakeAdvisor:
    def __init__(self):
        self.calls = []

    def advise(self, entry, retakes_left):
        self.calls.append((entry["face"], entry["attempt"], retakes_left))
        return {"choice": "human", "mode": "shadow"}  # 규칙과 다른 선택을 해도


def test_advisor_is_shadow_only():
    robot = MockRobot(speed=0)
    sensor = FakeSensor({("A", 0): "unmeasurable"})
    adv = FakeAdvisor()
    r = Sequencer(robot, sensor, settle_timeout_s=0.1, advisor=adv).run("S11", "t")
    assert r["final_verdict"] == "no_anomaly" and r["bin"] == "ok"  # 흐름은 규칙대로
    assert adv.calls == [("A", 0, 1), ("A", 1, 0), ("B", 0, 0)]
    assert all(i["advisor"]["choice"] == "human" for i in r["inspections"])


def test_broken_advisor_does_not_stop_run():
    class Boom:
        def advise(self, entry, retakes_left):
            raise RuntimeError("laya down")
    r = Sequencer(MockRobot(speed=0), FakeSensor(), settle_timeout_s=0.1, advisor=Boom()).run("S12", "t")
    assert r["state"] == "done" and "laya down" in r["inspections"][0]["advisor"]["error"]


def test_laya_advisor_unreachable_and_budget():
    from advisor import LayaAdvisor
    a = LayaAdvisor("http://127.0.0.1:9", timeout_s=0.2)
    out = a.advise({"face": "A", "attempt": 1, "verdict": "unmeasurable", "reasons": ["rgb_blur"]}, 0)
    assert "error" in out and out["allowed"] == ["confirm", "human"] and out["rule_action"] == "human"


def test_sensor_live_proxy(mock_sensor_url, tmp_path):
    from app import create_app
    app = create_app(robot=MockRobot(speed=0), sensor_url=mock_sensor_url, db_path=tmp_path / "t.db")
    with TestClient(app) as client:
        r = client.get("/sensor-live", params={"specimen_id": "S01"})
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
        assert client.get("/sensor-live", params={"specimen_id": "../x"}).status_code == 400


def test_three_faces_inspect_c_and_any_suspect_goes_human():
    # 3면 테이프 검사: FACES=A,B,C → face_C 자세까지 보여 주고, C면만 suspect여도 사람 확인함
    robot = MockRobot(speed=0)
    sensor = FakeSensor({("C", 0): "suspect"})
    seq = Sequencer(robot, sensor, settle_timeout_s=0.1, faces="A,B,C")
    r = seq.run("S3F", "t")
    assert r["state"] == "done" and r["final_verdict"] == "suspect" and r["placed_bin"] == "human", r
    assert [i["face"] for i in r["inspections"]] == ["A", "B", "C"]
    moves = [c[1] for c in robot.calls if c[0] == "move_to"]
    assert moves.index("face_A") < moves.index("face_B") < moves.index("face_C") < moves.index("bin_human")
    assert seq.snapshot()["faces"] == ["A", "B", "C"]


def test_faces_env_rejects_unknown_or_duplicate():
    import pytest as _pt
    from sequencer import SequenceError, decide, parse_faces
    assert parse_faces("a, b ,c") == ("A", "B", "C")
    for bad in ("", "A,A", "A,D", "B,X"):
        with _pt.raises(ValueError):
            parse_faces(bad)
    with _pt.raises(SequenceError):
        decide({"A": "no_anomaly", "B": "no_anomaly"}, ("A", "B", "C"))  # C 빠짐 → 정상 분류 금지


def test_box_type_selects_taught_pose_variant_and_falls_back():
    # 흰/갈색 상자별로 가르친 자세(pick_white 등)가 있으면 그것을 쓰고, 없는 자세는 접미사 없는 것으로 돌아간다
    poses = {"joints": {n: {} for n in ["home", "pick_approach", "pick", "lift", "face_A", "face_B", "bin_ok", "bin_human",
                                        "pick_approach_white", "pick_white", "lift_white"]},
             "gripper": {"open": 100.0, "closed": 0.0, "held_white": 40.0}}
    robot = MockRobot(speed=0, poses=poses)
    r = Sequencer(robot, FakeSensor(), settle_timeout_s=0.1).run("W1", "t", box_type="white")
    assert r["state"] == "done" and r["box_type"] == "white", r
    moves = [c[1] for c in robot.calls if c[0] == "move_to"]
    assert moves[:4] == ["home", "pick_approach_white", "pick_white", "lift_white"]
    assert "face_A" in moves and "pick_brown" not in moves
    assert all(g["threshold_frac"] == 0.2 for g in r["grasp_checks"])  # held_white 40/100 → 기준 절반 0.2
    r2 = Sequencer(MockRobot(speed=0, poses=poses), FakeSensor(), settle_timeout_s=0.1).run("B1", "t", box_type="brown")
    assert r2["state"] == "done"  # brown 자세가 없으면 공통 자세로
