"""Current-Windows-user encryption and owner API lifecycle; synthetic keys only."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from client_credentials import CredentialVault


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI required')
class OwnerCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name)
        self.key = 'synthetic-owner-credential-not-valid-for-network'
        self.server = None
        self.addCleanup(self.stop)
        self.start()

    def start(self):
        with patch.dict(os.environ, {'TIKHUB_API_KEY': ''}):
            self.server = app.create_server(0, self.data)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.token = self.request('/api/state?mode=live')['token']

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.worker.join(3)
            self.server = None

    def request(self, path, body=None):
        req = Request(self.origin + path, None if body is None else json.dumps(body).encode(),
            {'Origin': self.origin, 'X-Radar-Token': getattr(self, 'token', ''), 'Content-Type': 'application/json'})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            payload = json.load(response)
            if response.status >= 400:
                raise ValueError(payload['error'])
            return payload

    def test_save_restart_and_forget_never_calls_tikhub(self):
        with patch.object(app, 'tikhub_json', side_effect=AssertionError('unexpected paid request')):
            saved = self.request('/api/connect', {'key': self.key})
            self.assertTrue(saved['remembered'])
            vault = CredentialVault(self.data / 'owner-tikhub')
            self.assertTrue(vault.path.exists())
            self.assertNotIn(self.key.encode(), vault.path.read_bytes())
            self.stop()
            self.start()
            state = self.request('/api/state?mode=live')
            self.assertTrue(state['connected'])
            self.assertTrue(state['credential_remembered'])
            self.assertNotIn(self.key, json.dumps(state))
            self.assertFalse(state['access']['enabled'])
            cleared = self.request('/api/connect', {'key': ''})
            self.assertFalse(cleared['remembered'])
            self.stop()
            self.start()
            self.assertFalse(self.request('/api/state?mode=live')['connected'])
            self.assertFalse(vault.path.exists())

    def test_corrupt_vault_does_not_block_startup_or_echo_content(self):
        self.stop()
        vault = CredentialVault(self.data / 'owner-tikhub')
        vault.path.parent.mkdir()
        vault.path.write_bytes(b'corrupt synthetic content')
        self.start()
        state = self.request('/api/state?mode=live')
        self.assertFalse(state['connected'])
        self.assertIn('重新', state['credential_error'])
        self.assertNotIn('corrupt synthetic content', json.dumps(state))
        self.request('/api/connect', {'key': self.key})
        self.assertEqual(self.request('/api/state?mode=live')['credential_error'], '')

    def test_vault_failure_cannot_report_success_or_replace_in_memory_key(self):
        with patch.object(CredentialVault, 'save', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(ValueError):
                self.request('/api/connect', {'key': self.key})
        self.assertFalse(self.request('/api/state?mode=live')['connected'])
