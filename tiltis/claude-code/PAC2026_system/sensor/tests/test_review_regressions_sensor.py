import json
import time
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from depth import OrbbecDepthSource
from test_depth import SDKFrame
from test_sensor_evidence import sensor_app, FakeDepth

@pytest.mark.parametrize('policy',['timing_policy.json','depth_policy_faceA.json','roi_faceA.json'])
def test_post_capture_policy_error_keeps_artifacts_and_request(tmp_path,monkeypatch,policy):
    calib=tmp_path/'calib';calib.mkdir();(calib/policy).write_text('{broken')
    monkeypatch.setattr(server,'CALIB_DIR',calib)
    with TestClient(sensor_app(tmp_path/'captures')) as client:
        result=client.post('/inspect',json={'session':'t','specimen_id':'S01','face':'A','trigger_id':'NEW'}).json()
        if policy.startswith('depth_'): assert result['status']=='ok';return
        assert result['status']=='error' and result['capture_id'] and result['trigger_id']=='NEW'
        assert client.get(result['artifacts']['rgb']).status_code==200
        saved=client.get('/captures/t/'+result['capture_id']+'/inspect.json').json()
        assert saved['status']=='error' and saved['trigger_id']=='NEW'

def test_disabled_depth_ignores_remaining_validated_policy(tmp_path,monkeypatch):
    calib=tmp_path/'calib';calib.mkdir()
    (calib/'depth_policy_faceA.json').write_text(json.dumps({'validated':True}))
    monkeypatch.setattr(server,'CALIB_DIR',calib)
    with TestClient(sensor_app(tmp_path/'captures')) as client:
        result=client.post('/inspect',json={'specimen_id':'S01','face':'A'}).json()
    assert result['verdict']=='review' and result['sensor_data']['depth']['status']=='disabled'

def test_device_clock_reset_recovers_after_quarantine():
    source=OrbbecDepthSource(timeout_s=.05);source._last_device_timestamp_ms=10000
    stamps=iter([100,200,300,400])
    class Pipeline:
        def wait_for_frames(self,timeout):
            stamp=next(stamps)
            if stamp==400:source._stop.set()
            return SimpleNamespace(get_depth_frame=lambda:SDKFrame(timestamp=stamp))
    source._pipeline=Pipeline();source._receive()
    assert source._frame is not None and source._frame.device_timestamp_ms==400
    assert source._frame.device_clock_epoch==1

def test_repeated_timestamp_never_recovers_and_request_has_deadline():
    source=OrbbecDepthSource(timeout_s=.02);source._last_device_timestamp_ms=10000
    stamps=iter([100,100,100,100])
    class Pipeline:
        calls=0
        def wait_for_frames(self,timeout):
            self.calls+=1
            if self.calls==4:source._stop.set()
            return SimpleNamespace(get_depth_frame=lambda:SDKFrame(timestamp=next(stamps)))
    source._pipeline=Pipeline();source._receive()
    assert source._frame is None
    before=time.monotonic()
    with pytest.raises((RuntimeError,TimeoutError)):source.next_after(time.time())
    assert time.monotonic()-before<.2

def test_enabled_depth_policy_failure_preserves_raw_capture(tmp_path,monkeypatch):
    calib=tmp_path/'calib';calib.mkdir();(calib/'depth_policy_faceA.json').write_text('{broken')
    monkeypatch.setattr(server,'CALIB_DIR',calib)
    with TestClient(sensor_app(tmp_path/'captures',FakeDepth())) as client:
        result=client.post('/inspect',json={'specimen_id':'S01','face':'A','trigger_id':'NEW'}).json()
        assert result['status']=='error' and result['capture_id']
        assert client.get(result['artifacts']['depth_raw']).content[:2]==b'PK'
        meta=client.get(result['artifacts']['metadata']).json()
        assert meta['trigger_id']=='NEW' and meta['attempt']==0
        assert meta['depth']['scale_mm_per_unit']==.1
