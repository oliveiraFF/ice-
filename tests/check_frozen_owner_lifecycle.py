"""Explicit opt-in frozen-exe acceptance with isolated data and localhost-only model."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_creative import DIMENSIONS


def launch(exe, data):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    environment = dict(os.environ)
    for key in ('TIKHUB_API_KEY', 'LLM_ALLOW_PAID'):
        environment.pop(key, None)
    process = subprocess.Popen([str(exe), '--data-dir', str(data)], env=environment, startupinfo=startup)
    try:
        for _ in range(160):
            if process.poll() is not None:
                raise RuntimeError('test exe exited before readiness')
            session = data / 'desktop-session.json'
            if session.exists():
                state = json.loads(session.read_text('utf-8'))
                if state['pid'] == process.pid:
                    origin = 'http://127.0.0.1:' + str(state['port'])
                    time.sleep(.3)
                    return process, origin
            time.sleep(.25)
        raise RuntimeError('test exe startup timed out')
    except Exception:
        process.terminate()
        process.wait(15)
        raise


def request(origin, path, body=None, headers=None):
    options = {}
    if body is not None:
        with urlopen(origin + '/api/state?mode=live', timeout=5) as response:
            token = json.load(response)['token']
        options = dict(data=body if isinstance(body, bytes) else json.dumps(body).encode(),
            headers={'Origin': origin, 'X-Radar-Token': token, 'Content-Type': 'application/json', **(headers or {})})
    with urlopen(Request(origin + path, **options), timeout=15) as response:
        return json.load(response)


def close_cleanly(process, origin, data):
    request(origin, '/api/desktop/exit', {'confirm': True})
    assert process.wait(20) == 0, 'nonzero exe exit'
    assert not (data / 'desktop-session.json').exists(), 'desktop cleanup did not finish'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    data = args.output / 'data'
    data.mkdir()
    key = 'synthetic-frozen-owner-lifecycle-not-a-live-key'
    model_calls = []
    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            model_calls.append({'max_tokens': payload.get('max_tokens')})
            report = dict(summary='Synthetic frozen transport test; no quality claim',
                observations=[dict(frame=1, evidence='synthetic', inference='unverified', advice='manual review')],
                evaluations=[dict(dimension=d, verdict='无法判断', reason='synthetic', frames=[]) for d in DIMENSIONS],
                adaptation=dict(reuse=[], adjust=[], avoid=[]), missing=['真实素材与人工评审'],
                deliverables=dict(shooting='合成分镜', video_prompt='合成提示词'))
            raw = json.dumps({'choices': [{'message': {'content': json.dumps(report)}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    model = HTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    process = None
    result = {}
    try:
        process, origin = launch(args.exe.resolve(), data)
        request(origin, '/api/connect', {'key': key})
        assert model_calls == []
        vault = data / 'owner-tikhub/credential.bin'
        assert vault.exists() and key.encode() not in vault.read_bytes()
        strategy = request(origin, '/api/strategy/save', {'expected_version': 0,
            'data': {'direction': '合成演示', 'audience': '合成受众', 'resources': '仅合成素材'}})
        request(origin, '/api/strategy/confirm', {'expected_version': strategy['version']})
        media = request(origin, '/api/agent/media', args.video.read_bytes(),
            {'Content-Type': 'video/webm', 'X-Radar-Filename': 'synthetic.webm'})
        frame = (Path(__file__).parent / 'fixtures/frame.jpg').read_bytes()
        inputs = dict(duration=3, outputs=['shooting', 'video_prompt'], target_seconds=30,
            product='合成测试收纳盒', audience='合成受众', facts='合成事实：宽20厘米', conditions='手机拍摄',
            details='', transcript='人工合成台词', transcript_source='manual', goal='展示卖点',
            format='实测演示', style='自然分享', reference='借鉴整体结构',
            frames=[dict(at=0, image='data:image/jpeg;base64,' + base64.b64encode(frame).decode())])
        task = request(origin, '/api/agent/task/save', {'input': inputs, 'media_id': media['media_id'], 'expected_version': 0})
        request(origin, '/api/ai/config', {'endpoint': 'http://127.0.0.1:' + str(model.server_address[1]), 'model': 'localhost-frozen-fixture'})
        generated = request(origin, '/api/agent/task/generate', {'task_uid': task['task_uid'], 'expected_version': 1, 'confirm': True})
        edited = copy.deepcopy(generated['result'])
        edited['report']['deliverables']['shooting'] = '人工编辑：合成分镜'
        saved = request(origin, '/api/agent/task/save', {'task_uid': task['task_uid'], 'expected_version': 2,
            'input': inputs, 'media_id': media['media_id'], 'result': edited})
        close_cleanly(process, origin, data)
        print('frozen save and normal exit passed', flush=True)
        process, origin = launch(args.exe.resolve(), data)
        state = request(origin, '/api/state?mode=live')
        assert state['connected'] and state['credential_remembered'] and not state['credential_error']
        assert not state['access']['enabled']
        reopened = request(origin, '/api/agent/task?id=' + task['task_uid'])
        assert reopened['result'] == saved['result'] and reopened['version'] == 3
        assert reopened['strategy']['confirmed'] == 1
        old = request(origin, '/api/agent/task?id=' + task['task_uid'] + '&version=2')
        assert old['result']['report']['deliverables']['shooting'] == '合成分镜'
        assert len(model_calls) == 1
        request(origin, '/api/connect', {'key': ''})
        assert not vault.exists()
        close_cleanly(process, origin, data)
        print('frozen restart, history and forget passed', flush=True)
        process, origin = launch(args.exe.resolve(), data)
        assert not request(origin, '/api/state?mode=live')['connected']
        close_cleanly(process, origin, data)
        vault.parent.mkdir(exist_ok=True)
        vault.write_bytes(b'corrupt synthetic vault')
        process, origin = launch(args.exe.resolve(), data)
        state = request(origin, '/api/state?mode=live')
        assert not state['connected'] and state['credential_error']
        request(origin, '/api/connect', {'key': key})
        request(origin, '/api/connect', {'key': ''})
        close_cleanly(process, origin, data)
        print('frozen clear persistence and corrupt-vault recovery passed', flush=True)
        for path in data.rglob('*'):
            if path.is_file():
                assert key.encode() not in path.read_bytes(), 'synthetic key leaked outside protected vault'
        release = args.exe.parent
        manifest_bad = []
        for line in (release / 'MANIFEST.sha256').read_text('utf-8').splitlines():
            digest, name = line.split('  ', 1)
            if hashlib.sha256((release / name).read_bytes()).hexdigest() != digest:
                manifest_bad.append(name)
        assert not manifest_bad
        identity = json.loads((release / 'SOURCE.json').read_text('utf-8'))
        assert identity['build_id'] == 'ice-agent-20261024-credential1' and not identity['source_dirty']
        result = dict(save_restart_forget_passed=True, corrupt_vault_recovered=True,
            normal_exits=4, task_versions_preserved=True, confirmed_strategy_preserved=True,
            actual_local_model_calls=len(model_calls), external_paid_calls=0, manifest_bad=manifest_bad,
            source_commit=identity['source_commit'], exe_sha256=hashlib.sha256(args.exe.read_bytes()).hexdigest(),
            evidence_scope='actual packaged exe; synthetic business inputs and localhost model, no real quality claim')
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(15)
        model.shutdown()
        model.server_close()
    (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')


if __name__ == '__main__':
    main()
