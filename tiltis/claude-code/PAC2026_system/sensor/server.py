"""센서 서버 (../CONTRACT.md). 기본 포트 8001.

    python server.py                       # 실제 카메라
    python server.py --fake-rig            # 카메라 없이 (가짜 영상)

- 지금 판정은 품질 검사만 한다(quality.py). 결함 판정 규칙은 시편 실험(Step 3) 뒤에 추가한다.
- calib/H_face<A|B>.json과 calib/roi_face<A|B>.json이 있으면 검사 영역 열화상 특징값도 기록한다.
- 이 서버가 카메라와 Boson 시리얼 포트를 독점한다. capture_app.py와 동시에 실행하지 말 것.
"""
import argparse
import json
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import quality
import rules
import evidence
import live
import locate
import marker
import objects
from depth import OrbbecDepthSource, summarize as summarize_depth
from registration import CALIB_DIR, Registration
from rig import validate_capture_name, CaptureSaveError, DEFAULT_DATA_ROOT

sys.stdout.reconfigure(encoding="utf-8")


class InspectRequest(BaseModel):
    session: str = "demo"
    specimen_id: str
    face: Literal["A", "B", "C"]  # 3면 테이프 검사용 C(스테이션 FACES=A,B,C)
    attempt: Literal[0, 1] = 0
    trigger_id: str | None = None
    single_stationary_specimen: bool = False

    @field_validator("session", "specimen_id")
    @classmethod
    def validate_name(cls, value):
        return validate_capture_name(value)

    @field_validator("trigger_id")
    @classmethod
    def validate_trigger(cls, value):
        return validate_capture_name(value) if value is not None else None


def load_roi(face):
    p = CALIB_DIR / f"roi_face{face}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def create_app(rig_factory, depth_factory=None, depth_required=False, depth_max_age_s=2.0):
    """rig_factory: 호출하면 Rig(또는 FakeRig)를 돌려주는 함수. 서버 시작 시 한 번 부른다."""
    state = {}
    lock = threading.Lock()  # 촬영은 한 번에 하나 (Boson 시리얼·카메라 공유)

    @asynccontextmanager
    async def lifespan(app):
        rig = rig_factory()
        state["rig"] = rig
        source = None
        try:
            rig.set_ffc_manual(True)  # 촬영 직전에만 FFC
            source = depth_factory() if depth_factory else None
            state["depth"] = source
            if source:
                source.start()
            app.mount("/captures", StaticFiles(directory=str(rig.cfg.data_root), check_dir=False), name="captures")
            yield
        finally:
            try:
                if source:
                    source.close()
            finally:
                rig.close()  # 수동 FFC를 자동으로 되돌린다

    app = FastAPI(title="PAC2026 sensor", lifespan=lifespan)

    @app.get("/health")
    def health():
        rig = state["rig"]
        h = rig.health()
        source = state.get("depth")
        depth_ok = source.health(depth_max_age_s) if source else False
        return {"ok": all(h.values()) and (depth_ok or not depth_required), "sensors": {**h, "depth": depth_ok},
                "depth_enabled": source is not None, "depth_required": depth_required,
                "capture_mode": "simulated" if rig.boson_info.get("part_number") == "FAKE" else "live",
                "boson_part": rig.boson_info.get("part_number"),
                "ffc_mode": "manual" if rig.ffc_manual else "auto",
                "rules_version": quality.RULES_VERSION}

    def object_check(vis, lwir, depth_mm):
        """같은 물체 확인(objects.py). 배경이 없으면 None. 기록·화면용이며 판정에는 쓰지 않는다."""
        bg = objects.load_background_cached()
        if vis is None or lwir is None or (bg is None and depth_mm is None):
            return None  # 배경도 깊이도 없으면 물체를 찾을 방법이 없다
        dets = objects.detect_all(bg, vis, lwir, depth_mm)
        sizes = {"lwir": (lwir.shape[1], lwir.shape[0]),
                 "depth": (depth_mm.shape[1], depth_mm.shape[0]) if depth_mm is not None else (1, 1)}
        return dets, objects.associate(dets, objects.load_map(), sizes)

    def preview_all():
        vis, lwir = state["rig"].preview()
        f = state["depth"].latest() if state.get("depth") is not None else None
        return vis, lwir, (f.raw.astype(np.float32) * f.scale_mm if f is not None else None)

    @app.post("/object/background")
    def object_background():
        """물체를 모두 치운 상태에서 호출: 지금 화면을 빈 장면으로 저장한다."""
        vis, lwir, depth_mm = preview_all()
        if vis is None or lwir is None:
            raise HTTPException(503, "프레임 없음")
        objects.save_background(vis, lwir, depth_mm)
        return {"ok": True, "depth": depth_mm is not None}

    @app.post("/object/map-point")
    def object_map_point():
        """물체를 한 곳에 놓고 호출: 카메라 사이 위치 대응점을 추가한다(4곳 이상)."""
        obj = object_check(*preview_all())
        if obj is None:
            raise HTTPException(409, "배경이 없음. 먼저 /object/background")
        m, msg = objects.add_map_point(obj[0])
        return {"ok": m is not None, "message": msg, "points": len((m or objects.load_map() or {}).get("points", []))}

    @app.get("/object/locate")
    def object_locate(frames: int = 5, save_debug: int = 0):
        """깊이로 집기 영역의 상자(손잡이 포함) 위치·방향. 깊이 카메라 좌표(mm). 로봇 집기(방식 C)용."""
        source = state.get("depth")
        if source is None:
            raise HTTPException(409, "깊이 카메라가 꺼져 있음(run_sensor -Depth)")
        intr = getattr(source, "intrinsics", None)
        if not intr:
            raise HTTPException(503, "깊이 카메라 내부 파라미터 없음")
        stack, frame_times, t = [], [], time.time() - 1e-3
        for _ in range(max(1, min(frames, 15))):  # 새 프레임 여러 장의 중앙값(잡음·빈칸 줄이기)
            f = source.next_after(t)
            t = f.received_at_s
            frame_times.append(t)
            stack.append(f.raw.astype(np.float32) * f.scale_mm)
        arr = np.stack(stack)
        valid = np.isfinite(arr) & (arr > 0)
        # 무효 깊이를 중앙값 계산에서 제외한다. 일반 median은 NaN 하나만 있어도 유효한 과반까지 지운다.
        median = np.ma.median(np.ma.array(arr, mask=~valid), axis=0).filled(0)
        mm = np.where(valid.sum(0) >= max(1, len(stack) // 2 + 1), median, 0)
        if save_debug:  # 현장 진단: 이 깊이 영상을 저장해 두고 나중에 locate를 다시 돌려 볼 수 있다
            dbg_dir = DEFAULT_DATA_ROOT / "locate_debug"
            dbg_dir.mkdir(parents=True, exist_ok=True)
            dbg_path = dbg_dir / time.strftime("depth_%Y%m%d_%H%M%S.npy")
            np.save(dbg_path, np.nan_to_num(mm).astype(np.float32))
        cfg = objects.load_config()
        if cfg.get("locate_mode") == "front":  # 카메라를 세워 둬서 윗면 안쪽이 잘 안 보일 때(앞면 + 상자 크기)
            result = locate.locate_box_front_any(np.nan_to_num(mm), intr, cfg.get("boxes_mm") or [cfg["box_mm"]],
                                                 tab_height_mm=cfg["tab_height_mm"], pick_roi=cfg.get("pick_roi_depth"),
                                                 table_roi=cfg.get("table_roi_depth"),
                                                 near_far=tuple(cfg["near_far_mm"]), downsample=cfg.get("locate_downsample", 2))
        else:
            result = locate.locate_box(np.nan_to_num(mm), intr, pick_roi=cfg.get("pick_roi_depth"), table_roi=cfg.get("table_roi_depth"), near_far=tuple(cfg["near_far_mm"]),
                                       downsample=cfg.get("locate_downsample", 2))
        result = locate.public(result)
        # 중앙값 영상의 가장 오래된 프레임 시각으로 freshness를 보수적으로 검사한다.
        result.update(frames=len(stack), intrinsics=intr, captured_at_s=frame_times[0],
                      last_frame_at_s=t, time=time.time())
        if save_debug:
            result["debug_depth_file"] = str(dbg_path)
        return result

    @app.get("/object/status")
    def object_status():
        obj = object_check(*preview_all())
        if obj is None:
            return {"background": False}
        return {"background": True, "association": obj[1], "detections": objects.to_dict(obj[0])}

    @app.get("/live.jpg")
    def live_jpg(specimen_id: str = ""):
        """RGB · 열화상 · (켜져 있으면) 깊이 3화면 실시간 합성. 촬영을 막지 않고 최신 프레임만 읽는다."""
        vis, lwir = state["rig"].preview()
        if vis is None:
            raise HTTPException(503, "RGB 프레임 없음")
        lines = []
        if specimen_id:
            info, found = marker.check(vis, specimen_id)
            vis = marker.draw(vis, found, info["marker_expected"])
            lines.append(f"{specimen_id} marker {info['marker_ids']} match={info['marker_match']}")
        depth, depth_mm = None, None
        if state.get("depth") is not None:
            f = state["depth"].latest()
            depth = (f.raw, f.scale_mm) if f is not None else (None, None)
            depth_mm = f.raw.astype(np.float32) * f.scale_mm if f is not None else None
        obj = object_check(vis, lwir, depth_mm)
        ok, buf = cv2.imencode(".jpg", live.compose(vis, lwir, depth, lines, obj), [cv2.IMWRITE_JPEG_QUALITY, 75])
        return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/inspect")
    def inspect(req: InspectRequest):
        t0 = time.time()
        trigger_id = req.trigger_id or uuid.uuid4().hex
        base = {"session": req.session, "specimen_id": req.specimen_id, "face": req.face,
                "attempt": req.attempt, "trigger_id": trigger_id}
        out, artifacts = None, {}
        try:
            with lock:
                requested_at_s = time.time()
                out, meta = state["rig"].capture_pair(req.session, req.specimen_id, req.face,
                                                      note=f"attempt={req.attempt};trigger_id={trigger_id}",
                                                      trigger_id=trigger_id, attempt=req.attempt)
                prefix = f"/captures/{req.session}/{out.name}"
                artifacts = {"rgb": prefix + "/vis.png", "lwir_raw": prefix + "/lwir_y16.npz",
                             "lwir_preview": prefix + "/lwir_preview.png", "metadata": prefix + "/meta.json"}
                for key, expected in (("session", req.session), ("specimen_id", req.specimen_id), ("face", req.face)):
                    if meta.get(key) != expected:
                        raise ValueError(f"촬영 메타데이터의 시료 연결 불일치: {key}")
                if meta.get("trigger_id") not in (None, trigger_id):
                    raise ValueError("다른 트리거의 저장 촬영물을 현재 검사로 재사용하지 않음")
                meta.update(trigger_id=trigger_id, attempt=req.attempt)
                (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                depth_frame, depth_error = None, None
                if state.get("depth"):
                    try:
                        depth_frame = state["depth"].next_after(requested_at_s)
                    except Exception as e:
                        depth_error = f"{type(e).__name__}: {e}"
                if depth_frame is not None:
                    np.savez_compressed(out / "depth_raw.npz", raw=depth_frame.raw)
                    artifacts["depth_raw"] = prefix + "/depth_raw.npz"
                    meta["depth"] = {"scale_mm_per_unit": depth_frame.scale_mm,
                        "received_at_s": depth_frame.received_at_s,
                        "device_timestamp_ms": depth_frame.device_timestamp_ms,
                        "frame_index": getattr(depth_frame, "frame_index", None),
                        "device_clock_epoch": getattr(depth_frame, "device_clock_epoch", 0),
                        "raw_file": artifacts["depth_raw"], "unit": "mm",
                        "status": "assessment_pending"}
                    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            vis = cv2.imdecode(np.frombuffer((out / "vis.png").read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            if vis is None:
                raise ValueError("RGB 이미지 읽기 실패")
            with np.load(out / "lwir_y16.npz") as archive:
                stack = archive["stack"]
            verdict, reasons, features = quality.judge(vis, stack)
            features.update(marker.check(vis, req.specimen_id)[0])  # 시편 ID 마커: 기록만 하고 판정에는 쓰지 않는다
            obj = object_check(vis, stack.astype(np.float32).mean(axis=0),
                               depth_frame.raw.astype(np.float32) * depth_frame.scale_mm if depth_frame is not None else None)
            if obj is not None:  # 3카메라 같은 물체 확인: 기록만 한다
                features.update(objects.features(*obj))
            quality_verdict, quality_reasons = verdict, list(reasons)
            rule_cfg = rules.load()
            if rule_cfg and verdict != "unmeasurable":  # 테이프·냉매 규칙(검증 전이면 기록만 하고 review)
                ruled = rules.judge_face(req.face, vis, stack.astype(np.float32).mean(axis=0), rule_cfg)
                if ruled is not None:
                    verdict, reasons, rule_features = ruled
                    reasons = list(reasons)
                    features.update(rule_features)
            roi = load_roi(req.face)
            registration_info = {"status": "missing", "rgb_lwir_aligned": False, "depth_rgb_aligned": False}
            if roi and (CALIB_DIR / f"H_face{req.face}.json").exists():
                registration = Registration.load(req.face)
                features.update(quality.roi_features(stack.astype(np.float32).mean(axis=0),
                                                     registration, roi))
                registration_info.update(status="available_unvalidated", calibration=registration.meta,
                                         roi_features_recorded=True)
            prefix = f"/captures/{req.session}/{out.name}"
            depth_policy_path = CALIB_DIR / f"depth_policy_face{req.face}.json"
            depth_policy = json.loads(depth_policy_path.read_text(encoding="utf-8")) if state.get("depth") and depth_policy_path.exists() else None
            depth_info = {"enabled": state.get("depth") is not None, "status": "missing" if state.get("depth") else "disabled",
                          "unit": "mm", "coordinate_frame": "depth_pixels_unaligned_to_rgb", "error": depth_error}
            if depth_frame is not None:
                depth_info = summarize_depth(depth_frame, time.time(), depth_max_age_s, depth_policy)
                depth_info["device"] = getattr(state["depth"], "device_info", {})
                if depth_frame.received_at_s <= requested_at_s:
                    depth_info.update(status="stale", pose_gate="unavailable", reasons=["depth_before_trigger"])
                depth_info["raw_file"] = artifacts["depth_raw"]
                meta["depth"] = depth_info
                features.update(depth_median_mm=depth_info["median_mm"], depth_valid_fraction=depth_info["valid_fraction"])
            if depth_required and depth_info["status"] != "valid":
                verdict = "unmeasurable"
                reasons += depth_info.get("reasons") or ["depth_missing"]
            if depth_info.get("pose_gate") == "out_of_range" or (
                    depth_policy and depth_policy.get("validated") is True and depth_info["status"] != "valid"):
                verdict = "unmeasurable"
                reasons += depth_info.get("reasons") or ["depth_missing"]
            timing_path = CALIB_DIR / "timing_policy.json"
            timing_policy = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else None
            sensor_data = evidence.build(vis, stack, meta, depth_info, prefix, timing_policy, registration_info)
            sensor_data["association"] = {**base, "capture_id": out.name,
                "requested_at_s": requested_at_s, "completed_at_s": time.time(),
                "single_stationary_specimen_asserted_by_caller": req.single_stationary_specimen,
                "automatic_visual_reidentification": False, "same_object_independently_verified": False,
                "status": "linked_by_request_only",
                "precondition": "한 개의 시료를 세 센서의 시야에 고정하고 촬영 종료까지 교체·이동하지 않음"}
            observed_times = [sensor_data["rgb"]["received_at_s"], sensor_data["lwir"]["received_first_s"],
                              sensor_data["lwir"]["received_last_s"]]
            if any(type(t) not in (int, float) or not requested_at_s <= t <= sensor_data["association"]["completed_at_s"] for t in observed_times):
                verdict = "unmeasurable"
                reasons += ["frame_outside_trigger_window"]
                sensor_data["association"]["status"] = "invalid_trigger_window"
            elif depth_info["status"] in ("stale", "invalid", "missing"):
                sensor_data["association"]["status"] = "depth_unavailable"
            elif req.single_stationary_specimen and sensor_data["timing"]["status"] == "within_limit":
                sensor_data["association"]["status"] = "linked_under_stationary_specimen_precondition"
            if sensor_data["timing"]["status"] == "invalid":
                verdict = "unmeasurable"
                reasons += sensor_data["timing"]["reasons"]
            reasons = list(dict.fromkeys(reasons))
            sensor_data["assessment"].update(capture_quality_ok=quality_verdict != "unmeasurable",
                capture_quality_reasons=quality_reasons, final_verdict=verdict, final_reasons=reasons,
                depth_required=depth_required)
            sensor_data["assessment"].update(
                defect_rules_available=bool(rule_cfg and rule_cfg.get("validated") is True),
                defect_inspected=features.get("defect_inspected") is True,
                defect_rules_version=features.get("defect_rules_version"))
            features["rules_version"] = (features["defect_rules_version"] if features.get("defect_inspected") is True
                                         else quality.RULES_VERSION)
            features["simulated"] = sensor_data["simulated"]
            meta["sensor_data"] = sensor_data
            (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            result = {
                "status": "ok", "error": None, **base,
                "verdict": verdict, "reasons": reasons, "features": features,
                "sensor_data": sensor_data, "artifacts": artifacts,
                "capture_id": out.name,
                "images": {"rgb": f"/captures/{req.session}/{out.name}/vis.png",
                           "lwir": f"/captures/{req.session}/{out.name}/lwir_preview.png"},
                "elapsed_ms": round((time.time() - t0) * 1000),
            }
            (out / "inspect.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            return result
        except Exception as e:  # 계약: 오류도 HTTP 200 + status "error"
            if isinstance(e, CaptureSaveError):
                out = e.capture_path
                prefix = f"/captures/{req.session}/{out.name}"
                artifacts = {key: prefix + "/" + filename for key, filename in (
                    ("request_metadata", "capture_request.json"), ("metadata", "meta.json"),
                    ("rgb", "vis.png"), ("lwir_raw", "lwir_y16.npz"), ("lwir_preview", "lwir_preview.png"))
                    if (out / filename).is_file()}
            result = {"status": "error", "error": f"{type(e).__name__}: {e}", **base, "verdict": None,
                      "reasons": [], "features": {}, "capture_id": out.name if out is not None else None,
                      "images": {key: artifacts[file] for key, file in (("rgb", "rgb"), ("lwir", "lwir_preview")) if file in artifacts},
                      "artifacts": artifacts, "elapsed_ms": round((time.time() - t0) * 1000)}
            if out is not None:
                try:
                    (out / "inspect.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
                except Exception as save_error:
                    result["persistence_error"] = f"{type(save_error).__name__}: {save_error}"
            return result


    return app


def main():
    import uvicorn
    from pathlib import Path

    from rig import DEFAULT_DATA_ROOT, Rig, RigConfig

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    ap.add_argument("--vis-res", default="1600x1200")
    ap.add_argument("--fake-rig", action="store_true", help="카메라 없이 가짜 영상으로 실행")
    ap.add_argument("--blur-faces", default="", help="가짜 모드에서 흐리게 만들 면 (예: A)")
    ap.add_argument("--depth", action="store_true", help="선택 Orbbec 깊이 취득(기본 꺼짐)")
    ap.add_argument("--require-depth", action="store_true", help="깊이 누락/무효 시 측정 불가 처리")
    args = ap.parse_args()
    w, h = map(int, args.vis_res.lower().split("x"))
    cfg = RigConfig(vis_width=w, vis_height=h, data_root=Path(args.data_root))
    if args.fake_rig:
        from fake_rig import FakeRig
        factory = lambda: FakeRig(cfg, blur_faces=tuple(args.blur_faces))  # noqa: E731
    else:
        factory = lambda: Rig(cfg)  # noqa: E731
    if args.require_depth and not args.depth:
        ap.error("--require-depth는 --depth와 함께 사용")
    if args.fake_rig and args.depth:
        ap.error("--fake-rig에서는 실제 --depth를 열지 않음. 모의 depth는 테스트 주입으로 사용")
    uvicorn.run(create_app(factory, OrbbecDepthSource if args.depth else None, args.require_depth),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
