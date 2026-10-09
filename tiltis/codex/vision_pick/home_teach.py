"""Exclusive, manual HOME/lower observation capture. Never replays a trajectory."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import socket
import sys
import threading
import time
import uuid

KEYS = tuple(n + '.pos' for n in (
    'shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'))


class TeachSession:
    def __init__(self, robot, output_path, station_url='http://127.0.0.1:8000'):
        self.robot, self.output_path = robot, Path(output_path)
        self.connected = self.free = self.saved = False
        self.home = self.lower = None
        self.error = None
        self.lock = threading.RLock()

    def station_running(self):
        try:
            with socket.create_connection(('127.0.0.1', 8000), timeout=1):
                return True
        except ConnectionRefusedError:
            return False
        except OSError as exc:
            raise RuntimeError('검사 서버 종료 여부를 확인할 수 없습니다') from exc

    def snapshot(self):
        with self.lock:
            return dict(connected=self.connected, free=self.free, home=self.home,
                        lower=self.lower, saved=self.saved, error=self.error,
                        file=str(self.output_path) if self.saved else None,
                        hardware_motion_validated=False,
                        warning='두 위치는 가르친 관측값입니다. 저장만으로 자동 이동을 시작하지 않습니다.')

    def release(self, supported):
        with self.lock:
            if supported is not True:
                raise ValueError('빈 집게와 팔을 받친 상태를 확인해 주세요')
            if self.station_running():
                raise ValueError('검사 서버가 로봇을 사용 중입니다. 두 프로그램을 함께 연결할 수 없습니다')
            if not self.connected:
                self.robot.connect()
                self.connected = True
            self.robot.disable_torque()
            self.free = True
            return self.snapshot()

    def _need_connected(self):
        if not self.connected:
            raise ValueError('먼저 팔을 받치고 손으로 움직이기 버튼을 눌러 주세요')

    def hold(self):
        with self.lock:
            self._need_connected()
            self.robot.hold()  # Writes the CURRENT observation before enabling torque.
            self.free = False
            return self.snapshot()

    def capture(self, name):
        with self.lock:
            self._need_connected()
            if name not in ('home', 'lower'):
                raise ValueError('home 또는 lower 위치만 기록할 수 있습니다')
            if name == 'lower' and self.home is None:
                raise ValueError('HOME 위치를 먼저 기록해 주세요')
            raw = self.robot.current_joints()
            if set(raw) != set(KEYS) or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                           or not math.isfinite(v) for v in raw.values()):
                raise ValueError('6개 관절 관측값이 모두 유효해야 합니다')
            sample = {'joints': {k: float(raw[k]) for k in KEYS}, 'recorded_at': time.time()}
            if name == 'home':
                self.home, self.lower = sample, None
            else:
                self.lower = sample
            self.saved = False
            return self.snapshot()

    def save(self):
        with self.lock:
            self._need_connected()
            if self.home is None or self.lower is None:
                raise ValueError('HOME과 아래로 내린 시작 위치를 모두 기록해 주세요')
            result = {'schema': 'pac-home-descent-teaching-v1',
                      'robot_id': getattr(self.robot, 'robot_id', None),
                      'units': {'arm': 'deg', 'gripper': 'lerobot-normalized'},
                      'home': self.home, 'lower': self.lower,
                      'home_joints': self.home['joints'],
                      'taught_lower_joints': self.lower['joints'],
                      'saved_at': time.time(), 'hardware_motion_validated': False}
            path = self.output_path
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                if path.exists():
                    path.with_name(path.name + '.' + uuid.uuid4().hex + '.bak').write_bytes(path.read_bytes())
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            self.saved = True
            return self.snapshot()


def create_app(session):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    app = FastAPI(title='HOME 하강 위치 가르치기')
    app.state.session = session

    def invoke(fn, *args):
        try:
            session.error = None
            return fn(*args)
        except Exception as exc:
            session.error = str(exc)
            raise HTTPException(409, str(exc)) from exc

    @app.get('/')
    def page():
        return FileResponse(Path(__file__).with_suffix('.html'))

    @app.get('/api/status')
    def status():
        return session.snapshot()

    @app.post('/api/release')
    def release(body: dict):
        return invoke(session.release, body.get('supported'))

    @app.post('/api/hold')
    def hold():
        return invoke(session.hold)

    @app.post('/api/capture/{name}')
    def capture(name: str):
        return invoke(session.capture, name)

    @app.post('/api/save')
    def save():
        return invoke(session.save)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--station-dir', type=Path, required=True)
    parser.add_argument('--robot-port', required=True)
    parser.add_argument('--robot-id', default='so101_follower')
    parser.add_argument('--port', type=int, default=8003)
    args = parser.parse_args()
    sys.path.insert(0, str(args.station_dir))
    from robot import So101Robot
    import uvicorn
    robot = So101Robot(args.robot_port, args.robot_id, args.station_dir / 'poses.json')
    session = TeachSession(robot, args.station_dir / 'calib' / 'home_path_teaching.json')
    # Connecting/releasing torque requires the user's explicit button click.
    uvicorn.run(create_app(session), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
