import base64
import copy
import json
import io
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from contextlib import closing
from urllib.request import Request, urlopen
from unittest.mock import patch

import app
from video_creative import DIMENSIONS


class AgentAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.start_server()
        self.addCleanup(self.stop_server)
        jpeg = (Path(__file__).parent / 'fixtures/frame.jpg').read_bytes()
        self.inputs = dict(duration=2, outputs=['shooting', 'video_prompt'], target_seconds=30,
            product='合成测试收纳盒', audience='整理桌面的人', facts='合成资料：盒宽20厘米',
            conditions='手机拍摄，不露脸', details='', transcript='先量一下桌面。',
            transcript_source='manual', goal='展示卖点', format='实测演示', style='自然分享',
            reference='借鉴整体结构', frames=[dict(at=0, image='data:image/jpeg;base64,' + base64.b64encode(jpeg).decode())])

    def start_server(self):
        self.server = app.create_server(port=0, data_dir=self.folder.name)
        port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(port)
        self.token = self.request('/api/state?mode=live')['token']

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, path, body=None, headers=None):
        options = {}
        if body is not None:
            options = dict(data=body if isinstance(body, bytes) else json.dumps(body).encode(),
                headers={'Origin': self.base, 'X-Radar-Token': self.token,
                         'Content-Type': 'application/json', **(headers or {})})
        try:
            with urlopen(Request(self.base + path, **options), timeout=5) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            with exc:
                exc.payload = json.loads(exc.read())
            raise

    def saved_input(self):
        media = self.request('/api/agent/media', b'\x00\x00\x00\x18ftypisom0000',
                             {'Content-Type': 'video/mp4', 'X-Radar-Filename': 'test.mp4'})
        return self.request('/api/agent/task/save', {'input': self.inputs,
                            'media_id': media['media_id'], 'expected_version': 0})

    def test_truncated_frame_is_rejected_without_creating_task(self):
        self.inputs['frames'][0]['image'] = 'data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8truncated').decode()
        with self.assertRaises(HTTPError) as error:
            self.saved_input()
        self.assertIn('JPEG', error.exception.payload['error'])
        self.assertEqual(self.request('/api/agent/tasks'), [])

    def test_nonempty_transcript_cannot_be_labeled_as_missing_source(self):
        self.inputs['transcript_source'] = 'none'
        with self.assertRaises(HTTPError) as error:
            self.saved_input()
        self.assertIn('台词来源', error.exception.payload['error'])
        self.assertEqual(self.request('/api/agent/tasks'), [])

    def fake_generate(self, body, account_context=None, response_sink=None):
        self.seen_context = account_context
        report = dict(summary='合成传输替身，仅验证流程',
            observations=[dict(frame=1,evidence='合成画面',inference='待验证',advice='按资料拍摄')],
            evaluations=[dict(dimension=d,verdict='无法判断',reason='合成测试',frames=[]) for d in DIMENSIONS],
            adaptation=dict(reuse=[],adjust=[],avoid=[]), missing=['人工复核'],
            deliverables=dict(shooting='合成分镜',video_prompt='合成提示词'))
        return dict(model='test-double-no-network',version='creative-v1.1',report=report,
            scope=dict(duration=body['duration'],frames=[dict(frame=1,at=0)],audio='人工台词',limitation='合成测试'))

    def test_generate_receives_frozen_account_and_survives_server_restart(self):
        draft = self.saved_input()
        self.request('/api/ai/config', {'endpoint': 'http://127.0.0.1:1/v1', 'model': 'offline-double'})
        with patch.object(app.VideoCreative, 'generate', side_effect=self.fake_generate) as generate:
            saved = self.request('/api/agent/task/generate',
                {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True})
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(self.seen_context['account']['account_uid'], saved['account']['account_uid'])
        self.assertEqual(self.seen_context['strategy'], draft['strategy'])
        self.assertEqual(saved['version'], 2)
        self.stop_server()
        self.start_server()
        opened = self.request('/api/agent/task?id=' + saved['task_uid'])
        self.assertEqual(opened['result'], saved['result'])
        self.assertEqual(opened['input']['transcript_source'], 'manual')
        self.assertEqual(opened['account'], saved['account'])

    def test_no_confirmation_or_stale_version_never_calls_model(self):
        draft = self.saved_input()
        with patch.object(app.VideoCreative, 'generate') as generate:
            for fields in [{'expected_version': 1, 'confirm': False},
                           {'expected_version': 0, 'confirm': True}]:
                with self.assertRaises(HTTPError) as error:
                    self.request('/api/agent/task/generate', {'task_uid': draft['task_uid'], **fields})
                self.assertEqual(error.exception.code, 400)
            generate.assert_not_called()

    def test_invalid_response_is_archived_before_validation_and_survives_restart(self):
        draft = self.saved_input()
        self.request('/api/ai/config', {'endpoint': 'http://127.0.0.1:1/v1', 'model': 'offline-double'})
        raw = json.dumps({'choices': [{'message': {'content': '```json\n{bad\n```'}}]}).encode()
        with patch('ai_directions.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(raw)
            with self.assertRaises(HTTPError):
                self.request('/api/agent/task/generate',
                    {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True})
            self.assertEqual(opener.return_value.open.call_count, 1)
        with closing(sqlite3.connect(Path(self.folder.name) / 'radar.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT raw_response FROM agent_task_attempt').fetchone()[0], raw)
        self.stop_server()
        self.start_server()
        reopened = self.request('/api/agent/task?id=' + draft['task_uid'])
        attempt = reopened['attempts'][-1]
        self.assertEqual(attempt['status'], 'validation_failed')
        self.assertEqual(attempt['validation']['repairs'], ['remove_code_fence'])
        self.assertEqual(attempt['validation']['location']['line'], 1)
        self.assertNotIn('raw_response', attempt)
        self.assertEqual(reopened['input'], draft['input'])

    def test_bad_transport_cannot_erase_previous_result_or_trigger_retry(self):
        draft = self.saved_input()
        self.request('/api/ai/config', {'endpoint': 'http://127.0.0.1:1/v1', 'model': 'offline-double'})
        with patch.object(app.VideoCreative, 'generate', side_effect=self.fake_generate):
            generated = self.request('/api/agent/task/generate',
                {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True})
        with patch('ai_directions.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b'bad envelope')
            with self.assertRaises(HTTPError):
                self.request('/api/agent/task/generate',
                    {'task_uid': draft['task_uid'], 'expected_version': 2, 'confirm': True})
            self.assertEqual(opener.return_value.open.call_count, 1)
        reopened = self.request('/api/agent/task?id=' + draft['task_uid'])
        self.assertEqual(reopened['result'], generated['result'])
        self.assertEqual(reopened['version'], 2)
        self.assertEqual(reopened['attempts'][-1]['status'], 'validation_failed')

    def test_concurrent_generate_and_save_cannot_duplicate_model_call(self):
        draft = self.saved_input()
        self.request('/api/ai/config', {'endpoint': 'http://127.0.0.1:1/v1', 'model': 'offline-double'})
        started, release = threading.Event(), threading.Event()
        results = []
        def slow_generate(*args, **kwargs):
            started.set()
            if not release.wait(4):
                raise ValueError('测试超时')
            return self.fake_generate(*args, **kwargs)
        payload = {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True}
        def generate_first():
            try:
                results.append(self.request('/api/agent/task/generate', payload))
            except Exception as exc:
                results.append(exc)
        with patch.object(app.VideoCreative, 'generate', side_effect=slow_generate) as model:
            worker = threading.Thread(target=generate_first)
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                with self.assertRaises(HTTPError):
                    self.request('/api/agent/task/generate', payload)
                with self.assertRaises(HTTPError):
                    self.request('/api/agent/task/save', dict(payload, input=self.inputs, media_id=draft['media']['media_id']))
            finally:
                release.set()
                worker.join(5)
            self.assertEqual(model.call_count, 1)
        self.assertEqual(results[0]['version'], 2)

    def test_successful_retry_uses_frozen_rules_and_records_local_repairs(self):
        draft = self.saved_input()
        self.request('/api/ai/config', {'endpoint': 'http://127.0.0.1:1/v1', 'model': 'offline-double'})
        with patch('ai_directions.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b'invalid first response')
            with self.assertRaises(HTTPError):
                self.request('/api/agent/task/generate',
                    {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True})
        report = self.fake_generate(self.inputs)['report']
        raw = json.dumps({'choices': [{'message': {'content': '\ufeff```json\n' + json.dumps(report) + '\n```'}}]}).encode()
        captured = []
        def transport(request, timeout):
            captured.append(json.loads(request.data))
            return io.BytesIO(raw)
        with patch('ai_directions.build_opener') as opener, patch('video_creative.TASK_RULES', 'changed rules'):
            opener.return_value.open.side_effect = transport
            result = self.request('/api/agent/task/generate',
                {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True})
        self.assertEqual(captured[0]['messages'][0]['content'], draft['rules']['text'])
        self.assertEqual(captured[0]['max_tokens'], 6000)
        self.assertEqual(result['rules'], draft['rules'])
        self.assertEqual(result['attempts'][-1]['validation']['repairs'], ['remove_bom', 'remove_code_fence'])
        self.assertEqual(result['version'], 2)
        self.assertEqual([a['status'] for a in result['attempts']], ['validation_failed', 'success'])

    def test_edit_is_new_version_and_changed_inputs_cannot_relabel_old_result(self):
        draft = self.saved_input()
        self.request('/api/ai/config', {'endpoint': 'http://127.0.0.1:1/v1', 'model': 'offline-double'})
        with patch.object(app.VideoCreative, 'generate', side_effect=self.fake_generate):
            generated = self.request('/api/agent/task/generate',
                {'task_uid': draft['task_uid'], 'expected_version': 1, 'confirm': True})
        result = copy.deepcopy(generated['result'])
        result['report']['deliverables']['shooting'] = '人工修改分镜'
        payload = {'task_uid': draft['task_uid'], 'expected_version': 2,
                   'input': self.inputs, 'media_id': generated['media']['media_id'], 'result': result}
        edited = self.request('/api/agent/task/save', payload)
        self.assertEqual(edited['version'], 3)
        self.assertEqual(edited['source'], 'user_saved')
        payload['expected_version'] = 3
        payload['input'] = dict(self.inputs, transcript='新的台词')
        with self.assertRaises(HTTPError):
            self.request('/api/agent/task/save', payload)
        old = self.request('/api/agent/task?id=' + draft['task_uid'] + '&version=2')
        self.assertEqual(old['result']['report']['deliverables']['shooting'], '合成分镜')


if __name__ == '__main__':
    unittest.main()
