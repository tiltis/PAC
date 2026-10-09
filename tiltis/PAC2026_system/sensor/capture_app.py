"""실시간 미리보기와 촬영쌍 저장.

    python capture_app.py --session 20261003_calib --specimen target01

키
  SPACE  촬영(FFC → 0.5초 대기 → RGB 1장 + 열화상 8장 저장)
  a / b  촬영 면 선택
  n      시편 번호 +1 (target01 → target02)
  f      FFC 지금 실행
  m      FFC 자동 / 수동 전환 (실험 촬영은 수동 권장)
  l      RGB 노출·화이트밸런스를 현재 값으로 고정
  [ / ]  RGB 노출 한 단계 어둡게 / 밝게
  s      Arducam 드라이버 설정창 (열려 있는 동안 RGB 미리보기가 멈출 수 있음)
  o      저장된 현재 면의 정합으로 열화상을 RGB 위에 겹쳐 보기 (calib/H_face<A|B>.json)
--depth를 주면 Gemini 2 깊이 화면을 세 번째 칸에 띄운다(촬영 저장은 RGB·열화상만, 깊이 기록은 server.py --depth).
RGB 화면에는 시편 ID 마커(marker.py)를 찾아 표시한다. 시편 번호와 같으면 초록, 다르면 빨강.

같은 물체 확인(objects.py)
  g      지금 화면을 빈 장면(배경)으로 저장. 물체를 모두 치운 뒤 누른다 (--depth면 깊이 배경도)
  j      물체를 놓고 누르면 세 카메라의 물체 위치를 대응점으로 추가. 4곳 이상 놓아 가며 반복
  배경이 있으면 카메라마다 물체 상자를 그린다. 초록=같은 물체, 노랑=미검증·일부 미검출, 빨강=위치 불일치
  q      종료
열화상 화면에 마우스를 올리면 그 픽셀의 원시값이 표시된다.
"""
import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import live
import marker
import objects
from registration import Registration, to_u8
from rig import DEFAULT_DATA_ROOT, LWIR_H, LWIR_W, Rig, RigConfig, colorize_y16

sys.stdout.reconfigure(encoding="utf-8")
VIEW_H = 480
WIN = "PAC2026 capture"


def load_overlay(face, state):
    try:
        return Registration.load(face)
    except FileNotFoundError:
        state["msg"] = f"face {face}: no calib/H_face{face}.json"
        return None


def bump_id(s):
    m = re.search(r"(\d+)$", s)
    if not m:
        return s + "02"
    return s[: m.start()] + str(int(m.group(1)) + 1).zfill(len(m.group(1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=dt.date.today().strftime("%Y%m%d"))
    ap.add_argument("--specimen", default="test01")
    ap.add_argument("--face", default="A", choices=["A", "B"])
    ap.add_argument("--vis-res", default="1600x1200")
    ap.add_argument("--exposure", type=float, default=None, help="RGB 노출(log2초, 예: -6). 생략하면 자동")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    ap.add_argument("--note", default="")
    ap.add_argument("--depth", action="store_true", help="Gemini 2 깊이 화면도 띄운다")
    args = ap.parse_args()

    w, h = map(int, args.vis_res.lower().split("x"))
    rig = Rig(RigConfig(vis_width=w, vis_height=h, vis_exposure=args.exposure, data_root=Path(args.data_root)))
    print("Boson:", rig.boson_info)
    depth_src = None
    if args.depth:
        from depth import OrbbecDepthSource
        depth_src = OrbbecDepthSource()
        depth_src.start()
        print("Depth:", depth_src.device_info)

    state = {"specimen": args.specimen, "face": args.face, "msg": "", "mouse": None}
    lw_scale = VIEW_H / LWIR_H
    vis_w = round(w * VIEW_H / h)

    def on_mouse(event, x, y, flags, _):
        lx = x - vis_w
        state["mouse"] = (int(lx / lw_scale), int(y / lw_scale)) if lx >= 0 else None

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WIN, on_mouse)

    fpa, fpa_t = rig.fpa_temp(), time.time()
    fps_t, fps_v, fps_l = time.time(), (rig.vis.count, 0.0), (rig.lwir.count, 0.0)
    markers, mk_info, loop = [], {}, 0
    bg, cmap, obj = objects.load_background(), objects.load_map(), None
    try:
        while True:
            vis, _, _ = rig.vis.latest()
            lw, _, _ = rig.lwir.latest()
            now = time.time()
            if now - fpa_t > 3:
                fpa, fpa_t = rig.fpa_temp(), now
            if now - fps_t > 1:
                fps_v = (rig.vis.count, (rig.vis.count - fps_v[0]) / (now - fps_t))
                fps_l = (rig.lwir.count, (rig.lwir.count - fps_l[0]) / (now - fps_t))
                fps_t = now

            if state.get("overlay"):
                if state["overlay"].face != state["face"]:
                    state["overlay"] = load_overlay(state["face"], state)
            if state.get("overlay"):
                warped = state["overlay"].warp_lwir_to_vis(to_u8(lw.astype(np.float32)), vis.shape)
                vis = cv2.addWeighted(vis, 0.5, cv2.applyColorMap(warped, cv2.COLORMAP_INFERNO), 0.5, 0)
            loop += 1
            f = depth_src.latest() if depth_src else None
            depth_mm = f.raw.astype(np.float32) * f.scale_mm if f is not None else None
            if loop % 3 == 1:  # 마커·물체 검출은 몇 프레임마다
                mk_info, markers = marker.check(vis, state["specimen"])
                if bg is not None or depth_mm is not None:  # 배경이 없으면 깊이 거리 범위로만 찾는다
                    dets = objects.detect_all(bg, vis, lw, depth_mm)
                    sizes = {"lwir": (LWIR_W, LWIR_H), "depth": (f.raw.shape[1], f.raw.shape[0]) if f is not None else (1, 1)}
                    obj = (dets, objects.associate(dets, cmap, sizes))
            raw_vis, raw_lw = vis, lw
            vis = marker.draw(vis, markers, mk_info.get("marker_expected"))
            left = cv2.resize(vis, (vis_w, VIEW_H), interpolation=cv2.INTER_AREA)
            right = cv2.resize(colorize_y16(lw), (round(LWIR_W * lw_scale), VIEW_H), interpolation=cv2.INTER_NEAREST)
            panels = [left, right]
            if depth_src:
                dp = live.depth_panel(f.raw, f.scale_mm) if f is not None else live.empty_panel("DEPTH: no frame")
                panels.append(cv2.resize(dp, (round(dp.shape[1] * VIEW_H / dp.shape[0]), VIEW_H)))
            if obj is not None:
                dets, assoc = obj
                live._draw_object(left, dets.get("rgb"), VIEW_H / raw_vis.shape[0], assoc["status"])
                info = assoc.get("cams", {})
                live._draw_object(right, dets.get("lwir"), lw_scale, info.get("lwir", {}).get("status", "-"),
                                  info.get("lwir", {}).get("predicted"))
                if depth_src and f is not None:
                    live._draw_object(panels[2], dets.get("depth"), VIEW_H / f.raw.shape[0],
                                      info.get("depth", {}).get("status", "-"), info.get("depth", {}).get("predicted"))
            view = np.hstack(panels)

            lines = [
                f"session {args.session} | specimen {state['specimen']} | face {state['face']}",
                f"RGB {fps_v[1]:.1f}fps  LWIR {fps_l[1]:.1f}fps  FPA {fpa}C  FFC {'manual' if rig.ffc_manual else 'auto'}",
            ]
            if state["mouse"]:
                mx, my = state["mouse"]
                if 0 <= mx < LWIR_W and 0 <= my < LWIR_H:
                    lines.append(f"raw({mx},{my}) = {int(lw[my, mx])}")
            if obj is not None:
                d, a = obj
                found = "/".join(f"{c}:{'O' if d[c].found else 'X'}" for c in d)
                lines.append(f"OBJECT {a['status']}  ({found})  map points {len((cmap or {}).get('points', []))}")
            if bg is None:
                lines.append("no background: RGB/thermal off (clear the scene and press g)")
            if mk_info.get("marker_ids"):
                ok = {True: "match", False: "MISMATCH", None: "unknown"}[mk_info["marker_match"]]
                lines.append(f"marker {mk_info['marker_ids']} vs {state['specimen']}: {ok}")
            if state["msg"]:
                lines.append(state["msg"])
            for i, t in enumerate(lines):
                y = 22 + 22 * i
                cv2.putText(view, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(view, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(WIN, view)

            k = cv2.waitKey(15) & 0xFF
            if k == ord("q"):
                break
            elif k == ord(" "):
                state["msg"] = "capturing..."
                out, meta = rig.capture_pair(args.session, state["specimen"], state["face"], note=args.note)
                state["msg"] = f"saved {out.name} ({meta['elapsed_ms']} ms)"
                print(state["msg"], "->", out)
            elif k in (ord("a"), ord("b")):
                state["face"] = chr(k).upper()
            elif k == ord("n"):
                state["specimen"] = bump_id(state["specimen"])
            elif k == ord("f"):
                rig.do_ffc()
                state["msg"] = "FFC done"
            elif k == ord("m"):
                rig.set_ffc_manual(not rig.ffc_manual)
                state["msg"] = f"FFC {'manual' if rig.ffc_manual else 'auto'}"
            elif k == ord("l"):
                s = rig.lock_vis()
                state["msg"] = f"RGB locked: exposure {s['EXPOSURE']}, WB {s['WB_TEMPERATURE']}"
            elif k in (ord("["), ord("]")):
                e = rig.vis_settings()["EXPOSURE"] + (-1 if k == ord("[") else 1)
                rig.set_vis_exposure(e)
                state["msg"] = f"RGB exposure {e}"
            elif k == ord("s"):
                rig.open_vis_dialog()
            elif k == ord("g"):
                objects.save_background(raw_vis, raw_lw, depth_mm)
                bg, obj = objects.load_background(), None
                state["msg"] = "background saved" + (" (with depth)" if depth_mm is not None else "")
            elif k == ord("j"):
                if obj is None:
                    state["msg"] = "save background first (g)"
                else:
                    cmap_new, msg = objects.add_map_point(obj[0])
                    cmap = objects.load_map()
                    state["msg"] = msg if cmap_new else "need the object found in every camera"
                    print(msg)
            elif k == ord("o"):
                state["overlay"] = None if state.get("overlay") else load_overlay(state["face"], state)
    finally:
        rig.close()
        if depth_src:
            depth_src.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
