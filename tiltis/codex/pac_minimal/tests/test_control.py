import math
import unittest
from control import Controller


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.
        self.c = Controller(lambda: self.now)
        self.c.update((.5,.5),1,self.now)
        self.assertTrue(self.c.enable())

    def test_mapping_and_speed(self):
        self.now += .04
        self.c.update((.9,.1),1,self.now)
        p = self.c.state()['position_m']
        self.assertGreater(p[0],.3)
        self.assertLess(p[1],0)
        self.assertEqual(p[2],.2)
        self.assertLessEqual(math.dist(p,[.3,0,.2]),.05*.04+1e-12)

    def test_two_hands_latch(self):
        self.c.update((.5,.5),2,self.now)
        self.now += .03
        self.c.update((.5,.5),1,self.now)
        self.assertFalse(self.c.state()['motion_enabled'])
        self.assertTrue(self.c.enable())

    def test_missing(self):
        self.c.update(None,0,self.now)
        self.assertFalse(self.c.enable())

    def test_hand_stop_reason_survives_stale_api_poll(self):
        self.c.update(None,0,self.now)
        self.now += .3
        state = self.c.state()
        self.assertEqual(state['reason'], 'single_hand_required')
        self.assertFalse(state['input_valid'])
        self.assertFalse(state['motion_enabled'])
        self.c.update((.5,.5),1,self.now)
        self.assertEqual(self.c.state()['reason'], 'single_hand_required')
        self.assertTrue(self.c.enable())
        self.assertEqual(self.c.state()['reason'], 'enabled')

    def test_camera_stop_reason_survives_stale_api_poll(self):
        self.c.stop('camera_stopped')
        self.now += .3
        self.assertEqual(self.c.state()['reason'], 'camera_stopped')

    def test_area(self):
        self.c.update((.99,.5),1,self.now)
        self.assertFalse(self.c.state()['motion_enabled'])

    def test_stale_without_camera_updates(self):
        self.now += .201
        self.assertFalse(self.c.state()['motion_enabled'])
        self.c.update((.5,.5),1,self.now)
        self.assertFalse(self.c.state()['motion_enabled'])

    def test_processing_delay(self):
        self.c.update((.5,.5),1,self.now-.3)
        self.assertFalse(self.c.state()['motion_enabled'])

    def test_nonfinite(self):
        self.c.update((float('nan'),.5),1,self.now)
        self.assertFalse(self.c.state()['motion_enabled'])

    def test_clock_regression_requires_manual_reactivation(self):
        self.c.update((.5,.5),1,self.now-.01)
        self.assertFalse(self.c.state()['motion_enabled'])
        self.now += .03
        self.c.update((.5,.5),1,self.now)
        self.assertFalse(self.c.state()['motion_enabled'])
        self.assertTrue(self.c.enable())

    def test_equal_windows_clock_tick_has_zero_motion_budget(self):
        previous = list(self.c.position)
        self.c.update((.9,.1),1,self.now)
        self.assertTrue(self.c.state()['motion_enabled'])
        self.assertEqual(self.c.position,previous)


if __name__ == '__main__':
    unittest.main()
