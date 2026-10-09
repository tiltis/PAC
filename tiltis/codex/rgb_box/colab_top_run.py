"""Colab cell body: loaded detector/segmenter, uploaded RGB files, CUDA runtime."""
from top_face import propose_faces, annotate_face
from google.colab import files
import json, shutil
from pathlib import Path
from PIL import Image
from IPython.display import display

face_dir = Path('/content/pac_sam_faces')
face_dir.mkdir(exist_ok=True)
face_summary = []
for index, name in enumerate(uploaded, 1):
    image = Image.open(name).convert('RGB')
    detection = detector.detect(image)
    if detection['candidate_count'] != 1:
        face_summary.append({'image': name, 'reason': 'single_box_not_confirmed', 'faces': []})
        continue
    whole, _ = segmenter.segment(image, detection['detections'])
    faces, masks, info = propose_faces(segmenter, image, detection['detections'][0], whole[0])
    for number, (candidate, mask) in enumerate(zip(faces, masks), 1):
        stem = f'{index:02}_{Path(name).stem}_face{number}'
        Image.fromarray(mask.astype('uint8') * 255).save(face_dir / f'{stem}_mask.png')
        vis = annotate_face(image, candidate, mask)
        vis.save(face_dir / f'{stem}.png')
        candidate['mask_file'] = f'{stem}_mask.png'
        candidate['preview_file'] = f'{stem}.png'
        display(vis.resize((min(image.width, 800), round(image.height * min(image.width, 800) / image.width))))
    row = dict(image=name, faces=faces, **info)
    face_summary.append(row)
    print(json.dumps(row, ensure_ascii=False))
manifest = {'gpu': torch.cuda.get_device_name(0), 'motion_enabled': False, 'robot_ready': False,
            'top_confirmed': False, 'results': face_summary,
            'note': 'RGB candidates include tape/front faces. Registered depth must select the top plane.'}
(face_dir / 'summary.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
print('SAM FACE GPU COMPLETE', manifest['gpu'], 'images:', len(face_summary), '| DEPTH REQUIRED')
files.download(shutil.make_archive('/content/pac_sam_faces_gpu', 'zip', face_dir))
