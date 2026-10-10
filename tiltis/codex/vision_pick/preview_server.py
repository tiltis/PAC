"""Integrated source + current camera server preview. No robot or camera handles."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import json
import time
from pathlib import Path

from bootstrap import station_path

STATION_SOURCE = station_path()
import grasp
import handeye
from guard import GuardedVisionPicker, observation_error
from sensor_client import SensorClient

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PAC 카메라 · 검사 결과</title><style>body{font:16px system-ui;background:#111827;color:#e5e7eb;margin:24px}main{max-width:1506px;margin:auto}h1{font-size:24px}img{width:100%;display:block}button{padding:12px;font-size:16px}pre{white-space:pre-wrap;background:#1f2937;padding:16px}p{line-height:1.6}a{color:#93c5fd}.card{background:#1f2937;border:1px solid #475569;border-radius:12px;padding:18px;margin:18px 0}.decision{font-size:23px;font-weight:700;margin:10px 0}.decision.red{color:#fca5a5}.decision.blue{color:#93c5fd}.note{font-size:14px;color:#cbd5e1}#decisionReasons{padding-left:22px;line-height:1.9}details{margin:14px 0}</style>
<main><h1>PAC — 카메라 · 검사 결과</h1>
<p>RGB / 열화상 / 깊이 실시간 화면 · <a href="http://127.0.0.1:8000/">검사 스테이션 열기</a></p>
<img id="cam" alt="RGB · 열화상 · 깊이 실시간 카메라" src="/camera.jpg">
<p class="note" id="cameraNote">빨간 테두리: 가운데 흰 영역의 상자 1개 · 양쪽 색 영역이 확인되지 않거나 후보가 여러 개면 표시를 보류합니다. 판정 색상과 별개입니다.</p>
<section class="card" aria-live="polite"><h2>최근 검사 판정</h2><p class="note" id="stationState">스테이션 연결 중…</p>
<details id="stationErrorBox" hidden><summary>현재 실행 오류 상세</summary><p class="note" id="stationError"></p></details>
<div id="decision" class="decision">결과 확인 중…</div><ul id="decisionReasons"></ul>
<p class="note" id="decisionSource"></p></section>
<details><summary>상자 위치·방향 및 새 제어 코드 준비 상태</summary>
<p class="note">새 SAM 각도 정렬 코드의 준비 검사입니다. 실제 실행과 판정은 기존 스테이션 기준입니다.</p>
<button onclick="check()">상자 위치·방향 확인</button><pre id="result">확인 버튼을 누르세요.</pre></details>
<details><summary>SAM 윗면 — 저장 사진 검증</summary>
<p>Colab GPU의 저장 사진 결과입니다. 현재 영상 추적이나 로봇 이동 상태를 뜻하지 않습니다. 영상 변 각도와 로봇 각도는 다릅니다.</p>
<img src="/sam-preview.png"><details><summary>SAM 사진 검증 상세</summary><pre id="samResult">저장 결과 확인 중…</pre></details></details>
<script src="/inspection-presentation.js"></script><script>
const cam=document.getElementById('cam');
let cameraStarted=performance.now(),cameraTimer=null;
function nextCamera(){clearTimeout(cameraTimer);if(document.hidden)return;cameraStarted=performance.now();cam.src='/camera.jpg?t='+Date.now()}
function scheduleCamera(delay){clearTimeout(cameraTimer);if(!document.hidden)cameraTimer=setTimeout(nextCamera,delay)}
cam.onload=()=>{document.getElementById('cameraNote').textContent='빨간 테두리: 가운데 흰 영역의 상자 1개 · 양쪽 색 영역이 확인되지 않거나 후보가 여러 개면 표시를 보류합니다. 판정 색상과 별개입니다.';scheduleCamera(Math.max(0,1000/15-(performance.now()-cameraStarted)))};
cam.onerror=()=>{document.getElementById('cameraNote').textContent='카메라 연결 확인 중…';scheduleCamera(2000)};
document.addEventListener('visibilitychange',()=>{clearTimeout(cameraTimer);if(!document.hidden)nextCamera()});
async function check(){result.textContent='깊이 측정 중…';try{let r=await fetch('/api/preview');result.textContent=JSON.stringify(await r.json(),null,2)}catch(e){result.textContent=String(e)}}
async function refreshDecision(){
 const title=document.getElementById('decision'), list=document.getElementById('decisionReasons'), source=document.getElementById('decisionSource');
 try{
  const response=await fetch('/api/inspection-summary',{cache:'no-store'});if(!response.ok)throw Error('station unavailable');
  const data=await response.json();
  const status=data.status, current=status.current || status.last_result;
  const stateLabels={idle:'검사 대기',running:'검사 진행 중',saving:'검사 기록 저장 중',done:'최근 실행 완료',error:'최근 실행 오류',aborted:'최근 실행 중단'};
  document.getElementById('stationState').textContent=(stateLabels[status.state]||'상태 확인 필요')+(current?' · 시료 '+current.specimen_id:'');
  document.getElementById('stationErrorBox').hidden=!current?.error;
  document.getElementById('stationError').textContent=current?.error||'';
  const run=data.decision; list.replaceChildren();title.className='decision';source.textContent='';
  if(!run){title.textContent='저장된 판정 없음';return}
  const summary=PacReasons.summarizeRun(run);
  title.textContent=summary.title;title.className='decision '+(run.bin==='human'?'red':run.bin==='ok'?'blue':'');
  for(const detail of summary.lines){const li=document.createElement('li');li.textContent=detail;list.appendChild(li)}
  source.textContent='시료 '+run.specimen_id+' · '+(run.finished_at||run.started_at||'')+' · 저장된 검사 결과 (현재 카메라 화면과 별개)';
 }catch(e){document.getElementById('stationState').textContent='스테이션 연결 확인 필요';document.getElementById('stationErrorBox').hidden=true;title.textContent='검사 결과를 불러올 수 없습니다';title.className='decision';list.replaceChildren();source.textContent=''}
 finally{setTimeout(refreshDecision,2500)}
}
refreshDecision();
fetch('/api/sam-result').then(r=>r.json()).then(v=>samResult.textContent=JSON.stringify(v,null,2)).catch(e=>samResult.textContent=String(e));</script></main></html>"""


def create_preview_app(site_dir, sensor_url="http://127.0.0.1:8001", sensor=None, sam_result_dir=None,
                       station_url="http://127.0.0.1:8000"):
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
    # Reuse local connections across frames instead of constructing an HTTP
    # client (and its certificate store) for every image and result query.
    upstream = httpx.Client(timeout=5, trust_env=False)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            upstream.close()

    app = FastAPI(title="PAC integrated preview (no motion)", lifespan=lifespan)
    app.state.preview_http = upstream

    @app.get('/inspection-presentation.js')
    def inspection_presentation():
        html = (STATION_SOURCE / 'web/index.html').read_text(encoding='utf-8')
        start, end = '// PAC_REASON_PRESENTATION_START', '// PAC_REASON_PRESENTATION_END'
        if start not in html or end not in html:
            raise HTTPException(503, 'Inspection presentation unavailable')
        script = html.split(start, 1)[1].split(end, 1)[0]
        return Response(script, media_type='application/javascript', headers={'Cache-Control':'no-store'})

    @app.get('/api/inspection-summary')
    def inspection_summary():
        # Existing station results only. Never calls inspection or motion endpoints.
        try:
            base = station_url.rstrip('/')
            status = upstream.get(base + '/api/status', timeout=3)
            status.raise_for_status()
            runs = upstream.get(base + '/api/runs', params={'limit': 30}, timeout=3)
            runs.raise_for_status()
            decision = next((dict(r) for r in runs.json() if r.get('final_verdict')), None)
            if decision:
                inspections = upstream.get(base + f"/api/runs/{int(decision['id'])}/inspections", timeout=3)
                inspections.raise_for_status()
                decision['inspections'] = inspections.json()
            return {'status': status.json(), 'decision': decision, 'motion_enabled': False}
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise HTTPException(503, 'Station result unavailable')

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
    def camera(specimen_id: str = ''):
        try:
            r = upstream.get(sensor_url.rstrip("/") + "/live.jpg",
                             params={'specimen_id': specimen_id, 'fast': 1})
            r.raise_for_status()
            from box_overlay import annotate_jpeg
            data, count = annotate_jpeg(r.content, central_white_only=True)
            return Response(data, media_type="image/jpeg", headers={
                'Cache-Control': 'no-store', 'X-Box-Candidates': str(count),
                'X-Overlay-Role': 'display-only-central-white-box'})
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
