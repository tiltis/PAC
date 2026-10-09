"""센서 서버 모의 구현(CONTRACT.md). 실행: uvicorn mock_sensor:app --port 8001"""
from __future__ import annotations

import io
import os
import random
import time
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont, ImageOps

SCENARIOS = ["all_ok", "suspect_B", "unmeasurable_once", "unmeasurable_twice", "sensor_error", "random"]

app = FastAPI(title="mock sensor")
state = {"scenario": os.environ.get("MOCK_SCENARIO", "all_ok"), "latency_s": 0.3}
captures: dict = {}  # capture_id -> {specimen, face, verdict}


class InspectReq(BaseModel):
    session: str
    specimen_id: str
    face: str
    attempt: int = 0
    trigger_id: str | None = None


class ScenarioReq(BaseModel):
    name: str


@app.post("/mock/scenario")
def set_scenario(req: ScenarioReq):
    if req.name not in SCENARIOS:
        return Response(status_code=422, content=f"알 수 없는 시나리오: {req.name}")
    state["scenario"] = req.name
    return {"scenario": req.name}


@app.get("/mock/scenario")
def get_scenario():
    return {"scenario": state["scenario"], "available": SCENARIOS}


@app.get("/health")
def health():
    return {"ok": True, "sensors": {"vis": True, "lwir": True, "depth": False},
            "boson_part": "MOCK", "ffc_mode": "manual"}


def pick_verdict(scenario: str, face: str, attempt: int) -> str:
    if scenario == "suspect_B" and face == "B":
        return "suspect"
    if scenario == "unmeasurable_once" and face == "A" and attempt == 0:
        return "unmeasurable"
    if scenario == "unmeasurable_twice" and face == "A":
        return "unmeasurable"
    if scenario == "random":
        return random.choices(["no_anomaly", "suspect", "unmeasurable"], [0.6, 0.2, 0.2])[0]
    return "no_anomaly"


REASONS = {"suspect": ["lid_gap_rgb", "lwir_local_contrast"], "unmeasurable": ["rgb_blur"]}


@app.post("/inspect")
def inspect(req: InspectReq):
    t0 = time.perf_counter()
    time.sleep(state["latency_s"])
    base = {"session": req.session, "specimen_id": req.specimen_id, "face": req.face,
            "attempt": req.attempt, "trigger_id": req.trigger_id}
    if state["scenario"] == "sensor_error":
        return {**base, "status": "error", "error": "mock: 카메라 연결 실패", "verdict": None,
                "reasons": [], "features": {}, "capture_id": None, "images": {}, "elapsed_ms": 0}
    verdict = pick_verdict(state["scenario"], req.face, req.attempt)
    suffix = f"_r{req.attempt}" if req.attempt else ""
    cid = f"{req.specimen_id}_{req.face}{suffix}_{datetime.now():%Y%m%d_%H%M%S}"
    captures[cid] = {"specimen": req.specimen_id, "face": req.face, "verdict": verdict}
    prefix = f"/captures/{req.session}/{cid}"
    return {
        **base, "status": "ok", "error": None, "verdict": verdict,
        "reasons": REASONS.get(verdict, []),
        "features": {"defect_inspected": True, "defect_rules_version": "mock-only-0.1", "simulated": True,
                     "rgb_sharpness": round(random.uniform(50, 200), 1),
                     "lwir_roi_delta": round(random.uniform(-15, 15), 1)},
        "capture_id": cid,
        "images": {"rgb": f"{prefix}/vis.png", "lwir": f"{prefix}/lwir_preview.png"},
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 구버전 Pillow
        return ImageFont.load_default()


def make_png(info: dict, thermal: bool) -> bytes:
    w, h = 320, 240
    if thermal:
        grad = ImageOps.invert(Image.radial_gradient("L").resize((w, h)))
        img = ImageOps.colorize(grad, black=(10, 0, 70), mid=(200, 40, 80), white=(255, 230, 40))
        kind = "LWIR (mock)"
    else:
        img = Image.new("RGB", (w, h), (92, 112, 100))
        kind = "RGB (mock)"
    d = ImageDraw.Draw(img)
    d.text((10, 10), kind, fill="white", font=_font(18))
    d.text((10, 100), f"{info['specimen']}  face {info['face']}", fill="white", font=_font(26))
    d.text((10, 140), info["verdict"], fill="yellow", font=_font(22))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/live.jpg")
def live(specimen_id: str = ""):
    return Response(content=make_png({"specimen": specimen_id or "LIVE", "face": "-", "verdict": "live (mock)"},
                                     thermal=False), media_type="image/png")


@app.get("/captures/{session}/{capture_id}/{name}")
def capture_image(session: str, capture_id: str, name: str):
    info = captures.get(capture_id, {"specimen": "?", "face": "?", "verdict": "unknown"})
    return Response(content=make_png(info, thermal=name.startswith("lwir")), media_type="image/png")
