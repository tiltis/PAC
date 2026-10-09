import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coolant_lab import read_stack, validate_rois, load_peer


def test_thermal_rois_reject_overlap_and_outside_pixels():
    validate_rois([[0, 0, 10, 10], [10, 0, 20, 10]], (256, 320))
    for rois in ([[0, 0, 10, 10], [9, 0, 20, 10]],
                 [[0, 0, 10, 10], [10, 0, 321, 10]],
                 [[0, 0, 10, 10], [10.5, 0, 20, 10]]):
        with pytest.raises(ValueError):
            validate_rois(rois, (256, 320))


def test_saved_raw_stack_requires_real_sensor_provenance(tmp_path):
    np.savez(tmp_path / 'lwir_y16.npz', stack=np.ones((8, 20, 30), np.uint16))
    meta = tmp_path / 'meta.json'
    for sensor_data in ({}, {'simulated': True}):
        meta.write_text(json.dumps({'sensor_data': sensor_data}))
        with pytest.raises(ValueError):
            read_stack(tmp_path)
    meta.write_text(json.dumps({'sensor_data': {'simulated': False}, 'face': 'B'}))
    stack, result = read_stack(tmp_path)
    assert stack.shape == (8, 20, 30) and result['face'] == 'B'
    np.savez(tmp_path / 'lwir_y16.npz', stack=np.ones((20, 30), np.uint16))
    with pytest.raises(ValueError):
        read_stack(tmp_path)


def test_lab_cannot_use_running_system_directory(tmp_path):
    with pytest.raises(ValueError, match='outside'):
        load_peer(tmp_path, tmp_path / 'sensor' / 'calib')


def test_cli_measures_cold_surface_using_peer_rule_without_changing_peer_config(tmp_path):
    import subprocess
    script = Path(__file__).resolve().parents[1] / 'coolant_lab.py'
    system = script.parents[2] / 'claude-code' / 'PAC2026_system'
    production = system / 'sensor/calib/rules.json'
    before = production.read_bytes() if production.exists() else None
    capture = tmp_path / 'synthetic_fixture'
    capture.mkdir()
    stack = np.full((8, 20, 30), 21000, np.uint16)
    stack[:, :10, :10] = 20900
    np.savez(capture / 'lwir_y16.npz', stack=stack)
    (capture / 'meta.json').write_text(json.dumps({'face': 'B', 'sensor_data': {
        'simulated': False, 'assessment': {'capture_quality_ok': True}}}))
    base = [sys.executable, str(script), '--system-dir', str(system),
            '--workspace', str(tmp_path / 'lab')]
    subprocess.run(base + ['roi', '--capture', str(capture), '--rois', '0,0,10,10;10,0,20,10'], check=True, capture_output=True)
    result = subprocess.run(base + ['measure', '--captures', str(capture), '--label', 'present'], check=True, capture_output=True)
    report = json.loads(result.stdout)
    assert report['samples'][0]['delta_counts'] == -100
    assert report['samples'][0]['frame_delta_range'] == [-100, -100]
    assert report['deployment_ready'] is False
    draft = json.loads((tmp_path / 'lab/coolant_draft.json').read_text())
    assert draft['validated'] is False and draft['coolant']['delta_max_counts'] is None
    assert (production.read_bytes() if production.exists() else None) == before
