"""로봇 제어 인터페이스. MockRobot(테스트/리허설)과 So101Robot(실기)을 제공한다."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_POSES = BASE_DIR / "poses.json"

POSE_NAMES = ["home", "pick_approach", "pick", "lift", "face_A", "face_B", "face_C", "bin_ok", "bin_human"]  # face_C는 FACES=A,B,C일 때만 쓴다
# 상자 종류별 자세: 이름 뒤에 "_white"/"_brown"을 붙여 가르치면(예: pick_white, gripper_held_brown) 검사 시작 때 고른 상자 종류의
# 자세를 쓰고, 없으면 접미사 없는 자세로 돌아간다. 10-09 시편: 흰 70×70×90, 갈색 80×80×45(집는 높이·그리퍼 폭이 다름)
BOX_TYPES = ("white", "brown")


def split_box_suffix(name: str):
    """"pick_white" → ("pick", "white"), "pick" → ("pick", "")"""
    for b in BOX_TYPES:
        if name.endswith("_" + b):
            return name[: -len(b) - 1], b
    return name, ""
JOINT_KEYS = [
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
]


class RobotError(Exception):
    """로봇 동작 실패(연결, 이동, 안정화 등)."""


def load_poses(path: Path = DEFAULT_POSES) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_poses(poses: dict, path: Path = DEFAULT_POSES) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(poses, f, ensure_ascii=False, indent=2)


def empty_poses() -> dict:
    """빈 자세 파일. 가르치지 않은 자세는 넣지 않는다(0° 자리표시가 있으면 move_to가 실제로 0°로 가 버린다, 10-09 현장에서 발견)."""
    return {"_note": "teach.py로 기록. 없는 자세는 move_to에서 오류로 멈춘다", "joints": {}, "gripper": {}}


class RobotBase:
    is_mock = False
    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def move_to(self, pose_name: str, duration_s: float) -> None:
        raise NotImplementedError

    def move_joints(self, target: Dict[str, float], duration_s: float) -> None:
        """관절값(LeRobot 단위)으로 직접 이동. 비전 집기에서 쓴다."""
        raise NotImplementedError

    def set_gripper(self, state: str) -> None:
        raise NotImplementedError

    def wait_settled(self, timeout_s: float) -> bool:
        raise NotImplementedError

    def current_joints(self) -> dict:
        raise NotImplementedError

    def gripper_reading(self) -> dict:
        """집기 확인용: 멈춘 뒤 그리퍼 위치와 가르친 값 {"pos", "open", "closed", "held"}."""
        raise NotImplementedError

    def stop(self) -> None:
        """현재 위치에서 멈춘다(소프트웨어 정지). 물리적 비상정지는 전원 스위치."""
        raise NotImplementedError


class MockRobot(RobotBase):
    """실제 이동 없이 시간만 흘려 보내는 가짜 로봇.

    speed: duration_s에 곱하는 비율(0.1이면 10배 빠르게).
    fail_on: 이 이름의 자세로 move_to 하면 RobotError. "gripper_open"/"gripper_closed"도 가능.
        "grasp_miss": 닫아도 아무것도 안 물림(끝까지 닫힘). "drop:<자세>": 그 자세로 가면 물건을 떨어뜨림.
    settle_ok: False면 wait_settled가 항상 False(안정화 실패 주입).
    """

    is_mock = True

    def __init__(self, poses: Optional[dict] = None, speed: float = 0.1,
                 fail_on: Iterable[str] = (), settle_ok: bool = True):
        self.poses = poses
        self.speed = speed
        self.fail_on = set(fail_on)
        self.settle_ok = settle_ok
        self.calls: list = []  # (동작, 인자) 기록. 테스트에서 확인
        self.stopped = False
        self.connected = False
        self._pose = "unknown"
        self._grip = "unknown"
        self._holding = False

    def connect(self) -> None:
        self.connected = True
        self.calls.append(("connect", None))

    def disconnect(self) -> None:
        self.connected = False
        self.calls.append(("disconnect", None))

    def move_to(self, pose_name: str, duration_s: float) -> None:
        self.calls.append(("move_to", pose_name))
        if pose_name in self.fail_on:
            raise RobotError(f"MockRobot 이동 실패 주입: {pose_name}")
        time.sleep(max(0.0, duration_s * self.speed))
        self._pose = pose_name
        if f"drop:{pose_name}" in self.fail_on:
            self._holding = False

    def move_joints(self, target: Dict[str, float], duration_s: float) -> None:
        self.calls.append(("move_joints", dict(target)))
        if "move_joints" in self.fail_on:
            raise RobotError("MockRobot 관절 이동 실패 주입")
        time.sleep(max(0.0, duration_s * self.speed))
        self._pose = "custom"

    def set_gripper(self, state: str) -> None:
        self.calls.append(("gripper", state))
        if f"gripper_{state}" in self.fail_on:
            raise RobotError(f"MockRobot 그리퍼 실패 주입: {state}")
        time.sleep(0.2 * self.speed)
        self._grip = state
        self._holding = state == "closed" and "grasp_miss" not in self.fail_on

    def wait_settled(self, timeout_s: float) -> bool:
        self.calls.append(("wait_settled", None))
        return self.settle_ok

    def current_joints(self) -> dict:
        if self.poses and self._pose in self.poses.get("joints", {}):
            return dict(self.poses["joints"][self._pose])
        return {k: 0.0 for k in JOINT_KEYS}

    def gripper_reading(self) -> dict:
        # 가짜 값: 열림 100, 빈손 닫힘 0, 손잡이를 물면 35에서 멈춤
        pos = 100.0 if self._grip != "closed" else (35.0 if self._holding else 0.0)
        return {"pos": pos, "open": 100.0, "closed": 0.0, "held": None}

    def stop(self) -> None:
        self.stopped = True
        self.calls.append(("stop", None))

    def moves(self) -> list:
        return [a for c, a in self.calls if c == "move_to"]


class So101Robot(RobotBase):
    """LeRobot SO-101 follower 어댑터. lerobot는 connect() 시점에 import한다.

    '# 현장 확인' 표시는 실기에서만 확인 가능한 LeRobot 호출이다.
    """

    HZ = 30.0

    def __init__(self, port: str, robot_id: str = "so101_follower",
                 poses_path: Path = DEFAULT_POSES, tolerance: float = 2.0):
        self.port = port
        self.robot_id = robot_id
        self.poses_path = Path(poses_path)
        self.tolerance = tolerance
        self.poses: dict = {}
        self._robot = None
        self._target: Dict[str, float] = {}
        self._halt = False
        self._lock = threading.Lock()

    # --- 연결 ---
    def connect(self) -> None:
        try:
            from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig  # 현장 확인
        except ImportError as e:
            raise RobotError(f"lerobot가 설치되어 있지 않다: {e}")
        if self.poses_path.exists():
            self.poses = load_poses(self.poses_path)
        # 비전 집기의 역기구학은 관절값을 도(degree)로 쓴다. 가르친 자세도 같은 단위로 저장되도록 항상 도 단위로 연결한다.
        config = SO101FollowerConfig(port=self.port, id=self.robot_id, use_degrees=True)  # 현장 확인: use_degrees 인자
        self._robot = SO101Follower(config)  # 현장 확인
        try:
            self._robot.connect()  # 현장 확인 (보정 파일이 없으면 보정 절차가 시작될 수 있음)
        except Exception as e:
            raise RobotError(f"SO-101 연결 실패: {e}")

    def disconnect(self) -> None:
        if self._robot is not None:
            self._robot.disconnect()  # 현장 확인
            self._robot = None

    def disable_torque(self) -> None:
        self._robot.bus.disable_torque()  # 현장 확인

    def enable_torque(self) -> None:
        self._robot.bus.enable_torque()  # 현장 확인

    # --- 관측/전송 ---
    def current_joints(self) -> dict:
        self._need_robot()
        obs = self._robot.get_observation()  # 현장 확인: "shoulder_pan.pos" 같은 키의 dict
        return {k: float(v) for k, v in obs.items() if k.endswith(".pos")}

    def _send(self, action: Dict[str, float]) -> None:
        self._robot.send_action(action)  # 현장 확인

    def _need_robot(self) -> None:
        if self._robot is None:
            raise RobotError("로봇이 연결되지 않았다")

    # --- 동작 ---
    def _move_joints(self, target: Dict[str, float], duration_s: float) -> None:
        """현재 위치에서 target까지 관절 공간 선형 보간(약 30Hz)."""
        self._need_robot()
        self._halt = False
        start = self.current_joints()
        keys = list(target.keys())
        steps = max(1, int(duration_s * self.HZ))
        period = 1.0 / self.HZ
        try:
            for i in range(1, steps + 1):
                if self._halt:
                    raise RobotError("정지 요청으로 이동 중단")
                t0 = time.perf_counter()
                r = i / steps
                self._send({k: start.get(k, target[k]) + (target[k] - start.get(k, target[k])) * r
                            for k in keys})
                rest = period - (time.perf_counter() - t0)
                if rest > 0:
                    time.sleep(rest)
        except RobotError:
            raise
        except Exception as e:
            raise RobotError(f"이동 중 오류: {e}")
        self._target.update(target)

    def move_to(self, pose_name: str, duration_s: float) -> None:
        joints = self.poses.get("joints", {})
        if pose_name not in joints:
            raise RobotError(f"poses.json에 자세가 없다: {pose_name}")
        # 그리퍼는 별도 set_gripper로 다루므로 현재 값을 유지한다
        target = {k: v for k, v in joints[pose_name].items() if k != "gripper.pos"}
        self._move_joints(target, duration_s)

    def move_joints(self, target: Dict[str, float], duration_s: float) -> None:
        self._move_joints({k: float(v) for k, v in target.items() if k != "gripper.pos"}, duration_s)

    def set_gripper(self, state: str) -> None:
        if state not in ("open", "closed"):
            raise RobotError(f"알 수 없는 그리퍼 상태: {state}")
        value = self.poses.get("gripper", {}).get(state)
        if value is None:
            raise RobotError(f"poses.json에 gripper.{state} 값이 없다")
        self._move_joints({"gripper.pos": float(value)}, 0.6)

    def gripper_reading(self, timeout_s: float = 1.5) -> dict:
        """그리퍼가 멈출 때까지(연속 3회 변화 < 0.5) 기다린 뒤 위치를 읽는다. 물체에 막히면 그 자리에서 멈춘다."""
        self._need_robot()
        deadline = time.monotonic() + timeout_s
        prev, stable, pos = None, 0, None
        while True:
            pos = float(self.current_joints()["gripper.pos"])
            stable = stable + 1 if prev is not None and abs(pos - prev) < 0.5 else 0
            if stable >= 3 or time.monotonic() > deadline:
                break
            prev = pos
            time.sleep(0.05)
        g = self.poses.get("gripper", {})
        return {"pos": pos, "open": g.get("open"), "closed": g.get("closed"), "held": g.get("held")}

    def wait_settled(self, timeout_s: float) -> bool:
        """모든 관절이 목표 ±tolerance 이내이고 관측값 변화가 멈추면 True."""
        self._need_robot()
        deadline = time.monotonic() + timeout_s
        prev: Optional[Dict[str, float]] = None
        stable = 0
        while time.monotonic() < deadline:
            cur = self.current_joints()
            near = all(abs(cur.get(k, 1e9) - v) <= self.tolerance
                       for k, v in self._target.items() if k != "gripper.pos")
            moving = prev is not None and any(abs(cur[k] - prev.get(k, cur[k])) > 0.3 for k in cur)
            stable = stable + 1 if (near and not moving) else 0
            if stable >= 3:
                return True
            prev = cur
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        """이동 루프를 끊고 현재 위치를 유지한다. 토크는 끄지 않는다(패키지 낙하 방지)."""
        self._halt = True
        try:
            if self._robot is not None:
                self._send(self.current_joints())  # 현장 확인: 현재 위치를 다시 목표로 보내 정지
        except Exception:
            pass


def make_robot(kind: str, port: str = "", robot_id: str = "so101_follower",
               poses_path: Path = DEFAULT_POSES, mock_speed: float = 0.1) -> RobotBase:
    if kind == "so101":
        return So101Robot(port=port, robot_id=robot_id, poses_path=poses_path)
    poses = load_poses(poses_path) if Path(poses_path).exists() else None
    return MockRobot(poses=poses, speed=mock_speed)
