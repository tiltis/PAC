"""120 synthetic frames, a missing hand, and recovery requiring manual rearm."""
import json
from pathlib import Path
from control import Controller
from robot_bridge import Bridge, MockBackend


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
        assert controller.enable()
        assert bridge.receive(controller.state(),now[0])
        assert bridge.arm()
        for i in range(120):
            now[0] += 1/30
            controller.update((.5+.2*i/120,.5-.2*i/120),1,now[0])
            assert bridge.receive(controller.state(),now[0])
            assert bridge.step()
        controller.update(None,0,now[0])
        assert not bridge.receive(controller.state(),now[0])
        assert backend.holds == 1
        now[0] += 1/30
        controller.update((.5,.5),1,now[0])
        assert not controller.state()['motion_enabled']
        assert not bridge.enabled
    print(json.dumps(dict(frames=120,commands=len(backend.actions),holds=backend.holds,
                         manual_rearm_required=True,log=str(path),synthetic=True)))


if __name__ == '__main__':
    main()
