import unittest
import hack_qut
from control import Controller


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.original = hack_qut.controller
        hack_qut.controller = Controller()
        self.client = hack_qut.app.test_client()
    def tearDown(self):
        hack_qut.controller = self.original
    def test_default_disabled_and_contract(self):
        state = self.client.get('/api/state').get_json()
        self.assertFalse(state['motion_enabled'])
        self.assertEqual(state['units'],'m')
        self.assertEqual(state['coordinate_frame'],'robot_base')
    def test_monitor_page_served(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'canvas',response.get_data())
        response.close()
    def test_enable_requires_fresh_hand_then_stop(self):
        self.assertFalse(self.client.post('/api/enable').get_json()['ok'])
        c = hack_qut.controller
        c.update((.5,.5),1,c.clock())
        self.assertTrue(self.client.post('/api/enable').get_json()['ok'])
        self.assertFalse(self.client.post('/api/stop').get_json()['motion_enabled'])
