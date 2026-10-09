"""깊이로 책상 위 상자 위치·자세 찾기 (로봇 집기용).

1) 깊이 픽셀 → 3D(깊이 카메라 좌표, mm): 내부 파라미터(fx, fy, cx, cy)
2) 집기 영역(pick_roi)에서 가장 큰 평면 = 책상 (RANSAC 후 최소제곱)
3) 책상 위 12~300mm 높이의 가장 큰 덩어리 = 상자
4) 상자 윗면(최고 높이 ±6mm) 점의 최소 외접 사각형 → 윗면 중심, 긴 변·짧은 변 방향과 길이

결과는 깊이 카메라 좌표다. 로봇 좌표로는 hand-eye 보정(station/handeye.py)으로 바꾼다.
윗면 먼 가장자리 너머가 무효 깊이(가림)이면 짧은 변 길이는 하한값일 수 있다(far_edge_invalid_frac로 알림).
"""
from __future__ import annotations

import cv2
import numpy as np


def deproject(mm, intr):
    H, W = mm.shape
    v, u = np.mgrid[0:H, 0:W]
    Z = mm.astype(np.float64)
    return np.stack([(u - intr["cx"]) * Z / intr["fx"], (v - intr["cy"]) * Z / intr["fy"], Z], -1)


def fit_plane(pts, rng, iters=300, tol=6.0):
    best_n, best = 0, None
    for _ in range(iters):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(b - a, c - a)
        nn = np.linalg.norm(n)
        if nn < 1e-6:
            continue
        n /= nn
        k = int((np.abs(pts @ n - n @ a) < tol).sum())
        if k > best_n:
            best_n, best = k, (n, -n @ a)
    n, d = best
    inl = pts[np.abs(pts @ n + d) < tol]
    c0 = inl.mean(0)
    n = np.linalg.svd(inl - c0, full_matrices=False)[2][2]  # full U(N×N)를 만들면 2만 점에서 3GB·17초(10-08 노트북 실측)
    if n @ c0 > 0:  # 책상 법선은 카메라 원점 쪽. 수직 하향 카메라(n.y≈0)에서도 부호가 안정적이다.
        n = -n
    return n, -n @ c0, len(inl)


def locate_box(mm, intr, pick_roi=None, near_far=(150, 1200), min_h=12, max_h=300, seed=0, downsample=1, jump_mm=25.0,
               min_short_mm=20.0, expected_h=None, height_tol_mm=15.0, table_roi=None, object_mask=None):
    """mm: 깊이(mm, 0 또는 nan=무효). pick_roi: 상자 탐색 픽셀 [x0, y0, x1, y1] (기본: 전체 화면).
    table_roi: 책상 평면을 맞출 영역(기본: 화면 아래쪽 45%). 탐색 영역과 별도로 지정한다.
    downsample: 2면 가로세로 절반(1280×800 → 640×400)으로 계산해 약 4배 빠르다(노트북 25~58초 → 수 초, 10-08).
    결과의 bbox_px는 원본 픽셀로 되돌려 준다.
    near_far: 이 거리(mm) 밖의 점은 무시. 상자 뒤 벽·가구가 화면에서 상자와 붙어 한 덩어리가 되는 것을 막으려면
    far를 상자 거리 + 20cm 정도로 좁힌다(10-08 실측: 벽 75cm가 상자 42cm와 합쳐져 거부됨).
    결과의 "_internal"(마스크·좌표 배열)은 locate_box_front가 쓴다. 밖으로 보낼 때는 public()으로 뺀다."""
    if object_mask is not None:
        object_mask = np.asarray(object_mask)
        if object_mask.dtype != np.bool_ or object_mask.shape != mm.shape or not object_mask.any():
            raise ValueError("object mask must be nonempty boolean in native depth pixels")
    mm = np.where(np.isfinite(mm), mm, 0).astype(np.float64)
    k = max(1, int(downsample))
    if k > 1:
        mm = mm[::k, ::k]
        if object_mask is not None:
            object_mask = object_mask[::k, ::k]
        intr = {"fx": intr["fx"] / k, "fy": intr["fy"] / k, "cx": intr["cx"] / k, "cy": intr["cy"] / k}
        if pick_roi:
            pick_roi = [int(round(v / k)) for v in pick_roi]
        if table_roi:
            table_roi = [int(round(v / k)) for v in table_roi]
    px = 1.0 / (k * k)  # 픽셀 수 기준값을 해상도에 맞게 줄인다
    H, W = mm.shape
    P = deproject(mm, intr)
    valid = (mm > near_far[0]) & (mm < near_far[1])
    def roi_mask(bounds):
        x0, y0, x1, y1 = bounds
        if not (0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H):
            raise ValueError("depth ROI must be inside the image")
        mask = np.zeros_like(valid)
        mask[y0:y1, x0:x1] = True
        return mask
    search_bounds = pick_roi or [0, 0, W, H]
    table_bounds = table_roi or [0, int(H * 0.55), W, H]
    roi = roi_mask(search_bounds)
    region = valid & roi_mask(table_bounds)
    if region.sum() < 500 * px:
        return {"found": False, "reason": "pick_area_has_no_depth"}
    rng = np.random.default_rng(seed)
    pts = P[region]
    sub = pts[rng.choice(len(pts), min(20000, len(pts)), replace=False)]
    n, d, n_in = fit_plane(sub, rng)
    h = P @ n + d
    box = valid & roi & (h > min_h) & (h < max_h)
    if object_mask is not None:
        box &= object_mask  # SAM association restricts objects, never the table plane fit.
    if jump_mm:  # 이웃 픽셀과 깊이가 크게 다른 경계를 끊어, 화면에서 붙어 보이는 뒤쪽 선반·벽과 상자가 한 덩어리로 묶이지 않게 한다
        gx = np.abs(np.diff(mm, axis=1, append=mm[:, -1:]))
        gy = np.abs(np.diff(mm, axis=0, append=mm[-1:, :]))
        box &= ~((gx > jump_mm) | (gy > jump_mm))
    ks = 7 if k == 1 else 5
    box = cv2.morphologyEx(box.astype(np.uint8), cv2.MORPH_OPEN, np.ones((ks, ks), np.uint8))
    ncomp, lab, st, _ = cv2.connectedComponentsWithStats(box, 8)  # k(축소 배수)를 덮어쓰지 않도록 이름 분리
    e1 = np.cross(n, [1.0, 0, 0] if abs(n[2]) > 0.95 else [0, 0, 1.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    rejected, accepted = [], []
    # 큰 덩어리부터 상자 모양 후보를 확인한다. 유효 후보가 여럿이면 임의로 집지 않는다.
    # 책상 옆 가구·벽처럼 가는 띠 모양은 걸러진다.
    for i in 1 + np.argsort(st[1:, cv2.CC_STAT_AREA])[::-1][:6]:
        if st[i, cv2.CC_STAT_AREA] < 800 * px:
            break
        m = lab == i
        # 윗면 = 최고 높이(97%) 근처 ±10mm. 비스듬히 볼수록 윗면 깊이가 퍼지므로(10-06 실측 14°에서 49~61mm)
        # 띠를 너무 좁히면 먼 쪽이 잘린다. 높이는 띠 안 중앙값으로 보고한다(97%는 높게 치우침).
        top = m & (np.abs(h - float(np.percentile(h[m], 97))) < 10)
        top_h = float(np.median(h[top]))
        tp = P[top]
        q2 = np.stack([tp @ e1, tp @ e2], 1).astype(np.float32)
        (cx2, cy2), (w2, h2), ang = cv2.minAreaRect(q2)
        L, S = max(w2, h2), min(w2, h2)
        fill = (cv2.contourArea(cv2.convexHull(q2)) if len(q2) >= 3 else 0.0) / max(L * S, 1e-6)
        box_px = [int(st[i, 0]) * k, int(st[i, 1]) * k, int(st[i, 0] + st[i, 2]) * k, int(st[i, 1] + st[i, 3]) * k]
        # expected_h(앞면 모델): 높이가 기대 상자와 맞는 덩어리만 고르고, 그때는 윗면 짧은 변 하한을 두지 않는다.
        # 카메라를 낮게 세워 두면(책상 위 19cm, 9cm 상자) 윗면이 얇은 띠(약 16mm)로만 보이기 때문(10-08 실측).
        # 뒤 선반 모서리 같은 띠는 높이가 안 맞아 걸러진다. expected_h가 없으면(top 모드) 짧은 변 ≥ min_short_mm 유지
        if expected_h is not None:
            shape_ok = abs(top_h - expected_h) <= height_tol_mm and L <= 400 and fill >= 0.6
        else:
            shape_ok = min_short_mm <= S and L <= 400 and fill >= 0.6
        if shape_ok:
            accepted.append((i, top_h, top, cx2, cy2, w2, h2, ang, fill, box_px))
        else:
            rejected.append({"bbox_px": box_px, "top_size_mm": [round(float(L), 1), round(float(S), 1)], "fill": round(float(fill), 2),
                             "top_height_mm": round(float(top_h), 1)})
    if not accepted:
        return {"found": False, "reason": "no_box_shaped_object", "rejected": rejected, "table_normal_cam": n.round(4).tolist()}
    if len(accepted) > 1:
        return {"found": False, "reason": "multiple_boxes_in_pick_area", "candidate_count": len(accepted),
                "candidate_bboxes_px": [a[-1] for a in accepted]}
    i, top_h, top, cx2, cy2, w2, h2, ang, fill, box_px = accepted[0]
    L, S = max(w2, h2), min(w2, h2)
    a = np.radians(ang)
    d1 = np.cos(a) * e1 + np.sin(a) * e2  # 사각형 첫 변 방향(평면 위)
    d2 = np.cross(n, d1)
    long_axis, short_axis = (d1, d2) if w2 >= h2 else (d2, d1)
    # 윗면 중심: 평면 좌표의 사각형 중심을 3D로 되돌리고, 윗면 높이에 놓는다
    base = -d * n  # 평면 위 원점에 가장 가까운 점
    center = base + (cx2 - base @ e1) * e1 + (cy2 - base @ e2) * e2
    center = center - (center @ n + d) * n + top_h * n
    ys, xs = np.where(top)
    far_row = ys.min()
    band = mm[max(0, far_row - 25):far_row, xs.min():xs.max() + 1]
    return {
        "found": True, "frame": "depth_camera_mm",
        "candidate_count": 1,
        "search_roi_px": [int(v) * k for v in search_bounds],
        "table_roi_px": [int(v) * k for v in table_bounds],
        "top_center_cam_mm": center.round(1).tolist(),
        "top_height_mm": round(top_h, 1),
        "top_size_mm": [round(float(L), 1), round(float(S), 1)],
        "long_axis_cam": long_axis.round(4).tolist(), "short_axis_cam": short_axis.round(4).tolist(),
        "table_normal_cam": n.round(4).tolist(), "table_d_mm": round(float(d), 2), "table_inliers": int(n_in),
        "bbox_px": box_px,
        "top_points": int(top.sum()), "top_fill": round(float(fill), 2), "rejected": rejected,
        "far_edge_invalid_frac": round(float((band <= 0).mean()), 2) if band.size else None,
        "_internal": {"mask": lab == i, "P": P, "h": h, "n": n, "d": d, "e1": e1, "e2": e2, "px": px},
    }


def locate_box_front(mm, intr, box_mm=(160.0, 130.0, 50.0), tab_height_mm=20.0, pick_roi=None,
                     face_tol_mm=25.0, height_tol_mm=15.0, seed=0, near_far=(150, 1200), downsample=1, max_h=None, table_roi=None):
    """카메라가 세워져(거의 수평) 상자 윗면 안쪽이 잘 안 보일 때: 카메라를 향한 앞면으로 위치·방향을 잡고
    알고 있는 상자 크기로 윗면 중심·손잡이 위치를 계산한다(모델 기반).

    앞면 = 책상 위 상자 점 중 윗면보다 충분히 낮은 점(옆면). 책상 평면에 투영하면 앞 모서리 선이 된다.
    그 선의 길이로 어느 변이 카메라를 향하는지(160 또는 130) 고르고, 반대쪽 길이의 절반만큼 안쪽이 상자 중심이다.
    손잡이는 윗면 가운데에 긴 변 방향으로 붙어 있다고 가정한다.
    """
    L, W, Hbox = box_mm
    # 상자 높이보다 훨씬 높은 점(뒤쪽 선반·벽·사람)은 처음부터 제외한다. 상자 윗면 판정에 쓰는 97% 높이가 엉뚱한 곳에 잡히지 않게
    base = locate_box(mm, intr, pick_roi=pick_roi, table_roi=table_roi, near_far=near_far, seed=seed, downsample=downsample,
                      max_h=(Hbox + tab_height_mm + 2 * height_tol_mm) if max_h is None else max_h,
                      expected_h=Hbox, height_tol_mm=height_tol_mm)  # 윗면 97% 높이는 상자 윗면 기준(손잡이는 작아 영향 없음, 아래 검사와 동일)
    if not base.get("found"):
        return base
    it = base.pop("_internal")
    m, P, h, n, d, e1, e2 = it["mask"], it["P"], it["h"], it["n"], it["d"], it["e1"], it["e2"]
    top_h = base["top_height_mm"]
    if abs(top_h - Hbox) > height_tol_mm:
        return {"found": False, "reason": f"상자 높이 {top_h:.0f}mm가 설정 {Hbox:.0f}mm와 다름", "table_normal_cam": base["table_normal_cam"]}
    side = m & (h > 8) & (h < top_h - 12)
    if side.sum() < 300 * it.get("px", 1.0):
        return {"found": False, "reason": "front_face_not_visible", "table_normal_cam": base["table_normal_cam"]}
    q = np.stack([P[side] @ e1, P[side] @ e2], 1)
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(200):  # 평면 위 2D 점에서 앞 모서리 직선(RANSAC)
        a, b = q[rng.choice(len(q), 2, replace=False)]
        v = b - a
        nv = np.linalg.norm(v)
        if nv < 20:
            continue
        v /= nv
        dist = np.abs((q - a) @ np.array([-v[1], v[0]]))
        k = int((dist < 4).sum())
        if best is None or k > best[0]:
            best = (k, a, v)
    if best is None:
        return {"found": False, "reason": "front_edge_fit_failed", "table_normal_cam": base["table_normal_cam"]}
    _, a, v = best
    inl = q[np.abs((q - a) @ np.array([-v[1], v[0]])) < 4]
    t = (inl - a) @ v
    t0, t1 = np.percentile(t, [1, 99])
    face_len = float(t1 - t0)
    mid = a + v * (t0 + t1) / 2
    inward = np.array([-v[1], v[0]])
    if inward @ mid < 0:  # 카메라(평면 좌표 원점)에서 멀어지는 쪽이 상자 안쪽
        inward = -inward
    if abs(face_len - L) <= abs(face_len - W):
        facing, depth, long2 = L, W, v
    else:
        facing, depth, long2 = W, L, inward
    if abs(face_len - facing) > face_tol_mm:
        return {"found": False, "reason": f"앞면 길이 {face_len:.0f}mm가 상자 변({L:.0f}/{W:.0f})과 맞지 않음",
                "table_normal_cam": base["table_normal_cam"]}
    c2 = mid + inward * depth / 2
    on_plane = -d * n + c2[0] * e1 + c2[1] * e2
    long_axis = long2[0] * e1 + long2[1] * e2
    long_axis /= np.linalg.norm(long_axis)
    short_axis = np.cross(n, long_axis)
    box_top = on_plane + n * Hbox
    tab_top = box_top + n * tab_height_mm
    base.update({
        "mode": "front_face_model",
        "top_center_cam_mm": tab_top.round(1).tolist(),       # 손잡이 윗면 중심(계산값)
        "box_top_center_cam_mm": box_top.round(1).tolist(),
        "box_center_on_table_cam_mm": on_plane.round(1).tolist(),
        "front_face_len_mm": round(face_len, 1), "facing_side_mm": facing,
        "measured_top_size_mm": base["top_size_mm"], "top_size_mm": None,
        "long_axis_cam": long_axis.round(4).tolist(), "short_axis_cam": short_axis.round(4).tolist(),
        "front_points": int(len(inl)),
    })
    return base



def locate_box_front_any(mm, intr, boxes_mm, tab_height_mm=0.0, pick_roi=None, **kw):
    """상자 후보가 여럿일 때(예: 70×70×90 흰 상자, 80×80×45 갈색 상자): 측정한 높이와 앞면 길이에 맞는 후보를 고른다.
    모두 실패하면 후보별 이유를 함께 돌려준다. 결과에 "box_mm"으로 어느 후보였는지 적는다."""
    reasons, matches = [], []
    for box in boxes_mm:
        r = locate_box_front(mm, intr, box_mm=tuple(box), tab_height_mm=tab_height_mm, pick_roi=pick_roi, **kw)
        if r.get("found"):
            r["box_mm"] = [float(v) for v in box]
            matches.append(r)
            continue
        if r.get("reason") == "multiple_boxes_in_pick_area":
            return r
        reasons.append({"box_mm": list(box), "reason": r.get("reason")})
        if r.get("reason") == "pick_area_has_no_depth":
            break  # 깊이 자체가 없는 것이라 다른 크기를 시도해도 같다("no_box_shaped_object"는 기대 높이에 따라 달라지므로 계속)
    if len(matches) > 1:
        return {"found": False, "reason": "multiple_boxes_or_box_models", "candidate_count": len(matches)}
    if matches:
        return matches[0]
    out = {"found": False, "reason": "no_candidate_box_matched", "candidates": reasons}
    if isinstance(r, dict) and r.get("rejected") is not None:
        out["rejected"] = r["rejected"]  # 어떤 덩어리를 왜 걸렀는지(크기·채움 비율) 현장 진단용
    if reasons and isinstance(r, dict) and r.get("table_normal_cam") is not None:
        out["table_normal_cam"] = r["table_normal_cam"]
    return out


def locate_box_top_any(mm, intr, boxes_mm, pick_roi=None, near_far=(150, 1200), downsample=1, size_tol_mm=25.0, height_tol_mm=15.0, table_roi=None):
    """카메라가 위에서 내려다봐 윗면이 통째로 보일 때(10-09 현장): 후보 상자마다 높이로 덩어리를 고르고 윗면 크기(L×W ±size_tol)까지 맞으면 채택.
    결과에 box_mm, box_center_on_table_cam_mm(윗면 중심 - 법선×높이)를 넣어 옆집기 계획이 front 모드와 같은 키를 쓸 수 있게 한다."""
    reasons, last, matches = [], None, []
    for box in boxes_mm:
        L, W, Hbox = (float(v) for v in box)
        r = locate_box(mm, intr, pick_roi=pick_roi, table_roi=table_roi, near_far=near_far, downsample=downsample,
                       max_h=Hbox + 2 * height_tol_mm, expected_h=Hbox, height_tol_mm=height_tol_mm)
        last = r
        if r.get("reason") == "multiple_boxes_in_pick_area":
            return r
        if not r.get("found"):
            reasons.append({"box_mm": list(box), "reason": r.get("reason")})
            if r.get("reason") == "pick_area_has_no_depth":
                break
            continue
        a, b = r["top_size_mm"]
        ok = (abs(a - max(L, W)) <= size_tol_mm and abs(b - min(L, W)) <= size_tol_mm)
        if not ok:
            reasons.append({"box_mm": list(box), "reason": f"윗면 {a:.0f}x{b:.0f}mm가 상자 {L:.0f}x{W:.0f}와 맞지 않음"})
            continue
        r.pop("_internal", None)
        n = np.asarray(r["table_normal_cam"], float)
        top = np.asarray(r["top_center_cam_mm"], float)
        r["mode"] = "top_face"
        r["box_mm"] = [L, W, Hbox]
        r["box_top_center_cam_mm"] = top.round(1).tolist()
        r["box_center_on_table_cam_mm"] = (top - n * r["top_height_mm"]).round(1).tolist()
        matches.append(r)
    if len(matches) > 1:
        return {"found": False, "reason": "multiple_boxes_or_box_models", "candidate_count": len(matches)}
    if matches:
        return matches[0]
    out = {"found": False, "reason": "no_candidate_box_matched", "candidates": reasons}
    if isinstance(last, dict):
        if last.get("rejected") is not None:
            out["rejected"] = last["rejected"]
        if last.get("table_normal_cam") is not None:
            out["table_normal_cam"] = last["table_normal_cam"]
    return out


def public(result):
    return {k: v for k, v in result.items() if k != "_internal"}
