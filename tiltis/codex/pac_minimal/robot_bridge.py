"""Cartesian bridge with a latched watchdog. SDK access is serialized.

Backend contract: observe(), solve(position, reference, observation), validate(),
send(), hold(). Real hardware is intentionally only available after commissioning.
"""
import argparse
import json
import math
import threading
import time
import urllib.request
from pathlib import Path
from workspace import Workspace


class MockBackend:
    """Synthetic state for software tests; no physical kinematics or collision model."""
    is_mock = True

    def __init__(self, workspace=None):
        self.position = (workspace or Workspace()).center()
        self.actions = []
        self.holds = 0

    def observe(self):
        return dict(joints=dict(zip(('mock_x_m', 'mock_y_m', 'mock_z_m'), self.position)),
                    ee_position_m=list(self.position), ee_rotation=[1,0,0,0,1,0,0,0,1], synthetic=True)

    def solve(self, position, reference, observation):
        return {'position_m': list(position)}

    def validate(self, action, position, reference, observation, dt):
        return True

    def send(self, action):
        self.position = list(action['position_m'])
        self.actions.append(action)
        return action

    def hold(self):
        self.holds += 1
        return dict(position_m=list(self.position))


class Bridge:
    def __init__(self, backend, log=None, clock=time.monotonic, workspace=None):
        self.backend, self.log, self.clock = backend, log, clock
        self.workspace = workspace or Workspace()
        if not backend.is_mock and self.workspace.profile != 'commissioned':
            raise ValueError('Hardware backend requires an explicitly commissioned workspace')
        self.lock = threading.RLock()
        self.enabled = False
        self.reason = 'manual_arm_required'
        self.generation = 0
        self.fresh_at = None
        self.last_frame = None
        self.last_step = None
        self.reference = None
        self.commanded = None
        self.last_state = None

    def record(self, **fields):
        if self.log:
            self.log.write(json.dumps(dict(local_monotonic_s=self.clock(),
                wall_time_ns=time.time_ns(), mock=self.backend.is_mock, **fields), allow_nan=False)+'\n')
            self.log.flush()

    def stop(self, reason):
        with self.lock:
            was_enabled = self.enabled
            self.enabled = False
            self.generation += 1
            self.reason = reason
            if was_enabled:
                try:
                    start = self.clock()
                    held = self.backend.hold()
                    self.record(event='hold', reason=reason, action_sent=held,
                                send_started_s=start, send_finished_s=self.clock())
                except Exception as exc:
                    self.reason = 'hold_failed'
                    self.record(event='hold_failed', reason=reason, error=str(exc),
                                action_sent=getattr(exc,'action_sent',None))

    def watchdog(self):
        with self.lock:
            if self.enabled and (self.fresh_at is None or self.clock()-self.fresh_at > .2):
                self.stop('receiver_timeout')

    def receive(self, state, request_started):
        with self.lock:
            now = self.clock()
            try:
                age = state['frame_age_s']
                frame = state['frame_id']
                p = state['position_m']
                if state['motion_enabled'] is not True:
                    raise ValueError('input_disabled')
                if state.get('coordinate_frame') != 'robot_base' or state.get('units') != 'm':
                    raise ValueError('coordinate_contract')
                if state.get('workspace') != self.workspace.metadata():
                    raise ValueError('workspace_contract')
                if type(frame) is not int or frame < 0:
                    raise ValueError('invalid_frame_id')
                rtt = now-request_started
                if not math.isfinite(rtt) or not 0 <= rtt <= .2 or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age + rtt <= .2:
                    raise ValueError('stale_source')
                if not isinstance(p, list) or len(p) != 3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in p):
                    raise ValueError('invalid_position')
                if not self.workspace.contains(p):
                    raise ValueError('workspace')
                if self.last_frame is not None and frame < self.last_frame:
                    self.last_frame = None
                    raise ValueError('source_restarted')
                if frame != self.last_frame:
                    self.fresh_at = now - age - (now-request_started)
                    self.last_frame = frame
                self.last_state = dict(state, position_m=list(p))
                self.watchdog()
                return True
            except (ValueError, KeyError, TypeError) as exc:
                self.last_state = None
                self.fresh_at = None
                self.stop(str(exc))
                return False

    def arm(self):
        with self.lock:
            if self.enabled:
                return False
            if self.last_state is None or self.fresh_at is None or self.clock()-self.fresh_at > .2:
                return False
            obs = self.backend.observe()
            p = obs['ee_position_m']
            if not self.workspace.contains(p, z_tolerance=.001):
                self.reason = 'initial_ee_outside_workspace_or_fixed_z'
                return False
            if self.clock()-self.fresh_at > .2:
                self.reason = 'stale_during_arm'
                return False
            self.reference = obs
            self.commanded = list(p)
            self.last_step = self.clock()
            self.enabled = True
            self.generation += 1
            self.reason = 'armed'
            self.record(event='arm', observation=obs, workspace=self.workspace.metadata())
            return True

    def step(self):
        with self.lock:
            self.watchdog()
            if not self.enabled or self.last_state is None:
                return False
            generation = self.generation
            observed_at = self.clock()
            try:
                obs = self.backend.observe()
            except Exception as exc:
                self.stop('observation_failed')
                self.record(event='observation_failed', error=str(exc))
                return False
            observed_end = self.clock()
            dt = min(.05, max(0., observed_end-self.last_step))
            # arm() and step() can share a Windows clock tick. No time budget
            # means no command; it is not a failed motion validation.
            if dt == 0:
                return True
            target = self.last_state['position_m']
            delta = [b-a for a,b in zip(self.commanded, target)]
            dist = math.sqrt(sum(x*x for x in delta))
            ratio = min(1., self.workspace.target_speed_m_s*dt/dist) if dist else 0.
            limited = [a+ratio*d for a,d in zip(self.commanded, delta)]
            reference = self.reference
            frame_id = self.last_frame
        # IK and path checking may be slow: neither holds the SDK/control lock.
        try:
            action = self.backend.solve(limited, reference, obs)
            valid = self.backend.validate(action, limited, reference, obs, dt)
            with self.lock:
                self.watchdog()
                if not self.enabled or generation != self.generation:
                    return False
                if self.clock()-observed_at > .2:
                    self.stop('stale_robot_observation')
                    return False
                if not valid:
                    self.stop('motion_validation_failed')
                    return False
                sent_at = self.clock()
                sent = self.backend.send(action)
                sent_end = self.clock()
                self.commanded = limited
                self.last_step = sent_end
                self.record(event='command', source_frame_id=frame_id,
                    observation=obs, observation_started_s=observed_at,
                    observation_finished_s=observed_end, requested_position_m=target,
                    limited_position_m=limited, action_requested=action,
                    action_sent=sent, send_started_s=sent_at, send_finished_s=sent_end)
                self.watchdog()
                return self.enabled
        except Exception as exc:
            self.stop('backend_error')
            with self.lock:
                self.record(event='backend_error', error=str(exc),
                            action_sent=getattr(exc,'action_sent',None))
            return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5001/api/state')
    parser.add_argument('--log', default='logs/bridge.jsonl')
    parser.add_argument('--workspace', default=str(Path(__file__).with_name('workspace.virtual.json')))
    args = parser.parse_args()
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    quitting = threading.Event()
    with path.open('a', encoding='utf-8') as log:
        workspace = Workspace.load(args.workspace)
        bridge = Bridge(MockBackend(workspace), log, workspace=workspace)
        def watch():
            while not quitting.wait(.01):
                bridge.watchdog()
        def console():
            while not quitting.is_set():
                try:
                    command = input('bridge: arm / stop / quit > ').strip().lower()
                    if command == 'arm':
                        try:
                            print('armed' if bridge.arm() else 'arm rejected: '+bridge.reason)
                        except Exception as exc:
                            bridge.stop('arm_observation_failed')
                            print('arm failed: '+str(exc))
                    elif command == 'stop':
                        bridge.stop('manual_stop')
                    elif command == 'quit':
                        bridge.stop('quit')
                        quitting.set()
                except EOFError:
                    return
        threading.Thread(target=watch, daemon=True).start()
        threading.Thread(target=console, daemon=True).start()
        print('MOCK ONLY: synthetic robot state; no serial port is opened.')
        try:
            while not quitting.is_set():
                start = time.monotonic()
                try:
                    with urllib.request.urlopen(args.url, timeout=.08) as response:
                        state = json.load(response)
                    if bridge.receive(state, start):
                        bridge.step()
                except Exception:
                    bridge.stop('receive_failure')
                quitting.wait(max(0., 1/30-(time.monotonic()-start)))
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop('shutdown')
            quitting.set()


if __name__ == '__main__':
    main()
