"""Pick approach settings and offline preview through the station's existing owner.

No endpoint moves the robot or changes torque. Recording home only reads joints.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

import kinematics as K
from clearance_transfer import _q, _sample_joint_segment

DEFAULT = {"mode": "legacy", "height_offset_mm": 0.0}


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["legacy", "home_descend_forward"]
    height_offset_mm: float = Field(default=0.0, ge=-10.0, le=30.0)
    preview_id: str | None = None


def home_info(joints, joint_map=None):
    try:
        model = K.SO101()
        q = _q(joints, joint_map, "home")
        tcp = (model.fk(q)[:3, 3] * 1000).round(2).tolist()
        violations = []
        for i, name in enumerate(K.ARM_JOINTS):
            if not model.lower[i] <= q[i] <= model.upper[i]:
                violations.append(f"{name}: {np.degrees(q[i]):.2f}°, 허용 {np.degrees(model.lower[i]):.2f}~{np.degrees(model.upper[i]):.2f}°")
        return {"valid": not violations, "tcp_mm": tcp,
                "reason": "home 관절 범위 확인 필요: " + "; ".join(violations) if violations else None}
    except (ValueError, TypeError, KeyError) as exc:
        return {"valid": False, "tcp_mm": None, "reason": f"home 자세 확인 필요: {exc}"}


class HomePathPicker:
    """Keep the installed vision picker, with an explicit optional approach policy."""
    def __init__(self, original, settings):
        self.original, self.settings = original, settings

    def __getattr__(self, name):
        return getattr(self.original, name)

    def validate_home_path_start(self, home):
        if self.settings()["mode"] == "legacy":
            return None
        if self.settings().get("needs_preview"):
            raise ValueError("home 또는 설정이 바뀌었습니다. 경로 미리보기 후 다시 적용해 주세요")
        info = home_info(home, self.joint_map)
        if not info["valid"]:
            raise ValueError(info["reason"])
        if self.cfg.get("grasp_mode") != "side" or self.cfg.get("side_use_absolute_z") is not True:
            raise ValueError("수직 하강 접근은 책상 Z=0으로 보정한 옆집기 설정이 필요합니다")
        return {"ok": True}

    def plan(self, loc):
        settings = self.settings()
        if settings["mode"] == "legacy":
            return self.original.plan(loc)
        candidate = copy.copy(self.original)
        candidate.cfg = copy.deepcopy(self.original.cfg)
        candidate.cfg["side_tcp_offset_mm"] = float(candidate.cfg.get("side_tcp_offset_mm", 0)) + settings["height_offset_mm"]
        candidate.cfg["side_approach_up_mm"] = 0.0
        result = candidate.plan(loc)
        result["pick_path_mode"] = settings["mode"]
        result["height_offset_mm"] = settings["height_offset_mm"]
        return result

    def plan_home_path(self, plan, home):
        if self.settings()["mode"] == "legacy":
            return None
        self.validate_home_path_start(home)
        from home_approach import plan_home_approach
        model, joint_map = K.SO101(), self.joint_map
        approach = _q(plan["approach"], joint_map, "approach")
        grasp = _q(plan["grasp"], joint_map, "grasp")
        a, g = model.fk(approach), model.fk(grasp)
        if abs(float(a[2, 3] - g[2, 3])) > 0.001:
            raise ValueError("접근점과 집기점 높이가 달라 수평 전진할 수 없습니다")
        floor = float(self.cfg.get("side_min_tip_z_mm", 10.0)) / 1000
        # The final existing approach->grasp move must also stay on the horizontal line.
        delta = g[:3, 3] - a[:3, 3]
        for q in _sample_joint_segment(approach, grasp):
            p = model.fk(q)[:3, 3]
            fraction = float(np.clip(np.dot(p - a[:3, 3], delta) / max(np.dot(delta, delta), 1e-12), 0, 1))
            if abs(float(p[2] - a[2, 3])) > 0.001 or np.linalg.norm(p - (a[:3, 3] + fraction * delta)) > 0.001 or p[2] < floor - 1e-6:
                raise ValueError("마지막 집기 접근이 수평 직선/바닥 여유 조건을 벗어납니다")
        return plan_home_approach(home, plan["approach"], joint_map=joint_map,
                                  table_z_m=0.0, min_tip_clearance_mm=floor * 1000)


class PickPathService:
    def __init__(self, seq, path):
        self.seq, self.path = seq, Path(path)
        self.value = dict(DEFAULT)
        self.accepted_geometry = None
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.accepted_geometry = saved.pop("accepted_geometry_sha256", None)
            self.value = PathSettings.model_validate(saved).model_dump(exclude={"preview_id"})
        self.preview = None
        self.bind_picker(seq.picker)

    def bind_picker(self, original):
        """Keep optional station entry points bound to the same executed picker."""
        if isinstance(original, HomePathPicker):
            original = original.original
        self.picker = HomePathPicker(original, self.execution_settings) if original is not None else None
        self.seq.picker = self.picker
        self.preview = None

    @contextmanager
    def idle(self):
        with self.seq._lock:
            if self.seq._busy or getattr(self.seq, "_configuration_active", False):
                raise HTTPException(409, "실행 중에는 집기 경로를 설정할 수 없습니다")
            self.seq._configuration_active = True
        try:
            yield
        finally:
            with self.seq._lock:
                self.seq._configuration_active = False

    def home(self):
        return (getattr(self.seq.robot, "poses", None) or {}).get("joints", {}).get("home")

    def execution_settings(self):
        return {**self.value, "needs_preview": self.value["mode"] == "home_descend_forward"
                and self.accepted_geometry != self.fingerprint()}

    def settings(self):
        return {**self.execution_settings(), "home": home_info(self.home(), getattr(self.picker, "joint_map", None)),
                "busy": self.seq.busy or getattr(self.seq, "_configuration_active", False)}

    def fingerprint(self):
        value = {"poses": self.seq.robot.poses, "cfg": getattr(self.picker, "cfg", None),
                 "he": getattr(self.picker, "he", None), "joint_map": getattr(self.picker, "joint_map", None)}
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=lambda x: x.tolist()).encode()).hexdigest()

    def preview_path(self, request):
        with self.idle():
            self.preview = None
            info = self.settings()["home"]
            try:
                if self.picker is None:
                    raise ValueError("비전 집기 모드에서만 경로 미리보기를 사용할 수 있습니다")
                proposed = request.model_dump(exclude={"preview_id"})
                proposed["mode"] = "home_descend_forward"
                picker = HomePathPicker(self.picker.original, lambda: proposed)
                picker.validate_home_path_start(self.home())
                loc = picker.locate()
                plan = picker.plan(loc)
                if not plan.get("ok"):
                    raise ValueError(plan.get("reason", "상자 집기점 계산 실패"))
                path = picker.plan_home_path(plan, self.home())
                token = uuid.uuid4().hex
                self.preview = (token, proposed, self.fingerprint(), time.monotonic())
                return {"ok": True, "home": info, "plan": path, "preview_id": token,
                        "grasp_point_mm": (np.asarray(plan["grasp_point_m"]) * 1000).tolist(),
                        "hardware_moved": False}
            except (ValueError, KeyError, TypeError) as exc:
                return {"ok": False, "home": info, "reason": str(exc), "hardware_moved": False}

    def apply(self, request):
        with self.idle():
            proposed = request.model_dump(exclude={"preview_id"})
            if request.mode == "home_descend_forward":
                record = self.preview
                if (not record or request.preview_id != record[0] or proposed != record[1]
                        or self.fingerprint() != record[2] or time.monotonic() - record[3] > 120):
                    raise HTTPException(409, "현재 설정으로 경로 미리보기를 다시 통과해야 합니다")
            accepted = self.fingerprint() if request.mode == "home_descend_forward" else None
            atomic_json(self.path, {**proposed, "accepted_geometry_sha256": accepted})
            self.accepted_geometry = accepted
            self.value, self.preview = proposed, None
        return self.settings()

    def record_home(self):
        with self.idle():
            robot = self.seq.robot
            path = Path(robot.poses_path)
            before = path.read_bytes()
            poses = json.loads(before.decode("utf-8-sig"))
            joints = robot.current_joints()  # existing COM owner; no connect, torque or motion call
            info = home_info(joints, getattr(self.picker, "joint_map", None))
            if not info["valid"] or info["tcp_mm"][2] < 10:
                raise HTTPException(422, info["reason"] or "home이 책상에 너무 가깝습니다")
            if path.read_bytes() != before:
                raise HTTPException(409, "다른 프로그램이 자세 파일을 변경했습니다. 다시 확인해 주세요")
            backup = path.with_name(path.name + ".before-home-" + uuid.uuid4().hex + ".bak")
            backup.write_bytes(before)
            poses.setdefault("joints", {})["home"] = joints
            # Persist invalidation before HOME changes: no restart can silently use
            # a newly taught HOME with an approval for the previous geometry.
            atomic_json(self.path, {**self.value, "accepted_geometry_sha256": None})
            self.accepted_geometry = None
            atomic_json(path, poses)
            robot.poses = poses
            self.preview = None
        return self.settings()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def register_pick_path(app, seq, base_dir):
    robot_path = Path(getattr(seq.robot, "poses_path", Path(base_dir) / "poses.json"))
    service = PickPathService(seq, robot_path.parent / "calib" / "pick_path.json")
    app.state.pick_path = service

    @app.get("/pick-path")
    def page():
        return FileResponse(Path(base_dir) / "web" / "pick_path.html")

    @app.get("/api/pick-path/settings")
    def settings():
        return service.settings()

    @app.post("/api/pick-path/preview")
    def preview(request: PathSettings):
        return service.preview_path(request)

    @app.put("/api/pick-path/settings")
    def apply(request: PathSettings):
        return service.apply(request)

    @app.post("/api/pick-path/home")
    def record_home():
        return service.record_home()
