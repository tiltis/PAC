"""Build a self-contained Colab notebook from the reviewed local inference modules."""
import json
from pathlib import Path


def build():
    here = Path(__file__).resolve().parent
    cells = []

    def markdown(source):
        cells.append(dict(cell_type="markdown", metadata={}, source=source))

    def code(source):
        cells.append(dict(cell_type="code", metadata={}, source=source, execution_count=None, outputs=[]))

    markdown("# PAC2026: RGB 상자 검출 + SAM 분리 — Colab GPU\n"
             "1단계는 RGB 사진에서 상자의 bbox/마스크를 검증합니다. 로봇/직렬 포트/로컬 서버 연결은 없습니다.\n\n"
             "런타임 → 런타임 유형 변경 → **T4 GPU** 선택 후 위에서부터 실행하세요. GPU가 없으면 중단합니다. "
             "자신의 카메라에서 RGB 사진만 업로드하세요. 개인 Drive 전체를 마운트하거나 HF 토큰을 요구하지 않습니다.\n\n"
             "Colab의 127.0.0.1은 현장 노트북이 아닙니다. 실제 카메라 스트림·깊이·로봇 제어 연결은 다음 단계이며 "
             "클라우드 추론 시간을 실제 제어 지연으로 취급하지 않습니다. 기존 LeRobot 정책 학습 노트북과 별도입니다.")
    code('import os, sys, json, time, subprocess\nfrom pathlib import Path\nimport torch\n'
         'assert torch.cuda.is_available(), "GPU 없음: 런타임 유형을 T4 GPU로 변경하세요"\n'
         'print("GPU:", torch.cuda.get_device_name(0), "torch:", torch.__version__)\n'
         'subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], check=True)\n'
         'Path("/content/pac_rgb").mkdir(exist_ok=True)\n'
         'subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers==5.13.0", '
         '"huggingface_hub>=1.3,<2", "httpx>=0.28,<1", "Pillow>=10", "opencv-python-headless>=4.10,<5"], check=True)')
    markdown("## 공유 구현 사용\n아래 파일은 `tiltis/codex/rgb_box`의 구현을 그대로 포함합니다. "
             "수정 시 `make_colab.py`를 다시 실행해 노트북을 갱신하세요.")
    for name in ("device.py", "detector.py", "segment.py", "source.py", "top_face.py"):
        code(f"%%writefile /content/pac_rgb/{name}\n" + (here / name).read_text(encoding="utf-8"))
    markdown("## 공개 모델 다운로드 및 GPU 로드\n모델 revision 고정, safetensors만 사용. "
             "모델 가중치 로드 시간은 사진별 추론 시간에서 제외합니다.")
    code('sys.path.insert(0, "/content/pac_rgb")\n'
         'from detector import BoxDetector, MODEL_ID as DINO_ID, MODEL_REVISION as DINO_REV\n'
         'from segment import BoxSegmenter, MODEL_ID as SAM_ID, MODEL_REVISION as SAM_REV\n'
         'from source import annotate\nfrom PIL import Image\nfrom IPython.display import display\n'
         'import shutil, transformers\n'
         'hf = shutil.which("hf")\nassert hf, "hf CLI installation missing"\n'
         'subprocess.run([hf, "download", DINO_ID, "model.safetensors", "config.json", "preprocessor_config.json", '
         '"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "vocab.txt", '
         '"--revision", DINO_REV], check=True)\n'
         'subprocess.run([hf, "download", SAM_ID, "model.safetensors", "config.json", "preprocessor_config.json", '
         '"--revision", SAM_REV], check=True)\n'
         'detector = BoxDetector(device="cuda")\nsegmenter = BoxSegmenter(device="cuda")\n'
         'assert next(detector.model.parameters()).is_cuda and next(segmenter.model.parameters()).is_cuda\n'
         'print("GPU models loaded:", detector.device, segmenter.device)')
    markdown("## RGB 사진 업로드\n검증할 실제 RGB 사진을 선택하세요. 3카메라 합성 사진 대신 RGB 패널만 선택하세요. "
             "파일 선택 위젯이 동작하지 않으면 왼쪽 **파일 → 세션 저장소에 업로드**로 사진을 올리고 "
             "아래 `IMAGE_FILES`에 파일 이름을 넣으세요. 업로드한 파일은 이 Colab 세션의 추론 입력이며 GitHub에는 넣지 않습니다.")
    code('from google.colab import files\n'
         'IMAGE_FILES = []  # 파일 패널로 올렸다면 ["box1.png", "box2.png"]처럼 지정\n'
         'if IMAGE_FILES:\n'
         '    assert all(Path(name).is_file() for name in IMAGE_FILES), "파일 패널에 먼저 업로드하세요"\n'
         '    uploaded = {name: b"" for name in IMAGE_FILES}\n'
         'else:\n    uploaded = files.upload()\n'
         'assert uploaded, "검증할 RGB 사진이 필요합니다"\nprint("RGB files:", list(uploaded))')
    markdown("## 검출·분리·저장\n사진마다 RGB 픽셀 bbox/중심/마스크와 추론 시간을 표시합니다. "
             "GPU 워밍업 한 장은 시간 비교에서 제외하고 모든 입력을 다시 처리합니다. "
             "CUDA 동기화 후 시간을 기록합니다. 모델 점수/추정 IoU는 측정한 정확도가 아닙니다.")
    code('output_dir = Path("/content/pac_rgb_results")\noutput_dir.mkdir(exist_ok=True)\n'
         'names = [name for name in uploaded if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]\n'
         'assert names, "지원되는 RGB 이미지가 없습니다"\n'
         'warm = Image.open(names[0]).convert("RGB")\n'
         'warm_result = detector.detect(warm)\nsegmenter.segment(warm, warm_result["detections"])\n'
         'summary = []\n'
         'for index, name in enumerate(names, 1):\n'
         '    image = Image.open(name).convert("RGB")\n'
         '    result = detector.detect(image)\n'
         '    result["frame"] = "uploaded_rgb_px"\n'
         '    result["source_metadata"] = {"source": "colab_uploaded_rgb", "filename": Path(name).name, '
         '"capture_time_verified": False}\n'
         '    masks, result["segmentation"] = segmenter.segment(image, result["detections"])\n'
         '    stem = f"{index:03}_{Path(name).stem}"\n'
         '    for number, mask in enumerate(masks, 1):\n'
         '        mask_name = f"{stem}_mask{number}.png"\n'
         '        Image.fromarray(mask.astype("uint8") * 255).save(output_dir / mask_name)\n'
         '        result["detections"][number - 1]["mask_file"] = mask_name\n'
         '    annotated = annotate(image, result, masks)\n'
         '    annotated.save(output_dir / f"{stem}.png")\n'
         '    (output_dir / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))\n'
         '    row = {"image": Path(name).name, "candidates": result["candidate_count"], '
         '"dino_ms": result["inference_ms"], "sam_ms": result["segmentation"]["inference_ms"], '
         '"detections": result["detections"]}\n'
         '    summary.append(row)\n    print(json.dumps(row, ensure_ascii=False))\n'
         '    display(annotated.resize((min(image.width, 800), round(image.height * min(image.width, 800) / image.width))))\n'
         'manifest = {"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, '
         '"transformers": transformers.__version__, "motion_enabled": False, "robot_ready": False, '
         '"warmup_excluded": True, "results": summary}\n'
         '(output_dir / "summary.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))\n'
         'print("GPU VALIDATION COMPLETE", manifest["gpu"], "images:", len(summary))')
    markdown("## SAM 면 후보와 영상 각도\n상자 전체 마스크와 윗면은 다릅니다. "
             "자동 point/negative prompts로 면 후보·사각형·두 영상 변의 각도를 표시합니다. "
             "테이프나 앞면 후보도 나올 수 있어 RGB 점수로 윗면을 확정하지 않습니다. "
             "`sam_depth.py`에서 검증된 RGB–depth 정합·동시 촬영·책상 평면과 상자 실측 크기를 확인한 후 "
             "로봇 방향에 사용할 3D 축을 생성합니다. 출력의 영상 각도는 로봇 yaw가 아닙니다.")
    code((here / "colab_top_run.py").read_text(encoding="utf-8"))
    markdown("## 상자 전체 결과 다운로드\nPNG/개별 마스크/JSON/환경·시간 요약을 보관합니다. "
             "노트북 실행 결과에 RGB 사진이 표시되므로 공유하기 전에 출력 내용을 확인하세요. "
             "검증 종료 후 런타임 연결 해제로 GPU 사용을 마칩니다.")
    code('archive = shutil.make_archive("/content/pac_rgb_gpu_results", "zip", output_dir)\nfiles.download(archive)')
    notebook = dict(nbformat=4, nbformat_minor=4,
                    metadata={"accelerator": "GPU", "colab": {"name": "PAC_RGB_SAM_GPU.ipynb", "provenance": []},
                              "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, cells=cells)
    path = here / "colab/PAC_RGB_SAM_GPU.ipynb"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    build()
