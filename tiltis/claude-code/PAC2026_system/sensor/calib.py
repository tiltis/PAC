"""정합 타깃 도안 출력, 격자 검출, 면별 호모그래피 계산·검증, 렌즈 왜곡 보정.

    python calib.py template                                  # 도안(A4 가로) → calib/target_template.png/.pdf
    python calib.py detect --capture <촬영폴더>                 # 두 카메라에서 격자가 잡히는지만 확인
    python calib.py homography --capture <촬영폴더> --face A    # 면 A 정합 계산·저장
    python calib.py check --capture <다른 촬영폴더> --face A     # 저장된 정합을 다른 촬영으로 검증
    python calib.py intrinsics --session <세션폴더> --cam lwir   # 여러 자세 촬영(8장 이상)으로 왜곡 보정값 계산
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import registration as reg

sys.stdout.reconfigure(encoding="utf-8")


def cmd_template(args):
    dpi = 300
    mm = dpi / 25.4
    W, H = round(297 * mm), round(210 * mm)
    img = np.zeros((H, W), np.uint8)  # 검은 바탕: 알루미늄 사각형을 붙일 자리만 흰 선으로 표시
    cols, rows = reg.PATTERN
    gw, gh = (cols - 1) * reg.SPACING_MM, (rows - 1) * reg.SPACING_MM
    x0, y0 = (297 - gw) / 2, (210 - gh) / 2
    half = reg.SQUARE_MM / 2
    for r in range(rows):
        for c in range(cols):
            cx, cy = x0 + c * reg.SPACING_MM, y0 + r * reg.SPACING_MM
            p1 = (round((cx - half) * mm), round((cy - half) * mm))
            p2 = (round((cx + half) * mm), round((cy + half) * mm))
            cv2.rectangle(img, p1, p2, 255, 3)
            cv2.circle(img, (round(cx * mm), round(cy * mm)), 4, 255, -1)
    # 인쇄 배율 확인용 100mm 막대
    bx, by = round(15 * mm), round(200 * mm)
    cv2.line(img, (bx, by), (bx + round(100 * mm), by), 255, 4)
    cv2.putText(img, "100 mm (print at 100%, check with a ruler)", (bx, by - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 3)
    cv2.putText(img, f"{cols}x{rows} squares, {reg.SQUARE_MM:.0f} mm, pitch {reg.SPACING_MM:.0f} mm - cover each with aluminum tape",
                (bx, round(10 * mm)), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 3)
    reg.CALIB_DIR.mkdir(exist_ok=True)
    png = reg.CALIB_DIR / "target_template.png"
    cv2.imwrite(str(png), img)
    print("saved", png)
    try:
        from PIL import Image
        pdf = reg.CALIB_DIR / "target_template.pdf"
        Image.fromarray(img).convert("RGB").save(pdf, resolution=dpi)
        print("saved", pdf, "(PDF는 실제 크기 그대로 인쇄된다)")
    except ImportError:
        print("Pillow가 없어 PDF는 만들지 않음. PNG를 300dpi 실제 크기로 인쇄할 것")


def draw_points(img, pts, color=(0, 255, 0), scale=1.0):
    out = img.copy()
    for i, (x, y) in enumerate(pts):
        p = (round(x), round(y))
        cv2.circle(out, p, max(2, round(4 * scale)), color, -1)
        cv2.putText(out, str(i), (p[0] + 4, p[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4 * scale, color, max(1, round(scale)))
    return out


def debug_image(vis, lwir, pv, pl, registration=None):
    """왼쪽: RGB 검출점, 가운데: 열화상 검출점, 오른쪽: 정합 겹쳐 보기."""
    h = 480
    sv = h / vis.shape[0]
    left = cv2.resize(draw_points(vis, pv, scale=2.5) if pv is not None else vis, None, fx=sv, fy=sv)
    lw = cv2.applyColorMap(reg.to_u8(lwir), cv2.COLORMAP_INFERNO)
    lw = cv2.resize(lw, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    if pl is not None:
        lw = draw_points(lw, pl * 3, (0, 255, 0), scale=1.2)
    mid = cv2.resize(lw, (round(lw.shape[1] * h / lw.shape[0]), h))
    panels = [left, mid]
    if registration is not None:
        warped = registration.warp_lwir_to_vis(reg.to_u8(lwir), vis.shape)
        color = cv2.applyColorMap(warped, cv2.COLORMAP_INFERNO)
        blend = cv2.addWeighted(vis, 0.5, color, 0.5, 0)
        if pv is not None:
            blend = draw_points(blend, pv, (0, 255, 0), scale=2.5)
            if pl is not None:
                proj = registration.lwir_to_vis(pl)
                for (x, y) in proj:
                    cv2.drawMarker(blend, (round(x), round(y)), (255, 255, 0), cv2.MARKER_CROSS, 30, 3)
        panels.append(cv2.resize(blend, None, fx=sv, fy=sv))
    return np.hstack(panels)


def detect_or_report(cap_dir):
    vis, lwir = reg.load_capture(cap_dir)
    pv, pl = reg.detect_capture(vis, lwir)
    n = reg.PATTERN[0] * reg.PATTERN[1]
    print(f"RGB 격자: {'찾음' if pv is not None else '못 찾음'}, 열화상 격자: {'찾음' if pl is not None else '못 찾음'} (점 {n}개 기준)")
    return vis, lwir, pv, pl


def cmd_detect(args):
    vis, lwir, pv, pl = detect_or_report(args.capture)
    out = Path(args.capture) / "calib_detect.png"
    cv2.imwrite(str(out), debug_image(vis, lwir, pv, pl))
    print("saved", out)
    if pv is None or pl is None:
        print("못 찾았을 때: 타깃 전체가 두 화면에 다 들어오는지, 열화상에서 사각형이 보이는지 확인."
              " 열화상 대비가 약하면 판을 드라이어로 30초 데우거나 따뜻한 곳에 두었다가 다시 촬영.")
        sys.exit(1)


def cmd_homography(args):
    vis, lwir, pv, pl = detect_or_report(args.capture)
    if pv is None or pl is None:
        sys.exit(1)
    r, pl_matched, stats = reg.new_registration(args.face, pl, pv, args.capture)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    path = r.save()
    dbg = reg.CALIB_DIR / f"debug_face{args.face}.png"
    cv2.imwrite(str(dbg), debug_image(vis, lwir, pv, pl_matched, r))
    print("saved", path, dbg)
    if stats["loo_max_lwir_px"] > 3:
        print("주의: 최대 오차가 열화상 3px를 넘음. 가장자리 오차가 크면 intrinsics로 렌즈 왜곡 보정 후 다시 계산")


def cmd_check(args):
    r = reg.Registration.load(args.face)
    vis, lwir, pv, pl = detect_or_report(args.capture)
    if pv is None or pl is None:
        sys.exit(1)
    pvu = reg.undistort_pts(pv, r.vis_intr)
    best = None
    for src in (pl, pl[::-1].copy()):
        plu = reg.undistort_pts(src, r.lwir_intr)
        err = np.linalg.norm(reg.apply_h(np.linalg.inv(r.H), pvu) - plu, axis=1)
        if best is None or err.mean() < best[1].mean():
            best = (src, err)
    src, err = best
    mm_per_px = r.meta["stats"]["lwir_mm_per_px"]
    print(f"저장된 면 {args.face} 정합을 새 촬영에 적용: 평균 {err.mean():.2f}px, 최대 {err.max():.2f}px (열화상), "
          f"약 {err.mean() * mm_per_px:.1f} / {err.max() * mm_per_px:.1f} mm")
    out = Path(args.capture) / f"calib_check_face{args.face}.png"
    cv2.imwrite(str(out), debug_image(vis, lwir, pv, src, r))
    print("saved", out)


def cmd_intrinsics(args):
    caps = sorted(p for p in Path(args.session).iterdir() if (p / "meta.json").exists())
    objp = reg.object_points()
    obj, img, used, size = [], [], [], None
    for c in caps:
        vis, lwir = reg.load_capture(c)
        gray = reg.to_u8(lwir) if args.cam == "lwir" else cv2.cvtColor(vis, cv2.COLOR_BGR2GRAY)
        pts = reg.detect_grid(gray)
        if pts is None:
            print("격자 없음:", c.name)
            continue
        size = gray.shape[::-1]
        obj.append(objp)
        img.append(pts.astype(np.float32).reshape(-1, 1, 2))
        used.append(c.name)
    if len(obj) < 8:
        print(f"격자가 잡힌 촬영이 {len(obj)}개뿐. 판의 위치·기울기를 바꿔 8장 이상 촬영할 것")
        sys.exit(1)
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(obj, img, size, None, None)
    per_view = []
    for o, i, rv, tv in zip(obj, img, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, rv, tv, K, dist)
        per_view.append(float(np.sqrt(((proj - i) ** 2).sum(axis=2).mean())))
    d = {
        "cam": args.cam, "created": dt.datetime.now().isoformat(timespec="seconds"),
        "image_size": list(size), "rms_px": round(rms, 4),
        "K": K.tolist(), "dist": dist.ravel().tolist(),
        "views": dict(zip(used, [round(v, 3) for v in per_view])),
    }
    reg.CALIB_DIR.mkdir(exist_ok=True)
    p = reg.CALIB_DIR / f"intrinsics_{args.cam}.json"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    fx = K[0, 0]
    print(f"RMS {rms:.3f}px, fx {fx:.1f}, cx {K[0, 2]:.1f}, cy {K[1, 2]:.1f}, dist {np.round(dist.ravel(), 4).tolist()}")
    if args.cam == "lwir":
        print("참고: Boson 320 50° 렌즈의 fx는 약 343px가 정상 범위. 크게 다르면 촬영을 다시 할 것")
    print("saved", p, "→ 이후 homography를 다시 계산해야 반영된다")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template")
    for name in ("detect", "homography", "check"):
        s = sub.add_parser(name)
        s.add_argument("--capture", required=True)
        if name != "detect":
            s.add_argument("--face", required=True, choices=["A", "B"])
    s = sub.add_parser("intrinsics")
    s.add_argument("--session", required=True)
    s.add_argument("--cam", required=True, choices=["lwir", "vis"])
    args = ap.parse_args()
    {"template": cmd_template, "detect": cmd_detect, "homography": cmd_homography,
     "check": cmd_check, "intrinsics": cmd_intrinsics}[args.cmd](args)


if __name__ == "__main__":
    main()
