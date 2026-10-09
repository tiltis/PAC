"""Normalized wrist input to bounded Cartesian targets (metres)."""
import math
import threading
import time
from workspace import Workspace


class Controller:
    def __init__(self, clock=time.monotonic, workspace=None):
        self.clock = clock
        self.workspace = workspace or Workspace()
        self.lock = threading.RLock()
        self.enabled = False
        self.valid = False
        self.reason = 'manual_enable_required'
        self.position = self.workspace.center()
        self.updated = None
        self.sequence = 0

    def stop(self, reason='manual_stop'):
        with self.lock:
            self.enabled = False
            self.reason = reason

    def update(self, wrist, count, captured_at):
        with self.lock:
            now = self.clock()
            previous = self.updated
            self.updated = captured_at
            self.sequence += 1
            self.valid = False
            if not math.isfinite(captured_at) or not 0 <= now - captured_at <= .2:
                self.stop('stale_frame')
                return
            if count != 1 or wrist is None:
                self.stop('single_hand_required')
                return
            u, v = wrist
            if not all(math.isfinite(x) and .1 <= x <= .9 for x in (u, v)):
                self.stop('outside_input_area')
                return
            self.valid = True
            # Windows Python 3.10 monotonic timestamps can be equal for distinct
            # frames within one clock tick; these yield a zero movement budget.
            if previous is not None and captured_at < previous:
                self.valid = False
                self.stop('capture_time_regression')
                return
            if previous is not None and captured_at - previous > .2:
                self.stop('frame_gap')
            if not self.enabled:
                return
            target = self.workspace.map_wrist(u, v)
            dt = min(.05, max(0., captured_at - previous)) if previous is not None else 0.
            delta = [b-a for a, b in zip(self.position, target)]
            distance = math.sqrt(sum(x*x for x in delta))
            scale = min(1., self.workspace.target_speed_m_s * dt / distance) if distance else 0.
            self.position = [a + scale*d for a, d in zip(self.position, delta)]

    def state(self):
        with self.lock:
            age = self.clock() - self.updated if self.updated is not None else None
            if age is None or not 0 <= age <= .2:
                self.valid = False
                self.stop('stale_frame')
            return dict(position_m=list(self.position), motion_enabled=self.enabled,
                        input_valid=self.valid, reason=self.reason, frame_id=self.sequence,
                        frame_age_s=age, coordinate_frame='robot_base', units='m',
                        workspace=self.workspace.metadata())

    def enable(self):
        with self.lock:
            self.state()
            if not self.valid:
                return False
            self.enabled = True
            self.reason = 'enabled'
            return True
