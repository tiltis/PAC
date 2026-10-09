import io
import json
import math
import threading
import unittest
from robot_bridge import Bridge, MockBackend
from workspace import Workspace


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.
        self.backend = MockBackend()
        self.log = io.StringIO()
        self.b = Bridge(self.backend,self.log,lambda:self.now)
        self.state = dict(position_m=[.4,-.1,.2], motion_enabled=True,
                          frame_age_s=0.,frame_id=1,coordinate_frame='robot_base',units='m',
                          workspace=Workspace().metadata())
        self.assertTrue(self.b.receive(self.state,self.now))
        self.assertTrue(self.b.arm())

    def test_command_rate_and_log(self):
        self.now += .04
        self.assertTrue(self.b.step())
        self.assertLessEqual(math.dist(self.backend.position,[.3,0,.2]),.002+1e-12)
        row = json.loads(self.log.getvalue().splitlines()[-1])
        self.assertIn('observation',row)
        self.assertIn('action_sent',row)
        self.assertTrue(row['mock'])

    def test_false_holds_and_latches(self):
        self.assertFalse(self.b.receive(dict(self.state,motion_enabled=False),self.now))
        self.assertEqual(self.backend.holds,1)
        self.b.receive(dict(self.state,frame_id=2),self.now)
        self.assertFalse(self.b.step())
        self.assertTrue(self.b.arm())

    def test_watchdog_without_http(self):
        self.now += .201
        self.b.watchdog()
        self.assertFalse(self.b.enabled)
        self.assertEqual(self.backend.holds,1)

    def test_duplicate_responses_do_not_refresh(self):
        self.now += .15
        self.b.receive(self.state,self.now)
        self.now += .06
        self.b.receive(self.state,self.now)
        self.assertFalse(self.b.enabled)

    def test_http_roundtrip_added_to_source_age(self):
        self.now += .21
        self.assertFalse(self.b.receive(dict(self.state,frame_id=2),self.now-.21))

    def test_nonfinite_and_workspace(self):
        for p in ([float('nan'),0,.2],[.5,0,.2],[.3,0,.3]):
            self.assertFalse(self.b.receive(dict(self.state,position_m=p),self.now))
        self.assertEqual(self.backend.actions,[])

    def test_validation_failure(self):
        self.backend.validate = lambda *args: False
        self.now += .03
        self.assertFalse(self.b.step())
        self.assertEqual(self.backend.actions,[])
        self.assertEqual(self.backend.holds,1)

    def test_watchdog_during_ik_discards_result(self):
        entered, release = threading.Event(), threading.Event()
        def solve(position, reference, observation):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('test timeout')
            return dict(position_m=position)
        self.backend.solve = solve
        self.now += .03
        worker = threading.Thread(target=self.b.step)
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            self.now += .201
            self.b.watchdog()
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.backend.actions,[])
        self.assertEqual(self.backend.holds,1)

    def test_source_restart_requires_rearm(self):
        self.assertFalse(self.b.receive(dict(self.state,frame_id=0),self.now))
        self.assertFalse(self.b.enabled)

    def test_hold_failure_is_reported(self):
        def fail():
            raise RuntimeError('bus disconnected')
        self.backend.hold = fail
        self.b.stop('receive_failure')
        self.assertEqual(self.b.reason,'hold_failed')
        self.assertIn('hold_failed',self.log.getvalue())

    def test_robot_observation_failure_stops_inside_bridge(self):
        def fail():
            raise RuntimeError('encoder read failed')
        self.backend.observe = fail
        self.now += .03
        self.assertFalse(self.b.step())
        self.assertFalse(self.b.enabled)
        self.assertEqual(self.backend.holds,1)

    def test_slow_initial_observation_cannot_arm(self):
        self.b.stop('manual_stop')
        original = self.backend.observe
        def slow():
            self.now += .21
            return original()
        self.backend.observe = slow
        self.assertFalse(self.b.arm())
        self.assertFalse(self.b.enabled)

    def test_input_units_and_workspace_mismatch_hold(self):
        self.assertFalse(self.b.receive(dict(self.state,units='mm'),self.now))
        self.assertEqual(self.backend.holds,1)
        self.assertFalse(self.b.receive(dict(self.state,workspace={}),self.now))

    def test_hardware_refuses_virtual_workspace(self):
        self.backend.is_mock = False
        with self.assertRaisesRegex(ValueError,'commissioned'):
            Bridge(self.backend)

    def test_arm_does_not_reset_reference_while_active(self):
        reference = self.b.reference
        self.assertFalse(self.b.arm())
        self.assertIs(self.b.reference,reference)

    def test_watchdog_during_slow_collision_check_discards_action(self):
        entered,release = threading.Event(),threading.Event()
        def validate(*args):
            entered.set()
            return release.wait(2)
        self.backend.validate = validate
        self.now += .03
        worker = threading.Thread(target=self.b.step)
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            self.now += .201
            self.b.watchdog()
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.backend.actions,[])
        self.assertEqual(self.backend.holds,1)


if __name__ == '__main__':
    unittest.main()
