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

from robot import (BOX_TYPES, DEFAULT_POSES, POSE_NAMES, RobotError, So101Robot, empty_poses,
                   load_poses, save_poses, split_box_suffix)
from sequencer import SORTING_ZONES

ZONE_LABELS = {zone["pose"]: zone["label"] for zone in SORTING_ZONES.values()}

REPLAY_ORDER = ["home", "pick_approach", "pick", "lift", "face_A", "face_B", "face_C", "bin_ok", "bin_human", "home"]
# gripper_closed: 빈손으로 끝까지 닫은 값(집을 때 이 값으로 조여 쥔다). gripper_held: 손잡이를 물린 채 닫은 값(선택,
# 집기 확인 기준을 정확히 한다). 닫은 뒤 위치가 closed 근처면 놓친 것으로 보고 멈춘다(sequencer.judge_grasp).
GRIPPER_CMDS = {"gripper_open": "open", "gripper_closed": "closed", "gripper_held": "held"}


GUIDED_ORDER = [  # 10-09 현장: 옆으로 집기(상자 뒤에서), 테이프는 앞면·윗면·아랫면
    ("pick_approach_brown", "갈색 상자 뒤 5cm, 집게 수평으로 벌림, 상자와 같은 높이"),
    ("pick_brown", "앞으로 밀어 상자가 집게 사이에"),
    ("gripper_held_brown", "집게 닫아 상자 문 상태"),
    ("lift_brown", "그대로 10cm 들어 올림"),
    ("face_A", "상자 든 채 앞면이 카메라 정면"),
    ("face_B", "손목 위로 꺾어 윗면이 카메라로"),
    ("face_C", "손목 아래로 꺾어 아랫면이 카메라로"),
    ("bin_ok", "파랑 종이 위 5cm"),
    ("bin_human", "빨강 종이 위 5cm"),
    ("gripper_open", "상자 빼고 집게 9.5cm 이상 벌림"),
    ("gripper_closed", "집게 끝까지 닫음(빈손)"),
    ("pick_approach_white", "흰 상자 뒤 5cm, 집게 수평으로 벌림"),
    ("pick_white", "앞으로 밀어 상자가 집게 사이에"),
    ("gripper_held_white", "집게 닫아 상자 문 상태"),
    ("lift_white", "그대로 10cm 들어 올림"),
]


def _save_one(robot: So101Robot, poses: dict, poses_path: Path, name: str) -> bool:
    base, box = split_box_suffix(name)
    if base not in POSE_NAMES and base not in GRIPPER_CMDS:
        print("  알 수 없는 이름.")
        return False
    joints = robot.current_joints()
    if base in GRIPPER_CMDS:
        key = GRIPPER_CMDS[base] + ("_" + box if box else "")
        poses.setdefault("gripper", {})[key] = joints["gripper.pos"]
        print(f"  gripper.{key} = {joints['gripper.pos']:.1f}")
    else:
        poses.setdefault("joints", {})[name] = joints
        print(f"  저장: {name} ({ZONE_LABELS.get(name, name)})", {k: round(v, 1) for k, v in joints.items()})
    save_poses(poses, poses_path)  # 매번 저장해 중간에 끊겨도 남게 한다
    return True


def guided_teach(robot: So101Robot, poses_path: Path, start: int = 1) -> None:
    """순서대로 이름을 띄워 준다. 팔을 놓고 Enter만 치면 저장. s=건너뜀, r=방금 것 다시, q=종료."""
    poses = load_poses(poses_path) if poses_path.exists() else empty_poses()
    robot.disable_torque()
    print("토크 OFF. 팔을 손으로 움직일 수 있다. 각 단계: 팔 놓고 Enter (s=건너뜀, r=이전 단계 다시, q=종료)")
    i = max(0, start - 1)
    while i < len(GUIDED_ORDER):
        name, hint = GUIDED_ORDER[i]
        ans = input(f"[{i + 1}/{len(GUIDED_ORDER)}] {name}: {hint} → Enter ").strip().lower()
        if ans == "q":
            break
        if ans == "s":
            i += 1
            continue
        if ans == "r":
            i = max(0, i - 1)
            continue
        if _save_one(robot, poses, poses_path, name):
            i += 1
    print("안내 모드 종료. 저장된 자세:", ", ".join(sorted(poses.get("joints", {}))), "| 그리퍼:", poses.get("gripper"))


def teach(robot: So101Robot, poses_path: Path) -> None:
    poses = load_poses(poses_path) if poses_path.exists() else empty_poses()
    robot.disable_torque()
    print("토크 OFF. 팔을 손으로 움직일 수 있다.")
    print("자세 이름:", ", ".join(POSE_NAMES + list(GRIPPER_CMDS)))
    print("상자 종류별 자세: 이름 뒤에 _" + " 또는 _".join(BOX_TYPES) + " (예: pick_approach_white, pick_brown, lift_white, gripper_held_brown).")
    print("  검사 시작 때 고른 상자 종류의 자세를 쓰고, 없으면 접미사 없는 자세를 쓴다.")
    print("분류 위치: bin_ok = 파랑 영역(정상), bin_human = 빨강 영역(불량·확인 필요).")
    print("각 영역에서 상자를 안전하게 내려놓을 자세를 저장한다. 색만으로 좌표를 추정하지 않는다.")
    print("빈 줄 또는 q 입력 시 종료.")
    while True:
        name = input("저장할 이름> ").strip()
        if name in ("", "q", "quit"):
            break
        base, box = split_box_suffix(name)
        if base not in POSE_NAMES and base not in GRIPPER_CMDS:
            print("  알 수 없는 이름.")
            continue
        joints = robot.current_joints()
        if base in GRIPPER_CMDS:
            key = GRIPPER_CMDS[base] + ("_" + box if box else "")
            poses.setdefault("gripper", {})[key] = joints["gripper.pos"]
            print(f"  gripper.{key} = {joints['gripper.pos']:.1f}")
        else:
            poses.setdefault("joints", {})[name] = joints
            print(f"  저장: {name} ({ZONE_LABELS.get(name, name)})", {k: round(v, 1) for k, v in joints.items()})
        save_poses(poses, poses_path)  # 매번 저장해 중간에 끊겨도 남게 한다


def replay(robot: So101Robot, poses_path: Path, duration_s: float = 4.0, box: str = "") -> None:
    """저장한 자세를 순서대로 천천히 재생한다. box("white"/"brown")를 주면 그 상자의 자세(pick_white 등)를 쓰고,
    없는 자세는 건너뛴다. 팔 주변을 비우고 상자는 빼 둔다(집게는 열린 채 움직임)."""
    robot.poses = load_poses(poses_path)
    joints = robot.poses.get("joints", {})
    order = []
    for name in REPLAY_ORDER:
        cand = f"{name}_{box}" if box and f"{name}_{box}" in joints else name
        if cand in joints:
            order.append(cand)
        else:
            print(f"   (건너뜀: {cand} 자세 없음)")
    robot.enable_torque()
    print("토크 ON. 각 이동 전에 Enter로 확인한다. 위험하면 전원 스위치를 끈다.")
    if input("그리퍼를 열까요? (Enter=예, n=건너뜀) ").strip() != "n":
        robot.set_gripper("open")
    for name in order:
        if input(f"-> {name} ({ZONE_LABELS.get(name, name)}) 로 이동 (Enter, q=중단) ").strip() == "q":
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
    from grasp import camera_grasp_point, load_config
    from sensor_client import SensorClient
    model, jm, cfg, sensor = K.SO101(), K.load_joint_map(), load_config(), SensorClient(sensor_url)
    cam, rob = [], []
    side = cfg.get("grasp_mode") == "side"
    print("카메라와 로봇 바닥을 고정한 상태에서 한 번 좌표를 보정한다. 상자 위치가 바뀌어도 매 작업 다시 하지 않는다.")
    print(f"실측한 집기 영역의 서로 다른 {points}곳(넓게)에 상자를 놓는다. FK/도구 기준점을 실측 확인한 뒤 진행한다.")
    while len(cam) < points:
        robot.enable_torque()
        if input(f"[{len(cam) + 1}/{points}] 상자를 놓고 손을 뗀 뒤 Enter (q=중단) ").strip() == "q":
            break
        loc = sensor.locate()
        if not loc.get("found"):
            print("  상자를 못 찾음:", loc.get("reason"), loc.get("rejected", ""))
            continue
        c, offset_mm = camera_grasp_point(loc, cfg)
        reference = f"책상 위 {offset_mm:.1f}mm" if side else f"윗면 아래 {offset_mm:.1f}mm"
        print(f"  카메라: 집는 도구 기준점 {np.round(c, 1).tolist()}mm ({reference})")
        robot.disable_torque()
        input(f"  토크 OFF. 상자를 밀지 않게 집게의 FK 도구 기준점을 표시된 점({reference})에 맞추고 Enter ")
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
        print("오차가 10mm를 넘음: 보정 점·FK 도구 기준점을 다시 확인할 것. 검증 picker는 비전 집기를 거부한다.")
    if input("저장할까요? (y/N) ").strip().lower() == "y":
        print("저장:", handeye.save(res, cam, rob))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="lerobot-find-port로 찾은 포트")
    ap.add_argument("--id", default="so101_follower", help="보정할 때 쓴 로봇 id")
    ap.add_argument("--poses", default=str(DEFAULT_POSES))
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--box", default="", help="--replay에서 쓸 상자 자세 세트(white/brown)")
    ap.add_argument("--guided", action="store_true", help="정해진 순서대로 이름을 띄워 주고 Enter만으로 저장")
    ap.add_argument("--start", type=int, default=1, help="--guided 시작 단계 번호")
    ap.add_argument("--fk-check", action="store_true")
    ap.add_argument("--handeye", action="store_true")
    ap.add_argument("--sensor-url", default="http://127.0.0.1:8001")
    ap.add_argument("--points", type=int, default=6)
    args = ap.parse_args()

    robot = So101Robot(port=args.port, robot_id=args.id, poses_path=Path(args.poses))
    try:
        robot.connect()
        if args.guided:
            guided_teach(robot, Path(args.poses), args.start)
        elif args.replay:
            replay(robot, Path(args.poses), box=args.box)
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
