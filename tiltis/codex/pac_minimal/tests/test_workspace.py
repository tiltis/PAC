import json
import tempfile
import unittest
from pathlib import Path
from control import Controller
from robot_bridge import Bridge, MockBackend
from workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def test_corner_directions_and_metres(self):
        w = Workspace()
        for wrist, expected in [((.1,.1),[.4,.1,.2]), ((.9,.9),[.2,-.1,.2])]:
            for actual, value in zip(w.map_wrist(*wrist),expected):
                self.assertAlmostEqual(actual,value)

    def test_custom_workspace_used_in_whole_pipeline(self):
        w = Workspace(x=(.12,.18),y=(-.03,.03),z=.15,target_speed_m_s=.01,
                      profile='commissioned')
        now = [1.]
        c = Controller(lambda:now[0],workspace=w)
        backend = MockBackend(w)
        b = Bridge(backend,clock=lambda:now[0],workspace=w)
        c.update((.5,.5),1,now[0])
        self.assertTrue(c.enable())
        self.assertTrue(b.receive(c.state(),now[0]))
        self.assertTrue(b.arm())
        now[0] += .04
        c.update((.1,.1),1,now[0])
        self.assertTrue(b.receive(c.state(),now[0]))
        self.assertTrue(b.step())
        self.assertTrue(w.contains(backend.position))
        self.assertEqual(backend.position[2],.15)

    def test_unconfigured_site_template_cannot_load(self):
        template = Path(__file__).resolve().parents[1]/'workspace.site.template.json'
        with self.assertRaises(ValueError):
            Workspace.load(template)

    def test_invalid_speed_or_bounds(self):
        for kwargs in ({'target_speed_m_s':.1},{'x':(.4,.2)},{'z':float('nan')}):
            with self.assertRaises(ValueError):
                Workspace(**kwargs)

    def test_mm_workspace_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.json'
            path.write_text(json.dumps({'units':'mm','coordinate_frame':'robot_base'}))
            with self.assertRaisesRegex(ValueError,'metre'):
                Workspace.load(path)
