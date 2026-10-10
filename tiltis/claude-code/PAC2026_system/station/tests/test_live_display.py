"""The display proxy is same-origin and never requests inspection or motion."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[4] / 'codex/vision_pick'))


@pytest.fixture
def display(monkeypatch, tmp_path):
    monkeypatch.setenv('PICK_MODE', 'taught')
    from app import create_app
    import app as station
    from robot import MockRobot

    frame = np.full((360, 1506, 3), 225, np.uint8)
    cv2.rectangle(frame, (50, 210), (185, 345), (0, 0, 255), -1)
    cv2.rectangle(frame, (295, 210), (430, 345), (255, 0, 0), -1)
    brown = tuple(int(x) for x in cv2.cvtColor(np.uint8([[[15, 115, 180]]]), cv2.COLOR_HSV2BGR)[0, 0])
    cv2.rectangle(frame, (225, 200), (285, 265), brown, -1)
    ok, encoded = cv2.imencode('.jpg', frame)
    assert ok

    class Sensor:
        result = (encoded.tobytes(), 'image/jpeg')
        calls = []

        def fetch_image(self, path):
            self.calls.append(path)
            return self.result

        def close(self):
            pass

    sensor = Sensor()
    monkeypatch.setattr(station, 'SensorClient', lambda _: sensor)
    application = create_app(robot=MockRobot(speed=0), db_path=tmp_path / 'display.db')
    with TestClient(application) as client:
        yield client, sensor


def test_raw_live_image_is_unchanged_and_has_no_overlay(display):
    client, sensor = display
    response = client.get('/sensor-live', params={'specimen_id': 'S01'})
    assert response.status_code == 200
    assert response.content == sensor.result[0]
    assert 'X-Box-Candidates' not in response.headers
    assert sensor.calls == ['/live.jpg?specimen_id=S01']


def test_boxed_live_image_is_served_from_station_origin(display):
    client, sensor = display
    response = client.get('/sensor-live?boxes=1&specimen_id=S01')
    assert response.status_code == 200
    assert response.headers['X-Box-Candidates'] == '1'
    assert response.headers['content-type'] == 'image/jpeg'
    assert response.content != sensor.result[0]
    assert sensor.calls == ['/live.jpg?specimen_id=S01']


def test_optional_overlay_missing_keeps_camera_available(display, monkeypatch):
    client, sensor = display
    monkeypatch.setitem(sys.modules, 'box_overlay', None)
    response = client.get('/sensor-live?boxes=1')
    assert response.status_code == 200
    assert response.content == sensor.result[0]
    assert response.headers['X-Box-Candidates'] == 'unavailable'


def test_camera_disconnect_does_not_return_previous_successful_frame(display):
    client, sensor = display
    assert client.get('/sensor-live?boxes=1').status_code == 200
    sensor.result = None
    assert client.get('/sensor-live?boxes=1').status_code == 502


def test_bad_specimen_is_rejected_before_sensor_request(display):
    client, sensor = display
    assert client.get('/sensor-live?boxes=1&specimen_id=../other').status_code == 400
    assert sensor.calls == []


def test_invalid_boxed_image_is_not_reported_as_success(display):
    client, sensor = display
    sensor.result = (b'not an image', 'image/jpeg')
    assert client.get('/sensor-live?boxes=1').status_code == 502
