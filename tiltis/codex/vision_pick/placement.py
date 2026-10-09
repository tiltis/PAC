"""Expected held-box geometry at release; no robot or camera IO.

This uses measured joints and assumes the box has not slipped in the fingers.
It cannot prove that an actual release remains upright.
"""
from itertools import product

import numpy as np


def transform(value):
    T = np.asarray(value, float)
    if (T.shape != (4,4) or not np.isfinite(T).all() or
            not np.allclose(T[3], [0,0,0,1]) or
            not np.allclose(T[:3,:3].T @ T[:3,:3], np.eye(3), atol=1e-4) or
            not np.isclose(np.linalg.det(T[:3,:3]), 1)):
        raise ValueError('invalid measured tool transform')
    return T


def placement_config_error(cfg):
    try:
        if cfg.get('validated') is not True or not cfg.get('source_id') or cfg.get('frame') != 'base_link' or cfg.get('units') != 'm':
            return 'measured_placement_not_configured'
        normal = np.asarray(cfg['normal_base'],float)
        scalar = np.asarray([cfg['plane_d_m'],cfg['max_tilt_deg'],*cfg['bottom_clearance_m']],float)
        if normal.shape != (3,) or not np.isfinite(normal).all() or not np.isclose(np.linalg.norm(normal),1,atol=1e-4):
            return 'invalid_placement_plane'
        if scalar.shape != (4,) or not np.isfinite(scalar).all() or not 0 < scalar[1] < 45 or not 0 <= scalar[2] <= scalar[3]:
            return 'invalid_placement_limits'
        for name in ('ok','human'):
            zone = np.asarray(cfg['zones_xy_m'][name],float)
            if zone.shape != (2,2) or not np.isfinite(zone).all() or np.any(zone[0]>=zone[1]):
                return 'invalid_measured_bin_area'
    except (AttributeError,KeyError,ValueError,TypeError):
        return 'measured_placement_not_configured'
    return None


def bind_box(tool_T, top_center_m, axes_base, size_m):
    T = transform(tool_T)
    axes = np.asarray(axes_base,float)
    top = np.asarray(top_center_m,float)
    sizes = np.asarray(size_m,float)
    if (axes.shape != (3,3) or top.shape != (3,) or sizes.shape != (3,) or
            not np.isfinite(axes).all() or not np.isfinite(top).all() or not np.isfinite(sizes).all() or
            np.any(sizes<=0) or not np.allclose(axes.T@axes,np.eye(3),atol=.01)):
        raise ValueError('invalid observed box geometry')
    center = top - axes[:,2] * sizes[2]/2
    corners = np.array([center + axes @ (sizes * s / 2) for s in np.asarray(list(product((-1,1),repeat=3)))])
    return {'corners_tool_m': (corners-T[:3,3])@T[:3,:3],
            'up_tool': T[:3,:3].T@axes[:,2]}


def verify_release(held, tool_T, cfg, bin_name):
    error = placement_config_error(cfg)
    if error:
        return {'ok':False,'reason':error}
    try:
        T = transform(tool_T)
        corners = np.asarray(held['corners_tool_m'],float)
        up = np.asarray(held['up_tool'],float)
        if corners.shape != (8,3) or up.shape != (3,) or not np.isfinite(corners).all() or not np.isfinite(up).all() or not np.isclose(np.linalg.norm(up),1,atol=.01):
            raise ValueError('invalid held-box state')
        normal = np.asarray(cfg['normal_base'],float)
        tilt = float(np.degrees(np.arccos(np.clip(normal@(T[:3,:3]@up),-1,1))))
        world = corners@T[:3,:3].T + T[:3,3]
        bottom = float(np.min(world@normal+cfg['plane_d_m']))
        zone = np.asarray(cfg['zones_xy_m'][bin_name],float)
        lo,hi = cfg['bottom_clearance_m']
        reason = ('box_not_upright' if tilt>cfg['max_tilt_deg'] else
                  'box_bottom_outside_release_height' if not lo<=bottom<=hi else
                  'box_outside_measured_bin_area' if np.any(world[:,:2]<zone[0]) or np.any(world[:,:2]>zone[1]) else None)
        return {'ok':reason is None,'reason':reason,'expected_tilt_deg':round(tilt,2),
                'expected_bottom_clearance_m':round(bottom,4),'slip_verified':False,
                'hardware_release_verified':False}
    except (KeyError,ValueError,TypeError):
        return {'ok':False,'reason':'held_box_or_release_state_missing'}
