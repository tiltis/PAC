"""A single RGB display outline for the existing three-camera display.

This is an approximate display selection, not a calibrated association with the
depth pick target. Only an unambiguous box in the visible work area is outlined.
No camera is opened and no depth pixels are treated as Arducam coordinates.
"""
from __future__ import annotations

from functools import lru_cache
import importlib.util
from pathlib import Path

import cv2
import numpy as np


DISPLAY_WORKSPACE_ROI = (0.0, 0.4, 1.0, 1.0)


@lru_cache(maxsize=1)
def _zone_hulls():
    """Reuse peer color regions on this RGB frame, without depth projection."""
    path = (Path(__file__).resolve().parents[2] / "claude-code" /
            "PAC2026_system" / "sensor" / "zones.py")
    spec = importlib.util.spec_from_file_location("_pac_overlay_zones", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Zone display rules unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.paper_hulls


@lru_cache(maxsize=1)
def _inspection_colors():
    """Read the peer inspection rules without importing its camera/server code."""
    path = (Path(__file__).resolve().parents[2] / "claude-code" /
            "PAC2026_system" / "sensor" / "rules.py")
    spec = importlib.util.spec_from_file_location("_pac_overlay_rules", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Inspection color rules unavailable")
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    return rules.CARDBOARD, rules.GREEN


def _color_mask(hsv, color):
    h, s, v = cv2.split(hsv)
    return (((h >= color["h"][0]) & (h <= color["h"][1]) &
             (s >= color["s_min"]) & (v >= color["v_min"]))
            .astype(np.uint8) * 255)


def cardboard_outlines(rgb_bgr):
    """Find conservative display regions in this RGB frame only.

    Shared cardboard/tape colors come from the existing inspection rules. Small
    distant boxes require a lower pixel area than the inspection close-up ROI.
    Shape/size filters reject scattered background color, but this heuristic
    cannot identify every box or distinguish every brown background object.
    """
    cardboard, tape = _inspection_colors()
    hsv = cv2.cvtColor(rgb_bgr, cv2.COLOR_BGR2HSV)
    mask = _color_mask(hsv, cardboard)
    height, width = mask.shape
    kernel_size = max(1, int(round(width / 480 * 5)) | 1)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    tape_mask = _color_mask(hsv, tape)
    tape_count, tape_labels, tape_stats, _ = cv2.connectedComponentsWithStats(tape_mask, 8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    outlines = []
    for contour in contours:
        area = cv2.contourArea(contour)
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        x, y, w, h = cv2.boundingRect(contour)
        if not (0.0035 <= area / mask.size <= 0.35):
            continue
        if min(w, h) < max(8, width / 60) or not (0.3 <= w / h <= 4):
            continue
        if hull_area <= 0 or area / hull_area < 0.60:
            continue
        # Include nearby tape that interrupts the cardboard surface, without
        # joining arbitrary green scenery or filling another camera's pixels.
        region = np.zeros_like(mask)
        cv2.drawContours(region, [contour], -1, 255, -1)
        # Keep extension local: a large group of touching boxes must not pull
        # in distant green scenery just because the group's hull is wide.
        reach = max(2, min(int(round(width * 0.025)), int(round(min(w, h) * 0.4))))
        near = cv2.dilate(region, np.ones((2 * reach + 1, 2 * reach + 1), np.uint8)) > 0
        points = [contour]
        for label in np.unique(tape_labels[near]):
            if label == 0 or label >= tape_count:
                continue
            if tape_stats[label, cv2.CC_STAT_AREA] > hull_area:
                continue
            ys, xs = np.nonzero(tape_labels == label)
            if len(xs) and near[ys, xs].mean() >= 0.45:
                points.append(np.column_stack((xs, ys)).astype(np.int32).reshape(-1, 1, 2))
        outline = cv2.convexHull(np.concatenate(points))
        epsilon = max(1, cv2.arcLength(outline, True) * 0.008)
        outlines.append(cv2.approxPolyDP(outline, epsilon, True))
    return sorted(outlines, key=lambda p: cv2.boundingRect(p)[0])


def single_target_outline(rgb_bgr, workspace_roi=DISPLAY_WORKSPACE_ROI):
    """Return zero or one display contour; never pick the largest of many.

    The normalized ROI excludes the background above this fixed camera's table.
    It is a display filter, not a robot workspace limit. Boxes resting in the
    red/blue destination papers are excluded using the existing color detector.
    Without Arducam/depth calibration, multiple eligible boxes remain ambiguous.
    """
    roi = np.asarray(workspace_roi, dtype=float)
    if (roi.shape != (4,) or not np.isfinite(roi).all() or
            not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1)):
        raise ValueError("Expected normalized display ROI [x0, y0, x1, y1]")
    height, width = rgb_bgr.shape[:2]
    x0, y0, x1, y1 = roi * (width, height, width, height)
    # Mask the background before finding papers: a robot or poster in the
    # background must not expand a destination region on the table.
    table = np.zeros_like(rgb_bgr)
    table[int(y0):int(y1), int(x0):int(x1)] = rgb_bgr[int(y0):int(y1), int(x0):int(x1)]
    zones = _zone_hulls()(table)
    eligible = []
    for outline in cardboard_outlines(rgb_bgr):
        x, y, w, h = cv2.boundingRect(outline)
        if not (x >= x0 and y >= y0 and x + w <= x1 and y + h <= y1):
            continue
        foot = (float(x + w / 2), float(y + h - 1))
        if any(cv2.pointPolygonTest(hull, foot, False) >= 0 for hull in zones.values()):
            continue
        eligible.append(outline)
    return eligible if len(eligible) == 1 else []


def annotate_collage(collage_bgr, rgb_width=480, workspace_roi=DISPLAY_WORKSPACE_ROI):
    """Return a copied BGR collage and 0/1 count; only its RGB panel changes.

    The sensor live.jpg currently puts the 480x360 Arducam panel first. Callers
    must explicitly pass a different width if that server layout changes.
    Thermal/depth pixels are bit-identical in the returned array. JPEG encoding
    can subsequently introduce ordinary compression changes across the image.
    """
    if (not isinstance(collage_bgr, np.ndarray) or collage_bgr.dtype != np.uint8 or
            collage_bgr.ndim != 3 or collage_bgr.shape[2] != 3 or
            not isinstance(rgb_width, int) or rgb_width < 1 or
            collage_bgr.shape[1] < rgb_width or collage_bgr.shape[0] < 1):
        raise ValueError("Expected a uint8 BGR collage with the full RGB panel")
    result = collage_bgr.copy()
    rgb = result[:, :rgb_width]
    outlines = single_target_outline(rgb, workspace_roi=workspace_roi)
    thickness = max(2, int(round(rgb_width / 240)))
    # Drawing into the panel view clips even antialiased strokes at its border.
    cv2.polylines(rgb, outlines, True, (0, 0, 255), thickness, cv2.LINE_AA)
    return result, len(outlines)


def annotate_jpeg(jpeg_bytes, rgb_width=480, workspace_roi=DISPLAY_WORKSPACE_ROI):
    """Return (display JPEG bytes, outlined box count: 0 or 1).

    Invalid images raise ValueError so the caller can report an unavailable
    preview. A valid frame with no candidate is returned byte-for-byte unchanged.
    """
    if not isinstance(jpeg_bytes, (bytes, bytearray)) or not jpeg_bytes:
        raise ValueError("Empty or invalid preview image")
    image = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode preview image")
    annotated, count = annotate_collage(image, rgb_width=rgb_width, workspace_roi=workspace_roi)
    if not count:
        return bytes(jpeg_bytes), 0
    ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("Could not encode preview image")
    return encoded.tobytes(), count
