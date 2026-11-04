"""Local collection capability and pre-charge guards; no provider requests."""
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
from catalog import Catalog, can_collect


class CapturePickerTests(unittest.TestCase):
    def test_capability_means_adapter_exists_not_endpoint_verified(self):
        for platform in ('douyin', 'xiaohongshu'):
            self.assertTrue(can_collect({'platform': platform}))
            self.assertFalse(can_collect({'platform': platform, 'collection_supported': False}))
        for platform in ('tiktok', 'youtube', 'bilibili', 'tikhub'):
            self.assertFalse(can_collect({'platform': platform, 'collection_supported': True}))

    def test_catalog_state_and_detail_agree_for_all_platforms(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Catalog(Path(app.__file__).parent / 'catalog.json', Path(folder) / 'test.sqlite3')
            rows = catalog.state()['items']
            self.assertGreater(len({row['platform'] for row in rows}), 20)
            self.assertTrue(all(type(row['collection_supported']) is bool for row in rows))
            for platform in ('douyin', 'xiaohongshu', 'tiktok', 'youtube', 'bilibili'):
                row = next(row for row in rows if row['platform'] == platform)
                self.assertEqual(row['collection_supported'], catalog.detail(row['id'])['collection_supported'])
            self.assertFalse(next(row for row in rows if 'fetch_challenge_search_v2' in row['path'])['collection_supported'])

    def test_unsupported_collection_rejected_before_provider_or_budget_use(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TIKHUB_API_KEY': '', 'SHORT_VIDEO_OPS_WORKSPACE': ''}), patch('app.tikhub_json') as supplier:
            server = app.create_server(0, folder)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = 'http://127.0.0.1:' + str(server.server_address[1])
            try:
                with urlopen(origin + '/api/state?mode=live') as stream:
                    token = json.load(stream)['token']
                body = dict(id='GET /api/v1/youtube/web/search_video', params={'keyword': 'test'}, collect=True)
                request = Request(origin + '/api/tools/run', json.dumps(body).encode(),
                    {'Origin': origin, 'X-Radar-Token': token, 'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request)
                self.assertEqual(caught.exception.code, 400)
                self.assertIn('未发出供应商请求', json.load(caught.exception)['error'])
                supplier.assert_not_called()
            finally:
                server.shutdown(); server.server_close(); worker.join(3)
