"""120 synthetic frames, a missing hand, and recovery requiring manual rearm."""
import json
from pathlib import Path
from control import Controller
from robot_bridge import Bridge, MockBackend


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    now = [1.]
    clock = lambda: now[0]
    controller = Controller(clock)
    backend = MockBackend()
    path = Path('logs/replay.jsonl')
    path.parent.mkdir(exist_ok=True)
    with path.open('w',encoding='utf-8') as log:
        bridge = Bridge(backend,log,clock)
        controller.update((.5,.5),1,now[0])
        require(controller.enable(), 'Initial input enable failed')
        require(bridge.receive(controller.state(),now[0]), 'Initial input rejected')
        require(bridge.arm(), 'Initial bridge arm failed')
        for i in range(120):
            now[0] += 1/30
            controller.update((.5+.2*i/120,.5-.2*i/120),1,now[0])
            require(bridge.receive(controller.state(),now[0]), f'Frame {i} rejected')
            require(bridge.step(), f'Frame {i} step failed')
        require(len(backend.actions) == 120, 'Replay must issue exactly 120 synthetic commands')
        controller.update(None,0,now[0])
        require(not bridge.receive(controller.state(),now[0]), 'Missing hand must disable input')
        require(backend.holds == 1, 'Missing hand must hold exactly once')
        now[0] += 1/30
        controller.update((.5,.5),1,now[0])
        require(not controller.state()['motion_enabled'], 'Input must require manual reactivation')
        require(not bridge.enabled, 'Bridge must require manual rearm')
    print(json.dumps(dict(frames=120,commands=len(backend.actions),holds=backend.holds,
                         manual_rearm_required=True,log=str(path),synthetic=True)))


if __name__ == '__main__':
    main()
