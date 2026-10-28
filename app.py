"""Local-only radar MVP. Python standard library; no paid calls on startup."""
import argparse
import copy
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
import webbrowser
from contextlib import closing
from datetime import datetime, timezone

import topics
import reviews
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, unquote
from urllib.request import Request, urlopen
from catalog import Catalog, MAX_RESPONSE_BYTES, ResponseTooLarge
from free_tools import download_cached_video, imported_posts, cached_media_url, resolved_media_url, validate_media_url
from browser_collector import browser_posts
from ai_directions import AIDirections
from video_creative import VideoCreative, MAX_REQUEST_BYTES, MAX_VIDEO_BYTES, TASK_RULES
from agent_tasks import AgentTasks
from agent_loop import AgentLoop
from account_onboarding import AccountOnboarding
from local_asr import LocalASR
from client_credentials import CredentialVault
from ops import OpsStore, ensure_tables
from agent_bridge import (build_view_model, clear_workspace_config, empty_view_model,
                           read_workspace_config, save_workspace_config, validate_workspace)

# 复用 OPS 脚本工作流：发布包默认从包内 _ops 加载；开发模式保留 OPS_PROJECT_ROOT / D 盘默认。
def _executable_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


_APP_DIR = _executable_dir()
_RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', _APP_DIR))
def _resolve_ops_root(app_dir, frozen, env_value):
    release = frozen or (app_dir / 'release.marker').is_file()
    if release:
        if (app_dir / '_ops').is_dir():
            return str(app_dir / '_ops')
        return ''
    if env_value:
        return env_value
    return r'D:\自媒体运营\project'


OPS_PROJECT_ROOT = _resolve_ops_root(_APP_DIR, getattr(sys, 'frozen', False),
                                     os.environ.get('OPS_PROJECT_ROOT', '').strip())
if OPS_PROJECT_ROOT and OPS_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, OPS_PROJECT_ROOT)
try:
    from workflows import ops_reminders as reminders
    from workflows import conversion_observation as conversion
    from tools.facts import validate_facts, FactsError
    from tools.run_log import record as record_run
    from skills.topic_discovery import generate_topic_candidates
    from workflows.keyword_to_topics import run as run_topics
    from workflows.topic_to_script import run as run_script
    from workflows.ops_advice import build_advice_prompt, parse_advice, demo_advice, validate_status
    from workflows.research_draft import (validate_topic, build_draft_prompt, build_optimize_prompt,
                                           parse_draft, demo_draft, demo_optimize, to_markdown)
    from workflows.media_review import (validate_input, build_review_prompt, parse_review, demo_review)
    from workflows.industry_templates import (
        catalog as industry_catalog,
        validate_industry_code as validate_industry_code,
        validate_snapshot as validate_industry_snapshot,
        build_snapshot as build_industry_snapshot,
        render_prompt as render_industry_prompt,
        DEFAULT_CODE as DEFAULT_INDUSTRY_CODE)
    from workflows.draft_optimization import (
        parse_optimization as parse_draft_optimization,
        validate_request as validate_draft_optimization,
        freeze_base as freeze_draft_base,
        freeze_extras as freeze_draft_extras,
        build_messages as build_draft_optimization_messages,
        demo_result as demo_draft_optimization,
        parse_result as parse_draft_optimization_result,
        allowed_refs as draft_optimization_refs,
        version_payload as draft_optimization_payload,
        changes_markdown as draft_optimization_changes)
    from workflows.research import (validate_input as validate_research_input,
                                    build_research_prompt, parse_research, demo_research,
                                    ROLE_LABELS as RESEARCH_ROLE_LABELS,
                                    DEMAND_ROLES as TOPIC_DEMAND_ROLES,
                                    DEMAND_ROLE_LABELS as TOPIC_DEMAND_ROLE_LABELS,
                                    MAX_CANDIDATES as TOPIC_MAX_CANDIDATES,
                                    build_topics_prompt, parse_topics, demo_topics,
                                    validate_candidate as validate_topic_candidate,
                                    validate_adaptation_input, build_adaptation_prompt,
                                    parse_adaptation, demo_adaptation)
    from tools.llm_call import call_llm, LLMError
    OPS_IMPORT_ERROR = None
except Exception as exc:  # 缺项目/依赖时给出明确错误，不影响应用启动
    validate_facts = FactsError = run_topics = run_script = generate_topic_candidates = None
    build_advice_prompt = parse_advice = demo_advice = validate_status = None
    validate_research_input = build_research_prompt = parse_research = demo_research = None
    RESEARCH_ROLE_LABELS = {}
    TOPIC_DEMAND_ROLES = ()
    TOPIC_DEMAND_ROLE_LABELS = {}
    TOPIC_MAX_CANDIDATES = 0
    build_topics_prompt = parse_topics = demo_topics = None
    validate_topic_candidate = None
    validate_adaptation_input = build_adaptation_prompt = parse_adaptation = demo_adaptation = None
    industry_catalog = validate_industry_code = validate_industry_snapshot = None
    build_industry_snapshot = render_industry_prompt = None
    DEFAULT_INDUSTRY_CODE = 'generic'
    parse_draft_optimization = validate_draft_optimization = None
    freeze_draft_base = freeze_draft_extras = build_draft_optimization_messages = None
    demo_draft_optimization = parse_draft_optimization_result = None
    draft_optimization_refs = draft_optimization_payload = draft_optimization_changes = None
    call_llm = LLMError = None
    record_run = None
    OPS_IMPORT_ERROR = str(exc)

ROOT = _RESOURCE_DIR
BILLBOARD = '/api/v1/douyin/billboard/fetch_hot_total_video_list'
STATISTICS = '/api/v1/douyin/app/v3/fetch_video_statistics'
MAX_SCAN_COST = Decimal('0.006')


def number(value):
    if value is None or value == '':
        return None
    text = str(value).strip().replace(',', '').replace('+', '')
    multiplier = 10000 if '万' in text else 1000 if text.lower().endswith('k') else 1
    try:
        result = float(text.replace('万', '').rstrip('kK')) * multiplier
        return max(0, int(result)) if math.isfinite(result) else None
    except (ValueError, OverflowError):
        return None


def first(*values):
    return next((v for v in values if v is not None and v != ''), None)


def timestamp(value):
    value = number(value)
    if value and value > 100000000000:
        value //= 1000
    return value if value and 946684800 < value <= time.time() + 300 else None


def image_url(value):
    if isinstance(value, dict):
        value = first(value.get('url_default'), value.get('url'), value.get('url_list'))
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) and value.startswith('https://') else None


def normalize_douyin(raw):
    author = raw.get('author') or {}
    stats = raw.get('statistics') or {}
    video = raw.get('video') or {}
    ident = str(raw.get('aweme_id') or '')
    return dict(external_id=ident, platform='dy', title=raw.get('desc') or '无标题视频',
                author=author.get('nickname') or '作者信息缺失',
                published_at=timestamp(raw.get('create_time')),
                plays=number(stats.get('play_count')),
                likes=number(stats.get('digg_count')), saves=number(stats.get('collect_count')),
                comments=number(stats.get('comment_count')), followers=number(author.get('follower_count')),
                cover=image_url(video.get('cover')), duration=number(video.get('duration')),
                video_url=cached_media_url(video),
                url='https://www.douyin.com/video/' + ident if ident.isdigit() else None,
                tags=[], artwork='clean')


def normalize_xhs(raw):
    card = raw.get('note_card') or raw.get('note') or raw
    stats = card.get('interact_info') or card
    author = card.get('user') or {}
    ident = str(first(card.get('note_id'), card.get('id'), raw.get('id')) or '')
    return dict(external_id=ident, platform='xhs', title=first(card.get('display_title'), card.get('title'), card.get('desc')) or '无标题笔记',
                author=author.get('nickname') or '作者信息缺失',
                published_at=timestamp(first(card.get('time'), card.get('publish_time'))),
                likes=number(stats.get('liked_count')), saves=number(stats.get('collected_count')),
                comments=number(first(stats.get('comment_count'), stats.get('comments_count'))), followers=None,
                cover=image_url(card.get('cover')), duration=None, video_url=cached_media_url(card.get('video')),
                url='https://www.xiaohongshu.com/explore/' + ident if re.match(r'^[a-fA-F0-9]{24}$', ident) else None,
                tags=[], artwork='storage')


def normalize_billboard(raw):
    post = normalize_douyin(dict(aweme_id=raw['item_id'], desc=raw.get('item_title'),
        create_time=raw.get('publish_time'),
        author=dict(nickname=raw.get('nick_name'), follower_count=raw.get('fans_cnt')),
        statistics=dict(play_count=raw.get('play_cnt'), digg_count=raw.get('like_cnt')),
        video=dict(cover=raw.get('item_cover_url'), duration=raw.get('item_duration'))))
    post.update(video_url=image_url(raw.get('item_url')),
                source='TikHub 视频热榜 · 供应商返回的 play_cnt',
                plays_source='TikHub 视频热榜 play_cnt')
    return post


def extract_posts(payload, platform):
    """Only recognize content objects, never treat arbitrary nested IDs as posts."""
    found = {}

    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            if platform == 'dy' and node.get('item_id') and 'item_title' in node:
                if node.get('media_type') == 4:
                    post = normalize_billboard(node)
                    found[post['external_id']] = post
                return
            if platform == 'dy' and node.get('aweme_id') and ('desc' in node or 'video' in node):
                if node.get('images') or node.get('aweme_type') in (2, 68, 150):
                    return
                post = normalize_douyin(node)
                found[post['external_id']] = post
                return
            card = node.get('note_card') or node.get('note')
            if platform == 'xhs' and isinstance(card, dict) and first(card.get('note_id'), card.get('id'), node.get('id')):
                post = normalize_xhs(node)
                found[post['external_id']] = post
                return
            if platform == 'xhs' and node.get('note_id') and ('title' in node or 'desc' in node):
                post = normalize_xhs(node)
                found[post['external_id']] = post
                return
            for child in node.values():
                if isinstance(child, (list, dict)):
                    walk(child)

    walk(payload.get('data'))
    return list(found.values())


class Store:
    def __init__(self, path):
        self.path = str(path)
        with closing(self.connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS keywords(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, mode TEXT NOT NULL,
                    platform TEXT NOT NULL, external_id TEXT NOT NULL, data TEXT NOT NULL,
                    first_seen REAL NOT NULL, updated_at REAL NOT NULL,
                    saved INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
                    UNIQUE(mode,platform,external_id));
                CREATE TABLE IF NOT EXISTS matches(keyword_id INTEGER NOT NULL, post_id INTEGER NOT NULL,
                    UNIQUE(keyword_id,post_id));
                CREATE TABLE IF NOT EXISTS snapshots(post_id INTEGER NOT NULL, at REAL NOT NULL, likes INTEGER);
                CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, keyword_id INTEGER NOT NULL,
                    at REAL NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS list_clears(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                    mode TEXT NOT NULL, at REAL NOT NULL, ids TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
            ''')
            for table in ('posts', 'keywords'):
                if 'archived' not in {row['name'] for row in db.execute('PRAGMA table_info(' + table + ')')}:
                    db.execute('ALTER TABLE ' + table + ' ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
            ensure_tables(db)
            db.commit()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def add_keyword(self, name):
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError('关键词需为1～40个字符')
        with closing(self.connect()) as db:
            db.execute('INSERT OR IGNORE INTO keywords(name) VALUES(?)', (name,))
            ident = db.execute('SELECT id FROM keywords WHERE name=?', (name,)).fetchone()['id']
            db.execute('UPDATE keywords SET archived=0 WHERE id=?', (ident,))
            db.commit()
        return ident

    def put_posts(self, keyword_id, posts, mode):
        now = time.time()
        with closing(self.connect()) as db:
            for post in posts:
                if not post.get('external_id'):
                    continue
                args = (mode, post['platform'], post['external_id'])
                db.execute('INSERT OR IGNORE INTO posts(mode,platform,external_id,data,first_seen,updated_at) VALUES(?,?,?,?,?,?)',
                           args + (json.dumps(post, ensure_ascii=False), now, now))
                row = db.execute('SELECT id,data FROM posts WHERE mode=? AND platform=? AND external_id=?', args).fetchone()
                if not post.get('video_url'):
                    previous_url = json.loads(row['data']).get('video_url')
                    if previous_url:
                        try:
                            post = dict(post, video_url=validate_media_url(previous_url))
                        except ValueError:
                            pass
                db.execute('UPDATE posts SET data=?,updated_at=?,archived=0 WHERE id=?', (json.dumps(post, ensure_ascii=False), now, row['id']))
                db.execute('INSERT OR IGNORE INTO matches VALUES(?,?)', (keyword_id, row['id']))
                db.execute('INSERT INTO snapshots VALUES(?,?,?)', (row['id'], now, post.get('likes')))
            db.commit()

    def set_video_url(self, ident, url):
        url = validate_media_url(url)
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT data FROM posts WHERE id=? AND mode='live' AND archived=0", (ident,)).fetchone()
            if row is None:
                raise ValueError('视频已移除；未保存直链或下载')
            post = json.loads(row['data'])
            post['video_url'] = url
            db.execute('UPDATE posts SET data=?,updated_at=? WHERE id=?',
                       (json.dumps(post, ensure_ascii=False), time.time(), ident))
            db.commit()
            return dict(post, id=ident)

    def save(self, ident, saved, note):
        with closing(self.connect()) as db:
            cursor = db.execute('UPDATE posts SET saved=?,note=? WHERE id=?', (int(bool(saved)), str(note)[:2000], ident))
            if not cursor.rowcount:
                raise ValueError('内容不存在')
            db.commit()

    def state(self, mode):
        if mode not in ('demo', 'live'):
            raise ValueError('数据模式无效')
        with closing(self.connect()) as db:
            keywords = [dict(r) for r in db.execute('SELECT id,name FROM keywords WHERE archived=0 ORDER BY id')]
            posts = []
            for row in db.execute('SELECT * FROM posts WHERE mode=? AND archived=0 ORDER BY updated_at DESC,id', (mode,)):
                post = json.loads(row['data'])
                post.update(id=row['id'], saved=bool(row['saved']), note=row['note'],
                            first_seen=row['first_seen'], updated_at=row['updated_at'])
                post['keyword_ids'] = [r['keyword_id'] for r in db.execute('SELECT m.keyword_id FROM matches m JOIN keywords k ON k.id=m.keyword_id WHERE m.post_id=? AND k.archived=0', (row['id'],))]
                posts.append(post)
            last = db.execute('SELECT keyword_id,at,data FROM scans ORDER BY id DESC LIMIT 1').fetchone()
            scan = json.loads(last['data']) if last and mode == 'live' else None
            if scan is not None:
                scan.update(keyword_id=last['keyword_id'], at=last['at'])
            cleared = db.execute("SELECT id,kind,mode,at,ids FROM list_clears WHERE undone=0 AND (kind='keywords' OR mode=?) ORDER BY id DESC LIMIT 1", (mode,)).fetchone()
            last_clear = dict(id=cleared['id'], kind=cleared['kind'], mode=cleared['mode'], at=cleared['at'], count=len(json.loads(cleared['ids']))) if cleared else None
            return dict(keywords=keywords, posts=posts, last_scan=scan, last_clear=last_clear)

    def clear_list(self, kind, mode, expected_count=None):
        if kind not in ('videos', 'keywords') or mode not in ('live', 'demo'):
            raise ValueError('清空对象或数据模式无效')
        table = 'posts' if kind == 'videos' else 'keywords'
        condition = 'archived=0' + (' AND mode=?' if kind == 'videos' else '')
        params = (mode,) if kind == 'videos' else ()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            ids = [row['id'] for row in db.execute('SELECT id FROM ' + table + ' WHERE ' + condition, params)]
            if expected_count is not None and expected_count != len(ids):
                raise ValueError('列表数量已变化，请关闭对话框并重新确认清空范围')
            if not ids:
                return dict(count=0, id=None)
            cursor = db.execute('INSERT INTO list_clears(kind,mode,at,ids) VALUES(?,?,?,?)',
                                (kind, mode, time.time(), json.dumps(ids)))
            ident = cursor.lastrowid
            db.execute('UPDATE ' + table + ' SET archived=1 WHERE ' + condition, params)
            db.commit()
            return dict(count=len(ids), id=ident)

    def undo_clear(self, ident):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM list_clears WHERE id=? AND undone=0', (ident,)).fetchone()
            if not row:
                raise ValueError('没有可撤销的清空记录，请刷新页面')
            table = 'posts' if row['kind'] == 'videos' else 'keywords'
            count = 0
            for item in json.loads(row['ids']):
                count += db.execute('UPDATE ' + table + ' SET archived=0 WHERE id=? AND archived=1', (item,)).rowcount
            db.execute('UPDATE list_clears SET undone=1 WHERE id=?', (ident,))
            db.commit()
            return dict(count=count, kind=row['kind'])

    def record_scan(self, keyword_id, result):
        summary = {k: v for k, v in result.items() if k not in ('posts', '_response')}
        summary['count'] = len(result['posts'])
        with closing(self.connect()) as db:
            db.execute('INSERT INTO scans(keyword_id,at,data) VALUES(?,?,?)',
                       (keyword_id, time.time(), json.dumps(summary, ensure_ascii=False)))
            db.commit()

    def seed(self):
        with closing(self.connect()) as db:
            if db.execute("SELECT count(*) FROM posts WHERE mode='demo'").fetchone()[0]:
                return
        from demo import sample_posts
        for keyword, posts in sample_posts().items():
            self.put_posts(self.add_keyword(keyword), posts, 'demo')


def tikhub_json(path, key=None, body=None, params=None):
    headers = {'Content-Type': 'application/json', 'User-Agent': 'LocalRadar/0.2'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    url = 'https://api.tikhub.io' + path + ('?' + urlencode(params, doseq=True) if params else '')
    request = Request(url, data=json.dumps(body).encode('utf-8') if body is not None else None, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge()
            payload = json.loads(raw)
    except HTTPError as exc:
        detail = ''
        try:
            error = json.loads(exc.read(12000).decode('utf-8'))
            detail = first(error.get('message_zh'), error.get('detail'), error.get('message'))
            if not isinstance(detail, str):
                detail = ''
            if key:
                detail = detail.replace(key, '[密钥已隐藏]')
        except (ValueError, UnicodeError, AttributeError):
            pass
        raise ValueError('数据服务 HTTP {}：{}'.format(exc.code, detail[:240] or '请求被拒绝；已停止，不自动重试'))
    except (URLError, TimeoutError, OSError):
        raise ValueError('数据服务连接超时或不可达；已停止，不自动重试')
    except ResponseTooLarge:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('数据服务返回了无法识别的响应')
    if not isinstance(payload, dict) or payload.get('code') not in (0, 200, '200'):
        raise ValueError('数据服务未返回成功状态，请到供应商后台检查请求记录')
    return payload


def money(value):
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and amount >= 0:
            return amount
    except (InvalidOperation, ValueError):
        pass
    raise ValueError('无法核实赠送额度或接口价格；已停止')


def free_credit(key):
    account = tikhub_json('/api/v1/tikhub/user/get_user_info', key=key)
    return money((account.get('user_data') or {}).get('free_credit'))


def merge_play_counts(posts, payload):
    stats = {}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            ident = str(node.get('aweme_id') or '')
            if ident and 'play_count' in node:
                stats[ident] = number(node['play_count'])
            for item in node.values():
                if isinstance(item, (list, dict)):
                    walk(item)

    walk(payload.get('data'))
    for post in posts:
        if post['external_id'] in stats:
            post['plays'] = stats[post['external_id']]
            post['plays_source'] = 'TikHub APP V3 play_count'
            post['plays_checked_at'] = time.time()


def fetch_douyin_radar(key, keyword, probe_only=False):
    result = dict(platform='dy', posts=[], content_requests=0, cost_upper_bound='0.0000',
                  free_credit_before=None, free_credit_after=None, message='', probe_only=probe_only)
    spent = Decimal(0)
    costs = {}
    limit = Decimal('0.001') if probe_only else MAX_SCAN_COST

    def content_request(path, **kwargs):
        nonlocal spent
        available = free_credit(key)
        result['free_credit_after'] = format(available, '.4f')
        if available < costs[path] or result['content_requests'] >= (1 if probe_only else 6) or spent + costs[path] > limit:
            raise ValueError('赠送额度或本次请求预算不足；已停止后续请求')
        result['content_requests'] += 1
        spent += costs[path]
        result['cost_upper_bound'] = format(spent, '.4f')
        return tikhub_json(path, key=key, **kwargs)

    try:
        for path in ((BILLBOARD,) if probe_only else (BILLBOARD, STATISTICS)):
            info = tikhub_json('/api/v1/tikhub/user/get_endpoint_info', params={'endpoint': path}).get('data') or {}
            if info.get('allow_free_credit') not in (True, 1):
                raise ValueError('当前接口不接受赠送额度；已停止，不切换付费接口')
            costs[path] = money(info.get('endpoint_cost'))
        maximum = costs[BILLBOARD] + (0 if probe_only else 5 * costs[STATISTICS])
        if maximum > limit:
            raise ValueError('接口价格已超出本次 ${:.3f} 上限；已停止'.format(limit))
        before = free_credit(key)
        result['free_credit_before'] = format(before, '.4f')
        result['free_credit_after'] = result['free_credit_before']
        if before < maximum:
            raise ValueError('赠送额度不足本次最多 ${:.4f} 的预算；已停止'.format(maximum))
        payload = content_request(BILLBOARD, body=dict(page=1, page_size=10, date_window=168,
                                                      sub_type=1001, keyword='' if probe_only else keyword, tags=[]))
        result['_response'] = {k: payload[k] for k in ('code', 'request_id', 'router', 'data', 'cache_url') if k in payload}
        result['cache_url'] = payload.get('cache_url')
        upstream = payload.get('data') or {}
        if isinstance(upstream, dict) and isinstance(upstream.get('data'), dict):
            page = upstream['data'].get('page') or {}
            result['provider_total'] = number(page.get('total')) if isinstance(page, dict) else None
        posts = extract_posts(payload, 'dy')[:10]
        if not posts:
            if result.get('provider_total') == 0:
                result['message'] = '供应商热榜返回0条视频；未翻页或补查播放量。此结果不代表全站没有相关视频。'
            elif result.get('provider_total', 0):
                result['error'] = '供应商返回了内容，但本地解析尚未适配；已停止并保留原始响应。'
            else:
                result['message'] = '热榜未返回可识别的视频；已保留原始响应，未继续补查播放量。'
            return result
        result['posts'] = posts
        for post in posts:
            if post.get('plays') is not None:
                post['plays_checked_at'] = timestamp(upstream.get('extra', {}).get('now')) if isinstance(upstream, dict) else None
            if not post.get('source'):
                post['source'] = 'TikHub 近7天视频热榜'
        if probe_only:
            known = sum(p.get('plays') is not None for p in posts)
            result['message'] = '热榜返回 {} 个视频，其中 {} 个含榜单播放量；未调用播放量补查接口，已排除图文。'.format(len(posts), known)
            result['posts'].sort(key=lambda p: p.get('plays') if p.get('plays') is not None else -1, reverse=True)
            return result
        missing = [p for p in posts if p.get('plays') is None]
        for offset in range(0, len(missing), 2):
            batch = missing[offset:offset + 2]
            stats = content_request(STATISTICS, params={'aweme_ids': ','.join(p['external_id'] for p in batch)})
            merge_play_counts(batch, stats)
        result['free_credit_after'] = format(free_credit(key), '.4f')
        known = sum(p.get('plays') is not None for p in posts)
        result['message'] = '收录 {} 个视频，其中 {} 个返回播放量；未知值不参与高播放筛选。'.format(len(posts), known)
    except ValueError as exc:
        result['error'] = str(exc)
    result['posts'].sort(key=lambda p: p.get('plays') if p.get('plays') is not None else -1, reverse=True)
    return result


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _ops_post(post):
    return {
        'id': post.get('id'),
        'title': post.get('title') or '',
        'plays': post.get('plays'),
        'likes': post.get('likes'),
        'tags': post.get('tags') or [],
    }


def _reference(post):
    return {
        'id': post.get('id'),
        'title': post.get('title') or '',
        'plays': post.get('plays'),
        'likes': post.get('likes'),
        'url': post.get('url') or '',
    }


def _log_script(data_dir, keyword, product, model_mode, data_mode, status, error, started, **meta):
    if record_run is None:
        return None, 'unavailable'
    try:
        entry = record_run(
            'script',
            {'keyword': keyword, 'product': product, 'mode': model_mode, 'data_mode': data_mode},
            status, None,
            int((time.time() - started) * 1000),
            error,
            runs_dir=str(data_dir) if data_dir else None,
            meta=meta,
        )
        return entry, 'ok'
    except Exception:
        return None, 'failed'


def script_prepare(body, store=None, ai=None, data_dir=None, ops=None):
    """脚本准备：雷达真实作品 / 显式示例，测试或真实模型，带运行记录。"""
    if OPS_IMPORT_ERROR:
        return {'ok': False, 'error': '未找到工作流项目：' + OPS_IMPORT_ERROR}
    started = time.time()
    keyword = str(body.get('keyword') or '').strip()
    product = str(body.get('product') or '').strip()
    audience = str(body.get('audience') or '').strip() or '目标用户'
    data_mode = str(body.get('data_mode') or 'radar').strip()
    model_mode = str(body.get('model_mode') or 'test').strip()
    facts = body.get('facts')

    def fail(message, status='blocked', need_collect=False, **meta):
        _, log_status = _log_script(data_dir, keyword, product, model_mode, data_mode, status, message, started, **meta)
        result = {'ok': False, 'error': message, 'log_status': log_status}
        if need_collect:
            result['need_collect'] = True
        if log_status == 'failed':
            result['warning'] = '运行记录保存失败'
        return result

    if data_mode not in ('radar', 'sample'):
        return fail('数据来源无效')
    if model_mode not in ('test', 'real'):
        return fail('模型模式无效')
    if model_mode == 'real' and body.get('confirm') is not True:
        return fail('真实模型调用需要先确认计费与发送范围')
    if not keyword:
        return fail('请填写关键词')
    if not product:
        return fail('请填写商品名称')
    if not isinstance(facts, list) or not facts:
        return fail('请至少填写一条商品事实')
    try:
        facts = validate_facts({'product': product, 'facts': facts})
    except FactsError as exc:
        return fail('事实无效：' + str(exc))

    reference_ids = body.get('reference_ids') if isinstance(body.get('reference_ids'), list) else []
    pain_ids = body.get('pain_ids') if isinstance(body.get('pain_ids'), list) else []
    selected_references, selected_pains = [], []
    if reference_ids or pain_ids:
        if ops is None:
            return fail('资料库不可用')
        for ident in reference_ids:
            try:
                item = ops.get_reference(ident)
            except ValueError as exc:
                return fail('参考不可用：' + str(exc))
            selected_references.append({
                'id': item['id'], 'title': item.get('title') or '',
                'source_type': item.get('source_type') or '',
                'model': item.get('model') or '',
                'report': item.get('report') or {},
                'post_id': item.get('post_id'),
                'source_name': item.get('source_name') or '',
                'scope': item.get('scope') or {},
                'report_version': item.get('report_version') or '',
                'created_at': item.get('created_at'),
            })
        for ident in pain_ids:
            try:
                item = ops.get_pain(ident)
            except ValueError as exc:
                return fail('痛点不可用：' + str(exc))
            selected_pains.append({
                'id': item['id'], 'pain': item.get('pain') or '',
                'source': item.get('source') or '', 'frequency': item.get('frequency'),
                'related_post_id': item.get('related_post_id'),
                'evidence': item.get('evidence') or '',
                'evidence_role': item.get('evidence_role') or '',
            })

    candidate_id = body.get('candidate_id')
    combo_uid = str(body.get('combo_uid') or '').strip()
    candidate = None
    strategy = None
    if candidate_id:
        strategy = ops.get_strategy() if ops is not None else {}
        if not strategy or not strategy.get('confirmed'):
            return fail('账号策略未确认，不能生成正式选题')
        combo = ops.get_combo_by_uid(combo_uid) if combo_uid else None
        if not combo:
            return fail('当日组合不存在')
        candidate = next((item for item in (combo.get('snapshot_json') or [])
                          if int(item.get('id') or 0) == int(candidate_id)), None)
        if not candidate:
            return fail('候选不属于当日组合')
        if int(combo.get('strategy_version') or 0) != int(strategy.get('version') or 0):
            return fail('策略已改版，请重新选择选题')
        if candidate.get('expires_at') and str(candidate['expires_at']) < time.strftime('%Y-%m-%d'):
            return fail('实验候选已过期')

    suggestion_ids = body.get('suggestion_ids') if isinstance(body.get('suggestion_ids'), list) else []
    selected_suggestions = []
    for suggestion_id in suggestion_ids:
        if ops is None:
            return fail('资料库不可用')
        try:
            item = ops.get_suggestion(suggestion_id)
        except ValueError as exc:
            return fail('建议不可用：' + str(exc))
        if item.get('simulated'):
            return fail('演练建议不能进入正式生成')
        selected_suggestions.append(item)

    references = []
    if candidate:
        candidates = []
        data_source = 'radar'
    elif data_mode == 'sample':
        topics = run_topics(keyword)
        if topics.get('status') != 'ok':
            return fail(topics.get('blocked_reason') or '示例选题生成失败')
        candidates = (topics.get('outputs') or {}).get('candidates') or []
        data_source = 'sample'
    else:
        if store is None:
            return fail('雷达数据源不可用')
        try:
            state = store.state('live')
        except Exception as exc:
            return fail('读取雷达数据失败：' + str(exc))
        hit = next((k for k in (state.get('keywords') or []) if k.get('name') == keyword), None)
        matched = [p for p in (state.get('posts') or [])
                   if hit and hit.get('id') in (p.get('keyword_ids') or [])]
        if not hit or not matched:
            return fail('关键词“%s”还没有收录作品，请先在雷达采集或导入' % keyword, need_collect=True)
        candidates = generate_topic_candidates(keyword, [_ops_post(p) for p in matched], 3)
        references = [_reference(p) for p in sorted(matched, key=lambda p: p.get('plays') or 0, reverse=True)[:3]]
        data_source = 'radar'
    if not candidates and not candidate:
        return fail('没有可用的选题候选')

    llm_config = None
    if model_mode == 'real':
        cfg = ai.snapshot() if ai is not None else {}
        endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
        if not endpoint or not model:
            return fail('请先在 AI 模型设置中配置服务地址和模型')
        if not key:
            return fail('请先在 AI 模型设置中填写模型密钥')
        base = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
        llm_config = {
            'base_url': base,
            'model': model,
            'api_key': key,
            'authorized': body.get('confirm') is True,
            'allow_paid': body.get('confirm') is True,
        }

    source, model, usage, llm_duration, llm_error = None, None, None, None, None
    try:
        brief = {'product': product, 'audience': audience, 'facts': ''}
        chosen_topic = ({'topic': candidate.get('topic') or '',
                         'angle': candidate.get('audience_question') or ''}
                        if candidate else candidates[0])
        script = run_script(chosen_topic, brief, facts, use_llm=(model_mode == 'real'),
                            llm_config=llm_config,
                            references=selected_references, pains=selected_pains,
                            suggestions=selected_suggestions)
    except Exception as exc:
        return fail(str(exc), source=source, model=model, usage=usage,
                    llm_duration=llm_duration, llm_error=llm_error, data_source=data_source,
                    post_ids=[r['id'] for r in references])

    outputs = (script or {}).get('outputs') or {}
    source = outputs.get('source')
    llm_error = outputs.get('llm_error')
    inner = outputs.get('script') or {}
    model = inner.get('model')
    usage = inner.get('usage')
    llm_duration = inner.get('duration_ms')

    if (script or {}).get('status') != 'ok':
        return fail((script or {}).get('blocked_reason') or '脚本生成失败',
                    source=source, model=model, usage=usage,
                    llm_duration=llm_duration, llm_error=llm_error, data_source=data_source,
                    post_ids=[r['id'] for r in references])
    if model_mode == 'real' and source != 'llm':
        return fail(llm_error or '真实模型未产生输出，已拒绝回退结果',
                    source=source, model=model, usage=usage,
                    llm_duration=llm_duration, llm_error=llm_error, data_source=data_source,
                    post_ids=[r['id'] for r in references])

    entry, log_status = _log_script(
        data_dir, keyword, product, model_mode, data_mode, 'ok', None, started,
        source=source, model=model, usage=usage, llm_duration=llm_duration, llm_error=llm_error,
        data_source=data_source, post_ids=[r['id'] for r in references],
    )
    result = {
        'ok': True,
        'run_id': (entry or {}).get('run_id'),
        'log_status': log_status,
        'data_source': data_source,
        'model_mode': model_mode,
        'source': source,
        'model': model,
        'usage': usage,
        'candidates': candidates,
        'script': inner,
        'missing': inner.get('missing') or [],
        'references': references,
        'snapshot': {'product': product, 'audience': audience, 'facts': facts['facts']},
        'selection': {'references': selected_references, 'pains': selected_pains},
        'suggestion_snapshot': selected_suggestions,
        'candidate': candidate,
        'combo_uid': combo_uid,
        'plan': {
            'combo_uid': combo_uid,
            'candidate_id': candidate.get('id') if candidate else None,
            'topic_snapshot': candidate,
            'strategy_version': strategy.get('version') if candidate else None,
            'run_id': (entry or {}).get('run_id'),
            'references': selected_references,
            'pains': selected_pains,
            'facts': facts['facts'],
            'proof': '',
            'duration_seconds': inner.get('estimated_seconds') or None,
            'shots': [],
            'next_action': '',
            'missing': inner.get('missing') or [],
        },
    }
    if log_status == 'failed':
        result['warning'] = '文稿已生成，运行记录保存失败'
    return result


def _advice_refs(store, ops, selected=None):
    selected = selected or {}
    refs, read_errors, confirmed, has_metrics = [], [], False, False
    try:
        strategy = ops.get_strategy()
        confirmed = bool(strategy.get('confirmed'))
        data = strategy.get('data') or {}
        refs.append({'id': 'strategy', 'text': '策略 v%s（%s）；实验许可：%s' % (
            strategy.get('version'), '已确认' if confirmed else '未确认，仅研究草案',
            '开' if data.get('experiment_allowed') else '关')})
        for key, label in (('direction', '方向'), ('audience', '受众'), ('resources', '真实资源'),
                           ('goal', '阶段目标'), ('principles', '内容原则'), ('exclusions', '排除项'),
                           ('takeover', '承接方式')):
            if data.get(key):
                refs.append({'id': 'strategy:%s' % key,
                             'text': '%s：%s' % (label, str(data.get(key))[:500])})
    except Exception as exc:
        read_errors.append('策略读取失败：%s' % exc)
    suggestion_ids = selected.get('suggestion_ids') or []
    if not isinstance(suggestion_ids, list) or any(not isinstance(item, str) for item in suggestion_ids):
        raise ValueError('复盘建议选择无效')
    if len(suggestion_ids) > 3:
        raise ValueError('最多选择 3 条复盘建议')
    for suggestion_id in suggestion_ids:
        item = ops.get_suggestion(suggestion_id)
        suggestion = item.get('suggestion') or {}
        review = ops.get_review(item['review_uid'])
        ops.get_publish_record(item['record_uid'])
        frozen = review.get('data_json') or {}
        notes = frozen.get('consultation_snapshot')
        snaps = frozen.get('metric_snapshots')
        if notes is None or snaps is None:
            notes, snaps = None, None
        refs.append({'id': 'suggestion:%s' % item['id'],
                     'text': ('复盘建议：%s；依据：%s；条件：%s；待验证：%s' % (
                         suggestion.get('text') or '', suggestion.get('basis') or '',
                         suggestion.get('conditions') or '', suggestion.get('pending') or ''))[:1200]})
        if notes is None:
            refs.append({'id': 'review:%s' % item['review_uid'],
                         'text': '复盘来源：登记 %s；该旧复盘没有冻结咨询/指标快照，不加载当前新数据' % item['record_uid']})
        else:
            refs.append({'id': 'review:%s' % item['review_uid'],
                         'text': '复盘来源（冻结快照）：登记 %s；指标快照 %d 份；咨询摘录 %d 条（旧复盘冻结，与指标中的咨询次数不可相加）' % (
                             item['record_uid'], len(snaps), len(notes))})
            for note in notes[:3]:
                refs.append({'id': 'consultation:%s' % (note.get('note_uid') or ''),
                             'text': '咨询摘录：%s（来源 %s）' % (str(note.get('text') or '')[:200],
                                                              note.get('source') or 'manual')[:600]})
    pain_ids = selected.get('pain_ids') or []
    reference_ids = selected.get('reference_ids') or []
    if not isinstance(pain_ids, list) or any(type(item) is not int for item in pain_ids):
        raise ValueError('痛点选择无效')
    if not isinstance(reference_ids, list) or any(type(item) is not int for item in reference_ids):
        raise ValueError('参考选择无效')
    for ident in pain_ids:
        try:
            item = ops.get_pain(ident)
        except ValueError:
            raise ValueError('所选痛点不存在或已归档：%s' % ident)
        refs.append({'id': 'pain:%s' % item.get('id'),
                     'text': '痛点[%s] 归纳：%s；原摘录：%s；证据角色：%s；来源：%s；频次：%s' % (
                         item.get('id'), item.get('pain'), item.get('evidence') or '无',
                         item.get('evidence_role'), item.get('source'), item.get('frequency'))[:900]})
    for ident in reference_ids:
        try:
            item = ops.get_reference(ident)
        except ValueError:
            raise ValueError('所选参考不存在或已归档：%s' % ident)
        report = item.get('report') or {}
        scope = item.get('scope') or {}
        refs.append({'id': 'ref:%s' % item.get('id'),
                     'text': '参考[%s] 《%s》；来源：%s；观察范围：%s；摘要：%s' % (
                         item.get('id'), item.get('title') or '', item.get('source_name') or '未知',
                         scope.get('limitation') or '未标注',
                         str(report.get('summary') or '')[:300])[:900]})
    if not pain_ids and not reference_ids:
        refs.append({'id': 'selection', 'text': '本次未选择痛点/参考；不得假设库内其他资料可用'})
    try:
        dash = ops.ops_dashboard()
        counts = (dash.get('tasks') or {}).get('counts') or {}
        refs.append({'id': 'tasks', 'text': '任务：草稿 %s / 待审 %s / 已审未登记 %s / 已登记 %s' % (
            counts.get('draft', 0), counts.get('pending_review', 0),
            counts.get('approved_unpublished', 0), (dash.get('published') or {}).get('count', 0))})
        for item in (dash.get('latest_metrics') or [])[:5]:
            snap = item.get('snapshot') or {}
            if snap:
                has_metrics = True
                refs.append({'id': 'metric:%s' % item.get('record_uid'),
                             'text': '自有发布指标[%s] 采集：%s；口径：%s；来源：%s；值：%s' % (
                                 item.get('record_uid'), snap.get('collected_at'),
                                 snap.get('definition') or '未标注', snap.get('source') or '未标注',
                                 snap.get('metrics'))[:600]})
    except Exception as exc:
        read_errors.append('任务/指标读取失败：%s' % exc)
    return {'refs': refs, 'read_errors': read_errors, 'strategy_confirmed': confirmed,
            'has_metrics': has_metrics}


def _advice_parent(parent):
    result = parent.get('result_json') or {}
    lines = []
    for item in result.get('cannot_judge') or []:
        lines.append('不能判断：%s' % str(item)[:200])
    for item in result.get('priorities') or []:
        lines.append('优先问题：%s（依据：%s）' % (
            item.get('text') or '', '、'.join(item.get('basis') or [])))
    for item in result.get('directions') or []:
        lines.append('方向：%s；理由：%s；条件：%s' % (
            item.get('text') or '', item.get('why') or '', item.get('conditions') or ''))
    for item in result.get('week_actions') or []:
        state = next((row for row in parent.get('actions') or []
                      if row.get('action_id') == item.get('id')), None)
        lines.append('动作：%s；理由：%s；证明：%s；条件：%s；缺口：%s；下一步：%s%s' % (
            item.get('action') or '', item.get('why') or '', item.get('proof') or '',
            item.get('conditions') or '', item.get('gaps') or '', item.get('next') or '',
            ('；进度：%s；备注：%s' % (state.get('status'), state.get('note') or '无')) if state else ''))
    return {'summary': '；'.join(lines)[:3500],
            'actions': [item.get('action') or '' for item in result.get('week_actions') or []]}


def _advice_digest(parent, budget=1200):
    result = parent.get('result_json') or {}
    actions = result.get('week_actions') or []
    state_by_id = {row.get('action_id'): row for row in parent.get('actions') or []}

    def state_of(item):
        return state_by_id.get(item.get('id')) or {}

    def clip_field(label, value, room):
        if room <= 0:
            return label
        text = str(value)
        if len(text) <= room:
            return label + text
        if room <= 4:
            return label + '压'[:room]
        return label + text[:room - 4] + '（压缩）'

    count = len(actions)
    share = (budget - max(0, count - 1)) // max(1, count) if actions else budget
    groups = []
    for item in actions:
        state = state_of(item)
        aid = str(item.get('id'))
        fields = []
        if item.get('conditions'):
            fields.append(('条件:', str(item.get('conditions'))))
        if item.get('next'):
            fields.append(('下一步:', str(item.get('next'))))
        if state.get('note'):
            fields.append(('备注:', str(state.get('note'))))
        head = '%s:%s{' % (aid, state.get('status') or 'todo')
        fixed = len(head) + sum(1 + len(label) for label, _ in fields) + 1
        room_total = max(0, share - fixed)
        room = room_total // max(1, len(fields))
        parts = [head]
        for index, (label, value) in enumerate(fields):
            parts.append(('' if index == 0 else ';') + clip_field(label, value, room))
        parts.append('}')
        groups.append(''.join(parts))
    digest = '；'.join(groups)
    used = len(digest)
    desc = []
    for item in actions:
        aid = str(item.get('id'))
        if item.get('action'):
            desc.append('%s正文：%s' % (aid, str(item.get('action'))[:120]))
        for label, field in (('理由', 'why'), ('证明', 'proof'), ('缺口', 'gaps')):
            if item.get(field):
                desc.append('%s%s：%s' % (aid, label, str(item.get(field))[:80]))
    extras = []
    for item in result.get('cannot_judge') or []:
        extras.append('不能判断：' + str(item)[:150])
    for item in result.get('directions') or []:
        extras.append('方向：%s；理由：%s；条件：%s' % (
            str(item.get('text') or '')[:150], str(item.get('why') or '')[:100],
            str(item.get('conditions') or '')[:120]))
    for item in result.get('priorities') or []:
        extras.append('优先问题：' + str(item.get('text') or '')[:100])
    for chunk in ['；'.join(desc)] + extras:
        if not chunk:
            continue
        room = budget - used - 1
        if room <= 0:
            break
        if len(chunk) > room:
            chunk = chunk[:max(0, room - 4)] + '（压缩）'
        digest += '；' + chunk
        used += len(chunk) + 1
    return digest


def _advice_history(ops, parent):
    nodes, current = [], parent
    for _ in range(3):
        if not current:
            break
        nodes.append(current)
        parent_uid = current.get('parent_uid')
        if not parent_uid:
            break
        try:
            current = ops.get_advice(parent_uid)
        except ValueError:
            break
    nodes.reverse()
    parts = []
    for index, node in enumerate(nodes, 1):
        digest = _advice_digest(node)
        question = node.get('question') or '（首轮分析）'
        parts.append('第%d轮：问题=%s；%s' % (index, str(question)[:150], digest))
    return '\n'.join(parts)[:4500]


def _advice_run(status, context, question, parent, model_mode, confirm, ai):
    if build_advice_prompt is None:
        raise ValueError('运营建议模块不可用')
    if model_mode != 'real':
        return demo_advice(status, context), {'source': 'demo', 'model': None, 'usage': {},
                                              'duration_ms': 0, 'run_id': None}
    if confirm is not True:
        raise ValueError('真实模型调用需本次确认')
    cfg = ai.snapshot() if ai is not None else {}
    endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
    if not endpoint or not model or not key:
        raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
    base = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
    llm_config = {'base_url': base, 'model': model, 'api_key': key, 'authorized': True,
                  'allow_paid': confirm is True}
    system, user = build_advice_prompt(status, context, question, parent=parent)
    started = time.time()
    try:
        resp = call_llm([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                        max_tokens=1600, timeout=90, config=llm_config)
    except LLMError as exc:
        raise ValueError('模型调用失败：%s' % exc)
    parsed = parse_advice(resp['text'], [ref['id'] for ref in context.get('refs') or []])
    return parsed, {'source': 'llm', 'model': resp.get('model'), 'usage': resp.get('usage') or {},
                    'duration_ms': resp.get('duration_ms') or int((time.time() - started) * 1000),
                    'run_id': uuid.uuid4().hex[:12]}


M04_OPS_BYTES = 64 * 1024
M04_OPS_PATHS = ('/api/ops/advice/save', '/api/ops/advice/analyze', '/api/ops/advice/ask',
                 '/api/ops/draft/save', '/api/ops/draft/generate', '/api/ops/draft/optimize',
                 '/api/ops/research/save', '/api/ops/research/analyze',
                 '/api/ops/research/topics', '/api/ops/research/to-draft',
                 '/api/ops/research/adaptation', '/api/ops/research/adaptation-to-draft',
                 '/api/ops/reminders/create', '/api/ops/reminders/update', '/api/ops/conversion/build')


def _bounded_text(value, name, limit):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('%s必须是文本' % name)
    text = value.strip()
    if len(text) > limit:
        raise ValueError('%s超过 %d 字符上限，请精简' % (name, limit))
    return text


def advice_analyze(body, store, ops, ai):
    status = validate_status(body.get('status') or {})
    if not any(status.values()):
        raise ValueError('请至少填写一项业务现状')
    context = _advice_refs(store, ops, body.get('selected') or {})
    question = _bounded_text(body.get('question'), '追问', 1000)
    result, meta = _advice_run(status, context, question, None, body.get('model_mode'),
                               body.get('confirm'), ai)
    saved = ops.save_advice(status, context, source=meta['source'], result=result, question=question,
                            model=meta['model'], run_id=meta['run_id'], usage=meta['usage'],
                            duration_ms=meta['duration_ms'])
    return {'ok': True, 'advice': saved}


def advice_ask(body, store, ops, ai):
    parent = ops.get_advice(str(body.get('advice_uid') or ''))
    question = _bounded_text(body.get('question'), '追问', 1000)
    if not question:
        raise ValueError('请填写追问')
    context = parent.get('context_json') or {}
    history = _advice_history(ops, parent)
    result, meta = _advice_run(parent.get('status_json') or {}, context, question,
                               {'summary': history, 'actions': []}, body.get('model_mode'),
                               body.get('confirm'), ai)
    saved = ops.save_advice(parent.get('status_json') or {}, context, source=meta['source'], result=result,
                            question=question, parent_uid=parent['advice_uid'], model=meta['model'],
                            run_id=meta['run_id'], usage=meta['usage'], duration_ms=meta['duration_ms'])
    return {'ok': True, 'advice': saved}


def advice_save(body, ops):
    status = validate_status(body.get('status') or {})
    if not any(status.values()):
        raise ValueError('请至少填写一项业务现状')
    return {'ok': True, 'advice': ops.save_advice(status, {}, source='draft')}


def _draft_run(status, topic, context, instruction, ai, model_mode, confirm, base=None, base_version=0):
    if build_draft_prompt is None:
        raise ValueError('研究稿模块不可用')
    # R2：带 B 来源的生成/优化先组装完整上下文并按 24000 字符受控拒绝；不先调用再丢尾部。
    source = (context or {}).get('research_source')
    if isinstance(source, dict) and source.get('kind') in ('topics', 'adaptation'):
        size = _draft_context_chars(context)
        if size > M02_RESEARCH_CONTEXT_CHARS:
            raise ValueError('研究稿来源上下文超过 24000 字符上限（当前约 %d 字符），'
                             '请减少来源或缩短原文' % size)
    elif isinstance((context or {}).get('industry'), dict):
        size = _draft_context_chars(context)
        if size > M02_RESEARCH_CONTEXT_CHARS:
            raise ValueError('研究稿上下文超过 24000 字符上限（当前约 %d 字符），'
                             '请减少资料或缩短模板' % size)
    meta = {'source': 'demo', 'model': None, 'usage': {}, 'duration_ms': 0, 'run_id': None}
    if model_mode != 'real':
        content = demo_optimize(base, instruction) if base else demo_draft(status, topic, context)
        return content, meta
    if confirm is not True:
        raise ValueError('真实模型调用需本次确认')
    cfg = ai.snapshot() if ai is not None else {}
    endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
    if not endpoint or not model or not key:
        raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
    base_url = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
    llm_config = {'base_url': base_url, 'model': model, 'api_key': key, 'authorized': True,
                  'allow_paid': confirm is True}
    if base:
        system, user = build_optimize_prompt(base, instruction, context, topic, status,
                                             base_version=base_version)
    else:
        system, user = build_draft_prompt(status, topic, context)
    user = _append_industry_prompt(user, context.get('industry'))
    started = time.time()
    try:
        resp = call_llm([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                        max_tokens=2400, timeout=90, config=llm_config)
    except LLMError as exc:
        raise ValueError('模型调用失败：%s' % exc)
    parsed = parse_draft(resp['text'], [ref['id'] for ref in context.get('refs') or []])
    return parsed, {'source': 'llm', 'model': resp.get('model'), 'usage': resp.get('usage') or {},
                    'duration_ms': resp.get('duration_ms') or int((time.time() - started) * 1000),
                    'run_id': uuid.uuid4().hex[:12]}


def draft_save(body, store, ops):
    topic = validate_topic(body.get('topic'))
    status = validate_status(body.get('status') or {})
    context = _advice_refs(store, ops, body.get('selected') or {})
    industry, industry_source = _industry_choose(body)
    context = _industry_apply(context, industry, industry_source)
    if _industry_context_size(context) > M02_RESEARCH_CONTEXT_CHARS:
        raise ValueError('研究稿上下文超过 24000 字符上限，请减少资料或缩短模板')
    return {'ok': True, 'draft': ops.save_draft(topic, status, context)}


M02_RESEARCH_CONTEXT_CHARS = 24000
_INDUSTRY_MISSING = object()


def _industry_from_context(context):
    """读取记录/版本保存的模板；返回 (完整快照|None, 状态/来源)。"""
    raw = None
    if isinstance(context, dict):
        raw = context.get('industry')
        if raw is None:
            wrapped = (context.get('draft_optimization') or {}).get('industry')
            if wrapped is not None:
                raw = wrapped
    if raw is None:
        return None, {'status': 'legacy_missing', 'label': '通用（历史未保存模板）'}
    if isinstance(raw, str):
        try:
            validate_industry_code(raw)
        except ValueError:
            return None, {'status': 'legacy_invalid', 'code': raw}
        return None, {'status': 'legacy_string', 'code': raw}
    if isinstance(raw, dict):
        if ('status' in raw or 'data' in raw) and not (
                raw.get('questions') and raw.get('label') and raw.get('code')):
            status = raw.get('status')
            data = raw.get('data')
            code = raw.get('code')
            if status == 'not_provided' and data is None and code is None:
                return None, {'status': 'legacy_missing'}
            if data is not None:
                if not isinstance(data, dict) or not data.get('code'):
                    return None, {'status': 'legacy_invalid', 'wrapped': True}
                try:
                    return validate_industry_snapshot(data), {'status': 'frozen',
                                                              'wrapped': True}
                except ValueError:
                    return None, {'status': 'legacy_invalid', 'wrapped': True}
            if code is not None:
                if not isinstance(code, str):
                    return None, {'status': 'legacy_invalid', 'wrapped': True}
                try:
                    validate_industry_code(code)
                except ValueError:
                    return None, {'status': 'legacy_invalid', 'wrapped': True}
                return None, {'status': 'legacy_string', 'code': code, 'wrapped': True}
            return None, {'status': 'legacy_invalid', 'wrapped': True}
        try:
            return validate_industry_snapshot(raw), {'status': 'frozen'}
        except ValueError:
            return None, {'status': 'legacy_invalid'}
    return None, {'status': 'legacy_invalid'}


def _industry_source_of(context):
    if not isinstance(context, dict) or not isinstance(context.get('industry_source'), dict):
        return {}
    return copy.deepcopy(context['industry_source'])


def _industry_choose(body, inherited_context=None):
    """本次选择：显式 code 优先；否则使用继承完整快照；均无时冻结 generic。"""
    if industry_catalog is None:
        raise ValueError('内容领域模板模块不可用')
    if isinstance(body, dict) and 'industry' in body:
        code = validate_industry_code(body['industry'])
        snapshot = build_industry_snapshot(code)
        return snapshot, {'type': 'explicit', 'code': code}
    inherited, status = _industry_from_context(inherited_context or {})
    if inherited is not None:
        source = {'type': 'inherited', 'code': inherited['code'], 'status': status['status']}
        saved = _industry_source_of(inherited_context)
        if saved:
            source['parent'] = saved
        return inherited, source
    if status.get('status') == 'legacy_invalid':
        raise ValueError('旧内容领域模板不可用，请明确选择本次模板后再生成')
    snapshot = build_industry_snapshot(DEFAULT_INDUSTRY_CODE)
    source = {'type': 'default', 'code': DEFAULT_INDUSTRY_CODE}
    if status.get('status') != 'legacy_missing':
        source['legacy_status'] = status.get('status')
        if status.get('code'):
            source['legacy_code'] = status['code']
    return snapshot, source


def _industry_apply(context, snapshot, source):
    context = dict(context or {})
    context['industry'] = copy.deepcopy(snapshot)
    context['industry_source'] = copy.deepcopy(source)
    return context


def _industry_prompt(snapshot):
    if snapshot is None or render_industry_prompt is None:
        return ''
    return render_industry_prompt(snapshot)


def _append_industry_prompt(user, snapshot):
    prompt = _industry_prompt(snapshot)
    return (user + '\n\n' + prompt) if prompt else user


def _industry_context_size(context):
    compact = json.dumps(context or {}, ensure_ascii=False, separators=(',', ':'))
    return len(compact)


def _research_source_of(draft):
    context = (draft or {}).get('context_json') or {}
    source = context.get('research_source')
    if isinstance(source, dict) and source.get('kind') in ('topics', 'adaptation'):
        return source
    return None


def _frozen_strategy(source):
    raw = source.get('strategy') if isinstance(source, dict) else None
    if not isinstance(raw, dict):
        return {'version': 0, 'confirmed': False, 'data': {}}
    version = raw.get('version', 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        version = 0
    data = raw.get('data')
    return {'version': version, 'confirmed': bool(raw.get('confirmed')),
            'data': data if isinstance(data, dict) else {}}


def _frozen_source_refs(draft, source):
    # Q03-A：B 固定来源只取 B 快照，不继承上一次生成时附加的 selected refs。
    refs = []
    seen = set()
    for ref in source.get('refs') or []:
        if not isinstance(ref, dict):
            continue
        ident = ref.get('id')
        if not isinstance(ident, str) or not ident or ident in seen:
            continue
        seen.add(ident)
        refs.append({'id': ident, 'text': ref.get('text') or '',
                     'role': ref.get('role') or '',
                     'source': ref.get('source') or ''})
    return refs


def _verify_b_source_refs(ops, source):
    """B 导入稿只核验冻结来源仍存在/未归档/非演练/归属，不重载当前正文。"""
    refs, ref_map = [], {}
    for row in source.get('basis_chain') or []:
        if not isinstance(row, dict):
            continue
        ident = row.get('source_id')
        if not isinstance(ident, str) or not _TOPIC_SOURCE_ID_RE.match(ident):
            continue
        origin = row.get('origin')
        if not isinstance(origin, dict):
            raise ValueError('B 冻结来源 %s 缺少真实身份' % ident)
        if ident in ref_map:
            raise ValueError('B 冻结来源号重复：%s' % ident)
        refs.append({'id': ident})
        ref_map[ident] = origin
    if refs:
        _verify_ref_origins(ops, refs, ref_map)


_SELECTED_ABSENT = object()


def _b_selected_refs(ops, selected):
    """Q03：本次另选资料先严格校验类型，再按权威库全文构建，不复用展示摘要截断。"""
    if selected is _SELECTED_ABSENT:
        selected = {}
    if not isinstance(selected, dict):
        raise ValueError('selected 必须是对象')
    pain_ids = selected.get('pain_ids', [])
    reference_ids = selected.get('reference_ids', [])
    for name, values in (('pain_ids', pain_ids), ('reference_ids', reference_ids)):
        if not isinstance(values, list):
            raise ValueError('%s 必须是数组' % name)
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError('%s 只能包含正整数 ID' % name)
    refs = []
    seen = set()
    for ident in pain_ids:
        key = ('pain', ident)
        if key in seen:
            continue
        seen.add(key)
        try:
            item = ops.get_pain(ident)
        except ValueError:
            raise ValueError('所选痛点不存在或已归档：%s' % ident)
        refs.append({'id': 'pain:%s' % item.get('id'),
                     'text': '痛点[%s] 归纳：%s；原摘录：%s；证据角色：%s；来源：%s；频次：%s' % (
                         item.get('id'), item.get('pain'), item.get('evidence') or '无',
                         item.get('evidence_role'), item.get('source'), item.get('frequency'))})
    for ident in reference_ids:
        key = ('ref', ident)
        if key in seen:
            continue
        seen.add(key)
        try:
            item = ops.get_reference(ident)
        except ValueError:
            raise ValueError('所选参考不存在或已归档：%s' % ident)
        report = item.get('report') or {}
        scope = item.get('scope') or {}
        refs.append({'id': 'ref:%s' % item.get('id'),
                     'text': '参考[%s] 《%s》；来源：%s；观察范围：%s；摘要：%s' % (
                         item.get('id'), item.get('title') or '', item.get('source_name') or '未知',
                         scope.get('limitation') or '未标注',
                         str(report.get('summary') or ''))})
    return refs


def _b_import_context(ops, draft, source, store, selected):
    """R2/Q03：B 冻结来源 + 本次明确另选资料；当前策略只作变更提示。"""
    context = {'refs': _frozen_source_refs(draft, source), 'read_errors': [],
               'research_source': source,
               'strategy': _frozen_strategy(source),
               'strategy_confirmed': bool(_frozen_strategy(source).get('confirmed')),
               'has_metrics': bool((draft.get('context_json') or {}).get('has_metrics'))}
    _verify_b_source_refs(ops, source)
    # 先按 M02 既有契约校验本次 selected（非法 ID 在模型前抛错）。
    current = {'refs': _b_selected_refs(ops, selected)}
    frozen_identities = set()
    for row in source.get('basis_chain') or []:
        origin = row.get('origin') if isinstance(row, dict) else None
        if not isinstance(origin, dict):
            continue
        if origin.get('kind') == 'pain' and origin.get('id') is not None:
            frozen_identities.add('pain:%s' % origin.get('id'))
        elif origin.get('kind') == 'reference' and origin.get('id') is not None:
            frozen_identities.add('ref:%s' % origin.get('id'))
    extras = []
    for ref in current.get('refs') or []:
        rid = str(ref.get('id') or '')
        if not (rid.startswith('pain:') or rid.startswith('ref:')):
            continue
        if rid in frozen_identities or rid.startswith('strategy'):
            continue
        extras.append({'id': 'selected:%s' % rid, 'text': ref.get('text') or '',
                       'role': ref.get('role') or '', 'source': ref.get('source') or '',
                       'selected_this_run': True})
    if extras:
        context['refs'].extend(extras)
        context['selected_this_run'] = [ref['id'] for ref in extras]
    try:
        current = ops.get_strategy()
    except ValueError:
        current = {}
    frozen = context['strategy']
    changed = (int(current.get('version') or 0) != frozen['version'] or
               bool(current.get('confirmed')) != frozen['confirmed'])
    if changed:
        context['current_strategy'] = {'version': int(current.get('version') or 0),
                                       'confirmed': bool(current.get('confirmed')),
                                       'changed': True}
    imported, status = _industry_from_context(source)
    if imported is None and status.get('status') == 'legacy_invalid':
        raise ValueError('来源记录的旧内容领域模板不可用，不能转入')
    if imported is not None:
        context = _industry_apply(context, imported,
                                  _industry_source_of(source) or {'type': 'inherited',
                                                                  'code': imported['code'],
                                                                  'parent_kind': 'topics'})
    return context


def _draft_context_chars(context):
    return len(json.dumps(context or {}, ensure_ascii=False, separators=(',', ':')))


def draft_generate(body, store, ops, ai):
    topic = validate_topic(body.get('topic'))
    status = validate_status(body.get('status') or {})
    draft_uid = str(body.get('draft_uid') or '')
    draft = ops.get_draft(draft_uid) if draft_uid else None
    source = _research_source_of(draft) if draft is not None else None
    if source is not None and draft.get('topic') == topic:
        if source.get('kind') == 'topics':
            context = _b_import_context(ops, draft, source, store, body['selected'] if 'selected' in body else _SELECTED_ABSENT)
        else:
            context = _adaptation_import_context(ops, draft, source, store,
                                                 body['selected'] if 'selected' in body else _SELECTED_ABSENT)
    else:
        context = _advice_refs(store, ops, body.get('selected') or {})
    if not (isinstance(context.get('industry'), dict) and context['industry'].get('code')):
        inherited = (draft or {}).get('context_json') or {}
        industry, industry_source = _industry_choose(body, inherited)
        context = _industry_apply(context, industry, industry_source)
    elif 'industry' in body:
        industry, industry_source = _industry_choose(body)
        context = _industry_apply(context, industry, industry_source)
    if _industry_context_size(context) > M02_RESEARCH_CONTEXT_CHARS:
        raise ValueError('研究稿上下文超过 24000 字符上限，请减少资料或缩短模板')
    content, meta = _draft_run(status, topic, context, '', ai, body.get('model_mode'), body.get('confirm'))
    if draft is None or draft['topic'] != topic:
        draft = ops.save_draft(topic, status, context)
    else:
        ops.update_draft(draft['draft_uid'], topic=topic, status=status, context=context)
    saved = ops.add_draft_version(draft['draft_uid'], content, source=meta['source'], model=meta['model'],
                                  run_id=meta['run_id'], usage=meta['usage'],
                                  duration_ms=meta['duration_ms'], topic=topic, status=status,
                                  context=context)
    return {'ok': True, 'draft': saved}


def _verify_draft_optimization_adaptation(ops, artifact):
    """按 C 保存记录核验父 B/A、候选与归属；只读冻结记录，不重算或读取 LIVE 正文。"""
    context = artifact.get('context_json') or {}
    parent_info = context.get('parent')
    parent_uid = artifact.get('parent_uid') or ''
    uid = artifact.get('artifact_uid')
    if parent_info is None:
        if parent_uid:
            raise ValueError('附加适配记录缺少冻结父链信息：%s' % uid)
        return
    if not isinstance(parent_info, dict):
        raise ValueError('附加适配记录父链格式无效：%s' % uid)
    b_uid = parent_info.get('artifact_uid')
    candidate_id = parent_info.get('candidate_id')
    if not isinstance(b_uid, str) or not _ARTIFACT_UID_RE.match(b_uid):
        raise ValueError('附加适配记录父选题 UID 无效：%s' % uid)
    if b_uid != parent_uid:
        raise ValueError('附加适配记录父选题归属不一致：%s' % uid)
    subject = context.get('subject') or {}
    frozen_candidate = subject.get('candidate') if isinstance(subject, dict) else None
    if (not isinstance(frozen_candidate, dict)
            or frozen_candidate.get('id') != candidate_id):
        raise ValueError('附加适配记录候选与父链不一致：%s' % uid)
    resolved = _c_resolve_candidate(ops, {'kind': 'candidate', 'artifact_uid': b_uid,
                                          'candidate_id': candidate_id})
    if resolved['candidate'].get('id') != candidate_id:
        raise ValueError('附加适配记录候选不属于父选题：%s' % uid)
    if resolved['parent'].get('artifact_uid') != parent_info.get('parent_uid'):
        raise ValueError('附加适配记录父研究归属不一致：%s' % uid)


def _verify_inherited_artifacts(ops, inherited):
    """核验基版本实际继承的 A/C 身份与冻结快照；内容仍用基版快照，不读 LIVE 正文。"""
    for item in inherited or []:
        uid = item.get('artifact_uid')
        try:
            artifact = ops.get_research_artifact(uid)
        except ValueError:
            raise ValueError('基版本继承的附加资料不存在或已归档：%s' % uid)
        kind = item.get('kind')
        if kind not in ('research', 'adaptation') or artifact.get('kind') != kind:
            raise ValueError('基版本继承的附加资料类型不一致：%s' % uid)
        if (artifact.get('parent_uid') or '') != (item.get('parent_uid') or ''):
            raise ValueError('基版本继承的附加资料父记录不一致：%s' % uid)
        result = artifact.get('result_json')
        if (not isinstance(result, dict) or not result
                or result != item.get('result')):
            raise ValueError('基版本继承的附加资料快照与记录不一致：%s' % uid)
        context = artifact.get('context_json')
        if not isinstance(context, dict):
            raise ValueError('基版本继承的附加资料上下文无效：%s' % uid)
        if kind == 'adaptation':
            _verify_draft_optimization_adaptation(ops, artifact)
        refs = context.get('refs') or []
        ref_map = context.get('ref_map') or {}
        _verify_ref_origins(ops, refs, ref_map, limit=24 if kind == 'adaptation' else 12)
        mapped = []
        for ref in refs:
            sid = ref.get('id')
            origin = ref_map.get(sid)
            mapped.append({'id': '%s:%s' % (uid, sid),
                           'text': str(ref.get('text') or ''),
                           'role': str(ref.get('label') or ref.get('role') or ''),
                           'origin': dict(origin) if isinstance(origin, dict) else None})
        if mapped != (item.get('refs') or []):
            raise ValueError('基版本继承的附加资料引用快照不一致：%s' % uid)
        note = context.get('instruction') if kind == 'adaptation' else ''
        if (item.get('note') or '') != (note or ''):
            raise ValueError('基版本继承的附加资料说明快照不一致：%s' % uid)


def _draft_optimization_extras(ops, uids):
    """按 UID 权威加载本次明确选择的 A/C 记录，映射为带命名空间的冻结依据。"""
    extras = []
    for uid in uids:
        try:
            artifact = ops.get_research_artifact(uid)
        except ValueError:
            raise ValueError('附加资料不存在或已归档：%s' % uid)
        kind = artifact.get('kind')
        if kind not in ('research', 'adaptation'):
            raise ValueError('附加资料只能是已分析的研究或适配记录：%s' % uid)
        result = artifact.get('result_json')
        if not isinstance(result, dict) or not result:
            raise ValueError('附加资料尚未分析，不能附加：%s' % uid)
        context = artifact.get('context_json')
        if not isinstance(context, dict):
            raise ValueError('附加资料上下文无效：%s' % uid)
        if kind == 'adaptation':
            _verify_draft_optimization_adaptation(ops, artifact)
        refs = context.get('refs') or []
        ref_map = context.get('ref_map') or {}
        _verify_ref_origins(ops, refs, ref_map, limit=24 if kind == 'adaptation' else 12)
        mapped = []
        for ref in refs:
            sid = ref.get('id')
            origin = ref_map.get(sid)
            mapped.append({'id': '%s:%s' % (uid, sid),
                           'text': str(ref.get('text') or ''),
                           'role': str(ref.get('label') or ref.get('role') or ''),
                           'origin': dict(origin) if isinstance(origin, dict) else None})
        extras.append({'artifact_uid': uid, 'kind': kind,
                       'parent_uid': artifact.get('parent_uid') or '',
                       'topic': artifact.get('topic') or '',
                       'source': artifact.get('source') or 'manual',
                       'created_at': artifact.get('created_at'),
                       'refs': mapped, 'result': result,
                       'note': context.get('instruction') if kind == 'adaptation' else ''})
    return extras


def _draft_optimize_with_optimization(body, store, ops, ai, optimization):
    spec = validate_draft_optimization(body, optimization)
    draft = ops.get_draft(spec['draft_uid'])
    try:
        base_record = ops.get_draft_version(draft['draft_uid'], spec['base_version'])
    except ValueError:
        raise ValueError('基版本不属于该研究稿')
    base = freeze_draft_base(base_record, spec['base_version'], draft)
    _verify_inherited_artifacts(ops, base.get('inherited') or [])
    base_industry, base_industry_status = _industry_from_context(base.get('context') or {})
    industry, industry_source = _industry_choose(body, base.get('context') or {})
    industry_source['base_version'] = base.get('version')
    if base_industry is not None:
        industry_source['base_code'] = base_industry['code']
    base['context'] = _industry_apply(base.get('context') or {}, industry, industry_source)
    extras = freeze_draft_extras(_draft_optimization_extras(
        ops, optimization.get('additional_artifact_uids') or []))
    source = _research_source_of({'context_json': base['context']})
    if source is not None:
        if source.get('kind') == 'topics':
            _verify_b_source_refs(ops, source)
        else:
            _verify_adaptation_source(ops, source)
    # 先构最终 messages：基稿/上下文两类 24000 与引用冲突都在模型前失败。
    system, user = build_draft_optimization_messages(spec, base, extras)
    user = _append_industry_prompt(user, industry)
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': user}]
    meta = {'source': 'demo', 'model': None, 'usage': {}, 'duration_ms': 0, 'run_id': None}
    if spec['model_mode'] == 'real':
        if spec['confirm'] is not True:
            raise ValueError('真实模型调用需本次确认')
        cfg = ai.snapshot() if ai is not None else {}
        endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
        if not endpoint or not model or not key:
            raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
        base_url = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
        llm_config = {'base_url': base_url, 'model': model, 'api_key': key,
                      'authorized': True,
                      'allow_paid': spec['confirm'] is True}
        started = time.time()
        try:
            resp = call_llm(messages, max_tokens=2400, timeout=90, config=llm_config)
        except LLMError as exc:
            raise ValueError('模型调用失败：%s' % exc)
        content = parse_draft_optimization_result(
            resp['text'], draft_optimization_refs(base, extras),
            (optimization or {}).get('max_body_chars'))
        meta = {'source': 'llm', 'model': resp.get('model'),
                'usage': resp.get('usage') or {},
                'duration_ms': resp.get('duration_ms') or int((time.time() - started) * 1000),
                'run_id': uuid.uuid4().hex[:12]}
    else:
        content = demo_draft_optimization(spec, base, extras)
    payload = draft_optimization_payload(spec, base, content, extras, source=meta['source'])
    payload['context']['industry'] = copy.deepcopy(industry)
    payload['context']['industry_source'] = copy.deepcopy(industry_source)
    if 'industry' in body or base_industry is not None:
        payload['context']['draft_optimization']['industry'] = {
            'status': 'frozen', 'data': copy.deepcopy(industry)}
    else:
        payload['context']['draft_optimization']['industry'] = {'status': 'not_provided'}
    saved = ops.add_draft_version(draft['draft_uid'], **payload,
                                  model=meta['model'], run_id=meta['run_id'],
                                  usage=meta['usage'], duration_ms=meta['duration_ms'])
    return {'ok': True, 'draft': saved}


def _draft_optimize_legacy(body, store, ops, ai):
    draft = ops.get_draft(str(body.get('draft_uid') or ''))
    instruction = _bounded_text(body.get('instruction'), '优化要求', 1000)
    if not instruction:
        raise ValueError('请填写优化要求')
    raw_version = body.get('base_version')
    if type(raw_version) is not int or raw_version <= 0:
        raise ValueError('请明确选择基版本')
    try:
        base_record = ops.get_draft_version(draft['draft_uid'], raw_version)
    except ValueError:
        raise ValueError('基版本不属于该研究稿')
    base_topic = base_record.get('topic') or ''
    base_status = base_record.get('status_json')
    base_context = base_record.get('context_json')
    legacy = not base_topic and not base_status and not base_context
    if legacy:
        base_topic = draft.get('topic') or ''
        base_status = draft.get('status_json') or {}
        base_context = draft.get('context_json') or {}
    source = _research_source_of({'context_json': base_context})
    if source is not None:
        if source.get('kind') == 'topics':
            _verify_b_source_refs(ops, source)
        else:
            _verify_adaptation_source(ops, source)
    if 'industry' in body or _industry_from_context(base_context)[0] is None:
        industry, industry_source = _industry_choose(body, base_context)
        base_context = _industry_apply(base_context, industry, industry_source)
    content, meta = _draft_run(base_status, base_topic, base_context, instruction, ai,
                               body.get('model_mode'), body.get('confirm'),
                               base=base_record.get('content_json') or {},
                               base_version=raw_version)
    saved = ops.add_draft_version(draft['draft_uid'], content, instruction=instruction,
                                  source=meta['source'], model=meta['model'], run_id=meta['run_id'],
                                  usage=meta['usage'], duration_ms=meta['duration_ms'],
                                  topic=base_topic, status=base_status, context=base_context,
                                  base_version=raw_version, legacy_snapshot=legacy)
    return {'ok': True, 'draft': saved}


def draft_optimize(body, store, ops, ai):
    if parse_draft_optimization is None:
        raise ValueError('研究稿优化模块不可用')
    optimization = parse_draft_optimization(body)
    if optimization is None:
        return _draft_optimize_legacy(body, store, ops, ai)
    return _draft_optimize_with_optimization(body, store, ops, ai, optimization)


def script_task_save(body, ops):
    try:
        task_uid = str(body.get('task_uid') or '').strip()
        if task_uid:
            return ops.append_content_version(
                task_uid, body.get('expected_version'), body.get('human_beats'),
                body.get('fact_ids'), body.get('missing'), body.get('run_id'),
                body.get('reference_ids'), body.get('reference_snapshot'),
                body.get('pain_ids'), body.get('pain_snapshot'), body.get('plan'),
                body.get('suggestion_ids'), body.get('suggestion_snapshot'))
        return ops.create_content_task(body)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('保存失败：' + str(exc))


def script_task_approve(body, ops):
    return ops.approve_content_task(body.get('task_uid'), body.get('version'))


def topics_build(body, store, ops):
    strategy = ops.get_strategy()
    if not strategy.get('confirmed'):
        return {'ok': False, 'blocked': '账号策略未确认，只能做研究草稿',
                'candidates': [], 'gap': {'conservative': 6, 'experimental': 4}}
    keyword = str(body.get('keyword') or '').strip()
    if not keyword:
        raise ValueError('请填写关键词')
    pains = ops.list_pains()
    posts = store.state('live').get('posts') or []
    result = topics.build_candidates(keyword, strategy, posts, pains)
    batch_id = uuid.uuid4().hex[:12]
    saved = ops.save_candidates(batch_id, result['candidates'])
    return {'ok': True, 'batch_id': batch_id, 'candidates': saved,
            'gap': result['gap'], 'notes': result.get('notes') or []}


def topics_select(body, ops):
    strategy = ops.get_strategy()
    if not strategy.get('confirmed'):
        raise ValueError('账号策略未确认，不能提交正式组合')
    batch_id = str(body.get('batch_id') or '').strip()
    candidates = ops.get_candidates(batch_id)
    if not candidates:
        raise ValueError('候选批次不存在')
    picked = topics.validate_combo(candidates, body.get('conservative_ids') or [],
                                   body.get('experimental_ids') or [], strategy['version'])
    keys = ('id', 'topic_id', 'topic', 'audience_question', 'lane', 'strategy_version',
            'signals', 'reason', 'hypothesis', 'risk', 'metric', 'expires_at')
    snapshot = [{key: item.get(key) for key in keys} for item in picked]
    combo_uid = str(body.get('combo_uid') or '').strip()
    business_date = str(body.get('business_date') or time.strftime('%Y-%m-%d'))
    existing = ops.get_combo(business_date)
    if not combo_uid:
        combo_uid = existing['combo_uid'] if existing else uuid.uuid4().hex[:12]
    combo = ops.save_combo(combo_uid, business_date, strategy['version'],
                           [picked[0]['id'], picked[1]['id']], [picked[2]['id']],
                           snapshot, body.get('expected_version', 0))
    return {'ok': True, 'combo': combo}


def _simulated_flag(body):
    if not body.get('simulated'):
        return 0
    if os.getenv('RADAR_ALLOW_SIMULATED') != '1':
        raise ValueError('当前实例不允许演练写入')
    return 1


def conversion_get(ops, uid):
    review = ops.get_review(uid)
    if review.get('simulated') or not conversion.is_conversion(review.get('data_json')):
        raise ValueError('不是可用的转化观察报告')
    return review


def feedback_register(body, ops):
    return ops.save_publish_record(
        body.get('task_uid'), body.get('version'), body.get('platform'),
        body.get('platform_post_id'), body.get('url'), body.get('published_at'),
        body.get('source') or 'manual', _simulated_flag(body))


def feedback_metrics(body, ops):
    return ops.save_metric_snapshot(
        body.get('record_uid'), body.get('snapshot_key'), body.get('metrics') or {},
        body.get('source') or 'manual', body.get('collected_at'),
        body.get('definition') or '累计值', _simulated_flag(body))


def feedback_review(body, ops):
    record = ops.get_publish_record(body.get('record_uid'))
    snapshots = ops.list_metric_snapshots(record['record_uid'])
    consultations = ops.list_consultations(record['record_uid'])
    review = reviews.build_review(record, snapshots, consultations)
    review['snapshot_ids'] = [item['id'] for item in snapshots]
    review['record_uid'] = record['record_uid']
    review['data'] = {
        'consultation_ids': [item['note_uid'] for item in consultations],
        'consultation_snapshot': [{key: item.get(key) for key in
                                   ('note_uid', 'text', 'source', 'occurred_at', 'note_key')}
                                  for item in consultations],
        'metric_snapshots': [{key: item.get(key) for key in
                              ('id', 'snapshot_key', 'collected_at', 'definition', 'source', 'metrics')}
                             for item in snapshots],
    }
    return ops.save_review(record['record_uid'], review)


def feedback_consultation(body, ops):
    return {'ok': True, 'consultation': ops.save_consultation(
        body.get('record_uid'), body.get('text'), body.get('source') or 'manual',
        body.get('occurred_at'), body.get('note_key'))}


def _media_review_manuscript(ops, body):
    draft_uid = body.get('draft_uid')
    raw_version = body.get('draft_version')
    if draft_uid in (None, '') and raw_version in (None, ''):
        return None
    if not isinstance(draft_uid, str) or not draft_uid.strip():
        raise ValueError('关联研究稿需同时提供 UID 与正整数版本')
    if type(raw_version) is not int or raw_version <= 0:
        raise ValueError('关联研究稿需同时提供 UID 与正整数版本')
    draft = ops.get_draft(draft_uid)
    try:
        record = ops.get_draft_version(draft_uid, raw_version)
    except ValueError:
        raise ValueError('研究稿版本不存在')
    status = record.get('status_json')
    context = record.get('context_json')
    topic = record.get('topic') or ''
    legacy = int(record.get('legacy_snapshot') or 0)
    if not topic and not status and not context:
        legacy = 1
        topic = draft.get('topic') or ''
        status = draft.get('status_json') or {}
        context = draft.get('context_json') or {}
    content = record.get('content_json') or {}
    markdown = str(content.get('draft_markdown') or '')
    if len(markdown) > 20000:
        raise ValueError('关联研究稿正文超过 20000 字支持范围')
    return {'draft_uid': draft_uid, 'version': raw_version,
            'topic': topic, 'status_json': status or {}, 'context_json': context or {},
            'content_json': content, 'legacy_snapshot': legacy}


def _review_stored_input(input_data):
    stored = dict(input_data)
    stored['frames'] = [{'frame': item['frame'], 'at': item['at'], 'sha256': item['sha256']}
                        for item in input_data['frames']]
    return stored


def media_review_analyze(body, store, ops, ai):
    if validate_input is None:
        raise ValueError('成片审阅模块不可用')
    input_data = validate_input(body)
    manuscript = _media_review_manuscript(ops, body)
    context = _advice_refs(store, ops, body.get('selected') or {})
    if body.get('model_mode') == 'test':
        result = demo_review(input_data, manuscript)
        meta = {'source': 'demo', 'model': None, 'usage': {}, 'duration_ms': 0, 'run_id': None}
    elif body.get('model_mode') == 'real':
        if body.get('confirm') is not True:
            raise ValueError('真实模型调用需本次确认')
        cfg = ai.snapshot() if ai is not None else {}
        endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
        if not endpoint or not model or not key:
            raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
        base_url = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
        llm_config = {'base_url': base_url, 'model': model, 'api_key': key, 'authorized': True,
                      'allow_paid': body.get('confirm') is True}
        system, user = build_review_prompt(input_data, manuscript, extra_context=context)
        content = [{'type': 'text', 'text': user}]
        for item in input_data['frames']:
            content.append({'type': 'text', 'text': '帧%d 时间 %.2f 秒' % (item['frame'], item['at'])})
            content.append({'type': 'image_url', 'image_url': {'url': item['image']}})
        started = time.time()
        try:
            resp = call_llm([{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                            max_tokens=2000, timeout=90, config=llm_config)
        except LLMError as exc:
            raise ValueError('模型调用失败：%s' % exc)
        allowed = {'frame:%d' % index for index in range(1, len(input_data['frames']) + 1)}
        if input_data['transcript']['source'] == 'manual':
            allowed.add('transcript')
        if manuscript:
            allowed.add('manuscript')
            for ref in (manuscript.get('context_json') or {}).get('refs') or []:
                if ref.get('id'):
                    allowed.add(str(ref['id']))
        for ref in context.get('refs') or []:
            if ref.get('id'):
                allowed.add(str(ref['id']))
        result = parse_review(resp['text'], {
            'frame_count': len(input_data['frames']),
            'transcript': input_data['transcript']['source'],
            'manuscript': bool(manuscript),
            'refs': sorted(allowed),
        })
        meta = {'source': 'llm', 'model': resp.get('model'), 'usage': resp.get('usage') or {},
                'duration_ms': resp.get('duration_ms') or int((time.time() - started) * 1000),
                'run_id': uuid.uuid4().hex[:12]}
    else:
        raise ValueError('模型模式无效')
    scope = {'duration': input_data['duration'],
             'frames': [{'frame': item['frame'], 'at': item['at'], 'sha256': item['sha256']}
                        for item in input_data['frames']],
             'transcript': input_data['transcript'],
             'transcript_complete': input_data['transcript_complete'],
             'model_hears_audio': False, 'full_view': False}
    stored_input = _review_stored_input(input_data)
    saved = ops.save_media_review(input_data['goal'], stored_input, scope, context, manuscript, result,
                                  source=meta['source'], model=meta['model'], run_id=meta['run_id'],
                                  usage=meta['usage'], duration_ms=meta['duration_ms'])
    return {'ok': True, 'review': saved}


def _research_refs(store, ops, selected):
    if validate_research_input is None:
        raise ValueError('研究增强模块不可用')
    refs, ref_map = [], {}

    def add(role, text, source, origin, extra=None):
        sid = 's%d' % (len(refs) + 1)
        ref = {'id': sid, 'role': role,
               'label': RESEARCH_ROLE_LABELS.get(role, role),
               'text': str(text or ''), 'source': str(source or '')}
        if extra:
            ref.update(extra)
        refs.append(ref)
        ref_map[sid] = origin

    def when(value):
        try:
            return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(value)))
        except (TypeError, ValueError, OSError):
            return '未提供'

    strategy = ops.get_strategy()
    for ident in selected.get('pain_ids') or []:
        try:
            item = ops.get_pain(ident)
        except ValueError:
            raise ValueError('所选痛点不存在或已归档：%s' % ident)
        add('pain', '痛点：%s\n原摘录：%s\n证据角色：%s\n频次：%s\n来源：%s\n记录时间：%s' % (
            item.get('pain') or '', item.get('evidence') or '', item.get('evidence_role') or '',
            item.get('frequency') if item.get('frequency') is not None else '未提供',
            item.get('source') or '未提供', when(item.get('created_at'))),
            item.get('source') or '',
            {'kind': 'pain', 'id': int(item.get('id') or 0)},
            {'evidence_role': item.get('evidence_role') or '',
             'evidence': item.get('evidence') or ''})
    for ident in selected.get('reference_ids') or []:
        try:
            item = ops.get_reference(ident)
        except ValueError:
            raise ValueError('所选参考不存在或已归档：%s' % ident)
        report = item.get('report') or {}
        scope = item.get('scope') or {}
        observations = '；'.join(str(row.get('evidence') or row.get('text') or '')
                                for row in (report.get('observations') or [])[:12]) or '未提供'
        range_text = scope.get('limitation') or (
            '帧数 %s' % scope.get('frames') if scope.get('frames') else '未提供')
        add('reference', '标题：%s\n摘要：%s\n观察：%s\n观察范围：%s\n来源：%s\n记录时间：%s' % (
            item.get('title') or '', report.get('summary') or '', observations, range_text,
            item.get('source_name') or '未提供', when(item.get('created_at'))),
            item.get('source_name') or '',
            {'kind': 'reference', 'id': int(item.get('id') or 0)})
    if selected.get('draft_uid'):
        try:
            draft = ops.get_draft(selected['draft_uid'])
            record = ops.get_draft_version(selected['draft_uid'], selected['draft_version'])
        except ValueError:
            raise ValueError('所选研究稿版本不存在或不属于该稿件')
        content = record.get('content_json') or {}
        topic = record.get('topic') or ''
        status = record.get('status_json') or {}
        context = record.get('context_json') or {}
        legacy_flag = bool(record.get('legacy_snapshot'))
        # Q02：整组判定用“整个 context 是否为空”，refs 只是它的子字段
        fallback = not topic and not status and not context
        if fallback:
            topic = draft.get('topic') or ''
            status = draft.get('status_json') or {}
            context = draft.get('context_json') or {}
        context_refs = context.get('refs') or [] if isinstance(context, dict) else []
        if fallback:
            note = '（旧记录：无版本快照，已回退稿件级资料）'
        elif legacy_flag:
            note = '（来源曾按旧记录回退；本版本快照完整，以下使用版本自身内容）'
        else:
            note = ''
        refs_text = '\n'.join('- %s：%s' % (ref.get('id'), ref.get('text') or '')
                              for ref in context_refs) or '（未提供）'
        add('draft',
            '版本快照%s\n主题：%s\n业务：%s\n受众：%s\n目标：%s\n资源：%s\n产能：%s\n当前问题：%s\n'
            '正文：\n%s\n该版本冻结资料：\n%s' % (
                note,
                topic, status.get('business') or '未填写', status.get('audience') or '未填写',
                status.get('goal') or '未填写', status.get('resources') or '未填写',
                status.get('capacity') or '未填写', status.get('question') or '未填写',
                content.get('draft_markdown') or '', refs_text),
            '研究稿 %s v%s' % (selected['draft_uid'], selected['draft_version']),
            {'kind': 'draft', 'uid': selected['draft_uid'],
             'version': selected['draft_version'], 'fallback': fallback,
             'legacy_flag': legacy_flag})
    record = None
    if selected.get('record_uid'):
        try:
            record = ops.get_publish_record(selected['record_uid'])
        except ValueError:
            raise ValueError('所选作品登记不存在或已归档')
        if record.get('simulated'):
            raise ValueError('演练登记不能用于研究')
        add('record', '平台 %s · 作品 %s · 版本 v%s · 发布 %s · 登记 %s' % (
            record.get('platform') or '', record.get('platform_post_id') or '',
            record.get('version') or 0, record.get('published_at') or '未提供',
            when(record.get('registered_at'))),
            record.get('source') or '',
            {'kind': 'record', 'uid': selected['record_uid']})
    for ident in selected.get('consultation_ids') or []:
        if record is None:
            raise ValueError('选择咨询摘录时必须同时选择所属作品登记')
        try:
            item = ops.get_consultation(ident)
        except ValueError:
            raise ValueError('所选咨询摘录不存在')
        if item.get('record_uid') != selected['record_uid']:
            raise ValueError('咨询摘录不属于所选作品登记')
        add('consultation', '咨询摘录：%s\n来源：%s\n发生时间：%s' % (
            item.get('text') or '', item.get('source') or '未提供',
            when(item.get('occurred_at')) if item.get('occurred_at') else '未提供'),
            item.get('source') or '', {'kind': 'consultation', 'uid': ident},
            {'excerpt': item.get('text') or ''})
    for ident in selected.get('review_uids') or []:
        if record is None:
            raise ValueError('选择复盘时必须同时选择所属作品登记')
        try:
            item = ops.get_review(ident)
        except ValueError:
            raise ValueError('所选复盘不存在或已归档')
        if item.get('record_uid') != selected['record_uid']:
            raise ValueError('复盘不属于所选作品登记')
        if item.get('simulated'):
            raise ValueError('演练复盘不能用于研究')
        data = item.get('data_json') or {}
        lines = ['复盘 %s（冻结于 %s）' % (ident, when(item.get('created_at')))]
        lines.append('指标快照：')
        metrics = data.get('metric_snapshots') or []
        if metrics:
            for snap in metrics:
                lines.append('- 采集 %s · 口径 %s · 来源 %s · 数值 %s' % (
                    snap.get('collected_at') or '未提供', snap.get('definition') or '未提供',
                    snap.get('source') or '未提供',
                    json.dumps(snap.get('metrics') or {}, ensure_ascii=False)))
        else:
            lines.append('- 未提供')
        lines.append('咨询摘录：')
        notes = data.get('consultation_snapshot') or []
        if notes:
            for note in notes:
                lines.append('- %s（来源 %s；时间 %s）' % (
                    note.get('text') or '', note.get('source') or '未提供',
                    note.get('occurred_at') or '未提供'))
        else:
            lines.append('- 未提供')
        for obs in item.get('observations_json') or []:
            if isinstance(obs, str):
                lines.append('观察：%s（依据：未提供；旧复盘为文本观察）' % obs)
            elif isinstance(obs, dict):
                lines.append('观察：%s（依据：%s）' % (obs.get('text') or '',
                                                obs.get('basis') or '未提供'))
            else:
                raise ValueError('复盘观察格式无效（应为文本或对象）')
        for index, sug in enumerate(item.get('suggestions_json') or [], 1):
            if not isinstance(sug, dict):
                raise ValueError('复盘建议格式无效（应为对象）')
            basis = sug.get('basis')
            basis_text = basis if isinstance(basis, str) else '；'.join(basis or [])
            conditions = sug.get('conditions')
            conditions_text = conditions if isinstance(conditions, str) else '；'.join(conditions or [])
            lines.append('建议%d：%s｜依据：%s｜条件：%s｜待验证：%s' % (
                index, sug.get('text') or '', basis_text or '未提供',
                conditions_text or '未提供', sug.get('pending') or '未提供'))
        add('review', '\n'.join(lines), '复盘 %s' % ident, {'kind': 'review', 'uid': ident})
    for index, item in enumerate(selected.get('manual_excerpts') or []):
        add('manual', '人工摘录（人工提供，未独立核实）：%s' % item['text'],
            item['source'], {'kind': 'manual', 'index': index})
    context = {'topic': None, 'question': None, 'business': None,
               'strategy': {'version': int(strategy.get('version') or 0),
                            'confirmed': bool(strategy.get('confirmed')),
                            'data': strategy.get('data') or {},
                            'updated_at': strategy.get('updated_at') or 0},
               'refs': refs, 'ref_map': ref_map}
    return context


def _research_finish_context(context, input_data):
    context['topic'] = input_data['topic']
    context['question'] = input_data['question']
    context['business'] = input_data['business']
    compact = json.dumps(context, ensure_ascii=False, separators=(',', ':'))
    if len(compact) > 24000:
        largest = max((ref for ref in context['refs']), key=lambda ref: len(ref['text']),
                      default=None)
        where = ('资料 %s[%s] 正文过长' % (largest['id'], largest['label'])
                 if largest else '策略/业务字段过长')
        raise ValueError('研究上下文超过 24000 字符上限（%s），请减少所选资料或缩短正文' % where)
    return context


def research_save(body, store, ops):
    if validate_research_input is None:
        raise ValueError('研究增强模块不可用')
    if isinstance(body, dict) and 'kind' in body:
        if body.get('kind') != 'adaptation':
            raise ValueError('保存类型无效（C 只支持 adaptation；A 请沿用原保存）')
        return research_adaptation_save(body, ops)
    input_data = validate_research_input(body)
    context = _research_refs(store, ops, input_data['selected'])
    industry, industry_source = _industry_choose(body)
    context = _industry_apply(context, industry, industry_source)
    context = _research_finish_context(context, input_data)
    saved = ops.save_research_artifact('research', input_data['topic'], input_data, context, {},
                                       source='manual')
    return {'ok': True, 'artifact': saved}


def research_analyze(body, store, ops, ai):
    if validate_research_input is None:
        raise ValueError('研究增强模块不可用')
    input_data = validate_research_input(body)
    context = _research_refs(store, ops, input_data['selected'])
    industry, industry_source = _industry_choose(body)
    context = _industry_apply(context, industry, industry_source)
    context = _research_finish_context(context, input_data)
    if body.get('model_mode') == 'test':
        result = demo_research(input_data, context)
        meta = {'source': 'demo', 'model': None, 'usage': {}, 'duration_ms': 0, 'run_id': None}
    elif body.get('model_mode') == 'real':
        if body.get('confirm') is not True:
            raise ValueError('真实模型调用需本次确认')
        cfg = ai.snapshot() if ai is not None else {}
        endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
        if not endpoint or not model or not key:
            raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
        base_url = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
        llm_config = {'base_url': base_url, 'model': model, 'api_key': key, 'authorized': True,
                      'allow_paid': body.get('confirm') is True}
        system, user = build_research_prompt(input_data, context)
        user = _append_industry_prompt(user, context.get('industry'))
        started = time.time()
        try:
            resp = call_llm([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                            max_tokens=2400, timeout=90, config=llm_config)
        except LLMError as exc:
            raise ValueError('模型调用失败：%s' % exc)
        result = parse_research(resp['text'], context['ref_map'])
        meta = {'source': 'llm', 'model': resp.get('model'), 'usage': resp.get('usage') or {},
                'duration_ms': resp.get('duration_ms') or int((time.time() - started) * 1000),
                'run_id': uuid.uuid4().hex[:12]}
    else:
        raise ValueError('模型模式无效')
    saved = ops.save_research_artifact('research', input_data['topic'], input_data, context, result,
                                       source=meta['source'])
    return {'ok': True, 'artifact': saved}


_ARTIFACT_UID_RE = re.compile(r'^[a-f0-9]{12}$')
_TOPIC_SOURCE_ID_RE = re.compile(r'^s\d+$')
_TOPIC_CANDIDATE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')


def _artifact_uid(value, name):
    if not isinstance(value, str) or not _ARTIFACT_UID_RE.match(value):
        raise ValueError('%s必须是有效的 12 位记录 UID' % name)
    return value


def _parent_research(ops, parent_uid):
    try:
        parent = ops.get_research_artifact(parent_uid)
    except ValueError:
        raise ValueError('父研究记录不存在或已归档')
    if parent.get('kind') != 'research':
        raise ValueError('指定记录不是 M05-A 研究记录')
    return parent


def _frozen_business_value(value, name):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('父记录业务字段 %s 不是文本' % name)
    value = value.strip()
    if len(value) > 2000:
        raise ValueError('父记录业务字段 %s 超过 2000 字符上限' % name)
    return value


def _verify_origin(ops, origin, record_uid=''):
    """校验单个冻结来源身份仍存在/未归档/非演练/归属；不重载当前正文。"""
    if not isinstance(origin, dict):
        raise ValueError('真实身份无效')
    kind = origin.get('kind')
    if kind in ('pain', 'reference'):
        getter = ops.get_pain if kind == 'pain' else ops.get_reference
        getter(origin.get('id'))
    elif kind == 'draft':
        uid = origin.get('uid')
        version = origin.get('version')
        if not isinstance(uid, str) or not uid.strip():
            raise ValueError('研究稿 UID 无效')
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise ValueError('研究稿版本必须是正整数')
        ops.get_draft(uid)
        ops.get_draft_version(uid, version)
    elif kind == 'record':
        record = ops.get_publish_record(origin.get('uid'))
        if int(record.get('simulated') or 0):
            raise ValueError('演练登记不能用于研究')
    elif kind == 'consultation':
        note = ops.get_consultation(origin.get('uid'))
        if record_uid and note.get('record_uid') != record_uid:
            raise ValueError('咨询摘录不属于所选作品登记')
    elif kind == 'review':
        review = ops.get_review(origin.get('uid'))
        if int(review.get('simulated') or 0):
            raise ValueError('演练复盘不能用于研究')
        if record_uid and review.get('record_uid') != record_uid:
            raise ValueError('复盘不属于所选作品登记')
    elif kind == 'manual':
        index = origin.get('index')
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError('人工摘录身份无效')
    else:
        raise ValueError('未知来源类型')


def _verify_ref_origins(ops, refs, ref_map, limit=12):
    if not isinstance(refs, list) or not isinstance(ref_map, dict):
        raise ValueError('父记录来源格式无效')
    if len(refs) > limit:
        raise ValueError('来源超过 %d 条' % limit)
    ids = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError('父记录来源格式无效')
        ident = ref.get('id')
        if not isinstance(ident, str) or not _TOPIC_SOURCE_ID_RE.match(ident):
            raise ValueError('父记录来源号无效')
        if ident in ids:
            raise ValueError('父记录来源号重复')
        ids.append(ident)
    if set(ids) != set(ref_map.keys()):
        raise ValueError('父记录来源映射与来源不一致')
    record_uid = ''
    for ident in ids:
        origin = ref_map.get(ident)
        if not isinstance(origin, dict):
            raise ValueError('父记录来源 %s 的真实身份无效' % ident)
        if origin.get('kind') == 'record' and isinstance(origin.get('uid'), str):
            record_uid = origin['uid']
    for ident in ids:
        origin = ref_map.get(ident)
        try:
            _verify_origin(ops, origin, record_uid)
        except ValueError as exc:
            raise ValueError('父记录来源 %s 已不可用：%s' % (ident, exc))
    return ids


def _freeze_parent_context(ops, parent):
    input_data = parent.get('input_json')
    context = parent.get('context_json')
    if not isinstance(input_data, dict) or not isinstance(context, dict):
        raise ValueError('父研究记录内容格式无效')
    topic = input_data.get('topic')
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError('父研究记录缺少研究主题')
    topic = topic.strip()
    if len(topic) > 200:
        raise ValueError('父研究记录主题超过 200 字符上限')
    question = input_data.get('question')
    if question is None:
        question = ''
    if not isinstance(question, str):
        raise ValueError('父研究记录问题不是文本')
    raw_business = input_data.get('business')
    if raw_business is None:
        raw_business = {}
    if not isinstance(raw_business, dict):
        raise ValueError('父研究记录业务现状格式无效')
    business = dict((key, _frozen_business_value(raw_business.get(key), key))
                    for key in ('business', 'audience', 'goal', 'resources', 'capacity', 'question'))
    refs = context.get('refs')
    ref_map = context.get('ref_map')
    _verify_ref_origins(ops, refs, ref_map)
    strategy_raw = context.get('strategy')
    if strategy_raw is None:
        strategy_raw = {}
    if not isinstance(strategy_raw, dict):
        raise ValueError('父研究记录策略快照格式无效')
    version = strategy_raw.get('version', 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError('父研究记录策略版本无效')
    confirmed = strategy_raw.get('confirmed', False)
    if confirmed not in (True, False, 0, 1):
        raise ValueError('父研究记录策略确认状态无效')
    data = strategy_raw.get('data')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError('父研究记录策略内容格式无效')
    result = parent.get('result_json')
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise ValueError('父研究记录结果格式无效')
    return {
        'parent': {'artifact_uid': parent.get('artifact_uid') or '',
                   'topic': topic, 'kind': 'research',
                   'source': parent.get('source') or 'manual',
                   'created_at': parent.get('created_at') or 0,
                   'analyzed': bool(result)},
        'parent_input': {'topic': topic, 'question': question.strip(), 'business': business},
        'parent_result': result,
        'strategy': {'version': version, 'confirmed': bool(confirmed),
                     'data': data, 'updated_at': strategy_raw.get('updated_at') or 0},
        'refs': refs,
        'ref_map': ref_map,
        'industry': copy.deepcopy(context.get('industry')),
        'industry_source': copy.deepcopy(context.get('industry_source') or {}),
    }


def _apply_topic_source_roles(ops, raw, present, base):
    if not present:
        raw = []
    if not isinstance(raw, list):
        raise ValueError('source_roles 必须是数组；缺省为 []')
    if len(raw) > 12:
        raise ValueError('source_roles 最多 12 项')
    refs = base['refs']
    ref_map = base['ref_map']
    by_id = dict((ref.get('id'), ref) for ref in refs)
    seen = set()
    declarations = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('source_roles 每项必须是对象')
        if set(item.keys()) != set(('source_id', 'role')):
            raise ValueError('source_roles 每项只能包含 source_id 与 role')
        ident = item.get('source_id')
        role = item.get('role')
        if not isinstance(ident, str) or not _TOPIC_SOURCE_ID_RE.match(ident):
            raise ValueError('source_roles 的 source_id 必须是父来源 sN')
        if ident in seen:
            raise ValueError('source_roles 的 source_id 重复：%s' % ident)
        seen.add(ident)
        ref = by_id.get(ident)
        if ref is None:
            raise ValueError('source_roles 引用了父记录不存在的来源 %s' % ident)
        if ref.get('role') != 'manual' or (ref_map.get(ident) or {}).get('kind') != 'manual':
            raise ValueError('source_roles 只能标注父记录中的人工摘录：%s' % ident)
        if not isinstance(role, str) or role not in TOPIC_DEMAND_ROLES:
            raise ValueError('source_roles 的 role 不是允许的需求角色：%s' % ident)
        declarations.append({'source_id': ident, 'role': role})
    return declarations


_QUESTION_MARKS = ('?', '？')
# R1：只有“原始受众证据”才可自动进入需求角色；user_observation/空原摘录/自有表现一律不升级。
_PAIN_EVIDENCE_ROLES = ('comment_evidence', 'audience_pain')


def _frozen_label_value(text, label):
    """从父 A 冻结 ref 文本读取一行结构化字段（旧快照兼容）；读不到返回 None。"""
    prefix = label + '：'
    for line in str(text or '').splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _frozen_label_values(text, label):
    prefix = label + '：'
    values = []
    for line in str(text or '').splitlines():
        line = line.strip()
        if line.startswith(prefix):
            values.append(line[len(prefix):].strip())
    return values


def _pain_evidence_fields(ref):
    if 'evidence_role' in ref:
        role = ref.get('evidence_role')
        evidence = ref.get('evidence')
        return (role if isinstance(role, str) else None,
                evidence if isinstance(evidence, str) else '')
    text = str(ref.get('text') or '')
    # Q01：旧格式没有结构化字段；正文中的仿标签会造成重复，不能取第一条就相信。
    roles = _frozen_label_values(text, '证据角色')
    excerpts = _frozen_label_values(text, '原摘录')
    if len(roles) != 1 or len(excerpts) != 1:
        return None, ''
    return roles[0], excerpts[0] or ''


def _consultation_excerpt_field(ref):
    if 'excerpt' in ref:
        return ref.get('excerpt') if isinstance(ref.get('excerpt'), str) else ''
    return _frozen_label_value(str(ref.get('text') or ''), '咨询摘录') or ''


def _is_structural_question(text):
    """R1：只按结构性问句判定明确问题，不做关键词语义分类。"""
    text = str(text or '').strip()
    if not text:
        return False
    # Q02：引号/代码/日志中的问号只是字符，不是提问。
    cleaned = re.sub(r'“[^”]*”|《[^》]*》|「[^」]*」|『[^』]*』|`[^`]*`|\"[^\"]*\"|\'[^\']*\'', '', text)
    if not any(mark in cleaned for mark in _QUESTION_MARKS):
        return False
    core = cleaned
    for mark in _QUESTION_MARKS:
        core = core.replace(mark, '')
    core = core.strip(' \t\r\n，,。.；;：:!！、')
    if len(core) < 2:
        return False
    return re.search(r'[0-9A-Za-z\u4e00-\u9fff]', core) is not None


def _topics_demand_roles(base, declarations):
    """R1：按父 A 冻结证据角色/原摘录保守认定需求；不靠容器名称自动升级。"""
    declared = dict((item['source_id'], item['role']) for item in declarations)
    demand_roles = {}
    notes = []
    by_id = dict((ref.get('id'), ref) for ref in base['refs'])
    for ref in base['refs']:
        ident = ref.get('id')
        kind = ref.get('role')
        demand_role = None
        reason = ''
        if kind == 'pain':
            evidence_role, excerpt = _pain_evidence_fields(ref)
            if evidence_role is None:
                reason = '父快照缺少可判断的证据角色结构化信息，保守视为背景'
            elif evidence_role not in _PAIN_EVIDENCE_ROLES:
                reason = ('痛点证据角色为 %s，不是可归类的原始受众证据'
                          '（用户观察/自有表现不构成需求）' % (evidence_role or '未标注'))
            elif not excerpt.strip():
                reason = '痛点原摘录为空，不能作为需求原文'
            else:
                demand_role = 'audience_pain'
        elif kind == 'consultation':
            excerpt = _consultation_excerpt_field(ref)
            if not excerpt.strip():
                reason = '咨询摘录为空，不能作为需求原文'
            elif not _is_structural_question(excerpt):
                reason = '咨询摘录不是明确问题（缺少结构性问句），不能认定为明确需求'
            else:
                demand_role = 'audience_pain'
        elif kind == 'manual' and ident in declared:
            demand_role = declared[ident]
        if demand_role:
            demand_roles[ident] = demand_role
        elif kind in ('pain', 'consultation'):
            notes.append({'source_id': ident, 'role': kind, 'reason': reason})
    enriched = []
    for item in declarations:
        ident = item['source_id']
        if ident not in by_id:
            raise ValueError('source_roles 引用了父记录不存在的来源 %s' % ident)
        enriched.append({'source_id': ident, 'role': item['role'],
                         'role_label': TOPIC_DEMAND_ROLE_LABELS.get(item['role'], item['role']),
                         'note': '人工声明，未独立核实'})
    return demand_roles, enriched, notes


def _topics_finish_context(base, declarations):
    demand_roles, enriched, demand_notes = _topics_demand_roles(base, declarations)
    context = {
        'parent': base['parent'], 'parent_input': base['parent_input'],
        'parent_result': base['parent_result'], 'strategy': base['strategy'],
        'refs': base['refs'], 'ref_map': base['ref_map'],
        'source_roles': enriched, 'demand_roles': demand_roles,
        'demand_notes': demand_notes,
        'industry': copy.deepcopy(base.get('industry')),
        'industry_source': copy.deepcopy(base.get('industry_source') or {}),
        'limits': {'max_context_chars': 24000, 'max_candidates': TOPIC_MAX_CANDIDATES},
    }
    compact = json.dumps(context, ensure_ascii=False, separators=(',', ':'))
    if len(compact) > 24000:
        largest = max((ref for ref in context['refs']),
                      key=lambda ref: len(ref.get('text') or ''), default=None)
        where = ('资料 %s 原文过长' % largest.get('id') if largest else '父记录结果/策略过长')
        raise ValueError('选题上下文超过 24000 字符上限（%s），请减少父记录资料或缩短正文' % where)
    return context


def _topic_mode(body):
    mode = body.get('model_mode')
    if mode == 'test':
        return 'test'
    if mode == 'real':
        return 'real'
    raise ValueError('模型模式无效')


def research_topics(body, store, ops, ai):
    if build_topics_prompt is None:
        raise ValueError('选题建议模块不可用')
    # R4：model_mode 与 confirm 为必填契约；confirm 必须严格 bool（test/real 都校验）。
    mode = _topic_mode(body)
    confirm = body.get('confirm')
    if not isinstance(confirm, bool):
        raise ValueError('confirm 必须是布尔值（true/false）')
    parent_uid = _artifact_uid(body.get('parent_uid'), '父研究记录 UID')
    parent = _parent_research(ops, parent_uid)
    if 'industry' in body:
        raise ValueError('B 选题沿用父研究模板，不提供独立模板选择')
    base = _freeze_parent_context(ops, parent)
    industry, industry_source = _industry_choose({}, base)
    industry_source['parent_kind'] = 'research'
    industry_source['parent_uid'] = parent_uid
    base = _industry_apply(base, industry, industry_source)
    declarations = _apply_topic_source_roles(ops, body.get('source_roles'),
                                             'source_roles' in body, base)
    context = _topics_finish_context(base, declarations)
    if mode == 'test':
        result = demo_topics(context)
        meta = {'source': 'demo', 'model': None, 'usage': {}, 'duration_ms': 0, 'run_id': None}
    else:
        if confirm is not True:
            raise ValueError('真实模型调用需本次确认')
        cfg = ai.snapshot() if ai is not None else {}
        endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
        if not endpoint or not model or not key:
            raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
        base_url = endpoint[:-len('/chat/completions')] if endpoint.endswith('/chat/completions') else endpoint
        llm_config = {'base_url': base_url, 'model': model, 'api_key': key, 'authorized': True,
                      'allow_paid': confirm is True}
        system, user = build_topics_prompt(context)
        user = _append_industry_prompt(user, context.get('industry'))
        started = time.time()
        try:
            resp = call_llm([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                            max_tokens=2600, timeout=90, config=llm_config)
        except LLMError as exc:
            raise ValueError('模型调用失败：%s' % exc)
        result = parse_topics(resp['text'], context['ref_map'].keys(),
                              context['demand_roles'].keys(),
                              bool(context['strategy'].get('confirmed')))
        meta = {'source': 'llm', 'model': resp.get('model'), 'usage': resp.get('usage') or {},
                'duration_ms': resp.get('duration_ms') or int((time.time() - started) * 1000),
                'run_id': uuid.uuid4().hex[:12]}
    input_data = {'parent_uid': parent_uid, 'source_roles': declarations, 'model_mode': mode}
    saved = ops.save_research_artifact('topics', context['parent_input']['topic'], input_data,
                                       context, result, source=meta['source'],
                                       parent_uid=parent_uid)
    return {'ok': True, 'artifact': saved}


def _draft_source_ref_id(origin):
    kind = origin.get('kind')
    if kind == 'pain':
        return 'pain:%s' % origin.get('id')
    if kind == 'reference':
        return 'ref:%s' % origin.get('id')
    if kind == 'consultation':
        return 'note:%s' % origin.get('uid')
    if kind == 'review':
        return 'review:%s' % origin.get('uid')
    if kind == 'draft':
        return 'draft:%s' % origin.get('uid')
    if kind == 'record':
        return 'record:%s' % origin.get('uid')
    # R1-B：人工摘录的来源 ID 必须带所属快照范围，否则父 B 与本次同 index 会串成一条。
    scope = origin.get('scope') or ''
    if scope:
        return 'manual:%s:%s' % (scope, origin.get('index'))
    return 'manual:%s' % origin.get('index')


def _draft_status_from_parent(context):
    input_data = context.get('parent_input') or {}
    business = input_data.get('business') or {}
    status = {}
    for key in ('business', 'audience', 'goal', 'resources', 'capacity', 'question'):
        value = business.get(key)
        if value is None:
            value = ''
        if not isinstance(value, str):
            raise ValueError('父记录业务字段 %s 不是文本' % key)
        value = value.strip()
        if len(value) > 2000:
            raise ValueError('父记录业务字段 %s 超过 2000 字符上限' % key)
        status[key] = value
    if not status.get('question'):
        status['question'] = str(input_data.get('question') or '').strip()[:2000]
    return status


def _topic_candidate_refs(context, candidate):
    ref_map = context.get('ref_map') or {}
    refs = context.get('refs') or []
    by_id = dict((ref.get('id'), ref) for ref in refs)
    demand_roles = context.get('demand_roles') or {}
    declarations = dict((item.get('source_id'), item) for item in context.get('source_roles') or [])
    out, chain, seen = [], [], set()
    for sid in candidate.get('basis') or []:
        ref = by_id.get(sid)
        origin = ref_map.get(sid)
        if ref is None or not isinstance(origin, dict):
            raise ValueError('候选依据 %s 不在该选题记录的冻结来源中' % sid)
        rid = _draft_source_ref_id(origin)
        if rid in seen:
            continue
        seen.add(rid)
        declaration = declarations.get(sid)
        identity = ['kind=%s' % origin.get('kind')]
        if origin.get('id') is not None:
            identity.append('id=%s' % origin.get('id'))
        if origin.get('uid'):
            identity.append('uid=%s' % origin['uid'])
        if origin.get('version'):
            identity.append('version=%s' % origin['version'])
        if origin.get('index') is not None:
            identity.append('index=%s' % origin['index'])
        note = ''
        if declaration:
            note = '\n人工声明需求角色：%s（人工声明，未独立核实）' % (
                TOPIC_DEMAND_ROLE_LABELS.get(declaration.get('role'), declaration.get('role')))
        text = '%s（M05-B 冻结来源 %s）：%s\n出处：%s\n真实身份：%s%s' % (
            RESEARCH_ROLE_LABELS.get(ref.get('role'), ref.get('role') or '来源'),
            sid, ref.get('text') or '', ref.get('source') or '未提供',
            '，'.join(identity), note)
        out.append({'id': rid, 'text': text, 'role': ref.get('role'),
                    'source': ref.get('source') or '',
                    'origin': origin, 'demand_role': demand_roles.get(sid) or ''})
        chain.append({'source_id': sid, 'role': ref.get('role'),
                      'demand_role': demand_roles.get(sid) or '',
                      'label': ref.get('label') or '', 'text': ref.get('text') or '',
                      'source': ref.get('source') or '', 'origin': origin,
                      'declaration': declaration or None})
    return out, chain


def research_to_draft(body, ops):
    if parse_topics is None:
        raise ValueError('选题建议模块不可用')
    if not isinstance(body, dict):
        raise ValueError('请求格式无效')
    extra = set(body.keys()) - set(('artifact_uid', 'candidate_id'))
    if extra:
        raise ValueError('转为研究稿输入只接受 artifact_uid 与 candidate_id，不接受覆盖字段')
    artifact_uid = _artifact_uid(body.get('artifact_uid'), '选题记录 UID')
    candidate_id = body.get('candidate_id')
    if not isinstance(candidate_id, str) or not _TOPIC_CANDIDATE_ID_RE.fullmatch(candidate_id):
        raise ValueError('candidate_id 必须是 1–20 位 [A-Za-z0-9_-] 字符串')
    try:
        artifact = ops.get_research_artifact(artifact_uid)
    except ValueError:
        raise ValueError('选题记录不存在或已归档')
    if artifact.get('kind') != 'topics':
        raise ValueError('指定记录不是选题建议记录')
    parent_uid = artifact.get('parent_uid')
    if not isinstance(parent_uid, str) or not _ARTIFACT_UID_RE.match(parent_uid):
        raise ValueError('选题记录缺少有效的父研究记录')
    parent = _parent_research(ops, parent_uid)
    if parent.get('artifact_uid') != parent_uid:
        raise ValueError('父研究记录不一致')
    context = artifact.get('context_json')
    if not isinstance(context, dict) or not isinstance(context.get('parent_input'), dict):
        raise ValueError('选题记录冻结上下文格式无效')
    failed_parent = context.get('parent') or {}
    if failed_parent.get('artifact_uid') != parent_uid:
        raise ValueError('选题记录冻结上下文与父记录不一致')
    refs = context.get('refs') or []
    ref_map = context.get('ref_map') or {}
    _verify_ref_origins(ops, refs, ref_map)
    result = artifact.get('result_json') or {}
    rows = result.get('candidates') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise ValueError('选题记录结果格式无效')
    candidate = None
    legacy_id = False
    for row in rows:
        if isinstance(row, dict) and row.get('id') == candidate_id:
            candidate = row
            break
    if candidate is None:
        # 旧整数 ID 历史记录：只按字符串精确命中兼容分支，不做 parseInt/Number。
        for row in rows:
            if (isinstance(row, dict) and isinstance(row.get('id'), int)
                    and not isinstance(row.get('id'), bool)
                    and 1 <= row['id'] <= 20 and str(row['id']) == candidate_id):
                candidate = row
                legacy_id = True
                break
    if candidate is None:
        raise ValueError('候选不属于该选题记录')
    strategy = context.get('strategy') or {}
    confirmed = bool(strategy.get('confirmed')) if isinstance(strategy, dict) else False
    clean = validate_topic_candidate(candidate, set(ref_map.keys()),
                                     set((context.get('demand_roles') or {}).keys()),
                                     confirmed, candidate_id, legacy_ids=legacy_id)
    topic = validate_topic(clean['topic'])
    status = _draft_status_from_parent(context)
    refs_out, chain = _topic_candidate_refs(context, clean)
    expert_industry, industry_status = _industry_from_context(context)
    if expert_industry is None and industry_status.get('status') == 'legacy_invalid':
        raise ValueError('选题记录的旧内容领域模板不可用，不能转入')
    if expert_industry is None:
        expert_industry = build_industry_snapshot(DEFAULT_INDUSTRY_CODE)
        industry_source = {'type': 'default', 'code': DEFAULT_INDUSTRY_CODE,
                           'parent_kind': 'topics', 'parent_uid': artifact_uid}
        if industry_status.get('status') != 'legacy_missing':
            industry_source['legacy_status'] = industry_status.get('status')
    else:
        industry_source = {'type': 'inherited', 'code': expert_industry['code'],
                           'parent_kind': 'topics', 'parent_uid': artifact_uid}
    research_source = {
        'kind': 'topics', 'artifact_uid': artifact_uid, 'parent_uid': parent_uid,
        'candidate_id': clean['id'], 'candidate': clean,
        'topic': clean['topic'], 'state': clean['state'],
        'source': artifact.get('source') or 'manual',
        'parent_topic': (context.get('parent_input') or {}).get('topic') or '',
        'parent_business': status, 'strategy': strategy,
        'source_roles': context.get('source_roles') or [],
        'basis_chain': chain, 'refs': refs_out,
        'industry': copy.deepcopy(expert_industry),
        'industry_source': copy.deepcopy(industry_source),
        'note': ('本稿由 M05-B 语义选题建议转入；候选文本是模型/演示建议，不是事实；'
                 '研究状态不表示需求已验证，也不代表正式选题或批准。'),
    }
    draft_context = {'refs': refs_out, 'read_errors': [],
                     'strategy_confirmed': confirmed,
                     'has_metrics': any((ref_map.get(sid) or {}).get('kind') in ('record', 'metrics')
                                        for sid in clean.get('basis') or []),
                     'research_source': research_source}
    draft_context = _industry_apply(draft_context, expert_industry, industry_source)
    saved = ops.save_draft(topic, status, draft_context)
    return {'ok': True, 'draft': saved}


# ---------------------------------------------------------------------------
# M05-C 参考适配：明确主题/候选 + 一条明确外部参考 → 适配计划；零模型转 M02。
# 复用 research_artifact(kind=adaptation) 与 research_draft，不新增表。
# ---------------------------------------------------------------------------

_C_UID_RE = re.compile(r'^[a-f0-9]{12}$')
_C_BIZ_ORIGIN_KINDS = ('pain', 'record', 'consultation', 'manual', 'metrics')
_C_FIELDS = ('business', 'audience', 'goal', 'resources', 'capacity', 'question')


def _c_uid(value, name):
    if not isinstance(value, str) or not _C_UID_RE.match(value):
        raise ValueError('%s必须是有效的 12 位记录 UID' % name)
    return value


def _c_when(value):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return '未提供'


def _c_business_value(value, name):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('%s不是文本' % name)
    value = value.strip()
    if len(value) > 2000:
        raise ValueError('%s超过 2000 字符上限' % name)
    return value


def _c_business(values):
    return dict((key, _c_business_value((values or {}).get(key), '业务字段 %s' % key))
                for key in _C_FIELDS)


def _c_current_strategy(ops):
    try:
        strategy = ops.get_strategy()
    except ValueError:
        strategy = {}
    version = strategy.get('version') or 0
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        version = 0
    data = strategy.get('data')
    return {'version': version, 'confirmed': bool(strategy.get('confirmed')),
            'data': data if isinstance(data, dict) else {},
            'updated_at': strategy.get('updated_at') or 0}


def _c_resolve_candidate(ops, subject):
    """加载指定 B 及其候选；只取该候选自己的主题/链路，不取最新 B 或首候选。"""
    try:
        artifact = ops.get_research_artifact(subject['artifact_uid'])
    except ValueError:
        raise ValueError('所选 B 选题记录不存在或已归档')
    if artifact.get('kind') != 'topics':
        raise ValueError('指定记录不是 M05-B 选题建议')
    parent_uid = artifact.get('parent_uid')
    if not isinstance(parent_uid, str) or not _ARTIFACT_UID_RE.match(parent_uid):
        raise ValueError('选题记录缺少有效的父研究记录')
    parent = _parent_research(ops, parent_uid)
    if parent.get('artifact_uid') != parent_uid:
        raise ValueError('父研究记录不一致')
    context = artifact.get('context_json')
    if not isinstance(context, dict) or not isinstance(context.get('parent_input'), dict):
        raise ValueError('选题记录冻结上下文格式无效')
    frozen_parent = context.get('parent') or {}
    if frozen_parent.get('artifact_uid') != parent_uid:
        raise ValueError('选题记录冻结上下文与父记录不一致')
    refs = context.get('refs') or []
    ref_map = context.get('ref_map') or {}
    _verify_ref_origins(ops, refs, ref_map)
    result = artifact.get('result_json') or {}
    rows = result.get('candidates') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise ValueError('选题记录结果格式无效')
    candidate = None
    legacy_id = False
    for row in rows:
        if isinstance(row, dict) and row.get('id') == subject['candidate_id']:
            candidate = row
            break
    if candidate is None:
        for row in rows:
            if (isinstance(row, dict) and isinstance(row.get('id'), int)
                    and not isinstance(row.get('id'), bool)
                    and 1 <= row['id'] <= 20
                    and str(row['id']) == subject['candidate_id']):
                candidate = row
                legacy_id = True
                break
    if candidate is None:
        raise ValueError('候选不属于该选题记录')
    strategy = context.get('strategy') or {}
    if not isinstance(strategy, dict):
        raise ValueError('选题记录策略快照格式无效')
    version = strategy.get('version') or 0
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError('选题记录策略版本无效')
    confirmed = strategy.get('confirmed', False)
    if confirmed not in (True, False, 0, 1):
        raise ValueError('选题记录策略确认状态无效')
    data = strategy.get('data')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError('选题记录策略内容格式无效')
    clean = validate_topic_candidate(candidate, set(ref_map.keys()),
                                     set((context.get('demand_roles') or {}).keys()),
                                     bool(confirmed), subject['candidate_id'],
                                     legacy_ids=legacy_id)
    return {'artifact': artifact, 'parent': parent, 'context': context,
            'candidate': clean,
            'strategy': {'version': version, 'confirmed': bool(confirmed),
                         'data': data, 'updated_at': strategy.get('updated_at') or 0}}


def _c_reference_snapshot(ops, reference_id, chain_rows):
    """加载本次明确选择的参考；若同一身份属于 B 选中候选冻结链路，以 B 冻结正文为准。"""
    try:
        item = ops.get_reference(reference_id)
    except ValueError:
        raise ValueError('所选参考不存在或已归档：%s' % reference_id)
    report = item.get('report') or {}
    scope = item.get('scope') or {}
    summary = str(report.get('summary') or '')
    observations = '；'.join(str(row.get('evidence') or row.get('text') or '')
                            for row in (report.get('observations') or [])[:12]) or '未提供'
    range_text = scope.get('limitation') or (
        '帧数 %s' % scope.get('frames') if scope.get('frames') else '未提供')
    for row in chain_rows or []:
        origin = row.get('origin') or {}
        if origin.get('kind') == 'reference' and origin.get('id') == reference_id:
            text = row.get('text') or ''
            # R1-C：标题/观察范围也只从 B 冻结文本取，与正文/出处同一快照口径；
            # 取不到就写“父快照未提供独立字段”，不拿当前记录的新值伪装当时内容。
            return {'snapshot_source': 'b_frozen',
                    'title': _c_frozen_field(text, '标题'),
                    'source': row.get('source') or '',
                    'scope': _c_frozen_field(text, '观察范围'),
                    'created_at': _c_when(item.get('created_at')),
                    'excerpt': text[:200], 'text': text,
                    'note': '该身份属于所选 B 候选的冻结链路：正文、出处、观察范围与标题均取自'
                            'B 冻结快照文本，标题/范围取不到时写“%s”，不混入当前同 ID 记录的'
                            '新正文/新标题/新范围。' % _C_FROZEN_MISSING}
    text = '标题：%s\n摘要：%s\n观察：%s\n观察范围：%s\n来源：%s\n记录时间：%s' % (
        item.get('title') or '', summary, observations, range_text,
        item.get('source_name') or '未提供', _c_when(item.get('created_at')))
    return {'snapshot_source': 'current', 'title': item.get('title') or '',
            'source': item.get('source_name') or '',
            'scope': range_text, 'created_at': _c_when(item.get('created_at')),
            'excerpt': text[:200], 'text': text,
            'note': '本次明确选择的外部参考；按原记录摘要、出处、观察范围与时间冻结。'}


_C_FROZEN_MISSING = '父快照未提供独立字段'
_C_FROZEN_TITLE_RES = (re.compile(r'标题[：:][ \t]*([^\n]+)'),
                       re.compile(r'《([^》\n]+)》'))
_C_FROZEN_SCOPE_RE = re.compile(r'观察范围[：:][ \t]*([^\n；;]+)')


def _c_frozen_field(text, label):
    """从父冻结文本中取可确定的标题/观察范围；取不到返回缺字段标记，不做通用文本解析。"""
    if not isinstance(text, str) or not text:
        return _C_FROZEN_MISSING
    candidates = _C_FROZEN_TITLE_RES if label == '标题' else (_C_FROZEN_SCOPE_RE,)
    for pattern in candidates:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return _C_FROZEN_MISSING


def _c_identity(origin):
    kind = origin.get('kind') if isinstance(origin, dict) else None
    if kind in ('pain', 'reference'):
        return (kind, int(origin.get('id') or 0))
    if kind in ('draft', 'record', 'consultation', 'review'):
        return (kind, origin.get('uid'), int(origin.get('version') or 0))
    if kind == 'manual':
        # R1-B：人工摘录的局部 index 只在所属快照/选择集内有意义，
        # B 的第 0 条与本次另选的第 0 条不是同一条资料。
        return (kind, str(origin.get('scope') or ''), int(origin.get('index') or 0))
    return (kind, str(origin))


def _adaptation_context(ops, input_data, industry_value=_INDUSTRY_MISSING):
    """冻结 C 实际输入、策略、来源映射与全部原资料；上下文超限受控拒绝。"""
    subject = input_data['subject']
    chain_in = []
    b_context = None
    if subject['kind'] == 'candidate':
        resolved = _c_resolve_candidate(ops, subject)
        artifact_b = resolved['artifact']
        b_context = resolved['context']
        candidate = resolved['candidate']
        topic = validate_topic(candidate['topic'])
        business = _c_business((b_context.get('parent_input') or {}).get('business'))
        strategy = resolved['strategy']
        chain_in = _topic_candidate_refs(b_context, candidate)[1]
        parent_info = {'artifact_uid': artifact_b['artifact_uid'],
                       'parent_uid': resolved['parent']['artifact_uid'],
                       'candidate_id': candidate['id'],
                       'topic': candidate['topic'],
                       'state': candidate['state'],
                       'source': artifact_b.get('source') or 'manual'}
    else:
        topic = validate_topic(subject['topic'])
        business = _c_business(subject['business'])
        strategy = _c_current_strategy(ops)
        candidate = None
        parent_info = None
    # R1-A/R1-B：先确定 B 冻结链路的身份与来源范围。同身份 selected 只做可用性校验，
    # 不得用当前正文/标题覆盖 B 冻结快照；不同身份的新选择仍按本次输入进入。
    chain_rows = []
    chain_identities = set()
    parent_scope = ('parent:%s' % parent_info['artifact_uid']) if parent_info else ''
    if parent_info is not None:
        for row in chain_in:
            if not isinstance(row, dict):
                raise ValueError('选题记录来源链路格式无效')
            origin = row.get('origin')
            if not isinstance(origin, dict):
                raise ValueError('选题记录来源链路缺少真实身份')
            frozen_origin = dict(origin)
            if frozen_origin.get('kind') == 'manual':
                # 人工摘录身份带所属快照范围：B 的第 0 条与本次另选的第 0 条不是同一条资料。
                frozen_origin.setdefault('scope', parent_scope)
            chain_rows.append((row, frozen_origin))
            chain_identities.add(_c_identity(frozen_origin))
    snapshot = _c_reference_snapshot(ops, input_data['reference_id'], chain_in)
    refs, ref_map, identity_sids = [], {}, {}

    def add(role, text, source, origin, identity):
        sid = 's%d' % (len(refs) + 1)
        refs.append({'id': sid, 'role': role,
                     'label': RESEARCH_ROLE_LABELS.get(role, role),
                     'text': str(text or ''), 'source': str(source or '')})
        ref_map[sid] = origin
        if identity is not None:
            identity_sids[identity] = sid
        return sid

    reference_sid = add(
        'reference', snapshot['text'], snapshot['source'],
        {'kind': 'reference', 'id': int(input_data['reference_id']),
         'snapshot': snapshot['snapshot_source']},
        ('reference', int(input_data['reference_id'])))
    snapshot.pop('text', None)
    selected = input_data['selected']
    for pain_id in selected['pain_ids']:
        try:
            item = ops.get_pain(pain_id)
        except ValueError:
            raise ValueError('所选痛点不存在或已归档：%s' % pain_id)
        identity = ('pain', int(item.get('id') or 0))
        if identity in chain_identities:
            # 冻结正文/出处/角色已由 B 链路提供；本次只做当前有效性校验，不覆写。
            continue
        text = '痛点：%s\n原摘录：%s\n证据角色：%s\n频次：%s\n来源：%s\n记录时间：%s' % (
            item.get('pain') or '', item.get('evidence') or '',
            item.get('evidence_role') or '',
            item.get('frequency') if item.get('frequency') is not None else '未提供',
            item.get('source') or '未提供', _c_when(item.get('created_at')))
        add('pain', text, item.get('source') or '',
            {'kind': 'pain', 'id': identity[1]}, identity)
    if selected['draft_uid']:
        draft_uid = selected['draft_uid']
        draft_version = selected['draft_version']
        try:
            draft = ops.get_draft(draft_uid)
            record = ops.get_draft_version(draft_uid, draft_version)
        except ValueError:
            raise ValueError('所选研究稿版本不存在或不属于该稿件')
        content = record.get('content_json') or {}
        version_topic = record.get('topic') or ''
        version_status = record.get('status_json') or {}
        version_context = record.get('context_json') or {}
        legacy_flag = bool(record.get('legacy_snapshot'))
        fallback = not version_topic and not version_status and not version_context
        if fallback:
            version_topic = draft.get('topic') or ''
            version_status = draft.get('status_json') or {}
            version_context = draft.get('context_json') or {}
        context_refs = version_context.get('refs') or [] \
            if isinstance(version_context, dict) else []
        refs_text = '\n'.join('- %s：%s' % (ref.get('id'), ref.get('text') or '')
                              for ref in context_refs) or '（未提供）'
        note = ('（旧记录：无版本快照，已回退稿件级资料）' if fallback else
                '（来源曾按旧记录回退；本版本快照完整）' if legacy_flag else '')
        text = ('版本快照%s\n主题：%s\n业务：%s\n受众：%s\n目标：%s\n资源：%s\n产能：%s\n'
                '当前问题：%s\n正文：\n%s\n该版本冻结资料：\n%s' % (
                    note, version_topic,
                    version_status.get('business') or '未填写',
                    version_status.get('audience') or '未填写',
                    version_status.get('goal') or '未填写',
                    version_status.get('resources') or '未填写',
                    version_status.get('capacity') or '未填写',
                    version_status.get('question') or '未填写',
                    content.get('draft_markdown') or '', refs_text))
        if ('draft', draft_uid, draft_version) not in chain_identities:
            # R1：同稿件版本已在 B 冻结链路中时，冻结正文/六字段/资料已在，本次只校验可用性。
            add('draft', text, '研究稿 %s v%s' % (draft_uid, draft_version),
                {'kind': 'draft', 'uid': draft_uid, 'version': draft_version,
                 'fallback': fallback, 'legacy_flag': legacy_flag},
                ('draft', draft_uid, draft_version))
    for index, item in enumerate(selected['manual_excerpts']):
        # R1-B：本次人工摘录带“本次选择”来源范围，不与父 B 同 index 摘录合并。
        add('manual', '人工摘录（人工提供，未独立核实）：%s' % item['text'],
            item['source'],
            {'kind': 'manual', 'index': index, 'scope': 'selected:this-run'},
            ('manual', 'selected:this-run', index))
    chain_out = []
    for row, origin in chain_rows:
        identity = _c_identity(origin)
        sid = identity_sids.get(identity)
        reused = sid is not None
        if not reused:
            sid = add(row.get('role') or 'reference', row.get('text') or '',
                      row.get('source') or '', dict(origin), identity)
        chain_out.append({'source_id': sid,
                          'parent_sid': row.get('source_id') or '',
                          'role': row.get('role') or 'reference',
                          'label': row.get('label') or '',
                          'text': row.get('text') or '',
                          'source': row.get('source') or '',
                          'origin': dict(origin),
                          'demand_role': row.get('demand_role') or '',
                          'declaration': row.get('declaration'),
                          'reused': reused})
    business_ids = []
    for sid in ref_map:
        if ref_map[sid].get('kind') in _C_BIZ_ORIGIN_KINDS and sid not in business_ids:
            business_ids.append(sid)
    subject_context = dict(subject, topic=topic, business=business)
    if candidate is not None:
        subject_context['candidate'] = candidate
    context = {'topic': topic,
               'subject': subject_context,
               'business': business, 'strategy': strategy,
               'reference': snapshot, 'refs': refs, 'ref_map': ref_map,
               'business_source_ids': business_ids,
               'input': dict(input_data, kind='adaptation'),
               'instruction': input_data.get('instruction') or '',
               'limits': {'max_context_chars': 24000, 'max_patterns': 12,
                          'max_selected': 12, 'max_basis': 12}}
    if parent_info is not None:
        context['parent'] = parent_info
        context['candidate'] = candidate
        context['basis_chain'] = chain_out
    choose_body = {'industry': industry_value} if industry_value is not _INDUSTRY_MISSING else {}
    industry, industry_source = _industry_choose(choose_body, b_context)
    if parent_info is not None:
        industry_source['parent_kind'] = 'topics'
        industry_source['parent_uid'] = artifact_b['artifact_uid']
        industry_source['parent_version'] = 0
    context = _industry_apply(context, industry, industry_source)
    compact = json.dumps(context, ensure_ascii=False, separators=(',', ':'))
    if len(compact) > 24000:
        raise ValueError('适配上下文超过 24000 字符上限（当前约 %d 字符），'
                         '请减少参考或缩短所选资料' % len(compact))
    return context


def research_adaptation_save(body, ops):
    if validate_adaptation_input is None:
        raise ValueError('参考适配模块不可用')
    if not isinstance(body, dict) or body.get('kind') != 'adaptation':
        raise ValueError('保存类型无效')
    data = validate_adaptation_input({key: value for key, value in body.items()
                                      if key != 'industry'}, require_mode=False)
    context = _adaptation_context(ops, data, body.get('industry', _INDUSTRY_MISSING))
    parent_uid = (context.get('parent') or {}).get('artifact_uid') or ''
    saved = ops.save_research_artifact('adaptation', context['topic'],
                                       context['input'], context, {},
                                       source='manual', parent_uid=parent_uid)
    return {'ok': True, 'artifact': saved}


def research_adaptation(body, store, ops, ai):
    if validate_adaptation_input is None or build_adaptation_prompt is None:
        raise ValueError('参考适配模块不可用')
    data = validate_adaptation_input({key: value for key, value in body.items()
                                      if key != 'industry'})
    context = _adaptation_context(ops, data, body.get('industry', _INDUSTRY_MISSING))
    mode = data['model_mode']
    confirm = data['confirm']
    if mode == 'test':
        result = demo_adaptation(context)
        meta = {'source': 'demo', 'model': None, 'usage': {}, 'duration_ms': 0, 'run_id': None}
    else:
        if confirm is not True:
            raise ValueError('真实模型调用需本次确认')
        cfg = ai.snapshot() if ai is not None else {}
        endpoint, model, key = cfg.get('endpoint') or '', cfg.get('model') or '', cfg.get('key') or ''
        if not endpoint or not model or not key:
            raise ValueError('请先在 AI 模型设置中配置服务地址、模型和密钥')
        base_url = endpoint[:-len('/chat/completions')] \
            if endpoint.endswith('/chat/completions') else endpoint
        llm_config = {'base_url': base_url, 'model': model, 'api_key': key,
                      'authorized': True,
                      'allow_paid': confirm is True}
        system, user = build_adaptation_prompt(context)
        user = _append_industry_prompt(user, context.get('industry'))
        started = time.time()
        try:
            resp = call_llm([{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}],
                            max_tokens=3200, timeout=90, config=llm_config)
        except LLMError as exc:
            raise ValueError('模型调用失败：%s' % exc)
        result = parse_adaptation(resp['text'], context['ref_map'].keys(),
                                  context['business_source_ids'], 's1')
        meta = {'source': 'llm', 'model': resp.get('model'),
                'usage': resp.get('usage') or {},
                'duration_ms': resp.get('duration_ms')
                or int((time.time() - started) * 1000),
                'run_id': uuid.uuid4().hex[:12]}
    parent_uid = (context.get('parent') or {}).get('artifact_uid') or ''
    saved = ops.save_research_artifact('adaptation', context['topic'],
                                       context['input'], context, result,
                                       source=meta['source'], parent_uid=parent_uid)
    return {'ok': True, 'artifact': saved}


def _verify_adaptation_source(ops, source):
    """核对 C 导入稿依赖的 C 记录、父 B/A、候选与底层来源仍存在/未归档/归属正确。"""
    if not isinstance(source, dict):
        raise ValueError('研究稿来源格式无效')
    rows = source.get('basis_chain') or []
    if not isinstance(rows, list):
        raise ValueError('研究稿来源链路格式无效')
    refs, ref_map = [], {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('研究稿来源链路格式无效')
        sid = row.get('source_id')
        if not isinstance(sid, str) or not _TOPIC_SOURCE_ID_RE.match(sid):
            raise ValueError('研究稿来源号无效')
        if sid in ref_map:
            raise ValueError('研究稿来源号重复')
        origin = row.get('origin')
        if not isinstance(origin, dict):
            raise ValueError('研究稿来源 %s 缺少真实身份' % sid)
        refs.append({'id': sid})
        ref_map[sid] = origin
    if refs:
        _verify_ref_origins(ops, refs, ref_map, limit=24)
    c_uid = source.get('artifact_uid')
    if not isinstance(c_uid, str) or not _ARTIFACT_UID_RE.match(c_uid):
        raise ValueError('研究稿缺少有效的适配记录身份')
    try:
        artifact = ops.get_research_artifact(c_uid)
    except ValueError:
        raise ValueError('适配记录不存在或已归档')
    if artifact.get('kind') != 'adaptation':
        raise ValueError('来源记录不是参考适配记录')
    parent_uid = source.get('parent_uid') or ''
    if parent_uid:
        if not isinstance(parent_uid, str) or not _ARTIFACT_UID_RE.match(parent_uid):
            raise ValueError('适配来源父 B UID 无效')
        try:
            artifact_b = ops.get_research_artifact(parent_uid)
        except ValueError:
            raise ValueError('父 B 选题记录不存在或已归档')
        if artifact_b.get('kind') != 'topics':
            raise ValueError('父记录不是选题建议')
        candidate_id = source.get('candidate_id') or ''
        rows_b = (artifact_b.get('result_json') or {}).get('candidates') or []
        found = False
        for row in rows_b:
            if not isinstance(row, dict):
                continue
            if row.get('id') == candidate_id or (
                    isinstance(row.get('id'), int) and str(row.get('id')) == candidate_id):
                found = True
                break
        if not found:
            raise ValueError('候选已不属于父 B 记录')
        b_parent = artifact_b.get('parent_uid')
        if not isinstance(b_parent, str) or not _ARTIFACT_UID_RE.match(b_parent):
            raise ValueError('父 B 记录缺少父 A 身份')
        _parent_research(ops, b_parent)
    else:
        if artifact.get('parent_uid'):
            raise ValueError('适配记录与来源父 B 不一致')
    return artifact


def _adaptation_import_context(ops, draft, source, store, selected):
    """C 冻结来源 + 本次明确另选资料；固定计划/策略不被当前内容替换。"""
    _verify_adaptation_source(ops, source)
    frozen = _frozen_source_refs(draft, source)
    if len(frozen) > 24:
        raise ValueError('适配来源超过支持范围')
    strategy = _frozen_strategy(source)
    context = {'refs': frozen, 'read_errors': [], 'research_source': source,
               'strategy': strategy,
               'strategy_confirmed': bool(strategy.get('confirmed')),
               'has_metrics': any((row.get('origin') or {}).get('kind')
                                  in ('record', 'metrics')
                                  for row in source.get('basis_chain') or []
                                  if isinstance(row, dict))}
    current = {'refs': _b_selected_refs(ops, selected)}
    frozen_ids = set(ref.get('id') for ref in frozen)
    extras = []
    for ref in current.get('refs') or []:
        rid = str(ref.get('id') or '')
        if not (rid.startswith('pain:') or rid.startswith('ref:')):
            continue
        if rid in frozen_ids:
            continue
        extras.append({'id': 'selected:%s' % rid, 'text': ref.get('text') or '',
                       'role': ref.get('role') or '', 'source': ref.get('source') or '',
                       'selected_this_run': True})
    if extras:
        context['refs'].extend(extras)
        context['selected_this_run'] = [ref['id'] for ref in extras]
    try:
        current_strategy = ops.get_strategy()
    except ValueError:
        current_strategy = {}
    if (int(current_strategy.get('version') or 0) != strategy['version']
            or bool(current_strategy.get('confirmed')) != strategy['confirmed']):
        context['current_strategy'] = {'version': int(current_strategy.get('version') or 0),
                                       'confirmed': bool(current_strategy.get('confirmed')),
                                       'changed': True}
    imported, status = _industry_from_context(source)
    if imported is None and status.get('status') == 'legacy_invalid':
        raise ValueError('来源记录的旧内容领域模板不可用，不能转入')
    if imported is not None:
        context = _industry_apply(context, imported,
                                  _industry_source_of(source) or {'type': 'inherited',
                                                                  'code': imported['code'],
                                                                  'parent_kind': 'adaptation'})
    return context


def research_adaptation_to_draft(body, ops):
    if parse_adaptation is None:
        raise ValueError('参考适配模块不可用')
    if not isinstance(body, dict):
        raise ValueError('请求格式无效')
    extra = set(body) - {'artifact_uid'}
    if extra:
        raise ValueError('转为研究稿输入只接受 artifact_uid，不接受覆盖字段')
    artifact_uid = _artifact_uid(body.get('artifact_uid'), '适配记录 UID')
    try:
        artifact = ops.get_research_artifact(artifact_uid)
    except ValueError:
        raise ValueError('适配记录不存在或已归档')
    if artifact.get('kind') != 'adaptation':
        raise ValueError('指定记录不是参考适配记录')
    result = artifact.get('result_json') or {}
    if not isinstance(result, dict) or not result:
        raise ValueError('适配记录未分析，不能转为研究稿')
    context = artifact.get('context_json')
    if not isinstance(context, dict):
        raise ValueError('适配记录冻结上下文格式无效')
    subject = context.get('subject')
    if not isinstance(subject, dict) or subject.get('kind') not in ('manual', 'candidate'):
        raise ValueError('适配记录主题快照格式无效')
    topic = validate_topic(subject.get('topic') or artifact.get('topic') or '')
    status = _c_business(subject.get('business'))
    raw_strategy = context.get('strategy') or {}
    if not isinstance(raw_strategy, dict):
        raise ValueError('适配记录策略快照格式无效')
    version = raw_strategy.get('version') or 0
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError('适配记录策略版本无效')
    confirmed = raw_strategy.get('confirmed', False)
    if confirmed not in (True, False, 0, 1):
        raise ValueError('适配记录策略确认状态无效')
    strategy_data = raw_strategy.get('data')
    strategy = {'version': version, 'confirmed': bool(confirmed),
                'data': strategy_data if isinstance(strategy_data, dict) else {},
                'updated_at': raw_strategy.get('updated_at') or 0}
    refs = context.get('refs')
    ref_map = context.get('ref_map')
    _verify_ref_origins(ops, refs, ref_map, limit=24)
    # R3：冻结的本次说明/限制；旧记录没有该字段时按空串处理，不补当前表单值。
    instruction = context.get('instruction', '')
    if instruction is None:
        instruction = ''
    if not isinstance(instruction, str):
        raise ValueError('适配记录说明/限制格式无效')
    limits = context.get('limits')
    limits = dict(limits) if isinstance(limits, dict) else {}
    result = parse_adaptation(json.dumps(result, ensure_ascii=False),
                              ref_map.keys(), context.get('business_source_ids') or [],
                              's1')
    candidate_id = ''
    parent_uid = ''
    if subject.get('kind') == 'candidate':
        candidate_id = subject.get('candidate_id') or ''
        parent_uid = artifact.get('parent_uid') or ''
        if not isinstance(parent_uid, str) or not _ARTIFACT_UID_RE.match(parent_uid):
            raise ValueError('适配记录缺少父 B 记录')
        parent_info = context.get('parent') or {}
        if parent_info.get('artifact_uid') != parent_uid:
            raise ValueError('适配记录冻结上下文与父 B 不一致')
        try:
            artifact_b = ops.get_research_artifact(parent_uid)
        except ValueError:
            raise ValueError('父 B 选题记录不存在或已归档')
        if artifact_b.get('kind') != 'topics':
            raise ValueError('父记录不是选题建议')
        rows_b = (artifact_b.get('result_json') or {}).get('candidates') or []
        found = False
        for row in rows_b:
            if isinstance(row, dict) and (
                    row.get('id') == candidate_id
                    or (isinstance(row.get('id'), int)
                        and str(row.get('id')) == candidate_id)):
                found = True
                break
        if not found:
            raise ValueError('候选已不属于父 B 记录')
        b_parent = artifact_b.get('parent_uid')
        if not isinstance(b_parent, str) or not _ARTIFACT_UID_RE.match(b_parent):
            raise ValueError('父 B 记录缺少父 A 身份')
        _parent_research(ops, b_parent)
    else:
        if artifact.get('parent_uid'):
            raise ValueError('手工适配记录不应有父 B 记录')
    chain_in = context.get('basis_chain') or []
    chain_by_sid = {}
    for row in chain_in:
        if isinstance(row, dict) and isinstance(row.get('source_id'), str):
            chain_by_sid[row['source_id']] = row
    refs_out, ref_entries, seen = [], [], set()
    for ref in refs:
        sid = ref.get('id')
        origin = ref_map.get(sid)
        if not isinstance(origin, dict):
            raise ValueError('适配来源 %s 缺少真实身份' % sid)
        rid = _draft_source_ref_id(origin)
        if rid in seen:
            continue
        seen.add(rid)
        row = chain_by_sid.get(sid) or {}
        identity = ['kind=%s' % origin.get('kind')]
        for key in ('id', 'uid', 'version', 'index'):
            if origin.get(key) is not None:
                identity.append('%s=%s' % (key, origin.get(key)))
        note = ''
        if origin.get('snapshot') == 'b_frozen':
            note += '\n快照：B 候选冻结链路正文'
        if row.get('parent_sid'):
            note += '\n父路径：B 来源 %s' % row.get('parent_sid')
        text = '%s（M05-C 冻结来源 %s）：%s\n出处：%s\n真实身份：%s%s' % (
            RESEARCH_ROLE_LABELS.get(ref.get('role'), ref.get('role') or '来源'),
            sid, ref.get('text') or '', ref.get('source') or '未提供',
            '，'.join(identity), note)
        refs_out.append({'id': rid, 'text': text, 'role': ref.get('role') or '',
                         'source': ref.get('source') or '', 'origin': origin,
                         'snapshot_source': origin.get('snapshot') or ''})
        ref_entries.append({'source_id': sid,
                            'parent_sid': row.get('parent_sid') or '',
                            'role': ref.get('role') or '',
                            'label': ref.get('label') or '',
                            'text': ref.get('text') or '',
                            'source': ref.get('source') or '',
                            'origin': origin,
                            'demand_role': row.get('demand_role') or '',
                            'declaration': row.get('declaration')})
    business_ref_ids = [ref['id'] for ref in refs_out
                        if (ref.get('origin') or {}).get('kind') in _C_BIZ_ORIGIN_KINDS]
    adaptation_industry, industry_info = _industry_from_context(context)
    if adaptation_industry is None and industry_info.get('status') == 'legacy_invalid':
        raise ValueError('适配记录的旧内容领域模板不可用，不能转入')
    if adaptation_industry is None:
        adaptation_industry = build_industry_snapshot(DEFAULT_INDUSTRY_CODE)
        industry_source = {'type': 'default', 'code': DEFAULT_INDUSTRY_CODE,
                           'parent_kind': 'adaptation', 'parent_uid': artifact_uid}
        if industry_info.get('status') != 'legacy_missing':
            industry_source['legacy_status'] = industry_info.get('status')
    else:
        industry_source = {'type': 'inherited', 'code': adaptation_industry['code'],
                           'parent_kind': 'adaptation', 'parent_uid': artifact_uid}
    research_source = {
        'kind': 'adaptation', 'artifact_uid': artifact_uid,
        'parent_uid': parent_uid, 'candidate_id': candidate_id,
        'topic': topic, 'subject': subject, 'source': artifact.get('source') or 'manual',
        # R3：C 的已保存说明/限制作为独立冻结输入进入 M02 来源与版本 context，
        # 不依赖模型恰好在计划正文里复述，也不取当前 C 表单的新说明。
        'instruction': instruction,
        'limits': limits,
        'strategy': strategy, 'summary': result['summary'],
        'patterns': result['patterns'],
        'non_transferable': result['non_transferable'],
        'cannot_judge': result['cannot_judge'], 'adaptation': result,
        'refs': refs_out, 'basis_chain': ref_entries,
        'business_ref_ids': business_ref_ids,
        'industry': copy.deepcopy(adaptation_industry),
        'industry_source': copy.deepcopy(industry_source),
        'note': '本稿由 M05-C 参考适配计划转入；计划是推断，不是事实；本稿未生成，'
                '不表示需求已验证、正式选题或批准。',
    }
    draft_context = {'refs': refs_out, 'read_errors': [],
                     'strategy_confirmed': bool(confirmed),
                     'has_metrics': any((row.get('origin') or {}).get('kind')
                                        in ('record', 'metrics') for row in ref_entries),
                     'research_source': research_source}
    draft_context = _industry_apply(draft_context, adaptation_industry, industry_source)
    saved = ops.save_draft(topic, status, draft_context)
    return {'ok': True, 'draft': saved}


def _industry_export(context):
    snapshot, status = _industry_from_context(context or {})
    if snapshot is None:
        return ''
    return ('\n\n## 内容领域模板（保存时冻结）\n\n'
            + render_industry_prompt(snapshot)
            + '\n\n> 模板只提供提问、证据检查与表达约束，不是事实、来源、资质或策略许可。\n')


def _reminder_parent(ops, kind, uid, sub_id):
    if kind == 'advice_action':
        if not isinstance(uid, str) or not uid:
            raise ValueError('建议 UID 无效')
        return ops.get_advice(uid)
    if kind == 'draft_version':
        if not isinstance(uid, str) or not uid:
            raise ValueError('研究稿 UID 无效')
        if isinstance(sub_id, bool) or not isinstance(sub_id, int) or sub_id <= 0:
            raise ValueError('研究稿版本必须是正整数')
        draft = ops.get_draft(uid)
        version = ops.get_draft_version(uid, sub_id)
        return {'draft': draft, 'version': version}
    raise ValueError('绑定类型只能是 advice_action 或 draft_version')


def _reminder_public(item, now=None, ops=None):
    now = time.time() if now is None else now
    state = reminders.display_state(item, now)
    result = {key: item.get(key) for key in (
        'reminder_uid', 'title', 'note', 'target_kind', 'target_uid', 'target_sub_id',
        'due_at', 'status', 'row_version', 'parent', 'created_at', 'updated_at')}
    result['uid'] = result.pop('reminder_uid')
    result['display_state'] = state
    result['state_label'] = reminders.state_label(state)
    result['parent_available'] = True
    if ops is not None:
        try:
            if item.get('target_kind') == 'advice_action':
                ops.get_advice(item.get('target_uid'))
            else:
                ops.get_draft(item.get('target_uid'))
                ops.get_draft_version(item.get('target_uid'), item.get('target_sub_id'))
        except ValueError:
            result['parent_available'] = False
    return result


def reminders_list(ops):
    now = time.time()
    return {'items': [_reminder_public(item, now, ops) for item in ops.list_reminders()],
            'now': now}


def reminders_get(ops, uid):
    return _reminder_public(ops.get_reminder(uid), ops=ops)


def reminders_create(ops, body):
    return _reminder_public(ops.create_reminder_atomic(body), ops=ops)


class ReminderNotFound(ValueError):
    pass


def reminders_update(ops, body):
    if not isinstance(body, dict):
        raise ValueError('提醒更新格式无效')
    uid = body.get('uid')
    if not isinstance(uid, str) or not uid:
        raise ReminderNotFound('提醒不存在')
    try:
        item = ops.get_reminder(uid)
    except ValueError:
        raise ReminderNotFound('提醒不存在')
    payload = {key: value for key, value in body.items() if key != 'uid'}
    updated = reminders.apply_update(item, payload, time.time())
    return _reminder_public(ops.update_reminder(
        uid, payload.get('expected_row_version'), updated, time.time()), ops=ops)


def _adaptation_source_export(source):
    """R3：M02 导出可见 C 转入的说明/限制，并明确标为用户输入（非事实、非批准）。"""
    if not isinstance(source, dict) or source.get('kind') != 'adaptation':
        return ''
    strategy = source.get('strategy') or {}
    label = {'demo': '演示（未调用模型）', 'llm': '真实模型'}.get(
        source.get('source') or '', '人工保存（未分析）')
    return '\n'.join([
        '', '## 研究稿来源（M05-C 参考适配计划，推断不是事实，不是需求验证或批准）',
        '- C 记录：%s；父 B 记录：%s；候选 id：%s；来源：%s' % (
            source.get('artifact_uid') or '', source.get('parent_uid') or '无',
            source.get('candidate_id') or '无', label),
        '- 目标主题：%s' % (source.get('topic') or ''),
        '- 本次说明/限制（用户输入，未独立核实；生成须遵守）：%s' % (
            source.get('instruction') or '未填写'),
        '- 冻结策略：v%s · %s' % (strategy.get('version') or 0,
                                  '已确认' if strategy.get('confirmed') else '未确认'),
        '- 说明：计划是推断，不是完整正文；本记录不表示需求已验证、正式选题或批准。',
    ]) + '\n'


def _adaptation_markdown(artifact):
    result = artifact.get('result_json') or {}
    context = artifact.get('context_json') or {}
    subject = context.get('subject') or {}
    business = subject.get('business') or {}
    strategy = context.get('strategy') or {}
    reference = context.get('reference') or {}
    parent = context.get('parent') or {}
    refs = dict((ref.get('id'), ref) for ref in context.get('refs') or [])
    ref_map = context.get('ref_map') or {}
    chain = dict((row.get('source_id'), row)
                 for row in context.get('basis_chain') or [] if isinstance(row, dict))
    source = artifact.get('source') or 'manual'
    labels = {'demo': '演示（未调用模型，未真实分析）', 'llm': '真实模型'}
    lines = ['# 参考适配计划', '',
             '适配记录 C：%s' % (artifact.get('artifact_uid') or ''),
             '目标主题：%s' % (context.get('topic') or artifact.get('topic') or ''),
             '主题来源：%s' % ('B 候选' if subject.get('kind') == 'candidate' else '手工主题'),
             '父 B 记录：%s' % (parent.get('artifact_uid') or '无'),
             '父 A 记录：%s' % (parent.get('parent_uid') or '无'),
             '候选 id：%s' % (parent.get('candidate_id') or '无'),
             '来源：%s' % labels.get(source, '人工保存（未分析）'),
             '时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S',
                                      time.localtime(artifact.get('created_at') or 0)), '']
    lines.append('## 本次适配摘要')
    lines.append(result.get('summary') or '（未分析）')
    lines.append('')
    lines.append('## 指定外部参考（%s）' % (
        'B 冻结链路快照' if reference.get('snapshot_source') == 'b_frozen'
        else '本次明确选择'))
    lines.append('- 标题：%s' % (reference.get('title') or '未提供'))
    lines.append('- 出处：%s' % (reference.get('source') or '未提供'))
    lines.append('- 观察范围：%s' % (reference.get('scope') or '未提供'))
    lines.append('- 原记录时间：%s' % (reference.get('created_at') or '未提供'))
    if reference.get('excerpt'):
        lines.append('- 短摘录：%s' % reference['excerpt'])
    if reference.get('note'):
        lines.append('- 快照规则：%s' % reference['note'])
    lines.append('')
    lines.append('## 本业务冻结输入（用户提供，未独立核实）')
    for key, label in (('business', '业务/商品或服务'), ('audience', '目标受众'),
                       ('goal', '阶段目标'), ('resources', '真实资源'),
                       ('capacity', '每周可用时间/产能'), ('question', '当前问题')):
        lines.append('- %s：%s' % (label, business.get(key) or '未填写'))
    lines.append('- 说明/限制：%s' % (context.get('instruction') or '未提供'))
    lines.append('')
    lines.append('## 冻结策略边界')
    lines.append('- 版本 v%s · %s' % (strategy.get('version') or 0,
                                    '已确认' if strategy.get('confirmed') else '未确认'))
    data = strategy.get('data') or {}
    if not data:
        lines.append('- 未提供策略内容')
    for key, value in data.items():
        if isinstance(value, list):
            value = '；'.join(str(item) for item in value)
        lines.append('- %s：%s' % (key, value))
    lines.append('')

    def basis_lines(ids):
        out = []
        for ident in ids or []:
            ref = refs.get(ident) or {}
            row = chain.get(ident) or {}
            origin = ref_map.get(ident) or {}
            identity = ['kind=%s' % origin.get('kind')]
            for key in ('id', 'uid', 'version', 'index'):
                if origin.get(key) is not None:
                    identity.append('%s=%s' % (key, origin.get(key)))
            if row.get('parent_sid'):
                identity.append('parent_sid=%s' % row['parent_sid'])
            out.append('- %s [%s] 出处：%s；真实身份：%s；原文：%s' % (
                ident, ref.get('label') or '未知来源', ref.get('source') or '未提供',
                '，'.join(identity), ref.get('text') or ''))
        return out or ['- 无']

    lines.append('## 本次所选资料（冻结来源，可追溯）')
    if not refs:
        lines.append('（无所选资料）')
    for ref in context.get('refs') or []:
        ident = ref.get('id')
        origin = ref_map.get(ident) or {}
        row = chain.get(ident) or {}
        identity = ['kind=%s' % origin.get('kind')]
        for key in ('id', 'uid', 'version', 'index'):
            if origin.get(key) is not None:
                identity.append('%s=%s' % (key, origin.get(key)))
        if row.get('parent_sid'):
            identity.append('parent_sid=%s' % row['parent_sid'])
        lines.append('- %s [%s] 真实身份：%s；出处：%s；原文：%s' % (
            ident, ref.get('label') or '', '，'.join(identity) or '未提供',
            ref.get('source') or '未提供', ref.get('text') or ''))
    lines.append('')
    lines.append('## 借鉴计划（开头/结构/证明/节奏/承接）')
    patterns = result.get('patterns') or []
    if not patterns:
        lines.append('（本次没有适配计划项；见“仍不能判断”）')
    for item in patterns:
        lines.append('### %s · %s' % (
            item.get('id'),
            {'hook': '开头', 'structure': '结构', 'proof': '证明方式',
             'pacing': '节奏', 'cta': '承接'}.get(item.get('aspect'), item.get('aspect'))))
        lines.append('- 如何替换：%s' % (item.get('text') or ''))
        lines.append('- 为什么/边界：%s' % (item.get('why') or ''))
        lines.append('- 依据（basis）：')
        lines.extend(basis_lines(item.get('basis')))
        lines.append('- 本业务依据（business_basis）：%s' % (
            '、'.join(item.get('business_basis') or []) or '无——本业务证明未提供'))
        lines.append('- 条件：%s' % ('；'.join(item.get('conditions') or []) or '无'))
        lines.append('- 缺口：%s' % ('；'.join(item.get('gaps') or []) or '无'))
        lines.append('- 下一步：%s' % (item.get('next_step') or '未提供'))
        if item.get('reference_excerpt'):
            lines.append('- 参考短摘录：%s' % item['reference_excerpt'])
        lines.append('')
    lines.append('## 不能照搬（他人案例/数字/身份/承诺）')
    non_rows = result.get('non_transferable') or []
    if not non_rows:
        lines.append('（本次未列出；不代表参考全部可复制）')
    for item in non_rows:
        lines.append('### %s' % (item.get('id') or ''))
        lines.append('- 不能照搬：%s' % (item.get('text') or ''))
        lines.append('- 原因：%s' % (item.get('why') or ''))
        lines.append('- 依据（basis）：')
        lines.extend(basis_lines(item.get('basis')))
        lines.append('- 条件：%s' % ('；'.join(item.get('conditions') or []) or '无'))
        lines.append('- 缺口：%s' % ('；'.join(item.get('gaps') or []) or '无'))
        lines.append('- 下一步：%s' % (item.get('next_step') or '未提供'))
        lines.append('')
    lines.append('## 仍不能判断')
    lines.extend(['- %s' % item for item in result.get('cannot_judge') or []]
                 or ['（无）'])
    lines.append('')
    lines.append('## 限制')
    lines.append('- 本记录是参考适配计划，不是完整原创正文、需求验证、效果承诺或发布建议。')
    lines.append('- 外部参考中的案例、数字、身份与承诺只属“参考中声称”，不是我方事实。')
    lines.append('- business_basis 非空只表示用户提供了对应资料，不表示效果已验证。')
    lines.append('- 人工摘录由用户提供，未独立核实；模型输出不自动变成事实。')
    if source == 'demo':
        lines.append('- 演示模式未调用模型，不代表真实适配质量。')
    if not result:
        lines.append('- 本记录尚未分析。')
    return '\n'.join(lines) + '\n'


def _topics_markdown(artifact):
    result = artifact.get('result_json') or {}
    context = artifact.get('context_json') or {}
    parent = context.get('parent') or {}
    input_data = context.get('parent_input') or {}
    business = input_data.get('business') or {}
    strategy = context.get('strategy') or {}
    refs = dict((ref.get('id'), ref) for ref in context.get('refs') or [])
    demand_roles = context.get('demand_roles') or {}
    declarations = dict((item.get('source_id'), item)
                        for item in context.get('source_roles') or [])
    ref_map = context.get('ref_map') or {}
    source = artifact.get('source') or 'manual'
    source_label = {'demo': '演示（未调用模型，未真实分析）', 'llm': '真实模型'}.get(
        source, '人工保存')
    lines = ['# 语义选题建议', '',
             '选题记录 B：%s' % (artifact.get('artifact_uid') or ''),
             '父研究记录 A：%s' % (parent.get('artifact_uid') or ''),
             '父记录主题：%s' % (parent.get('topic') or ''),
             '父记录状态：%s' % ('已分析' if parent.get('analyzed') else '未分析'),
             '来源：%s' % source_label,
             '基于已保存记录（父记录冻结快照，不使用当前表单未保存编辑）',
             '时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S',
                                      time.localtime(artifact.get('created_at') or 0)), '']
    lines.extend(['## 摘要', result.get('summary') or '（无）', ''])
    lines.append('## 父记录冻结业务与策略')
    for key, label in (('business', '业务/商品或服务'), ('audience', '目标受众'),
                       ('goal', '阶段目标'), ('resources', '真实资源'),
                       ('capacity', '每周可用时间/产能'), ('question', '当前问题')):
        lines.append('- %s：%s' % (label, business.get(key) or '未填写'))
    lines.append('- 策略边界：v%s · %s' % (strategy.get('version') or 0,
                                         '已确认' if strategy.get('confirmed') else '未确认'))
    data = strategy.get('data') or {}
    if not data:
        lines.append('- 未提供策略内容')
    for key, value in data.items():
        if isinstance(value, list):
            value = '；'.join(str(item) for item in value)
        lines.append('- %s：%s' % (key, value))
    lines.append('')
    lines.append('## 候选（研究状态，不是正式选题）')
    candidates = result.get('candidates') or []
    if not candidates:
        lines.append('（本次没有候选；见“仍不能判断”）')
    for candidate in candidates:
        lines.append('### 候选 %s · %s' % (candidate.get('id'),
                                          '研究候选' if candidate.get('state') == 'research_candidate'
                                          else '待验证'))
        lines.append('- 主题：%s' % (candidate.get('topic') or ''))
        lines.append('- 受众问题：%s' % (candidate.get('audience_problem') or ''))
        lines.append('- 适配理由：%s' % (candidate.get('fit_reason') or ''))
        lines.append('- 为什么：%s' % (candidate.get('why') or ''))
        lines.append('- 条件：%s' % ('；'.join(candidate.get('conditions') or []) or '无'))
        lines.append('- 缺口：%s' % ('；'.join(candidate.get('gaps') or []) or '无'))
        lines.append('- 下一步：%s' % (candidate.get('next_step') or ''))
        lines.append('- 背景依据（basis）：')
        for sid in candidate.get('basis') or []:
            ref = refs.get(sid) or {}
            origin = ref_map.get(sid) or {}
            identity = ['kind=%s' % origin.get('kind')]
            if origin.get('id') is not None:
                identity.append('id=%s' % origin['id'])
            if origin.get('uid'):
                identity.append('uid=%s' % origin['uid'])
            if origin.get('version'):
                identity.append('version=%s' % origin['version'])
            if origin.get('index') is not None:
                identity.append('index=%s' % origin['index'])
            declared = declarations.get(sid)
            fixed = ('；人工声明需求角色：%s（人工声明，未独立核实）' % (
                TOPIC_DEMAND_ROLE_LABELS.get(declared.get('role'), declared.get('role')))
                if declared else '')
            lines.append('  - %s [%s] 真实身份：%s；出处：%s；原文：%s%s' % (
                sid, ref.get('label') or '', '，'.join(identity) or '未提供',
                ref.get('source') or '未提供', ref.get('text') or '', fixed))
        lines.append('- 需求依据（demand_basis，服务端认定角色）：')
        for sid in candidate.get('demand_basis') or []:
            lines.append('  - %s：%s' % (sid, TOPIC_DEMAND_ROLE_LABELS.get(
                demand_roles.get(sid), demand_roles.get(sid) or '未认定')))
        if not (candidate.get('demand_basis') or []):
            lines.append('  - 无（只能待验证，不表示需求成立）')
        lines.append('')
    demand_notes = context.get('demand_notes') or []
    if demand_notes:
        lines.append('## 未计入需求角色的来源（保守规则）')
        for note in demand_notes:
            if isinstance(note, dict):
                lines.append('- %s：%s' % (note.get('source_id') or '',
                                           note.get('reason') or '证据不足'))
        lines.append('')
    lines.append('## 仍不能判断')
    lines.extend(['- %s' % item for item in result.get('cannot_judge') or []] or ['（无）'])
    lines.append('')
    lines.append('## 限制')
    lines.append('- 本记录只是研究用途选题建议，不是正式选题、批准或发布；状态不表示需求已验证。')
    lines.append('- 外部参考热度不等于本业务需求；自有指标不等于受众需求；模型推断不是事实。')
    lines.append('- 人工声明仅代表用户声明，未独立核实；演示模式未调用模型，不代表真实选题质量。')
    if source == 'demo':
        lines.append('- 来源为演示，未调用真实模型。')
    return '\n'.join(lines) + '\n'


def _research_markdown(artifact):
    if artifact.get('kind') == 'topics':
        return _topics_markdown(artifact)
    if artifact.get('kind') == 'adaptation':
        return _adaptation_markdown(artifact)
    result = artifact.get('result_json') or {}
    context = artifact.get('context_json') or {}
    refs = {ref.get('id'): ref for ref in context.get('refs') or []}

    def basis_line(basis):
        labels = []
        for ident in basis or []:
            ref = refs.get(ident) or {}
            labels.append('%s[%s]' % (ident, ref.get('label') or '未知来源'))
        return '；'.join(labels) or '无'

    source = artifact.get('source') or 'manual'
    source_label = {'demo': '演示（未真实分析）', 'llm': '真实模型'}.get(source, '人工保存（未分析）')
    lines = ['# 研究报告', '', '主题：%s' % (artifact.get('topic') or ''),
             '记录：%s' % (artifact.get('artifact_uid') or ''),
             '来源：%s' % source_label,
             '时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S',
                                      time.localtime(artifact.get('created_at') or 0)), '']
    lines.extend(['## 摘要', result.get('summary') or '（未分析）', ''])
    for title, key in (('观察', 'observations'), ('推断', 'inferences'), ('建议', 'suggestions')):
        lines.append('## %s' % title)
        rows = result.get(key) or []
        if not rows:
            lines.append('（无）')
        for row in rows:
            lines.append('- %s' % (row.get('text') or ''))
            if row.get('why'):
                lines.append('  - 理由：%s' % row['why'])
            lines.append('  - 依据：%s' % basis_line(row.get('basis')))
            for label, field in (('条件', 'conditions'), ('缺口', 'gaps')):
                if row.get(field):
                    lines.append('  - %s：%s' % (label, '；'.join(row[field])))
            if row.get('next_step'):
                lines.append('  - 下一步：%s' % row['next_step'])
        lines.append('')
    lines.append('## 资料冲突')
    lines.extend(['- %s（依据：%s；说明：%s）' % (row.get('text'), basis_line(row.get('basis')),
                                            row.get('why') or '') for row in result.get('conflicts') or []]
                 or ['（无）'])
    lines.append('')
    lines.append('## 仍不能判断')
    lines.extend(['- %s' % item for item in result.get('cannot_judge') or []] or ['（无）'])
    lines.append('')
    lines.append('## 本报告冻结策略')
    strategy = context.get('strategy') or {}
    lines.append('- 版本 v%s · %s' % (strategy.get('version') or 0,
                                    '已确认' if strategy.get('confirmed') else '未确认'))
    strategy_data = strategy.get('data') or {}
    if not strategy_data:
        lines.append('- 未提供策略内容')
    for key, value in strategy_data.items():
        if isinstance(value, list):
            value = '；'.join(str(item) for item in value)
        lines.append('- %s：%s' % (key, value))
    lines.append('')
    lines.append('## 所选资料（冻结来源，可追溯）')
    ref_map = context.get('ref_map') or {}
    if not (context.get('refs') or []):
        lines.append('（无所选资料）')
    for ref in context.get('refs') or []:
        origin = ref_map.get(ref.get('id')) or {}
        identity = []
        if origin.get('kind'):
            identity.append('kind=%s' % origin['kind'])
        if origin.get('id') is not None:
            identity.append('id=%s' % origin['id'])
        if origin.get('uid'):
            identity.append('uid=%s' % origin['uid'])
        if origin.get('version'):
            identity.append('version=%s' % origin['version'])
        if origin.get('index') is not None:
            identity.append('index=%s' % origin['index'])
        if origin.get('legacy'):
            identity.append('legacy=1')
        lines.append('- %s [%s] 真实身份：%s；出处：%s；原文：%s' % (
            ref.get('id'), ref.get('label') or '', '，'.join(identity) or '未提供',
            ref.get('source') or '未提供', ref.get('text') or ''))
    lines.append('')
    lines.append('## 限制')
    lines.append('- 仅基于本次所选资料；外部参考的热度不等于本业务需求，自有表现不等于受众需求。')
    lines.append('- 人工摘录为用户提供、未独立核实；模型推断不是事实。')
    lines.append('- 本报告不包含策略确认、稿件批准或发布操作。')
    if source == 'demo':
        lines.append('- 演示模式未调用模型，不代表真实内容质量。')
    return '\n'.join(lines) + '\n'


def create_server(port=8765, data_dir=None, downloads_dir=None, edition='owner', static_dir=None, catalog_snapshot=None, on_exit=None):
    if edition not in ('owner', 'customer'):
        raise ValueError('软件版本无效')
    data_dir = Path(data_dir) if data_dir is not None else ROOT / 'data'
    downloads_dir = Path(downloads_dir) if downloads_dir is not None else ROOT / 'downloads'
    data_dir.mkdir(parents=True, exist_ok=True)
    local_asr = LocalASR(data_dir)
    store = Store(data_dir / 'radar.sqlite3')
    store.seed()
    if edition == 'customer' and catalog_snapshot is None:
        from customer_snapshot import SNAPSHOT
        catalog_snapshot = SNAPSHOT
    catalog = Catalog(catalog_snapshot if catalog_snapshot is not None else ROOT / 'catalog.json',
                      store.path, retain_result=edition != 'customer')
    client = None
    if edition == 'customer':
        from customer_api import ClientAPI
        client = ClientAPI(data_dir, store, catalog)
    static_root = Path(static_dir) if static_dir is not None else ROOT / 'static'
    api_key = ['' if client else os.environ.get('TIKHUB_API_KEY', '')]
    owner_vault = CredentialVault(data_dir / 'owner-tikhub') if not client else None
    credential_error = ['']
    credential_remembered = [False]
    credential_lock = threading.Lock()
    if owner_vault is not None:
        try:
            owner, saved_key = owner_vault.load()
            if saved_key and owner != 'owner-tikhub':
                raise ValueError('凭据用途不符')
            if saved_key:
                api_key[0] = saved_key
                credential_remembered[0] = True
        except (ValueError, OSError):
            credential_error[0] = '本机加密凭据不可用，请重新填写或清除；换电脑或 Windows 账户需重填'
    token = secrets.token_urlsafe(24)
    scan_lock = threading.Lock()
    download_lock = threading.Lock()
    ai = AIDirections(store.path)
    creative = VideoCreative(ai)
    ops = OpsStore(store.path)
    agent_tasks = AgentTasks(store.path, TASK_RULES) if not client else None
    agent_loop = AgentLoop(data_dir, ops, ai, test_enabled=(not client and os.environ.get('ICE_AGENT_LOOP_TEST') == '1'))
    onboarding = AccountOnboarding(data_dir, ops, lambda: (api_key[0], ai.snapshot()['key']),
                                   os.environ.get('SHORT_VIDEO_OPS_WORKSPACE', '').strip())
    agent_task_lock = threading.Lock()
    ai_request_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, value, status=200, content_type='application/json; charset=utf-8'):
            body = json.dumps(value, ensure_ascii=False).encode('utf-8') if content_type.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' https: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get('Host') not in ('127.0.0.1:' + str(port), 'localhost:' + str(port)):
                return self.send({'error': '仅支持本机访问'}, 403)
            parsed = urlsplit(self.path)
            if client and parsed.path.startswith('/api/') and parsed.path not in ('/api/state', '/api/client/config', '/api/ai/config') and not parsed.path.startswith('/api/downloads/'):
                return self.send({'error': '页面不存在'}, 404)
            if client and parsed.path == '/api/client/config':
                return self.send(client.config())
            if parsed.path.startswith('/api/agent/'):
                try:
                    query = parse_qs(parsed.query)
                    if parsed.path == '/api/agent/onboarding':
                        try:
                            return self.send(onboarding.state())
                        except (OSError, ValueError, KeyError):
                            return self.send({'error': '账号资料读取失败，请检查目录权限或在高级设置查看原连接；不会覆盖旧资料'}, 503)
                    if parsed.path == '/api/agent/loop':
                        uid = query.get('run_uid', [''])[0]
                        return self.send(agent_loop.get(uid, query.get('version', [None])[0]) if uid else agent_loop.listing())
                    if parsed.path == '/api/agent/asr-config':
                        return self.send(local_asr.config())
                    if parsed.path == '/api/agent/account':
                        return self.send({'account': agent_tasks.account(), 'strategy': ops.get_strategy()})
                    if parsed.path == '/api/agent/workspace-config':
                        if client:
                            return self.send({'error': '接口不存在'}, 404)
                        saved_path, config_error = read_workspace_config(data_dir)
                        environment_path = os.environ.get('SHORT_VIDEO_OPS_WORKSPACE', '').strip()
                        effective_path = environment_path or saved_path
                        valid = False
                        message = (config_error if not environment_path else '') or (
                            '尚未配置 Agent workspace' if not effective_path else '')
                        if effective_path:
                            try:
                                validate_workspace(effective_path)
                                valid = True
                            except ValueError as exc:
                                message = str(exc)
                        return self.send({
                            'configured_path': saved_path or '',
                            'effective_path': effective_path or '',
                            'environment_override': bool(environment_path),
                            'valid': valid,
                            'message': message,
                        })
                    if parsed.path == '/api/agent/view-model':
                        onboarding.sync_strategy()
                        if client:
                            return self.send({'error': '接口不存在'}, 404)
                        workspace_root = os.environ.get('SHORT_VIDEO_OPS_WORKSPACE', '').strip()
                        if not workspace_root:
                            workspace_root, config_error = read_workspace_config(data_dir)
                            if config_error:
                                return self.send(empty_view_model('read_error', config_error), 503)
                        if not workspace_root:
                            return self.send(empty_view_model())
                        try:
                            return self.send(build_view_model(
                                Path(workspace_root),
                                fixture=os.environ.get('SHORT_VIDEO_OPS_WORKSPACE_MODE') == 'fixture'))
                        except (OSError, ValueError) as exc:
                            return self.send(empty_view_model('read_error',
                                                              'Agent workspace 读取失败：' + type(exc).__name__), 503)
                    if parsed.path == '/api/agent/tasks':
                        rows = agent_tasks.list()
                        for item in rows:
                            inputs = json.loads(item.pop('input_json'))
                            item.update(product=inputs.get('product', ''), goal=inputs.get('goal', ''))
                        return self.send(rows)
                    if parsed.path == '/api/agent/task':
                        version = query.get('version', [''])[0]
                        return self.send(agent_tasks.get(query.get('id', [''])[0], int(version) if version else None))
                    if parsed.path == '/api/agent/media':
                        media = agent_tasks.read_media(query.get('id', [''])[0])
                        return self.send(media['data'], content_type=media['mime'])
                    return self.send({'error': '页面不存在'}, 404)
                except (ValueError, TypeError) as exc:
                    return self.send({'error': str(exc)}, 400)
            if parsed.path == '/api/ai/config':
                return self.send(ai.config())
            if parsed.path == '/api/catalog':
                result = catalog.state()
                result.update(token=token, connected=bool(api_key[0]),
                              credential_remembered=credential_remembered[0],
                              credential_error=credential_error[0])
                return self.send(result)
            if parsed.path == '/api/catalog/detail':
                try:
                    return self.send(catalog.detail(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 400)
            if parsed.path == '/api/state':
                try:
                    state = store.state(parse_qs(parsed.query).get('mode', ['demo'])[0])
                    if client:
                        state = client.public_state(state)
                    state.update(connected=bool(client.key if client else api_key[0]), token=token,
                                 credential_remembered=credential_remembered[0],
                                 credential_error=credential_error[0],
                                 desktop_exit_enabled=on_exit is not None,
                                 free_only=False, access=client.access() if client else catalog.access_state(),
                                 agent_tasks_enabled=agent_tasks is not None)
                    return self.send(state)
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 400)
            if parsed.path == '/api/last-response':
                archive = data_dir / 'last_douyin_response.json'
                if not archive.exists():
                    return self.send({'error': '尚未保存供应商响应'}, 404)
                return self.send(json.loads(archive.read_text(encoding='utf-8')))
            if parsed.path == '/api/reference/list':
                return self.send(ops.list_references())
            if parsed.path == '/api/pain/list':
                return self.send(ops.list_pains())
            if parsed.path == '/api/reference':
                try:
                    return self.send(ops.get_reference(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/pain':
                try:
                    return self.send(ops.get_pain(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/strategy':
                return self.send(ops.get_strategy())
            if parsed.path == '/api/topics/combo':
                return self.send(ops.get_combo(parse_qs(parsed.query).get('date', [None])[0]))
            if parsed.path == '/api/ops/dashboard':
                try:
                    return self.send(ops.ops_dashboard(parse_qs(parsed.query).get('date', [None])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 400)
            if parsed.path == '/api/ops/advice/list':
                return self.send(ops.list_advices())
            if parsed.path == '/api/ops/advice':
                try:
                    return self.send(ops.get_advice(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/ops/industry/catalog':
                return self.send(industry_catalog())
            if parsed.path == '/api/ops/reminders/list':
                return self.send(reminders_list(ops))
            if parsed.path == '/api/ops/reminders':
                try:
                    return self.send(reminders_get(
                        ops, parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/ops/draft/list':
                return self.send(ops.list_drafts())
            if parsed.path == '/api/ops/draft':
                try:
                    return self.send(ops.get_draft(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/ops/media-review/list':
                return self.send(ops.list_media_reviews())
            if parsed.path == '/api/ops/media-review':
                try:
                    return self.send(ops.get_media_review(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/ops/research/list':
                return self.send(ops.list_research_artifacts(
                    parse_qs(parsed.query).get('kind', ['research'])[0]))
            if parsed.path == '/api/ops/research':
                try:
                    return self.send(ops.get_research_artifact(
                        parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/ops/research/export':
                try:
                    artifact = ops.get_research_artifact(
                        parse_qs(parsed.query).get('id', [''])[0])
                    payload = _research_markdown(artifact).encode('utf-8')
                    payload += _industry_export(artifact.get('context_json') or {}).encode('utf-8')
                    filename = 'research-%s.md' % artifact['artifact_uid']
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="%s"' % filename)
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/feedback/consultations':
                return self.send(ops.list_consultations(parse_qs(parsed.query).get('record', [None])[0]))
            if parsed.path == '/api/ops/draft/export':
                try:
                    draft = ops.get_draft(parse_qs(parsed.query).get('id', [''])[0])
                    version = parse_qs(parsed.query).get('version', [''])[0]
                    if version:
                        record = ops.get_draft_version(draft['draft_uid'], int(version))
                        content = record.get('content_json') or {}
                        source, model = record.get('source'), record.get('model')
                    else:
                        record = draft.get('current_version') or {}
                        content = record.get('content_json') or {}
                        source, model = record.get('source'), record.get('model')
                    if not record:
                        raise ValueError('请先生成研究稿')
                    payload = to_markdown(dict(content, source=source, model=model))
                    if draft_optimization_changes is not None and content.get('changes'):
                        payload += '\n\n' + draft_optimization_changes(content)
                    payload += _adaptation_source_export(_research_source_of(
                        {'context_json': record.get('context_json') or {}}))
                    payload += _industry_export(record.get('context_json') or {})
                    raw = payload.encode('utf-8')
                    filename = 'draft-%s-v%s.md' % (draft['draft_uid'], record.get('version') or 0)
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="%s"' % filename)
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path in ('/api/ops/conversion', '/api/ops/conversion/export'):
                try:
                    uid = parse_qs(parsed.query).get('id', [''])[0]
                    review = conversion_get(ops, uid)
                    if parsed.path == '/api/ops/conversion':
                        return self.send(review)
                    raw = conversion.report_markdown(review['data_json']).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="conversion-%s.md"' % review['review_uid'])
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/feedback/records':
                return self.send(ops.list_publish_records())
            if parsed.path == '/api/feedback/snapshots':
                return self.send(ops.list_metric_snapshots(parse_qs(parsed.query).get('record', [''])[0]))
            if parsed.path == '/api/feedback/reviews':
                return self.send(ops.list_reviews(parse_qs(parsed.query).get('record', [None])[0]))
            if parsed.path == '/api/feedback/suggestion':
                try:
                    return self.send(ops.get_suggestion(parse_qs(parsed.query).get('id', [''])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path == '/api/script/tasks':
                return self.send(ops.list_content_tasks())
            if parsed.path == '/api/script/task':
                try:
                    return self.send(ops.get_content_task(
                        parse_qs(parsed.query).get('id', [''])[0],
                        parse_qs(parsed.query).get('version', [None])[0]))
                except ValueError as exc:
                    return self.send({'error': str(exc)}, 404)
            if parsed.path.startswith('/api/downloads/'):
                filename = parsed.path.rsplit('/', 1)[-1]
                directory = downloads_dir.resolve()
                file = (directory / filename).resolve()
                if (not re.match(r'^video-\d+-[a-f0-9]{8}\.(mp4|webm|ts)$', filename)
                        or file.parent != directory or not file.is_file()):
                    return self.send({'error': '下载文件不存在'}, 404)
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment; filename="{}"'.format(filename))
                self.send_header('Content-Length', str(file.stat().st_size))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with file.open('rb') as stream:
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                return
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'),
                     '/creative': ('creative.html', 'text/html'), '/creative.js': ('creative.js', 'text/javascript'),
                     '/creative.css': ('creative.css', 'text/css'), '/creative-rules.txt': ('creative-rules.txt', 'text/plain'),
                     '/script': ('script.html', 'text/html'), '/script.js': ('script.js', 'text/javascript'),
                     '/script.css': ('script.css', 'text/css'),
                     '/strategy': ('strategy.html', 'text/html'), '/strategy.js': ('strategy.js', 'text/javascript'),
                     '/strategy.css': ('strategy.css', 'text/css'),
                     '/feedback': ('feedback.html', 'text/html'), '/feedback.js': ('feedback.js', 'text/javascript'),
                     '/feedback.css': ('feedback.css', 'text/css'),
                     '/advice': ('advice.html', 'text/html'), '/advice.js': ('advice.js', 'text/javascript'),
                     '/advice.css': ('advice.css', 'text/css'),
                     '/draft': ('draft.html', 'text/html'), '/draft.js': ('draft.js', 'text/javascript'),
                     '/media-review': ('media-review.html', 'text/html'), '/media-review.js': ('media-review.js', 'text/javascript'),
                     '/media-review.css': ('media-review.css', 'text/css'),
                     '/research': ('research.html', 'text/html'), '/research.js': ('research.js', 'text/javascript'),
                     '/research.css': ('research.css', 'text/css'),
                     '/draft.css': ('draft.css', 'text/css'),
                     '/market': ('market.html', 'text/html'), '/tools': ('tools.html', 'text/html'),
                     '/dashboard': ('dashboard.html', 'text/html'), '/dashboard.js': ('dashboard.js', 'text/javascript'),
                     '/dashboard-data.js': ('dashboard-data.js', 'text/javascript'), '/dashboard.css': ('dashboard.css', 'text/css'),
                     '/ops-wallboard': ('ops-wallboard.html', 'text/html'),
                     '/ops-wallboard.js': ('ops-wallboard.js', 'text/javascript'),
                     '/ops-wallboard.css': ('ops-wallboard.css', 'text/css'),
                     '/agent-loop.js': ('agent-loop.js', 'text/javascript'),
                     '/agent-loop.css': ('agent-loop.css', 'text/css'),
                     '/agent-workspace-settings.js': ('agent-workspace-settings.js', 'text/javascript'),
                     '/account-onboarding.js': ('account-onboarding.js', 'text/javascript'),
                     '/account-onboarding.css': ('account-onboarding.css', 'text/css'),
                     '/agent-workspace-settings.css': ('agent-workspace-settings.css', 'text/css'),
                     '/icons.js': ('icons.js', 'text/javascript'), '/icons.css': ('icons.css', 'text/css'),
                     '/site.js': ('site.js', 'text/javascript'), '/site.css': ('site.css', 'text/css'),
                     '/radar-data.js': ('radar-data.js', 'text/javascript'), '/discovery.css': ('discovery.css', 'text/css'),
                     '/browser-import': ('browser-import.html', 'text/html'),
                     '/browser-import.js': ('browser-import.js', 'text/javascript'),
                     '/browser-import.css': ('browser-import.css', 'text/css'),
                     '/browser-collector.zip': ('browser-collector.zip', 'application/zip'),
                     '/market.js': ('market.js', 'text/javascript'), '/market.css': ('market.css', 'text/css'),
                     '/tool-layout.css': ('tool-layout.css', 'text/css'),
                     '/market-data.js': ('market-data.js', 'text/javascript'),
                     '/tools.js': ('tools.js', 'text/javascript'), '/tools.css': ('tools.css', 'text/css'),
                     '/free-tools-data.js': ('free-tools-data.js', 'text/javascript')}
            files.update({'/theme.js': ('theme.js', 'text/javascript'),
                          '/theme.css': ('theme.css', 'text/css'),
                          '/tokens.css': ('tokens.css', 'text/css'),
                          '/components.css': ('components.css', 'text/css'),
                          '/ice.css': ('ice.css', 'text/css'),
                          '/ice-avatar.jpg': ('ice-assets/avatar.jpg', 'image/jpeg'),
                          '/ice-regular.ttf': ('ice-assets/MapleMono-CN-Regular.ttf', 'font/ttf'),
                          '/ice-semibold.ttf': ('ice-assets/MapleMono-CN-SemiBold.ttf', 'font/ttf'),
                          '/favicon.ico': ('ice-assets/ice.ico', 'image/x-icon')})
            if parsed.path not in files:
                return self.send({'error': '页面不存在'}, 404)
            if client and parsed.path in ('/market','/market.js','/market.css','/market-data.js',
                                           '/browser-import','/browser-import.js','/browser-collector.zip',
                                           '/media-review','/media-review.js','/media-review.css',
                                           '/ops-wallboard','/ops-wallboard.js','/ops-wallboard.css',
                                           '/agent-workspace-settings.js','/agent-workspace-settings.css',
                                           '/draft','/draft.js','/draft.css','/advice','/advice.js','/advice.css',
                                           '/research','/research.js','/research.css'):
                return self.send({'error': '页面不存在'}, 404)
            name, mime = files[parsed.path]
            file = static_root / name
            if not file.is_file():
                return self.send({'error': '页面不存在'}, 404)
            self.send(file.read_bytes(), content_type=mime + '; charset=utf-8')

        def _drain_request_body(self):
            """拒绝请求前读掉小请求体，避免 Windows 下客户端看到连接被重置而非 403/404。"""
            try:
                length = int(self.headers.get('Content-Length', '0') or '0')
            except (TypeError, ValueError):
                return
            if 0 < length <= 2000000:
                try:
                    self.rfile.read(length)
                except Exception:
                    pass

        def do_POST(self):
            if self.path == '/api/ops/conversion/build' and self.headers.get('Host') not in ('127.0.0.1:' + str(port), 'localhost:' + str(port)):
                self._drain_request_body()
                return self.send({'error': '仅支持本机访问'}, 403)
            allowed = ('http://127.0.0.1:' + str(port), 'http://localhost:' + str(port))
            if self.headers.get('Origin') not in allowed or self.headers.get('X-Radar-Token') != token:
                self._drain_request_body()
                return self.send({'error': '请求来源无效，请重新打开本地页面'}, 403)
            if client and self.path not in ('/api/client/config','/api/client/forget','/api/client/search',
                    '/api/ai/config','/api/ai/cache','/api/ai/generate','/api/keyword','/api/import',
                    '/api/download','/api/clear-list','/api/undo-clear','/api/video/generate','/api/video/transcribe'):
                self._drain_request_body()
                return self.send({'error': '接口不存在'}, 404)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                limit = (MAX_VIDEO_BYTES if self.path in ('/api/video/transcribe', '/api/agent/media', '/api/agent/transcribe-local') else
                         MAX_REQUEST_BYTES if self.path in ('/api/video/generate', '/api/reference/save',
                                                            '/api/ops/media-review/analyze', '/api/agent/task/save') else
                         M04_OPS_BYTES if self.path in M04_OPS_PATHS else
                         2000000 if self.path in ('/api/import', '/api/browser-import') else 12000)
                if not 0 < length <= limit:
                    # 超限请求先读掉小请求体，保证客户端收到受控 400 而不是连接重置。
                    self._drain_request_body()
                    raise ValueError('请求大小无效：超过 %d 字节上限' % limit)
                if self.path == '/api/agent/media':
                    media = self.rfile.read(length)
                    if len(media) != length:
                        raise ValueError('视频传输不完整')
                    return self.send(agent_tasks.put_media(media, self.headers.get('Content-Type'),
                        unquote(self.headers.get('X-Radar-Filename', 'video'))))
                if self.path == '/api/agent/transcribe-local':
                    if not agent_task_lock.acquire(False):
                        raise ValueError('当前任务正在处理，请稍后提取本地字幕')
                    try:
                        media = self.rfile.read(length)
                        if len(media) != length:
                            raise ValueError('视频传输不完整')
                        return self.send(local_asr.transcribe(media, self.headers.get('Content-Type'),
                            self.headers.get('X-Radar-Confirmed') == 'true'))
                    finally:
                        agent_task_lock.release()
                if self.path == '/api/video/transcribe':
                    if not ai_request_lock.acquire(False): raise ValueError('模型正在处理，请等待完成')
                    try:
                        media = self.rfile.read(length)
                        if len(media) != length: raise ValueError('视频传输不完整')
                        return self.send(creative.transcribe(media, self.headers.get('Content-Type'),
                            self.headers.get('X-Radar-Speech-Model'), self.headers.get('X-Radar-Confirmed') == 'true'))
                    finally:
                        ai_request_lock.release()
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(body, dict):
                    raise ValueError('请求格式无效')
                if self.path == '/api/agent/onboarding/create':
                    return self.send(onboarding.create(body))
                if self.path == '/api/agent/onboarding/backup':
                    return self.send(onboarding.backup(), content_type='application/zip')
                if self.path == '/api/agent/onboarding/open':
                    onboarding.open_folder()
                    return self.send({'opened': True})
                if self.path == '/api/agent/loop/action':
                    if not agent_loop.enabled:
                        raise ValueError('本实例未开启隔离测试')
                    action = body.get('action')
                    uid, expected = body.get('run_uid'), body.get('expected_version')
                    if action == 'create':
                        return self.send(agent_loop.create(body))
                    if action in ('diagnose','handoff','review'):
                        return self.send(getattr(agent_loop, action)(uid, expected))
                    if action in ('select','feedback'):
                        return self.send(getattr(agent_loop, action)(uid, expected, body))
                    if action in ('reference','creation'):
                        if not ai_request_lock.acquire(False):
                            raise ValueError('模型正在处理，请等待完成')
                        try:
                            return self.send(agent_loop.model(uid, expected, action))
                        finally:
                            ai_request_lock.release()
                    if action == 'fetch':
                        def fetch_reference(video_id):
                            if not api_key[0]:
                                raise ValueError('请先配置 TikHub Key')
                            route = '/api/v1/douyin/app/v3/fetch_one_video'
                            info = tikhub_json('/api/v1/tikhub/user/get_endpoint_info', params={'endpoint':route}).get('data') or {}
                            price = money(info.get('endpoint_cost'))
                            if info.get('endpoint_uri') != route or price is None or price * 10 > 1:
                                raise ValueError('接口价格未确认或超预算，不发送业务请求')
                            raw = tikhub_json(route, key=api_key[0], params={'aweme_id':video_id})
                            posts = extract_posts(raw, 'dy')
                            post = next((p for p in posts if p['external_id']==video_id), None)
                            if not post:
                                raise ValueError('没有对应视频字段，不自动重试')
                            # Only public content fields cross into the test artifacts; no upstream auth/URL echoes.
                            return dict(title=str(post.get('title') or '')[:1000],
                                author=str(post.get('author') or '')[:200],
                                source_url='https://www.douyin.com/video/'+video_id,
                                fetched_at=datetime.now(timezone.utc).isoformat(),priced_usd=str(price))
                        return self.send(agent_loop.fetch(uid, expected, body, fetch_reference))
                    raise ValueError('流程操作不存在')
                if self.path == '/api/agent/workspace-config':
                    if client:
                        return self.send({'error': '接口不存在'}, 404)
                    with onboarding.lock:
                        if body.get('clear') is True:
                            clear_workspace_config(data_dir)
                            return self.send({'configured': False, 'message': '已清除 ICE 本机保存的路径；Agent workspace 文件未改动。'})
                        root = save_workspace_config(data_dir, body.get('workspace_path'))
                    return self.send({'configured': True, 'valid': True,
                                      'message': 'Agent workspace 已校验并保存在本机数据目录。',
                                      'workspace_name': root.name})
                if self.path == '/api/agent/asr-config':
                    return self.send(local_asr.configure(body))
                if self.path == '/api/desktop/exit':
                    if on_exit is None:
                        return self.send({'error': '仅桌面版支持退出程序'}, 404)
                    if body.get('confirm') is not True:
                        raise ValueError('请先确认已保存修改并退出程序')
                    on_exit()
                    return self.send({'closing': True})
                if self.path == '/api/agent/task/save':
                    if not agent_task_lock.acquire(False):
                        raise ValueError('当前任务正在生成，请完成后再保存')
                    try:
                        raw = body.get('input')
                        if not isinstance(raw, dict):
                            raise ValueError('缺少任务输入')
                        if raw.get('transcript_source') == 'local_asr':
                            local_asr.verify(raw, body.get('media_id'))
                        prepared, frames = creative.prepare(dict(raw, confirmed=True))
                        prepared.update(frames=frames, confirmed=False)
                        task_uid = body.get('task_uid') or None
                        current = agent_tasks.get(task_uid) if task_uid else None
                        result = body.get('result')
                        if result is not None:
                            if not isinstance(result, dict):
                                raise ValueError('成果格式无效')
                            if (not current or not current['result'] or current['input'] != prepared
                                    or current['media']['media_id'] != body.get('media_id')):
                                raise ValueError('输入已改变，请先保存新输入；旧成果仍保留在历史版本')
                            report = creative.validate(copy.deepcopy(result.get('report')),
                                                       len(frames), prepared['outputs'])
                            result = dict(current['result'], report=report)
                        return self.send(agent_tasks.save(prepared, body.get('media_id'),
                            current['strategy'] if current else ops.get_strategy(), result=result,
                            source='user_saved' if result else 'user_input', task_uid=task_uid,
                            expected_version=body.get('expected_version', 0)))
                    finally:
                        agent_task_lock.release()
                if self.path == '/api/agent/task/generate':
                    if body.get('confirm') is not True:
                        raise ValueError('请先确认本次模型调用')
                    if not agent_task_lock.acquire(False):
                        raise ValueError('当前任务正在生成，请等待完成')
                    acquired_ai = False
                    attempt_uid = None
                    try:
                        task = agent_tasks.get(body.get('task_uid'))
                        if type(body.get('expected_version')) is not int or body['expected_version'] != task['current_version']:
                            raise ValueError('任务版本已变化，请重新打开最新版本')
                        acquired_ai = ai_request_lock.acquire(False)
                        if not acquired_ai:
                            raise ValueError('模型正在处理，请等待完成')
                        config = creative.connection()
                        attempt_uid = agent_tasks.begin_attempt(task, config['model'])
                        result = creative.generate(dict(task['input'], confirmed=True),
                            account_context={'account': task['account'], 'strategy': task['strategy'], 'rules': task['rules']},
                            response_sink=lambda raw: agent_tasks.archive_response(attempt_uid, raw))
                        saved = agent_tasks.save(task['input'], task['media']['media_id'],
                            task['strategy'], result=result, source='llm', task_uid=task['task_uid'],
                            expected_version=task['current_version'], rules=task['rules'])
                        agent_tasks.finish_attempt(attempt_uid, 'success', result.get('validation', {}))
                        return self.send(agent_tasks.get(saved['task_uid']))
                    except Exception as exc:
                        if attempt_uid is not None:
                            state = getattr(exc, 'state', 'result_unconfirmed')
                            message = str(exc) if isinstance(exc, ValueError) else '本地保存未完成，结果未确认；不会自动重试'
                            agent_tasks.finish_attempt(attempt_uid, state,
                                {'error': message, 'repairs': getattr(exc, 'repairs', []),
                                 'location': getattr(exc, 'location', None)})
                        raise
                    finally:
                        if acquired_ai:
                            ai_request_lock.release()
                        agent_task_lock.release()
                if self.path == '/api/agent/task/recover':
                    if body.get('confirm') is not True:
                        raise ValueError('请先确认本地恢复；此操作不调用模型')
                    if not agent_task_lock.acquire(False):
                        raise ValueError('当前任务正在处理，请稍后恢复')
                    try:
                        task = agent_tasks.get(body.get('task_uid'))
                        if type(body.get('expected_version')) is not int or body['expected_version'] != task['current_version']:
                            raise ValueError('任务版本已变化，请重新打开最新版本')
                        attempt = agent_tasks.archived_attempt(task['task_uid'], body.get('attempt_uid'), task['version'])
                        result = creative.recover(dict(task['input'], confirmed=True), attempt['raw_response'], attempt['model'])
                        # Keep the failed attempt and its original response unchanged.
                        result['validation']['recovery'] = dict(attempt_uid=attempt['attempt_uid'],
                            original_status=attempt['status'], input_version=attempt['input_version'],
                            response_sha256=attempt['response_sha256'], recovered_at=time.time(), network_requests=0)
                        return self.send(agent_tasks.save(task['input'], task['media']['media_id'],
                            task['strategy'], result=result, source='llm', task_uid=task['task_uid'],
                            expected_version=task['current_version'], rules=task['rules']))
                    finally:
                        agent_task_lock.release()
                if self.path == '/api/video/generate':
                    if body.get('transcript_source') == 'local_asr':
                        local_asr.verify(body, (body.get('transcript_asr') or {}).get('media_sha256'))
                    if not ai_request_lock.acquire(False): raise ValueError('模型正在处理，请等待完成')
                    try: return self.send(creative.generate(body))
                    finally: ai_request_lock.release()
                if client and self.path.startswith('/api/client/'):
                    if not scan_lock.acquire(False):
                        raise ValueError('已有请求正在运行，请等待完成')
                    try:
                        if self.path == '/api/client/config':
                            return self.send(client.configure(body))
                        if self.path == '/api/client/forget':
                            return self.send(client.forget())
                        return self.send(client.search(body, tikhub_json, extract_posts))
                    finally:
                        scan_lock.release()
                if self.path in ('/api/ai/config', '/api/ai/cache', '/api/ai/generate'):
                    if not ai_request_lock.acquire(False):
                        raise ValueError('AI 分类正在处理，请完成后再操作')
                    try:
                        if self.path == '/api/ai/config':
                            return self.send(ai.configure(body.get('endpoint'), body.get('model'),
                                                          body.get('key'), body.get('clear_key') is True))
                        ids, scope_mode = body.get('ids'), body.get('mode')
                        if (scope_mode not in ('live', 'demo') or not isinstance(ids, list) or len(ids) > 200
                                or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids)):
                            raise ValueError('请选择最多200条当前作品')
                        posts = [p for p in store.state(scope_mode)['posts'] if p['id'] in ids]
                        if len(posts) != len(ids):
                            raise ValueError('作品列表已变化，请刷新页面后重试')
                        if self.path == '/api/ai/cache':
                            return self.send(ai.preview(posts, scope_mode))
                        if body.get('confirmed') is not True:
                            raise ValueError('请先确认分类范围及模型服务')
                        return self.send(ai.generate(posts, scope_mode, body.get('fingerprint'), body.get('force') is True))
                    finally:
                        ai_request_lock.release()
                if self.path == '/api/scan':
                    return self.send({'error': '免费版已关闭计费采集，包括使用赠送额度的接口。请导入本地视频数据。'}, 403)
                if self.path == '/api/clear-list':
                    count = body.get('count')
                    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                        raise ValueError('请先确认清空对象和数量')
                    return self.send(store.clear_list(body.get('kind'), body.get('mode'), count))
                if self.path == '/api/undo-clear':
                    ident = body.get('id')
                    if isinstance(ident, bool) or not isinstance(ident, int):
                        raise ValueError('清空记录无效')
                    return self.send(store.undo_clear(ident))
                if self.path == '/api/browser-import':
                    keyword, posts = browser_posts(body)
                    existing = {(p['platform'], p['external_id']): p['id'] for p in store.state('live')['posts']}
                    fresh = [p for p in posts if (p['platform'], p['external_id']) not in existing]
                    ident = store.add_keyword(keyword)
                    store.put_posts(ident, fresh, 'live')
                    with closing(store.connect()) as db:
                        for post in posts:
                            post_id = existing.get((post['platform'], post['external_id']))
                            if post_id:
                                db.execute('INSERT OR IGNORE INTO matches VALUES(?,?)', (ident, post_id))
                        db.commit()
                    return self.send({'count': len(fresh), 'skipped': len(posts)-len(fresh), 'keyword_id': ident})
                if self.path == '/api/import':
                    posts = imported_posts(body.get('posts'))
                    existing = {(p['platform'], p['external_id']) for p in store.state('live')['posts']}
                    fresh = [p for p in posts if (p['platform'], p['external_id']) not in existing]
                    if not fresh:
                        return self.send({'count': 0, 'skipped': len(posts)})
                    ident = store.add_keyword(str(body.get('keyword') or '本地导入'))
                    store.put_posts(ident, fresh, 'live')
                    return self.send({'count': len(fresh), 'skipped': len(posts)-len(fresh), 'keyword_id': ident})
                if self.path == '/api/download':
                    ident = body.get('id')
                    resolve = body.get('resolve', False)
                    if not isinstance(resolve, bool) or not isinstance(ident, int) or isinstance(ident, bool):
                        raise ValueError('视频ID或解析选项无效')
                    if client and resolve:
                        return self.send({'error': '接口不存在'}, 404)
                    post = next((p for p in store.state('live')['posts'] if p['id'] == ident), None)
                    if not post:
                        raise ValueError('请选择已收录的真实视频')
                    if not download_lock.acquire(False):
                        raise ValueError('已有视频正在下载，请等待完成')
                    try:
                        resolution_cost = None
                        if resolve:
                            if post['platform'] != 'dy' or not re.fullmatch(r'[0-9]{1,30}', post['external_id']):
                                raise ValueError('此解析入口仅支持已收录的抖音视频；其他视频请使用已有直链或手动导入')
                            resolver = 'GET /api/v1/douyin/app/v3/fetch_video_high_quality_play_url'
                            expected_cost = catalog.get(resolver)['price']
                            if expected_cost is None or body.get('confirmed_cost') != expected_cost:
                                raise ValueError('请先确认本次直链解析的接口费用；费用变化时需重新确认')
                            if not scan_lock.acquire(False):
                                raise ValueError('已有接口请求正在运行，请等待完成')
                            try:
                                resolved = []
                                result = catalog.run(resolver, api_key[0], {'aweme_id': post['external_id']}, None, tikhub_json,
                                    consume=lambda payload: resolved.append(resolved_media_url(payload, post['external_id'])))
                                if not result['ok'] or result.get('processing_error'):
                                    raise ValueError('获取直链失败；未下载，不自动重试：' + result['result'][:500])
                                url = resolved[0]
                                post = store.set_video_url(ident, url)
                                resolution_cost = result['cost']
                            finally:
                                scan_lock.release()
                        downloaded = download_cached_video(post, downloads_dir)
                        if resolution_cost is not None:
                            downloaded['resolution_cost'] = resolution_cost
                        return self.send(downloaded)
                    finally:
                        download_lock.release()
                if self.path == '/api/tools':
                    catalog.manage(str(body.get('id', '')), str(body.get('action', '')))
                    return self.send({'ok': True})
                if self.path == '/api/access':
                    if not scan_lock.acquire(False):
                        raise ValueError('已有请求正在运行，请完成后再更改额度设置')
                    try:
                        return self.send(catalog.configure_access(body.get('enabled'), body.get('limit'),
                                                                  body.get('days'), body.get('allow_balance', False)))
                    finally:
                        scan_lock.release()
                if self.path == '/api/credit':
                    if not scan_lock.acquire(False):
                        raise ValueError('已有请求正在运行，请稍后查询')
                    try:
                        return self.send(catalog.refresh_credit(api_key[0], tikhub_json))
                    finally:
                        scan_lock.release()
                if self.path == '/api/tools/run':
                    if not scan_lock.acquire(False):
                        raise ValueError('已有请求正在运行，请等待完成')
                    try:
                        if body.get('collect') is True and catalog.get(str(body.get('id', ''))).get('collection_supported') is False:
                            raise ValueError('此接口只返回话题，不能收录为视频；请取消收录或选择视频接口。未发出供应商请求。')
                        item = catalog.get(str(body.get('id', '')))
                        posts = []
                        consume = (lambda payload: posts.extend(extract_posts(payload, 'dy' if item['platform']=='douyin' else 'xhs'))) \
                            if body.get('collect') is True and item['platform'] in ('douyin','xiaohongshu') else None
                        result = catalog.run(str(body.get('id', '')), api_key[0],
                                             body.get('params', {}), body.get('body'), tikhub_json, consume=consume)
                        if body.get('collect') is True:
                            item = catalog.get(str(body.get('id', '')))
                            if item['platform'] not in ('douyin', 'xiaohongshu'):
                                result['collection_message'] = '此平台暂不支持收录到发现内容，响应已保留。'
                            elif not result['ok']:
                                result['collection_message'] = '接口执行失败，未收录视频。实际原因：' + result['result'][:500]
                            elif result.get('processing_error'):
                                result['collection_message'] = result['processing_error']
                            else:
                                keyword = str(body.get('keyword') or 'TikHub采集').strip()
                                if not keyword or len(keyword) > 40:
                                    result['collection_message'] = '收录关键词无效，响应已保留。'
                                elif posts:
                                    ident = store.add_keyword(keyword)
                                    for post in posts:
                                        post['source'] = 'TikHub ' + item['path']
                                        post['plays_source'] = '接口实际返回字段' if post.get('plays') is not None else '接口未返回播放量'
                                    store.put_posts(ident, posts, 'live')
                                    result['collection_message'] = '已收录或更新 {} 条作品，播放量未知时保留未知。'.format(len(posts))
                                    result['keyword_id'] = ident
                                else:
                                    result['collection_message'] = '响应中没有可识别的作品，未收录。请检查原始响应。'
                                if result['truncated']:
                                    result['collection_message'] += ' 页面仅展示前30万字符，收录已使用完整响应。'
                        return self.send(result)
                    finally:
                        scan_lock.release()
                if self.path == '/api/keyword':
                    return self.send({'id': store.add_keyword(str(body.get('name', '')))})
                if self.path == '/api/save':
                    store.save(int(body['id']), body.get('saved'), body.get('note', ''))
                    return self.send({'ok': True})
                if self.path == '/api/reference/save':
                    result = {'version': body.get('version', ''), 'report': body.get('report'),
                              'scope': body.get('scope', {})}
                    ident = ops.save_reference(body.get('title'), result, body.get('model'),
                                               body.get('post_id'), body.get('source_name'))
                    return self.send({'id': ident, 'ok': True})
                if self.path == '/api/pain/save':
                    ident = ops.save_pain(body.get('pain'), body.get('source', 'comment'),
                                          body.get('related_post_id'), body.get('frequency', 1),
                                          body.get('evidence', ''), body.get('evidence_role', 'audience_pain'))
                    return self.send({'id': ident, 'ok': True})
                if self.path == '/api/strategy/save':
                    with onboarding.lock:
                        record = ops.save_strategy(body.get('data'), body.get('provenance'), body.get('expected_version'))
                        record['workspace_sync_error'] = onboarding.sync_strategy(record=record)
                        return self.send(record)
                if self.path == '/api/strategy/confirm':
                    with onboarding.lock:
                        onboarding.ensure_confirmable()
                        record = ops.confirm_strategy(body.get('expected_version'))
                        record['workspace_sync_error'] = onboarding.sync_strategy(record=record)
                        return self.send(record)
                if self.path == '/api/topics/build':
                    return self.send(topics_build(body, store, ops))
                if self.path == '/api/topics/select':
                    return self.send(topics_select(body, ops))
                if self.path == '/api/ops/conversion/build':
                    return self.send(ops.build_conversion(body))
                if self.path == '/api/feedback/register':
                    return self.send(feedback_register(body, ops))
                if self.path == '/api/feedback/metrics':
                    return self.send(feedback_metrics(body, ops))
                if self.path == '/api/feedback/review':
                    return self.send(feedback_review(body, ops))
                if self.path == '/api/ops/advice/analyze':
                    return self.send(advice_analyze(body, store, ops, ai))
                if self.path == '/api/ops/advice/ask':
                    return self.send(advice_ask(body, store, ops, ai))
                if self.path == '/api/ops/advice/save':
                    return self.send(advice_save(body, ops))
                if self.path == '/api/ops/advice/action':
                    return self.send({'ok': True, 'advice': ops.update_action(
                        body.get('advice_uid'), body.get('action_id'), body.get('status'),
                        body.get('note', ''), body.get('expected_version', 0))})
                if self.path == '/api/ops/media-review/analyze':
                    return self.send(media_review_analyze(body, store, ops, ai))
                if self.path == '/api/ops/research/save':
                    return self.send(research_save(body, store, ops))
                if self.path == '/api/ops/research/analyze':
                    return self.send(research_analyze(body, store, ops, ai))
                if self.path == '/api/ops/research/topics':
                    return self.send(research_topics(body, store, ops, ai))
                if self.path == '/api/ops/research/to-draft':
                    return self.send(research_to_draft(body, ops))
                if self.path == '/api/ops/research/adaptation':
                    return self.send(research_adaptation(body, store, ops, ai))
                if self.path == '/api/ops/research/adaptation-to-draft':
                    return self.send(research_adaptation_to_draft(body, ops))
                if self.path == '/api/feedback/consultation':
                    return self.send(feedback_consultation(body, ops))
                if self.path == '/api/ops/reminders/create':
                    return self.send(reminders_create(ops, body))
                if self.path == '/api/ops/reminders/update':
                    return self.send(reminders_update(ops, body))
                if self.path == '/api/ops/draft/save':
                    return self.send(draft_save(body, store, ops))
                if self.path == '/api/ops/draft/generate':
                    return self.send(draft_generate(body, store, ops, ai))
                if self.path == '/api/ops/draft/optimize':
                    return self.send(draft_optimize(body, store, ops, ai))
                if self.path == '/api/connect':
                    key = body.get('key')
                    if not isinstance(key, str) or len(key) > 500 or re.search(r'[\x00-\x20\x7f-\uffff]', key):
                        raise ValueError('密钥格式无效')
                    with credential_lock:
                        if key:
                            owner_vault.save('owner-tikhub', key)
                        else:
                            owner_vault.forget()
                        api_key[0] = key
                        credential_remembered[0] = bool(key)
                        credential_error[0] = ''
                    return self.send({'connected': bool(key), 'remembered': bool(key)})
                if self.path == '/api/script/prepare':
                    return self.send(script_prepare(body, store, ai, data_dir, ops))
                if self.path == '/api/script/task/save':
                    return self.send(script_task_save(body, ops))
                if self.path == '/api/script/task/approve':
                    return self.send(script_task_approve(body, ops))
                self.send({'error': '接口不存在'}, 404)
            except ReminderNotFound as exc:
                self.send({'error': str(exc)}, 404)
            except reminders.ReminderConflict as exc:
                self.send({'error': str(exc)}, 409)
            except (ValueError, KeyError, TypeError) as exc:
                self.send({'error': str(exc)}, 400)
            except Exception:
                self.send({'error': '本地处理失败，请检查数据目录是否可写'}, 500)

    server = Server(('127.0.0.1', port), Handler)
    port = server.server_address[1]
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    server = create_server(args.port, args.data_dir)
    print('Local Radar: http://127.0.0.1:{}'.format(args.port), flush=True)
    if args.open_browser:
        threading.Timer(0.5, lambda: webbrowser.open('http://127.0.0.1:{}'.format(args.port))).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()




