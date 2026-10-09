"""상자 찾기에서 빼야 할 상자 (10-09 현장).

1) 파랑(정상)·빨강(불량·확인) 구역 종이 위에 놓인 상자: 이미 분류가 끝난 상자다.
   깊이 카메라(Gemini 2)의 자체 컬러에서 파랑/빨강 종이 영역(볼록 껍질)을 찾고, 상자 바닥 중심을
   공장 외부 파라미터로 컬러 화면에 투영해 종이 안이면 무시한다(가장자리에 걸쳐 놓인 상자도 포함).
2) 이미 처리한 상자: 집기 직전 장면과 놓은 뒤 장면을 비교해 새로 생긴 상자 위치를 기억하고,
   그 근처(remember_radius_mm) 상자는 무시한다. 파일(processed_boxes.json)에 남겨 서버를 다시 켜도 유지한다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

ZONE_MARGIN_PX = -20  # 상자 바닥 중심이 종이 경계 바깥 20px(컬러 1280 기준 약 1cm) 안이면 그 구역 상자로 본다
REMEMBER_RADIUS_MM = 45.0


def color_masks(rgb_bgr):
    hsv = cv2.cvtColor(rgb_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sat = (s > 90) & (v > 40)
    return {"blue": sat & (h >= 100) & (h <= 130), "red": sat & ((h <= 8) | (h >= 165))}


def paper_hulls(rgb_bgr, min_area_frac=0.01):
    """파랑/빨강 종이 = 그 색의 가장 큰 덩어리(+겹치는 조각)의 볼록 껍질(위에 놓인 상자가 가린 부분까지 채운다)."""
    out = {}
    min_area = min_area_frac * rgb_bgr.shape[0] * rgb_bgr.shape[1]
    for key, mk in color_masks(rgb_bgr).items():
        mk = cv2.morphologyEx(mk.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        cs, _ = cv2.findContours(mk, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cs = sorted((c for c in cs if cv2.contourArea(c) >= min_area), key=cv2.contourArea, reverse=True)
        if not cs:
            continue
        # 종이 = 가장 큰 덩어리. 위에 놓인 상자가 종이를 둘로 가른 조각(바운딩 박스가 겹침)만 합치고,
        # 떨어져 있는 같은 색(10-09: 협업용 빨간 SO-101 로봇 몸체)은 빼서 구역이 로봇 쪽으로 커지지 않게 한다
        x, y, w, h = cv2.boundingRect(cs[0])
        g = int(0.15 * max(w, h))  # 상자 폭만큼 벌어진 조각도 같은 종이로 본다
        x, y, w, h = x - g, y - g, w + 2 * g, h + 2 * g
        def overlaps(c):
            cx, cy, cw, ch = cv2.boundingRect(c)
            return cx < x + w and x < cx + cw and cy < y + h and y < cy + ch
        out[key] = cv2.convexHull(np.concatenate([cs[0]] + [c for c in cs[1:] if overlaps(c)]))
    return out


def zone_fn(pair):
    """pair: Gemini 컬러·깊이 쌍(native_rgbd observation).
    반환: fn(mask, P, h, n) -> {색: 상자 바닥 중심과 종이 경계의 거리(컬러 px, +면 안쪽)}"""
    reg = pair["metadata"]["registration"]
    R, t = np.asarray(reg["R"], float), np.asarray(reg["t_mm"], float)
    ri = reg["rgb_intrinsics"]
    hulls = paper_hulls(pair["rgb_bgr"])

    def distances(m, P, h, n):
        q = table_center(m, P, h, n) @ R.T + t
        if q[2] <= 0:
            return {}
        uv = (float(ri["fx"] * q[0] / q[2] + ri["cx"]), float(ri["fy"] * q[1] / q[2] + ri["cy"]))
        return {k: float(cv2.pointPolygonTest(hull, uv, True)) for k, hull in hulls.items()}
    return distances


def table_center(m, P, h, n):
    """덩어리를 책상 평면에 내린 중심(깊이 카메라 mm)."""
    return (P[m] - h[m][:, None] * n).mean(0)


class ProcessedMemory:
    def __init__(self, path: Path, radius_mm=REMEMBER_RADIUS_MM):
        self.path = Path(path)
        self.radius = radius_mm
        self.before = []  # 마지막 집기 직전 장면의 상자 중심
        try:
            self.boxes = json.loads(self.path.read_text(encoding="utf-8")).get("boxes", [])
        except (OSError, ValueError):
            self.boxes = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"boxes": self.boxes}, ensure_ascii=False, indent=1), encoding="utf-8")

    def near(self, c):
        return any(np.linalg.norm(np.asarray(b["center_cam_mm"]) - c) < self.radius for b in self.boxes)

    def remember_new(self, after, specimen_id=""):
        """놓은 뒤 장면(after)에서 집기 직전(before)에 없던 상자 = 방금 처리한 상자."""
        new = [c for c in after
               if all(np.linalg.norm(np.asarray(c) - b) >= self.radius for b in self.before) and not self.near(np.asarray(c))]
        for c in new:
            self.boxes.append({"center_cam_mm": [round(float(x), 1) for x in c], "specimen_id": specimen_id, "time": time.time()})
        if new:
            self._save()
        return new

    def clear(self):
        self.boxes, self.before = [], []
        self._save()


def make_ignore(zone, memory, collect=None):
    """locate_box의 ignore_fn. collect가 리스트면 무시 여부와 상관없이 모든 상자 후보 중심을 모은다."""
    def ignore(m, P, h, n):
        c = table_center(m, P, h, n)
        if collect is not None:
            collect.append(c)
        if memory is not None and memory.near(c):
            return "이미 처리한 상자"
        if zone is not None:
            f = zone(m, P, h, n)
            for key, label in (("blue", "파랑 구역 상자"), ("red", "빨강 구역 상자")):
                if f.get(key, -1e9) >= ZONE_MARGIN_PX:
                    return f"{label}(경계에서 {f[key]:+.0f}px)"
        return None
    return ignore
