"""실기 SO-101 자세 티칭 도구.

사용: python teach.py --port /dev/tty.usbmodemXXXX --id my_follower
  토크를 끄고 손으로 팔을 움직인 뒤, 자세 이름을 입력하고 Enter 하면 현재 관절값을 poses.json에 저장한다.
  python teach.py --replay ...  : 저장된 자세를 천천히 따라 움직여 확인한다.
  python teach.py --fk-check ... : 손으로 집게 끝을 책상 위 여러 점에 대면 계산된 위치(mm)를 보여 준다.
                                  자로 잰 위치와 비교해 관절 각도 대응(부호·오프셋)을 확인한다. 비전 집기 전에 반드시.
  python teach.py --handeye --sensor-url http://<센서 IP>:8001 ... : 카메라·로봇 좌표 맞추기(방식 C)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from robot import (DEFAULT_POSES, POSE_NAMES, RobotError, So101Robot, empty_poses,
                   load_poses, save_poses)

REPLAY_ORDER = ["home", "pick_approach", "pick", "lift", "face_A", "face_B", "bin_ok", "home"]
# gripper_closed: 빈손으로 끝까지 닫은 값(집을 때 이 값으로 조여 쥔다). gripper_held: 손잡이를 물린 채 닫은 값(선택,
# 집기 확인 기준을 정확히 한다). 닫은 뒤 위치가 closed 근처면 놓친 것으로 보고 멈춘다(sequencer.judge_grasp).
GRIPPER_CMDS = {"gripper_open": "open", "gripper_closed": "closed", "gripper_held": "held"}


def teach(robot: So101Robot, poses_path: Path) -> None:
    poses = load_poses(poses_path) if poses_path.exists() else empty_poses()
    robot.disable_torque()
    print("토크 OFF. 팔을 손으로 움직일 수 있다.")
    print("자세 이름:", ", ".join(POSE_NAMES + list(GRIPPER_CMDS)))
    print("빈 줄 또는 q 입력 시 종료.")
    while True:
        name = input("저장할 이름> ").strip()
        if name in ("", "q", "quit"):
            break
        if name not in POSE_NAMES and name not in GRIPPER_CMDS:
            print("  알 수 없는 이름.")
            continue
        joints = robot.current_joints()
        if name in GRIPPER_CMDS:
            poses.setdefault("gripper", {})[GRIPPER_CMDS[name]] = joints["gripper.pos"]
            print(f"  gripper.{GRIPPER_CMDS[name]} = {joints['gripper.pos']:.1f}")
        else:
            poses.setdefault("joints", {})[name] = joints
            print("  저장:", {k: round(v, 1) for k, v in joints.items()})
        save_poses(poses, poses_path)  # 매번 저장해 중간에 끊겨도 남게 한다


def replay(robot: So101Robot, poses_path: Path, duration_s: float = 4.0) -> None:
    robot.poses = load_poses(poses_path)
    robot.enable_torque()
    print("토크 ON. 각 이동 전에 Enter로 확인한다. 위험하면 전원 스위치를 끈다.")
    if input("그리퍼를 열까요? (Enter=예, n=건너뜀) ").strip() != "n":
        robot.set_gripper("open")
    for name in REPLAY_ORDER:
        if input(f"-> {name} 로 이동 (Enter, q=중단) ").strip() == "q":
            break
        robot.move_to(name, duration_s)
        print(f"   도착 안정화: {robot.wait_settled(5.0)}")


def fk_check(robot: So101Robot) -> None:
    import kinematics as K
    model, jm = K.SO101(), K.load_joint_map()
    robot.disable_torque()
    print("토크 OFF. 집게 끝을 책상 위 점에 대고 Enter (q=종료). 로봇 바닥 중심 기준 x=앞, y=왼쪽, z=위 (mm)")
    while input("> ").strip() != "q":
        q = K.from_lerobot(robot.current_joints(), jm)
        p = model.fk(q)[:3, 3] * 1000
        print(f"  집게 끝 x={p[0]:.0f} y={p[1]:.0f} z={p[2]:.0f} mm | 관절(도) " +
              ", ".join(f"{n}={np.degrees(v):.1f}" for n, v in zip(K.ARM_JOINTS, q)))


def calibrate_handeye(robot: So101Robot, sensor_url: str, points: int) -> None:
    import handeye
    import kinematics as K
    from grasp import load_config
    from sensor_client import SensorClient
    model, jm, cfg, sensor = K.SO101(), K.load_joint_map(), load_config(), SensorClient(sensor_url)
    cam, rob = [], []
    print(f"손잡이 붙은 상자를 집기 영역의 서로 다른 {points}곳(넓게)에 차례로 놓는다.")
    while len(cam) < points:
        robot.enable_torque()
        if input(f"[{len(cam) + 1}/{points}] 상자를 놓고 손을 뗀 뒤 Enter (q=중단) ").strip() == "q":
            break
        loc = sensor.locate()
        if not loc.get("found"):
            print("  상자를 못 찾음:", loc.get("reason"), loc.get("rejected", ""))
            continue
        n = np.array(loc["table_normal_cam"])
        c = np.array(loc["top_center_cam_mm"]) - n * cfg["tab_height_mm"] / 2  # 손잡이 높이 가운데
        print(f"  카메라: 손잡이 {loc['top_size_mm']}mm, 중심 {np.round(c, 1).tolist()}")
        robot.disable_torque()
        input("  토크 OFF. 상자를 밀지 않게 그리퍼로 손잡이 가운데를 잡고(손끝이 손잡이 높이 가운데) Enter ")
        q = K.from_lerobot(robot.current_joints(), jm)
        p = model.fk(q)[:3, 3]
        print(f"  로봇: 집게 끝 {np.round(p * 1000, 1).tolist()} mm")
        cam.append(c)
        rob.append(p)
    sensor.close()
    if len(cam) < 4:
        print("점이 4개 미만이라 저장하지 않음")
        return
    res = handeye.fit(cam, rob)
    print(f"RMS {res['rms_mm']}mm, 최대 {res['max_mm']}mm, 점별 {res['residuals_mm']}")
    if res["rms_mm"] > 10:
        print("오차가 10mm를 넘음: 비전 집기 대신 가르친 자세(방식 A)로 시연하는 것을 권장")
    if input("저장할까요? (y/N) ").strip().lower() == "y":
        print("저장:", handeye.save(res, cam, rob))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="lerobot-find-port로 찾은 포트")
    ap.add_argument("--id", default="so101_follower", help="보정할 때 쓴 로봇 id")
    ap.add_argument("--poses", default=str(DEFAULT_POSES))
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--fk-check", action="store_true")
    ap.add_argument("--handeye", action="store_true")
    ap.add_argument("--sensor-url", default="http://127.0.0.1:8001")
    ap.add_argument("--points", type=int, default=6)
    args = ap.parse_args()

    robot = So101Robot(port=args.port, robot_id=args.id, poses_path=Path(args.poses))
    try:
        robot.connect()
        if args.replay:
            replay(robot, Path(args.poses))
        elif args.fk_check:
            fk_check(robot)
        elif args.handeye:
            calibrate_handeye(robot, args.sensor_url, args.points)
        else:
            teach(robot, Path(args.poses))
    except RobotError as e:
        print("오류:", e)
    finally:
        try:
            robot.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
