"""Count wrapped tape attachments at distinct top edges, including merged tape.

Reports observable attachments rather than guessing how many separate physical
tape pieces a connected green region contains. Unseen edges require a new view.
"""
from __future__ import annotations

import cv2
import numpy as np

from guided_top import quad_mask


def _runs(a):
    edges = np.flatnonzero(np.diff(np.r_[False, a, False]))
    return list(zip(edges[::2], edges[1::2]))


def inspect_top(rgb_bgr, quad, sam_mask, *, expected=3, top_confirmed=False, visible_mask=None):
    rgb = np.asarray(rgb_bgr)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("source BGR uint8 image required")
    sam = np.asarray(sam_mask)
    if sam.dtype != np.bool_ or sam.shape != rgb.shape[:2]:
        raise ValueError("SAM mask must match RGB")
    if type(expected) is not int or not 1 <= expected <= 4:
        raise ValueError("expected distinct wrapped edges must be 1..4")
    qmask = quad_mask(quad, rgb.shape[:2])
    visible = np.ones(sam.shape, bool) if visible_mask is None else np.asarray(visible_mask)
    if visible.dtype != np.bool_ or visible.shape != sam.shape:
        raise ValueError("visible mask must match RGB")
    n = 240
    # Source quad has cyclic order; no reliance on camera tilt/rotation.
    target = np.array([[0, 0], [n - 1, 0], [n - 1, n - 1], [0, n - 1]], np.float32)
    H = cv2.getPerspectiveTransform(np.asarray(quad, np.float32), target)
    canonical = cv2.warpPerspective(rgb, H, (n, n))
    valid = cv2.warpPerspective((sam & visible).astype(np.uint8), H, (n, n), flags=cv2.INTER_NEAREST).astype(bool)
    hsv = cv2.cvtColor(canonical, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35, 80, 50], np.uint8), np.array([95, 255, 255], np.uint8)) > 0
    green &= valid
    # Inspect 4%..17% inward; ignore corners so one corner patch cannot
    # impersonate two attachments. Require a finite-width strip at each edge.
    low, high, lo, hi = round(n * .04), round(n * .17), round(n * .12), round(n * .88)
    strips = [a[low:high, lo:hi] for a in (green, np.rot90(green), np.rot90(green, 2), np.rot90(green, 3))]
    seen = [a[low:high, lo:hi] for a in (valid, np.rot90(valid), np.rot90(valid, 2), np.rot90(valid, 3))]
    contacts, ambiguous, edges = [], False, []
    for i, (strip, visibility) in enumerate(zip(strips, seen)):
        runs = _runs(strip.mean(axis=0) >= .65)
        widths = [(b - a) / n for a, b in runs if b - a >= n * .05]
        qualifying = [w for w in widths if .08 <= w <= .55]
        seen_fraction = float(visibility.mean())
        edge_ok = seen_fraction >= .95
        ambiguous |= not edge_ok or len(qualifying) > 1 or any(w > .55 for w in widths)
        if edge_ok and len(qualifying) == 1:
            contacts.append(i)
        edges.append({"edge": i, "visible_fraction": round(seen_fraction, 4),
                      "strip_width_fractions": [round(w, 4) for w in widths], "attachment_present": i in contacts})
    count = len(contacts)
    verdict = "unmeasurable"
    if top_confirmed and not ambiguous:
        verdict = "no_anomaly" if count == expected else "suspect"
    return {"verdict": verdict, "expected_wrapped_edges": expected, "observed_wrapped_edges": count,
            "edges": edges, "needs_another_view": ambiguous or not top_confirmed,
            "top_confirmed": bool(top_confirmed), "method": "canonical_top_edge_attachments",
            "note": "attachment count does not establish the number of physical pieces in merged tape",
            "motion_enabled": False}, canonical, green
