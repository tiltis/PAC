"""Read-only Colab validation of uploaded Gemini RGB and projected top prompt."""
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from IPython.display import display
from google.colab import files
from huggingface_hub import snapshot_download

from detector import BoxDetector, MODEL_ID as DINO_ID, MODEL_REVISION as DINO_REV
from segment import BoxSegmenter, MODEL_ID as SAM_ID, MODEL_REVISION as SAM_REV
from guided_top import segment_top, quad_mask
from top_tape import inspect_top

assert torch.cuda.is_available(), "CUDA required"
for model, revision in ((DINO_ID, DINO_REV), (SAM_ID, SAM_REV)):
    snapshot_download(model, revision=revision, allow_patterns=["*.json", "*.txt", "*.safetensors"])
detector = BoxDetector(device="cuda")
segmenter = BoxSegmenter(device="cuda")
image = Image.open('/content/native_flat_rgb.png').convert('RGB')
prompt = json.loads(Path('/content/native_top_prompt.json').read_text())
out = Path('/content/native_sam_result')
out.mkdir(exist_ok=True)
torch.cuda.synchronize()
start = time.perf_counter()
detection = detector.detect(image)
# A grounded RGB class may miss a view or include other tabletop containers.
# Keep its result verbatim; the top proposal is separately bound to the sole
# measured depth box. This is still preview only, never a class fallback for motion.
assert prompt['location'].get('candidate_count') == 1, 'Single measured depth box required'
whole, whole_info = segmenter.segment(image, detection['detections'])
geometry, top = segment_top(segmenter, image, prompt['projected_top_quad_rgb_px'])
torch.cuda.synchronize()
elapsed = (time.perf_counter() - start) * 1000
assert top is not None, geometry
# SAM can label tape/cardboard separately. The diagnostic face boundary comes
# from SAM's own convex quad, not the projected depth prompt. Preserve both.
surface = quad_mask(geometry['sam_quad_rgb_px'], top.shape)
tape, canonical, green = inspect_top(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR),
                                    geometry['sam_quad_rgb_px'], surface, top_confirmed=False)
tape['surface_basis'] = 'SAM convex quadrilateral; occlusion not verified'
Image.fromarray(top.astype('uint8') * 255).save(out/'sam_top_mask.png')
Image.fromarray(surface.astype('uint8') * 255).save(out/'sam_face_polygon.png')
for number, mask in enumerate(whole):
    Image.fromarray(mask.astype('uint8') * 255).save(out/f'sam_whole_mask_{number}.png')
vis = np.asarray(image).copy()
vis[top] = (vis[top] * .6 + np.array([30, 180, 240]) * .4).astype('uint8')
cv2.polylines(vis, [np.asarray(geometry['sam_quad_rgb_px'], np.int32)], True, (255, 40, 40), 2)
Image.fromarray(vis).save(out/'sam_top_preview.png')
cv2.imwrite(str(out/'canonical_top.png'), canonical)
cv2.imwrite(str(out/'top_green.png'), green.astype('uint8') * 255)
result = {'gpu': torch.cuda.get_device_name(0), 'detection': detection, 'geometry': geometry,
          'tape': tape, 'inference_ms': round(elapsed, 2), 'motion_enabled': False,
          'note': 'Offline preview; capture timing and field registration remain unverified.'}
(out/'result.json').write_text(json.dumps(result, indent=2, allow_nan=False))
print('NATIVE SAM TOP GPU COMPLETE', json.dumps(result))
display(Image.fromarray(vis).resize((800, 450)))
display(Image.fromarray(cv2.cvtColor(canonical, cv2.COLOR_BGR2RGB)).resize((480, 480)))
files.download(shutil.make_archive('/content/native_sam_result', 'zip', out))
