"""Reconnect arm 2 with retained motor state and the installed Claude feeder.

Requires the existing station/feeder_server.py and feeder.py installation.
The previous idle serial owner must release COM10 before this entry starts.
No feed, HOME, gripper or motor configuration command runs at startup.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys

from fastapi import HTTPException


def create_retained_feeder_app(station_dir=None, service=None):
    station_dir = Path(station_dir or os.environ.get('PAC_STATION_DIR', 'C:/PAC2026_system/station'))
    sys.path.insert(0, str(station_dir))
    import feeder_server

    if service is None:
        import feeder
        from retained_robot import RetainedSo101Robot

        port, rid = os.environ['RED_ROBOT_PORT'], os.environ['RED_ROBOT_ID']
        calib_dir = Path(os.environ['RED_CALIB_DIR'])
        cal = calib_dir / (rid + '.json')
        calibration = json.loads(cal.read_text(encoding='utf-8-sig'))
        poses_path = Path(os.environ.get('RED_POSES', str(feeder.DEFAULT_POSES)))
        # Pass the selected arm's calibration without changing process-global
        # ROBOT_CALIB_DIR or copying another arm's default calibration.
        robot = RetainedSo101Robot(port, rid, poses_path=poses_path)
        robot.calibration_dir = calib_dir
        service = feeder_server.FeederService(
            robot, poses_path, int(os.environ.get('FEED_LEVELS', '3')),
            float(os.environ.get('FEED_STEP_MM', '45')),
            Path(os.environ.get('FEED_STATE', str(feeder.DEFAULT_STATE))),
            os.environ.get('SENSOR_URL', 'http://127.0.0.1:8001'),
            os.environ.get('PURPLE_STATION_URL', 'http://127.0.0.1:8000'),
            os.environ.get('FEED_CENTER_CHECK', '1') != '0',
            limits=feeder.joint_limits_deg(calibration))

    app = feeder_server.create_feeder_app(service=service)

    @asynccontextmanager
    async def retained_lifespan(app):
        service.robot.connect()  # Existing attach validates calibration/torque/mode by reading.
        try:
            yield
        finally:
            service.robot.disconnect()  # Preserve torque and goal registers.

    # Replace only startup: retain the installed supply routes and limits, but
    # avoid its SDK connect/configure and automatic hold/torque write.
    app.router.lifespan_context = retained_lifespan

    @app.get('/api/robot/connection')
    def connection():
        with service._lock:
            if service._busy:
                raise HTTPException(409, '2번 로봇 동작 중에는 별도 관절 조회를 하지 않습니다')
            try:
                joints = service.robot.current_joints()
            except Exception as exc:
                raise HTTPException(503, f'2번 로봇 통신 실패: {exc}') from exc
            return {'connected': True, 'port': service.robot.port, 'robot_id': service.robot.robot_id,
                    'joint_positions': joints, 'startup': 'retained_state',
                    'startup_motion': False}

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_retained_feeder_app(), host='0.0.0.0', port=8004)
