"""SAM top-face proposal using a depth-projected quad, with visible agreement.

The prompt is not substituted for a SAM result. Agreement is diagnostic;
multi-view field registration and verified timing are still required for motion.
"""
from __future__ import annotations

import cv2
import numpy as np


def quad_mask(quad, shape):
    q = np.asarray(quad, np.float32)
    if q.shape != (4, 2) or not np.isfinite(q).all() or not cv2.isContourConvex(q):
        raise ValueError("finite convex top quad required")
    if (q < 0).any() or (q[:, 0] >= shape[1]).any() or (q[:, 1] >= shape[0]).any():
        raise ValueError("top quad outside source image")
    if abs(cv2.contourArea(q)) < 100:
        raise ValueError("top quad too small")
    m = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(m, np.rint(q).astype(np.int32), 1)
    return m.astype(bool)


def prompts(quad, size):
    q = np.asarray(quad, float)
    quad_mask(q, (size[1], size[0]))
    center = q.mean(0)
    # Four negative points outside the top include the near side face.
    negative = center + 1.5 * ((q + np.roll(q, -1, axis=0)) / 2 - center)
    negative = np.clip(negative, [0, 0], np.array(size) - 1)
    midpoints = (q + np.roll(q, -1, axis=0)) / 2
    # One cardboard-only positive can exclude the attached tape. Ask for the
    # surface at nine spread points together, retaining the outside negatives.
    return [[center.tolist(), *(center + f * (q - center)).tolist(),
             *(center + f * (midpoints - center)).tolist(), *negative.tolist()]
            for f in (.4, .6, .8)]


def agreement(mask, projected_quad):
    mask = np.asarray(mask)
    if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any():
        raise ValueError("nonempty SAM boolean mask required")
    prompt_mask = quad_mask(projected_quad, mask.shape)
    iou = float((mask & prompt_mask).sum() / (mask | prompt_mask).sum())
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    q = cv2.approxPolyDP(hull, .025 * cv2.arcLength(hull, True), True).reshape(-1, 2)
    if len(q) != 4 or iou < .7:
        return None
    reference = np.asarray(projected_quad, float)
    best = min((np.roll(v, shift, axis=0) for v in (q, q[::-1]) for shift in range(4)),
               key=lambda v: np.square(v - reference).sum())
    rms = float(np.sqrt(np.square(best - reference).sum(axis=1).mean()))
    edges = np.roll(best, -1, axis=0) - best
    return {"sam_quad_rgb_px": best.tolist(), "depth_prompt_iou": round(iou, 4),
            "scene_corner_agreement_rms_px": round(rms, 3),
            "image_edge_angles_deg": (np.degrees(np.arctan2(edges[:, 1], edges[:, 0])) % 180).round(2).tolist(),
            "field_registration_validated": False, "motion_enabled": False}


def segment_top(segmenter, image, projected_quad):
    points = prompts(projected_quad, image.size)
    inputs = segmenter.processor(images=image, input_points=[points],
                                 input_labels=[[[1] * 9 + [0] * 4] * len(points)],
                                 return_tensors="pt").to(segmenter.device)
    with segmenter.torch.inference_mode():
        output = segmenter.model(**inputs)
    masks = segmenter.processor.post_process_masks(output.pred_masks.cpu(), inputs["original_sizes"].cpu(),
                                                  inputs["reshaped_input_sizes"].cpu())[0]
    candidates = []
    for p in range(masks.shape[0]):
        for k in range(masks.shape[1]):
            mask = masks[p, k].numpy().astype(bool)
            if not mask.any():
                continue
            result = agreement(mask, projected_quad)
            if result is not None:
                candidates.append((result, mask))
    if not candidates:
        return {"found": False, "reason": "SAM top disagrees with projected depth plane", "motion_enabled": False}, None
    result, mask = max(candidates, key=lambda v: v[0]["depth_prompt_iou"])
    return dict(result, found=True), mask
