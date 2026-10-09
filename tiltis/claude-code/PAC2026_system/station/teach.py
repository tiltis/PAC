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
import time
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


def _hold_loop(robot: So101Robot, msg: str) -> str:
    """Enter 전까지 w(현재 자세 고정: 손 떼고 상자 맞추기)·f(다시 풀기)를 받는다. 돌아올 때는 사용자가 친 마지막 답."""
    while True:
        ans = input(msg).strip().lower()
        if ans == "w":
            robot.hold()
            print("    고정됨(토크 ON). 손 떼도 됨. 상자를 집게 사이에 맞춘 뒤 Enter, 더 움직이려면 f")
            continue
        if ans == "f":
            robot.disable_torque()
            print("    풀림(토크 OFF)")
            continue
        return ans


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
        ans = _hold_loop(robot, f"[{i + 1}/{len(GUIDED_ORDER)}] {name}: {hint} → Enter (w=고정, f=풀기, s=건너뜀, r=이전, q=종료) ")
        if ans == "q":
            break
        if ans == "s":
            i += 1
            continue
        if ans == "r":
            i = max(0, i - 1)
            continue
        if _save_one(robot, poses, poses_path, name):
            robot.disable_torque()  # w로 고정했었다면 다음 자세를 위해 다시 푼다
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
    from grasp import load_config
    from sensor_client import SensorClient
    model, jm, cfg, sensor = K.SO101(), K.load_joint_map(), load_config(), SensorClient(sensor_url)
    cam, rob = [], []
    side = cfg.get("grasp_mode") == "side"
    print(f"상자를 집기 영역의 서로 다른 {points}곳(넓게, 로봇에서 {int(cfg['side_reach_r_m'][0]*100)}~{int(cfg['side_reach_r_m'][1]*100)}cm)에 차례로 놓는다."
          if side else f"손잡이 붙은 상자를 집기 영역의 서로 다른 {points}곳(넓게)에 차례로 놓는다.")
    while len(cam) < points:
        robot.enable_torque()
        if input(f"[{len(cam) + 1}/{points}] 상자를 놓고 손을 뗀 뒤 Enter (q=중단) ").strip() == "q":
            break
        loc = sensor.locate()
        if not loc.get("found"):
            print("  상자를 못 찾음:", loc.get("reason"), loc.get("rejected", ""))
            continue
        n = np.array(loc["table_normal_cam"])
        if side and loc.get("box_center_on_table_cam_mm") is not None:
            h = float(np.clip(cfg["side_height_frac"] * loc["top_height_mm"] + cfg["side_tcp_offset_mm"], 5.0, loc["top_height_mm"] - 5.0))
            c = np.array(loc["box_center_on_table_cam_mm"]) + n * h  # 옆집기 집는 점(상자 중심, 높이 h)
            print(f"  카메라: 상자 {loc.get('box_mm')} 높이 {loc['top_height_mm']}mm, 집는 점 {np.round(c, 1).tolist()} (높이 {h:.0f}mm)")
        else:
            c = np.array(loc["top_center_cam_mm"]) - n * cfg["tab_height_mm"] / 2  # 손잡이 높이 가운데
            print(f"  카메라: 손잡이 {loc['top_size_mm']}mm, 중심 {np.round(c, 1).tolist()}")
        robot.disable_torque()
        msg = ("  토크 OFF. 그리퍼로 상자를 옆에서 가운데 높이로 물고(집기 자세 그대로) Enter=기록, w=이 자세 고정(토크 ON), f=다시 풀기 "
               if side else "  토크 OFF. 그리퍼로 손잡이 가운데를 잡고 Enter=기록, w=이 자세 고정, f=다시 풀기 ")
        _hold_loop(robot, msg)
        q = K.from_lerobot(robot.current_joints(), jm)
        p = model.fk(q)[:3, 3]
        print(f"  로봇: 집게 끝 {np.round(p * 1000, 1).tolist()} mm")
        # 잘못 찍힌 점 걸러내기(10-09 현장: 팔을 든 채 Enter → z 128·169mm, 손이 상자 위 → 높이 76mm)
        bad = []
        if side and not (-0.02 <= p[2] <= 0.07):
            bad.append(f"집게 끝 높이 {p[2]*1000:.0f}mm가 상자 옆 높이(−20~70mm)가 아님: 팔을 내려 책상 위 상자를 물었는지")
        exp_h = (loc.get("box_mm") or [0, 0, None])[2]
        if exp_h and abs(float(loc["top_height_mm"]) - float(exp_h)) > 8:
            bad.append(f"카메라가 잰 높이 {loc['top_height_mm']}mm가 상자 {exp_h}mm와 다름: 손이 상자 위에 있었는지")
        if bad:
            print("  ⚠ " + " / ".join(bad))
            if input("  이 점을 그래도 쓸까요? (y/N) ").strip().lower() != "y":
                print("  버림. 같은 자리에서 다시.")
                continue
        cam.append(c)
        rob.append(p)
        robot.disable_torque()
        print(f"  기록 {len(cam)}/{points}")
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


def calibrate_handeye_auto(robot: So101Robot, sensor_url: str, radii=(0.42, 0.46), angles_deg=(0, 15, 30), duration_s: float = 4.0) -> None:  # 10-09: 깊이 카메라가 로봇 정면~왼쪽만 봄
    """로봇이 스스로 옆집기 자세 6곳으로 가서 집게를 벌리고 기다린다. 사용자는 상자를 집게 사이에 끼우고 손을 뗀 뒤 Enter.
    로봇 점 = 실제 관절값의 FK, 카메라 점 = 깊이로 잰 상자 중심(가운데 높이). 사람이 팔을 옮길 필요가 없다."""
    import handeye
    import kinematics as K
    from grasp import load_config
    from sensor_client import SensorClient
    model, jm, cfg, sensor = K.SO101(), K.load_joint_map(), load_config(), SensorClient(sensor_url)
    frac, off = cfg["side_height_frac"], cfg["side_tcp_offset_mm"]
    h_box = 45.0  # 자세 계산용 기본(갈색). 실제 기록은 카메라가 잰 높이로 한다
    z = (frac * h_box + off) / 1000.0
    targets, prev = [], None
    for r in radii:
        for a in angles_deg:
            t = np.radians(a)
            p = np.array([r * np.cos(t), r * np.sin(t), z])
            radial = np.array([np.cos(t), np.sin(t), 0.0])
            q = model.ik(p, down=radial, yaw=float(t + np.pi / 2), q0=prev)  # 이전 해를 시드로: 손목 180° 뒤집힘 방지
            prev = q if q is not None else prev
            if q is None:
                print(f"  (건너뜀: r={r*100:.0f}cm 각도 {a}° 역기구학 해 없음)")
                continue
            q_back = None  # 상자를 끼운 뒤 물러나 카메라가 상자만 보게. 수평 접근은 38cm 밑에서 안 풀리므로 6→3cm 순으로 시도
            for back in (0.06, 0.05, 0.04, 0.03):
                q_back = model.ik(p - radial * back + np.array([0, 0, 0.01]), down=radial, yaw=float(t + np.pi / 2), q0=q)
                if q_back is not None:
                    break
            if q_back is None:
                print(f"  (건너뜀: r={r*100:.0f}cm 각도 {a}° 물러날 자세 해 없음)")
                continue
            targets.append((p, q, q_back))
    print(f"자동 좌표 맞추기: 로봇이 {len(targets)}곳으로 차례로 간다. 팔 주변을 비울 것. 각 자리에서 상자를 집게 사이에 끼우고 손을 뗀 뒤 Enter.")
    if input("시작하려면 Enter (q=중단) ").strip() == "q":
        return
    robot.enable_torque()
    robot.set_gripper("open")
    cam, rob = [], []
    for i, (p, q, q_back) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] 목표 ({p[0]*1000:.0f}, {p[1]*1000:.0f}, {p[2]*1000:.0f})mm 로 이동 중... (상자는 아직 치워 둘 것)")
        robot.move_joints(K.to_lerobot(q_back, jm), duration_s)
        robot.wait_settled(4.0)
        robot.move_joints(K.to_lerobot(q, jm), 2.0)
        print(f"   도착 안정화: {robot.wait_settled(5.0)}")
        while True:
            ans = input("   상자를 집게 사이(가운데)에 끼우고 손을 뗀 뒤 Enter (s=이 자리 건너뜀, q=중단) ").strip().lower()
            if ans in ("s", "q"):
                break
            # 집게를 닫아 상자를 집게 가운데로 정렬한 뒤(손으로 끼운 오차 제거) 그 자세를 로봇 쪽 점으로 기록하고 다시 연다
            print("   집게를 닫아 상자를 가운데로 맞춤...")
            robot.set_gripper("closed")
            time.sleep(1.2)
            g = robot.gripper_reading()
            qa = K.from_lerobot(robot.current_joints(), jm)
            pa = model.fk(qa)[:3, 3]
            robot.set_gripper("open")
            time.sleep(0.8)
            if g.get("open") is not None and g.get("closed") is not None and abs(g["open"] - g["closed"]) > 1e-6:
                frac = (g["pos"] - g["closed"]) / (g["open"] - g["closed"])
                if frac < 0.1:
                    print(f"   ⚠ 집게가 끝까지 닫힘(빈손, {frac:.2f}) — 상자가 집게 사이에 없었음. 다시 끼우고 Enter")
                    continue
            print("   팔을 뒤로 뺀 뒤(home) 카메라가 상자만 보게 하고 측정... 상자는 그대로 둘 것")
            robot.move_joints(K.to_lerobot(q_back, jm), 2.0)   # 먼저 조금 물러나 상자를 건드리지 않게
            robot.wait_settled(3.0)
            robot.move_to("home", 3.0)                           # 집게가 깊이 영상에서 상자와 붙지 않게 완전히 뺀다(10-09: 3~6cm로는 한 덩어리로 보임)
            robot.wait_settled(4.0)
            loc = sensor.locate()
            if not loc.get("found"):
                print("   상자를 못 찾음:", loc.get("reason"), "— 상자가 깊이 화면 안에 있는지 보고 다시 끼운 뒤 Enter(s=건너뜀)")
                robot.move_joints(K.to_lerobot(q_back, jm), 3.0); robot.wait_settled(4.0)
                robot.move_joints(K.to_lerobot(q, jm), 2.0); robot.wait_settled(4.0)
                continue
            exp_h = (loc.get("box_mm") or [0, 0, None])[2]
            if exp_h and abs(float(loc["top_height_mm"]) - float(exp_h)) > 8:
                print(f"   카메라 높이 {loc['top_height_mm']}mm가 상자 {exp_h}와 다름(손?). 다시 Enter")
                robot.move_joints(K.to_lerobot(q_back, jm), 3.0); robot.wait_settled(4.0)
                robot.move_joints(K.to_lerobot(q, jm), 2.0); robot.wait_settled(4.0)
                continue
            n = np.array(loc["table_normal_cam"])
            h = float(np.clip(frac * loc["top_height_mm"] + off, 5.0, loc["top_height_mm"] - 5.0))
            c = np.array(loc["box_center_on_table_cam_mm"]) + n * h
            cam.append(c)
            rob.append(pa)
            print(f"   기록 {len(cam)}: 카메라 {np.round(c, 1).tolist()} ↔ 로봇 {np.round(pa * 1000, 1).tolist()}mm")
            break
        if ans == "q":
            break
    sensor.close()
    if len(cam) < 4:
        print("점이 4개 미만이라 저장하지 않음")
        return
    res = handeye.fit(cam, rob)
    print(f"RMS {res['rms_mm']}mm, 최대 {res['max_mm']}mm, 점별 {res['residuals_mm']}")
    if res["rms_mm"] > 10:
        print("오차가 10mm를 넘음: 상자가 집게 가운데에 안 끼워졌거나 손이 보였을 수 있음. 다시 권장")
    if input("저장할까요? (y/N) ").strip().lower() == "y":
        print("저장:", handeye.save(res, cam, rob))
    print("home으로 복귀 중..."); robot.move_to("home", duration_s); robot.wait_settled(5.0)


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
    ap.add_argument("--handeye-auto", action="store_true", help="로봇이 6곳으로 가서 기다리고 사용자는 상자만 끼움")
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
        elif args.handeye_auto:
            calibrate_handeye_auto(robot, args.sensor_url)
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
