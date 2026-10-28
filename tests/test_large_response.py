from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import app
from catalog import Catalog

LIMIT = 10 * 1024 * 1024
ROUTE = '/api/v1/douyin/app/v3/fetch_one_video_by_share_url'
KEY = 'synthetic-not-a-real-key-for-large-response'


def fixture_catalog():
    snapshot = json.loads((Path(__file__).resolve().parents[1] / 'catalog.json').read_text('utf-8'))
    item = dict(next(i for i in snapshot['items'] if i['path'] == ROUTE), price='0')
    return dict(imported_at=0, source='合成技术验收目录，不代表供应商价格', items=[item])


def large_payload():
    return dict(code=200, data=dict(echoed=KEY, padding='合成填充' * 100000,
        aweme_list=[dict(aweme_id='1234567890123456789', desc='合成大响应验收作品',
            author=dict(nickname='合成验收作者'), video=dict(duration=2000))]))


class LargeResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(fixture_catalog(), self.root / 'radar.sqlite3')
        self.catalog.manage('GET ' + ROUTE, 'enable')

    def run_catalog(self, payload, consume=None):
        calls = []
        def supplier(route, **kwargs):
            calls.append(route)
            return dict(data=dict(endpoint_uri=ROUTE, endpoint_cost='0')) if route.endswith('get_endpoint_info') else payload
        result = self.catalog.run('GET '+ROUTE, KEY, {'share_url':'https://example.test/video'}, None, supplier, consume=consume)
        return result, calls

    def test_display_truncation_does_not_truncate_collection_or_expose_key(self):
        posts = []; echoes = []
        def consume(value):
            echoes.append(value['data']['echoed']); posts.extend(app.extract_posts(value, 'dy'))
        result, calls = self.run_catalog(large_payload(), consume)
        self.assertTrue(result['ok']); self.assertTrue(result['truncated'])
        self.assertEqual(len(posts), 1); self.assertEqual(posts[0]['external_id'], '1234567890123456789')
        self.assertLess(len(result['result']), 300100)
        self.assertNotIn(KEY, json.dumps(result, ensure_ascii=False))
        self.assertNotIn('padding', result.keys())
        with closing(sqlite3.connect(self.catalog.database)) as db:
            saved = db.execute('SELECT last_result FROM tools WHERE id=?', ('GET '+ROUTE,)).fetchone()[0]
        self.assertLess(len(saved), 300100); self.assertNotIn(KEY, saved)
        self.assertEqual(calls.count(ROUTE), 1)
        self.assertEqual(echoes, ['[密钥已隐藏]'])

    def test_large_provider_payload_is_rejected_without_consuming_or_retry(self):
        consumed = []
        result, calls = self.run_catalog(dict(code=200, data='x' * (LIMIT+1)), consumed.append)
        self.assertFalse(result['ok']); self.assertTrue(result['response_too_large'])
        self.assertIn('10MiB', result['result']); self.assertEqual(consumed, [])
        self.assertEqual(calls.count(ROUTE), 1)

    def test_consumer_failure_keeps_successful_provider_receipt_and_does_not_retry(self):
        def fail(value): raise ValueError('synthetic parser failure ' + KEY)
        result, calls = self.run_catalog(dict(code=200, data={}), fail)
        self.assertTrue(result['ok']); self.assertIn('processing_error', result)
        self.assertNotIn(KEY, json.dumps(result)); self.assertEqual(calls.count(ROUTE), 1)

    def test_media_link_resolution_uses_full_response_after_display_limit(self):
        urls=[];url='https://v26-web.douyinvod.com/synthetic.mp4';ident='1234567890123456789'
        payload=dict(code=200,data=dict(padding='x'*400000,video_id=ident,original_video_url=url))
        result,calls=self.run_catalog(payload,lambda value:urls.append(app.resolved_media_url(value,ident)))
        self.assertTrue(result['ok']);self.assertTrue(result['truncated'])
        self.assertEqual(urls,[url]);self.assertEqual(calls.count(ROUTE),1)

    def test_transport_reads_at_most_ten_mib_plus_one_before_json_parsing(self):
        class LimitedStream(BytesIO):
            def read(self, size=-1):
                self.requested = size
                return super().read(size)
        stream = LimitedStream(b'x' * (LIMIT+100))
        with patch.object(app, 'urlopen', return_value=stream), patch.object(app.json, 'loads', wraps=json.loads) as decoder:
            with self.assertRaisesRegex(ValueError, '10MiB'): app.tikhub_json(ROUTE)
            decoder.assert_not_called()
        self.assertTrue(stream.closed)
        self.assertEqual(stream.requested, LIMIT+1)

    def test_transport_accepts_exact_boundary_and_multibyte_payloads(self):
        prefix = b'{"code":200,"data":{}}'
        for raw in [prefix + b' ' * (LIMIT-len(prefix)), json.dumps(large_payload(),ensure_ascii=False).encode()]:
            self.assertLessEqual(len(raw), LIMIT)
            with patch.object(app, 'urlopen', return_value=BytesIO(raw)):
                self.assertEqual(app.tikhub_json(ROUTE)['code'], 200)

    def test_paid_oversize_keeps_budget_reservation_and_uncertain_outcome(self):
        self.catalog.get('GET '+ROUTE)['price'] = '0.001'
        self.catalog.configure_access(True, '1')
        calls=[]
        def supplier(route, **kwargs):
            calls.append(route)
            if route.endswith('get_endpoint_info'):return dict(data=dict(endpoint_uri=ROUTE,endpoint_cost='0.001',allow_free_credit=True))
            return dict(code=200,data='x'*(LIMIT+1))
        with patch.object(self.catalog,'refresh_credit',return_value=dict(free_credit='1',balance='0',allow_balance=False)):
            result=self.catalog.run('GET '+ROUTE,KEY,{'share_url':'https://example.test/video'},None,supplier)
        self.assertFalse(result['ok']);self.assertEqual(result['access']['spent'],'0.001')
        with closing(sqlite3.connect(self.catalog.database)) as db:
            self.assertEqual(db.execute('SELECT cost,outcome FROM api_requests').fetchall(),[('0.001','uncertain')])
        self.assertEqual(calls.count(ROUTE),1)

    def test_http_collects_full_response_and_keeps_it_out_of_browser_and_history(self):
        snapshot = fixture_catalog(); business = []
        def supplier(route, **kwargs):
            if route.endswith('get_endpoint_info'): return dict(data=dict(endpoint_uri=ROUTE, endpoint_cost='0'))
            business.append(route); return large_payload()
        with patch.dict(os.environ, {'TIKHUB_API_KEY':KEY,'SHORT_VIDEO_OPS_WORKSPACE':''}), \
             patch.object(app, 'Catalog', side_effect=lambda path, database, **kwargs: Catalog(snapshot, database, **kwargs)), \
             patch.object(app, 'tikhub_json', side_effect=supplier):
            server=app.create_server(0,self.root);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            origin='http://127.0.0.1:'+str(server.server_address[1])
            try:
                def request(route, body=None):
                    with urlopen(origin+'/api/state?mode=live') as r: token=json.load(r)['token']
                    data=json.dumps(body).encode() if body is not None else None
                    with urlopen(Request(origin+route,data=data,headers={'Origin':origin,'Content-Type':'application/json','X-Radar-Token':token})) as r:return json.load(r)
                response=request('/api/tools/run',dict(id='GET '+ROUTE,params={'share_url':'https://example.test/video'},collect=True,keyword='合成大响应验收'))
                self.assertTrue(response['ok']);self.assertTrue(response['truncated'])
                self.assertIn('已收录或更新 1',response['collection_message'])
                self.assertNotIn(KEY,json.dumps(response));self.assertLess(len(json.dumps(response)),1900000)
                posts=request('/api/state?mode=live')['posts'];self.assertEqual(len(posts),1)
                self.assertEqual(posts[0]['external_id'],'1234567890123456789')
                self.assertEqual(business,[ROUTE])
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
