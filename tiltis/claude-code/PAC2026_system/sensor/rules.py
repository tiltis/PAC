"""포장 검사 규칙: 테이프 붙임 여부(RGB, 기본 초록) + 내부 냉매 유무(열화상).

로봇이 상자를 정해진 자세(면 A/B)로 보여 주므로 화면 속 위치가 거의 같다. 그래서 위치를 영역(ROI)으로 고정한다.
- 테이프: 영역 안 테이프 색 픽셀 비율 ≥ fill_min이면 붙어 있음. 색은 설정 "tape_color"
    - 초록(기본, 권장): 색상 H 35~95, 채도 ≥ 80, 밝기 ≥ 50. 마운자로 상자에 초록 인쇄는 0%(10-06 실측)
      10-09 시편의 청록 테이프는 H 81~84(채도 156~193, 밝기 84~103)라 상한을 85→95로 넓혔다. 파랑(H≥100)은 여전히 제외
    - 검정: 밝기 ≤ 80, 채도 ≤ 90. 상자 앞면 진회색 화살표 무늬(면적의 16%)도 검정으로 잡히므로 그 위에는 쓰지 말 것
- 냉매: 열화상 원시값 중앙값(상자 표면 영역) - 중앙값(기준 패치 영역) = delta.
        delta ≤ delta_max면 냉매 있음(표면이 차가움). 기준선에서 margin 안이면 판단 보류(review)
        같은 화면 안의 기준과 빼므로 FFC·예열로 생기는 전체 이동이 지워진다(10-06 측정: 절대값 323 → 차이 22 카운트)

설정: calib/rules.json — rules_calib.py로 영역을 지정하고, 실제 시편(있음/없음)으로 기준값을 맞춘다.
validated가 true가 아니면 값만 기록하고 판정은 review(사람 확인)로 둔다. 검증 안 된 기준으로 통과시키지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

CALIB_DIR = Path(__file__).parent / "calib"
PATH = CALIB_DIR / "rules.json"


def load(path=None):
    p = Path(path or PATH)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _crop(img, roi):
    x0, y0, x1, y1 = (int(round(v)) for v in roi)
    h, w = img.shape[:2]
    x0, x1, y0, y1 = max(0, x0), min(w, x1), max(0, y0), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"영역이 화면 밖: {roi}")
    return img[y0:y1, x0:x1]


GREEN = {"mode": "hue", "h": [35, 95], "s_min": 80, "v_min": 50}
BLACK = {"mode": "dark", "v_max": 80, "s_max": 90}


def tape_fill(vis, roi, color=None):
    """영역 안 테이프 색 픽셀 비율 0~1. color: GREEN(기본)·BLACK 형식의 dict."""
    c = color or GREEN
    hsv = cv2.cvtColor(_crop(vis, roi), cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    if c["mode"] == "dark":
        m = (V <= c["v_max"]) & (S <= c["s_max"])
    else:  # OpenCV 색상 H는 0~179
        m = (H >= c["h"][0]) & (H <= c["h"][1]) & (S >= c["s_min"]) & (V >= c["v_min"])
    return float(m.mean())


def tape_blob_areas(vis, roi, color=None, merge_px=9):
    """영역 안 테이프 색 덩어리들의 면적(픽셀)을 큰 순서로. 상자가 아무 방향으로 놓여도 개수를 셀 수 있게
    위치가 아니라 덩어리 수를 본다. 가까운 조각은 merge_px 커널로 닫아 한 덩어리로 묶는다."""
    c = color or GREEN
    img = _crop(vis, roi) if roi else vis
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    if c["mode"] == "dark":
        m = (V <= c["v_max"]) & (S <= c["s_max"])
    else:
        m = (H >= c["h"][0]) & (H <= c["h"][1]) & (S >= c["s_min"]) & (V >= c["v_min"])
    m = m.astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    k = max(1, int(merge_px))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m, 8)
    return sorted((int(st[i, cv2.CC_STAT_AREA]) for i in range(1, n)), reverse=True)


CARDBOARD = {"h": [8, 25], "s_min": 60, "v_min": 60}  # 갈색 골판지(현장 상자) 색 범위


def box_region_bbox(vis, color=None, min_area_px=20000):
    """RGB에서 골판지 색 가장 큰 덩어리의 bbox(x0,y0,x1,y1). 로봇이 든 상자 영역을 잡는다. 없으면 None."""
    c = color or CARDBOARD
    hsv = cv2.cvtColor(vis, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = ((H >= c["h"][0]) & (H <= c["h"][1]) & (S >= c["s_min"]) & (V >= c["v_min"])).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    if st[i, cv2.CC_STAT_AREA] < min_area_px:
        return None
    x, y, w, h = (int(v) for v in st[i, :4])
    return [x, y, x + w, y + h]


def bottom_features(vis, bbox, canny=(60, 160), color=None):
    """밑면 열림 지표 2개(상자 영역 안, 테이프 색 제외):
    edge = 골판지 영역 안 윤곽선 비율(열린 날개의 접힌 선·내부가 드러나면 커짐; 10-09 현장 정상 0.027~0.037, 열림 0.049)
    dark = 골판지 영역 안 어두운 틈 비율(열린 날개 그림자; 정상 ≤0.065, 열림 0.098)"""
    x0, y0, x1, y1 = bbox
    roi = vis[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    c = color or CARDBOARD
    card = (H >= c["h"][0]) & (H <= c["h"][1]) & (S >= c["s_min"]) & (V >= c["v_min"])
    g = GREEN
    green = (H >= g["h"][0]) & (H <= g["h"][1]) & (S >= g["s_min"]) & (V >= g["v_min"])
    card_d = cv2.dilate(card.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    keep = card_d & ~(cv2.dilate(green.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
    e = cv2.Canny(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), canny[0], canny[1]) > 0
    edge = float((e & keep).sum() / max(int(keep.sum()), 1))
    dark = float(((V < 70) & card_d & ~card).sum() / max(int(card_d.sum()), 1))
    return {"edge": round(edge, 4), "dark": round(dark, 4)}


def bottom_edge_density(vis, bbox, canny=(60, 160)):  # 예전 이름 유지
    return bottom_features(vis, bbox, canny)["edge"]


def _tape_count_for(cfg, face):
    """면별 개수 규칙: tape_counts(목록) 우선, 없으면 예전 단일 tape_count."""
    for t in cfg.get("tape_counts") or []:
        if t.get("face") == face:
            return t
    tc = cfg.get("tape_count")
    return tc if tc and tc.get("face") == face else None


def tape_color(cfg):
    if "tape_color" in cfg:
        return cfg["tape_color"]
    if "dark" in cfg:  # 예전 설정(검정)
        return {"mode": "dark", **cfg["dark"]}
    return GREEN


def coolant_delta(lwir_mean, roi, ref_roi):
    """상자 표면 - 기준 패치 (원시 카운트). 음수일수록 표면이 차갑다."""
    return float(np.median(_crop(lwir_mean, roi)) - np.median(_crop(lwir_mean, ref_roi)))


def measure(face, vis, lwir_mean, cfg):
    """이 면에 설정된 항목의 측정값만 계산한다(판정 없음). rules_calib의 기준값 맞추기에도 쓴다."""
    color = tape_color(cfg)
    out = {}
    for t in cfg.get("tapes", []):
        if t["face"] == face:
            out[f"tape_{t['id']}_fill"] = round(tape_fill(vis, t["roi_rgb"], color), 4)
    tc = _tape_count_for(cfg, face)
    if tc:  # 방향 무관 개수 세기: 큰 덩어리 면적 목록(기준값 맞추기와 판정에 함께 쓴다)
        out["tape_blob_areas"] = tape_blob_areas(vis, tc.get("roi_rgb"), color, tc.get("merge_px", 9))[:8]
    bc = cfg.get("bottom_check")
    if bc and bc.get("face") == face:  # 밑면 열림: 상자 영역 윤곽선 밀도
        bb = box_region_bbox(vis, bc.get("box_color"), bc.get("min_box_area_px", 20000))
        out["bottom_box_bbox"] = bb
        feats = bottom_features(vis, bb) if bb else None
        out["bottom_edge_density"] = feats["edge"] if feats else None
        out["bottom_dark_frac"] = feats["dark"] if feats else None
    c = cfg.get("coolant")
    if c and c.get("face") == face:
        out["coolant_delta_counts"] = round(coolant_delta(lwir_mean, c["roi_lwir"], c["ref_roi_lwir"]), 1)
    return out


def judge_face(face, vis, lwir_mean, cfg):
    """(verdict, reasons, features). 이 면에 검사 항목이 없으면 None."""
    m = measure(face, vis, lwir_mean, cfg)
    version = cfg.get("version", "tape-coolant-unversioned")
    validated = cfg.get("validated") is True
    if not m:
        if validated and face in cfg.get("faces_without_checks_ok", []):
            return "no_anomaly", [], {"defect_inspected": True, "defect_rules_version": version, "defect_checks": 0}
        return None
    f = dict(m)
    reasons, uncertain = [], []
    tapes_here = [t for t in cfg.get("tapes", []) if t["face"] == face]
    missing_ids = []
    for t in tapes_here:
        thr = t.get("fill_min")
        present = None if thr is None else m[f"tape_{t['id']}_fill"] >= thr
        f[f"tape_{t['id']}_present"] = present
        if present is False:
            reasons.append(f"tape_missing_{t['id']}")
            missing_ids.append(t["id"])
        elif present is None:
            uncertain.append(f"tape_threshold_missing_{t['id']}")
    if tapes_here:  # 면별 개수 요약: "3개 중 1개 누락" 식으로 화면·기록에 바로 쓰인다
        f["tape_expected"] = len(tapes_here)
        f["tape_present_count"] = sum(1 for t in tapes_here if f[f"tape_{t['id']}_present"] is True)
        f["tape_missing_count"] = len(missing_ids)
        f["tape_missing_ids"] = missing_ids
    tc = _tape_count_for(cfg, face)
    if tc:  # 상자 방향이 랜덤일 때: 영역 고정 대신 테이프 덩어리 개수 ≥ 기대 개수
        expected, min_area = int(tc.get("expected", 3)), tc.get("min_area_px")
        areas = m.get("tape_blob_areas", [])
        if min_area is None:
            count = None
            uncertain.append("tape_threshold_missing_count")
        else:
            count = sum(1 for a in areas if a >= min_area)
            total = sum(a for a in areas if a >= min_area)
            f["tape_total_area_px"] = total
            gold_total = tc.get("golden_total_area_px")
            frac_cfg = tc.get("min_total_area_frac")
            if frac_cfg and gold_total and count < expected and total >= frac_cfg * gold_total:  # 기본은 끔(개수만 본다)
                # 조각 둘이 붙어 한 덩어리로 보이는 경우(상자 각도): 총면적이 기준에 가까우면 다 있는 것으로 본다. 하나 빠지면 면적이 1/3 줄어 걸린다
                f["tape_merged_blobs"] = True
                count = expected
        f["tape_expected"] = expected
        f["tape_present_count"] = None if count is None else min(count, expected)
        f["tape_missing_count"] = None if count is None else max(0, expected - count)
        f["tape_blob_count"] = count
        f.setdefault("tape_missing_ids", [])
        if count is not None and count < expected:
            reasons.append(f"tape_missing_count_{expected - count}")
        elif count is not None and count > expected and tc.get("extra_is_uncertain", True):
            uncertain.append("tape_extra_blobs")  # 초록이 더 보이면(배경·다른 상자) 자동 통과시키지 않는다
    bc = cfg.get("bottom_check")
    if bc and bc.get("face") == face:
        dens, dark = m.get("bottom_edge_density"), m.get("bottom_dark_frac")
        thr_e, thr_d = bc.get("edge_max"), bc.get("dark_max")
        if dens is None:
            f["bottom_open"] = None
            uncertain.append("bottom_box_not_found")
        elif thr_e is None and thr_d is None:
            f["bottom_open"] = None
            uncertain.append("bottom_threshold_missing")
        else:  # 두 지표 중 하나라도 기준을 넘으면 열림(fail-closed)
            f["bottom_open"] = bool((thr_e is not None and dens > thr_e) or (thr_d is not None and dark is not None and dark > thr_d))
            if f["bottom_open"]:
                reasons.append("bottom_open")
    c = cfg.get("coolant")
    if c and c.get("face") == face:
        d, thr, margin = m["coolant_delta_counts"], c.get("delta_max_counts"), c.get("margin_counts", 0)
        if thr is None:
            f["coolant_present"] = None
            uncertain.append("coolant_threshold_missing")
        elif abs(d - thr) < margin:
            f["coolant_present"] = None
            uncertain.append("coolant_uncertain")
        else:
            f["coolant_present"] = d <= thr
            if not f["coolant_present"]:
                reasons.append("coolant_absent")
    f.update(defect_rules_version=version, defect_checks=len(m))
    if not validated:  # 기준값이 실제 시편으로 검증되기 전: 기록만
        f["defect_inspected"] = False
        return "review", ["defect_rules_unvalidated"], f
    f["defect_inspected"] = True
    if reasons:
        return "suspect", reasons, f
    if uncertain:
        return "review", uncertain, f
    return "no_anomaly", [], f
