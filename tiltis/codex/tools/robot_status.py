"""SO-101 상태 조회. LeRobot 0.6.1 버스의 ping/read만 사용하며 모터 설정은 쓰지 않는다."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import sys
import time
from pathlib import Path


SUPPORTED_SDK = "0.6.1"


def make_reader(port: str, robot_id: str):
    version = importlib.metadata.version("lerobot")
    if version != SUPPORTED_SDK:
        raise RuntimeError(f"점검한 SDK는 lerobot {SUPPORTED_SDK}; 설치 버전은 {version}")
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    config = SO101FollowerConfig(port=port, id=robot_id, cameras={}, use_degrees=True,
                                 disable_torque_on_disconnect=False)
    return SO101Follower(config)  # 생성만 한다. robot.connect/configure/calibrate는 호출하지 않는다.


def metadata(robot) -> dict:
    return {
        "expected_model": "so101_follower", "port": robot.config.port, "robot_id": robot.id,
        "calibration_file": str(robot.calibration_fpath),
        "calibration_file_exists": Path(robot.calibration_fpath).is_file(),
        "sdk_version": SUPPORTED_SDK, "hardware_queried": False,
        "motion_readiness": "not_verified",
    }


def _valid_sample(values: dict, motors: set, register: str) -> dict:
    if not isinstance(values, dict) or set(values) != motors:
        raise RuntimeError(f"{register}: 관절 응답 누락 또는 잘못된 키")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in values.values()):
        raise RuntimeError(f"{register}: 유효하지 않은 관절 값")
    return dict(values)


def read_status(robot) -> dict:
    """SDK 로봇의 하위 버스만 연결한다. 종료할 때도 기존 토크를 유지한다."""
    bus = robot.bus
    if bus.is_connected:
        raise RuntimeError("이미 열린 버스는 점유하거나 닫지 않는다")
    result = metadata(robot)
    motors = set(bus.motors)
    try:
        bus.connect(handshake=True)  # 기대 모터 ID/모델/펌웨어의 ping/read 확인
        start = time.time()
        raw = _valid_sample(bus.sync_read("Present_Position", normalize=False), motors, "Present_Position")
        result.update(hardware_queried=True, raw_position_ticks=raw,
                      raw_sample_window_s=[start, time.time()])
        torque = _valid_sample(bus.sync_read("Torque_Enable", normalize=False), motors, "Torque_Enable")
        result["torque_enabled"] = torque
        matched = bool(bus.is_calibrated)  # 보정 파일과 모터의 보정 레지스터를 읽어서 비교
        result["calibration_matches_motors"] = matched
        if matched:
            start = time.time()
            joints = _valid_sample(bus.sync_read("Present_Position", normalize=True), motors, "Present_Position")
            result["joint_positions"] = {name + ".pos": value for name, value in joints.items()}
            result["joint_sample_window_s"] = [start, time.time()]
            result["joint_units"] = {name + ".pos": "gripper_0_100" if name == "gripper" else "deg"
                                     for name in joints}
        else:
            result["joint_positions"] = None  # 미보정 tick을 deg/m로 주장하지 않는다.
        return result
    finally:
        # handshake/읽기 실패 후에도 열린 포트를 닫는다. 토크/목표/보정은 변경하지 않는다.
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["so101"], required=True, help="현장에서 확인한 모델")
    parser.add_argument("--port", required=True)
    parser.add_argument("--id", required=True, help="보정에 사용한 로봇 ID")
    parser.add_argument("--metadata-only", action="store_true", help="포트를 열지 않고 SDK/파일만 확인")
    args = parser.parse_args(argv)
    try:
        robot = make_reader(args.port, args.id)
        result = metadata(robot) if args.metadata_only else read_status(robot)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "motion_readiness": "not_verified"}, ensure_ascii=False),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
