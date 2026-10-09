"""Depth picking must honor the configured search area and reject ambiguity."""
import numpy as np
import pytest

import locate
from test_locate import H, INTR, W, render


@pytest.mark.parametrize("x,z", [(-150, 350), (130, 450), (0, 600)])
def test_box_at_different_table_positions(x, z):
    mm = render(cam_h=190, box=((x - 35, x + 35), (z - 35, z + 35)), box_h=90, tilt_deg=14)
    r = locate.public(locate.locate_box_front(mm, INTR, box_mm=(70, 70, 90), tab_height_mm=0,
                                              near_far=(200, 700), downsample=2))
    assert r["found"], r
    t = np.radians(14)
    R = np.array([[1, 0, 0], [0, np.cos(t), np.sin(t)], [0, -np.sin(t), np.cos(t)]])
    assert np.linalg.norm(np.asarray(r["top_center_cam_mm"]) - R.T @ [x, 100, z]) < 10
    assert r["search_roi_px"] == [0, 0, W, H]


def test_pick_roi_does_not_include_box_outside_horizontal_bounds():
    mm = render(box=((-80, 80), (300, 380)))
    # Previous mask included the full image above y0, ignoring x bounds.
    r = locate.locate_box(mm, INTR, pick_roi=[0, 400, 200, H])
    assert not r["found"], r


def test_multiple_matching_boxes_refused():
    a = render(box=((-180, -100), (310, 390)), box_h=45)
    b = render(box=((100, 180), (310, 390)), box_h=45)
    mm = np.minimum(a, b)
    r = locate.locate_box_front_any(mm, INTR, [(70, 70, 90), (80, 80, 45)], tab_height_mm=0,
                                    near_far=(200, 700), downsample=2)
    assert not r["found"] and r["reason"] == "multiple_boxes_in_pick_area", r


def test_two_different_specimens_refused():
    a = render(box=((-180, -110), (315, 385)), box_h=90)
    b = render(box=((100, 180), (310, 390)), box_h=45)
    r = locate.locate_box_front_any(np.minimum(a, b), INTR, [(70, 70, 90), (80, 80, 45)],
                                    tab_height_mm=0, near_far=(200, 700), downsample=2)
    assert not r["found"] and r["reason"] == "multiple_boxes_or_box_models", r


def test_invalid_roi_refused():
    with pytest.raises(ValueError, match="ROI"):
        locate.locate_box(render(), INTR, pick_roi=[-1, 0, W, H])


def test_camera_looking_straight_down_has_finite_plane_basis():
    intr = {"fx": 300, "fy": 300, "cx": 160, "cy": 120}
    mm = np.full((240, 320), 500.0)
    mm[105:155, 125:185] = 450
    r = locate.public(locate.locate_box(mm, intr, table_roi=[0, 170, 320, 240]))
    assert r["found"] and np.isfinite(r["top_center_cam_mm"]).all(), r


def render_rotated_box(x, z, yaw_deg):
    """Ray-cast a known square specimen rotated on the table, independent of locate."""
    v, u = np.mgrid[0:H:2, 0:W:2]
    d = np.stack([(u - INTR["cx"]) / INTR["fx"], (v - INTR["cy"]) / INTR["fy"], np.ones(v.shape)], -1)
    tilt, yaw = np.radians(14), np.radians(yaw_deg)
    Rcam = np.array([[1, 0, 0], [0, np.cos(tilt), np.sin(tilt)], [0, -np.sin(tilt), np.cos(tilt)]])
    Rbox = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
    dw = d @ Rcam.T
    dl = dw @ Rbox
    origin = -np.array([x, 0, z]) @ Rbox
    with np.errstate(divide="ignore", invalid="ignore"):
        table = 190 / dw[..., 1]
        best = np.where(table > 0, table, np.inf)
        t1, t2 = (np.array([-35, 100, -35]) - origin) / dl, (np.array([35, 190, 35]) - origin) / dl
        near = np.nanmax(np.minimum(t1, t2), axis=-1)
        far = np.nanmin(np.maximum(t1, t2), axis=-1)
        best = np.where((far >= near) & (near > 0) & (near < best), near, best)
    mm = np.where(np.isfinite(best) & (best < 3000), best, 0)
    intr = {name: value / 2 for name, value in INTR.items()}
    return mm, intr, Rcam.T @ [x, 100, z]


@pytest.mark.parametrize("x,z,yaw", [(-80, 400, -30), (70, 400, 30), (0, 500, 55)])
def test_rotated_box_center_follows_position(x, z, yaw):
    mm, intr, truth = render_rotated_box(x, z, yaw)
    r = locate.public(locate.locate_box_front(mm, intr, box_mm=(70, 70, 90), tab_height_mm=0, near_far=(200, 700)))
    assert r["found"], r
    assert np.linalg.norm(np.asarray(r["top_center_cam_mm"]) - truth) < 10, r
