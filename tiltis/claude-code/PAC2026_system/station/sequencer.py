"""검사 작업 순서(포장 1개당 1회 실행). 로봇/센서 객체는 주입받으므로 목업으로 테스트할 수 있다."""
from __future__ import annotations

import copy
import json
import math
import threading
import time
from datetime import datetime
from numbers import Real
from typing import Callable, Optional

from robot import JOINT_KEYS

DEFAULT_DURATIONS = {  # 이동별 기본 소요 시간(초). 현장에서 조정
    "home": 2.0, "pick_approach": 2.0, "pick": 1.5, "lift": 1.5,
    "face_A": 3.0, "face_B": 3.0, "face_C": 3.5, "bin_ok": 4.0, "bin_human": 4.0,  # 10-09 현장: 놓기 자세는 천천히(바닥에 '팍' 내려놓던 것)
    "vision_approach": 2.5, "vision_grasp": 1.5, "vision_lift": 1.5,
    "transfer_lift": 2.0, "transfer_travel": 4.0,
    "transfer_lower": 3.0, "transfer_retract": 3.0,
    "bin_ok_up": 2.0, "bin_human_up": 2.0,
}

# 기존 자세/DB 키를 유지한다. 실제 위치는 현장에서 poses.json에 가르친다.
SORTING_ZONES = {
    "ok": {"label": "파랑 영역", "color": "blue", "pose": "bin_ok"},
    "human": {"label": "빨강 영역", "color": "red", "pose": "bin_human"},
}


class BusyError(Exception):
    pass


class SequenceError(Exception):
    """로봇 안정화 실패, 센서 오류 등 작업을 멈춰야 하는 상황."""


class _Abort(Exception):
    pass


class _DryRun(Exception):
    """비전 집기 시험: 접근 위치까지만 가고 멈춘다."""


DEFAULT_FACES = ("A", "B")
ALLOWED_FACES = ("A", "B", "C")


def parse_faces(text) -> tuple:
    """환경변수 FACES("A,B" 또는 "A,B,C") → 검사할 면 순서. 모르는 면·중복·빈 값은 거부한다."""
    faces = tuple(f.strip().upper() for f in str(text or "").split(",") if f.strip())
    if not faces or len(set(faces)) != len(faces) or any(f not in ALLOWED_FACES for f in faces):
        raise ValueError(f"FACES는 {','.join(ALLOWED_FACES)} 중에서 중복 없이 골라야 한다: {text!r}")
    return faces


def decide(final_by_face: dict, faces=DEFAULT_FACES) -> tuple:
    """CONTRACT 최종 판정 규칙. 면별 최종 verdict -> (최종 verdict, 분류함). 검사하기로 한 면이 하나라도 빠지면 오류."""
    verdicts = list(final_by_face.values())
    if "suspect" in verdicts and set(final_by_face) <= set(faces) and final_by_face:
        return "suspect", "human"  # 불량 확정이면 남은 면이 없어도 빨강(조기 종료)
    if set(final_by_face) != set(faces) or any(
            v not in ("suspect", "unmeasurable", "review", "no_anomaly") for v in verdicts):
        raise SequenceError(f"불완전하거나 알 수 없는 면별 판정: {final_by_face}")
    if "suspect" in verdicts:
        return "suspect", "human"
    if "unmeasurable" in verdicts:
        return "unmeasurable", "human"
    if "review" in verdicts:
        return "review", "human"
    if verdicts and all(v == "no_anomaly" for v in verdicts):
        return "no_anomaly", "ok"
    raise SequenceError(f"알 수 없는 판정값으로 정상 분류하지 않음: {verdicts}")  # 모르는 값은 통과시키지 않는다


def judge_grasp(pos, open_v, closed_v, held_v=None, min_frac: float = 0.1) -> tuple:
    """그리퍼를 닫은 뒤 위치로 물건을 물고 있는지 판단한다. (holding: True/False/None, detail)

    closed는 빈손으로 끝까지 닫은 값, open은 열린 값(teach.py). 닫힘 쪽으로 명령하면 물건이 있을 때 그 폭에서 멈춘다.
    frac = (pos - closed) / (open - closed): 0 근처면 빈손(놓침), 0.9 이상이면 닫히지 않음.
    held(손잡이를 물린 채 가르친 값)가 있으면 그 frac의 절반을 기준으로, 없으면 min_frac.
    """
    try:
        pos, open_v, closed_v = float(pos), float(open_v), float(closed_v)
    except (TypeError, ValueError):
        return None, {"reason": "gripper_untaught", "pos": pos}
    span = open_v - closed_v
    if abs(span) < 1e-6:
        return None, {"reason": "gripper_untaught", "pos": pos}
    f = (pos - closed_v) / span
    thr = min_frac
    if held_v is not None:
        fh = (float(held_v) - closed_v) / span
        if 0.05 < fh < 0.9:
            thr = fh / 2
    detail = {"pos": round(pos, 2), "frac": round(f, 3), "threshold_frac": round(thr, 3)}
    if f >= 0.9:
        return False, {**detail, "reason": "gripper_not_closed"}
    if f < thr:
        return False, {**detail, "reason": "nothing_held"}
    return True, {**detail, "reason": "holding"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Sequencer:
    def __init__(self, robot, sensor, on_event: Optional[Callable[[dict], None]] = None,
                 on_finish: Optional[Callable[[dict], None]] = None,
                 durations: Optional[dict] = None, settle_timeout_s: float = 8.0, advisor=None,
                 picker=None, faces=DEFAULT_FACES):
        self.faces = parse_faces(faces if isinstance(faces, str) else ",".join(faces))
        self.robot = robot
        self.sensor = sensor
        self.picker = picker  # 비전 집기(grasp.VisionPicker). None이면 가르친 자세로 집는다
        self.advisor = advisor  # 기록 전용(advisor.py). 작업 순서에 영향을 주지 않는다
        self.on_event = on_event
        self.on_finish = on_finish
        self.durations = {**DEFAULT_DURATIONS, **(durations or {})}
        self.settle_timeout_s = settle_timeout_s
        self._lock = threading.Lock()
        self._busy = False
        self._paused = False
        self._abort = False
        self._cur: Optional[dict] = None
        self._last: Optional[dict] = None
        self._thread: Optional[threading.Thread] = None
        self._vision_lift = None

    # --- 외부 제어 ---
    @property
    def busy(self) -> bool:
        return self._busy

    def request_pause(self) -> None:
        """소프트웨어 일시정지 요청(다음 동작 전에 대기). 비상정지가 아니다."""
        self._paused = True
        self._emit("pause", "request")

    def resume(self) -> None:
        self._paused = False
        self._emit("pause", "resume")

    def request_abort(self) -> None:
        self._abort = True

    def snapshot(self) -> dict:
        with self._lock:
            cur = copy.deepcopy(self._cur) if self._cur else None
            last = copy.deepcopy(self._last) if self._last else None
            busy, paused = self._busy, self._paused
        state = cur["state"] if cur else (last["state"] if last else "idle")
        return {"state": state, "busy": busy, "paused": paused, "faces": list(self.faces),
                "zones": copy.deepcopy(SORTING_ZONES),
                "robot_mode": "mock" if getattr(self.robot, "is_mock", False) else "hardware",
                "pick_mode": "vision" if self.picker is not None else "taught",
                "current": cur, "last_result": last}

    def start(self, specimen_id: str, session: str, box_type: str = "") -> None:
        """백그라운드 스레드에서 실행. 이미 실행 중이면 BusyError. box_type: ""(공통) 또는 "white"/"brown" 자세 세트."""
        self._begin(specimen_id, session, box_type)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def run(self, specimen_id: str, session: str, box_type: str = "") -> dict:
        """동기 실행(테스트용). 결과 dict를 반환."""
        self._begin(specimen_id, session, box_type)
        return self._run()

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # --- 내부 ---
    def _begin(self, specimen_id: str, session: str, box_type: str = "") -> None:
        with self._lock:
            if self._busy:
                raise BusyError("이미 실행 중")
            self._busy = True
            self._abort = False
            self._vision_lift = None
            self._cur = {
                "specimen_id": specimen_id, "session": session, "box_type": box_type or "", "state": "running",
                "step": None, "started_at": _now_iso(), "finished_at": None,
                "final_verdict": None, "bin": None, "destination": None, "decision_status": "pending",
                "routing_status": "not_started", "placed_bin": None, "retakes_used": 0,
                "inspections": [], "events": [], "steps": [], "grasp_checks": [], "elapsed_ms": 0, "error": None,
            }
            self._t0 = time.perf_counter()

    def _emit(self, step: str, status: str, **extra) -> None:
        ev = {"t": time.time(), "step": step, "status": status, **extra}
        with self._lock:
            if self._cur is not None:
                self._cur["events"].append(ev)
                if status == "start":
                    self._cur["step"] = step
                self._cur["elapsed_ms"] = int((time.perf_counter() - self._t0) * 1000)
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:
                pass

    def _checkpoint(self) -> None:
        """모든 동작 직전에 호출: 중단 요청이면 종료, 일시정지면 재개까지 대기."""
        while True:
            if self._abort:
                raise _Abort()
            if not self._paused:
                return
            time.sleep(0.05)

    def _step(self, name: str, fn):
        self._checkpoint()
        self._emit(name, "start")
        t0 = time.perf_counter()
        try:
            result = fn()
        except Exception:
            self._emit(name, "error", ms=int((time.perf_counter() - t0) * 1000))
            raise
        ms = int((time.perf_counter() - t0) * 1000)
        with self._lock:
            self._cur["steps"].append({"step": name, "ms": ms})
        self._emit(name, "end", ms=ms)
        return result

    def _pose_name(self, base: str) -> str:
        """상자 종류별 자세(예: pick_white)가 가르쳐져 있으면 그것을, 없으면 접미사 없는 자세를 쓴다."""
        box = (self._cur or {}).get("box_type") or ""
        if box:
            poses = getattr(self.robot, "poses", None) or {}
            if f"{base}_{box}" in (poses.get("joints") or {}):
                return f"{base}_{box}"
        return base

    def _move(self, pose: str) -> None:
        name = self._pose_name(pose)
        self._step(f"move:{name}", lambda: self.robot.move_to(name, self.durations.get(pose, 2.0)))

    def _move_joints(self, name: str, target: dict) -> None:
        self._step(f"move:{name}", lambda: self.robot.move_joints(target, self.durations.get(name, 2.0)))

    def _prepare_transfer(self, pose: str):
        """전체 놓기 경로를 이동 전에 확인한다. planner가 없는 기존 어댑터는 가르친 자세를 사용한다."""
        planner = getattr(self.robot, "plan_transfer", None)
        if planner is None:
            return None
        if not callable(planner):
            raise SequenceError("분류 이동 계획기가 호출 가능한 함수가 아님")

        def prepare():
            plan = planner(self._pose_name(pose))
            if not isinstance(plan, dict):
                raise SequenceError("분류 이동 계획 형식 오류")
            arm_keys = set(JOINT_KEYS) - {"gripper.pos"}
            for stage in ("lift", "travel", "lower", "retract"):
                targets = plan.get(stage)
                if not isinstance(targets, list) or not targets:
                    raise SequenceError(f"분류 이동 계획의 {stage} 경로가 비어 있거나 잘못됨")
                for target in targets:
                    if not isinstance(target, dict) or set(target) != arm_keys:
                        raise SequenceError(f"분류 이동 계획의 {stage} 관절 목록 오류")
                    if any(isinstance(value, bool) or not isinstance(value, Real)
                           or not math.isfinite(value) for value in target.values()):
                        raise SequenceError(f"분류 이동 계획의 {stage} 관절값 오류")
                duration = self.durations[f"transfer_{stage}"]
                if (isinstance(duration, bool) or not isinstance(duration, Real)
                        or not math.isfinite(duration) or duration <= 0):
                    raise SequenceError(f"분류 이동 {stage} 시간은 양의 유한 숫자여야 함")
            # 실행 결과/상태 API에 그대로 기록 가능한 계획만 허용한다. 뒤쪽 경로 오류도 이동 전에 거부한다.
            try:
                return json.loads(json.dumps(plan, allow_nan=False))
            except (TypeError, ValueError) as exc:
                raise SequenceError(f"분류 이동 계획 기록 형식 오류: {exc}") from exc

        plan = self._step("transfer:plan", prepare)
        with self._lock:
            self._cur["transfer_plan"] = copy.deepcopy(plan)
        return plan

    def _transfer_stage(self, stage: str, plan: dict) -> None:
        """한 단계의 작은 경유점을 순서대로 실행하고 실제 목표 도달을 확인한다."""
        targets = plan[stage]
        name = f"transfer_{stage}"
        duration = self.durations[name] / len(targets)

        def move():
            for target in targets:
                self._checkpoint()
                rate_time = getattr(self.robot, "transfer_duration", None)
                seconds = rate_time(target, duration) if callable(rate_time) else duration
                if (isinstance(seconds, bool) or not isinstance(seconds, Real)
                        or not math.isfinite(seconds) or seconds < duration):
                    raise SequenceError("분류 이동 속도 제한의 시간 계산 오류")
                self.robot.move_joints(target, seconds)

        self._step(f"move:{name}", move)

        def settle():
            # 촬영 자세의 is_still 예외는 쓰지 않는다. 낮은 위치에서 정지만 했어도 다음 이동은 금지한다.
            if not self.robot.wait_settled(self.settle_timeout_s):
                raise SequenceError(f"분류 이동 {stage} 목표 도달 확인 실패")

        self._step(f"settle:{name}", settle)
        verifier = getattr(self.robot, "verify_transfer_stage", None)
        if verifier is not None:
            check = self._step(f"transfer:verify_{stage}", lambda: verifier(stage, plan))
            if not isinstance(check, dict):
                raise SequenceError(f"분류 이동 {stage} 실제 위치 확인 응답 오류")
            with self._lock:
                self._cur.setdefault("transfer_checks", []).append({"stage": stage, "result": copy.deepcopy(check)})
            if check.get("ok") is not True:
                raise SequenceError(f"분류 이동 {stage} 실제 위치 확인 실패: {check.get('reason')}")

    def _legacy_retract(self, pose: str) -> None:
        """기존 현장 bin_*_up 자세가 있으면 놓은 상자 위로 먼저 빠져나온다."""
        up = f"{pose}_up"
        poses = (getattr(self.robot, "poses", None) or {}).get("joints", {})
        # 현장에서 사용한 공통 이름과 두 가지 상자 접미사 위치를 모두 받아들인다.
        box = (self._cur or {}).get("box_type") or ""
        candidates = (f"{up}_{box}", f"{pose}_{box}_up", up) if box else (up,)
        for name in candidates:
            if name in poses:
                self._step(f"move:{name}", lambda: self.robot.move_to(name, self.durations.get(up, 2.0)))
                return

    def _verify_before_grasp(self, loc) -> None:
        verifier = getattr(self.picker, "verify_at_grasp", None)
        if verifier is not None:
            check = self._step("vision:recheck", lambda: verifier(loc))
            if not check.get("ok"):
                raise SequenceError(f"집기 직전 위치 확인 실패: {check.get('reason')}")

    def _pick(self) -> None:
        """가르친 자세(기본) 또는 깊이로 찾은 상자 손잡이를 계산한 자세(비전)로 집는다.
        비전 모드에서 찾기·계획이 실패하면 가르친 자세로 바꾸지 않고 멈춘다."""
        if self.picker is None:
            self._move("pick_approach")
            self._move("pick")
            self._grip("closed")
            self._check_grasp("pick")
            return
        loc = self._step("vision:locate", self.picker.locate)
        if isinstance(loc, dict) and loc.get("found") and not (self._cur or {}).get("box_type"):
            auto = getattr(self.picker, "box_type_for", lambda l: "")(loc)  # 잰 높이로 흰/갈색 자동 선택 → 그 상자의 gripper_held 기준 사용
            if auto:
                with self._lock:
                    self._cur["box_type"] = auto
                    self._cur["box_type_source"] = "depth_height"
        plan = self._step("vision:plan", lambda: self.picker.plan(loc))
        with self._lock:
            self._cur["pick"] = {"mode": "vision", "dry_run": bool(self.picker.dry_run),
                                 "locate": {k: loc.get(k) for k in ("found", "reason", "top_center_cam_mm", "top_size_mm", "top_height_mm")} if isinstance(loc, dict) else None,
                                 "plan": {k: v for k, v in plan.items() if k not in ("approach", "grasp", "lift")}}
        if not plan.get("ok"):
            raise SequenceError(f"비전 집기 계획 실패: {plan.get('reason')}")
        self._vision_lift = dict(plan["lift"])
        self._move_joints("vision_approach", plan["approach"])
        stage = getattr(self.picker, "dry_stage", "approach")
        if self.picker.dry_run and stage == "approach":
            self._step("vision:dry_hold", lambda: time.sleep(float(getattr(self.picker, "dry_hold_s", 8.0))))  # 접근점에서 멈춰 눈으로 확인할 시간
            raise _DryRun()
        self._verify_before_grasp(loc)
        self._move_joints("vision_grasp", plan["grasp"])
        if self.picker.dry_run:  # stage == "grasp": 집는 자세(닫기 직전)에서 멈춰 집게와 상자 위치를 확인
            def hold_and_measure():
                time.sleep(2.5)  # 도착 후 정지 대기
                try:  # 실제 관절값 → 집게 위치. 계획 목표와 비교해 "로봇이 목표에 못 미친 양"을 기록
                    import kinematics as K
                    cur = self.robot.current_joints()
                    q = K.from_lerobot(cur, getattr(self.picker, "joint_map", None))
                    actual = K.SO101().fk(q)[:3, 3]
                    tgt = plan.get("grasp_point_m")
                    err = [round((a - t) * 1000, 1) for a, t in zip(actual, tgt)] if tgt else None
                    dq = {k: round(float(cur.get(k, 0)) - float(plan["grasp"].get(k, 0)), 1) for k in plan["grasp"]}
                    with self._lock:
                        self._cur["pick"]["dry_hold"] = {"actual_tcp_mm": [round(v * 1000, 1) for v in actual], "target_tcp_mm": [round(v * 1000, 1) for v in tgt] if tgt else None,
                                                         "error_mm_xyz": err, "joint_error_deg": dq}
                except Exception as e:
                    with self._lock:
                        self._cur["pick"]["dry_hold"] = {"error": f"{type(e).__name__}: {e}"}
                time.sleep(max(0.0, float(getattr(self.picker, "dry_hold_s", 8.0)) - 2.5))
            self._step("vision:dry_hold", hold_and_measure)
            self._move_joints("vision_approach", plan["approach"])
            raise _DryRun()
        self._grip("closed")
        try:
            self._check_grasp("pick")
        except SequenceError as first:
            # 놓침(빈손): 집게를 열고 뒤로 빠진 뒤 다시 찾아 한 번 더 집는다. 두 번째도 실패하면 멈춘다(추측해서 계속 안 함)
            if "nothing_held" not in str(first) or getattr(self.picker, "retry_grasp", True) is False:
                raise
            self._emit("vision:regrasp", "start", reason=str(first))
            self._grip("open")
            self._move_joints("vision_approach", plan["approach"])
            self._move("home")  # 팔이 상자 옆에 있으면 깊이 영상에서 한 덩어리로 섞여 못 찾는다(10-09 현장) → 시야 밖으로 뺀 뒤 다시 측정
            loc2 = self._step("vision:locate#2", self.picker.locate)
            plan2 = self._step("vision:plan#2", lambda: self.picker.plan(loc2))
            with self._lock:
                self._cur["pick"]["retry"] = {"locate": {k: loc2.get(k) for k in ("found", "reason", "box_center_on_table_cam_mm", "top_height_mm")} if isinstance(loc2, dict) else None,
                                              "plan": {k: v for k, v in plan2.items() if k not in ("approach", "grasp", "lift")}}
            if not plan2.get("ok"):
                raise SequenceError(f"재집기 계획 실패: {plan2.get('reason')}")
            plan = plan2
            loc = loc2
            self._vision_lift = dict(plan["lift"])
            self._move_joints("vision_approach", plan["approach"])
            self._verify_before_grasp(loc2)
            self._move_joints("vision_grasp", plan["grasp"])
            self._grip("closed")
            self._check_grasp("pick")
            self._emit("vision:regrasp", "end")
        bind = getattr(self.picker, 'capture_held_box', None)
        if bind is not None:
            held = self._step('vision:held_box', lambda: bind(loc, self.robot.current_joints()))
            if not isinstance(held, dict) or held.get('ok') is not True:
                raise SequenceError(f"집은 상자 자세 확인 실패: {(held or {}).get('reason')}")
        self._move_joints("vision_lift", plan["lift"])

    def _grip(self, state: str) -> None:
        self._step(f"grip:{state}", lambda: self.robot.set_gripper(state))

    def _check_grasp(self, where: str) -> None:
        """그리퍼가 끝까지 닫혔으면(빈손) 또는 판단할 수 없으면 멈춘다. 빈 화면을 검사해 '테이프 없음'으로 기록하지 않게 한다."""
        def fn():
            reader = getattr(self.robot, "gripper_reading", None)
            try:
                r = reader() if reader else None
            except NotImplementedError:
                r = None
            if not isinstance(r, dict):
                raise SequenceError(f"집기 확인 불가({where}): 로봇이 그리퍼 위치를 주지 않음")
            held = r.get("held")
            box = (self._cur or {}).get("box_type") or ""
            if box:  # 상자 종류별로 가르친 gripper_held_<box>가 있으면 그 값으로 판단
                g = (getattr(self.robot, "poses", None) or {}).get("gripper") or {}
                held = g.get(f"held_{box}", held)
            holding, detail = judge_grasp(r.get("pos"), r.get("open"), r.get("closed"), held)
            with self._lock:
                self._cur["grasp_checks"].append({"where": where, "holding": holding, **detail})
            if holding is not True:
                hint = " (teach.py로 gripper_open·gripper_closed를 가르칠 것)" if holding is None else ""
                raise SequenceError(f"집기 실패({where}): {detail['reason']}{hint}")
        self._step(f"grip:check@{where}", fn)

    def _settle(self, face: str) -> None:
        def fn():
            if self.robot.wait_settled(self.settle_timeout_s):
                return
            # 10-09 현장: 상자를 들고 뻗으면 서보가 목표 ±5° 안에 간헐적으로 못 들어온다. 팔이 더 움직이지 않으면(정지) 촬영을 진행하고 기록만 남긴다
            still = getattr(self.robot, "is_still", None)
            moving = (not still()) if callable(still) else False
            if moving:
                raise SequenceError(f"면 {face} 자세 안정화 시간 초과(팔이 계속 움직임)")
            with self._lock:
                self._cur.setdefault("warnings", []).append(f"settle_timeout_{face}")
            self._emit(f"settle:{face}", "warning", detail="목표 각도 밖이지만 정지 상태라 진행")
        self._step(f"settle:{face}", fn)

    def _inspect(self, face: str, attempt: int) -> dict:
        cur = self._cur
        res = self._step(f"inspect:{face}#{attempt}", lambda: self.sensor.inspect(
            cur["session"], cur["specimen_id"], face, attempt))
        if not isinstance(res, dict):
            raise SequenceError("센서 응답 형식 오류")
        entry = {"face": face, "attempt": attempt, "status": res.get("status"),
                 "session": cur["session"], "trigger_id": res.get("trigger_id"),
                 "verdict": res.get("verdict"), "reasons": res.get("reasons", []),
                 "features": res.get("features", {}), "capture_id": res.get("capture_id"),
                 "images": res.get("images", {}), "elapsed_ms": res.get("elapsed_ms", 0),
                 "sensor_data": res.get("sensor_data", {}), "artifacts": res.get("artifacts", {}),
                 "error": res.get("error"), "persistence_error": res.get("persistence_error")}
        with self._lock:
            cur["inspections"].append(entry)
        if res.get("status") != "ok":
            raise SequenceError(f"센서 오류(면 {face}): {res.get('error')}")
        for key, expected in (("specimen_id", cur["specimen_id"]), ("face", face), ("attempt", attempt)):
            if type(res.get(key)) is not type(expected) or res.get(key) != expected:
                raise SequenceError(f"센서 응답 불일치: {key}")
        if entry["verdict"] not in ("no_anomaly", "suspect", "unmeasurable", "review"):
            raise SequenceError(f"알 수 없는 verdict: {entry['verdict']!r}")
        if not isinstance(entry["features"], dict) or not isinstance(entry["images"], dict) or not (
                isinstance(entry["reasons"], list) and all(isinstance(r, str) for r in entry["reasons"])):
            raise SequenceError("센서 응답 형식 오류(features/images/reasons)")
        if not isinstance(entry["sensor_data"], dict) or not isinstance(entry["artifacts"], dict):
            raise SequenceError("센서 응답 형식 오류(sensor_data/artifacts)")
        data = entry["sensor_data"]
        if (not getattr(self.robot, "is_mock", False) and entry["features"].get("simulated") is not True
                and data.get("schema_version") != "pac-sensors-1"):
            raise SequenceError("실장비 응답에 pac-sensors-1 association 스키마 필요")
        if data.get("schema_version") == "pac-sensors-1":
            association = data.get("association")
            if not isinstance(association, dict) or not isinstance(entry["trigger_id"], str) or not entry["trigger_id"] or any(
                    association.get(key) != expected for key, expected in (("session", cur["session"]),
                    ("specimen_id", cur["specimen_id"]), ("face", face), ("attempt", attempt),
                    ("trigger_id", entry["trigger_id"]), ("capture_id", entry["capture_id"]))):
                raise SequenceError("센서 데이터의 촬영 연결 불일치")
        # 구형 품질 전용 센서도 정상 분류하지 않는다(두 PC 업데이트 시점 차이).
        f = entry["features"]
        defect_version = f.get("defect_rules_version")
        has_evidence = (f.get("defect_inspected") is True and isinstance(defect_version, str)
                        and bool(defect_version.strip()))
        association_unverified = data.get("schema_version") == "pac-sensors-1" and (
            data["association"].get("status") != "linked_under_stationary_specimen_precondition")
        if data.get("schema_version") == "pac-sensors-1" and data.get("assessment", {}).get("defect_inspected") is not True:
            has_evidence = False
        simulated_on_hardware = f.get("simulated") is True and not getattr(self.robot, "is_mock", False)
        if entry["verdict"] == "no_anomaly" and (not has_evidence or simulated_on_hardware or association_unverified or str(
                f.get("rules_version", "")).startswith("quality-only-")):
            with self._lock:
                entry["sensor_verdict"] = entry["verdict"]
                entry["verdict"] = "review"
                entry["reasons"] = list(entry["reasons"]) + [
                    "simulated_inspection" if simulated_on_hardware else (
                    "sensor_association_unverified" if association_unverified else "defect_rules_unavailable")]
                entry["features"] = {**f, "sensor_verdict": "no_anomaly"}
        if self.advisor is not None:
            try:
                adv = self.advisor.advise(dict(entry), 1 - cur["retakes_used"])
            except Exception as e:  # 조언자 고장이 검사를 멈추게 하지 않는다
                adv = {"error": str(e)[:200]}
            with self._lock:  # snapshot()이 다른 스레드에서 복사하는 중에 dict가 바뀌지 않게
                entry["advisor"] = adv
        return entry

    def _inspect_face(self, face: str) -> str:
        """면 하나를 검사하고 최종 verdict를 돌려준다. 재촬영 예산은 포장당 1회."""
        self._move(f"face_{face}")
        self._settle(face)
        self._check_grasp(f"face_{face}")
        entry = self._inspect(face, 0)
        if entry["verdict"] == "unmeasurable" and self._cur["retakes_used"] == 0:
            self._cur["retakes_used"] = 1
            if self.picker is None:
                self._move("lift")
            else:
                self._move_joints("vision_lift", self._vision_lift)
            self._move(f"face_{face}")
            self._settle(face)
            self._check_grasp(f"face_{face}")
            entry = self._inspect(face, 1)
        return entry["verdict"]

    def _sequence(self) -> None:
        ready = getattr(self.picker, "preflight_ready", None)
        if ready is not None:
            check = self._step("vision:ready", ready)
            if not check.get("ok"):
                raise SequenceError(f"비전 집기 준비 미완료: {check.get('reason')}")
        self._move("home")
        self._grip("open")
        self._pick()
        if self.picker is None:
            self._move("lift")
        self._check_grasp("lift")
        finals = {}
        for face in self.faces:  # 기본 A·B. 3면 테이프 검사는 FACES=A,B,C로 face_C 자세(손목을 더 돌려 3번째 면)를 추가한다
            finals[face] = self._inspect_face(face)
            if finals[face] == "suspect" and getattr(self, "early_exit_on_suspect", True):
                # 10-09 현장 결정: 테이프 부족 등 불량이 확정되면 남은 면(밑면 등)은 보지 않고 바로 빨강 영역으로
                skipped = [f for f in self.faces if f not in finals]
                with self._lock:
                    self._cur["skipped_faces"] = skipped
                self._emit("early_exit", "end", face=face, skipped=skipped)
                break
        verdict, bin_name = decide(finals, self.faces)
        self._cur["final_verdict"] = verdict
        self._cur["bin"] = bin_name
        self._cur["destination"] = {"bin": bin_name, **SORTING_ZONES[bin_name]}
        self._cur["decision_status"] = "decided"
        self._emit("decide", "end", verdict=verdict, bin=bin_name,
                   destination=copy.deepcopy(self._cur["destination"]))
        self._cur["routing_status"] = "in_progress"
        bin_pose = SORTING_ZONES[bin_name]["pose"]
        transfer = self._prepare_transfer(bin_pose)
        if transfer is None:
            self._move(bin_pose)
        else:
            self._transfer_stage("lift", transfer)
            self._check_grasp("transfer_lift")
            self._transfer_stage("travel", transfer)
            self._check_grasp("transfer_travel")
            self._transfer_stage("lower", transfer)
        release = getattr(self.picker, 'verify_at_release', None)
        if release is not None:
            check = self._step('vision:release_check', lambda: release(bin_name, self.robot.current_joints()))
            self._cur['release_check'] = check
            if not isinstance(check, dict) or check.get('ok') is not True:
                raise SequenceError(f"놓기 자세 확인 실패: {(check or {}).get('reason')}")
        self._grip("open")
        self._cur["placed_bin"] = bin_name
        self._cur["routing_status"] = "placed"
        if transfer is None:
            self._legacy_retract(bin_pose)
        else:
            self._transfer_stage("retract", transfer)
        self._move("home")
        self._cur["routing_status"] = "complete"

    def _run(self) -> dict:
        try:
            self._sequence()
            state, err = "done", None
        except _Abort:
            state, err = "aborted", "사용자 중단"
            try:  # 경유점 사이 중단에서도 마지막 목표로 계속 수렴하지 않도록 현재 위치를 유지한다.
                self.robot.stop()
            except Exception:
                pass
        except _DryRun:
            state, err = "dry_run_done", None
            try:  # 상자 위 접근 위치에서 집지 않고 원위치
                self.robot.move_to("home", self.durations["home"])
            except Exception as e:
                state, err = "error", f"시험 이동 후 원위치 실패: {e}"
                try:
                    self.robot.stop()
                except Exception:
                    pass
        except Exception as e:  # 로봇 예외, 안정화 실패, 센서 오류 모두 즉시 정지
            state, err = "error", str(e) or type(e).__name__
            try:
                self.robot.stop()
            except Exception:
                pass
        with self._lock:
            cur = self._cur
            cur["state"], cur["error"] = ("saving" if self.on_finish else state), err
            cur["step"] = None
            cur["finished_at"] = _now_iso()
            if state != "done" and cur["decision_status"] == "decided":
                cur["routing_status"] = state
            cur["elapsed_ms"] = int((time.perf_counter() - self._t0) * 1000)
            result = copy.deepcopy(cur)
            result["state"] = state
        if self.on_finish:  # 저장을 끝낸 뒤에 busy를 풀어, 완료 직후 조회에서 기록이 보이게 한다
            try:
                self.on_finish(result)
            except Exception as e:
                # 물리 순서는 이미 끝났다. 결과와 실제 분류함은 보존하되 저장 실패를 노출한다.
                result["state"] = "error"
                result["persistence_error"] = f"{type(e).__name__}: {e}"
                result["error"] = "; ".join(filter(None, [result["error"],
                    f"기록 저장 실패: {result['persistence_error']}"]))
                with self._lock:
                    cur.update(error=result["error"],
                               persistence_error=result["persistence_error"])
        self._emit("finish", result["state"])
        with self._lock:
            result["events"] = copy.deepcopy(cur["events"])
            self._last = result
            self._cur = None
            self._paused = False
            self._busy = False
        return copy.deepcopy(result)
