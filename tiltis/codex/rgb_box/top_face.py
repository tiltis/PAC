"""SAM face proposals for previews. RGB alone does not confirm which face is the top."""
from __future__ import annotations

import time
import cv2
import numpy as np
from PIL import Image, ImageDraw

from device import synchronize
from segment import mask_geometry


def face_prompts(box, size):
    x0, y0, x1, y1 = np.asarray(box, float)
    if not np.isfinite([x0, y0, x1, y1]).all() or not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise ValueError("face prompt box outside source RGB")
    w, h, cx = x1 - x0, y1 - y0, (x0 + x1) / 2
    return [[[cx, y0 + r*h], [cx, y0 + .82*h], [x0 + .15*w, y0 + .65*h], [x0 + .85*w, y0 + .65*h]]
            for r in (.06, .12, .2, .3)]


def face_geometry(mask, whole_mask, points):
    mask_geometry(mask, (whole_mask.shape[1], whole_mask.shape[0]))
    mask_geometry(whole_mask, (whole_mask.shape[1], whole_mask.shape[0]))
    pts = np.asarray(points, float)
    if pts.shape != (4, 2) or not np.isfinite(pts).all():
        raise ValueError("one positive and three negative RGB prompts required")
    xy = np.rint(pts).astype(int)
    if (xy < 0).any() or (xy[:, 0] >= mask.shape[1]).any() or (xy[:, 1] >= mask.shape[0]).any():
        raise ValueError("prompt outside source RGB")
    values = mask[xy[:, 1], xy[:, 0]].tolist()
    area = int(mask.sum())
    fraction = area / int(whole_mask.sum())
    overlap = float((mask & whole_mask).sum()) / area
    if values != [True, False, False, False] or not .05 < fraction < .65 or overlap < .95:
        return None
    contours, _ = cv2.findContours(mask.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    quad = cv2.approxPolyDP(hull, .03 * cv2.arcLength(hull, True), True).reshape(-1, 2)
    if len(quad) != 4:
        return None
    filled = np.zeros(mask.shape, "uint8")
    cv2.fillConvexPoly(filled, quad, 1)
    q_iou = float((mask & (filled > 0)).sum()) / float((mask | (filled > 0)).sum())
    if q_iou < .7:
        return None
    edges = np.roll(quad, -1, axis=0).astype(float) - quad
    if np.linalg.norm(edges, axis=1).min() < 5:
        return None
    # Perspective gives two projected edge directions, not a physical robot yaw.
    directions = [edges[i] / np.linalg.norm(edges[i]) - edges[i + 2] / np.linalg.norm(edges[i + 2]) for i in (0, 1)]
    angles = [round(float(np.degrees(np.arctan2(v[1], v[0])) % 180), 2) for v in directions]
    return {"quad_px": quad.tolist(), "edge_angles_image_deg": angles,
            "quad_iou": round(q_iou, 4), "whole_mask_overlap": round(overlap, 4),
            "whole_mask_fraction": round(fraction, 4), "top_confirmed": False,
            "frame": "rgb_px_y_down", "robot_yaw_deg": None}


def propose_faces(segmenter, image, detection, whole_mask):
    prompts = face_prompts(detection["bbox_px"], image.size)
    synchronize(segmenter.torch, segmenter.device)
    t0 = time.perf_counter()
    inputs = segmenter.processor(images=image, input_points=[prompts],
                                 input_labels=[[[1, 0, 0, 0]] * len(prompts)], return_tensors="pt").to(segmenter.device)
    with segmenter.torch.inference_mode():
        out = segmenter.model(**inputs)
    masks = segmenter.processor.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"].cpu(),
                                                  inputs["reshaped_input_sizes"].cpu())[0]
    proposed, selected_masks = [], []
    for p, points in enumerate(prompts):
        for m in range(masks.shape[1]):
            mask = masks[p, m].numpy().astype(bool)
            if not mask.any():
                continue
            geometry = face_geometry(mask, whole_mask, points)
            if geometry is None:
                continue
            if any((mask & old).sum() / (mask | old).sum() >= .85 for old in selected_masks):
                continue
            proposed.append(dict(geometry, sam_iou_score=round(float(out.iou_scores[0, p, m]), 4), prompt=p, mask=m))
            selected_masks.append(mask)
    synchronize(segmenter.torch, segmenter.device)
    return proposed, selected_masks, {"inference_ms": round((time.perf_counter() - t0) * 1000, 1),
                                      "device": segmenter.device, "selected_top": None,
                                      "selection_requires": "registered_depth_top_plane", "motion_enabled": False}


def annotate_face(image, candidate, mask):
    rgb = np.asarray(image).copy()
    rgb[mask] = (rgb[mask] * .5 + np.array([0, 180, 255]) * .5).astype("uint8")
    vis = Image.fromarray(rgb)
    draw = ImageDraw.Draw(vis)
    quad = candidate["quad_px"]
    draw.line([tuple(v) for v in quad] + [tuple(quad[0])], fill="red", width=3)
    text = f"FACE CANDIDATE | image angles {candidate['edge_angles_image_deg']} | depth required"
    draw.rectangle((0, image.height - 20, image.width, image.height), fill="#102030")
    draw.text((6, image.height - 16), text, fill="white")
    return vis
