import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from preview_server import create_preview_app


def test_preview_handles_old_sensor_contract_without_motion_or_invented_calibration(tmp_path):
    class Sensor:
        def locate(self): return {"found": False, "reason": "box_not_found"}
    client = TestClient(create_preview_app(tmp_path, sensor=Sensor()))
    assert client.get("/").status_code == 200
    data = client.get("/api/preview").json()
    assert data["motion_enabled"] is False and data["sam_live_connected"] is False
    assert data["readiness"] == {"ok": False, "reason": "handeye_calibration_missing"}
    assert client.post("/api/run").status_code == 404


def test_saved_sam_result_cannot_be_exposed_as_live_or_motion_enabled(tmp_path):
    import json
    result_dir=tmp_path/'sam'; result_dir.mkdir()
    (result_dir/'result.json').write_text(json.dumps({'motion_enabled':True,'robot_ready':True}))
    client=TestClient(create_preview_app(tmp_path,sam_result_dir=result_dir))
    doc=client.get('/api/sam-result').json()
    assert doc['mode']=='saved_photo_only'
    assert doc['motion_enabled'] is doc['robot_ready'] is doc['live_connected'] is False
    assert client.get('/sam-preview.png').status_code==503


def test_reason_script_is_shared_with_station_and_contains_no_motion_routes(tmp_path):
    client = TestClient(create_preview_app(tmp_path))
    script = client.get('/inspection-presentation.js')
    assert script.status_code == 200
    assert 'PacReasons' in script.text
    assert '테이프 ' in script.text and '아랫면 결함' in script.text
    assert '/api/run' not in script.text
    assert client.post('/api/run').status_code == 404


def test_summary_uses_recorded_decision_not_a_newer_unfinished_run(tmp_path, monkeypatch):
    import httpx
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url.endswith('/api/status'):
            data = {'busy': True, 'current': {'specimen_id': 'new'}}
        elif url.endswith('/api/runs'):
            data = [{'id': 8, 'final_verdict': None, 'state': 'error'},
                    {'id': 7, 'final_verdict': 'suspect', 'bin': 'human', 'specimen_id': 'old'}]
        elif url.endswith('/api/runs/7/inspections'):
            data = [{'face':'B', 'reasons':['tape_missing_count_1']}]
        else:
            raise AssertionError(url)
        return httpx.Response(200, json=data, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    client = TestClient(create_preview_app(tmp_path))
    data = client.get('/api/inspection-summary').json()
    assert data['motion_enabled'] is False
    assert data['status']['current']['specimen_id'] == 'new'
    assert data['decision']['specimen_id'] == 'old'
    assert data['decision']['inspections'][0]['reasons'] == ['tape_missing_count_1']
    assert len(calls) == 3 and all('/api/' in url for url in calls)


def test_summary_connection_failure_does_not_return_cached_decision(tmp_path, monkeypatch):
    import httpx
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('station offline')
    monkeypatch.setattr(httpx, 'get', unavailable)
    client = TestClient(create_preview_app(tmp_path))
    assert client.get('/api/inspection-summary').status_code == 503
