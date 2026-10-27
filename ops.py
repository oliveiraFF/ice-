"""运营层数据表与存取（short-video-ops 融合 Phase 1）。

新增 7 张表，把 short-video-ops 的分层数据域落进好物雷达的 SQLite：
  L0/L1  account_profile / strategy_brief    账号定位 + 已确认策略
  L3     pain_bank                           用户痛点库（选题证据）
  L4     reference_deconstruction            爆款拆解（视频分析结果持久化）
  L5     topic_candidates                    选题候选（含血缘）
  L7     feedback / strategy_delta           发布反馈 + 策略增量

遵循好物雷达既有风格：SQLite + JSON 存 TEXT 列，中文错误信息，无第三方依赖。
"""

import datetime
import json
import math
import re
import sqlite3
import time
import urllib.parse
import uuid
from contextlib import closing, nullcontext

TABLES = '''
CREATE TABLE IF NOT EXISTS account_profile (
  id INTEGER PRIMARY KEY CHECK(id=1),
  data TEXT NOT NULL DEFAULT '{}',
  confirmed INTEGER NOT NULL DEFAULT 0,
  provenance TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS strategy_brief (
  id INTEGER PRIMARY KEY CHECK(id=1),
  data TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'unconfirmed',
  confirmed_by_user INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pain_bank (
  id INTEGER PRIMARY KEY,
  pain TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'comment',
  evidence_role TEXT NOT NULL DEFAULT 'audience_pain',
  frequency INTEGER NOT NULL DEFAULT 1,
  related_post_id INTEGER,
  evidence TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reference_deconstruction (
  id INTEGER PRIMARY KEY,
  post_id INTEGER,
  title TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL DEFAULT 'video_analysis',
  report TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  source_name TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS topic_candidates (
  id INTEGER PRIMARY KEY,
  topic_id TEXT NOT NULL,
  lane TEXT NOT NULL,
  strategy_id INTEGER,
  signal_ids TEXT NOT NULL DEFAULT '[]',
  data TEXT NOT NULL,
  batch_id TEXT NOT NULL DEFAULT '',
  selected INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS topic_combo (
  id INTEGER PRIMARY KEY,
  combo_uid TEXT NOT NULL,
  business_date TEXT NOT NULL,
  strategy_version INTEGER NOT NULL,
  conservative_ids TEXT NOT NULL DEFAULT '[]',
  experimental_ids TEXT NOT NULL DEFAULT '[]',
  snapshot_json TEXT NOT NULL DEFAULT '[]',
  version INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE(combo_uid, business_date)
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY,
  post_id INTEGER,
  data TEXT NOT NULL,
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS strategy_delta (
  id INTEGER PRIMARY KEY,
  data TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS content_task (
  id INTEGER PRIMARY KEY,
  task_uid TEXT NOT NULL UNIQUE,
  product TEXT NOT NULL,
  audience TEXT NOT NULL DEFAULT '',
  facts_json TEXT NOT NULL DEFAULT '[]',
  references_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  usage_json TEXT NOT NULL DEFAULT '{}',
  duration_ms INTEGER,
  run_id TEXT NOT NULL DEFAULT '',
  data_source TEXT NOT NULL DEFAULT '',
  model_mode TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  formal INTEGER NOT NULL DEFAULT 0,
  strategy_version INTEGER,
  strategy_summary TEXT NOT NULL DEFAULT '',
  strategy_snapshot_json TEXT NOT NULL DEFAULT '{}',
  current_version INTEGER NOT NULL DEFAULT 1,
  approved_version INTEGER,
  approved_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS content_version (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL,
  version INTEGER NOT NULL,
  model_beats_json TEXT NOT NULL,
  human_beats_json TEXT NOT NULL,
  fact_ids_json TEXT NOT NULL DEFAULT '[]',
  missing_json TEXT NOT NULL DEFAULT '[]',
  run_id TEXT NOT NULL DEFAULT '',
  reference_ids_json TEXT NOT NULL DEFAULT '[]',
  reference_snapshot_json TEXT NOT NULL DEFAULT '[]',
  pain_ids_json TEXT NOT NULL DEFAULT '[]',
  pain_snapshot_json TEXT NOT NULL DEFAULT '[]',
  plan_json TEXT NOT NULL DEFAULT '{}',
  suggestion_ids_json TEXT NOT NULL DEFAULT '[]',
  suggestion_snapshot_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL,
  UNIQUE(task_id, version)
);
CREATE TABLE IF NOT EXISTS publish_record (
  id INTEGER PRIMARY KEY,
  record_uid TEXT NOT NULL UNIQUE,
  task_uid TEXT NOT NULL,
  version INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  platform TEXT NOT NULL DEFAULT '',
  platform_post_id TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  normalized_url TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT '',
  registered_at REAL NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE(platform, platform_post_id, task_uid, version)
);
CREATE TABLE IF NOT EXISTS metric_snapshot (
  id INTEGER PRIMARY KEY,
  record_uid TEXT NOT NULL,
  snapshot_key TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  collected_at TEXT NOT NULL,
  definition TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE(record_uid, snapshot_key)
);
CREATE TABLE IF NOT EXISTS review_record (
  id INTEGER PRIMARY KEY,
  review_uid TEXT NOT NULL UNIQUE,
  record_uid TEXT NOT NULL,
  snapshot_ids TEXT NOT NULL DEFAULT '[]',
  data_json TEXT NOT NULL DEFAULT '{}',
  observations_json TEXT NOT NULL DEFAULT '[]',
  suggestions_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ops_advice (
  id INTEGER PRIMARY KEY,
  advice_uid TEXT NOT NULL UNIQUE,
  status_json TEXT NOT NULL DEFAULT '{}',
  context_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT,
  question TEXT NOT NULL DEFAULT '',
  parent_uid TEXT,
  source TEXT NOT NULL DEFAULT 'demo',
  model TEXT,
  run_id TEXT,
  usage_json TEXT NOT NULL DEFAULT '{}',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS advice_action (
  id INTEGER PRIMARY KEY,
  advice_uid TEXT NOT NULL,
  action_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'todo',
  note TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL DEFAULT 1,
  updated_at REAL NOT NULL,
  UNIQUE(advice_uid, action_id)
);

CREATE TABLE IF NOT EXISTS research_draft (
  id INTEGER PRIMARY KEY,
  draft_uid TEXT NOT NULL UNIQUE,
  topic TEXT NOT NULL DEFAULT '',
  status_json TEXT NOT NULL DEFAULT '{}',
  context_json TEXT NOT NULL DEFAULT '{}',
  archived INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS research_draft_version (
  id INTEGER PRIMARY KEY,
  draft_uid TEXT NOT NULL,
  version INTEGER NOT NULL,
  instruction TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL DEFAULT '',
  status_json TEXT NOT NULL DEFAULT '{}',
  context_json TEXT NOT NULL DEFAULT '{}',
  base_version INTEGER NOT NULL DEFAULT 0,
  legacy_snapshot INTEGER NOT NULL DEFAULT 0,
  content_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'demo',
  model TEXT,
  run_id TEXT,
  usage_json TEXT NOT NULL DEFAULT '{}',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(draft_uid, version)
);

CREATE TABLE IF NOT EXISTS media_review (
  id INTEGER PRIMARY KEY,
  review_uid TEXT NOT NULL UNIQUE,
  draft_uid TEXT,
  draft_version INTEGER,
  goal TEXT NOT NULL DEFAULT '',
  input_json TEXT NOT NULL DEFAULT '{}',
  scope_json TEXT NOT NULL DEFAULT '{}',
  context_json TEXT NOT NULL DEFAULT '{}',
  manuscript_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'demo',
  model TEXT,
  run_id TEXT,
  usage_json TEXT NOT NULL DEFAULT '{}',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS consultation_note (
  id INTEGER PRIMARY KEY,
  note_uid TEXT NOT NULL UNIQUE,
  record_uid TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  occurred_at REAL,
  note_key TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(record_uid, note_key)
);

CREATE TABLE IF NOT EXISTS research_artifact (
  id INTEGER PRIMARY KEY,
  artifact_uid TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  parent_uid TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL DEFAULT '',
  input_json TEXT NOT NULL DEFAULT '{}',
  context_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  source TEXT NOT NULL DEFAULT 'manual',
  created_at REAL NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops_reminder (
  id INTEGER PRIMARY KEY,
  reminder_uid TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  target_kind TEXT NOT NULL,
  target_uid TEXT NOT NULL,
  target_sub_id TEXT NOT NULL,
  due_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  row_version INTEGER NOT NULL DEFAULT 1,
  parent_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

'''


def ensure_tables(db):
    db.executescript(TABLES)
    for column, ddl in (('topic', "TEXT NOT NULL DEFAULT ''"),
                        ('status_json', "TEXT NOT NULL DEFAULT '{}'"),
                        ('context_json', "TEXT NOT NULL DEFAULT '{}'")):
        columns = {row[1] for row in db.execute('PRAGMA table_info(research_draft_version)')}
        if column not in columns:
            db.execute('ALTER TABLE research_draft_version ADD COLUMN %s %s' % (column, ddl))
    columns = {row[1] for row in db.execute('PRAGMA table_info(research_draft_version)')}
    if 'base_version' not in columns:
        db.execute('ALTER TABLE research_draft_version ADD COLUMN base_version INTEGER NOT NULL DEFAULT 0')
    columns = {row[1] for row in db.execute('PRAGMA table_info(research_draft_version)')}
    if 'legacy_snapshot' not in columns:
        db.execute('ALTER TABLE research_draft_version ADD COLUMN legacy_snapshot INTEGER NOT NULL DEFAULT 0')
    _ensure_column(db, 'account_profile', 'version', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(db, 'content_task', 'formal', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(db, 'content_task', 'strategy_version', 'INTEGER')
    _ensure_column(db, 'content_task', 'strategy_summary', "TEXT NOT NULL DEFAULT ''")
    _ensure_column(db, 'content_task', 'strategy_snapshot_json', "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(db, 'pain_bank', 'evidence', "TEXT NOT NULL DEFAULT ''")
    _ensure_column(db, 'topic_candidates', 'batch_id', "TEXT NOT NULL DEFAULT ''")
    _ensure_column(db, 'content_version', 'plan_json', "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(db, 'content_version', 'suggestion_ids_json', "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(db, 'content_version', 'suggestion_snapshot_json', "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(db, 'reference_deconstruction', 'source_name', "TEXT NOT NULL DEFAULT ''")
    for column, definition in (
            ('reference_ids_json', "TEXT NOT NULL DEFAULT '[]'"),
            ('reference_snapshot_json', "TEXT NOT NULL DEFAULT '[]'"),
            ('pain_ids_json', "TEXT NOT NULL DEFAULT '[]'"),
            ('pain_snapshot_json', "TEXT NOT NULL DEFAULT '[]'")):
        _ensure_column(db, 'content_version', column, definition)


def _ensure_column(db, table, column, definition):
    columns = [row[1] for row in db.execute('PRAGMA table_info(' + table + ')')]
    if column not in columns:
        db.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, column, definition))


def _validated_beats(beats, label='稿件'):
    if not isinstance(beats, list) or not beats:
        raise ValueError(label + '必须是非空数组')
    cleaned = []
    for offset, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            raise ValueError('%s第 %d 段不是对象' % (label, offset))
        kind = beat.get('beat')
        text = beat.get('text')
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError('%s第 %d 段缺少 beat 名称' % (label, offset))
        if not isinstance(text, str) or not text.strip():
            raise ValueError('%s第 %d 段 text 为空' % (label, offset))
        ids = beat.get('fact_ids')
        if ids is not None and (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)):
            raise ValueError('%s第 %d 段 fact_ids 必须是字符串数组' % (label, offset))
        cleaned.append({'beat': kind.strip(), 'text': text.strip(), 'fact_ids': list(ids or [])})
    return cleaned


def _selection_ids(items):
    ids = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError('资料快照格式无效')
        try:
            ids.append(int(item.get('id')))
        except (TypeError, ValueError):
            raise ValueError('资料快照缺少 ID')
    return ids


def _validated_selection(reference_ids, reference_snapshot, pain_ids, pain_snapshot):
    reference_ids = [int(x) for x in (reference_ids or [])]
    pain_ids = [int(x) for x in (pain_ids or [])]
    reference_snapshot = reference_snapshot if isinstance(reference_snapshot, list) else []
    pain_snapshot = pain_snapshot if isinstance(pain_snapshot, list) else []
    if _selection_ids(reference_snapshot) != reference_ids:
        raise ValueError('参考 ID 与快照不一致')
    if _selection_ids(pain_snapshot) != pain_ids:
        raise ValueError('痛点 ID 与快照不一致')
    return reference_ids, reference_snapshot, pain_ids, pain_snapshot


def _strategy_summary(data):
    parts = []
    for key in ('direction', 'audience'):
        value = str(data.get(key) or '').strip()
        if value:
            parts.append(value)
    exclusions = str(data.get('exclusions') or '').strip()
    if exclusions:
        parts.append('排除：' + exclusions)
    return ' · '.join(parts)[:300]


def _check_formal(db, strategy_version):
    row = db.execute('SELECT confirmed,version,data FROM account_profile WHERE id=1').fetchone()
    if not row or not row['confirmed']:
        raise ValueError('账号策略未确认，不能保存正式任务')
    if strategy_version is None or strategy_version == '':
        raise ValueError('正式任务必须提交策略版本')
    try:
        requested = int(strategy_version)
    except (TypeError, ValueError):
        raise ValueError('策略版本无效')
    if requested != int(row['version']):
        raise ValueError('策略版本已变化，请刷新后重试')
    return int(row['version']), json.loads(row['data'] or '{}')


def _validate_formal_plan(db, plan, strategy_version):
    if not isinstance(plan, dict):
        raise ValueError('正式任务必须绑定选题计划')
    combo_uid = str(plan.get('combo_uid') or '').strip()
    candidate_id = plan.get('candidate_id')
    if not combo_uid or candidate_id is None:
        raise ValueError('正式任务必须绑定组合与候选')
    combo = db.execute(
        'SELECT * FROM topic_combo WHERE combo_uid=? AND archived=0 ORDER BY version DESC LIMIT 1',
        (combo_uid,)).fetchone()
    if not combo:
        raise ValueError('组合不存在')
    if int(combo['strategy_version']) != int(strategy_version):
        raise ValueError('组合与当前策略版本不一致')
    snapshot = json.loads(combo['snapshot_json'] or '[]')
    candidate = next((item for item in snapshot if int(item.get('id') or 0) == int(candidate_id)), None)
    if not candidate:
        raise ValueError('候选不属于该组合')
    if candidate.get('expires_at') and str(candidate['expires_at']) < time.strftime('%Y-%m-%d'):
        raise ValueError('实验候选已过期')
    return {
        'combo_uid': combo_uid,
        'candidate_id': int(candidate_id),
        'topic_snapshot': candidate,
        'strategy_version': int(strategy_version),
        'references': plan.get('references') or [],
        'pains': plan.get('pains') or [],
        'facts': plan.get('facts') or [],
        'proof': str(plan.get('proof') or ''),
        'duration_seconds': plan.get('duration_seconds'),
        'shots': plan.get('shots') or [],
        'next_action': str(plan.get('next_action') or ''),
        'missing': plan.get('missing') or [],
    }


def _parse_time(value):
    text = str(value or '').strip()
    if not text:
        raise ValueError('缺少时间')
    text = text.replace('Z', '+0000')
    text = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', text)
    text = re.sub(r'\.\d+', '', text)
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%S%z')
    except ValueError:
        raise ValueError('时间必须带时区，格式如 2026-10-17T10:00:00+08:00')


def _validate_link(platform, url, post_id):
    text = str(url or '').strip()
    if not text.startswith(('http://', 'https://')):
        raise ValueError('链接必须是 http(s) 地址')
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or '').lower()
    path = parsed.path or ''
    if not host:
        raise ValueError('链接缺少有效主机')
    douyin_hosts = {'douyin.com', 'www.douyin.com', 'v.douyin.com'}
    xhs_hosts = {'xiaohongshu.com', 'www.xiaohongshu.com', 'v.xiaohongshu.com'}
    if platform == 'dy':
        if host in douyin_hosts:
            match = re.search(r'/video/([^/?#]+)', path)
            if match and match.group(1) != str(post_id):
                raise ValueError('链接中的作品 ID 与填写不一致')
        elif host in xhs_hosts:
            raise ValueError('链接平台与所选平台不一致')
        else:
            raise ValueError('无法确认的链接，请填写标准作品链接')
    elif platform == 'xhs':
        if host in xhs_hosts:
            match = re.search(r'/(?:explore|discovery/item)/([^/?#]+)', path)
            if match and match.group(1) != str(post_id):
                raise ValueError('链接中的作品 ID 与填写不一致')
        elif host in douyin_hosts:
            raise ValueError('链接平台与所选平台不一致')
        else:
            raise ValueError('无法确认的链接，请填写标准作品链接')
    else:
        raise ValueError('不支持的平台')


def _public_review_input(input_data):
    public = dict(input_data or {})
    frames = []
    for item in (input_data or {}).get('frames') or []:
        if isinstance(item, dict):
            frames.append({'frame': item.get('frame'), 'at': item.get('at'),
                           'sha256': item.get('sha256')})
    public['frames'] = frames
    return public


def _public_review_scope(scope, full=False):
    scope = scope or {}
    transcript = scope.get('transcript') or {}
    public = {'duration': scope.get('duration'),
              'frames': [{'frame': item.get('frame'), 'at': item.get('at'), 'sha256': item.get('sha256')}
                         for item in scope.get('frames') or [] if isinstance(item, dict)],
              'transcript': {'source': transcript.get('source') or 'none'},
              'transcript_complete': bool(scope.get('transcript_complete')),
              'model_hears_audio': bool(scope.get('model_hears_audio')),
              'full_view': bool(scope.get('full_view'))}
    if full:
        public['transcript']['text'] = transcript.get('text') or ''
    return public


class OpsStore:
    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def get_strategy(self):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM account_profile WHERE id=1').fetchone()
        if not row:
            return {'data': {}, 'confirmed': 0, 'version': 0, 'updated_at': 0, 'provenance': ''}
        item = dict(row)
        item['data'] = json.loads(item.get('data') or '{}')
        return item

    def save_strategy(self, data, provenance='', expected_version=None, database=None):
        if not isinstance(data, dict):
            raise ValueError('策略内容格式无效')
        if expected_version is None:
            raise ValueError('缺少策略版本')
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise ValueError('版本号无效')
        now = time.time()
        payload = json.dumps(data, ensure_ascii=False)
        with (closing(self.connect()) if database is None else nullcontext(database)) as db:
            if database is None:
                db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT version FROM account_profile WHERE id=1').fetchone()
            current = int(row['version']) if row else 0
            if expected_version != current:
                raise ValueError('策略版本已变化，请刷新后核对')
            version = current + 1
            if row:
                db.execute(
                    'UPDATE account_profile SET data=?,confirmed=0,provenance=?,version=?,updated_at=? WHERE id=1',
                    (payload, str(provenance or '')[:200], version, now))
            else:
                db.execute(
                    'INSERT INTO account_profile(id,data,confirmed,provenance,version,updated_at) VALUES(1,?,?,?,?,?)',
                    (payload, 0, str(provenance or '')[:200], version, now))
            if database is None:
                db.commit()
            else:
                return dict(db.execute('SELECT * FROM account_profile WHERE id=1').fetchone())
        return self.get_strategy()

    def confirm_strategy(self, expected_version):
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise ValueError('版本号无效')
        with closing(self.connect()) as db:
            updated = db.execute(
                'UPDATE account_profile SET confirmed=1 WHERE id=1 AND version=?', (expected_version,))
            if updated.rowcount != 1:
                raise ValueError('策略版本已变化，请刷新后重试')
            db.commit()
        return self.get_strategy()

    def save_candidates(self, batch_id, candidates):
        now = time.time()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            for item in candidates:
                db.execute(
                    'INSERT INTO topic_candidates(topic_id,lane,strategy_id,signal_ids,data,batch_id,created_at) '
                    'VALUES(?,?,?,?,?,?,?)',
                    (item.get('topic_id'), item.get('lane'), int(item.get('strategy_version') or 0),
                     json.dumps([s.get('id') for s in item.get('signals') or []], ensure_ascii=False),
                     json.dumps(dict(item, batch_id=batch_id), ensure_ascii=False), batch_id, now))
            db.commit()
        return self.get_candidates(batch_id)

    def get_candidates(self, batch_id):
        with closing(self.connect()) as db:
            rows = db.execute(
                'SELECT * FROM topic_candidates WHERE batch_id=? AND archived=0 ORDER BY id',
                (batch_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            data = json.loads(item['data'] or '{}')
            item['data'] = data
            item['signal_ids'] = json.loads(item['signal_ids'] or '[]')
            merged = dict(data)
            merged.update({'id': row['id'], 'batch_id': row['batch_id'], 'lane': row['lane'],
                           'strategy_version': row['strategy_id'], 'signal_ids': item['signal_ids']})
            result.append(merged)
        return result

    def save_combo(self, combo_uid, business_date, strategy_version, conservative_ids, experimental_ids,
                   snapshot, expected_version=0):
        now = time.time()
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise ValueError('组合版本无效')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            strategy = db.execute('SELECT confirmed,version FROM account_profile WHERE id=1').fetchone()
            if not strategy or not strategy['confirmed'] or int(strategy['version']) != int(strategy_version):
                raise ValueError('策略已改版或未确认，请重新选择选题')
            row = db.execute(
                'SELECT id,combo_uid,version FROM topic_combo WHERE business_date=? AND archived=0 '
                'ORDER BY version DESC LIMIT 1', (str(business_date),)).fetchone()
            if row and str(row['combo_uid']) != str(combo_uid):
                raise ValueError('当日组合已存在，请刷新后使用原组合')
            current = int(row['version']) if row else 0
            if expected_version != current:
                raise ValueError('组合版本已变化，请刷新后重试')
            version = current + 1
            if row:
                db.execute(
                    'UPDATE topic_combo SET strategy_version=?,conservative_ids=?,experimental_ids=?,'
                    'snapshot_json=?,version=?,created_at=? WHERE id=?',
                    (int(strategy_version), json.dumps(conservative_ids), json.dumps(experimental_ids),
                     json.dumps(snapshot, ensure_ascii=False), version, now, row['id']))
            else:
                db.execute(
                    'INSERT INTO topic_combo(combo_uid,business_date,strategy_version,conservative_ids,'
                    'experimental_ids,snapshot_json,version,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (str(combo_uid), str(business_date), int(strategy_version),
                     json.dumps(conservative_ids), json.dumps(experimental_ids),
                     json.dumps(snapshot, ensure_ascii=False), version, now))
            db.commit()
        return self.get_combo(business_date)

    def get_combo_by_uid(self, combo_uid):
        with closing(self.connect()) as db:
            row = db.execute(
                'SELECT * FROM topic_combo WHERE combo_uid=? AND archived=0 ORDER BY version DESC LIMIT 1',
                (str(combo_uid),)).fetchone()
        if not row:
            return None
        item = dict(row)
        for key in ('conservative_ids', 'experimental_ids', 'snapshot_json'):
            item[key] = json.loads(item[key] or '[]')
        return item

    def get_combo(self, business_date=None):
        with closing(self.connect()) as db:
            if business_date:
                row = db.execute(
                    'SELECT * FROM topic_combo WHERE business_date=? AND archived=0 '
                    'ORDER BY version DESC LIMIT 1', (str(business_date),)).fetchone()
            else:
                row = db.execute(
                    'SELECT * FROM topic_combo WHERE archived=0 ORDER BY id DESC LIMIT 1').fetchone()
        if not row:
            return None
        item = dict(row)
        for key in ('conservative_ids', 'experimental_ids', 'snapshot_json'):
            item[key] = json.loads(item[key] or '[]')
        return item

    def _record_dict(self, row):
        item = dict(row)
        item['snapshot_json'] = json.loads(item['snapshot_json'] or '{}')
        return item

    def save_publish_record(self, task_uid, version, platform, platform_post_id, url,
                            published_at, source='manual', simulated=0):
        task_uid = str(task_uid or '').strip()
        platform = str(platform or '').strip()
        platform_post_id = str(platform_post_id or '').strip()
        if not task_uid or not platform or not platform_post_id:
            raise ValueError('登记缺少任务、平台或作品 ID')
        if not published_at:
            raise ValueError('缺少发布时间')
        if platform not in ('dy', 'xhs'):
            raise ValueError('不支持的平台')
        _parse_time(published_at)
        _validate_link(platform, url, platform_post_id)
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise ValueError('版本号无效')
        now = time.time()
        normalized = str(url or '').split('#')[0].split('?')[0].rstrip('/')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute(
                'SELECT * FROM publish_record WHERE platform=? AND platform_post_id=? AND archived=0',
                (platform, platform_post_id)).fetchall()
            for row in existing:
                if row['task_uid'] == task_uid and int(row['version']) == version:
                    if int(row['simulated']) != int(bool(simulated)):
                        raise ValueError('该作品已有另一身份的登记，不能交叉重试')
                    return self._record_dict(row)
                raise ValueError('该作品已登记到其他任务/版本')
            task = db.execute('SELECT * FROM content_task WHERE task_uid=? AND archived=0',
                              (task_uid,)).fetchone()
            if not task:
                raise ValueError('任务不存在')
            if task['data_source'] == 'agent_test' and not simulated:
                raise ValueError('Agent 隔离测试稿不能登记为真实发布')
            if int(task['approved_version'] or 0) != version:
                raise ValueError('只能登记当前已批准的稿件版本')
            item = db.execute('SELECT * FROM content_version WHERE task_id=? AND version=?',
                              (task['id'], version)).fetchone()
            if not item:
                raise ValueError('稿件版本不存在')
            snapshot = {
                'task_uid': task_uid, 'version': version,
                'approved_version': task['approved_version'], 'approved_at': task['approved_at'],
                'product': task['product'], 'audience': task['audience'],
                'beats': json.loads(item['human_beats_json'] or '[]'),
                'plan': json.loads(item['plan_json'] or '{}'),
                'strategy': json.loads(task['strategy_snapshot_json'] or '{}'),
                'formal': task['formal'],
            }
            record_uid = uuid.uuid4().hex[:12]
            db.execute(
                'INSERT INTO publish_record(record_uid,task_uid,version,snapshot_json,platform,'
                'platform_post_id,url,normalized_url,published_at,registered_at,simulated,source) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (record_uid, task_uid, version, json.dumps(snapshot, ensure_ascii=False),
                 platform, platform_post_id, str(url or ''), normalized, published_at, now,
                 int(bool(simulated)), str(source or 'manual')[:40]))
            db.commit()
            return self.get_publish_record(record_uid)

    def get_publish_record(self, record_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM publish_record WHERE record_uid=? AND archived=0',
                             (str(record_uid),)).fetchone()
        if not row:
            raise ValueError('登记不存在')
        return self._record_dict(row)

    def list_publish_records(self, include_simulated=False):
        with closing(self.connect()) as db:
            query = 'SELECT * FROM publish_record WHERE archived=0'
            if not include_simulated:
                query += ' AND simulated=0'
            rows = db.execute(query + ' ORDER BY id DESC LIMIT 200').fetchall()
        return [self._record_dict(row) for row in rows]

    def save_metric_snapshot(self, record_uid, snapshot_key, metrics, source='manual',
                             collected_at=None, definition='累计值', simulated=0):
        record = self.get_publish_record(record_uid)
        if int(record['simulated']) != int(bool(simulated)):
            raise ValueError('真实/演练身份不一致')
        if not isinstance(metrics, dict):
            raise ValueError('指标格式无效')
        cleaned = {}
        for key in ('plays', 'likes', 'comments', 'favorites', 'inquiries'):
            value = metrics.get(key)
            if value is None or value == '':
                cleaned[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('指标必须是非负整数或留空')
            cleaned[key] = value
        if all(value is None for value in cleaned.values()):
            raise ValueError('没有已知指标，未生成快照')
        if not collected_at:
            raise ValueError('缺少采集时间')
        collected = _parse_time(collected_at)
        if collected < _parse_time(record['published_at']):
            raise ValueError('采集时间不能早于发布时间')
        source_text = str(source or 'manual')[:40]
        definition_text = str(definition or '累计值')[:60]
        snapshot_key = str(snapshot_key or '').strip()
        if not snapshot_key:
            raise ValueError('缺少快照标识')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute(
                'SELECT * FROM metric_snapshot WHERE record_uid=? AND snapshot_key=? AND archived=0',
                (str(record_uid), snapshot_key)).fetchone()
            if existing:
                same = (json.loads(existing['metrics_json'] or '{}') == cleaned
                        and str(existing['collected_at']) == str(collected_at)
                        and str(existing['source']) == source_text
                        and str(existing['definition']) == definition_text)
                if same:
                    return dict(existing)
                raise ValueError('同一快照标识已存在不同内容')
            cursor = db.execute(
                'INSERT INTO metric_snapshot(record_uid,snapshot_key,metrics_json,source,collected_at,'
                'definition,created_at,simulated) VALUES(?,?,?,?,?,?,?,?)',
                (str(record_uid), snapshot_key, json.dumps(cleaned, ensure_ascii=False),
                 source_text, collected_at, definition_text,
                 time.time(), int(bool(simulated))))
            db.commit()
            return dict(db.execute('SELECT * FROM metric_snapshot WHERE id=?',
                                   (cursor.lastrowid,)).fetchone())

    def list_metric_snapshots(self, record_uid):
        with closing(self.connect()) as db:
            rows = db.execute(
                'SELECT * FROM metric_snapshot WHERE record_uid=? AND archived=0 '
                'ORDER BY collected_at, id', (str(record_uid),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['metrics'] = json.loads(item['metrics_json'] or '{}')
            result.append(item)
        result.sort(key=lambda item: _parse_time(item['collected_at']))
        return result

    def _insert_review(self, db, record_uid, review):
        if not isinstance(review, dict):
            raise ValueError('复盘格式无效')
        review_uid = uuid.uuid4().hex[:12]
        suggestions = [dict(item, id=review_uid + ':' + str(index))
                       for index, item in enumerate(review.get('suggestions') or [])]
        record = db.execute('SELECT simulated FROM publish_record WHERE record_uid=? AND archived=0',
                            (str(record_uid),)).fetchone()
        if not record:
            raise ValueError('登记不存在')
        if record['simulated']:
            raise ValueError('演练记录不能生成正式复盘')
        db.execute(
            'INSERT INTO review_record(review_uid,record_uid,snapshot_ids,data_json,observations_json,'
            'suggestions_json,created_at,simulated) VALUES(?,?,?,?,?,?,?,?)',
            (review_uid, str(record_uid), json.dumps(review.get('snapshot_ids') or []),
             json.dumps(review.get('data') or {}, ensure_ascii=False),
             json.dumps(review.get('observations') or [], ensure_ascii=False),
             json.dumps(suggestions, ensure_ascii=False), time.time(), int(record['simulated'])))
        return review_uid

    def save_review(self, record_uid, review):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            review_uid = self._insert_review(db, record_uid, review)
            db.commit()
        return self.get_review(review_uid)

    def build_conversion(self, body):
        from workflows import conversion_observation as core
        request = core.validate_request(body)
        if request['snapshot_id'] > 9223372036854775807:
            raise ValueError('指定指标快照不存在')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            record = db.execute('SELECT * FROM publish_record WHERE record_uid=?',
                                (request['record_uid'],)).fetchone()
            snapshot = db.execute('SELECT * FROM metric_snapshot WHERE id=?',
                                  (request['snapshot_id'],)).fetchone()
            if not record or not snapshot:
                raise ValueError('登记或指定指标快照不存在')
            snapshot = dict(snapshot)
            snapshot['metrics'] = json.loads(snapshot['metrics_json'] or '{}')
            ids = request['consultation_ids']
            notes = [dict(row) for row in db.execute(
                'SELECT * FROM consultation_note WHERE note_uid IN (' + ','.join('?' for _ in ids) + ')', ids)] if ids else []
            review = core.build_report(request, dict(record), snapshot, notes, time.time())
            json.dumps(review, ensure_ascii=False, allow_nan=False)
            review_uid = self._insert_review(db, request['record_uid'], review)
            db.commit()
        return self.get_review(review_uid)

    def get_review(self, review_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM review_record WHERE review_uid=? AND archived=0',
                             (str(review_uid),)).fetchone()
        if not row:
            raise ValueError('复盘不存在')
        item = dict(row)
        item['snapshot_ids'] = json.loads(item['snapshot_ids'] or '[]')
        item['data_json'] = json.loads(item['data_json'] or '{}')
        item['observations_json'] = json.loads(item['observations_json'] or '[]')
        item['suggestions_json'] = json.loads(item['suggestions_json'] or '[]')
        return item

    def list_reviews(self, record_uid=None):
        with closing(self.connect()) as db:
            if record_uid:
                rows = db.execute(
                    'SELECT * FROM review_record WHERE record_uid=? AND archived=0 AND simulated=0 '
                    'ORDER BY id DESC', (str(record_uid),)).fetchall()
            else:
                rows = db.execute(
                    'SELECT * FROM review_record WHERE archived=0 AND simulated=0 '
                    'ORDER BY id DESC LIMIT 100').fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['suggestions_json'] = json.loads(item['suggestions_json'] or '[]')
            item['observations_json'] = json.loads(item['observations_json'] or '[]')
            item['snapshot_ids'] = json.loads(item['snapshot_ids'] or '[]')
            item['data_json'] = json.loads(item['data_json'] or '{}')
            result.append(item)
        return result

    def get_suggestion(self, suggestion_id):
        review_uid, _, index = str(suggestion_id or '').partition(':')
        try:
            index = int(index)
        except (TypeError, ValueError):
            raise ValueError('建议 ID 无效')
        review = self.get_review(review_uid)
        if review.get('simulated'):
            raise ValueError('演练建议不能使用')
        suggestions = review['suggestions_json']
        if index < 0 or index >= len(suggestions):
            raise ValueError('建议不存在')
        return {'id': suggestion_id, 'review_uid': review_uid, 'record_uid': review['record_uid'],
                'suggestion': suggestions[index], 'simulated': review['simulated']}

    def _load_suggestions(self, suggestion_ids):
        loaded = []
        for suggestion_id in suggestion_ids or []:
            item = self.get_suggestion(suggestion_id)
            if item.get('simulated'):
                raise ValueError('演练建议不能进入正式任务')
            loaded.append(item)
        return loaded

    def ops_dashboard(self, business_date=None):
        business_date = str(business_date or time.strftime('%Y-%m-%d'))
        try:
            datetime.datetime.strptime(business_date, '%Y-%m-%d')
        except ValueError:
            raise ValueError('业务日期无效')
        now = datetime.datetime.now().astimezone()
        read_at = now.isoformat(timespec='seconds')
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            task_rows = db.execute('SELECT * FROM content_task WHERE archived=0 ORDER BY id').fetchall()
            version_rows = db.execute(
                'SELECT * FROM content_version ORDER BY task_id, version').fetchall()
            record_rows = db.execute(
                'SELECT * FROM publish_record WHERE archived=0 AND simulated=0 ORDER BY id').fetchall()
            snapshot_rows = db.execute(
                'SELECT * FROM metric_snapshot WHERE archived=0 AND simulated=0 ORDER BY id').fetchall()
            review_rows = db.execute(
                'SELECT * FROM review_record WHERE archived=0 AND simulated=0 ORDER BY id').fetchall()
            combo_row = db.execute(
                'SELECT * FROM topic_combo WHERE business_date=? AND archived=0 '
                'ORDER BY version DESC LIMIT 1', (business_date,)).fetchone()
            strategy_row = db.execute('SELECT * FROM account_profile WHERE id=1').fetchone()
            db.execute('COMMIT')
        task_ids = {row['id'] for row in task_rows}
        version_rows = [row for row in version_rows if row['task_id'] in task_ids]
        versions_by_task = {}
        for row in version_rows:
            versions_by_task.setdefault(row['task_id'], {})[row['version']] = dict(row)
        records = []
        seen_works = set()
        for row in record_rows:
            key = (row['platform'], row['platform_post_id'])
            if key in seen_works:
                continue
            seen_works.add(key)
            records.append(self._record_dict(row))
        record_uids = {item['record_uid'] for item in records}
        review_rows = [row for row in review_rows if row['record_uid'] in record_uids]
        record_bindings = {(item['task_uid'], int(item['version'])) for item in records}
        snapshots_by_record = {}
        for row in snapshot_rows:
            item = dict(row)
            item['metrics'] = json.loads(item['metrics_json'] or '{}')
            item['_parsed'] = _parse_time(item['collected_at'])
            snapshots_by_record.setdefault(item['record_uid'], []).append(item)
        latest_by_record = {}
        for uid, items in snapshots_by_record.items():
            items.sort(key=lambda value: (value['_parsed'], value['id']))
            latest_by_record[uid] = items[-1]
        draft, pending, approved_unpublished = [], [], []
        for row in task_rows:
            task = dict(row)
            current = int(task['current_version'])
            version = versions_by_task.get(task['id'], {}).get(current)
            if not version:
                draft.append({'task_uid': task['task_uid'], 'version': current,
                              'reason': '缺少当前版本，待核对'})
                continue
            missing = json.loads(version['missing_json'] or '[]')
            approved = int(task['approved_version'] or 0)
            item = {'task_uid': task['task_uid'], 'version': current,
                    'formal': int(task['formal'] or 0), 'status': task['status'],
                    'missing': missing, 'approved_version': approved, 'product': task['product']}
            if task['status'] != 'ready' or missing:
                draft.append(item)
            elif approved != current:
                pending.append(item)
            elif (task['task_uid'], current) not in record_bindings:
                approved_unpublished.append(item)
        plans = []
        for row in task_rows:
            version = versions_by_task.get(row['id'], {}).get(int(row['current_version']))
            if not version:
                continue
            plan = json.loads(version['plan_json'] or '{}')
            if plan.get('combo_uid') or plan.get('candidate_id'):
                plans.append({'task_uid': row['task_uid'], 'version': version['version'], 'plan': plan})
        current_strategy = int(strategy_row['version'] or 0) if strategy_row else 0
        confirmed = bool(strategy_row and strategy_row['confirmed'])
        blockers = []
        plan_actions = []
        for item in plans:
            plan = item['plan']
            if int(plan.get('strategy_version') or 0) != current_strategy:
                blockers.append({'task_uid': item['task_uid'], 'version': item['version'],
                                 'reason': '计划绑定的策略版本与当前不一致'})
            topic = plan.get('topic_snapshot') or {}
            if topic.get('expires_at') and str(topic['expires_at']) < time.strftime('%Y-%m-%d'):
                blockers.append({'task_uid': item['task_uid'], 'version': item['version'],
                                 'reason': '实验候选已过期'})
            missing_plan = []
            if not (plan.get('shots') or []):
                missing_plan.append('镜头')
            if not plan.get('proof'):
                missing_plan.append('素材/证明')
            if not plan.get('next_action'):
                missing_plan.append('下一动作')
            if plan.get('duration_seconds') in (None, ''):
                missing_plan.append('目标时长')
            if missing_plan:
                plan_actions.append({'kind': 'plan_missing', 'task_uid': item['task_uid'],
                                     'version': item['version'],
                                     'reason': '计划缺：' + '、'.join(missing_plan),
                                     'target': '/script?task=%s&version=%s' % (
                                         item['task_uid'], item['version'])})
        combo = None
        if combo_row:
            combo = dict(combo_row)
            combo['conservative_ids'] = json.loads(combo['conservative_ids'] or '[]')
            combo['experimental_ids'] = json.loads(combo['experimental_ids'] or '[]')
            combo['snapshot_json'] = json.loads(combo['snapshot_json'] or '[]')
        if combo and int(combo.get('strategy_version') or 0) != current_strategy:
            blockers.append({'combo_uid': combo['combo_uid'],
                             'reason': '今日组合绑定的策略版本与当前不一致'})
        if combo:
            plan_candidates = {int(item['plan'].get('candidate_id') or 0) for item in plans}
            for item in combo['snapshot_json']:
                if int(item.get('id') or 0) not in plan_candidates:
                    expired = (item.get('expires_at')
                               and str(item['expires_at']) < time.strftime('%Y-%m-%d'))
                    if expired:
                        blockers.append({'combo_uid': combo['combo_uid'], 'candidate_id': item.get('id'),
                                         'reason': '实验候选已过期：' + (item.get('topic') or '')})
                    plan_actions.append({
                        'kind': 'continue_candidate', 'combo_uid': combo['combo_uid'],
                        'candidate_id': item.get('id'), 'topic': item.get('topic') or '',
                        'reason': '当日候选尚未产稿：' + (item.get('topic') or ''),
                        'target': '/script?combo=%s&candidate=%s' % (
                            combo['combo_uid'], item.get('id'))})
        used_ids = set()
        for row in version_rows:
            used_ids.update(json.loads(row['suggestion_ids_json'] or '[]'))
        suggestions = []
        for row in review_rows:
            review = dict(row)
            for item in json.loads(review['suggestions_json'] or '[]'):
                suggestions.append({'id': item.get('id'), 'review_uid': review['review_uid'],
                                    'record_uid': review['record_uid'], 'suggestion': item,
                                    'used': item.get('id') in used_ids})
        actions = []
        for item in draft:
            actions.append({'kind': 'fill_facts', 'task_uid': item['task_uid'], 'version': item['version'],
                            'reason': '缺资料/草稿', 'target': '/script?task=%s&version=%s' % (
                                item['task_uid'], item['version'])})
        for item in pending:
            actions.append({'kind': 'review', 'task_uid': item['task_uid'], 'version': item['version'],
                            'reason': '当前版本待审阅', 'target': '/script?task=%s&version=%s' % (
                                item['task_uid'], item['version'])})
        for item in approved_unpublished:
            actions.append({'kind': 'register', 'task_uid': item['task_uid'], 'version': item['version'],
                            'reason': '已审未登记发布', 'target': '/feedback?task=%s&version=%s' % (
                                item['task_uid'], item['version'])})
        for item in records:
            if item['record_uid'] not in latest_by_record:
                actions.append({'kind': 'metrics', 'record_uid': item['record_uid'],
                                'reason': '已登记但尚无指标', 'target': '/feedback?record=' + item['record_uid']})
        for item in suggestions:
            if not item['used']:
                actions.append({'kind': 'suggestion', 'review_uid': item['review_uid'],
                                'suggestion_id': item['id'], 'reason': '建议尚未用于稿件',
                                'target': '/feedback?record=%s&review=%s&suggestion=%s' % (
                                    item['record_uid'], item['review_uid'], item['id'])})
        actions.extend(plan_actions)
        latest_metrics = []
        for item in records:
            latest = latest_by_record.get(item['record_uid'])
            latest_metrics.append({
                'record_uid': item['record_uid'], 'platform': item['platform'],
                'platform_post_id': item['platform_post_id'], 'version': item['version'],
                'task_uid': item['task_uid'],
                'snapshot': ({'id': latest['id'], 'key': latest['snapshot_key'],
                              'collected_at': latest['collected_at'], 'source': latest['source'],
                              'definition': latest['definition'], 'metrics': latest['metrics']}
                             if latest else None),
            })
        strategy = {'configured': bool(strategy_row), 'confirmed': confirmed,
                    'version': current_strategy,
                    'affected_formal': [row['task_uid'] for row in task_rows
                                        if row['formal'] and (not confirmed or int(row['strategy_version'] or 0) != current_strategy)]}
        return {
            'read_at': read_at, 'business_date': business_date,
            'timezone': now.strftime('%z'),
            'definitions': {
                'draft': '当前版本 technical status 非 ready 或 missing 非空；task_uid+version',
                'pending_review': '非草稿且 approved_version != current_version；task_uid+version',
                'approved_unpublished': '非草稿、已批准当前版本、且无真实未归档登记；task_uid+version',
                'published': '真实未归档 (platform, platform_post_id) 去重；单位篇作品',
                'metrics': '每篇作品按采集时间取最新快照；不跨快照相加；null 不补 0',
                'suggestions': '未归档任务版本 suggestion_ids_json 引用过即视为已用于稿件',
            },
            'tasks': {'draft': draft, 'pending_review': pending,
                      'approved_unpublished': approved_unpublished,
                      'counts': {'draft': len(draft), 'pending_review': len(pending),
                                 'approved_unpublished': len(approved_unpublished)}},
            'published': {'count': len(records), 'records': records},
            'combo': combo, 'plans': plans, 'latest_metrics': latest_metrics,
            'suggestions': suggestions, 'actions': actions, 'strategy': strategy,
            'blockers': blockers,
            'diagnosis': {'status': 'insufficient',
                          'reason': '本批不建设健康评分；需真实运营数据与规则后再评估'},
        }

    def save_advice(self, status, context, source='demo', result=None, question='', parent_uid=None,
                    model=None, run_id=None, usage=None, duration_ms=0):
        advice_uid = uuid.uuid4().hex[:12]
        with closing(self.connect()) as db:
            db.execute('INSERT INTO ops_advice(advice_uid,status_json,context_json,result_json,question,parent_uid,'
                       'source,model,run_id,usage_json,duration_ms,version,created_at) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (advice_uid, json.dumps(status, ensure_ascii=False),
                        json.dumps(context, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False) if result is not None else None,
                        str(question or '')[:1000], parent_uid, str(source or 'demo'),
                        str(model or '')[:100] or None, str(run_id or '')[:40] or None,
                        json.dumps(usage or {}, ensure_ascii=False), int(duration_ms or 0),
                        1, time.time()))
            db.commit()
        return self.get_advice(advice_uid)

    def get_advice(self, advice_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM ops_advice WHERE advice_uid=? AND archived=0',
                             (str(advice_uid),)).fetchone()
        if not row:
            raise ValueError('建议不存在')
        item = dict(row)
        for key in ('status_json', 'context_json', 'usage_json'):
            item[key] = json.loads(item[key] or '{}')
        item['result_json'] = json.loads(item['result_json']) if item['result_json'] else None
        item['draft'] = item['result_json'] is None
        item['actions'] = self.list_actions(advice_uid)
        return item

    def list_advices(self, limit=30):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT * FROM ops_advice WHERE archived=0 ORDER BY id DESC LIMIT ?',
                              (int(limit),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['status_json'] = json.loads(item['status_json'] or '{}')
            item['context_json'] = json.loads(item['context_json'] or '{}')
            item['usage_json'] = json.loads(item['usage_json'] or '{}')
            item['result_json'] = json.loads(item['result_json']) if item['result_json'] else None
            item['draft'] = item['result_json'] is None
            result.append(item)
        return result

    def list_actions(self, advice_uid):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT action_id,status,note,version,updated_at FROM advice_action '
                              'WHERE advice_uid=? ORDER BY action_id', (str(advice_uid),)).fetchall()
        return [dict(row) for row in rows]

    def update_action(self, advice_uid, action_id, status, note='', expected_version=0):
        if status not in ('todo', 'doing', 'done'):
            raise ValueError('动作状态无效')
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise ValueError('版本号无效')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            advice = db.execute('SELECT result_json FROM ops_advice WHERE advice_uid=? AND archived=0',
                                (str(advice_uid),)).fetchone()
            if not advice:
                raise ValueError('建议不存在')
            result = json.loads(advice['result_json'] or '{}')
            allowed_ids = [str(item.get('id')) for item in (result.get('week_actions') or [])]
            if str(action_id) not in allowed_ids:
                raise ValueError('动作不属于该建议')
            row = db.execute('SELECT version FROM advice_action WHERE advice_uid=? AND action_id=?',
                             (str(advice_uid), str(action_id))).fetchone()
            current = int(row['version']) if row else 0
            if expected_version != current:
                raise ValueError('动作状态已被其他窗口更新，请刷新后重试')
            now = time.time()
            if row:
                db.execute('UPDATE advice_action SET status=?,note=?,version=?,updated_at=? '
                           'WHERE advice_uid=? AND action_id=?',
                           (status, str(note or '')[:500], current + 1, now, str(advice_uid), str(action_id)))
            else:
                db.execute('INSERT INTO advice_action(advice_uid,action_id,status,note,version,updated_at) '
                           'VALUES(?,?,?,?,?,?)',
                           (str(advice_uid), str(action_id), status, str(note or '')[:500], 1, now))
            db.commit()
        return self.get_advice(advice_uid)

    def save_draft(self, topic, status, context):
        draft_uid = uuid.uuid4().hex[:12]
        now = time.time()
        with closing(self.connect()) as db:
            db.execute('INSERT INTO research_draft(draft_uid,topic,status_json,context_json,archived,'
                       'created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                       (draft_uid, str(topic or '')[:200],
                        json.dumps(status, ensure_ascii=False),
                        json.dumps(context, ensure_ascii=False), 0, now, now))
            db.commit()
        return self.get_draft(draft_uid)

    def get_draft(self, draft_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM research_draft WHERE draft_uid=? AND archived=0',
                             (str(draft_uid),)).fetchone()
        if not row:
            raise ValueError('研究稿不存在')
        item = dict(row)
        item['status_json'] = json.loads(item['status_json'] or '{}')
        item['context_json'] = json.loads(item['context_json'] or '{}')
        item['versions'] = self.list_draft_versions(draft_uid)
        item['current_version'] = item['versions'][-1] if item['versions'] else None
        return item

    def list_drafts(self, limit=30):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT * FROM research_draft WHERE archived=0 ORDER BY updated_at DESC LIMIT ?',
                              (int(limit),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['status_json'] = json.loads(item['status_json'] or '{}')
            item['context_json'] = json.loads(item['context_json'] or '{}')
            item['versions'] = self.list_draft_versions(item['draft_uid'])
            item['version_count'] = len(item['versions'])
            result.append(item)
        return result

    def list_draft_versions(self, draft_uid):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT * FROM research_draft_version WHERE draft_uid=? ORDER BY version ASC',
                              (str(draft_uid),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['content_json'] = json.loads(item['content_json'] or '{}')
            item['usage_json'] = json.loads(item['usage_json'] or '{}')
            item['status_json'] = json.loads(item.get('status_json') or '{}')
            item['context_json'] = json.loads(item.get('context_json') or '{}')
            result.append(item)
        return result

    def add_draft_version(self, draft_uid, content, instruction='', source='demo', model=None,
                          run_id=None, usage=None, duration_ms=0, topic='', status=None, context=None,
                          base_version=0, legacy_snapshot=False):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            exists = db.execute('SELECT 1 FROM research_draft WHERE draft_uid=? AND archived=0',
                                (str(draft_uid),)).fetchone()
            if not exists:
                raise ValueError('研究稿不存在')
            row = db.execute('SELECT MAX(version) AS v FROM research_draft_version WHERE draft_uid=?',
                             (str(draft_uid),)).fetchone()
            version = int(row['v'] or 0) + 1
            db.execute('INSERT INTO research_draft_version(draft_uid,version,instruction,topic,status_json,'
                       'context_json,base_version,legacy_snapshot,content_json,source,model,run_id,usage_json,'
                       'duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (str(draft_uid), version, str(instruction or '')[:1000],
                        str(topic or '')[:200], json.dumps(status or {}, ensure_ascii=False),
                        json.dumps(context or {}, ensure_ascii=False), int(base_version or 0),
                        1 if legacy_snapshot else 0,
                        json.dumps(content, ensure_ascii=False), str(source or 'demo'),
                        str(model or '')[:100] or None, str(run_id or '')[:40] or None,
                        json.dumps(usage or {}, ensure_ascii=False), int(duration_ms or 0), time.time()))
            db.execute('UPDATE research_draft SET updated_at=? WHERE draft_uid=?',
                       (time.time(), str(draft_uid)))
            db.commit()
        return self.get_draft(draft_uid)

    def get_draft_version(self, draft_uid, version):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM research_draft_version WHERE draft_uid=? AND version=?',
                             (str(draft_uid), int(version))).fetchone()
        if not row:
            raise ValueError('版本不存在')
        item = dict(row)
        item['content_json'] = json.loads(item['content_json'] or '{}')
        item['usage_json'] = json.loads(item['usage_json'] or '{}')
        item['status_json'] = json.loads(item.get('status_json') or '{}')
        item['context_json'] = json.loads(item.get('context_json') or '{}')
        return item

    def update_draft(self, draft_uid, topic=None, status=None, context=None):
        sets, params = [], []
        if topic is not None:
            sets.append('topic=?')
            params.append(str(topic)[:200])
        if status is not None:
            sets.append('status_json=?')
            params.append(json.dumps(status, ensure_ascii=False))
        if context is not None:
            sets.append('context_json=?')
            params.append(json.dumps(context, ensure_ascii=False))
        if sets:
            sets.append('updated_at=?')
            params.append(time.time())
            params.append(str(draft_uid))
            with closing(self.connect()) as db:
                db.execute('UPDATE research_draft SET %s WHERE draft_uid=?' % ','.join(sets), params)
                db.commit()
        return self.get_draft(draft_uid)

    def save_media_review(self, goal, input_data, scope, context, manuscript, result,
                          source='demo', model=None, run_id=None, usage=None, duration_ms=0):
        review_uid = uuid.uuid4().hex[:12]
        draft_uid = (manuscript or {}).get('draft_uid')
        draft_version = (manuscript or {}).get('version')
        with closing(self.connect()) as db:
            db.execute('INSERT INTO media_review(review_uid,draft_uid,draft_version,goal,input_json,scope_json,'
                       'context_json,manuscript_json,result_json,source,model,run_id,usage_json,duration_ms,'
                       'created_at,archived) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)',
                       (review_uid, draft_uid, draft_version, str(goal)[:2000],
                        json.dumps(input_data, ensure_ascii=False), json.dumps(scope, ensure_ascii=False),
                        json.dumps(context, ensure_ascii=False), json.dumps(manuscript or {}, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False), str(source or 'demo'),
                        str(model or '')[:100] or None, str(run_id or '')[:40] or None,
                        json.dumps(usage or {}, ensure_ascii=False), int(duration_ms or 0), time.time()))
            db.commit()
        return self.get_media_review(review_uid)

    def get_media_review(self, review_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM media_review WHERE review_uid=? AND archived=0',
                             (str(review_uid),)).fetchone()
        if not row:
            raise ValueError('审阅记录不存在')
        item = dict(row)
        for key in ('input_json', 'scope_json', 'context_json', 'manuscript_json', 'usage_json'):
            item[key] = json.loads(item[key] or ('[]' if key == 'input_json' else '{}'))
        item['input_json'] = _public_review_input(item['input_json'])
        item['scope_json'] = _public_review_scope(item['scope_json'], full=True)
        item['result_json'] = json.loads(item['result_json'] or '{}')
        return item

    def list_media_reviews(self, limit=30):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT review_uid,draft_uid,draft_version,goal,scope_json,result_json,'
                              'source,model,created_at,archived FROM media_review WHERE archived=0 '
                              'ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            scope = json.loads(item.pop('scope_json') or '{}')
            result_json = json.loads(item.pop('result_json') or '{}')
            item['scope_json'] = _public_review_scope(scope)
            item['summary'] = str(result_json.get('summary') or '')
            result.append(item)
        return result

    def save_research_artifact(self, kind, topic, input_data, context, result, source='manual',
                               parent_uid=''):
        if kind not in ('research', 'topics', 'adaptation'):
            raise ValueError('研究记录类型无效')
        artifact_uid = uuid.uuid4().hex[:12]
        with closing(self.connect()) as db:
            db.execute('INSERT INTO research_artifact(artifact_uid,kind,parent_uid,topic,input_json,'
                       'context_json,result_json,source,created_at,archived) '
                       'VALUES(?,?,?,?,?,?,?,?,?,0)',
                       (artifact_uid, kind, str(parent_uid or ''), str(topic)[:2000],
                        json.dumps(input_data, ensure_ascii=False),
                        json.dumps(context, ensure_ascii=False),
                        json.dumps(result or {}, ensure_ascii=False),
                        str(source or 'manual')[:20], time.time()))
            db.commit()
        return self.get_research_artifact(artifact_uid)

    def get_research_artifact(self, artifact_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM research_artifact WHERE artifact_uid=? AND archived=0',
                             (str(artifact_uid),)).fetchone()
        if not row:
            raise ValueError('研究记录不存在')
        item = dict(row)
        for key in ('input_json', 'context_json', 'result_json'):
            item[key] = json.loads(item[key] or '{}')
        return item

    def list_research_artifacts(self, kind='research', limit=30):
        with closing(self.connect()) as db:
            rows = db.execute(
                'SELECT artifact_uid,kind,parent_uid,topic,result_json,source,created_at '
                'FROM research_artifact WHERE archived=0 AND kind=? ORDER BY id DESC LIMIT ?',
                (str(kind), int(limit))).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            result_json = json.loads(item.pop('result_json') or '{}')
            item['summary'] = str(result_json.get('summary') or '')
            item['analyzed'] = bool(result_json)
            result.append(item)
        return result

    def save_consultation(self, record_uid, text, source, occurred_at, note_key):
        if not isinstance(text, str):
            raise ValueError('咨询摘录必须是文本')
        text = text.strip()
        if not text:
            raise ValueError('请填写咨询摘录')
        if len(text) > 2000:
            raise ValueError('咨询摘录超过 2000 字上限')
        if not isinstance(note_key, str) or not note_key.strip():
            raise ValueError('请填写备注键')
        note_key = note_key.strip()
        if len(note_key) > 80:
            raise ValueError('备注键超过 80 字符上限')
        if not isinstance(source, str) or not source.strip():
            raise ValueError('来源说明必须是文本')
        source = source.strip()
        if len(source) > 40:
            raise ValueError('来源说明超过 40 字符上限')
        occurred = None
        if occurred_at is not None:
            if isinstance(occurred_at, bool) or not isinstance(occurred_at, (int, float)):
                raise ValueError('发生时间必须是有限数字时间戳')
            if not math.isfinite(occurred_at):
                raise ValueError('发生时间必须是有限数字时间戳')
            occurred = float(occurred_at)
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            record = db.execute('SELECT simulated FROM publish_record WHERE record_uid=? AND archived=0',
                                (str(record_uid),)).fetchone()
            if not record:
                raise ValueError('登记不存在或已归档')
            if int(record['simulated'] or 0):
                raise ValueError('演练登记不能记录咨询')
            row = db.execute('SELECT * FROM consultation_note WHERE record_uid=? AND note_key=?',
                             (str(record_uid), note_key)).fetchone()
            if row:
                if (row['text'] == text and row['source'] == source
                        and (row['occurred_at'] or 0) == (occurred or 0)):
                    return self.get_consultation(row['note_uid'])
                raise ValueError('同一记录下该备注键已存在且内容不同')
            note_uid = uuid.uuid4().hex[:12]
            db.execute('INSERT INTO consultation_note(note_uid,record_uid,text,source,occurred_at,note_key,'
                       'created_at) VALUES(?,?,?,?,?,?,?)',
                       (note_uid, str(record_uid), text, source, occurred, note_key, time.time()))
            db.commit()
        return self.get_consultation(note_uid)

    def get_consultation(self, note_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM consultation_note WHERE note_uid=?',
                             (str(note_uid),)).fetchone()
        if not row:
            raise ValueError('咨询记录不存在')
        return dict(row)

    def list_consultations(self, record_uid=None):
        with closing(self.connect()) as db:
            if record_uid:
                rows = db.execute('SELECT * FROM consultation_note WHERE record_uid=? ORDER BY id ASC',
                                  (str(record_uid),)).fetchall()
            else:
                rows = db.execute('SELECT * FROM consultation_note ORDER BY id DESC LIMIT 100').fetchall()
        return [dict(row) for row in rows]

    def save_reference(self, title, result, model, post_id=None, source_name=''):
        if not isinstance(result, dict) or 'report' not in result:
            raise ValueError('参考拆解内容格式无效')
        if not isinstance(result['report'], dict):
            raise ValueError('参考拆解缺少分析报告')
        title = str(title or '').strip()[:200]
        model = str(model or '').strip()[:150]
        source_name = str(source_name or '').strip()[:200]
        payload = json.dumps(result, ensure_ascii=False)
        with closing(self.connect()) as db:
            cursor = db.execute(
                'INSERT INTO reference_deconstruction(post_id,title,source_type,report,model,source_name,created_at) '
                'VALUES(?,?,?,?,?,?,?)',
                (post_id, title, 'video_analysis', payload, model, source_name, time.time()))
            db.commit()
            return cursor.lastrowid

    def list_references(self):
        with closing(self.connect()) as db:
            rows = db.execute(
                'SELECT id,post_id,title,model,source_name,created_at FROM reference_deconstruction '
                'WHERE archived=0 ORDER BY id DESC LIMIT 200').fetchall()
        return [dict(r) for r in rows]

    def save_pain(self, pain, source='comment', related_post_id=None, frequency=1,
                  evidence='', evidence_role='audience_pain'):
        pain = str(pain or '').strip()
        if not pain or len(pain) > 500:
            raise ValueError('痛点描述需为1～500字')
        source = str(source or 'comment').strip()[:40]
        evidence = str(evidence or '').strip()[:1000]
        evidence_role = str(evidence_role or 'audience_pain').strip()[:40]
        if evidence_role not in ('audience_pain', 'comment_evidence', 'user_observation'):
            raise ValueError('证据类型无效')
        try:
            frequency = int(frequency)
        except (TypeError, ValueError):
            raise ValueError('频次无效')
        if not 1 <= frequency <= 1000000:
            raise ValueError('频次需为1～1000000')
        with closing(self.connect()) as db:
            cursor = db.execute(
                'INSERT INTO pain_bank(pain,source,evidence_role,frequency,related_post_id,evidence,created_at) '
                'VALUES(?,?,?,?,?,?,?)',
                (pain, source, evidence_role, frequency, related_post_id, evidence, time.time()))
            db.commit()
            return cursor.lastrowid

    def list_pains(self):
        with closing(self.connect()) as db:
            rows = db.execute(
                'SELECT id,pain,source,evidence_role,frequency,related_post_id,evidence,created_at '
                'FROM pain_bank WHERE archived=0 ORDER BY frequency DESC, id DESC LIMIT 500').fetchall()
        return [dict(r) for r in rows]

    def get_reference(self, ident):
        try:
            ident = int(ident)
        except (TypeError, ValueError):
            raise ValueError('参考 ID 无效')
        with closing(self.connect()) as db:
            row = db.execute(
                'SELECT * FROM reference_deconstruction WHERE id=? AND archived=0', (ident,)).fetchone()
        if not row:
            raise ValueError('参考不存在')
        item = dict(row)
        raw = json.loads(item['report'] or '{}')
        if isinstance(raw.get('report'), dict):
            item['report'] = raw['report']
            item['scope'] = raw.get('scope') or {}
            item['report_version'] = raw.get('version') or ''
        else:
            item['report'] = raw
        return item

    def get_pain(self, ident):
        try:
            ident = int(ident)
        except (TypeError, ValueError):
            raise ValueError('痛点 ID 无效')
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM pain_bank WHERE id=? AND archived=0', (ident,)).fetchone()
        if not row:
            raise ValueError('痛点不存在')
        return dict(row)

    def create_content_task(self, payload):
        product = str(payload.get('product') or '').strip()[:200]
        if not product:
            raise ValueError('缺少商品名称')
        model_beats = _validated_beats(payload.get('model_beats'), '模型原稿')
        human_raw = payload.get('human_beats')
        human_beats = _validated_beats(human_raw, '人工稿') if isinstance(human_raw, list) else model_beats
        facts = payload.get('facts') if isinstance(payload.get('facts'), list) else []
        references = payload.get('references') if isinstance(payload.get('references'), list) else []
        fact_ids = payload.get('fact_ids') if isinstance(payload.get('fact_ids'), list) else []
        missing = payload.get('missing') if isinstance(payload.get('missing'), list) else []
        reference_ids, reference_snapshot, pain_ids, pain_snapshot = _validated_selection(
            payload.get('reference_ids'), payload.get('reference_snapshot'),
            payload.get('pain_ids'), payload.get('pain_snapshot'))
        now = time.time()
        formal = 1 if payload.get('formal') else 0
        strategy_summary = ''
        strategy_snapshot = {}
        strategy_version = None
        plan = payload.get('plan') if isinstance(payload.get('plan'), dict) else {}
        suggestion_ids = payload.get('suggestion_ids') if isinstance(payload.get('suggestion_ids'), list) else []
        suggestion_snapshot = payload.get('suggestion_snapshot') if isinstance(payload.get('suggestion_snapshot'), list) else []
        if suggestion_ids:
            suggestion_snapshot = self._load_suggestions(suggestion_ids)
        elif suggestion_snapshot:
            raise ValueError('建议快照缺少建议 ID')
        task_uid = uuid.uuid4().hex[:12]
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            if formal:
                strategy_version, strategy_data = _check_formal(db, payload.get('strategy_version'))
                plan = _validate_formal_plan(db, payload.get('plan'), strategy_version)
                strategy_summary = _strategy_summary(strategy_data)
                strategy_snapshot = strategy_data
            cursor = db.execute(
                'INSERT INTO content_task(task_uid,product,audience,facts_json,references_json,source,model,'
                'usage_json,duration_ms,run_id,data_source,model_mode,status,formal,strategy_version,'
                'strategy_summary,strategy_snapshot_json,current_version,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (task_uid, product, str(payload.get('audience') or '')[:200],
                 json.dumps(facts, ensure_ascii=False), json.dumps(references, ensure_ascii=False),
                 str(payload.get('source') or '')[:40], str(payload.get('model') or '')[:100],
                 json.dumps(payload.get('usage') or {}, ensure_ascii=False),
                 payload.get('duration_ms'), str(payload.get('run_id') or '')[:40],
                 str(payload.get('data_source') or '')[:20], str(payload.get('model_mode') or '')[:20],
                 str(payload.get('status') or 'draft')[:20], formal, strategy_version,
                 strategy_summary, json.dumps(strategy_snapshot, ensure_ascii=False), 1, now, now))
            task_id = cursor.lastrowid
            db.execute(
                'INSERT INTO content_version(task_id,version,model_beats_json,human_beats_json,'
                'fact_ids_json,missing_json,run_id,reference_ids_json,reference_snapshot_json,'
                'pain_ids_json,pain_snapshot_json,plan_json,suggestion_ids_json,suggestion_snapshot_json,'
                'created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (task_id, 1, json.dumps(model_beats, ensure_ascii=False),
                 json.dumps(human_beats, ensure_ascii=False),
                 json.dumps(fact_ids, ensure_ascii=False), json.dumps(missing, ensure_ascii=False),
                 str(payload.get('run_id') or '')[:40],
                 json.dumps(reference_ids, ensure_ascii=False),
                 json.dumps(reference_snapshot, ensure_ascii=False),
                 json.dumps(pain_ids, ensure_ascii=False),
                 json.dumps(pain_snapshot, ensure_ascii=False),
                 json.dumps(plan, ensure_ascii=False),
                 json.dumps(suggestion_ids, ensure_ascii=False),
                 json.dumps(suggestion_snapshot, ensure_ascii=False),
                 now))
            db.commit()
        return self.get_content_task(task_uid)

    def append_content_version(self, task_uid, expected_version, human_beats, fact_ids=None, missing=None, run_id='',
                               reference_ids=None, reference_snapshot=None, pain_ids=None, pain_snapshot=None,
                               plan=None, suggestion_ids=None, suggestion_snapshot=None):
        human_beats = _validated_beats(human_beats, '人工稿')
        if isinstance(suggestion_ids, list) and suggestion_ids:
            suggestion_snapshot = self._load_suggestions(suggestion_ids)
        elif isinstance(suggestion_snapshot, list) and suggestion_snapshot:
            raise ValueError('建议快照缺少建议 ID')
        reference_ids, reference_snapshot, pain_ids, pain_snapshot = _validated_selection(
            reference_ids, reference_snapshot, pain_ids, pain_snapshot)
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise ValueError('版本号无效')
        now = time.time()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                'SELECT id,current_version,formal,strategy_version FROM content_task WHERE task_uid=? AND archived=0',
                (str(task_uid),)).fetchone()
            if not row:
                raise ValueError('任务不存在')
            if row['current_version'] != expected_version:
                raise ValueError('版本冲突：当前版本 %d，期望 %d' % (row['current_version'], expected_version))
            if row['formal']:
                _check_formal(db, row['strategy_version'])
            first = db.execute(
                'SELECT model_beats_json FROM content_version WHERE task_id=? AND version=1',
                (row['id'],)).fetchone()
            if not first:
                raise ValueError('任务缺少模型原稿')
            next_version = row['current_version'] + 1
            previous = db.execute(
                'SELECT plan_json,suggestion_ids_json,suggestion_snapshot_json FROM content_version '
                'WHERE task_id=? AND version=?', (row['id'], expected_version)).fetchone()
            previous_plan = json.loads((previous or {})['plan_json'] if previous else '{}') or {}
            previous_suggestion_ids = json.loads((previous or {})['suggestion_ids_json'] if previous else '[]') or []
            previous_suggestion_snapshot = json.loads(
                (previous or {})['suggestion_snapshot_json'] if previous else '[]') or []
            if row['formal']:
                effective = plan if isinstance(plan, dict) else previous_plan
                if (not isinstance(effective, dict)
                        or str(effective.get('combo_uid') or '') != str(previous_plan.get('combo_uid') or '')
                        or int(effective.get('candidate_id') or 0) != int(previous_plan.get('candidate_id') or 0)):
                    raise ValueError('人工编辑不能替换选题身份')
                validated = _validate_formal_plan(db, effective, row['strategy_version'])
                for key in ('shots', 'proof', 'next_action', 'duration_seconds'):
                    validated[key] = effective.get(key, validated.get(key))
                plan_payload = validated
            else:
                plan_payload = plan if isinstance(plan, dict) else previous_plan
            db.execute(
                'INSERT INTO content_version(task_id,version,model_beats_json,human_beats_json,'
                'fact_ids_json,missing_json,run_id,reference_ids_json,reference_snapshot_json,'
                'pain_ids_json,pain_snapshot_json,plan_json,suggestion_ids_json,suggestion_snapshot_json,'
                'created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (row['id'], next_version, first['model_beats_json'],
                 json.dumps(human_beats, ensure_ascii=False),
                 json.dumps(fact_ids or [], ensure_ascii=False),
                 json.dumps(missing or [], ensure_ascii=False),
                 str(run_id or '')[:40],
                 json.dumps(reference_ids or [], ensure_ascii=False),
                 json.dumps(reference_snapshot or [], ensure_ascii=False),
                 json.dumps(pain_ids or [], ensure_ascii=False),
                 json.dumps(pain_snapshot or [], ensure_ascii=False),
                 json.dumps(plan_payload, ensure_ascii=False),
                 json.dumps(suggestion_ids if isinstance(suggestion_ids, list) else previous_suggestion_ids,
                            ensure_ascii=False),
                 json.dumps(suggestion_snapshot if isinstance(suggestion_snapshot, list) else previous_suggestion_snapshot,
                            ensure_ascii=False),
                 now))
            updated = db.execute(
                'UPDATE content_task SET current_version=?,updated_at=?,approved_version=NULL,approved_at=NULL '
                'WHERE id=? AND current_version=?',
                (next_version, now, row['id'], row['current_version']))
            if updated.rowcount != 1:
                raise ValueError('版本冲突：任务已被修改，请刷新后重试')
            db.commit()
        return self.get_content_task(str(task_uid))

    def list_content_tasks(self):
        with closing(self.connect()) as db:
            rows = db.execute(
                'SELECT task_uid,product,current_version,approved_version,formal,strategy_version,updated_at '
                'FROM content_task WHERE archived=0 ORDER BY updated_at DESC LIMIT 100').fetchall()
        return [dict(r) for r in rows]

    def get_content_task(self, task_uid, version=None):
        with closing(self.connect()) as db:
            row = db.execute(
                'SELECT * FROM content_task WHERE task_uid=? AND archived=0', (str(task_uid),)).fetchone()
            if not row:
                raise ValueError('任务不存在')
            versions = [dict(r) for r in db.execute(
                'SELECT version,model_beats_json,human_beats_json,fact_ids_json,missing_json,run_id,'
                'reference_ids_json,reference_snapshot_json,pain_ids_json,pain_snapshot_json,plan_json,'
                'suggestion_ids_json,suggestion_snapshot_json,created_at '
                'FROM content_version WHERE task_id=? ORDER BY version', (row['id'],)).fetchall()]
        if version is not None:
            try:
                version = int(version)
            except (TypeError, ValueError):
                raise ValueError('版本号无效')
            versions = [item for item in versions if item['version'] == version]
            if not versions:
                raise ValueError('版本不存在')
        task = dict(row)
        task['facts'] = json.loads(task.pop('facts_json') or '[]')
        task['references'] = json.loads(task.pop('references_json') or '[]')
        task['usage'] = json.loads(task.pop('usage_json') or '{}')
        task['strategy_snapshot_json'] = json.loads(task.get('strategy_snapshot_json') or '{}')
        for item in versions:
            for key in ('model_beats_json', 'human_beats_json', 'fact_ids_json', 'missing_json',
                        'reference_ids_json', 'reference_snapshot_json', 'pain_ids_json', 'pain_snapshot_json',
                        'suggestion_ids_json', 'suggestion_snapshot_json'):
                item[key] = json.loads(item[key] or '[]')
            item['plan_json'] = json.loads(item.get('plan_json') or '{}')
        return {'task': task, 'versions': versions}

    def approve_content_task(self, task_uid, version):
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise ValueError('版本号无效')
        now = time.time()
        with closing(self.connect()) as db:
            updated = db.execute(
                'UPDATE content_task SET approved_version=?,approved_at=? '
                'WHERE task_uid=? AND current_version=? AND archived=0',
                (version, now, str(task_uid), version))
            if updated.rowcount != 1:
                raise ValueError('批准失败：只能批准当前版本')
            db.commit()
        return self.get_content_task(str(task_uid))

    def create_reminder_atomic(self, body):
        """同一 IMMEDIATE 事务内加载权威父对象、校验并 INSERT。"""
        from workflows import ops_reminders as core
        kind = body.get('target_kind') if isinstance(body, dict) else None
        uid = body.get('target_uid') if isinstance(body, dict) else None
        sub = body.get('target_sub_id') if isinstance(body, dict) else None
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if kind == 'advice_action':
                    row = db.execute('SELECT * FROM ops_advice WHERE advice_uid=? AND archived=0',
                                     (str(uid or ''),)).fetchone()
                    if not row:
                        raise ValueError('建议不存在或已归档')
                    parent = dict(row)
                    parent['result_json'] = json.loads(parent['result_json']) if parent.get('result_json') else None
                elif kind == 'draft_version':
                    if isinstance(sub, bool) or not isinstance(sub, int) or sub <= 0:
                        raise ValueError('研究稿版本必须是正整数')
                    draft = db.execute('SELECT * FROM research_draft WHERE draft_uid=? AND archived=0',
                                       (str(uid or ''),)).fetchone()
                    version = db.execute('SELECT * FROM research_draft_version WHERE draft_uid=? AND version=?',
                                         (str(uid or ''), sub)).fetchone()
                    if not draft or not version:
                        raise ValueError('研究稿或精确版本不存在')
                    parent = {'draft': dict(draft), 'version': dict(version)}
                else:
                    raise ValueError('绑定类型只能是 advice_action 或 draft_version')
                record = core.validate_create(body, parent, time.time(), uuid.uuid4().hex[:12])
                self.create_reminder(record, db)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.get_reminder(record['uid'])

    def create_reminder(self, record, db=None):
        own = db is None
        db = self.connect() if own else db
        try:
            if record.get('target_kind') == 'advice_action':
                row = db.execute('SELECT archived FROM ops_advice WHERE advice_uid=?',
                                 (record.get('target_uid'),)).fetchone()
                if not row or row['archived']:
                    raise ValueError('建议不存在或已归档')
            else:
                draft = db.execute('SELECT archived FROM research_draft WHERE draft_uid=?',
                                   (record.get('target_uid'),)).fetchone()
                version = db.execute('SELECT 1 FROM research_draft_version WHERE draft_uid=? AND version=?',
                                     (record.get('target_uid'), record.get('target_sub_id'))).fetchone()
                if not draft or draft['archived'] or not version:
                    raise ValueError('研究稿或精确版本不存在')
            db.execute(
                'INSERT INTO ops_reminder(reminder_uid,title,note,target_kind,target_uid,'
                'target_sub_id,due_at,status,row_version,parent_json,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (record['uid'], record['title'], record['note'], record['target_kind'],
                 record['target_uid'], json.dumps(record['target_sub_id'], ensure_ascii=False),
                 record['due_at'], record['status'], record['row_version'],
                 json.dumps(record.get('parent') or {}, ensure_ascii=False),
                 record['created_at'], record['updated_at']))
            db.commit()
        finally:
            if own:
                db.close()
        return self.get_reminder(record['uid'])

    def get_reminder(self, reminder_uid):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM ops_reminder WHERE reminder_uid=?',
                             (str(reminder_uid),)).fetchone()
        if not row:
            raise ValueError('提醒不存在')
        item = dict(row)
        item['target_sub_id'] = json.loads(item['target_sub_id'])
        item['parent'] = json.loads(item.pop('parent_json') or '{}')
        return item

    def list_reminders(self):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT * FROM ops_reminder ORDER BY due_at,id').fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item['target_sub_id'] = json.loads(item['target_sub_id'])
            item['parent'] = json.loads(item.pop('parent_json') or '{}')
            items.append(item)
        return items

    def update_reminder(self, reminder_uid, expected_row_version, patch, now):
        from workflows.ops_reminders import ReminderConflict
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM ops_reminder WHERE reminder_uid=?',
                             (str(reminder_uid),)).fetchone()
            if not row:
                raise ValueError('提醒不存在')
            if row['row_version'] != expected_row_version:
                raise ReminderConflict('提醒已被更新，请刷新后重试')
            sets, params = [], []
            for key in ('title', 'note', 'due_at', 'status'):
                if key in patch:
                    sets.append('%s=?' % key)
                    params.append(patch[key])
            sets.extend(['row_version=?', 'updated_at=?'])
            params.extend([expected_row_version + 1, now, str(reminder_uid),
                           expected_row_version])
            updated = db.execute('UPDATE ops_reminder SET %s WHERE reminder_uid=? AND row_version=?'
                                 % ','.join(sets), params)
            if updated.rowcount != 1:
                raise ReminderConflict('提醒已被更新，请刷新后重试')
            db.commit()
        return self.get_reminder(reminder_uid)
