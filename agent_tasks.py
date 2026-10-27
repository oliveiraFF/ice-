"""Local video-task snapshots. Additive tables; no model or network calls."""
import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

MAX_MEDIA_BYTES = 20 * 1024 * 1024
TABLES = {'agent_local_account', 'agent_media', 'agent_task', 'agent_task_version', 'agent_task_attempt'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS agent_local_account (
 id INTEGER PRIMARY KEY CHECK(id=1), account_uid TEXT NOT NULL UNIQUE,
 label TEXT NOT NULL, identity_state TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS agent_media (
 media_id TEXT PRIMARY KEY, mime TEXT NOT NULL, filename TEXT NOT NULL,
 data BLOB NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS agent_task (
 task_uid TEXT PRIMARY KEY, account_uid TEXT NOT NULL, current_version INTEGER NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS agent_task_version (
 task_uid TEXT NOT NULL, version INTEGER NOT NULL, account_json TEXT NOT NULL,
 input_json TEXT NOT NULL, strategy_json TEXT NOT NULL, result_json TEXT,
 rules_json TEXT NOT NULL, media_id TEXT NOT NULL, source TEXT NOT NULL,
 created_at REAL NOT NULL, PRIMARY KEY(task_uid,version),
 FOREIGN KEY(task_uid) REFERENCES agent_task(task_uid),
 FOREIGN KEY(media_id) REFERENCES agent_media(media_id));
CREATE TABLE IF NOT EXISTS agent_task_attempt (
 attempt_uid TEXT PRIMARY KEY, task_uid TEXT NOT NULL, input_version INTEGER NOT NULL,
 status TEXT NOT NULL, model TEXT NOT NULL, raw_response BLOB,
 validation_json TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
 FOREIGN KEY(task_uid,input_version) REFERENCES agent_task_version(task_uid,version));
'''


def backup_database(path):
    folder = path.parent / 'backups'
    folder.mkdir(exist_ok=True)
    name = 'before-agent-tasks-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = folder / (name + '.sqlite3')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('BEGIN')
        schema_version = source.execute('PRAGMA schema_version').fetchone()[0]
        tables = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        def counts(db):
            return {table: db.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                    for table in tables}
        expected = counts(source)
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
            if (destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok'
                    or counts(destination) != expected):
                raise ValueError('数据库备份验证失败，未迁移')
    manifest = dict(schema_version=schema_version, tables=expected,
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    restore_scope='仅恢复备份时已提交的数据；迁移后的新增记录不在恢复点中')
    target.with_suffix('.json').write_text(_json(manifest), encoding='utf-8')
    return target


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class AgentTasks:
    def __init__(self, database, rules):
        self.path = Path(database).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rules = {'version': 'agent-video-v1', 'sha256': hashlib.sha256(rules.encode()).hexdigest(),
                      'text': rules}
        existed = self.path.exists() and self.path.stat().st_size > 0
        with closing(self.connect()) as db:
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not TABLES.issubset(present):
            if existed:
                backup_database(self.path)
            with closing(self.connect()) as db:
                try:
                    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
                except Exception:
                    db.rollback()
                    raise
        with closing(self.connect()) as db:
            db.execute('INSERT OR IGNORE INTO agent_local_account VALUES(1,?,?,?,?)',
                       (uuid.uuid4().hex, '当前本地账号', 'identity_pending', time.time()))
            db.execute("UPDATE agent_task_attempt SET status='result_unconfirmed',finished_at=?,validation_json=? WHERE status='processing'",
                       (time.time(), _json({'error': '上次生成被中断，结果未确认；不会自动重试'})))
            db.commit()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def account(self):
        with closing(self.connect()) as db:
            return dict(db.execute('SELECT * FROM agent_local_account WHERE id=1').fetchone())

    def put_media(self, raw, mime, filename):
        if not isinstance(raw, bytes):
            raise ValueError('视频数据格式无效')
        valid = (mime == 'video/mp4' and raw[4:8] == b'ftyp'
                 or mime == 'video/webm' and raw[:4] == b'\x1aE\xdf\xa3')
        if not isinstance(raw, bytes) or not 12 <= len(raw) <= MAX_MEDIA_BYTES or not valid:
            raise ValueError('请选择20MB以内的MP4或WebM视频')
        filename = re.sub(r'[\x00-\x1f/\\]', '_', str(filename or 'video'))[:150]
        ident = hashlib.sha256(raw).hexdigest()
        with closing(self.connect()) as db:
            db.execute('INSERT OR IGNORE INTO agent_media VALUES(?,?,?,?,?,?)',
                       (ident, mime, filename, raw, len(raw), time.time()))
            db.commit()
        return {key: value for key, value in self.read_media(ident).items() if key != 'data'}

    def read_media(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{64}', ident):
            raise ValueError('素材标识无效')
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM agent_media WHERE media_id=?', (ident,)).fetchone()
        if row is None:
            raise ValueError('本地素材不存在，请重新选择视频')
        return dict(row)

    def save(self, inputs, media_id, strategy, result=None, source='user_input',
             task_uid=None, expected_version=0, rules=None):
        if not isinstance(inputs, dict) or not isinstance(strategy, dict):
            raise ValueError('任务输入格式无效')
        if result is not None and not isinstance(result, dict):
            raise ValueError('成果格式无效')
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError('缺少有效的任务版本')
        if source not in ('user_input', 'user_saved', 'llm', 'test'):
            raise ValueError('成果来源无效')
        if task_uid is not None and (not isinstance(task_uid, str)
                                     or not re.fullmatch(r'[a-f0-9]{12}', task_uid)):
            raise ValueError('任务标识无效')
        self.read_media(media_id)
        input_json, strategy_json, result_json = _json(inputs), _json(strategy), _json(result)
        if len(input_json.encode()) > 5 * 1024 * 1024 or len(result_json.encode()) > 1024 * 1024:
            raise ValueError('任务内容超过保存上限')
        account = self.account()
        now = time.time()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM agent_task WHERE task_uid=?', (task_uid,)).fetchone()
            if task_uid is not None and row is None:
                raise ValueError('任务不存在')
            if (row['current_version'] if row else 0) != expected_version:
                raise ValueError('任务版本已变化，请重新打开最新版本')
            if row:
                version = row['current_version'] + 1
                db.execute('UPDATE agent_task SET current_version=?,updated_at=? WHERE task_uid=?',
                           (version, now, task_uid))
            else:
                task_uid, version = uuid.uuid4().hex[:12], 1
                db.execute('INSERT INTO agent_task VALUES(?,?,?,?,?)',
                           (task_uid, account['account_uid'], version, now, now))
            db.execute('INSERT INTO agent_task_version VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (task_uid, version, _json(account), input_json, strategy_json,
                        result_json, _json(rules or self.rules), media_id, source, now))
            db.commit()
        return self.get(task_uid)

    def get(self, task_uid, version=None):
        if not isinstance(task_uid, str) or not re.fullmatch(r'[a-f0-9]{12}', task_uid):
            raise ValueError('任务标识无效')
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError('任务版本无效')
        with closing(self.connect()) as db:
            task = db.execute('SELECT * FROM agent_task WHERE task_uid=?', (task_uid,)).fetchone()
            row = db.execute('SELECT * FROM agent_task_version WHERE task_uid=? AND version=?',
                             (task_uid, version or (task['current_version'] if task else 0))).fetchone()
            if not task or not row:
                raise ValueError('任务或版本不存在')
            versions = [dict(item) for item in db.execute(
                'SELECT version,source,created_at FROM agent_task_version WHERE task_uid=? ORDER BY version',
                (task_uid,))]
            attempts = [dict(item) for item in db.execute(
                'SELECT attempt_uid,input_version,status,model,validation_json,started_at,finished_at,length(raw_response) AS response_bytes FROM agent_task_attempt WHERE task_uid=? ORDER BY started_at',
                (task_uid,))]
            for attempt in attempts:
                attempt['validation'] = json.loads(attempt.pop('validation_json'))
        result = dict(task)
        for name in ('account', 'input', 'strategy', 'result', 'rules'):
            result[name] = json.loads(row[name + '_json'])
        result.update(version=row['version'], source=row['source'], versions=versions,
                      attempts=attempts,
                      media={key: value for key, value in self.read_media(row['media_id']).items() if key != 'data'})
        return result

    def archived_attempt(self, task_uid, attempt_uid, input_version):
        if not isinstance(attempt_uid, str) or not re.fullmatch(r'[a-f0-9]{32}', attempt_uid):
            raise ValueError('请选择有效的本机生成记录')
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM agent_task_attempt WHERE task_uid=? AND attempt_uid=? AND input_version=?',
                             (task_uid, attempt_uid, input_version)).fetchone()
        if not row or row['status'] not in ('validation_failed', 'result_unconfirmed', 'failed'):
            raise ValueError('只能恢复当前输入版本的失败响应；请重新打开最新任务')
        if not row['raw_response']:
            raise ValueError('此次请求未保留模型响应，无法本地恢复；不会调用模型')
        return dict(row, response_sha256=hashlib.sha256(row['raw_response']).hexdigest())

    def begin_attempt(self, task, model):
        ident = uuid.uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO agent_task_attempt VALUES(?,?,?,?,?,NULL,?,?,NULL)',
                       (ident, task['task_uid'], task['version'], 'processing', model, '{}', time.time()))
        return ident

    def archive_response(self, ident, raw):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE agent_task_attempt SET raw_response=? WHERE attempt_uid=? AND status='processing'",
                       (raw, ident))

    def finish_attempt(self, ident, status, validation):
        if status not in ('success', 'validation_failed', 'result_unconfirmed', 'failed'):
            raise ValueError('生成状态无效')
        with closing(self.connect()) as db, db:
            db.execute("UPDATE agent_task_attempt SET status=?,validation_json=?,finished_at=? WHERE attempt_uid=? AND status='processing'",
                       (status, _json(validation), time.time(), ident))

    def list(self):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute('''
                SELECT t.task_uid,t.current_version,t.updated_at,v.source,v.input_json
                FROM agent_task t JOIN agent_task_version v
                ON t.task_uid=v.task_uid AND t.current_version=v.version
                ORDER BY t.updated_at DESC LIMIT 30''')]
