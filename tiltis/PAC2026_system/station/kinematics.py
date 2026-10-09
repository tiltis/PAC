"""SO-101 정기구학·역기구학 (numpy만 사용). URDF: assets/so101_new_calib.urdf.

- 각도는 라디안, 길이는 m, 좌표는 로봇 base_link 기준.
- 도구 기준점은 gripper_frame_link(집게 끝). 이 프레임의 z축이 손가락이 뻗는 방향(접근 방향),
  x축이 집게가 닫히는 방향이다(URDF 관절 구조에서 계산).
- 위에서 내려 집기: 접근 방향 = 아래(-z), 집게 닫힘 방향을 상자의 잡을 변에 맞춘다(yaw).
- LeRobot 관절값(use_degrees=True의 도)과 URDF 각도의 대응은 기본 1:1로 둔다. LeRobot의 SO-101 IK 예제와 같은
  가정이며, 현장에서 자 측정으로 확인하기 전까지는 가정이다(joint_map으로 부호·오프셋 보정 가능).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

URDF = Path(__file__).parent / "assets" / "so101_new_calib.urdf"
ARM_JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
TOOL = "gripper_frame_link"

# 공식 CAD(STL)로 계산한 그리퍼 관절각(rad) → 움직이는 집게 끝과 고정 집게 사이 거리(mm).
# 상자를 비스듬한 집게로 누르는 실제 파지 폭은 이보다 작다. 공개 사양이 아니라 계산값이다.
GRIPPER_CLEARANCE = [(-0.17, 3.1), (-0.05, 12.6), (0.07, 22.5), (0.19, 32.4), (0.31, 42.2), (0.43, 51.8),
                     (0.55, 61.2), (0.67, 70.1), (0.79, 78.5), (0.91, 86.6), (1.03, 94.5), (1.15, 101.8),
                     (1.27, 107.4), (1.39, 112.4), (1.51, 117.1), (1.63, 121.3), (1.75, 125.0)]


def _rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _axis_angle(axis, q):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(q) * K + (1 - np.cos(q)) * K @ K


@dataclass
class _Joint:
    name: str
    kind: str
    parent: str
    child: str
    origin: np.ndarray
    axis: np.ndarray
    lower: float
    upper: float


class SO101:
    def __init__(self, urdf=URDF, tip=TOOL):
        root = ET.parse(urdf).getroot()
        joints = {}
        for j in root.findall("joint"):
            o = j.find("origin")
            T = np.eye(4)
            T[:3, :3] = _rpy(*map(float, o.get("rpy", "0 0 0").split()))
            T[:3, 3] = list(map(float, o.get("xyz", "0 0 0").split()))
            ax = j.find("axis")
            lim = j.find("limit")
            joints[j.find("child").get("link")] = _Joint(
                j.get("name"), j.get("type"), j.find("parent").get("link"), j.find("child").get("link"), T,
                np.array(list(map(float, ax.get("xyz").split()))) if ax is not None else np.zeros(3),
                float(lim.get("lower")) if lim is not None else -np.inf, float(lim.get("upper")) if lim is not None else np.inf)
        chain, link = [], tip
        while link in joints:
            chain.append(joints[link])
            link = joints[link].parent
        self.chain = chain[::-1]  # base_link → tip
        movable = [j.name for j in self.chain if j.kind == "revolute"]
        if movable != ARM_JOINTS:
            raise ValueError(f"예상과 다른 관절 순서: {movable}")
        self.lower = np.array([j.lower for j in self.chain if j.kind == "revolute"])
        self.upper = np.array([j.upper for j in self.chain if j.kind == "revolute"])

    def fk(self, q):
        """q: 길이 5(ARM_JOINTS 순서, rad) → 4x4 base_link→도구 변환."""
        T, i = np.eye(4), 0
        for j in self.chain:
            T = T @ j.origin
            if j.kind == "revolute":
                R = np.eye(4)
                R[:3, :3] = _axis_angle(j.axis, q[i])
                T = T @ R
                i += 1
        return T

    def _residual(self, q, pos, down, yaw_axis, w_rot):
        T = self.fk(q)
        r = [T[:3, 3] - pos]
        if down is not None:
            r.append(w_rot * np.cross(T[:3, 2], down))  # 접근 방향 오차
        if yaw_axis is not None:
            x = T[:3, 0] - np.dot(T[:3, 0], down) * down  # 닫힘 방향을 수평면에 투영
            n = np.linalg.norm(x)
            if n > 1e-9:
                r.append(w_rot * np.array([np.dot(np.cross(x / n, yaw_axis), down)]))  # 수평면 안에서 각도 차이
        return np.concatenate(r)

    def ik(self, pos, down=(0, 0, -1), yaw=None, q0=None, iters=200, w_rot=0.05, tol_mm=1.0, tol_deg=2.0, seeds=8, rng=0):
        """도구 위치 pos(m), 접근 방향 down, 닫힘 방향 수평각 yaw(rad, base x축 기준; 집게는 180° 대칭).
        성공하면 관절각(rad, 길이 5), 실패하면 None. 관절 한계를 넘는 해는 버린다."""
        pos = np.asarray(pos, float)
        dn = None if down is None else np.asarray(down, float) / np.linalg.norm(down)
        ya = None if yaw is None else np.array([np.cos(yaw), np.sin(yaw), 0.0])
        g = np.random.default_rng(rng)
        starts = [np.zeros(5) if q0 is None else np.asarray(q0, float)]
        pan = np.arctan2(pos[1], pos[0])
        starts += [np.array([pan, s, e, w, 0.0]) for s, e, w in g.uniform(-1.2, 1.2, (seeds, 3))]
        best = None
        for q in starts:
            q = np.clip(q.copy(), self.lower, self.upper)
            for _ in range(iters):
                r = self._residual(q, pos, dn, ya, w_rot)
                J = np.empty((len(r), 5))
                for k in range(5):
                    dq = np.zeros(5)
                    dq[k] = 1e-6
                    J[:, k] = (self._residual(q + dq, pos, dn, ya, w_rot) - r) / 1e-6
                lam = 1e-3
                step = -np.linalg.solve(J.T @ J + lam * np.eye(5), J.T @ r)
                q = np.clip(q + np.clip(step, -0.3, 0.3), self.lower, self.upper)
                if np.linalg.norm(step) < 1e-7:
                    break
            err = self.error(q, pos, dn, ya)
            if best is None or err[0] + err[1] / 10 < best[1][0] + best[1][1] / 10:
                best = (q, err)
            if err[0] <= tol_mm and err[1] <= tol_deg:
                return q
        return None

    def error(self, q, pos, down=None, yaw_axis=None):
        """(위치 오차 mm, 방향 오차 deg)"""
        T = self.fk(q)
        pe = np.linalg.norm(T[:3, 3] - pos) * 1000
        ae = 0.0
        if down is not None:
            ae = max(ae, np.degrees(np.arccos(np.clip(np.dot(T[:3, 2], down), -1, 1))))
        if yaw_axis is not None:
            x = T[:3, 0] - np.dot(T[:3, 0], down) * down
            c = abs(np.dot(x / max(np.linalg.norm(x), 1e-9), yaw_axis))  # 집게는 180° 대칭
            ae = max(ae, np.degrees(np.arccos(np.clip(c, -1, 1))))
        return pe, ae


def gripper_angle_for(width_mm, margin_mm=15.0):
    """상자 폭 + 여유를 지나갈 만큼 벌리는 그리퍼 관절각(rad). 범위를 넘으면 None."""
    target = width_mm + margin_mm
    for (q0, c0), (q1, c1) in zip(GRIPPER_CLEARANCE, GRIPPER_CLEARANCE[1:]):
        if c0 <= target <= c1:
            return q0 + (q1 - q0) * (target - c0) / (c1 - c0)
    return None


JOINT_MAP_PATH = Path(__file__).parent / "calib" / "joint_map.json"


def load_joint_map():
    """현장 자 측정으로 부호·오프셋이 다르다고 확인된 관절만 적는다. 없으면 1:1."""
    import json
    return json.loads(JOINT_MAP_PATH.read_text(encoding="utf-8")) if JOINT_MAP_PATH.exists() else {}


def to_lerobot(q, joint_map=None):
    """URDF 각도(rad) → LeRobot 관절값 dict(도). joint_map: {관절: {"sign": ±1, "offset_deg": x}} (현장 확인 후)."""
    joint_map = joint_map or {}
    out = {}
    for name, v in zip(ARM_JOINTS, q):
        m = joint_map.get(name, {})
        out[f"{name}.pos"] = float(np.degrees(v) * m.get("sign", 1) + m.get("offset_deg", 0.0))
    return out


def from_lerobot(obs, joint_map=None):
    joint_map = joint_map or {}
    q = []
    for name in ARM_JOINTS:
        m = joint_map.get(name, {})
        q.append(np.radians((obs[f"{name}.pos"] - m.get("offset_deg", 0.0)) * m.get("sign", 1)))
    return np.array(q)
