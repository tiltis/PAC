"""시편 ID 마커(ArUco). RGB 영상에서 붙어 있는 마커 번호를 읽어 요청한 시편과 같은 물체인지 확인한다.

    python marker.py sheet          # → calib/specimen_markers.pdf (S01~S12, 마커 한 변 40mm)

- 시편 ID의 숫자가 마커 번호다(S01 → 1). 숫자가 없거나 1~49 밖이면 확인하지 않는다(None).
- 마커는 검사면이 아닌 곳, 두 검사 자세 모두에서 RGB 카메라에 보이는 곳에 붙인다.
- 지금은 결과를 기록만 한다. 판정에 반영하려면 현장에서 인식률을 확인한 뒤 정한다.
"""
import re
import sys
from pathlib import Path

import cv2
import numpy as np

DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
CALIB_DIR = Path(__file__).parent / "calib"
_detector = cv2.aruco.ArucoDetector(DICT, cv2.aruco.DetectorParameters())


def expected_id(specimen_id):
    m = re.search(r"(\d+)$", specimen_id or "")
    n = int(m.group(1)) if m else None
    return n if n is not None and 1 <= n < 50 else None


def detect(vis):
    gray = cv2.cvtColor(vis, cv2.COLOR_BGR2GRAY) if vis.ndim == 3 else vis
    corners, ids, _ = _detector.detectMarkers(gray)
    if ids is None:
        return []
    return [{"id": int(i), "center": [round(float(x), 1) for x in c.reshape(4, 2).mean(axis=0)],
             "corners": c.reshape(4, 2).round(1).tolist()} for i, c in zip(ids.ravel(), corners)]


def check(vis, specimen_id):
    """{"marker_ids", "marker_expected", "marker_match"}. match: 일치 True, 다른 번호만 보임 False, 판단 불가 None."""
    found = detect(vis)
    ids = sorted({m["id"] for m in found})
    exp = expected_id(specimen_id)
    if exp is None or not ids:
        match = None
    else:
        match = exp in ids and len(ids) == 1  # 다른 시편 마커가 같이 보이면 같은 물체라고 하지 않는다
    return {"marker_ids": ids, "marker_expected": exp, "marker_match": match}, found


def draw(vis, found, expected=None):
    out = vis.copy()
    for m in found:
        pts = np.array(m["corners"], np.int32)
        color = (0, 200, 0) if expected is None or m["id"] == expected else (0, 0, 255)
        cv2.polylines(out, [pts], True, color, max(2, out.shape[1] // 400))
        x, y = map(int, m["center"])
        cv2.putText(out, f"S{m['id']:02d}", (x - 30, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    out.shape[1] / 900, color, max(2, out.shape[1] // 400))
    return out


def make_sheet(n=12, marker_mm=40, dpi=300):
    mm = dpi / 25.4
    W, H = round(210 * mm), round(297 * mm)
    page = np.full((H, W), 255, np.uint8)
    cols, cell = 3, 62  # 한 칸 62mm
    x0, y0 = (210 - cols * cell) / 2, 15
    side = round(marker_mm * mm)
    for k in range(n):
        r, c = divmod(k, cols)
        cx, cy = x0 + c * cell + cell / 2, y0 + r * (cell + 8) + cell / 2
        img = cv2.aruco.generateImageMarker(DICT, k + 1, side, borderBits=1)
        tx, ty = round(cx * mm - side / 2), round(cy * mm - side / 2)
        page[ty:ty + side, tx:tx + side] = img
        cv2.putText(page, f"S{k + 1:02d}", (tx, ty + side + round(7 * mm)), cv2.FONT_HERSHEY_SIMPLEX, 2.2, 0, 5)
    cv2.putText(page, f"ArUco 4x4_50, {marker_mm} mm. Print at 100%. Keep a white margin when cutting.",
                (round(10 * mm), round(290 * mm)), cv2.FONT_HERSHEY_SIMPLEX, 1.3, 0, 3)
    CALIB_DIR.mkdir(exist_ok=True)
    png = CALIB_DIR / "specimen_markers.png"
    cv2.imwrite(str(png), page)
    try:
        from PIL import Image
        pdf = CALIB_DIR / "specimen_markers.pdf"
        Image.fromarray(page).convert("RGB").save(pdf, resolution=dpi)
        return pdf
    except ImportError:
        return png


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["sheet"]:
        print("saved", make_sheet())
    else:
        print(__doc__)
