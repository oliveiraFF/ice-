import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import app


class DesktopExitTests(unittest.TestCase):
    def exercise(self, callback):
        with tempfile.TemporaryDirectory() as folder:
            server = app.create_server(0, folder, on_exit=callback)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = 'http://127.0.0.1:' + str(server.server_address[1])
            try:
                with urlopen(origin + '/api/state?mode=live') as response:
                    state = json.load(response)
                outcomes = []
                for confirmation in (False, True):
                    req = Request(origin + '/api/desktop/exit', json.dumps({'confirm': confirmation}).encode(),
                        {'Origin': origin, 'X-Radar-Token': state['token'], 'Content-Type': 'application/json'})
                    try:
                        response = urlopen(req)
                    except HTTPError as exc:
                        response = exc
                    with response:
                        outcomes.append(response.status)
                return state, outcomes
            finally:
                server.shutdown()
                server.server_close()
                worker.join(3)

    def test_desktop_exit_requires_confirmation_and_calls_window_hook_once(self):
        callback = Mock()
        state, statuses = self.exercise(callback)
        self.assertTrue(state['desktop_exit_enabled'])
        self.assertEqual(statuses, [400, 200])
        callback.assert_called_once_with()

    def test_browser_server_has_no_exit_hook(self):
        state, statuses = self.exercise(None)
        self.assertFalse(state['desktop_exit_enabled'])
        self.assertEqual(statuses, [404, 404])
