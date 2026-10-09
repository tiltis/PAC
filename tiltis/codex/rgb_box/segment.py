"""Optional compact SAM masks, prompted automatically by RGB detector boxes."""
from __future__ import annotations

import time

import numpy as np

from device import select_device, synchronize

MODEL_ID = "Zigeng/SlimSAM-uniform-77"
MODEL_REVISION = "79c09c1ce6b4ae51f00634ed171d9b8e888f6911"


def mask_geometry(mask, size):
    a = np.asarray(mask)
    if a.shape != (size[1], size[0]) or a.dtype != np.bool_:
        raise ValueError("mask must be boolean and match the source RGB dimensions")
    y, x = np.nonzero(a)
    if not len(x):
        raise ValueError("SAM returned an empty mask")
    return {"mask_area_px": int(len(x)), "mask_center_px": [round(float(x.mean()), 2), round(float(y.mean()), 2)],
            "mask_bbox_px": [int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1]}


class BoxSegmenter:
    def __init__(self, device="cpu"):
        import torch
        from transformers import SamModel, SamProcessor
        self.torch = torch
        self.device = select_device(device, torch)
        options = {"revision": MODEL_REVISION, "local_files_only": True}
        self.processor = SamProcessor.from_pretrained(MODEL_ID, **options)
        self.model = SamModel.from_pretrained(MODEL_ID, **options, use_safetensors=True).to(self.device).eval()

    def segment(self, image, detections):
        if not detections:
            return [], {"model": MODEL_ID, "revision": MODEL_REVISION, "device": self.device, "inference_ms": 0}
        synchronize(self.torch, self.device)
        t0 = time.perf_counter()
        inputs = self.processor(images=image, input_boxes=[[v["bbox_px"] for v in detections]], return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            out = self.model(**inputs)
        masks = self.processor.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"].cpu(),
                                                  inputs["reshaped_input_sizes"].cpu())[0]
        selected = []
        for i, detection in enumerate(detections):
            best = int(out.iou_scores[0, i].argmax())
            mask = masks[i, best].numpy().astype(bool)
            detection.update(mask_geometry(mask, image.size), sam_iou_score=round(float(out.iou_scores[0, i, best]), 4))
            selected.append(mask)
        synchronize(self.torch, self.device)
        return selected, {"model": MODEL_ID, "revision": MODEL_REVISION,
                          "device": self.device, "inference_ms": round((time.perf_counter() - t0) * 1000, 1)}
