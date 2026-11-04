"""XHS app-v2 note_list regression; synthetic fixtures, no paid requests."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import app
from catalog import Catalog

ROUTE = '/api/v1/xiaohongshu/app_v2/get_image_note_detail'
NOTE_ID = '0123456789abcdef01234567'


def note_payload(kind='normal'):
    return dict(code=200, data=dict(success=True, data=[dict(note_list=[dict(
        id=NOTE_ID, type=kind, title='合成图文收录验收', desc='第一行正文\n第二行 <script>不应执行</script>',
        user=dict(id='abcdef0123456789abcdef01', nickname='合成验收作者'),
        liked_count=12, collected_count=3, collected=True, comments_count=2,
        view_count=99, time=1700000000,
        images_list=[dict(url='https://example.test/first.jpg'),
                     dict(url='https://example.test/second.jpg'),
                     dict(url='javascript:alert(1)')])], comment_list=[])]))


class XHSNoteCollectionTests(unittest.TestCase):
    def test_note_list_image_preserves_body_images_type_and_unknown_plays(self):
        posts = app.extract_posts(note_payload(), 'xhs')
        self.assertEqual(len(posts), 1)
        post = posts[0]
        self.assertEqual(post['external_id'], NOTE_ID)
        self.assertEqual(post['content_type'], 'image')
        self.assertEqual(post['description'], note_payload()['data']['data'][0]['note_list'][0]['desc'])
        self.assertEqual(post['images'], ['https://example.test/first.jpg', 'https://example.test/second.jpg'])
        self.assertEqual(post['cover'], post['images'][0])
        self.assertEqual((post['likes'], post['saves'], post['comments']), (12, 3, 2))
        self.assertIsNone(post.get('plays'))  # view_count is not verified video play_count.
        self.assertIsNone(post['video_url'])

    def test_video_note_through_image_endpoint_is_not_labelled_image_or_given_fake_video(self):
        post, = app.extract_posts(note_payload('video'), 'xhs')
        self.assertEqual(post['content_type'], 'video')
        self.assertEqual(post['cover'], 'https://example.test/first.jpg')
        self.assertIsNone(post['video_url'])

    def test_arbitrary_user_comment_ids_are_not_content(self):
        payload = dict(data=dict(user=dict(id=NOTE_ID, title='用户', desc='简介'),
                                 comment_list=[dict(id=NOTE_ID, title='评论', desc='评论正文')]))
        self.assertEqual(app.extract_posts(payload, 'xhs'), [])
        self.assertEqual(app.extract_posts(dict(data=dict(note_list=[dict(id='bad', title='无效')])), 'xhs'), [])

    def test_legacy_wrapped_and_note_id_formats_remain_supported_and_deduplicate(self):
        note = copy.deepcopy(note_payload()['data']['data'][0]['note_list'][0])
        old = dict(note, note_id=note['id'])
        old.pop('id')
        payload = dict(data=[dict(note_card=note), old, dict(note_list=[note])])
        post, = app.extract_posts(payload, 'xhs')
        self.assertEqual(post['external_id'], NOTE_ID)
        self.assertEqual(post['description'], note['desc'])

    def test_database_reopen_and_recollection_preserve_one_post_and_saved_note(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'test.sqlite3'
            store = app.Store(db)
            keyword = store.add_keyword('合成图文验收')
            posts = app.extract_posts(note_payload(), 'xhs')
            self.assertEqual(len(posts), 1)
            store.put_posts(keyword, posts, 'live')
            post, = store.state('live')['posts']
            store.save(post['id'], True, '用户笔记保留')
            store.put_posts(keyword, app.extract_posts(note_payload(), 'xhs'), 'live')
            reopened, = app.Store(db).state('live')['posts']
            self.assertEqual(reopened['id'], post['id'])
            self.assertEqual(reopened['images'], posts[0]['images'])
            self.assertEqual(reopened['description'], posts[0]['description'])
            self.assertTrue(reopened['saved'])
            self.assertEqual(reopened['note'], '用户笔记保留')

    def test_http_collection_consumes_actual_note_list_shape(self):
        snapshot = json.loads((Path(app.__file__).parent / 'catalog.json').read_text('utf-8'))
        item = dict(next(i for i in snapshot['items'] if i['path'] == ROUTE), price='0', requires_key=False)
        snapshot = dict(imported_at=0, source='合成验收目录', items=[item])
        calls = []
        def supplier(route, **kwargs):
            calls.append(route)
            if route.endswith('get_endpoint_info'):
                return dict(data=dict(endpoint_uri=ROUTE, endpoint_cost='0'))
            return note_payload()
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, {'TIKHUB_API_KEY':'', 'SHORT_VIDEO_OPS_WORKSPACE':''}), \
             patch.object(app, 'Catalog', side_effect=lambda path, database, **kwargs: Catalog(snapshot, database, **kwargs)), \
             patch.object(app, 'tikhub_json', side_effect=supplier):
            server = app.create_server(0, folder)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = 'http://127.0.0.1:' + str(server.server_address[1])
            def request(route, body=None):
                with urlopen(origin + '/api/state?mode=live') as stream:
                    token = json.load(stream)['token']
                raw = json.dumps(body).encode() if body is not None else None
                with urlopen(Request(origin + route, raw, {'Origin':origin, 'X-Radar-Token':token,
                                                         'Content-Type':'application/json'})) as stream:
                    return json.load(stream)
            try:
                request('/api/tools', dict(id=item['id'], action='add'))
                request('/api/tools', dict(id=item['id'], action='enable'))
                result = request('/api/tools/run', dict(id=item['id'], params={'note_id':NOTE_ID},
                                                       collect=True, keyword='合成图文验收'))
                self.assertTrue(result['ok'])
                self.assertIn('已收录或更新 1', result['collection_message'])
                post, = request('/api/state?mode=live')['posts']
                self.assertEqual(post['content_type'], 'image')
                self.assertEqual(post['external_id'], NOTE_ID)
                self.assertEqual(calls.count(ROUTE), 1)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(3)


if __name__ == '__main__':
    unittest.main()
