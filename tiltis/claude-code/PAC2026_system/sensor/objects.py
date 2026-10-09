"""고정된 3대 카메라(RGB·열화상·깊이)에서 같은 물체(예: 상자)를 찾고, 같은 물체인지 확인한다.

1) 배경: 물체가 없는 빈 장면을 카메라마다 저장한다(capture_app의 g 키).
2) 검출: 배경과 달라진 영역 중 가장 큰 덩어리를 물체로 본다.
   - RGB: 밝기·색 차이(전체 밝기 변화는 보정)
   - 열화상: Y16 원시값 차이(FFC·드리프트로 생기는 화면 전체 오프셋은 빼고 본다).
     실온 상자는 배경과 온도가 같아 안 보일 수 있다. 냉매가 든 상자는 차갑게 보인다
   - 깊이: 배경보다 max(30mm, 거리의 2%) 이상 가까워진 픽셀
3) 위치 대응: 물체를 여러 곳(4곳 이상)에 놓아 가며 세 카메라의 물체 중심을 모아 RGB→열화상, RGB→깊이
   호모그래피를 맞춘다(capture_app의 j 키). 정합 타깃 없이 물체 자체로 맞춘다.
4) 같은 물체 판정: RGB 물체 중심을 다른 카메라로 옮긴 위치가 그 카메라에서 찾은 물체 중심과
   화면 폭의 8% 안이면 일치. 대응이 없으면 '미검증'이다. 자동 재식별 정확도를 보장하지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

CALIB_DIR = Path(__file__).parent / "calib"
BG_DIR = CALIB_DIR / "background"
MAP_PATH = CALIB_DIR / "object_map.json"
CONFIG_PATH = CALIB_DIR / "object_config.json"
DEFAULT_CONFIG = {
    "depth_band_mm": [200, 1000],  # 배경 없이 깊이로 찾을 때: 이 거리 안의 가장 큰 덩어리 = 물체
    "roi": {"rgb": None, "lwir": None, "depth": None},  # [x0, y0, x1, y1] 원본 픽셀. 이 밖의 변화(지나가는 사람 등)는 무시
    "pick_roi_depth": None,  # 로봇 집기 영역(깊이 픽셀 [x0, y0, x1, y1]). 없으면 화면 아래쪽 45%
    "locate_mode": "front",  # front: 앞면 + 상자 크기(카메라를 세워 둘 때, 10-06 결정) / top: 윗면 직접 측정(위에서 내려다볼 때)
    "box_mm": [160, 130, 50],  # 마운자로 상자(자 측정) 가로·세로·높이
    "tab_height_mm": 20,       # 손잡이 높이
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg["depth_band_mm"] = user.get("depth_band_mm", cfg["depth_band_mm"])
        cfg["roi"].update(user.get("roi") or {})
        for key in ("pick_roi_depth", "locate_mode", "box_mm", "tab_height_mm"):
            cfg[key] = user.get(key, cfg[key])
    return cfg


def _roi_mask(mask, roi, scale):
    """roi 밖을 지운다. roi는 원본 픽셀 좌표."""
    if not roi:
        return mask
    x0, y0, x1, y1 = (int(round(v * scale)) for v in roi)
    keep = np.zeros_like(mask, dtype=bool)
    keep[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    return mask & keep
CAMS = ("rgb", "lwir", "depth")


@dataclass
class Detection:
    cam: str
    found: bool
    bbox: list | None = None       # 그 카메라 원본 픽셀 [x0, y0, x1, y1]
    center: list | None = None     # 물체 영역 무게중심
    area_frac: float = 0.0         # 화면 대비 물체 넓이
    second_frac: float = 0.0       # 두 번째로 큰 덩어리 넓이(여러 물체 의심 판단용)
    extra: dict = field(default_factory=dict)


def _largest(mask, scale, cam, min_area_frac, extra=None):
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if n <= 1:
        return Detection(cam, False, extra=extra or {})
    areas = stats[1:, cv2.CC_STAT_AREA]
    order = np.argsort(areas)[::-1] + 1
    i = order[0]
    total = mask.size
    frac = float(stats[i, cv2.CC_STAT_AREA]) / total
    second = float(stats[order[1], cv2.CC_STAT_AREA]) / total if len(order) > 1 else 0.0
    if frac < min_area_frac:
        return Detection(cam, False, area_frac=round(frac, 5), extra=extra or {})
    x, y, w, h = stats[i, :4]
    s = 1.0 / scale
    return Detection(cam, True, [round(x * s, 1), round(y * s, 1), round((x + w) * s, 1), round((y + h) * s, 1)],
                     [round(cents[i][0] * s, 1), round(cents[i][1] * s, 1)], round(frac, 5), round(second, 5),
                     extra or {}), labels == i


def _clean(mask, k):
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, ker)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ker)


def _unwrap(res):
    return res[0] if isinstance(res, tuple) else res


def detect_rgb(vis, bg, min_area_frac=0.004, roi=None):
    scale = 400 / vis.shape[1]
    small = lambda im: cv2.GaussianBlur(cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), (5, 5), 0)
    a, b = cv2.cvtColor(small(vis), cv2.COLOR_BGR2LAB).astype(np.float32), cv2.cvtColor(small(bg), cv2.COLOR_BGR2LAB).astype(np.float32)
    a[..., 0] *= (np.median(b[..., 0]) + 1) / (np.median(a[..., 0]) + 1)  # 자동 노출로 인한 전체 밝기 변화 보정
    d = np.abs(a[..., 0] - b[..., 0]) + 0.7 * (np.abs(a[..., 1] - b[..., 1]) + np.abs(a[..., 2] - b[..., 2]))
    noise = 1.4826 * np.median(np.abs(d - np.median(d)))
    thr = max(18.0, np.median(d) + 5 * noise)
    mask = _roi_mask(_clean(d > thr, 5).astype(bool), roi, scale)
    return _unwrap(_largest(mask, scale, "rgb", min_area_frac, {"threshold": round(float(thr), 1), "mode": "background"}))


def detect_lwir(lw, bg, min_area_frac=0.004, min_counts=20.0, roi=None):
    d = lw.astype(np.float32) - bg.astype(np.float32)
    d = cv2.GaussianBlur(d - np.median(d), (5, 5), 0)  # FFC·드리프트로 인한 전체 오프셋 제거
    noise = 1.4826 * np.median(np.abs(d))
    thr = max(min_counts, 5 * noise)
    mask = _roi_mask(_clean(np.abs(d) > thr, 3).astype(bool), roi, 1.0)
    res = _largest(mask, 1.0, "lwir", min_area_frac, {"threshold_counts": round(float(thr), 1), "mode": "background"})
    if isinstance(res, tuple):
        det, m = res
        mean = float(d[m].mean())
        det.extra.update(delta_counts=round(mean, 1), polarity="colder" if mean < 0 else "warmer")
        return det
    return res


def detect_depth(mm, bg_mm=None, min_area_frac=0.004, min_closer_mm=30.0, rel=0.02, band_mm=(200, 1000), roi=None):
    """bg_mm가 있으면 배경보다 가까워진 픽셀, 없으면 band_mm 거리 안의 픽셀을 물체로 본다(배경 불필요)."""
    scale = 640 / mm.shape[1]
    small = lambda im: cv2.resize(im.astype(np.float32), None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    a = small(mm)
    if bg_mm is not None:
        b = small(bg_mm)
        mask, extra = (a > 0) & (b > 0) & ((b - a) > np.maximum(min_closer_mm, rel * b)), {"mode": "background"}
    else:
        b = None
        mask, extra = (a > band_mm[0]) & (a < band_mm[1]), {"mode": "band", "band_mm": list(band_mm)}
    mask = _roi_mask(_clean(mask, 5).astype(bool), roi, scale)
    res = _largest(mask, scale, "depth", min_area_frac, extra)
    if isinstance(res, tuple):
        det, m = res
        det.extra.update(distance_mm=round(float(np.median(a[m])), 1))
        if b is not None:
            det.extra["background_mm"] = round(float(np.median(b[m])), 1)
        return det
    return res


# --- 배경 ----------------------------------------------------------------------------------
def save_background(vis, lw, depth_mm=None):
    BG_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(BG_DIR / "rgb.png"), vis)
    np.save(BG_DIR / "lwir.npy", lw.astype(np.float32))
    if depth_mm is not None:
        np.save(BG_DIR / "depth_mm.npy", depth_mm.astype(np.float32))
    (BG_DIR / "meta.json").write_text(json.dumps({"created": dt.datetime.now().isoformat(timespec="seconds"),
                                                  "depth": depth_mm is not None}), encoding="utf-8")


def load_background():
    if not (BG_DIR / "rgb.png").exists():
        return None
    bg = {"rgb": cv2.imread(str(BG_DIR / "rgb.png")), "lwir": np.load(BG_DIR / "lwir.npy")}
    if (BG_DIR / "depth_mm.npy").exists():
        bg["depth"] = np.load(BG_DIR / "depth_mm.npy")
    return bg


_cache = {}


def load_background_cached():
    """서버용: 배경 파일이 바뀌었을 때만 다시 읽는다."""
    meta = BG_DIR / "meta.json"
    key = (str(BG_DIR), meta.stat().st_mtime_ns) if meta.exists() else None
    if "key" not in _cache or _cache["key"] != key:
        _cache.update(key=key, bg=load_background() if key else None)
    return _cache["bg"]


def detect_all(bg, vis, lw, depth_mm=None, cfg=None):
    """bg가 None이면 RGB·열화상은 '배경 없음'으로 두고, 깊이는 거리 범위로 찾는다."""
    cfg = cfg or load_config()
    roi = cfg["roi"]
    no_bg = lambda cam: Detection(cam, False, extra={"error": "no_background"})
    dets = {
        "rgb": detect_rgb(vis, bg["rgb"], roi=roi.get("rgb")) if bg is not None and bg["rgb"].shape == vis.shape else no_bg("rgb"),
        "lwir": detect_lwir(lw, bg["lwir"], roi=roi.get("lwir")) if bg is not None and bg["lwir"].shape == lw.shape else no_bg("lwir"),
    }
    if depth_mm is not None:
        dbg = bg.get("depth") if bg is not None else None
        dbg = dbg if dbg is not None and dbg.shape == depth_mm.shape else None
        dets["depth"] = detect_depth(depth_mm, dbg, band_mm=tuple(cfg["depth_band_mm"]), roi=roi.get("depth"))
    return dets


# --- 카메라 사이 위치 대응 ------------------------------------------------------------------
def load_map():
    return json.loads(MAP_PATH.read_text(encoding="utf-8")) if MAP_PATH.exists() else None


def add_map_point(dets):
    """켜진 카메라(RGB + 열화상, 깊이는 켜져 있으면) 모두 물체를 찾았을 때 중심 대응점을 추가한다.
    카메라마다 대응점이 4개 이상이면 RGB→그 카메라 호모그래피를 다시 맞춘다."""
    cams = [c for c in CAMS if c in dets]
    if "rgb" not in cams or len(cams) < 2 or not all(dets[c].found for c in cams):
        return None, "켜진 카메라 모두에서 물체를 찾아야 대응점을 추가할 수 있음"
    m = load_map() or {"points": []}
    m["points"].append({c: dets[c].center for c in cams})
    msg = f"map point {len(m['points'])}"
    for cam in ("lwir", "depth"):
        pts = [p for p in m["points"] if cam in p]
        if len(pts) < 4:
            continue
        src = np.array([p["rgb"] for p in pts], np.float64)
        dst = np.array([p[cam] for p in pts], np.float64)
        H, _ = cv2.findHomography(src, dst, 0)
        if H is None:
            msg += f", {cam} fit failed (spread positions wider)"
            continue
        err = np.linalg.norm(cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2) - dst, axis=1)
        m[f"H_rgb_to_{cam}"] = H.tolist()
        m[f"fit_err_px_{cam}"] = round(float(err.max()), 1)
        msg += f", {cam} max err {m[f'fit_err_px_{cam}']}px"
    m["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    CALIB_DIR.mkdir(exist_ok=True)
    MAP_PATH.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m, msg


def associate(dets, cmap, sizes, tol_frac=0.08):
    """sizes: {"lwir": (w, h), "depth": (w, h)}. 결과 status:
    same_object(세 대 모두 찾고 위치 일치) / partial(찾은 카메라는 일치, 일부 미검출) /
    mismatch(위치 불일치) / ambiguous(여러 물체 의심) / unverified(위치 대응 없음) / no_object
    """
    rgb = dets.get("rgb")
    out = {"status": "no_object", "cams": {}}
    if rgb is None or not rgb.found:
        dp = dets.get("depth")
        if dp is not None and dp.found:  # 배경이 없거나 RGB가 못 찾았지만 깊이에는 물체가 있음
            out["status"] = "depth_only"
        out["found"] = {c: bool(d.found) for c, d in dets.items()}
        return out
    per = {}
    for cam in ("lwir", "depth"):
        d = dets.get(cam)
        if d is None:
            per[cam] = {"status": "disabled"}
        elif not d.found:
            per[cam] = {"status": "not_found"}
        elif not cmap or f"H_rgb_to_{cam}" not in cmap:
            per[cam] = {"status": "unverified"}
        else:
            pred = cv2.perspectiveTransform(np.array([[rgb.center]], np.float64), np.array(cmap[f"H_rgb_to_{cam}"])).reshape(2)
            err = float(np.linalg.norm(pred - np.array(d.center)) / sizes[cam][0])
            per[cam] = {"status": "match" if err <= tol_frac else "mismatch", "error_frac": round(err, 3),
                        "predicted": [round(float(v), 1) for v in pred]}
    out["cams"] = per
    st = [p["status"] for p in per.values() if p["status"] != "disabled"]
    multiple = any(d is not None and d.found and d.second_frac > 0.5 * d.area_frac for d in dets.values())
    if "mismatch" in st:
        out["status"] = "mismatch"
    elif multiple:
        out["status"] = "ambiguous"
    elif "unverified" in st:
        out["status"] = "unverified"
    elif st and all(s == "match" for s in st):
        out["status"] = "same_object"
    else:
        out["status"] = "partial"
    out["found"] = {c: bool(d.found) for c, d in dets.items()}
    return out


def features(dets, assoc):
    """검사 기록용 평평한 특징값."""
    f = {"object_status": assoc["status"]}
    for c, d in dets.items():
        f[f"object_{c}_found"] = d.found
        if d.found:
            f[f"object_{c}_bbox"] = d.bbox
            f[f"object_{c}_area_frac"] = d.area_frac
    lw = dets.get("lwir")
    if lw is not None and lw.found:
        f["object_lwir_delta_counts"] = lw.extra.get("delta_counts")
    dp = dets.get("depth")
    if dp is not None and dp.found:
        f["object_depth_mm"] = dp.extra.get("distance_mm")
    return f


def to_dict(dets):
    return {c: asdict(d) for c, d in dets.items()}
