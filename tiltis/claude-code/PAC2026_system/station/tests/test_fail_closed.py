import threading

import httpx
import pytest

from robot import MockRobot
from sensor_client import SensorClient
from sequencer import Sequencer


def response(**updates):
    return {"status": "ok", "error": None, "specimen_id": "S01", "face": "A", "attempt": 0,
            "verdict": "no_anomaly", "reasons": [], "features": {}, "images": {},
            "capture_id": "test", "elapsed_ms": 1, **updates}


def client_for(data):
    client = SensorClient("http://fake")
    client._http.close()
    client._http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data)))
    return client


@pytest.mark.parametrize("updates", [
    {"specimen_id": "OTHER"}, {"face": "B"}, {"attempt": 1},
    {"features": [1]}, {"reasons": "rgb_blur"}, {"images": []},
])
def test_sensor_rejects_mismatched_identity_and_malformed_fields(updates):
    client = client_for(response(**updates))
    try:
        result = client.inspect("t", "S01", "A", 0)
        assert result["status"] == "error"
    finally:
        client.close()


def test_no_defect_evidence_goes_to_review_even_without_rules_version():
    class NoEvidence:
        def inspect(self, session, specimen_id, face, attempt):
            return response(specimen_id=specimen_id, face=face, attempt=attempt)
    robot = MockRobot(speed=0)
    result = Sequencer(robot, NoEvidence()).run("S01", "t")
    assert result["final_verdict"] == "review" and result["bin"] == "human"
    assert "bin_ok" not in robot.moves()


def test_status_is_busy_while_save_is_blocked():
    entered = threading.Event()
    release = threading.Event()
    class ReviewSensor:
        def inspect(self, session, specimen_id, face, attempt):
            return response(specimen_id=specimen_id, face=face, attempt=attempt, verdict="review")
    def save(result):
        entered.set()
        assert release.wait(5)
    seq = Sequencer(MockRobot(speed=0), ReviewSensor(), on_finish=save)
    seq.start("S01", "t")
    try:
        assert entered.wait(5)
        status = seq.snapshot()
        assert status["busy"] is True and status["state"] == "saving"
    finally:
        release.set()
        seq.wait(5)
    assert not seq.snapshot()["busy"] and seq.snapshot()["state"] == "done"


@pytest.mark.parametrize("features", [
    {}, {"defect_inspected": True}, {"defect_inspected": "true", "defect_rules_version": "v1"},
    {"defect_inspected": True, "defect_rules_version": " "},
])
def test_incomplete_evidence_never_passes(features):
    class Sensor:
        def inspect(self, session, specimen_id, face, attempt):
            return response(specimen_id=specimen_id, face=face, attempt=attempt, features=features)
    result = Sequencer(MockRobot(speed=0), Sensor()).run("S01", "t")
    assert result["final_verdict"] == "review" and result["bin"] == "human"


def test_synthetic_evidence_cannot_authorize_hardware_robot():
    robot = MockRobot(speed=0)
    robot.is_mock = False  # 실제 장비 연결 없이 실제 장비 모드의 보호를 시험
    class Sensor:
        def inspect(self, session, specimen_id, face, attempt):
            return response(specimen_id=specimen_id, face=face, attempt=attempt,
                features={"defect_inspected": True, "defect_rules_version": "mock-only-0.1", "simulated": True})
    result = Sequencer(robot, Sensor()).run("S01", "t")
    assert result["bin"] == "human" and result["final_verdict"] == "review"
    assert result["inspections"][0]["reasons"] == ["simulated_inspection"]


def test_explicit_defect_inspection_metadata_preserves_positive_route():
    class Sensor:
        def inspect(self, session, specimen_id, face, attempt):
            return response(specimen_id=specimen_id, face=face, attempt=attempt,
                features={"defect_inspected": True, "defect_rules_version": "fixture-defect-1"})
    result = Sequencer(MockRobot(speed=0), Sensor()).run("S01", "t")
    assert result["state"] == "done" and result["final_verdict"] == "no_anomaly" and result["bin"] == "ok"


def test_persistence_transaction_failure_then_repeat_success(tmp_path):
    import copy
    from store import Store
    store = Store(tmp_path / "transactions.db")
    class ReviewSensor:
        def inspect(self, session, specimen_id, face, attempt):
            return response(specimen_id=specimen_id, face=face, attempt=attempt, verdict="review")
    def broken_save(result):
        damaged = copy.deepcopy(result)
        del damaged["inspections"][1]["reasons"]  # 두 번째 INSERT 직전 실패, 첫 INSERT도 롤백되어야 한다.
        store.save_run(damaged)
    seq = Sequencer(MockRobot(speed=0), ReviewSensor(), on_finish=broken_save)
    failed = seq.run("FAILED", "t")
    assert failed["state"] == "error" and "persistence_error" in failed
    assert store.list_runs() == []
    seq.on_finish = store.save_run
    for specimen in ("NEXT1", "NEXT2"):
        result = seq.run(specimen, "t")
        assert result["state"] == "done" and result["bin"] == "human" and not seq.busy
    assert [r["specimen_id"] for r in store.list_runs()] == ["NEXT2", "NEXT1"]
    assert all(len(store.get_inspections(r["id"])) == 2 for r in store.list_runs())
