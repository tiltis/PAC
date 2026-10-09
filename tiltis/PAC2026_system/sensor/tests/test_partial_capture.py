import sys,json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rig,server

def mock_real_rig(tmp_path):
    obj=rig.Rig.__new__(rig.Rig)  # Never initialize/open cameras.
    obj.cfg=rig.RigConfig(data_root=tmp_path,lwir_frames=2)
    obj.boson=None;obj.boson_info={'part_number':'SYNTHETIC'};obj.ffc_manual=False
    obj.vis_index=obj.lwir_index=-1
    obj.vis=SimpleNamespace(next_after=lambda t:(np.full((100,100,3),90,np.uint8),t+.001,1),stop=lambda:None)
    obj.lwir=SimpleNamespace(next_after=lambda t:(np.full((256,320),22000,np.uint16),t+.001,1),stop=lambda:None)
    obj.vis_settings=lambda:{};obj.health=lambda:{'vis':True,'lwir':True}
    return obj

@pytest.mark.parametrize('failure',['png','npz','meta','request'])
def test_partial_save_keeps_capture_path_and_trigger(tmp_path,monkeypatch,failure):
    obj=mock_real_rig(tmp_path)
    if failure=='png':
        def partial_png(path,image):
            path.write_bytes(b'partial PNG')
            raise OSError('injected PNG failure')
        monkeypatch.setattr(rig,'save_png',partial_png)
    elif failure=='npz':monkeypatch.setattr(rig.np,'savez_compressed',lambda *args,**kw: (_ for _ in ()).throw(OSError('injected NPZ failure')))
    else:
        original=Path.write_text
        def fail(path,*args,**kwargs):
            if path.name==('capture_request.json' if failure=='request' else 'meta.json'):raise OSError('injected metadata failure')
            return original(path,*args,**kwargs)
        monkeypatch.setattr(Path,'write_text',fail)
    with TestClient(server.create_app(lambda:obj)) as client:
        result=client.post('/inspect',json={'session':'t','specimen_id':'S01','face':'A','attempt':1,'trigger_id':'T-FAIL'}).json()
        assert result['status']=='error' and result['trigger_id']=='T-FAIL' and result['capture_id']
        out=tmp_path/'t'/result['capture_id'];assert out.is_dir()
        if failure!='request':
            minimal=json.loads((out/'capture_request.json').read_text(encoding='utf-8'))
            assert minimal['trigger_id']=='T-FAIL' and minimal['attempt']==1
            assert client.get(result['artifacts']['request_metadata']).status_code==200
        saved=json.loads((out/'inspect.json').read_text(encoding='utf-8'))
        assert saved['capture_id']==out.name and saved['trigger_id']=='T-FAIL'
        if failure=='npz':assert client.get(result['artifacts']['rgb']).status_code==200
        if failure=='png':assert client.get(result['artifacts']['rgb']).content==b'partial PNG'
