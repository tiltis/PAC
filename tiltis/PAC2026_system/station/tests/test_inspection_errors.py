import sqlite3
from store import Store
from sequencer import Sequencer
from robot import MockRobot
from test_sequencer import FakeSensor

def test_inspection_errors_roundtrip_and_old_database_rows_remain(tmp_path):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE inspections (run_id INTEGER, face TEXT, attempt INTEGER, status TEXT, verdict TEXT,reasons TEXT,features TEXT,capture_id TEXT,images TEXT,elapsed_ms INTEGER)')
        c.execute("INSERT INTO inspections VALUES (77,'A',0,'error',NULL,'[]','{}','old','{}',1)")
    store=Store(path)
    old=store.get_inspections(77)[0]
    assert old['capture_id']=='old' and old['error'] is None and old['persistence_error'] is None
    class Sensor(FakeSensor):
        def inspect(self,*args):
            r=super().inspect(*args);r.update(status='error',error='raw write failed',persistence_error='inspect record failed');return r
    result=Sequencer(MockRobot(speed=0),Sensor()).run('S01','t')
    row=store.get_inspections(store.save_run(result))[0]
    assert row['error']=='raw write failed' and row['persistence_error']=='inspect record failed'
    assert Store(path).get_inspections(77)[0]==old
