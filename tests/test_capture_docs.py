from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from catalog import Catalog

VIDEO = 'POST /api/v1/douyin/search/fetch_video_search_v2'
TOPIC = 'POST /api/v1/douyin/search/fetch_challenge_search_v2'
SHARE = 'GET /api/v1/douyin/app/v3/fetch_one_video_by_share_url'


class CaptureDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(Path(__file__).resolve().parents[1] / 'catalog.json', self.root / 'radar.sqlite3')
        self.catalog.configure_access(True, '1', allow_balance=True)

    def test_current_search_contracts_have_explicit_input_and_documented_options(self):
        for kind in ('video', 'challenge'):
            for version in ('v1', 'v2'):
                item = self.catalog.detail('POST /api/v1/douyin/search/fetch_'+kind+'_search_'+version)
                self.assertEqual(item['body']['keyword'], '')
                self.assertIn('keyword', item['body_schema']['required'])
                self.assertEqual(item['body']['cursor'], 0)
                self.assertEqual(item['body']['search_id'], '')
                self.assertEqual(item['body_schema']['properties']['sort_type']['enum'], ['0','1','2'])
                self.assertEqual(item['collection_supported'], kind == 'video')
                self.assertTrue(item['docs_url'].startswith('https://docs.tikhub.io/'))

    def test_blank_keyword_and_undocumented_option_are_rejected_without_supplier(self):
        self.catalog.manage(VIDEO, 'enable')
        call = Mock(side_effect=AssertionError('No paid call'))
        for changes in ({'keyword':''}, {'keyword':' '}, {'keyword':'AI','sort_type':'99'}):
            with self.assertRaises(ValueError):
                self.catalog.run(VIDEO, 'synthetic', {}, dict(self.catalog.get(VIDEO)['body'], **changes), call)
        call.assert_not_called()
        with closing(sqlite3.connect(self.catalog.database)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM api_requests').fetchone()[0], 0)

    def test_share_link_is_required_but_official_example_is_not_a_customer_request(self):
        for prefix in ('app/v3', 'web'):
            item = self.catalog.detail('GET /api/v1/douyin/'+prefix+'/fetch_one_video_by_share_url')
            self.assertEqual(item['query']['share_url'], '')
            field = item['parameters'][0]
            self.assertTrue(field['required'])
            self.assertGreater(field['schema']['minLength'], 0)
            self.assertTrue(field['example'].startswith('https://v.douyin.com/'))

    def test_topic_collection_is_rejected_by_http_before_any_provider_request(self):
        with patch.dict(os.environ, {'TIKHUB_API_KEY':'', 'SHORT_VIDEO_OPS_WORKSPACE':''}), patch('app.tikhub_json') as supplier:
            server = app.create_server(0, self.root)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            origin = 'http://127.0.0.1:'+str(server.server_address[1])
            try:
                with urlopen(origin+'/api/state?mode=live') as r: token=json.load(r)['token']
                body=json.dumps(dict(id=TOPIC, params={}, body={'keyword':'AI'}, collect=True)).encode()
                request=Request(origin+'/api/tools/run', data=body, headers={'Origin':origin,'X-Radar-Token':token,'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as caught: urlopen(request)
                self.assertEqual(caught.exception.code, 400)
                self.assertIn('话题', json.load(caught.exception)['error'])
                supplier.assert_not_called()
            finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
