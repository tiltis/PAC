"""최성수 저장소(knu19css/PAC)의 box_grasp.py가 가르친 프로필(profiles/box_1.json, box_2.json)을
이 스테이션의 poses.json 자세로 가져온다. 같은 로봇·같은 보정 파일로 가르친 것만 받는다.

    python station\\import_grasp_profile.py <profiles\\box_1.json> --box white [--poses station\\poses.json]
    python station\\import_grasp_profile.py <profiles\\box_2.json> --box brown

대응: approach → pick_approach_<box>, grasp → pick_<box>, lift → lift_<box>,
      close의 그리퍼 값 → gripper.held_<box>, open의 그리퍼 값 → gripper.open(없을 때만)
      transfer/place/release/retreat/return/home은 검사 흐름(면 제시·파랑/빨강 영역)과 달라 가져오지 않는다.
단위는 양쪽 모두 LeRobot use_degrees=True(팔 deg, 그리퍼 0~100)다.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from robot import BOX_TYPES, DEFAULT_POSES, JOINT_KEYS, load_poses, save_poses  # noqa: E402

PHASE_TO_POSE = {"approach": "pick_approach", "grasp": "pick", "lift": "lift"}
BOX_CM = {"white": [7, 7, 9], "brown": [8, 8, 4.5]}


def our_calibration_sha256(robot_id="so101_follower"):
    p = Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower" / f"{robot_id}.json"
    return (hashlib.sha256(p.read_bytes()).hexdigest(), p) if p.exists() else (None, p)


def convert(profile: dict, box: str, poses: dict, allow_calibration_mismatch=False, robot_id="so101_follower"):
    if box not in BOX_TYPES:
        raise ValueError(f"box는 {BOX_TYPES} 중 하나")
    if profile.get("units") != "arm_degrees_gripper_percent":
        raise ValueError(f"단위가 다름: {profile.get('units')!r} (arm_degrees_gripper_percent 필요)")
    if profile.get("box_cm") != BOX_CM[box]:
        raise ValueError(f"프로필 상자 {profile.get('box_cm')} ≠ {box} 상자 {BOX_CM[box]}")
    ours, path = our_calibration_sha256(robot_id)
    if not allow_calibration_mismatch and (not ours or not profile.get("calibration_sha256")):
        raise ValueError("양쪽 로봇 보정 파일의 해시가 필요: 보정이 없는 두 파일을 같은 보정으로 간주하지 않음")
    if profile.get("calibration_sha256") != ours and not allow_calibration_mismatch:
        raise ValueError("보정 파일이 다름: 다른 보정으로 가르친 각도는 이 로봇에서 다른 자세가 된다. "
                         f"상대도 {path} 보정을 쓰게 하거나(--robot-id so101_follower --calibration-dir <그 폴더>), 여기서 다시 가르칠 것")
    by_phase = {w["phase"]: w["pose"] for w in profile.get("waypoints", [])}
    joints = poses.setdefault("joints", {})
    grip = poses.setdefault("gripper", {})
    imported = []
    for phase, base in PHASE_TO_POSE.items():
        if phase not in by_phase:
            raise ValueError(f"프로필에 {phase} 단계가 없음")
        pose = {k: float(by_phase[phase][k]) for k in JOINT_KEYS}
        joints[f"{base}_{box}"] = pose
        imported.append(f"{base}_{box}")
    if "close" in by_phase:
        grip[f"held_{box}"] = float(by_phase["close"]["gripper.pos"])
        imported.append(f"gripper.held_{box}")
    if "open" in by_phase and grip.get("open") is None:
        grip["open"] = float(by_phase["open"]["gripper.pos"])
        imported.append("gripper.open")
    return imported


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", type=Path)
    ap.add_argument("--box", required=True, choices=BOX_TYPES)
    ap.add_argument("--poses", type=Path, default=DEFAULT_POSES)
    ap.add_argument("--robot-id", default="so101_follower")
    ap.add_argument("--allow-calibration-mismatch", action="store_true", help="위험: 보정이 달라도 가져온다")
    a = ap.parse_args()
    profile = json.loads(a.profile.read_text(encoding="utf-8"))
    poses = load_poses(a.poses) if a.poses.exists() else {"joints": {}, "gripper": {}}
    imported = convert(profile, a.box, poses, a.allow_calibration_mismatch, a.robot_id)
    save_poses(poses, a.poses)
    print("가져옴:", ", ".join(imported), "→", a.poses)


if __name__ == "__main__":
    main()
