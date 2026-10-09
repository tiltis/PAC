"""Synthetic registered RGB/depth is geometry validation, not camera calibration."""
import copy
import sys
from pathlib import Path
import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sam_depth import locate_sam_top, project_sam_mask, SamDepthSensorAdapter

INTR = dict(fx=600., fy=600., cx=160., cy=120., width=320, height=240)


def scene(angle=30, shift=(0, 0)):
    # Rectified overhead camera: table Z=600mm; box top Z=540mm.
    mask = np.zeros((240, 320), 'uint8')
    center = (160 + shift[0], 100 + shift[1])
    quad = np.rint(cv2.boxPoints((center, (80/540*600, 50/540*600), angle))).astype(int)
    cv2.fillConvexPoly(mask, quad, 1)
    mm = np.full(mask.shape, 600.)
    mm[mask > 0] = 540.
    reg = dict(validated=True, source_id='SYNTHETIC ONLY', units='mm',
               from_frame='depth_camera_mm', to_frame='rgb_camera_mm',
               rgb_rectified=True, depth_rectified=True, rms_px=0.,
               R=np.eye(3).tolist(), t_mm=[0,0,0], rgb_intrinsics=INTR, depth_intrinsics=INTR,
               rgb_camera_id='mock-rgb', depth_camera_id='mock-depth')
    caps = {k: dict(camera_id=f'mock-{k}', capture_time_verified=True,
                    clock='host_unix_seconds', captured_at_s=99.9) for k in ('rgb', 'depth')}
    return mask.astype(bool), mm, reg, caps


def locate(data, **overrides):
    mask, mm, reg, caps = data
    options = dict(box_count=1, table_roi=[0,180,320,240], box_models_mm=[[80,50,60]])
    options.update(overrides)
    return locate_sam_top(mask, mm, INTR, INTR, reg, caps, 100., **options)


@pytest.mark.parametrize('angle,shift', [(0,(0,0)), (30,(25,10)), (-40,(-20,0)), (80,(0,10))])
def test_moved_rotated_box_top_center_axes_and_size_are_recomputed(angle, shift):
    result, mask = locate(scene(angle, shift))
    assert result['found'], result
    assert result['mode'] == 'sam_depth_top' and result['frame'] == 'depth_camera_mm'
    assert result['top_size_mm'] == pytest.approx([80,50], abs=4)
    assert result['top_center_cam_mm'] == pytest.approx([shift[0]*.9, (-20+shift[1])*.9,540], abs=2)
    assert result['top_height_mm'] == pytest.approx(60, abs=.1)
    expected = np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle)),0])
    assert abs(np.dot(result['long_axis_cam'], expected)) > .998
    assert result['top_normal_cam'] == pytest.approx([0,0,-1], abs=1e-5)
    assert mask.any() and not result['motion_enabled'] and not result['robot_ready']


@pytest.mark.parametrize('bad', ['unvalidated','units','camera','clock','stale','skew','intrinsics','rotation','residual','rectified'])
def test_unverified_registration_or_capture_never_produces_a_grasp(bad):
    data = list(scene())
    data[2], data[3] = copy.deepcopy(data[2]), copy.deepcopy(data[3])
    reg, caps = data[2:]
    if bad == 'unvalidated': reg['validated'] = False
    elif bad == 'units': reg['units'] = 'm'
    elif bad == 'camera': caps['rgb']['camera_id'] = 'other'
    elif bad == 'clock': caps['rgb']['capture_time_verified'] = False
    elif bad == 'stale': caps['depth']['captured_at_s'] = 90.
    elif bad == 'skew': caps['depth']['captured_at_s'] = 99.5
    elif bad == 'intrinsics': reg['rgb_intrinsics']['fx'] = 700.
    elif bad == 'rotation': reg['R'][0][0] = 2.
    elif bad == 'residual': reg['rms_px'] = 4.
    elif bad == 'rectified': reg['rgb_rectified'] = False
    result, mask = locate(data)
    assert not result['found'] and not mask.any() and result['motion_enabled'] is False


def test_partial_tape_mask_cannot_supply_full_box_center_or_rotation():
    data = list(scene(0))
    data[0][110:] = False
    result, _ = locate(data)
    assert not result['found']


def test_two_rgb_boxes_or_unmeasured_box_dimensions_are_refused():
    assert not locate(scene(), box_count=2)[0]['found']
    assert not locate(scene(), box_models_mm=[])[0]['found']
    assert not locate(scene(), box_models_mm=[[80,50,60],[82,52,62]])[0]['found']


def test_transform_is_used_instead_of_same_pixel_lookup():
    mask, mm, reg, _ = scene(0)
    # +18mm RGB X translation gives +20px at box top depth 540mm.
    shifted = np.zeros_like(mask)
    shifted[:,20:] = mask[:,:-20]
    reg['t_mm'] = [18.,0,0]
    mapped = project_sam_mask(shifted, mm, INTR, INTR, reg)
    assert np.all(mapped[mask])
    assert not np.array_equal(mapped, shifted)


def test_sam_association_excludes_other_depth_objects_but_preserves_table_fit():
    data = list(scene(0))
    data[1][45:95,240:300] = 520.  # separate object outside the one RGB SAM mask
    result, top = locate(data)
    assert result['found'] and result['candidate_count'] == 1, result
    assert result['table_d_mm'] == pytest.approx(600., abs=.1)
    assert not top[45:95,240:300].any()


def test_sloped_or_incomplete_top_is_refused():
    data = list(scene(0))
    y, x = np.where(data[0])
    data[1][y,x] += .5 * (x-160)
    assert locate(data)[0]['found'] is False


def test_projection_excludes_points_occluded_in_the_rgb_camera():
    _, _, reg, _ = scene()
    mm = np.full((20,20), 1000.)
    mm[:,:10] = 500.
    depth = dict(fx=1000.,fy=1000.,cx=10.,cy=10.,width=20,height=20)
    rgb = dict(depth, fx=.1, fy=.1)
    mask = np.zeros((20,20),bool)
    mask[10,10] = True
    reg['rgb_intrinsics'], reg['depth_intrinsics'] = rgb, depth
    mapped = project_sam_mask(mask, mm, depth, rgb, reg)
    assert mapped[:,:10].all() and not mapped[:,10:].any()


def test_adapter_rechecks_freshness_after_processing_and_reuses_inspection_api():
    mask, mm, reg, caps = scene()
    bundle = dict(sam_mask=mask,depth_mm=mm,depth_intrinsics=INTR,rgb_intrinsics=INTR,captures=caps,box_count=1)
    class Inspection:
        def inspect(self, *args, **kwargs): return ('existing',args,kwargs)
        def close(self): return 'closed'
    times = iter([100.,103.])
    adapter = SamDepthSensorAdapter(Inspection(),lambda:bundle,reg,[0,180,320,240],[[80,50,60]],lambda:next(times))
    assert adapter.locate()['found'] is False
    assert adapter.inspect('session')[0] == 'existing' and adapter.close() == 'closed'


def test_registered_sam_top_enters_existing_guard_and_ik_without_robot_io():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'vision_pick'))
    from bootstrap import station_path
    station_path()
    from guard import GuardedVisionPicker
    import grasp
    import kinematics as K
    mask, mm, reg, _ = scene(0)
    frames = iter([99.9,99.95,100.])
    def read_pair():
        stamp = next(frames)
        caps = {kind: dict(camera_id=f'mock-{kind}',capture_time_verified=True,
                           clock='host_unix_seconds',captured_at_s=stamp) for kind in ('rgb','depth')}
        return dict(sam_mask=mask,depth_mm=mm,depth_intrinsics=INTR,rgb_intrinsics=INTR,captures=caps,box_count=1)
    sensor = SamDepthSensorAdapter(None,read_pair,reg,[0,180,320,240],[[80,50,60]],lambda:100.1)
    he = dict(R=np.diag([1.,-1.,-1.]),t=np.array([.42,-.018,.6]),rms_mm=0.,n=6)
    cfg = dict(grasp.DEFAULTS,grasp_mode='side',workspace=dict(frame='base_link',units='m',
               min=[.30,-.10,.005],max=[.48,.10,.20]))  # SYNTHETIC, never an installation config
    picker = GuardedVisionPicker(sensor,he,cfg=cfg,joint_map={},clock=lambda:100.1)
    observation = picker.locate()
    result = picker.plan(observation)
    assert result['ok'] and result['hardware_motion_verified'] is False, result
    point = K.SO101().fk(K.from_lerobot(result['grasp']))[:3,3]
    assert point == pytest.approx([.42,0,.03], abs=.002)
    assert result['orientation_source'] == 'depth_camera_box_axes'
