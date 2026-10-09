"""스테이션 웹 앱. 실행: uvicorn app:app --host 0.0.0.0 --port 8000

환경변수: SENSOR_URL, ROBOT(mock|so101), ROBOT_PORT, ROBOT_ID, POSES, DB, MOCK_SPEED,
ADVISOR_URL(laya 서버 주소. 있으면 기록 전용 조언을 남긴다),
PICK_MODE(taught|vision), PICK_DRY_RUN(1이면 비전 집기 접근 위치까지만), HANDEYE(보정 파일 경로)
"""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, field_validator

from robot import BOX_TYPES, DEFAULT_POSES, RobotBase, make_robot
from advisor import from_env as advisor_from_env
from sensor_client import SensorClient
from sequencer import BusyError, Sequencer
from store import DEFAULT_DB, Store

BASE_DIR = Path(__file__).resolve().parent


class RunReq(BaseModel):
    specimen_id: str
    session: str = "demo"
    box_type: str = ""  # ""(공통) / "white" / "brown": 상자 종류별로 가르친 자세 세트

    @field_validator("specimen_id", "session")
    @classmethod
    def validate_name(cls, value, info):
        value = value.strip()
        if not value and info.field_name == "session":
            return "demo"
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}
        if not re.fullmatch(r"[\w.-]{1,80}", value) or ".." in value or value.startswith(".") or value.endswith(".") or (
                value.split(".", 1)[0].upper() in reserved):
            raise ValueError("시료·세션 이름은 문자·숫자·밑줄·하이픈·내부 점(최대 80자)만 허용")
        return value


def create_app(robot: Optional[RobotBase] = None, sensor_url: Optional[str] = None,
               db_path=None, durations: Optional[dict] = None) -> FastAPI:
    sensor_url = sensor_url or os.environ.get("SENSOR_URL", "http://127.0.0.1:8001")
    poses_path = Path(os.environ.get("POSES", DEFAULT_POSES))
    if robot is None:
        robot = make_robot(os.environ.get("ROBOT", "mock"), os.environ.get("ROBOT_PORT", ""),
                           os.environ.get("ROBOT_ID", "so101_follower"), poses_path,
                           float(os.environ.get("MOCK_SPEED", "0.1")))
    store = Store(db_path or os.environ.get("DB", DEFAULT_DB))
    sensor = SensorClient(sensor_url)
    picker = None
    pick_mode = os.environ.get("PICK_MODE", "taught")
    if pick_mode == "vision":  # 비전 집기(방식 C). 보정이 없으면 조용히 바꾸지 않고 시작을 거부한다
        import handeye
        from grasp import VisionPicker
        he = handeye.load(os.environ.get("HANDEYE") or None)
        if he is None:
            raise RuntimeError("PICK_MODE=vision인데 hand-eye 보정(station/calib/handeye.json)이 없음. teach.py --handeye 먼저")
        picker = VisionPicker(sensor, he, dry_run=os.environ.get("PICK_DRY_RUN", "0") == "1")
        picker.dry_stage = os.environ.get("PICK_DRY_STAGE", "approach")  # approach | grasp(닫기 직전에서 멈춤)
    elif pick_mode != "taught":
        raise RuntimeError(f"알 수 없는 PICK_MODE: {pick_mode} (taught 또는 vision)")
    seq = Sequencer(robot, sensor, on_finish=store.save_run, durations=durations,
                    advisor=advisor_from_env(), picker=picker,
                    faces=os.environ.get("FACES", "A,B"))  # 3면 검사: FACES=A,B,C (run_station -Faces A,B,C)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        robot.connect()
        yield
        robot.disconnect()
        sensor.close()

    app = FastAPI(title="station", lifespan=lifespan)
    app.state.sequencer = seq
    app.state.store = store
    from pick_path_api import register_pick_path
    register_pick_path(app, seq, BASE_DIR)

    @app.get("/")
    def index():
        return FileResponse(BASE_DIR / "web" / "index.html")

    @app.post("/api/run")
    def api_run(req: RunReq):
        specimen = req.specimen_id.strip()
        if not specimen:
            raise HTTPException(422, "specimen_id가 비어 있다")
        try:
            box = (req.box_type or "").strip().lower()
            if box and box not in BOX_TYPES:
                raise HTTPException(422, f"box_type은 {', '.join(BOX_TYPES)} 중 하나이거나 비워 둔다")
            seq.start(specimen, req.session.strip() or "demo", box)
        except BusyError:
            raise HTTPException(409, "이미 실행 중")
        return {"ok": True}

    @app.get("/api/status")
    def api_status():
        return seq.snapshot()

    def _need_running():
        if not seq.busy or seq.snapshot()["state"] != "running":
            raise HTTPException(409, "실행 중인 작업이 없다")

    @app.post("/api/pause")
    def api_pause():
        _need_running()
        seq.request_pause()
        return {"ok": True}

    @app.post("/api/resume")
    def api_resume():
        _need_running()
        seq.resume()
        return {"ok": True}

    @app.post("/api/abort")
    def api_abort():
        _need_running()
        seq.request_abort()
        return {"ok": True}

    @app.get("/api/runs")
    def api_runs(limit: int = 100):
        return store.list_runs(limit)

    @app.get("/api/runs/{run_id}/inspections")
    def api_inspections(run_id: int):
        return store.get_inspections(run_id)

    @app.get("/api/runs.csv")
    def api_runs_csv():
        # 엑셀에서 한글이 깨지지 않도록 BOM 포함
        return Response("﻿" + store.runs_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=runs.csv"})

    @app.get("/api/sensor/health")
    def api_sensor_health():
        return sensor.health()

    @app.get("/sensor-live")
    def sensor_live(specimen_id: str = ""):
        # 센서 서버의 실시간 3화면 합성 이미지. 시료 ID는 계약과 같은 문자만 허용
        if not re.fullmatch(r"[A-Za-z0-9_.-]{0,80}", specimen_id):
            raise HTTPException(400, "잘못된 시료 ID")
        got = sensor.fetch_image("/live.jpg?specimen_id=" + specimen_id)
        if got is None:
            raise HTTPException(502, "센서 서버에서 실시간 화면을 받지 못했다")
        content, ctype = got
        return Response(content, media_type=ctype, headers={"Cache-Control": "no-store"})

    @app.get("/sensor-img")
    def sensor_img(path: str):
        # 열린 프록시가 되지 않도록 /captures/ 아래만 허용
        if not path.startswith("/captures/") or ".." in path or "\\" in path:
            raise HTTPException(400, "허용되지 않는 경로")
        got = sensor.fetch_image(path)
        if got is None:
            raise HTTPException(502, "센서 서버에서 이미지를 받지 못했다")
        content, ctype = got
        return Response(content, media_type=ctype)

    return app


app = create_app()
