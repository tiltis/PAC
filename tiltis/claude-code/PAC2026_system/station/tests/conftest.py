import pytest
import sys
from pathlib import Path

# station 폴더를 import 경로에 추가 (어디서 pytest를 실행해도 동작)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _isolate_grasp_config(monkeypatch, tmp_path):
    """현장 설정 파일(station/calib/grasp_config.json)이 테스트 결과를 바꾸지 않게 기본값으로 돌린다."""
    import grasp
    monkeypatch.setattr(grasp, "CONFIG_PATH", tmp_path / "no_grasp_config.json")
