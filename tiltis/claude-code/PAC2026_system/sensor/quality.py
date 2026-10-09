"""촬영 품질 검사와 검사 영역 특징값. 하드웨어 없이 테스트할 수 있는 순수 함수만 둔다.

지금 판정은 품질 검사만 한다(어두움, 흐림, 열화상 정지·포화). 결함 판정 규칙은 시편 실험(Step 3) 뒤에 추가한다.
기준값은 calib/thresholds.json으로 덮어쓸 수 있다(현장 조명·거리에 맞춰 조정).
"""
import json
from pathlib import Path

import cv2
import numpy as np

CALIB_DIR = Path(__file__).parent / "calib"
RULES_VERSION = "quality-only-0.3"
DEFAULTS = {
    "rgb_mean_min": 15.0,           # 평균 밝기(0~255). 이보다 어두우면 조명 꺼짐·렌즈 가림
    "rgb_sharpness_min": 40.0,      # 라플라시안 분산(가로 800px로 줄인 회색조 기준)
    "lwir_temporal_std_min": 0.3,   # 프레임 간 잡음이 이보다 작으면 영상이 멈춘 것(정상은 약 2~5)
    "lwir_saturated_frac_max": 0.01,
}


def thresholds():
    p = CALIB_DIR / "thresholds.json"
    t = dict(DEFAULTS)
    if p.exists():
        t.update(json.loads(p.read_text(encoding="utf-8")))
    return t


def rgb_sharpness(vis):
    g = cv2.cvtColor(vis, cv2.COLOR_BGR2GRAY)
    scale = 800 / g.shape[1]
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def lwir_stats(stack):
    s = stack.astype(np.float32)
    return {
        "lwir_temporal_std": float(s.std(axis=0).mean()),
        "lwir_saturated_frac": float(((stack == 0) | (stack == np.iinfo(stack.dtype).max)).mean()),
    }


def roi_features(lwir_mean, registration, roi):
    """RGB 좌표로 정한 검사 영역·기준 패치를 열화상으로 옮겨 평균 차를 구한다.

    roi: {"inspect": [[x,y],...], "reference": [[x,y],...]} (RGB 픽셀 다각형)
    """
    out = {}
    means = {}
    for name in ("inspect", "reference"):
        if name not in roi:
            continue
        poly = registration.vis_to_lwir(np.array(roi[name], np.float64))
        mask = np.zeros(lwir_mean.shape, np.uint8)
        cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 1)
        if mask.sum() < 4:
            out[f"lwir_{name}_px"] = int(mask.sum())
            continue
        means[name] = float(lwir_mean[mask > 0].mean())
        out[f"lwir_{name}_mean"] = round(means[name], 2)
        out[f"lwir_{name}_px"] = int(mask.sum())
    if len(means) == 2:
        out["lwir_roi_delta"] = round(means["inspect"] - means["reference"], 2)
    return out


def judge(vis, stack, t=None):
    """품질 검사 결과 (verdict, reasons, features)."""
    t = t or thresholds()
    f = {"rgb_mean": round(float(vis.mean()), 2), "rgb_sharpness": round(rgb_sharpness(vis), 2),
         **{k: round(v, 4) for k, v in lwir_stats(stack).items()}}
    reasons = []
    if f["rgb_mean"] < t["rgb_mean_min"]:
        reasons.append("rgb_dark")  # 어두우면 선명도도 낮게 나오므로 흐림과 따로 알린다
    elif f["rgb_sharpness"] < t["rgb_sharpness_min"]:
        reasons.append("rgb_blur")
    if f["lwir_temporal_std"] < t["lwir_temporal_std_min"]:
        reasons.append("lwir_frozen")
    if f["lwir_saturated_frac"] > t["lwir_saturated_frac_max"]:
        reasons.append("lwir_saturated")
    if reasons:
        return "unmeasurable", reasons, f
    # 촬영 품질 통과는 결함 검사 통과가 아니다. 검증된 결함 규칙이 아직 없다.
    return "review", ["defect_rules_unavailable"], f
