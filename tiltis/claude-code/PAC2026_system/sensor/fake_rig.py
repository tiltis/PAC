"""카메라 없이 센서 서버를 돌리기 위한 가짜 Rig. 실제 Rig와 같은 파일 형식으로 저장한다.

    python server.py --fake-rig               # 모두 선명
    python server.py --fake-rig --blur-faces A  # 면 A는 흐린 영상(측정 불가 시험)
"""
import datetime as dt
import json
import time
from pathlib import Path

import cv2
import numpy as np

from rig import DEFAULT_DATA_ROOT, RigConfig, colorize_y16, validate_capture_name, save_png, capture_output


class FakeRig:
    def __init__(self, cfg=None, blur_faces=(), seed=0):
        self.cfg = cfg or RigConfig()
        self.blur_faces = set(blur_faces)
        self.rng = np.random.default_rng(seed)
        self.boson_info = {"part_number": "FAKE", "port": None}
        self.ffc_manual = False

    def health(self, max_age_s=2.0):
        return {"vis": True, "lwir": True}

    def preview(self):
        vis = np.full((self.cfg.vis_height, self.cfg.vis_width, 3), 90, np.uint8)
        cv2.putText(vis, "FAKE LIVE", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 255), 6)
        return vis, (22000 + self.rng.normal(0, 3, (256, 320))).astype(np.uint16)

    def set_ffc_manual(self, manual):
        self.ffc_manual = manual

    def capture_pair(self, session, specimen_id, face, note="", ffc=True, trigger_id=None, attempt=None):
        validate_capture_name(session)
        validate_capture_name(specimen_id)
        if face not in ("A", "B", "C"):
            raise ValueError("face는 A, B 또는 C여야 한다")
        t0 = time.time()
        h, w = self.cfg.vis_height, self.cfg.vis_width
        vis = np.full((h, w, 3), 90, np.uint8)
        for i in range(0, w, 40):  # 선명한 격자 무늬
            cv2.line(vis, (i, 0), (i, h), (200, 200, 200), 2)
        cv2.putText(vis, f"FAKE {specimen_id} {face}", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 255), 6)
        if face in self.blur_faces:
            vis = cv2.GaussianBlur(vis, (0, 0), 12)
        stack = (22000 + self.rng.normal(0, 3, (8, 256, 320))).astype(np.uint16)

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = Path(self.cfg.data_root) / session / f"{specimen_id}_{face}_{stamp}"
        out.mkdir(parents=True, exist_ok=False)
        with capture_output(out, session, specimen_id, face, note, trigger_id, attempt) as identity:
            save_png(out / "vis.png", vis)
            np.savez_compressed(out / "lwir_y16.npz", stack=stack)
            save_png(out / "lwir_preview.png", colorize_y16(stack.mean(axis=0)))
            meta = {**identity, "capture_status": "saved", "software": "fake-rig", "session": session, "specimen_id": specimen_id, "face": face,
                    "note": note, "elapsed_ms": round((time.time() - t0) * 1000), "boson": self.boson_info,
                    "vis": {"ts": t0}, "lwir": {"ts_first": t0, "ts_last": t0,
                        "ffc_mode": "manual" if self.ffc_manual else "auto"}}
            (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            return out, meta


    def close(self):
        pass
