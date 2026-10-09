"""Run the existing station through the user's explicitly taught HOME/lower points."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys


class TaughtPicker:
    def __init__(self, original, teaching):
        self.original, self.teaching = original, copy.deepcopy(teaching)

    def __getattr__(self, name):
        return getattr(self.original, name)

    def validate_home_path_start(self, home):
        from taught_approach import plan_taught_approach
        lower = self.teaching['taught_lower_joints']
        plan_taught_approach(self.teaching, home, lower, lower, self.joint_map)
        return {'ok': True, 'mode': 'taught_home_lower'}

    def plan(self, loc):
        # The former 370 mm minimum was a coarse reach estimate, applied even
        # before the jaw-to-tip correction. Let the existing IK decide whether
        # a nearer box is reachable; retain the configured outer boundary and
        # every downstream joint/approach/height check.
        candidate = copy.copy(self.original)
        candidate.cfg = copy.deepcopy(self.original.cfg)
        old_minimum, maximum = candidate.cfg['side_reach_r_m']
        candidate.cfg['side_reach_r_m'] = [0.0, maximum]
        plan = candidate.plan(loc)
        plan['pick_path_mode'] = 'taught_home_lower'
        plan['strict_vertical'] = False
        plan['reach_policy'] = {'minimum': 'existing_ik', 'previous_minimum_m': old_minimum,
                                'maximum_m': maximum}
        return plan

    def plan_home_path(self, plan, home):
        from taught_approach import plan_taught_approach
        return plan_taught_approach(self.teaching, home, plan['approach'], plan['grasp'], self.joint_map)


def create_taught_app(station_dir=None, teaching_path=None):
    station_dir = Path(station_dir or os.environ.get('PAC_STATION_DIR', 'C:/PAC2026_system/station'))
    os.environ['PAC_SYSTEM_DIR'] = str(station_dir.parent)
    sys.path.insert(0, str(station_dir))
    import app as station
    import kinematics as K
    from retained_robot import RetainedSo101Robot
    from taught_approach import load_teaching, validate_joint_segment
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    teaching_path = Path(teaching_path or station_dir / 'calib/home_path_teaching.json')
    teaching_bytes = teaching_path.read_bytes()
    teaching = load_teaching(teaching_path)

    class TaughtRobot(RetainedSo101Robot):
        def connect(self):
            super().connect()
            joints = self.poses.setdefault('joints', {})
            # This entry point explicitly uses the newly taught HOME for every
            # box choice, without rewriting any original installation poses.
            for name in ['home', 'home_white', 'home_brown']:
                joints[name] = copy.deepcopy(teaching['home_joints'])

        def move_to(self, pose_name, duration_s):
            if pose_name in ('home', 'home_white', 'home_brown'):
                target = self.poses['joints'][pose_name]
                validate_joint_segment(self.current_joints(), target, K.load_joint_map())
                duration_s = self.transfer_duration(target, duration_s)
            return super().move_to(pose_name, duration_s)

    robot = TaughtRobot(os.environ.get('ROBOT_PORT', 'COM8'),
                       os.environ.get('ROBOT_ID', 'so101_follower'),
                       poses_path=station_dir / 'poses.json')
    app = station.create_app(robot=robot)
    seq = app.state.sequencer
    original = getattr(seq.picker, 'original', seq.picker)
    if original is None:
        raise RuntimeError('가르친 경유점 실행은 기존 PICK_MODE=vision 환경이 필요합니다')
    seq.picker = TaughtPicker(original, teaching)
    # The old Cartesian settings must not replace this explicitly selected mode.
    app.routes[:] = [route for route in app.routes if getattr(route, 'path', '') not in ('/', '/api/status', '/pick-path')
                     and not getattr(route, 'path', '').startswith('/api/pick-path/')]

    @app.middleware('http')
    async def taught_file_guard(request, call_next):
        if request.method == 'POST' and request.url.path == '/api/run':
            if teaching_path.read_bytes() != teaching_bytes:
                return JSONResponse({'detail': '가르친 위치가 변경됐습니다. 새 위치를 검증해 다시 연결해 주세요'}, status_code=409)
        return await call_next(request)

    @app.get('/api/status')
    def status():
        return {**seq.snapshot(), 'pick_path_mode': 'taught_home_lower',
                'strict_vertical': False, 'taught_positions_loaded': True}

    @app.get('/api/taught-path')
    def taught_path():
        return {**teaching, 'mode': 'taught_home_lower', 'strict_vertical': False,
                'hardware_motion_validated': False, 'applied_in_memory': True}

    @app.get('/pick-path')
    def path_settings():
        return RedirectResponse('/')

    @app.get('/')
    def index():
        source = (station_dir / 'web/index.html').read_text(encoding='utf-8-sig')
        return HTMLResponse(source)

    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_taught_app(), host='0.0.0.0', port=8000)
