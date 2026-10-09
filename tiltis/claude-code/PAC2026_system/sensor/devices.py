"""카메라와 Boson 제어 포트를 이름·USB ID로 찾는다.

노트북은 내장 웹캠 때문에 OpenCV 번호가 바뀌고 COM 번호도 PC마다 다르므로 번호를 고정하지 않는다.
pygrabber가 돌려주는 DirectShow 장치 순서는 OpenCV CAP_DSHOW 번호 순서와 같다.

대회 로봇 손목 카메라처럼 이름이 겹치는 장치가 함께 꽂히면 환경변수로 고른다(check_cameras가 장치 목록을 보여 준다).
    PAC2026_VIS_NAME / PAC2026_LWIR_NAME    장치 이름 전체(대소문자 무시, 정확히 일치)
    PAC2026_VIS_INDEX / PAC2026_LWIR_INDEX  이름까지 같을 때 장치 번호
"""
import os

from pygrabber.dshow_graph import FilterGraph
from serial.tools import list_ports

VIS_NAME = "Arducam IMX179"
LWIR_NAME = "FLIR Video"
BOSON_USB_VID = 0x09CB  # FLIR Systems


def video_devices():
    return FilterGraph().get_input_devices()


def find_video_index(name_part, env_key=None):
    """env_key("VIS"/"LWIR")가 있으면 PAC2026_<key>_INDEX → _NAME 순으로 사용자가 고른 장치를 쓴다."""
    names = video_devices()
    idx = os.environ.get(f"PAC2026_{env_key}_INDEX", "").strip() if env_key else ""
    if idx:
        i = int(idx)
        if not 0 <= i < len(names):
            raise RuntimeError(f"PAC2026_{env_key}_INDEX={i}: 장치 번호 범위 밖. 연결된 영상 장치: {names}")
        return i
    exact = os.environ.get(f"PAC2026_{env_key}_NAME", "").strip() if env_key else ""
    if exact:
        hits = [i for i, n in enumerate(names) if n.strip().lower() == exact.lower()]
        if len(hits) != 1:
            raise RuntimeError(f"PAC2026_{env_key}_NAME='{exact}'과 정확히 같은 장치가 {len(hits)}개: {names}. "
                               f"이름이 같으면 PAC2026_{env_key}_INDEX로 번호를 지정할 것")
        return hits[0]
    hits = [i for i, n in enumerate(names) if name_part.lower() in n.lower()]
    if not hits:
        raise RuntimeError(f"'{name_part}' 카메라를 찾지 못함. 연결된 영상 장치: {names}")
    if len(hits) > 1:
        raise RuntimeError(f"'{name_part}' 이름의 장치가 {len(hits)}개: {names}. 하나만 연결하거나 "
                           f"PAC2026_{env_key or '<VIS|LWIR>'}_NAME / _INDEX 환경변수로 고를 것")
    return hits[0]


def find_boson_port():
    for p in list_ports.comports():
        if p.vid == BOSON_USB_VID:
            return p.device
    return None
