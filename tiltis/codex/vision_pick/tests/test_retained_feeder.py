"""Retained feeder startup must bypass the peer's motor-writing startup."""
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retained_feeder import create_retained_feeder_app


@pytest.fixture
def connected(monkeypatch):
    calls = []

    def read():
        calls.append('read')
        return {'shoulder_pan.pos': 12.5}

    robot = SimpleNamespace(port='FAKE', robot_id='arm2', current_joints=read,
                            connect=lambda: calls.append('connect'),
                            disconnect=lambda: calls.append('disconnect'))
    service = SimpleNamespace(robot=robot, _busy=False, _lock=threading.Lock())

    def peer_app(*, service):
        @asynccontextmanager
        async def motor_writing_startup(app):
            pytest.fail('Peer connect/hold must not execute')
            yield

        app = FastAPI(lifespan=motor_writing_startup)

        @app.post('/api/run')
        def preserved_supply_route():
            return {'existing': True}

        return app

    monkeypatch.setitem(sys.modules, 'feeder_server', SimpleNamespace(create_feeder_app=peer_app))
    app = create_retained_feeder_app(service=service)
    yield app, service, calls


def test_startup_does_not_hold_move_or_disable_torque(connected):
    app, _, calls = connected
    with TestClient(app) as client:
        assert calls == ['connect']
        assert client.get('/api/robot/connection').json()['connected'] is True
        assert client.post('/api/run').json() == {'existing': True}
    assert calls == ['connect', 'read', 'disconnect']


def test_busy_refuses_read_without_using_motor_bus(connected):
    app, service, calls = connected
    with TestClient(app) as client:
        service._busy = True
        assert client.get('/api/robot/connection').status_code == 409
        assert calls == ['connect']


def test_disconnected_robot_is_not_reported_as_connected(connected):
    app, service, _ = connected
    def failed_read():
        raise RuntimeError('USB disconnected')
    service.robot.current_joints = failed_read
    with TestClient(app) as client:
        assert client.get('/api/robot/connection').status_code == 503
