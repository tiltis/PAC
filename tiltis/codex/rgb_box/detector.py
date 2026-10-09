"""Stage 1: RGB box candidates only. No depth, calibration or motor imports."""
from __future__ import annotations

import math
import time

from device import select_device, synchronize

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
MODEL_REVISION = "a2bb814dd30d776dcf7e30523b00659f4f141c71"
DEFAULT_LABELS = ["a cardboard box", "a white cardboard box"]


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    aa, bb = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (aa + bb - overlap)


def candidates(boxes, scores, labels, size, threshold=0.4, nms_iou=0.5):
    """Validate model coordinates; merge duplicate text matches, retain separate objects."""
    if len(boxes) != len(scores) or len(boxes) != len(labels):
        raise ValueError("model result lengths differ")
    width, height = size
    result = []
    for box, score, label in zip(boxes, scores, labels):
        coords, score = [float(v) for v in box], float(score)
        if len(coords) != 4 or not all(math.isfinite(v) for v in [*coords, score]):
            raise ValueError("nonfinite model result")
        if not 0 <= score <= 1:
            raise ValueError("invalid model score")
        if score < threshold:
            continue
        x0, y0, x1, y1 = coords
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("model box outside source image")
        result.append({"label": str(label), "score": round(score, 4),
                       "bbox_px": [round(v, 2) for v in coords],
                       "center_px": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)]})
    kept = []
    for item in sorted(result, key=lambda v: v["score"], reverse=True):
        if not any(iou(item["bbox_px"], v["bbox_px"]) >= nms_iou for v in kept):
            kept.append(item)
    return kept


class BoxDetector:
    def __init__(self, model_dir=None, threads=4, shortest_edge=512, labels=None, threshold=0.4, device="cpu"):
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        torch.set_num_threads(threads)
        self.device = select_device(device, torch)
        self.torch, self.labels, self.threshold = torch, labels or DEFAULT_LABELS, threshold
        model = model_dir or MODEL_ID
        options = {"local_files_only": True}
        if model_dir is None:
            options["revision"] = MODEL_REVISION
        self.processor = AutoProcessor.from_pretrained(model, **options)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            model, **options, use_safetensors=True, disable_custom_kernels=True).to(self.device).eval()
        self.size = {"shortest_edge": shortest_edge, "longest_edge": max(shortest_edge, 768)}

    def detect(self, image):
        synchronize(self.torch, self.device)
        t0 = time.perf_counter()
        inputs = self.processor(images=image, text=[self.labels], size=self.size, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            output = self.model(**inputs)
        parsed = self.processor.post_process_grounded_object_detection(
            output, inputs.input_ids, threshold=self.threshold, text_threshold=0.25,
            target_sizes=[image.size[::-1]])[0]
        # Text labels moved to text_labels in newer Transformers versions.
        labels = parsed.get("text_labels", parsed.get("labels"))
        boxes = candidates(parsed["boxes"].tolist(), parsed["scores"].tolist(), labels,
                           image.size, self.threshold)
        synchronize(self.torch, self.device)
        return {"stage": "rgb_box_detection", "frame": "rgb_preview_px", "motion_enabled": False,
                "robot_ready": False, "depth_association": "not_established", "model": MODEL_ID,
                "model_revision": MODEL_REVISION, "device": self.device, "image_size_px": list(image.size),
                "found": bool(boxes), "candidate_count": len(boxes), "detections": boxes,
                "status": "single_box_candidate" if len(boxes) == 1 else ("multiple_candidates" if boxes else "no_box"),
                "inference_ms": round((time.perf_counter() - t0) * 1000, 1)}
