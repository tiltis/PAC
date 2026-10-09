import json
import httpx
import pytest
from robot import MockRobot
from sensor_client import SensorClient
from sequencer import Sequencer
from store import Store
from test_sequencer import FakeSensor
from test_sensor_association import client_with_handler

@pytest.mark.parametrize('abort', [False, True])
def test_decision_survives_failed_or_aborted_routing(tmp_path, abort):
    robot = MockRobot(speed=0, fail_on=set() if abort else {'bin_human'})
    holder = {}
    def event(e):
        if abort and e['step'] == 'decide': holder['seq'].request_abort()
    seq = holder['seq'] = Sequencer(robot, FakeSensor({('A',0):'suspect'}), on_event=event)
    result = seq.run('S01','t')
    assert result['final_verdict'] == 'suspect' and result['bin'] == 'human'
    assert result['decision_status'] == 'decided'
    assert result['routing_status'] == ('aborted' if abort else 'error')
    assert result['placed_bin'] is None
    store=Store(tmp_path/'runs.db'); store.save_run(result)
    saved=store.list_runs()[0]
    assert saved['bin']=='human' and saved['routing_status']==result['routing_status']

def test_timeout_keeps_generated_request_identity():
    client=SensorClient('http://synthetic'); client._http.close(); sent=[]
    def handler(req):
        sent.append(json.loads(req.content)); raise httpx.ReadTimeout('synthetic', request=req)
    client._http=httpx.Client(transport=httpx.MockTransport(handler))
    try: result=client.inspect('t','S01','A',0)
    finally: client.close()
    assert result['status']=='error' and result['trigger_id']==sent[0]['trigger_id']
    assert result['session']=='t'
    assert sent[0]['single_stationary_specimen'] is False

@pytest.mark.parametrize('schema',[None,'unexpected'])
def test_live_success_requires_association_schema(schema):
    def mutate(r):
        r['features']={'defect_inspected':True,'defect_rules_version':'test'}
        r['verdict']='no_anomaly'
        if schema is None: r.pop('sensor_data')
        else:r['sensor_data']['schema_version']=schema
    client=client_with_handler(mutate)
    try: assert client.inspect('t','S01','A',0)['status']=='error'
    finally:client.close()

def test_stationary_precondition_is_not_assumed():
    client=SensorClient('http://synthetic');client._http.close();sent=[]
    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(500)
    client._http=httpx.Client(transport=httpx.MockTransport(handler))
    try:client.inspect('t','S01','A',0)
    finally:client.close()
    assert sent[0]['single_stationary_specimen'] is False

def test_direct_live_sensor_cannot_bypass_client_schema_guard():
    robot=MockRobot(speed=0);robot.is_mock=False
    class Sensor(FakeSensor):
        def inspect(self,*args):
            result=super().inspect(*args);result['features'].pop('simulated');return result
    result=Sequencer(robot,Sensor()).run('S01','t')
    assert result['state']=='error' and result['bin'] is None

def test_home_failure_preserves_acknowledged_placement():
    class Robot(MockRobot):
        def move_to(self,pose,duration):
            if pose=='home' and 'bin_ok' in self.moves(): raise RuntimeError('home fail')
            super().move_to(pose,duration)
    result=Sequencer(Robot(speed=0),FakeSensor()).run('S01','t')
    assert result['state']=='error' and result['final_verdict']=='no_anomaly'
    assert result['placed_bin']=='ok' and result['routing_status']=='error'
