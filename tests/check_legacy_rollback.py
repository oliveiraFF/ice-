"""Opt-in old-exe compatibility check using new, isolated synthetic data only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tasks import AgentTasks


def launch(exe, data):
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    environment = dict(os.environ)
    for key in ('TIKHUB_API_KEY', 'LLM_ALLOW_PAID'):
        environment.pop(key, None)
    process = subprocess.Popen([str(exe), '--data-dir', str(data)], env=environment, startupinfo=info)
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError('旧exe提前退出：' + str(process.returncode))
            session = data / 'desktop-session.json'
            if session.exists():
                state = json.loads(session.read_text('utf-8'))
                if state['pid'] == process.pid:
                    return process, 'http://127.0.0.1:' + str(state['port'])
            time.sleep(.25)
        raise RuntimeError('旧exe启动超时')
    except Exception:
        process.terminate()
        process.wait(10)
        raise


def request(origin, path, body=None):
    headers = {}
    if body is not None:
        with urlopen(origin + '/api/state?mode=live', timeout=10) as response:
            token = json.load(response)['token']
        headers = {'Origin': origin, 'X-Radar-Token': token, 'Content-Type': 'application/json'}
    req = Request(origin + path, json.dumps(body).encode() if body is not None else None, headers)
    with urlopen(req, timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if response.headers.get('Content-Type', '').startswith('application/json') else raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    data = root / 'migrated-data'
    data.mkdir()
    process, origin = launch(args.exe.resolve(), data)
    try:
        strategy = request(origin, '/api/strategy/save', {'data': {'direction': '旧exe兼容性合成资料'}, 'expected_version': 0})
        strategy = request(origin, '/api/strategy/confirm', {'expected_version': strategy['version']})
        draft = request(origin, '/api/ops/draft/generate', {'topic': '合成回滚验收',
            'status': {'business': '合成业务', 'audience': '成年人', 'goal': '验证保存',
                       'resources': '仅合成资料', 'capacity': '2小时', 'question': ''},
            'selected': {}, 'model_mode': 'test', 'confirm': False})['draft']
        export_path = '/api/ops/draft/export?id=' + draft['draft_uid']
        before = request(origin, export_path)
    finally:
        process.terminate()
        process.wait(15)
    store = AgentTasks(data / 'radar.sqlite3', 'legacy compatibility test rules')
    media = store.put_media(b'\0\0\0\x18ftypisom0000', 'video/mp4', 'synthetic.mp4')
    task = store.save({'product': '仅迁移测试'}, media['media_id'], strategy)
    print('New additive task saved; checking old executable.', flush=True)
    results = {}
    backup = next((data / 'backups').glob('*.sqlite3'))
    restored = root / 'restored-data'
    restored.mkdir()
    shutil.copy2(backup, restored / 'radar.sqlite3')
    for label, folder in [('migrated', data), ('restored', restored)]:
        process, origin = launch(args.exe.resolve(), folder)
        try:
            results[label] = {'strategy_identical': request(origin, '/api/strategy') == strategy,
                              'export_identical': request(origin, export_path) == before}
            assert all(results[label].values()), label
            print(label + ' old-exe read/export passed', flush=True)
        finally:
            process.terminate()
            process.wait(15)
    assert AgentTasks(data / 'radar.sqlite3', 'rules').get(task['task_uid'])['input']['product'] == '仅迁移测试'
    (root / 'legacy-export.md').write_bytes(before)
    (root / 'result.json').write_text(json.dumps(dict(results=results,
        old_exe_sha256=hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        process_stop='terminated isolated test process; no claim of graceful exe exit',
        external_model_calls=0, new_agent_task_survives_old_exe=True), ensure_ascii=False, indent=2), 'utf-8')


if __name__ == '__main__':
    main()
