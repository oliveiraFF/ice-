"""Copy an explicitly supplied synthetic acceptance DB into a NEW test directory."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tasks import AgentTasks

source, target = map(lambda s: Path(s).resolve(), sys.argv[1:3])
target.mkdir(parents=True, exist_ok=False)
(target / 'data').mkdir()
shutil.copy2(source, target / 'data/radar.sqlite3')
store = AgentTasks(target / 'data/radar.sqlite3', 'UI validation only')
task = store.get('7a4b5d86524e')
raw = store.read_media(task['media']['media_id'])['data']
(target / 'original-video.mp4').write_bytes(raw)
(target / 'relink-video.mp4').write_bytes(raw + b'\x00\x00\x00\x08free')
ids = {}
for status in ['need_input', 'failed', 'result_unconfirmed', 'processing']:
    row = store.save({**task['input'], 'product': '演示 ' + status},
                     task['media']['media_id'], task['strategy'], source='test')
    ids[status] = row['task_uid']
    if status != 'need_input':
        attempt = store.begin_attempt(row, 'local-fixture')
        if status != 'processing':
            store.finish_attempt(attempt, status, {'error': '演示：本地失败夹具，未调用模型'})
(target / 'fixture.json').write_text(json.dumps({
    'ids': ids, 'media_id': task['media']['media_id']}, indent=2), encoding='utf-8')
