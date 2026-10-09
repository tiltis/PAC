"""새 PC(현장 노트북)에서 카메라 수신을 확인한다. 결과를 PASS/FAIL로 출력한다.

    python check_cameras.py           # RGB + 열화상
    python check_cameras.py --depth   # + Gemini 2 깊이(USB3 연결·프레임률·내부 파라미터)
"""
import sys
import time
from pathlib import Path

import cv2

from devices import LWIR_NAME, VIS_NAME, find_boson_port, find_video_index, video_devices
from rig import Rig, RigConfig, colorize_y16

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).parent / "check_out"
results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((name, True, detail))
    except Exception as e:
        results.append((name, False, f"{type(e).__name__}: {e}"))
        return None
    return detail


def boson_port():
    port = find_boson_port()
    if not port:
        raise RuntimeError("FLIR 시리얼 포트 없음 (FFC 제어 불가)")
    return port


print("영상 장치:", video_devices())
check("RGB 장치 찾기", lambda: f"번호 {find_video_index(VIS_NAME, 'VIS')}")
check("열화상 장치 찾기", lambda: f"번호 {find_video_index(LWIR_NAME, 'LWIR')}")
check("Boson 제어 포트", boson_port)

rig_obj = check("두 카메라 동시 열기", lambda: Rig(RigConfig(data_root=OUT)))
if rig_obj:
    results[-1] = (results[-1][0], True, f"Boson {rig_obj.boson_info.get('part_number')}")
    # 촬영 앱이 강제 종료되면 Boson이 수동 FFC로 남아 영상이 서서히 흐트러진다. 자동으로 되돌린다
    rig_obj.set_ffc_manual(False)

    def fps():
        v0, l0 = rig_obj.vis.count, rig_obj.lwir.count
        time.sleep(5)
        v, l = (rig_obj.vis.count - v0) / 5, (rig_obj.lwir.count - l0) / 5
        if v < 1 or l < 20:
            raise RuntimeError(f"프레임률 낮음: RGB {v:.1f}fps, 열화상 {l:.1f}fps (USB 포트를 바꿔 볼 것)")
        return f"RGB {v:.1f}fps, 열화상 {l:.1f}fps"
    check("5초 동시 수신", fps)

    def y16():
        f, _, _ = rig_obj.lwir.latest()
        return f"{f.dtype} {f.shape}, 원시값 {int(f.min())}~{int(f.max())}"
    check("Y16 원시값", y16)
    def ffc():
        if not rig_obj.boson:
            raise RuntimeError("Boson 제어 포트가 없어 FFC 불가")
        rig_obj.do_ffc()
        return "완료"
    check("FFC 실행", ffc)

    if "--depth" in sys.argv:  # Gemini 2를 RGB·열화상과 동시에 돌려 본다(연결 속도·프레임률·내부 파라미터)
        def depth_check():
            from depth import OrbbecDepthSource
            src = OrbbecDepthSource()
            src.start()
            try:
                conn = src.device_info.get("connection") or "?"
                f0 = src.next_after(0)
                time.sleep(3)
                f1 = src.latest()
                fps = (f1.frame_index - f0.frame_index) / 3 if f1 is not None and f0.frame_index is not None else 0
                if "3" not in conn.split("USB")[-1][:2]:
                    raise RuntimeError(f"Gemini 2가 {conn}로 연결됨: USB3 포트에 직접(또는 USB3 연장선) 연결할 것")
                if fps < 20:
                    raise RuntimeError(f"깊이 {fps:.1f}fps로 낮음 (선·허브·포트 확인)")
                if not src.intrinsics:
                    raise RuntimeError("깊이 내부 파라미터를 읽지 못함")
                return f"{conn}, 깊이 {fps:.1f}fps (RGB·열화상과 동시), fx={src.intrinsics['fx']:.1f}"
            finally:
                src.close()
        check("Gemini 2 깊이", depth_check)

    def save():
        OUT.mkdir(exist_ok=True)
        vis, _, _ = rig_obj.vis.latest()
        lw, _, _ = rig_obj.lwir.latest()
        cv2.imwrite(str(OUT / "vis.png"), vis)
        cv2.imwrite(str(OUT / "lwir_preview.png"), colorize_y16(lw))
        return str(OUT)
    check("샘플 저장", save)
    rig_obj.close()

print()
for name, ok, detail in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
failed = [r for r in results if not r[1]]
print("\n결과:", "모두 통과" if not failed else f"{len(failed)}개 실패")
sys.exit(1 if failed else 0)
