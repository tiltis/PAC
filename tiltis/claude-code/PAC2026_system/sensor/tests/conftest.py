"""센서 테스트 공통: 현장 설정 파일(calib/rules.json, calib/object_config.json)이 테스트 결과를 바꾸지 않게 기본값으로 돌린다.
실제 시편으로 맞춘 테이프 영역은 가상 영상 크기와 달라 '영역이 화면 밖' 오류가 나므로 테스트에서는 보지 않는다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _isolate_site_calib(monkeypatch, tmp_path):
    import objects
    import rules
    monkeypatch.setattr(rules, "PATH", tmp_path / "no_rules.json")
    monkeypatch.setattr(objects, "CONFIG_PATH", tmp_path / "no_object_config.json")
    try:  # 현장 timing_policy.json도 테스트에서는 보지 않는다
        import server
        monkeypatch.setattr(server, "CALIB_DIR", tmp_path)
    except Exception:
        pass
