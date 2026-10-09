"""Read the existing sensor preview; never open another camera handle."""
from __future__ import annotations

import io
import time

import httpx
import numpy as np
from PIL import Image, ImageDraw


def rgb_panel(data, rgb_width=480):
    image = Image.open(io.BytesIO(data)).convert("RGB")
    if type(rgb_width) is not int or rgb_width <= 0 or rgb_width >= image.width:
        raise ValueError("explicit RGB panel width required for composite preview")
    return image.crop((0, 0, rgb_width, image.height))


def fetch_rgb(client, url, rgb_width=480):
    response = client.get(url)
    response.raise_for_status()
    image = rgb_panel(response.content, rgb_width)
    return image, {"received_at_s": time.time(), "capture_time_verified": False,
                   "source": "existing_sensor_composite_preview", "rgb_panel_width_px": rgb_width,
                   "original_rgb_size_px": None}


def annotate(image, result, masks=()):
    out = image.copy()
    if masks:
        rgb = np.asarray(out).copy()
        for mask in masks:
            rgb[mask] = (rgb[mask] * 0.65 + np.array([255, 210, 0]) * 0.35).astype(np.uint8)
        out = Image.fromarray(rgb)
    draw = ImageDraw.Draw(out)
    for i, item in enumerate(result["detections"], 1):
        box, center = item["bbox_px"], item["center_px"]
        draw.rectangle(box, outline="#00ff77", width=3)
        x, y = center
        draw.line((x - 7, y, x + 7, y), fill="#ff66ff", width=2)
        draw.line((x, y - 7, x, y + 7), fill="#ff66ff", width=2)
        label = f"BOX {i} | score {item['score']:.2f}" + (" | SAM" if masks else "")
        left, top = max(0, box[0]), max(36, box[1] - 16)
        draw.rectangle((left, top, min(out.width, left + 185), top + 15), fill="#003b23")
        draw.text((left + 3, top + 1), label, fill="white")
    footer = f"RGB ONLY | {result['candidate_count']} candidates | NO ROBOT COMMANDS"
    draw.rectangle((0, out.height - 20, out.width, out.height), fill="#102030")
    draw.text((6, out.height - 16), footer, fill="white")
    return out
