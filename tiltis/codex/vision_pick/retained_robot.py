"""Attach to an already held SO-101 without changing motor registers.

The previous serial owner must first release its port while preserving torque.
This attachment verifies retained state; it does not validate a motion path.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from robot import JOINT_KEYS, RobotError, So101Robot, load_poses


_spec = importlib.util.spec_from_file_location(
    "pac_retained_robot_status", Path(__file__).resolve().parents[1] / "tools" / "robot_status.py"
)
if _spec is None or _spec.loader is None:
    raise ImportError("Cannot load the inspected SO-101 status reader")
_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_status)
make_reader = _status.make_reader
_valid_sample = _status._valid_sample
_MOTORS = {key.removesuffix(".pos") for key in JOINT_KEYS}


class RetainedSo101Robot(So101Robot):
    """Keep the preceding hold's torque, goals, PID and calibration unchanged."""

    def connect(self) -> None:
        if self._robot is not None:
            raise RobotError("이미 연결된 로봇은 다시 연결하지 않습니다")
        if self.poses_path.exists():
            self.poses = load_poses(self.poses_path)
        reader = None
        owns_bus = False
        try:
            # Shared reader pins the audited SDK and disables torque-off cleanup.
            reader = make_reader(self.port, self.robot_id)
            bus = reader.bus
            if bus.is_connected:
                raise RobotError("이미 열린 버스는 점유하거나 닫지 않습니다")
            if set(bus.motors) != _MOTORS:
                raise RobotError("SO-101의 여섯 모터 구성이 일치하지 않습니다")
            owns_bus = True  # A failed handshake can still leave the port open.
            bus.connect(handshake=True)
            if not bus.is_calibrated:
                raise RobotError("모터 보정이 파일과 일치하지 않습니다")
            torque = _valid_sample(bus.sync_read("Torque_Enable", normalize=False), _MOTORS,
                                   "Torque_Enable")
            if any(value != 1 for value in torque.values()):
                raise RobotError("모든 모터가 이미 토크 고정된 상태여야 합니다")
            modes = _valid_sample(bus.sync_read("Operating_Mode", normalize=False), _MOTORS,
                                  "Operating_Mode")
            if any(value != 0 for value in modes.values()):  # Audited Feetech POSITION = 0.
                raise RobotError("모든 모터가 위치 제어 모드여야 합니다")
            joints = _valid_sample(bus.sync_read("Present_Position", normalize=True), _MOTORS,
                                   "Present_Position")
            self._target = {key + ".pos": float(value) for key, value in joints.items()}
            self._robot = reader
        except Exception as exc:
            cleanup_error = None
            if owns_bus and reader is not None and reader.bus.is_connected:
                try:
                    reader.bus.disconnect(disable_torque=False)
                except Exception as close_exc:
                    cleanup_error = close_exc
            self._robot = None
            self._target = {}
            detail = f"; 포트 닫기 실패: {cleanup_error}" if cleanup_error else ""
            raise RobotError(f"기존 고정 상태 연결 실패: {exc}{detail}") from exc

    def disconnect(self) -> None:
        reader, self._robot = self._robot, None
        self._target = {}
        if reader is not None and reader.bus.is_connected:
            reader.bus.disconnect(disable_torque=False)
