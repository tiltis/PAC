"""테이프·냉매 규칙(rules.py) 현장 설정. 촬영 폴더는 capture_app.bat(SPACE) 또는 센서 서버가 만든 것을 쓴다.

1) 영역 지정 (테이프가 모두 붙은 상자를 정해진 자세로 찍은 폴더에서)
   python rules_calib.py roi-tape --capture <폴더> --face A --auto   # 초록 테이프 3개를 자동으로 찾아 영역 설정(권장)
   python rules_calib.py roi-tape --capture <폴더> --face A          # 직접: RGB 위에서 테이프 자리마다 드래그 → Enter, 다 하면 Esc
   python rules_calib.py roi-coolant --capture <폴더> --face A       # 열화상(확대)에서 ① 냉매가 닿는 상자 표면 ② 기준 패치
   (화면 없이: --rois "x0,y0,x1,y1;x0,y0,x1,y1")
2) 기준값 맞추기: 있음/없음 시편을 각각 3번 이상 찍은 폴더들로
   python rules_calib.py fit --tape-on <폴더…> --tape-off <폴더…> --coolant-on <폴더…> --coolant-off <폴더…> --source-id 1007_s1
   두 집단이 겹치지 않을 때만 validated=true가 된다. 겹치면 그 항목은 판정에 쓰지 않는다.
3) 다른 세션 촬영으로 확인(기준을 맞춘 촬영으로 평가하지 않는다)
   python rules_calib.py eval --tape-on … --tape-off … --coolant-on … --coolant-off …
4) 센서 시각 차 허용값(같은 시료 연결에 필요): python rules_calib.py timing --session <세션 폴더>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import rules

sys.stdout.reconfigure(encoding="utf-8")
DEFAULT = {"version": "tape-coolant-0.2", "validated": False, "tape_color": dict(rules.GREEN),  # 검정이면 dict(rules.BLACK)
           "tapes": [], "coolant": None, "faces_without_checks_ok": []}


def load_capture(d):
    d = Path(d)
    vis = cv2.imread(str(d / "vis.png"))
    with np.load(d / "lwir_y16.npz") as a:
        lw = a["stack"].astype(np.float32).mean(axis=0)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    return vis, lw, meta.get("face")


def cfg_load():
    return rules.load() or json.loads(json.dumps(DEFAULT))


def cfg_save(cfg):
    rules.CALIB_DIR.mkdir(exist_ok=True)
    rules.PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", rules.PATH)


def parse_rois(s):
    return [[float(v) for v in part.split(",")] for part in s.split(";") if part.strip()]


def pick_rois(img, title, scale=1.0):
    view = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST) if scale != 1 else img
    boxes = cv2.selectROIs(title, view, showCrosshair=False)
    cv2.destroyAllWindows()
    return [[x / scale, y / scale, (x + w) / scale, (y + h) / scale] for x, y, w, h in boxes]


def auto_tape_rois(vis, color, n=3, pad=0.5):
    """테이프 색 덩어리 중 큰 것 n개 → 여유를 둔 영역(왼쪽→오른쪽). 테이프가 조금 밀려도 영역 안에 들도록 pad만큼 넓힌다."""
    hsv = cv2.cvtColor(vis, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = ((H >= color["h"][0]) & (H <= color["h"][1]) & (S >= color["s_min"]) & (V >= color["v_min"])).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    k, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    min_area = 0.0002 * vis.shape[0] * vis.shape[1]
    blobs = sorted((st[i] for i in range(1, k) if st[i, cv2.CC_STAT_AREA] >= min_area), key=lambda b: -b[4])[:n]
    rois = []
    for x, y, w, h, _ in sorted(blobs, key=lambda b: b[0]):
        px, py = max(15, w * pad), max(15, h * pad)
        rois.append([max(0, x - px), max(0, y - py), min(vis.shape[1], x + w + px), min(vis.shape[0], y + h + py)])
    return rois


def cmd_roi_tape(a):
    vis, _, _ = load_capture(a.capture)
    if getattr(a, "auto", False):
        color = rules.tape_color(cfg_load())
        if color.get("mode") != "hue":
            raise SystemExit("--auto는 색 테이프(초록 등)에만 쓴다")
        rois = auto_tape_rois(vis, color, a.count)
        dbg = vis.copy()
        for k, r in enumerate(rois, 1):
            cv2.rectangle(dbg, (int(r[0]), int(r[1])), (int(r[2]), int(r[3])), (0, 0, 255), 3)
            cv2.putText(dbg, f"T{k}", (int(r[0]), int(r[1]) - 8), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        cv2.imwrite(str(Path(a.capture) / "rules_tape_rois.jpg"), dbg)
        print("영역 확인 그림:", Path(a.capture) / "rules_tape_rois.jpg")
        if len(rois) != a.count:
            raise SystemExit(f"초록 테이프 {a.count}개를 찾지 못함(찾은 수 {len(rois)}). 테이프가 모두 화면에 보이는지, 조명·노출 확인")
    else:
        rois = parse_rois(a.rois) if a.rois else pick_rois(vis, "tape ROIs: drag each, Enter; Esc when done")
    cfg = cfg_load()
    cfg["tapes"] = [t for t in cfg["tapes"] if t["face"] != a.face]
    n0 = len(cfg["tapes"])
    for k, r in enumerate(rois, 1):
        cfg["tapes"].append({"id": f"T{n0 + k}", "face": a.face, "roi_rgb": [round(v, 1) for v in r], "fill_min": None})
    cfg["validated"] = False
    cfg_save(cfg)
    print(f"면 {a.face} 테이프 영역 {len(rois)}개. 이제 fit으로 기준값을 맞춘다")


def cmd_roi_coolant(a):
    _, lw, _ = load_capture(a.capture)
    if a.rois:
        rois = parse_rois(a.rois)
    else:
        lo, hi = np.percentile(lw, [1, 99])
        img = cv2.applyColorMap((np.clip((lw - lo) / max(hi - lo, 1), 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        rois = pick_rois(img, "coolant: 1) box surface  2) reference patch  (Enter each, Esc)", scale=3.0)
    if len(rois) != 2:
        raise SystemExit("영역 2개(상자 표면, 기준 패치)가 필요")
    cfg = cfg_load()
    cfg["coolant"] = {"face": a.face, "roi_lwir": [round(v, 1) for v in rois[0]],
                      "ref_roi_lwir": [round(v, 1) for v in rois[1]], "delta_max_counts": None, "margin_counts": None}
    cfg["validated"] = False
    cfg_save(cfg)


def measures(dirs, cfg):
    out = []
    for d in dirs or []:
        vis, lw, face = load_capture(d)
        out.append((d, face, rules.measure(face, vis, lw, cfg)))
    return out


def cmd_fit(a):
    cfg = cfg_load()
    report, ok_all = {}, True
    for t in cfg["tapes"]:
        key = f"tape_{t['id']}_fill"
        on = [m[key] for _, f, m in measures(a.tape_on, cfg) if key in m]
        off = [m[key] for _, f, m in measures(a.tape_off, cfg) if key in m]
        sep = len(on) >= 3 and len(off) >= 3 and min(on) > max(off)
        t["fill_min"] = round((min(on) + max(off)) / 2, 4) if sep else None
        report[t["id"]] = {"on": [round(v, 3) for v in on], "off": [round(v, 3) for v in off], "separable": sep, "fill_min": t["fill_min"]}
        ok_all &= sep
    c = cfg.get("coolant")
    if c:
        on = [m["coolant_delta_counts"] for _, f, m in measures(a.coolant_on, cfg) if "coolant_delta_counts" in m]
        off = [m["coolant_delta_counts"] for _, f, m in measures(a.coolant_off, cfg) if "coolant_delta_counts" in m]
        sep = len(on) >= 3 and len(off) >= 3 and max(on) < min(off)  # 냉매 있으면 더 차갑다(작다)
        gap = (min(off) - max(on)) if on and off else None
        c["delta_max_counts"] = round((max(on) + min(off)) / 2, 1) if sep else None
        c["margin_counts"] = round(gap / 4, 1) if sep else None
        report["coolant"] = {"on": on, "off": off, "separable": sep, "delta_max_counts": c["delta_max_counts"],
                             "margin_counts": c["margin_counts"]}
        ok_all &= sep
    cfg.update(validated=bool(ok_all and (cfg["tapes"] or c)), source_id=a.source_id,
               fitted=dt.datetime.now().isoformat(timespec="seconds"), fit_report=report)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("validated:", cfg["validated"], "" if cfg["validated"] else "(겹치거나 3장 미만인 항목이 있어 판정에 쓰지 않음)")
    cfg_save(cfg)


def cmd_eval(a):
    cfg = cfg_load()
    rows = []
    for label, dirs in (("tape_on", a.tape_on), ("tape_off", a.tape_off), ("coolant_on", a.coolant_on), ("coolant_off", a.coolant_off)):
        for d in dirs or []:
            vis, lw, face = load_capture(d)
            res = rules.judge_face(face, vis, lw, dict(cfg, validated=True))
            v, r, f = res if res else (None, [], {})
            if label.startswith("tape"):
                pres = [f[k] for k in f if k.startswith("tape_") and k.endswith("_present")]
                correct = all(pres) if label == "tape_on" else (False in pres)
            else:
                correct = f.get("coolant_present") is (label == "coolant_on")
            rows.append((label, Path(d).name, v, r, correct))
            print(f"{label:12s} {Path(d).name:40s} {v} {r} {'OK' if correct else 'WRONG'}")
    n = len(rows)
    print(f"맞음 {sum(r[4] for r in rows)}/{n}")


def cmd_timing(a):
    skews = {"rgb_lwir_skew_s": [], "depth_rgb_skew_s": []}
    for m in Path(a.session).glob("*/meta.json"):
        t = json.loads(m.read_text(encoding="utf-8")).get("sensor_data", {}).get("timing", {})
        for k in skews:
            if isinstance(t.get(k), (int, float)):
                skews[k].append(abs(t[k]))
    if len(skews["rgb_lwir_skew_s"]) < 5:
        raise SystemExit("센서 서버로 찍은 촬영이 5개 이상 필요")
    pol = {"validated": True, "source_id": Path(a.session).name, "measured": {k: [round(min(v), 4), round(max(v), 4), len(v)] for k, v in skews.items() if v}}
    for k, v in skews.items():
        if v:
            pol["max_" + k] = round(max(v) * 1.5 + 0.02, 3)  # 실측 최대의 1.5배 + 20ms
    path = rules.CALIB_DIR / "timing_policy.json"
    path.write_text(json.dumps(pol, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(pol, ensure_ascii=False, indent=1))
    print("saved", path)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("roi-tape", "roi-coolant"):
        s = sub.add_parser(name)
        s.add_argument("--capture", required=True)
        s.add_argument("--face", required=True, choices=["A", "B", "C"])
        s.add_argument("--rois", default="")
        if name == "roi-tape":
            s.add_argument("--auto", action="store_true", help="초록 테이프 자동 찾기")
            s.add_argument("--count", type=int, default=3)
    for name in ("fit", "eval"):
        s = sub.add_parser(name)
        for k in ("tape-on", "tape-off", "coolant-on", "coolant-off"):
            s.add_argument("--" + k, nargs="*", default=[])
        if name == "fit":
            s.add_argument("--source-id", required=True)
    s = sub.add_parser("timing")
    s.add_argument("--session", required=True)
    a = ap.parse_args()
    {"roi-tape": cmd_roi_tape, "roi-coolant": cmd_roi_coolant, "fit": cmd_fit, "eval": cmd_eval, "timing": cmd_timing}[a.cmd](a)


if __name__ == "__main__":
    main()
