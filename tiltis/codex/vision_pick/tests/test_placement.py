import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bootstrap import station_path
station_path()
from placement import bind_box, verify_release
from robot import MockRobot
from sequencer import Sequencer


CFG = {'source_id':'synthetic-test-only','validated':True,'frame':'base_link','units':'m',
       'normal_base':[0,0,1],'plane_d_m':0,'max_tilt_deg':10,'bottom_clearance_m':[0,.005],
       'zones_xy_m':{'ok':[[.1,-.1],[.3,.1]],'human':[[.1,.2],[.3,.4]]}}


@pytest.mark.parametrize('mode,reason',[('flat',None),('side','box_not_upright'),
    ('high','box_bottom_outside_release_height'),('outside','box_outside_measured_bin_area'),
    ('unmeasured','measured_placement_not_configured')])
def test_measured_release_rejects_side_drop_height_and_wrong_zone(mode,reason):
    held = bind_box(np.eye(4),[.2,0,.06],np.eye(3),[.08,.08,.06])
    T = np.eye(4)
    cfg = dict(CFG)
    if mode=='side': T[:3,:3] = [[1,0,0],[0,0,-1],[0,1,0]]
    if mode=='high': T[2,3]=.05
    if mode=='outside': T[1,3]=.2
    if mode=='unmeasured': cfg['validated']=False
    result=verify_release(held,T,cfg,'ok')
    assert result['ok'] == (reason is None) and result['reason']==reason
    if result['ok']: assert result['hardware_release_verified'] is False


@pytest.mark.parametrize('permit',[True,False])
def test_sequence_checks_release_before_open_and_stops_holding_on_failure(permit):
    class Picker:
        dry_run=False
        def locate(self): return {'found':True}
        def plan(self,loc): return dict(ok=True,approach={},grasp={},lift={})
        def capture_held_box(self,loc,joints):
            assert ('gripper','closed') in robot.calls
            return {'ok':True}
        def verify_at_release(self,bin_name,joints):
            assert robot.moves()[-1]=='bin_ok'
            return {'ok':permit,'reason':None if permit else 'box_not_upright'}
    class Sensor:
        def inspect(self,session,specimen_id,face,attempt):
            return {'specimen_id':specimen_id,'face':face,'attempt':attempt,'status':'ok','verdict':'no_anomaly','features':{'defect_inspected':True,
                   'defect_rules_version':'mock','simulated':True},'reasons':[],'images':{}}
    robot=MockRobot(speed=0)
    result=Sequencer(robot,Sensor(),picker=Picker(),settle_timeout_s=.1).run('test','test')
    assert result['state']==('done' if permit else 'error'),result
    assert robot.calls.count(('gripper','open'))==(2 if permit else 1)
    if not permit:
        assert robot.stopped and result['placed_bin'] is None and 'box_not_upright' in result['error']
