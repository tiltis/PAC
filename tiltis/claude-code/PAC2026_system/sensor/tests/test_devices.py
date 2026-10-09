"""손목 카메라처럼 이름이 겹치는 장치가 함께 꽂혀도 RGB 카메라를 고를 수 있어야 한다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
devices = pytest.importorskip("devices")


@pytest.fixture
def names(monkeypatch):
    for k in ("PAC2026_VIS_NAME", "PAC2026_VIS_INDEX"):
        monkeypatch.delenv(k, raising=False)
    lst = ["Integrated Webcam", "Arducam IMX179 8MP Camera", "FLIR Video", "Arducam IMX179 Wrist"]
    monkeypatch.setattr(devices, "video_devices", lambda: lst)
    return lst


def test_duplicate_name_refuses_without_choice(names):
    with pytest.raises(RuntimeError, match="PAC2026_VIS_NAME"):
        devices.find_video_index(devices.VIS_NAME, "VIS")
    assert devices.find_video_index(devices.LWIR_NAME, "LWIR") == 2


def test_exact_name_and_index_override(names, monkeypatch):
    monkeypatch.setenv("PAC2026_VIS_NAME", "arducam imx179 8mp camera")
    assert devices.find_video_index(devices.VIS_NAME, "VIS") == 1
    monkeypatch.setenv("PAC2026_VIS_INDEX", "3")  # 번호가 이름보다 우선
    assert devices.find_video_index(devices.VIS_NAME, "VIS") == 3
    monkeypatch.setenv("PAC2026_VIS_INDEX", "9")
    with pytest.raises(RuntimeError, match="범위 밖"):
        devices.find_video_index(devices.VIS_NAME, "VIS")


def test_exact_name_must_match_one(names, monkeypatch):
    monkeypatch.setenv("PAC2026_VIS_NAME", "Arducam IMX179")  # 일부만 같은 이름은 받지 않는다
    with pytest.raises(RuntimeError, match="0개"):
        devices.find_video_index(devices.VIS_NAME, "VIS")
