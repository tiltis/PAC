"""Offline SAM/depth bundle validation. Does not open cameras or robot ports."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from sam_depth import locate_sam_top


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=Path, required=True, help='NPZ with sam_mask (bool) and depth_mm, no pickled objects')
    ap.add_argument('--metadata', type=Path, required=True, help='paired capture times, intrinsics, box_count, table_roi and measured box_models_mm')
    ap.add_argument('--registration', type=Path, required=True, help='verified depth-camera to rectified RGB-camera calibration JSON')
    ap.add_argument('--now-s', type=float, required=True, help='same host clock; replay requires explicit historical evaluation time')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding='utf-8'))
    reg = json.loads(args.registration.read_text(encoding='utf-8'))
    with np.load(args.bundle, allow_pickle=False) as b:
        result, mask = locate_sam_top(b['sam_mask'], b['depth_mm'], metadata['depth_intrinsics'],
                                      metadata['rgb_intrinsics'], reg, metadata['captures'], args.now_s,
                                      box_count=metadata['box_count'], table_roi=metadata['table_roi'],
                                      box_models_mm=metadata['box_models_mm'])
    args.output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask.astype('uint8') * 255).save(args.output / 'top_mask_depth.png')
    (args.output / 'top.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result['found'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
