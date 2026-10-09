"""RGB(Arducam IMX179) + 열화상(Boson 320) 동시 수신과 촬영쌍 저장.

열화상은 8비트 AGC 영상(640x512 업스케일)이 아니라 Y16 원시값(320x256 uint16)만 쓴다.
Boson 320 (20320A050-6PAAX)은 비방사측정형이라 원시값을 섭씨로 바꾸지 않는다.
"""
import datetime as dt
import uuid
from contextlib import contextmanager
import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


LWIR_W, LWIR_H = 320, 256
# 환경변수 PAC2026_DATA가 있으면 그곳, 없으면 이 데스크톱은 D:, 그 외 PC는 사용자 폴더(OneDrive 동기화 회피)
DEFAULT_DATA_ROOT = Path(os.environ["PAC2026_DATA"]) if os.environ.get("PAC2026_DATA") else (
    Path(r"D:\PAC2026_data") if Path(r"D:\PAC2026_data").exists() else Path.home() / "PAC2026_data")
SOFTWARE = "pac2026-capture 0.1"


def validate_capture_name(value):
    """촬영 폴더 이름은 단일 경로 요소만 허용한다(Windows/Mac 공통)."""
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if not re.fullmatch(r"[\w.-]{1,80}", value) or ".." in value or value.startswith(".") or value.endswith(".") or (
            value.split(".", 1)[0].upper() in reserved):
        raise ValueError("촬영 이름은 문자·숫자·밑줄·하이픈·내부 점(최대 80자)만 허용")
    return value


class CaptureSaveError(OSError):
    """A capture directory exists but saving did not finish; preserve its request identity."""
    def __init__(self, out, identity, cause):
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.capture_path = out
        self.capture_identity = identity


@contextmanager
def capture_output(out, session, specimen_id, face, note, trigger_id=None, attempt=None):
    identity = {"session": session, "specimen_id": specimen_id, "face": face,
                "trigger_id": trigger_id or uuid.uuid4().hex, "attempt": attempt,
                "capture_id": out.name, "note": note, "created_at_s": time.time(),
                "capture_status": "saving"}
    try:
        # This small separate record is never overwritten by the full metadata writer.
        (out / "capture_request.json").write_text(json.dumps(identity, ensure_ascii=False, indent=1), encoding="utf-8")
        yield identity
    except Exception as cause:
        raise CaptureSaveError(out, identity, cause) from cause


def save_png(path, image):
    """OpenCV의 Windows 한글 파일명 제약을 피하고 저장 실패를 숨기지 않는다."""
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError("이미지 인코딩 실패")
    Path(path).write_bytes(encoded.tobytes())

VIS_PROPS = ["EXPOSURE", "GAIN", "AUTO_WB", "WB_TEMPERATURE", "AUTOFOCUS", "FOCUS",
             "BRIGHTNESS", "CONTRAST", "SATURATION", "SHARPNESS", "GAMMA", "BACKLIGHT"]


@dataclass
class RigConfig:
    vis_width: int = 1600
    vis_height: int = 1200
    vis_exposure: float | None = None  # None이면 자동 노출로 시작. lock_vis()로 고정한다
    ffc_settle_s: float = 0.5          # FFC 완료 후 이 시간 동안의 프레임은 버린다
    lwir_frames: int = 8               # 저장할 열화상 연속 프레임 수 (분석 때 평균)
    data_root: Path = DEFAULT_DATA_ROOT


class CamThread(threading.Thread):
    """프레임을 계속 읽어 최신 1장만 보관한다.

    DSHOW 내부 버퍼에 오래된 프레임이 쌓이지 않게 하고, 카메라 설정 변경도
    읽기 사이에 같은 스레드에서 처리한다(다른 스레드에서 cap.set을 부르지 않는다).
    """

    def __init__(self, cap, name):
        super().__init__(daemon=True, name=name)
        self.cap = cap
        self.cond = threading.Condition()
        self.frame, self.ts, self.count, self.errors = None, 0.0, 0, 0
        self.jobs = queue.Queue()
        self.running = True

    def run(self):
        while self.running:
            while not self.jobs.empty():
                fn, box, done = self.jobs.get()
                try:
                    box["result"] = fn(self.cap)
                except Exception as e:  # 호출한 쪽에서 다시 던진다
                    box["error"] = e
                done.set()
            ok, f = self.cap.read()
            now = time.time()
            if not ok or f is None:
                self.errors += 1
                time.sleep(0.02)
                continue
            with self.cond:
                self.frame, self.ts = f, now
                self.count += 1
                self.cond.notify_all()

    def call(self, fn, timeout=5.0):
        """fn(cap)을 읽기 스레드에서 실행하고 결과를 돌려준다."""
        box, done = {}, threading.Event()
        self.jobs.put((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError(f"{self.name}: 설정 명령 응답 없음")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def latest(self):
        with self.cond:
            return self.frame, self.ts, self.count

    def next_after(self, ts, timeout=5.0):
        """ts 이후에 도착한 프레임을 기다려 돌려준다."""
        deadline = time.time() + timeout
        with self.cond:
            while self.ts <= ts:
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(f"{self.name}: {timeout:.0f}초 동안 새 프레임 없음")
                self.cond.wait(left)
            return self.frame, self.ts, self.count

    def stop(self):
        self.running = False
        self.join(timeout=3)
        self.cap.release()


def open_vis(index, cfg):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"RGB 카메라(번호 {index})를 열지 못함. Windows 카메라 앱 등 다른 프로그램이 쓰고 있지 않은지 확인")
    # 순서 주의: 크기를 먼저 정하고 MJPG를 지정해야 적용된다. 반대로 하면 YUY2(1600x1200 약 3fps)로 떨어진다
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.vis_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.vis_height)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    ok, f = cap.read()
    if not ok:
        raise RuntimeError("RGB 프레임 수신 실패")
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace")
    if fourcc != "MJPG":
        raise RuntimeError(f"RGB가 MJPG가 아니라 {fourcc}로 열림")
    if f.shape[:2] != (cfg.vis_height, cfg.vis_width):
        raise RuntimeError(f"RGB 요청 {cfg.vis_width}x{cfg.vis_height}, 실제 {f.shape[1]}x{f.shape[0]}")
    if cfg.vis_exposure is not None:
        cap.set(cv2.CAP_PROP_EXPOSURE, cfg.vis_exposure)  # 값을 지정하면 자동 노출이 꺼진다
    return cap


def open_lwir(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"열화상 카메라(번호 {index})를 열지 못함. Windows 카메라 앱 등 다른 프로그램이 쓰고 있지 않은지 확인")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"Y16 "))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, LWIR_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LWIR_H)
    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
    for _ in range(5):
        ok, f = cap.read()
    if not ok or f is None:
        raise RuntimeError("열화상 프레임 수신 실패")
    if f.dtype != np.uint16 or f.shape != (LWIR_H, LWIR_W):
        raise RuntimeError(f"Y16 원시값이 아님: dtype={f.dtype}, shape={f.shape}")
    return cap


def colorize_y16(a, lo_pct=1, hi_pct=99):
    """원시값을 보기용 색상 영상으로. 저장·분석에는 쓰지 않는다."""
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    n = np.clip((a.astype(np.float32) - lo) / max(hi - lo, 1.0), 0, 1)
    return cv2.applyColorMap((n * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)


class Rig:
    def __init__(self, cfg=None):
        # Windows 전용(pygrabber) 모듈이라 여기서 불러온다. 가짜 Rig·테스트는 다른 OS에서도 import된다
        from devices import LWIR_NAME, VIS_NAME, find_boson_port, find_video_index

        self.cfg = cfg or RigConfig()
        self.vis_index = find_video_index(VIS_NAME, "VIS")
        self.lwir_index = find_video_index(LWIR_NAME, "LWIR")
        self.vis = CamThread(open_vis(self.vis_index, self.cfg), "VIS")
        self.lwir = CamThread(open_lwir(self.lwir_index), "LWIR")
        self.boson, self.boson_info, self.ffc_manual = None, {}, False
        port = find_boson_port()
        if port:
            from flirpy.camera.boson import Boson
            self.boson = Boson(port=port)
            self.boson.set_ffc_auto()  # 이전 프로그램이 강제 종료돼 수동 FFC로 남아 있어도 상태를 맞춘다
            self.boson_info = {
                "port": port,
                "part_number": self.boson.get_part_number().strip("\x00 "),
                "camera_serial": self.boson.get_camera_serial(),
                "firmware": list(self.boson.get_firmware_revision()),
            }
        self.vis.start()
        self.lwir.start()
        self.vis.next_after(0)
        self.lwir.next_after(0)

    def preview(self):
        """실시간 화면용 최신 프레임 복사본 (RGB BGR, 열화상 Y16). 촬영 기록에는 capture_pair를 쓴다."""
        vis, lw = self.vis.latest()[0], self.lwir.latest()[0]
        return (None if vis is None else vis.copy()), (None if lw is None else lw.copy())

    def health(self, max_age_s=2.0):
        now = time.time()
        return {"vis": now - self.vis.latest()[1] < max_age_s, "lwir": now - self.lwir.latest()[1] < max_age_s}

    # --- Boson -------------------------------------------------------------
    def set_ffc_manual(self, manual):
        """수동이면 촬영 직전에만 FFC가 일어나 촬영 중 원시값이 계단처럼 튀지 않는다."""
        if not self.boson:
            return
        self.boson.set_ffc_manual() if manual else self.boson.set_ffc_auto()
        self.ffc_manual = manual

    def do_ffc(self, timeout=3.0):
        """FFC를 요청하고 끝날 때까지 기다린다. 완료 시각을 돌려준다.

        이 펌웨어(2.0.15223)는 상태가 0→1(진행)→0으로 돌아오고 3(완료)을 보고하지 않는다.
        그래서 마지막 FFC 프레임 번호가 바뀌고 상태가 0으로 돌아온 시점을 완료로 본다(실측 약 0.4초).
        """
        if not self.boson:
            return None
        before = self.boson.get_last_ffc_frame_count()
        self.boson.do_ffc()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.03)
            if self.boson.get_last_ffc_frame_count() != before and self.boson.get_ffc_state() == 0:
                return time.time()
        raise TimeoutError("Boson FFC가 완료되지 않음")

    def fpa_temp(self):
        return self.boson.get_fpa_temperature() if self.boson else None

    # --- RGB ---------------------------------------------------------------
    def vis_settings(self):
        return self.vis.call(lambda cap: {p: cap.get(getattr(cv2, "CAP_PROP_" + p)) for p in VIS_PROPS})

    def lock_vis(self):
        """지금 자동으로 잡힌 노출·화이트밸런스 값을 그대로 고정하고 자동 초점을 끈다."""
        def _lock(cap):
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # 고정 초점 렌즈면 효과 없음. 초점이 움직이면 면별 정합이 틀어진다
            cap.set(cv2.CAP_PROP_EXPOSURE, cap.get(cv2.CAP_PROP_EXPOSURE))
            wb = cap.get(cv2.CAP_PROP_WB_TEMPERATURE)
            cap.set(cv2.CAP_PROP_AUTO_WB, 0)
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb)
        self.vis.call(_lock)
        return self.vis_settings()

    def set_vis_exposure(self, value):
        self.vis.call(lambda cap: cap.set(cv2.CAP_PROP_EXPOSURE, value))

    def open_vis_dialog(self):
        """Arducam 드라이버 설정창. 바꾼 값은 vis_settings()로 메타에 남는다."""
        self.vis.call(lambda cap: cap.set(cv2.CAP_PROP_SETTINGS, 1))

    # --- 촬영 ---------------------------------------------------------------
    def capture_pair(self, session, specimen_id, face, note="", ffc=True, trigger_id=None, attempt=None):
        validate_capture_name(session)
        validate_capture_name(specimen_id)
        if face not in ("A", "B", "C"):
            raise ValueError("face는 A, B, C 중 하나여야 한다")
        cfg = self.cfg
        t0 = time.time()
        ffc_ts = None
        if ffc and self.boson:
            ffc_ts = self.do_ffc()
            time.sleep(cfg.ffc_settle_s)
        t_req = time.time()

        stack, lwir_ts, last = [], [], t_req
        for _ in range(cfg.lwir_frames):
            f, ts, _ = self.lwir.next_after(last)
            stack.append(f.copy())
            lwir_ts.append(ts)
            last = ts
        stack = np.stack(stack)
        vis, vis_ts, _ = self.vis.next_after(t_req)
        vis = vis.copy()

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = Path(cfg.data_root) / session / f"{specimen_id}_{face}_{stamp}"
        out.mkdir(parents=True, exist_ok=False)
        with capture_output(out, session, specimen_id, face, note, trigger_id, attempt) as identity:
            save_png(out / "vis.png", vis)
            np.savez_compressed(out / "lwir_y16.npz", stack=stack)
            mean = stack.mean(axis=0)
            save_png(out / "lwir_preview.png", colorize_y16(mean))
    
            meta = {**identity,
                "capture_status": "saved",
                "software": SOFTWARE,
                "session": session,
                "specimen_id": specimen_id,
                "face": face,
                "note": note,
                "time_local": dt.datetime.now().isoformat(timespec="seconds"),
                "elapsed_ms": round((time.time() - t0) * 1000),
                "vis": {
                    "file": "vis.png",
                    "width": vis.shape[1], "height": vis.shape[0],
                    "ts": vis_ts,
                    "device_index": self.vis_index,
                    "settings": self.vis_settings(),
                },
                "lwir": {
                    "file": "lwir_y16.npz",
                    "format": "Y16 raw counts, uint16, stack[n,256,320]; not radiometric",
                    "n_frames": int(stack.shape[0]),
                    "ts_first": lwir_ts[0], "ts_last": lwir_ts[-1],
                    "raw_min": int(stack.min()), "raw_max": int(stack.max()),
                    "raw_mean": round(float(mean.mean()), 2),
                    "temporal_std_mean": round(float(stack.std(axis=0).mean()), 3),
                    "fpa_temp_c": self.fpa_temp(),
                    "ffc_ts": ffc_ts,
                    "ffc_settle_s": cfg.ffc_settle_s if ffc_ts else None,
                    "ffc_mode": "manual" if self.ffc_manual else "auto",
                    "device_index": self.lwir_index,
                },
                "boson": self.boson_info,
                "vis_minus_lwir_s": round(vis_ts - lwir_ts[len(lwir_ts) // 2], 4),
            }
            (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            return out, meta


    def close(self):
        if self.boson:
            if self.ffc_manual:
                self.boson.set_ffc_auto()  # 수동 FFC로 남겨두면 나중에 영상이 점점 흐트러진다
            self.boson.close()
        self.vis.stop()
        self.lwir.stop()
