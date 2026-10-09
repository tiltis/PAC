"""RGB · 열화상 · 깊이 3화면 합성. 미리보기 창(capture_app)과 센서 서버의 /live.jpg가 같이 쓴다."""
import cv2
import numpy as np

PANEL_H = 360


def _fit(img, h=PANEL_H, nearest=False):
    s = h / img.shape[0]
    return cv2.resize(img, (round(img.shape[1] * s), h),
                      interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_AREA)


def _label(img, lines):
    for i, t in enumerate(lines):
        y = 22 + 22 * i
        cv2.putText(img, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(img, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def thermal_panel(lwir):
    a = lwir.astype(np.float32)
    lo, hi = np.percentile(a, [1, 99])
    n = (np.clip((a - lo) / max(hi - lo, 1.0), 0, 1) * 255).astype(np.uint8)
    return _label(_fit(cv2.applyColorMap(n, cv2.COLORMAP_INFERNO), nearest=True),
                  ["THERMAL (Y16 raw, relative)", f"raw {int(lo)}~{int(hi)}"])


def depth_panel(raw, scale_mm, near_mm=None, far_mm=None):
    """0(무효)은 검정. 색 범위는 보기용이며 측정 범위가 아니다.

    범위를 안 주면 화면 안 유효 거리의 2~98%로 자동으로 맞춘다. 고정 범위(예: 0.2~1.5m)는
    먼 장면을 한 색으로 뭉개 다른 곳을 보는 것처럼 보이게 했다(2026-10-06 실측).
    """
    mm = raw.astype(np.float32) * scale_mm
    valid = mm[raw > 0]
    if near_mm is None or far_mm is None:
        lo, hi = np.percentile(valid, [2, 98]) if valid.size else (200.0, 1500.0)
        near_mm, far_mm = (lo, hi) if hi - lo > 50 else (lo - 25, lo + 25)
    n = np.clip((mm - near_mm) / (far_mm - near_mm), 0, 1)
    col = cv2.applyColorMap((255 - n * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    col[raw == 0] = 0
    h, w = raw.shape
    c = mm[h // 2 - 10:h // 2 + 10, w // 2 - 10:w // 2 + 10]
    c = c[c > 0]
    centre = f"center {np.median(c):.0f} mm" if c.size else "center: no depth"
    out = _fit(col)
    cv2.drawMarker(out, (out.shape[1] // 2, out.shape[0] // 2), (255, 255, 255), cv2.MARKER_CROSS, 18, 2)
    return _label(out, ["DEPTH (Gemini 2)", centre, f"valid {100 * (raw > 0).mean():.0f}%",
                        f"color {near_mm / 1000:.2f}-{far_mm / 1000:.2f} m (near=red)"])


def empty_panel(text, w=480):
    return _label(np.full((PANEL_H, w, 3), 40, np.uint8), [text])


STATUS_COLOR = {"same_object": (0, 200, 0), "match": (0, 200, 0), "partial": (0, 200, 255),
                "unverified": (0, 200, 255), "not_found": (0, 200, 255),
                "mismatch": (0, 0, 255), "ambiguous": (0, 0, 255)}


def _draw_object(panel, det, scale, status, predicted=None):
    color = STATUS_COLOR.get(status, (255, 255, 0))
    if det is not None and det.found:
        x0, y0, x1, y1 = (int(round(v * scale)) for v in det.bbox)
        cv2.rectangle(panel, (x0, y0), (x1, y1), color, 2)
        cv2.putText(panel, f"OBJ {status}", (x0 + 3, max(14, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    if predicted is not None:  # RGB 물체 위치를 이 카메라로 옮긴 예상 위치
        cv2.drawMarker(panel, (int(predicted[0] * scale), int(predicted[1] * scale)), color, cv2.MARKER_TILTED_CROSS, 16, 2)


def compose(vis, lwir, depth=None, rgb_lines=(), objects=None):
    """depth: (raw uint16, scale_mm) 또는 None(깊이 꺼짐). objects: (검출 dict, 대응 결과) 또는 None."""
    dets, assoc = objects if objects else ({}, None)
    lines = list(rgb_lines)
    if assoc is not None:
        lines.append(f"OBJECT: {assoc['status']}")
    rgb = _fit(vis)
    if assoc is not None:
        _draw_object(rgb, dets.get("rgb"), PANEL_H / vis.shape[0], assoc["status"])
    panels = [_label(rgb, ["RGB (Arducam)", *lines])]
    for cam, img, make in (("lwir", lwir, lambda: thermal_panel(lwir)),
                           ("depth", depth[0] if depth else None, lambda: depth_panel(*depth))):
        if cam == "depth" and depth is None:
            continue
        if img is None:
            panels.append(empty_panel(f"{'THERMAL' if cam == 'lwir' else 'DEPTH'}: no frame"))
            continue
        panel = make()
        if assoc is not None:
            info = assoc.get("cams", {}).get(cam, {})
            _draw_object(panel, dets.get(cam), PANEL_H / img.shape[0], info.get("status", assoc["status"]), info.get("predicted"))
        panels.append(panel)
    return np.hstack(panels)
