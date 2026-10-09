"""Boson 원시값의 안정성을 잰다. 카메라 앞을 움직이지 않는 장면(벽, 상자)으로 두고 실행한다.

    python measure_drift.py settle                       # FFC 후 대기시간 0.5/1/2초 비교 (약 30초)
    python measure_drift.py drift --minutes 30 --every 30  # 예열 곡선 (전원 넣자마자 시작)

결과 CSV는 <data_root>/_drift/ 에 저장된다.
"""
import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path

import numpy as np

from rig import LWIR_H, LWIR_W, Rig, RigConfig

sys.stdout.reconfigure(encoding="utf-8")
CY, CX, R = LWIR_H // 2, LWIR_W // 2, 20  # 가운데 40x40 영역


def grab(rig, settle, n=8):
    rig.do_ffc()
    time.sleep(settle)
    stack, last = [], time.time()
    for _ in range(n):
        f, last, _ = rig.lwir.next_after(last)
        stack.append(f.astype(np.float32))
    s = np.stack(stack)
    mean = s.mean(axis=0)
    return {
        "frame_mean": round(float(mean.mean()), 2),
        "center_mean": round(float(mean[CY - R:CY + R, CX - R:CX + R].mean()), 2),
        "temporal_std": round(float(s.std(axis=0).mean()), 3),
        "fpa_c": rig.fpa_temp(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["settle", "drift"])
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--every", type=float, default=30, help="측정 간격(초)")
    ap.add_argument("--settle", type=float, default=0.5, help="drift 모드의 FFC 후 대기(초)")
    args = ap.parse_args()

    rig = Rig(RigConfig())
    rig.set_ffc_manual(True)
    out_dir = Path(rig.cfg.data_root) / "_drift"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.mode}_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    rows = []
    t0 = time.time()
    try:
        if args.mode == "settle":
            for rep in range(3):
                for settle in (0.5, 1.0, 2.0):
                    r = {"rep": rep, "settle_s": settle, **grab(rig, settle)}
                    rows.append(r)
                    print(r)
        else:
            while time.time() - t0 < args.minutes * 60:
                tick = time.time()
                r = {"t_min": round((tick - t0) / 60, 2), **grab(rig, args.settle)}
                rows.append(r)
                print(r, flush=True)
                time.sleep(max(0, args.every - (time.time() - tick)))
    finally:
        rig.close()
        if rows:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            print("saved", path)


if __name__ == "__main__":
    main()
