"""A real local TCP API, synthetic wrist input, and the existing bridge/backend."""
import io
import json
import threading
import time
import unittest
import urllib.request
from werkzeug.serving import make_server, WSGIRequestHandler
import hack_qut
from control import Controller
from robot_bridge import Bridge, MockBackend


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


class HttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.previous = hack_qut.controller
        self.controller = hack_qut.controller = Controller()
        self.server = make_server('127.0.0.1',0,hack_qut.app,request_handler=QuietHandler)
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.backend = MockBackend()
        self.bridge = Bridge(self.backend,io.StringIO())

    def tearDown(self):
        self.bridge.stop('test_shutdown')
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        hack_qut.controller = self.previous

    def request(self, route, method='GET'):
        start = time.monotonic()
        request = urllib.request.Request(self.url+route,method=method)
        with urllib.request.urlopen(request,timeout=1) as response:
            return json.load(response),start

    def receive(self):
        state,start = self.request('/api/state')
        return self.bridge.receive(state,start)

    def test_http_to_mock_commands_then_stop_and_manual_rearm(self):
        self.controller.update((.5,.5),1,time.monotonic())
        reply,_ = self.request('/api/enable','POST')
        self.assertTrue(reply['ok'])
        self.assertTrue(self.receive(), self.bridge.reason)
        self.assertTrue(self.bridge.arm())
        for i in range(5):
            self.controller.update((.8,.2),1,time.monotonic())
            self.assertTrue(self.receive(), (i, self.bridge.reason, self.controller.state()))
            self.assertTrue(self.bridge.step())
        self.assertEqual(len(self.backend.actions),5)
        self.assertGreater(self.backend.position[0],.3)
        self.assertLess(self.backend.position[1],0.)
        self.request('/api/stop','POST')
        self.assertFalse(self.receive())
        self.assertEqual(self.backend.holds,1)
        self.controller.update((.5,.5),1,time.monotonic())
        self.request('/api/enable','POST')
        self.assertTrue(self.receive())
        self.assertFalse(self.bridge.step())
        self.assertTrue(self.bridge.arm())

    def test_no_more_responses_independent_watchdog_holds(self):
        self.controller.update((.5,.5),1,time.monotonic())
        self.request('/api/enable','POST')
        self.assertTrue(self.receive())
        self.assertTrue(self.bridge.arm())
        deadline = time.monotonic()+1
        while self.bridge.enabled and time.monotonic()<deadline:
            self.bridge.watchdog()
            time.sleep(.01)
        self.assertFalse(self.bridge.enabled)
        self.assertEqual(self.backend.holds,1)
