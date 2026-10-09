"""Integrated source + current camera server preview. No robot or camera handles."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bootstrap import station_path

station_path()
import grasp
import handeye
from guard import GuardedVisionPicker, observation_error
from sensor_client import SensorClient

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>PAC 통합 확인</title><style>body{font:16px system-ui;background:#111827;color:#e5e7eb;margin:24px}h1{font-size:24px}img{width:100%;max-width:1440px}button{padding:12px;font-size:16px}pre{white-space:pre-wrap;background:#1f2937;padding:16px}p{line-height:1.6}</style>
<h1>PAC — 통합 코드 · 현재 카메라</h1>
<p>로봇 이동 없음 · RGB / 열화상 / 깊이 화면 · 상자 위치/방향 및 준비 상태 확인</p>
<p>이 화면의 준비 검사는 새 각도 정렬 코드에 적용됩니다. 기존 실기 설정과 실행 기록은 <a href="http://127.0.0.1:8000/">8000 스테이션</a>에서 확인합니다. 별도 XYZ 범위가 없다는 결과는 기존 반경 제한·보정·성공 기록이 없다는 뜻이 아닙니다.</p>
<img id="cam" src="/camera.jpg"><p><button onclick="check()">상자 위치·방향 확인</button></p>
<details><summary>현재 상자 · 제어 준비 상세</summary><pre id="result">확인 버튼을 누르세요.</pre></details>
<h2>SAM 윗면 — 저장 사진 검증</h2>
<p>Colab GPU의 저장 사진 결과입니다. 현재 영상 추적이나 로봇 이동 상태를 뜻하지 않습니다. 영상 변 각도와 로봇 각도는 다릅니다.</p>
<img src="/sam-preview.png"><details><summary>SAM 사진 검증 상세</summary><pre id="samResult">저장 결과 확인 중…</pre></details>
<script>setInterval(()=>cam.src='/camera.jpg?t='+Date.now(),1500);
async function check(){result.textContent='깊이 측정 중…';try{let r=await fetch('/api/preview');result.textContent=JSON.stringify(await r.json(),null,2)}catch(e){result.textContent=String(e)}}check();
fetch('/api/sam-result').then(r=>r.json()).then(v=>samResult.textContent=JSON.stringify(v,null,2)).catch(e=>samResult.textContent=String(e));</script></html>"""


def create_preview_app(site_dir, sensor_url="http://127.0.0.1:8001", sensor=None, sam_result_dir=None):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, Response
    import httpx

    site = Path(site_dir)
    cfg = dict(grasp.DEFAULTS)
    site_cfg = {}
    config_path = site / "station/calib/grasp_config.json"
    if config_path.exists():
        site_cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
        cfg.update(site_cfg)
    he = handeye.load(site / "station/calib/handeye.json")
    reader = sensor or SensorClient(sensor_url)
    picker = GuardedVisionPicker(reader, he, dry_run=True, cfg=cfg)
    app = FastAPI(title="PAC integrated preview (no motion)")

    @app.get('/api/sam-result')
    def sam_result():
        path = Path(sam_result_dir) / 'result.json' if sam_result_dir else None
        if path is None or not path.is_file():
            raise HTTPException(503,'Offline SAM result not configured')
        doc = json.loads(path.read_text(encoding='utf-8'))
        return dict(doc, mode='saved_photo_only', motion_enabled=False, robot_ready=False,
                    live_connected=False)

    @app.get('/sam-preview.png')
    def sam_preview():
        path = Path(sam_result_dir) / 'sam_top_preview.png' if sam_result_dir else None
        if path is None or not path.is_file():
            raise HTTPException(503,'Offline SAM image not configured')
        return Response(path.read_bytes(),media_type='image/png',headers={'Cache-Control':'no-store'})

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/camera.jpg")
    def camera():
        try:
            r = httpx.get(sensor_url.rstrip("/") + "/live.jpg", timeout=5)
            r.raise_for_status()
            return Response(r.content, media_type="image/jpeg")
        except Exception as e:
            raise HTTPException(503, f"Camera preview unavailable: {type(e).__name__}")

    @app.get("/api/preview")
    def preview():
        loc = reader.locate()
        observed = observation_error(loc, time.time(), picker.limits)
        ready = picker.preflight_ready()
        orientation = None
        if loc.get("found") and he is not None:
            try:
                import numpy as np
                point, _ = grasp.camera_grasp_point(loc, cfg)
                approach, jaw, yaw, _ = grasp.side_box_alignment(loc, he, handeye.point(he, point))
                orientation = {"source": "depth_camera_box_axes", "yaw_deg": round(float(np.degrees(yaw)), 1),
                               "approach_axis_base": approach.tolist(), "jaw_axis_base": jaw.tolist(),
                               "verified_for_motion": False}
            except (ValueError, TypeError, KeyError) as e:
                orientation = {"error": str(e)}
        field_limits = {key: site_cfg[key] for key in (
            "grasp_mode", "side_reach_r_m", "side_min_tip_z_mm", "side_jaw_offset_frame_m",
            "side_approach_mm", "side_lift_mm", "side_max_joint_jump_deg", "max_roll_jump_deg"
        ) if key in site_cfg}
        return {"motion_enabled": False, "mode": "preview_only", "readiness": ready,
                "readiness_scope": "new_box_alignment_guard",
                "existing_field_limits": field_limits,
                "cartesian_workspace_present": isinstance(site_cfg.get("workspace"), dict),
                "observation_check": observed, "orientation_candidate": orientation, "locate": loc,
                "sam_live_connected": False,
                "sam_live_reason": "verified RGB-depth registration and paired frames not configured",
                "code_dir": str(Path(__file__).resolve().parents[2] / "claude-code/PAC2026_system"),
                "calibration_dir": str(site)}

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-dir", required=True)
    ap.add_argument("--sensor-url", default="http://127.0.0.1:8001")
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument('--sam-result-dir', help='Read-only saved Colab result; never a live control input')
    args = ap.parse_args()
    import uvicorn
    uvicorn.run(create_preview_app(args.site_dir, args.sensor_url, sam_result_dir=args.sam_result_dir), host="127.0.0.1", port=args.port)
