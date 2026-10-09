"""Explicit screen-to-robot workspace in base-frame metres."""
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    x: tuple = (.20, .40)
    y: tuple = (-.10, .10)
    z: float = .20
    target_speed_m_s: float = .05
    profile: str = 'virtual'

    def __post_init__(self):
        for bounds in (self.x, self.y):
            if len(bounds) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds) or bounds[0] >= bounds[1]:
                raise ValueError('Workspace bounds must be finite increasing metre values')
        if type(self.z) not in (int, float) or not math.isfinite(self.z):
            raise ValueError('Fixed Z must be finite metres')
        if not math.isfinite(self.target_speed_m_s) or not 0 < self.target_speed_m_s <= .05:
            raise ValueError('Target speed must be positive and <= 0.05m/s')
        if self.profile not in ('virtual', 'commissioned'):
            raise ValueError('Unknown workspace profile')

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('units') != 'm' or data.get('coordinate_frame') != 'robot_base':
            raise ValueError('Workspace requires robot_base frame and metre units')
        return cls(x=tuple(data['x_m']), y=tuple(data['y_m']), z=data['fixed_z_m'],
                   target_speed_m_s=data['target_speed_m_s'], profile=data['profile'])

    def contains(self, position, z_tolerance=1e-8):
        return (len(position) == 3 and
                all(type(v) in (int, float) and math.isfinite(v) for v in position) and
                self.x[0] <= position[0] <= self.x[1] and
                self.y[0] <= position[1] <= self.y[1] and
                abs(position[2]-self.z) <= z_tolerance)

    def center(self):
        return [(self.x[0]+self.x[1])/2, (self.y[0]+self.y[1])/2, self.z]

    def map_wrist(self, u, v):
        return [self.x[1]-(v-.1)/.8*(self.x[1]-self.x[0]),
                self.y[1]-(u-.1)/.8*(self.y[1]-self.y[0]), self.z]

    def metadata(self):
        return dict(profile=self.profile, x_m=list(self.x), y_m=list(self.y),
                    fixed_z_m=self.z, target_speed_m_s=self.target_speed_m_s,
                    coordinate_frame='robot_base', units='m')
