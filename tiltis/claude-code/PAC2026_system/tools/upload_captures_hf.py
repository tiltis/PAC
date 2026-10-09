"""PAC2026_data 촬영 샘플을 HF Hub 비공개 데이터셋으로 올린다. 먼저 `hf auth login`."""
from pathlib import Path
from huggingface_hub import HfApi

DATA = Path.home() / "PAC2026_data"
REPO = "tiltis/pac2026_sensor_captures"

api = HfApi()
api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
api.upload_large_folder(folder_path=str(DATA), repo_id=REPO, repo_type="dataset",
                        ignore_patterns=["station.db", "*.zip"])
print("https://huggingface.co/datasets/" + REPO)
