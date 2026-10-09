"""Read-only RGB detection from current sensor preview or an image."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from PIL import Image

from detector import BoxDetector
from source import annotate, fetch_rgb


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, help="ordinary RGB image, not the three-camera composite")
    ap.add_argument("--live-url", default="http://127.0.0.1:8001/live.jpg")
    ap.add_argument("--rgb-width", type=int, default=480, help="current composite RGB panel width; preview pixels only")
    ap.add_argument("--output", type=Path, default=Path.home() / "PAC2026_data/rgb_box")
    ap.add_argument("--model-dir")
    ap.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--interval", type=float, default=1)
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--sam", action="store_true", help="add SlimSAM masks with automatic detector box prompts")
    ap.add_argument("--faces", action="store_true", help="add SAM face proposals and image angles; needs --sam and verified depth for top selection")
    args = ap.parse_args()
    if args.samples < 1 or args.interval < 0 or not 0 < args.threshold < 1:
        ap.error("positive samples, nonnegative interval and threshold in (0,1) required")
    if args.faces and not args.sam:
        ap.error("--faces requires --sam")
    detector = BoxDetector(model_dir=args.model_dir, threshold=args.threshold, device=args.device)
    segmenter = None
    if args.sam:
        from segment import BoxSegmenter
        segmenter = BoxSegmenter(device=args.device)
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=8) as client:
        for i in range(args.samples):
            if args.image:
                image = Image.open(args.image).convert("RGB")
                meta = {"source": "local_rgb_image", "capture_time_verified": False}
            else:
                image, meta = fetch_rgb(client, args.live_url, args.rgb_width)
            result = dict(detector.detect(image), source_metadata=meta)
            masks = []
            if segmenter:
                masks, result["segmentation"] = segmenter.segment(image, result["detections"])
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{i + 1:03}"
            png, js = args.output / f"rgb_{stamp}.png", args.output / f"rgb_{stamp}.json"
            raw = args.output / f"rgb_{stamp}_input.png"
            image.save(raw)
            for j, mask in enumerate(masks, 1):
                mask_path = args.output / f"rgb_{stamp}_mask{j}.png"
                Image.fromarray(mask.astype("uint8") * 255).save(mask_path)
                result["detections"][j - 1]["mask_path"] = str(mask_path.resolve())
            if args.faces:
                from top_face import propose_faces, annotate_face
                result["faces"] = []
                if result["candidate_count"] == 1:
                    faces, face_masks, result["face_proposals"] = propose_faces(segmenter, image, result["detections"][0], masks[0])
                    for j, (face, mask) in enumerate(zip(faces, face_masks), 1):
                        path = args.output / f"rgb_{stamp}_face{j}"
                        Image.fromarray(mask.astype("uint8") * 255).save(str(path) + "_mask.png")
                        annotate_face(image, face, mask).save(str(path) + ".png")
                        face["mask_path"] = str(path.resolve()) + "_mask.png"
                        face["preview_path"] = str(path.resolve()) + ".png"
                    result["faces"] = faces
            annotate(image, result, masks).save(png)
            js.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            print(json.dumps({"image": str(png.resolve()), "input": str(raw.resolve()), "result": str(js.resolve()), **result}, ensure_ascii=True), flush=True)
            if i + 1 < args.samples:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
