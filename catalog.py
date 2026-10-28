"""Local API directory and zero-price tool management; no network on import."""
import json
import re
import sqlite3
import time
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

PLATFORMS = {'douyin': '抖音', 'xiaohongshu': '小红书', 'tiktok': 'TikTok',
             'tikhub': 'TikHub 账户', 'youtube': 'YouTube', 'bilibili': '哔哩哔哩',
             'kuaishou': '快手', 'weibo': '微博', 'wechat': '微信', 'instagram': 'Instagram',
             'twitter': 'X / Twitter', 'demo': '演示接口', 'health': '服务健康检查'}


def price(value):
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and amount >= 0:
            return format(amount.normalize(), 'f')
    except (InvalidOperation, ValueError):
        pass
    return None


def resolve_schema(schema, spec, depth=0):
    if depth > 4 or not isinstance(schema, dict):
        return schema
    if '$ref' in schema:
        name = schema['$ref'].rsplit('/', 1)[-1]
        return resolve_schema(spec.get('components', {}).get('schemas', {}).get(name, schema), spec, depth + 1)
    result = dict(schema)
    if 'properties' in result:
        result['properties'] = {k: resolve_schema(v, spec, depth + 1) for k, v in result['properties'].items()}
    if 'items' in result:
        result['items'] = resolve_schema(result['items'], spec, depth + 1)
    return result


def example_type(value, schema):
    kind = schema.get('type')
    if kind == 'integer' and isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]+', value):
        return int(value)
    if kind == 'boolean' and isinstance(value, str) and value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    if kind == 'string' and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return value


def example(schema):
    for key in ('example', 'default'):
        if key in schema:
            return example_type(schema[key], schema)
    if schema.get('examples'):
        return example_type(schema['examples'][0], schema)
    if schema.get('enum'):
        return schema['enum'][0]
    kind = schema.get('type')
    if kind == 'object' or 'properties' in schema:
        required = schema.get('required', [])
        return {k: example(v) for k, v in schema.get('properties', {}).items()
                if k in required or any(f in v for f in ('default', 'example', 'examples'))}
    return [] if kind == 'array' else False if kind == 'boolean' else 0 if kind in ('integer', 'number') else ''


# Confirmed by the local 2026-10-27 response; do not retry or infer a replacement route.
UNAVAILABLE_ROUTES = {
    '/api/v1/douyin/app/v1/fetch_hashtag_search_result':
        '此历史话题搜索接口已返回 HTTP 404，已暂停调用；可使用视频分享链接收录或导入本地视频。',
}


def availability(item, last_ok=None):
    if item['path'] in UNAVAILABLE_ROUTES:
        status, label = 'unavailable', '不可用 · HTTP 404'
    elif last_ok:
        status, label = 'verified_response', '已验证响应'
    elif item.get('legacy_documentation'):
        status, label = 'legacy', '历史接口 · 待验证' if last_ok is None else '历史接口 · 最近失败'
    else:
        status, label = 'unverified', '待验证' if last_ok is None else '最近失败 · 待验证'
    return dict(availability=status, availability_label=label)


def execution_reason(item, allow_balance=False):
    if item['path'] in UNAVAILABLE_ROUTES:
        return UNAVAILABLE_ROUTES[item['path']]
    if re.search(r'live|webcast|livestream', item['path'], re.I):
        return '直播接口按设置停用'
    if not item['runnable']:
        return '缺少执行文档或尚未接入此操作'
    if (item.get('platform') == 'douyin' and item.get('legacy_documentation')
            and re.search(r'(?:video|general)_search|search_video$', item['path'])):
        return '历史搜索地址已暂停，请使用当前官方搜索接口'
    if item['price'] is None:
        return '价格未知，不能执行'
    if item['price'] != '0' and not item['free_credit'] and not allow_balance:
        return '此接口需要充值余额，请在额度设置中明确允许使用充值余额'
    return ''


def validate_value(value, schema, label):
    if not isinstance(schema, dict):
        return
    choices = schema.get('anyOf')
    if choices:
        for choice in choices:
            try:
                validate_value(value, choice, label)
                return
            except ValueError:
                pass
        raise ValueError(label + '类型无效')
    kind = schema.get('type')
    valid = {'string': isinstance(value, str), 'integer': isinstance(value, int) and not isinstance(value, bool),
             'number': isinstance(value, (int, float)) and not isinstance(value, bool),
             'boolean': isinstance(value, bool), 'object': isinstance(value, dict),
             'array': isinstance(value, list), 'null': value is None}
    if kind in valid and not valid[kind]:
        raise ValueError(label + '类型应为 ' + kind)
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(label + '不在允许选项中')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in schema and value < schema['minimum'] or 'maximum' in schema and value > schema['maximum']:
            raise ValueError(label + '超出允许范围')
    if isinstance(value, str):
        if schema.get('minLength', 0) and not value.strip():
            raise ValueError(label + '不能为空')
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 1000000):
            raise ValueError(label + '长度超出允许范围')
    if isinstance(value, dict):
        for name in schema.get('required', []):
            if name not in value:
                raise ValueError(label + '缺少必填参数：' + name)
        for name, child in schema.get('properties', {}).items():
            if name in value:
                validate_value(value[name], child, label + '.' + name)
    if isinstance(value, list):
        for child in value:
            validate_value(child, schema.get('items', {}), label + '[]')


def build_catalog(rules, spec):
    by_path = {}
    for rule in rules:
        path = rule.get('endpoint_uri', '').strip()
        if not path.startswith('/api/'):
            continue
        if path in by_path and price(by_path[path].get('endpoint_cost')) != price(rule.get('endpoint_cost')):
            rule = dict(rule, endpoint_cost=None)
        by_path[path] = rule
    items = []
    for path in sorted(set(by_path) | set(spec.get('paths', {}))):
        rule = by_path.get(path, {})
        methods = {m.upper(): op for m, op in spec.get('paths', {}).get(path, {}).items()
                   if m.lower() in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')}
        if not methods:
            methods = {'UNKNOWN': {}}
        for method, op in methods.items():
            parts = path.split('/')
            platform = parts[3] if len(parts) > 3 else 'other'
            title = op.get('summary', '').split('/')[0].strip() or path.rsplit('/', 1)[-1]
            parameters = op.get('parameters', [])
            query = {p['name']: example_type(p.get('example', example(p.get('schema', {}))), p.get('schema', {})) for p in parameters
                     if p.get('in') == 'query' and ('example' in p or p.get('required') or 'default' in p.get('schema', {}))}
            body_schema = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
            body_schema = resolve_schema(body_schema, spec) if body_schema else None
            documented = method != 'UNKNOWN'
            runnable = documented and method in ('GET', 'POST') and '{' not in path and not path.endswith('/create_token')
            items.append(dict(id=method + ' ' + path, path=path, method=method, platform=platform,
                platform_name=PLATFORMS.get(platform, platform.replace('_', ' ').title()), title=title,
                description=op.get('description', ''), price=price(rule.get('endpoint_cost')),
                free_credit=bool(rule.get('allow_free_credit')), discount=bool(rule.get('allow_discount')),
                rate_limit=str(rule.get('rate_limit', '未提供')), documented=documented, runnable=runnable,
                requires_key=bool(op.get('security', spec.get('security', []))),
                category='web' if '/web' in path else 'app' if '/app' in path else 'other',
                query=query, body=example(body_schema) if body_schema else None,
                parameters=parameters, body_schema=body_schema,
                docs_url='https://api.tikhub.io/#/{}/{}'.format(quote((op.get('tags') or [''])[0]), quote(op.get('operationId', '')))))
    return dict(imported_at=time.time(), source='TikHub 公开价格目录 + OpenAPI', items=items)


class Catalog:
    def __init__(self, path, database, retain_result=True):
        self.database = str(database)
        self.snapshot = path if isinstance(path, dict) else json.loads(Path(path).read_text(encoding='utf-8'))
        self.retain_result = retain_result
        self.items = self.snapshot['items']
        self.index = {i['id']: i for i in self.items}
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS tools(id TEXT PRIMARY KEY, added INTEGER NOT NULL DEFAULT 1, '
                       'enabled INTEGER NOT NULL DEFAULT 0, last_at REAL, last_ok INTEGER, last_result TEXT)')
            db.executemany('INSERT OR IGNORE INTO tools(id) VALUES(?)',
                           [(i['id'],) for i in self.items if i['price'] == '0'])
            db.execute('CREATE TABLE IF NOT EXISTS api_access(id INTEGER PRIMARY KEY CHECK(id=1), '
                       'enabled INTEGER NOT NULL DEFAULT 0, limit_amount TEXT NOT NULL DEFAULT "0", '
                       'expires_at REAL, free_credit TEXT, balance TEXT, checked_at REAL)')
            db.execute('INSERT OR IGNORE INTO api_access(id) VALUES(1)')
            if 'allow_balance' not in {r[1] for r in db.execute('PRAGMA table_info(api_access)')}:
                db.execute('ALTER TABLE api_access ADD COLUMN allow_balance INTEGER NOT NULL DEFAULT 0')
            db.execute('CREATE TABLE IF NOT EXISTS api_requests(id INTEGER PRIMARY KEY, '
                       'tool_id TEXT NOT NULL, cost TEXT NOT NULL, at REAL NOT NULL, outcome TEXT NOT NULL)')
            db.commit()

    def get(self, ident):
        if ident not in self.index:
            raise ValueError('接口不在已收录目录中')
        return self.index[ident]

    def state(self):
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            rows = db.execute('SELECT id,enabled,last_at,last_ok FROM tools WHERE added=1').fetchall()
        last_ok = {r[0]: r[3] for r in rows}
        access = self.access_state()
        compact = [dict({k: v for k, v in i.items() if k not in ('description', 'query', 'body', 'parameters', 'body_schema')},
                        execution_reason=execution_reason(i, access['allow_balance']),
                        **availability(i, last_ok.get(i['id']))) for i in self.items]
        return dict(items=compact, imported_at=self.snapshot['imported_at'], source=self.snapshot['source'],
                    access=access,
                    tools={r[0]: dict(enabled=bool(r[1]), last_at=r[2], last_ok=None if r[3] is None else bool(r[3]))
                           for r in rows if r[0] in self.index})

    def detail(self, ident):
        item = dict(self.get(ident))
        item['execution_reason'] = execution_reason(item, self.access_state()['allow_balance'])
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            row = db.execute('SELECT last_result,last_ok FROM tools WHERE id=?', (ident,)).fetchone()
        item['last_result'] = row[0] if row else None
        item.update(availability(item, row[1] if row else None))
        return item

    def manage(self, ident, action):
        item = self.get(ident)
        if action not in ('add', 'remove', 'enable', 'disable'):
            raise ValueError('工具操作无效')
        reason = execution_reason(item, self.access_state()['allow_balance'])
        if action == 'enable' and reason:
            raise ValueError(reason)
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            if action == 'add':
                db.execute('INSERT OR IGNORE INTO tools(id) VALUES(?)', (ident,))
                db.execute('UPDATE tools SET added=1 WHERE id=?', (ident,))
            elif action == 'enable':
                db.execute('INSERT OR IGNORE INTO tools(id) VALUES(?)', (ident,))
                db.execute('UPDATE tools SET added=1,enabled=1 WHERE id=?', (ident,))
            elif action == 'disable':
                db.execute('UPDATE tools SET enabled=0 WHERE id=?', (ident,))
            else:
                db.execute('UPDATE tools SET added=0,enabled=0 WHERE id=?', (ident,))
            db.commit()

    def access_state(self):
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            db.row_factory = sqlite3.Row
            row = dict(db.execute('SELECT * FROM api_access WHERE id=1').fetchone())
            spent = sum((Decimal(r[0]) for r in db.execute('SELECT cost FROM api_requests')), Decimal('0'))
        remaining = max(Decimal('0'), Decimal(row['limit_amount']) - spent)
        active = bool(row['enabled'] and remaining > 0 and (not row['expires_at'] or time.time() < row['expires_at']))
        return dict(enabled=bool(row['enabled']), active=active, limit=row['limit_amount'], spent=format(spent, 'f'),
                    remaining=format(remaining, 'f'), expires_at=row['expires_at'], free_credit=row['free_credit'],
                    balance=row['balance'], checked_at=row['checked_at'], allow_balance=bool(row['allow_balance']))

    def configure_access(self, enabled, amount, days=None, allow_balance=False):
        amount = price(amount)
        if not isinstance(enabled, bool) or not isinstance(allow_balance, bool) or amount is None:
            raise ValueError('开关或预算金额无效')
        if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650):
            raise ValueError('开启天数需为1～3650的整数，持续开启请留空')
        expires = time.time() + days * 86400 if enabled and days is not None else None
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            db.execute('UPDATE api_access SET enabled=?,limit_amount=?,expires_at=?,allow_balance=? WHERE id=1',
                       (int(enabled), amount, expires, int(allow_balance)))
            db.commit()
        return self.access_state()

    def refresh_credit(self, key, call):
        if not key:
            raise ValueError('请先配置 TikHub API Key')
        route = '/api/v1/tikhub/user/get_user_info'
        info = call('/api/v1/tikhub/user/get_endpoint_info', params={'endpoint': route}).get('data') or {}
        if info.get('endpoint_uri') != route or price(info.get('endpoint_cost')) != '0':
            raise ValueError('无法确认账户查询接口为 $0；已停止')
        account = call(route, key=key)
        user = account.get('user_data') or {}
        gift, balance = price(user.get('free_credit')), price(user.get('balance'))
        if gift is None or balance is None or user.get('account_disabled') or user.get('is_active') is False:
            raise ValueError('无法核实赠送额度或账户状态；已停止')
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            db.execute('UPDATE api_access SET free_credit=?,balance=?,checked_at=? WHERE id=1',
                       (gift, balance, time.time()))
            db.commit()
        return self.access_state()

    def reserve(self, ident, cost, uses_balance=False):
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            db.execute('BEGIN IMMEDIATE')
            enabled, limit, expires, allow_balance = db.execute(
                'SELECT enabled,limit_amount,expires_at,allow_balance FROM api_access WHERE id=1').fetchone()
            spent = sum((Decimal(r[0]) for r in db.execute('SELECT cost FROM api_requests')), Decimal('0'))
            if not enabled or (expires and time.time() >= expires):
                raise ValueError('接口调用未开启或已到期，请在额度设置中开启')
            if uses_balance and not allow_balance:
                raise ValueError('未允许使用充值余额，已停止')
            if spent + cost > Decimal(limit):
                raise ValueError('本地累计预算不足，已停止')
            row = db.execute('INSERT INTO api_requests(tool_id,cost,at,outcome) VALUES(?,?,?,?)',
                             (ident, format(cost, 'f'), time.time(), 'reserved'))
            db.commit()
            return row.lastrowid

    def run(self, ident, key, params, body, call):
        item = self.get(ident)
        state = self.state()
        tool = state['tools'].get(ident)
        reason = execution_reason(item, state['access']['allow_balance'])
        if reason or not tool or not tool['enabled']:
            raise ValueError(reason or '请先启用该接口')
        if item['requires_key'] and not key:
            raise ValueError('请先在数据源设置填写 API Key')
        if not isinstance(params, dict):
            raise ValueError('查询参数必须是 JSON 对象')
        if item['method'] == 'GET' and body is not None:
            raise ValueError('GET 接口不接受请求体')
        for parameter in item['parameters']:
            if parameter.get('in') == 'query':
                name = parameter['name']
                if parameter.get('required') and (name not in params or params[name] == ''):
                    raise ValueError('缺少必填参数：' + name)
                if name in params:
                    validate_value(params[name], parameter.get('schema', {}), name)
        if item.get('body_schema'):
            validate_value(body, item['body_schema'], '请求体')
        if item['price'] != '0' and not self.access_state()['active']:
            raise ValueError('接口调用未开启、预算不足或已到期')
        info = call('/api/v1/tikhub/user/get_endpoint_info', params={'endpoint': item['path']}).get('data') or {}
        current = price(info.get('endpoint_cost'))
        if info.get('endpoint_uri') != item['path'] or current is None or current != item['price']:
            raise ValueError('实时价格与目录不一致或无法确认价格；已停止，未执行目标接口')
        request_id = None
        funding_source = 'zero'
        if current != '0':
            account = self.refresh_credit(key, call)
            if info.get('allow_free_credit') in (True, 1) and Decimal(account['free_credit']) >= Decimal(current):
                funding_source = 'free_credit'
            elif not account['allow_balance']:
                raise ValueError('接口不支持赠送额度或赠送余额不足；未允许使用充值余额，已停止')
            elif Decimal(account['balance']) < Decimal(current):
                raise ValueError('充值余额不足，已停止')
            else:
                funding_source = 'balance'
            request_id = self.reserve(ident, Decimal(current), uses_balance=funding_source == 'balance')
        ok = False
        try:
            payload = call(item['path'], key=key if item['requires_key'] else None, params=params,
                           body=body if item['method'] == 'POST' else None)
            result = json.dumps(payload, ensure_ascii=False, indent=2)
            ok = payload.get('code', 200) in (0, 200)
        except ValueError as exc:
            result = str(exc)
        if key:
            result = result.replace(key, '[密钥已隐藏]')
        truncated = len(result) > 300000
        result = result[:300000] + ('\n…响应超过显示上限，已截断。' if truncated else '')
        at = time.time()
        with closing(sqlite3.connect(self.database, timeout=15)) as db:
            db.execute('UPDATE tools SET last_at=?,last_ok=?,last_result=? WHERE id=?', (at, int(ok), result if self.retain_result else None, ident))
            if request_id is not None:
                db.execute('UPDATE api_requests SET outcome=? WHERE id=?', ('returned' if ok else 'uncertain', request_id))
            db.commit()
        return dict(ok=ok, result=result, at=at, truncated=truncated, cost=current,
                    funding_source=funding_source, access=self.access_state())
