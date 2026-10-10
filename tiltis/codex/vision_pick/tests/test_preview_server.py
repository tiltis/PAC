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
    app = create_preview_app(tmp_path)
    monkeypatch.setattr(app.state.preview_http, 'get', get)
    client = TestClient(app)
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
    app = create_preview_app(tmp_path)
    monkeypatch.setattr(app.state.preview_http, 'get', unavailable)
    client = TestClient(app)
    assert client.get('/api/inspection-summary').status_code == 503


def test_camera_outlines_one_table_box_without_polling_robot_or_depth_locator(tmp_path, monkeypatch):
    import cv2
    import httpx
    import numpy as np
    image = np.full((360, 1506, 3), 225, np.uint8)
    brown = tuple(int(v) for v in cv2.cvtColor(np.uint8([[[15, 115, 180]]]), cv2.COLOR_HSV2BGR)[0, 0])
    cv2.rectangle(image, (10, 170), (170, 350), (0, 0, 255), -1)
    cv2.rectangle(image, (310, 170), (479, 350), (255, 0, 0), -1)
    cv2.rectangle(image, (200, 190), (280, 270), brown, -1)
    cv2.rectangle(image, (40, 40), (120, 100), brown, -1)
    ok, jpeg = cv2.imencode('.jpg', image)
    assert ok
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        assert url.endswith('/live.jpg')
        assert kwargs['params']['fast'] == 1
        return httpx.Response(200, content=jpeg.tobytes(), request=httpx.Request('GET', url))
    app = create_preview_app(tmp_path)
    monkeypatch.setattr(app.state.preview_http, 'get', get)
    client = TestClient(app)
    result = client.get('/camera.jpg')
    assert result.status_code == 200
    assert result.headers['x-box-candidates'] == '1'
    assert result.headers['x-overlay-role'] == 'display-only-central-white-box'
    assert calls == ['http://127.0.0.1:8001/live.jpg']


def test_camera_failure_after_good_frame_is_not_served_as_cached_video(tmp_path, monkeypatch):
    import cv2
    import httpx
    import numpy as np
    app = create_preview_app(tmp_path)
    _, jpeg = cv2.imencode('.jpg', np.full((360, 1506, 3), 225, np.uint8))
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 1:
            return httpx.Response(200, content=jpeg.tobytes(), request=httpx.Request('GET', args[0]))
        raise httpx.ConnectError('sensor offline')
    monkeypatch.setattr(app.state.preview_http, 'get', unavailable)
    with TestClient(app) as client:
        assert client.get('/camera.jpg').status_code == 200
        assert client.get('/camera.jpg').status_code == 503
    assert len(calls) == 2
    assert app.state.preview_http.is_closed
