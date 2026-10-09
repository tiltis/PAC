"""면별 평면 정합: 열화상(Y16, 320x256) 좌표 ↔ RGB 좌표.

로봇이 포장을 정해진 자세로 멈추므로 검사면마다 평면 호모그래피 1개로 충분하다.
정합 타깃: 무광 검은 판에 알루미늄 테이프 사각형을 격자로 붙인 것(template 명령으로 도안 출력).
알루미늄은 방사율이 낮아 열화상에서 검은 판과 구분되고, RGB에서는 밝게 보인다.

렌즈 왜곡 보정값(intrinsics_<cam>.json)이 있으면 점을 먼저 왜곡 보정한 뒤 호모그래피를 구한다.
"""
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

CALIB_DIR = Path(__file__).parent / "calib"
PATTERN = (7, 5)        # 가로 7개 x 세로 5개
SPACING_MM = 35.0       # 사각형 중심 간격
SQUARE_MM = 18.0        # 사각형 한 변


# --- 촬영 불러오기 ------------------------------------------------------------
def load_capture(cap_dir):
    cap_dir = Path(cap_dir)
    vis = cv2.imread(str(cap_dir / "vis.png"))
    if vis is None:
        raise FileNotFoundError(cap_dir / "vis.png")
    lwir = np.load(cap_dir / "lwir_y16.npz")["stack"].astype(np.float32).mean(axis=0)
    return vis, lwir


def to_u8(a, lo_pct=1, hi_pct=99):
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    return (np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)


# --- 격자 검출 ----------------------------------------------------------------
def _blob_detector(img_area):
    p = cv2.SimpleBlobDetector_Params()
    p.filterByColor, p.blobColor = True, 0      # 어두운 덩어리. 밝은 경우는 영상을 반전해 다시 찾는다
    p.filterByArea, p.minArea, p.maxArea = True, 12, img_area * 0.03
    p.filterByCircularity, p.minCircularity = True, 0.55   # 사각형도 통과(정사각형 원형도 약 0.785)
    p.filterByConvexity, p.minConvexity = True, 0.8
    p.filterByInertia, p.minInertiaRatio = True, 0.3
    p.minThreshold, p.maxThreshold, p.thresholdStep = 10, 240, 10
    p.minDistBetweenBlobs = 3
    return cv2.SimpleBlobDetector_create(p)


def detect_grid(gray, pattern=PATTERN):
    """대칭 격자 중심점(cols*rows, 2)을 찾는다. 밝기 극성은 자동으로 시도한다. 실패하면 None."""
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    det = _blob_detector(gray.shape[0] * gray.shape[1])
    for img in (gray, 255 - gray):
        for flags in (cv2.CALIB_CB_SYMMETRIC_GRID, cv2.CALIB_CB_SYMMETRIC_GRID | cv2.CALIB_CB_CLUSTERING):
            ok, centers = cv2.findCirclesGrid(img, pattern, flags=flags, blobDetector=det)
            if ok:
                return centers.reshape(-1, 2).astype(np.float64)
    return None


def detect_capture(vis, lwir, pattern=PATTERN):
    pv = detect_grid(cv2.cvtColor(vis, cv2.COLOR_BGR2GRAY), pattern)
    pl = detect_grid(to_u8(lwir), pattern)
    return pv, pl


def object_points(pattern=PATTERN, spacing=SPACING_MM):
    cols, rows = pattern
    return np.array([[c * spacing, r * spacing, 0.0] for r in range(rows) for c in range(cols)], np.float32)


# --- 렌즈 왜곡 ----------------------------------------------------------------
def load_intrinsics(cam):
    p = CALIB_DIR / f"intrinsics_{cam}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return np.array(d["K"]), np.array(d["dist"])


def undistort_pts(pts, intr):
    if intr is None:
        return pts
    K, dist = intr
    return cv2.undistortPoints(pts.reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2)


def distort_pts(pts, intr):
    """undistort_pts의 역변환(보정된 픽셀 → 원래 영상 픽셀)."""
    if intr is None:
        return pts
    K, dist = intr
    norm = cv2.undistortPoints(pts.reshape(-1, 1, 2), K, None).reshape(-1, 2)  # K만 풀어 정규좌표로
    obj = np.hstack([norm, np.ones((len(norm), 1))]).astype(np.float64)
    out, _ = cv2.projectPoints(obj, np.zeros(3), np.zeros(3), K, dist)
    return out.reshape(-1, 2)


def apply_h(H, pts):
    return cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), H).reshape(-1, 2)


# --- 호모그래피와 검증 ---------------------------------------------------------
def _keeps_axes(H, pl):
    """열화상의 오른쪽·아래 방향이 RGB에서도 오른쪽·아래로 가는지."""
    c = pl.mean(axis=0)
    p = apply_h(H, np.array([c, c + [10, 0], c + [0, 10]]))
    return p[1, 0] - p[0, 0] > 0 and p[2, 1] - p[0, 1] > 0


def fit_homography(pl, pv):
    """열화상 점 → RGB 점.

    대칭 격자는 180° 돌려도 같은 모양이라 두 순서 모두 오차 없이 맞는다. 그래서 오차가 아니라
    "두 카메라 모두 똑바로 서 있다(서로 뒤집히거나 돌지 않음)"는 조건으로 순서를 고른다.
    """
    cands = []
    for name, src in (("as_is", pl), ("rot180", pl[::-1].copy())):
        H, _ = cv2.findHomography(src, pv, 0)
        if H is not None and _keeps_axes(H, src):
            cands.append((np.linalg.norm(apply_h(H, src) - pv, axis=1).mean(), H, src, name))
    if not cands:
        raise RuntimeError("두 카메라 방향이 맞는 호모그래피가 없음. 카메라가 뒤집혀 달려 있지 않은지 확인")
    _, H, src, name = min(cands, key=lambda c: c[0])
    return H, src, name


def evaluate(H, pl, pv, pattern=PATTERN, spacing=SPACING_MM):
    """열화상 픽셀 단위 오차. 하나씩 빼고 맞춘 뒤 뺀 점을 예측하는 방식(LOO)을 함께 본다."""
    Hinv = np.linalg.inv(H)
    fit_err = np.linalg.norm(apply_h(Hinv, pv) - pl, axis=1)
    loo = []
    for i in range(len(pl)):
        keep = np.arange(len(pl)) != i
        Hi, _ = cv2.findHomography(pl[keep], pv[keep], 0)
        loo.append(np.linalg.norm(apply_h(np.linalg.inv(Hi), pv[i:i + 1])[0] - pl[i]))
    loo = np.array(loo)
    cols, rows = pattern
    grid = np.arange(cols * rows).reshape(rows, cols)
    edge = np.zeros(cols * rows, bool)
    edge[np.r_[grid[0], grid[-1], grid[:, 0], grid[:, -1]]] = True
    # 격자 간격으로 열화상 1px이 몇 mm인지 환산
    g = pl.reshape(rows, cols, 2)
    step_px = np.median(np.r_[np.linalg.norm(np.diff(g, axis=1), axis=2).ravel(),
                              np.linalg.norm(np.diff(g, axis=0), axis=2).ravel()])
    mm_per_px = spacing / step_px
    r = lambda x: round(float(x), 3)
    return {
        "n_points": int(len(pl)),
        "fit_rms_lwir_px": r(np.sqrt((fit_err ** 2).mean())),
        "loo_mean_lwir_px": r(loo.mean()),
        "loo_max_lwir_px": r(loo.max()),
        "loo_center_mean_lwir_px": r(loo[~edge].mean()) if (~edge).any() else None,
        "loo_edge_mean_lwir_px": r(loo[edge].mean()),
        "lwir_mm_per_px": r(mm_per_px),
        "loo_mean_mm": r(loo.mean() * mm_per_px),
        "loo_max_mm": r(loo.max() * mm_per_px),
    }


# --- 저장·사용 ----------------------------------------------------------------
@dataclass
class Registration:
    face: str
    H: np.ndarray                 # 왜곡 보정된 열화상 좌표 → 왜곡 보정된 RGB 좌표
    lwir_intr: tuple | None
    vis_intr: tuple | None
    meta: dict
    cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, face):
        d = json.loads((CALIB_DIR / f"H_face{face}.json").read_text(encoding="utf-8"))
        return cls(face, np.array(d["H_lwir_to_vis"]), load_intrinsics("lwir"), load_intrinsics("vis"), d)

    def save(self):
        CALIB_DIR.mkdir(exist_ok=True)
        d = dict(self.meta, face=self.face, H_lwir_to_vis=self.H.tolist(),
                 lwir_undistorted=self.lwir_intr is not None, vis_undistorted=self.vis_intr is not None)
        p = CALIB_DIR / f"H_face{self.face}.json"
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def lwir_to_vis(self, pts):
        pts = np.asarray(pts, np.float64).reshape(-1, 2)
        return distort_pts(apply_h(self.H, undistort_pts(pts, self.lwir_intr)), self.vis_intr)

    def vis_to_lwir(self, pts):
        """RGB에서 정한 검사 영역(다각형 꼭짓점)을 열화상 픽셀 좌표로 옮긴다."""
        pts = np.asarray(pts, np.float64).reshape(-1, 2)
        return distort_pts(apply_h(np.linalg.inv(self.H), undistort_pts(pts, self.vis_intr)), self.lwir_intr)

    def warp_lwir_to_vis(self, lwir_img, vis_shape):
        """확인용 겹쳐 보기. 왜곡 보정값이 있으면 먼저 보정한다(분석은 원래 Y16 좌표에서 한다)."""
        img = lwir_img
        if self.lwir_intr is not None:
            img = cv2.undistort(img, *self.lwir_intr)
        h, w = vis_shape[:2]
        out = cv2.warpPerspective(img, self.H, (w, h))
        if self.vis_intr is not None:  # 원래 RGB 픽셀마다 보정 좌표를 구해 그 위치에서 샘플링
            m = self.cache.get(("vis_map", h, w))
            if m is None:  # 실시간 겹쳐 보기에서 매 프레임 다시 계산하지 않게 한 번만 만든다
                K, dist = self.vis_intr
                ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
                und = cv2.undistortPoints(np.stack([xs.ravel(), ys.ravel()], 1).reshape(-1, 1, 2), K, dist, P=K)
                m = self.cache[("vis_map", h, w)] = und.reshape(h, w, 2).astype(np.float32)
            out = cv2.remap(out, m[..., 0], m[..., 1], cv2.INTER_LINEAR)
        return out


def new_registration(face, pl, pv, source):
    """돌려주는 두 번째 값은 pv와 같은 순서로 맞춘 원래(왜곡 보정 전) 열화상 점이다."""
    lwir_intr, vis_intr = load_intrinsics("lwir"), load_intrinsics("vis")
    plu, pvu = undistort_pts(pl, lwir_intr), undistort_pts(pv, vis_intr)
    H, src, order = fit_homography(plu, pvu)
    stats = evaluate(H, src, pvu)
    meta = {
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "source_capture": str(source),
        "pattern": list(PATTERN), "spacing_mm": SPACING_MM,
        "grid_order": order,
        "stats": stats,
    }
    return Registration(face, H, lwir_intr, vis_intr, meta), (pl if order == "as_is" else pl[::-1]), stats
