"""M05-D 深度文案优化核心（纯函数，D1 独立模块）。

本模块只做内存内的确定工作，不联网、不写 SQLite、不读环境变量、不写文件：
1. 输入契约：存在 optimization 对象才进入 D；targets 为 1–5 个唯一枚举，instruction
   ≤1000 码点，additional_artifact_uids ≤12，max_body_chars 为 50–10000 的 JSON
   integer；model_mode/confirm 严格校验。
2. 冻结：只接受用户指定基版本自己的完整正文/主题/业务/context/来源；基稿 JSON 与输入
   研究上下文 JSON 分别独立 ≤24000 码点，超限受控失败，不裁剪。
3. 最终 messages：明确“本次优化基于版本 vN”，带该版本原主题/业务/来源、本次目标与说明、
   本次另选的已分析 A/C 记录（保留记录身份与原文，不覆盖基版事实与限制）。
4. 严格解析：不 strip / 不 slice；draft_markdown 保存原串，按 Unicode 码点计 10000 总上限
   与本次硬上限；changes 结构严格；未知 basis、重复 ID、错类型、缺字段一律拒绝。
5. 中性 demo：只追加“未实际重写/压缩”的说明，同样过全部校验；不裁剪正文凑通过。
6. 落库载荷：新版本 content_json / context_json（基版本、目标、说明、硬上限、附加快照、
   行业快照、实际保存码点数），不写库。

返工 R1–R4 后补充的边界：
- 冻结策略独立输出，不依赖 research_source.kind；root context 快照优先，缺失时按来源快照
  兼容口径取用，都没有就明示未提供（不补默认已确认策略）。
- 区分“继承基版的附加依据”与“本次新增附加资料”：前者随基版进入允许引用集合、最终 prompt
  与新版本可追溯快照，下一轮未重新勾选也不得删除；后者只由本次明确选择决定。
- 空 basis 的事实必须待验证：模型显式 `unverified=false` 属矛盾输出，受控拒绝。
- 附加资料来源枚举与现有生产者一致：manual/demo/mock/real/llm，原样保留。

明确不做：UID 存在性/归档/归属的数据库权威加载、真实模型调用、版本写入、页面状态。
这些由 D2 在调用本模块前后完成；本模块只接经规范化的合成输入与冻结资料。
引用号冲突（基版、继承依据与本次选择之间同号）在此直接拒绝，由服务端建立明确映射后重试。
"""
import copy
import json
import re

TARGETS = ('hook', 'structure', 'proof', 'pacing', 'cta')
TARGET_LABELS = {'hook': '开头', 'structure': '结构清晰', 'proof': '证明',
                 'pacing': '口语节奏', 'cta': '承接'}

MAX_TARGETS = 5
MAX_INSTRUCTION = 1000
MAX_ADDITIONAL = 12
MIN_BODY_LIMIT = 50
MAX_BODY_LIMIT = 10000
MAX_BODY = 10000
MAX_BASE_JSON = 24000
MAX_CONTEXT_JSON = 24000
MAX_TITLE = 200
MAX_SUMMARY = 500
MAX_FACTS = 20
MAX_FACT_TEXT = 800
MAX_LIST_ITEMS = 20
MAX_LIST_TEXT = 500
MAX_CHANGES = 12
MAX_CHANGE_TEXT = 1500
MAX_CHANGE_WHY = 1000
MAX_CHANGE_BASIS = 12
MAX_CHANGE_ITEMS = 8
MAX_CHANGE_ITEM_TEXT = 500
MAX_NEXT_STEP = 500

EXTRA_SOURCES = ('manual', 'demo', 'mock', 'real', 'llm')
STRATEGY_ORIGIN_LABELS = {'context': '基版本 context 快照',
                          'research_source': '该版本来源快照'}

STATUS_LABELS = (('business', '业务/商品或服务（用户提供）'), ('audience', '目标受众（用户提供）'),
                 ('goal', '阶段目标（用户提供）'), ('resources', '真实资源（用户提供）'),
                 ('capacity', '每周可用时间/产能（用户提供）'), ('question', '当前问题（用户提供）'))

_OPT_KEYS = ('targets', 'additional_artifact_uids', 'max_body_chars')
_RESULT_KEYS = ('title', 'summary', 'facts', 'outline', 'draft_markdown', 'gaps',
                'questions', 'changes')
_CHANGE_KEYS = ('id', 'text', 'why', 'basis', 'conditions', 'gaps', 'next_step')
_FACT_KEYS = ('id', 'text', 'basis', 'source', 'unverified')
_FORBIDDEN_BODY_KEYS = ('context', 'ref_map', 'strategy', 'body', 'content', 'draft')

_UID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')
_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,20}')
_REF_ID_RE = re.compile(r'[A-Za-z0-9:_-]{1,64}')

_MISSING = object()

_SYSTEM = ('你是本地单用户运营助手，只做研究稿的一次有目标改写。主题不变；只基于给定基稿与资料；'
           '不编造案例、数字、资质、效果或账号数据；不删除限定条件、来源与依据；'
           '不替用户确认策略、批准稿件或发布。输出必须是 JSON，不要额外说明。')

_SCHEMA = '''{
 "title": "研究稿标题",
 "summary": "一句话摘要",
 "facts": [{"id": "f1", "text": "可引用的事实", "basis": ["pain:1"], "source": "资料|用户"}],
 "outline": ["一、…", "二、…"],
 "draft_markdown": "## 小节\\n完整新正文（原始字符串，不截断）",
 "gaps": ["缺少的资料/不能判断的部分"],
 "questions": ["需要用户决定的事项"],
 "changes": [{"id": "c1", "text": "改了什么", "why": "为什么这样改", "basis": ["pain:1"],
              "conditions": ["适用条件"], "gaps": ["仍缺什么"], "next_step": "下一步"}]
}'''


def _fail(message):
    raise ValueError(message)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def body_chars(text):
    """保存原串的 Unicode 码点数：不剥离空白、标点、Markdown 标记或换行。"""
    if not isinstance(text, str):
        _fail('正文必须是字符串')
    return len(text)


def parse_optimization(body):
    """optimization 缺失 → None（旧 M02 请求）；存在则严格校验并返回规范化对象。"""
    if not isinstance(body, dict):
        _fail('请求必须是对象')
    if 'optimization' not in body:
        return None
    raw = body['optimization']
    if not isinstance(raw, dict):
        _fail('optimization 必须是对象（null/false/数组都不视作缺省）')
    unknown = sorted(str(key) for key in raw if key not in _OPT_KEYS)
    if unknown:
        _fail('optimization 含不支持的字段：%s' % '、'.join(unknown))
    if 'targets' not in raw:
        _fail('请至少选择一个优化目标')
    targets = _targets(raw['targets'])
    uids = _additional_uids(raw.get('additional_artifact_uids', []))
    limit = _max_body_chars(raw.get('max_body_chars', _MISSING))
    return {'targets': targets, 'additional_artifact_uids': uids, 'max_body_chars': limit}


def _targets(value):
    if not isinstance(value, list):
        _fail('优化目标必须是数组')
    if not value:
        _fail('请至少选择一个优化目标')
    if len(value) > MAX_TARGETS:
        _fail('优化目标最多 5 项')
    result, seen = [], set()
    for item in value:
        if not isinstance(item, str):
            _fail('优化目标必须是字符串')
        if item not in TARGETS:
            _fail('未知的优化目标：%s' % item)
        if item in seen:
            _fail('优化目标重复：%s' % item)
        seen.add(item)
        result.append(item)
    return result


def _additional_uids(value):
    if not isinstance(value, list):
        _fail('附加资料 UID 必须是数组')
    if len(value) > MAX_ADDITIONAL:
        _fail('本次最多 12 条附加资料')
    result, seen = [], set()
    for item in value:
        if not isinstance(item, str) or not _UID_RE.fullmatch(item):
            _fail('附加资料 UID 无效')
        if item in seen:
            _fail('附加资料 UID 重复：%s' % item)
        seen.add(item)
        result.append(item)
    return result


def _max_body_chars(value):
    if value is _MISSING:
        return None
    if not _is_int(value):
        _fail('正文字符硬上限必须是 JSON 整数（不接受字符串/小数/布尔）')
    if value < MIN_BODY_LIMIT or value > MAX_BODY_LIMIT:
        _fail('正文字符硬上限必须在 %d–%d 之间' % (MIN_BODY_LIMIT, MAX_BODY_LIMIT))
    return value


def validate_request(body, optimization=_MISSING):
    """规范化 D 优化请求；返回 {'draft_uid','base_version','instruction','model_mode',
    'confirm','optimization'}。optimization 为 None 表示旧 M02 请求（不进入 D）。"""
    if not isinstance(body, dict):
        _fail('请求必须是对象')
    for key in _FORBIDDEN_BODY_KEYS:
        if key in body:
            _fail('请求不能携带 %s：优化只使用服务端按 UID 权威加载的基版本与记录' % key)
    draft_uid = body.get('draft_uid')
    if not isinstance(draft_uid, str) or not _UID_RE.fullmatch(draft_uid):
        _fail('请明确选择研究稿')
    base_version = body.get('base_version')
    if not _is_int(base_version) or base_version <= 0:
        _fail('请明确选择基版本（必须是正整数版本号，不默认最新版本）')
    instruction = body.get('instruction', '')
    if not isinstance(instruction, str):
        _fail('优化说明必须是字符串')
    if len(instruction) > MAX_INSTRUCTION:
        _fail('优化说明超过 %d 码点上限，请精简' % MAX_INSTRUCTION)
    model_mode = body.get('model_mode')
    if model_mode not in ('test', 'real'):
        _fail('model_mode 必须是 test 或 real')
    confirm = body.get('confirm')
    if not isinstance(confirm, bool):
        _fail('confirm 必须是布尔值（本次确认）')
    if optimization is _MISSING:
        optimization = parse_optimization(body)
    return {'draft_uid': draft_uid, 'base_version': base_version, 'instruction': instruction,
            'model_mode': model_mode, 'confirm': confirm, 'optimization': optimization}


def resolve_base_snapshot(record, draft=None):
    """按 M02 已通过的整组 legacy 规则回退：仅当该版本的 topic/status/context 三者都为空。"""
    if not isinstance(record, dict):
        _fail('基版本读取失败')
    version = record.get('version')
    if not _is_int(version) or version <= 0:
        _fail('基版本记录无效')
    topic = record.get('topic') if isinstance(record.get('topic'), str) else ''
    status = record.get('status_json') if isinstance(record.get('status_json'), dict) else {}
    context = record.get('context_json') if isinstance(record.get('context_json'), dict) else {}
    legacy = not topic and not status and not context
    if legacy:
        if not isinstance(draft, dict):
            _fail('该版本是旧记录，缺少可回退的稿件级快照')
        topic = draft.get('topic') if isinstance(draft.get('topic'), str) else ''
        status = draft.get('status_json') if isinstance(draft.get('status_json'), dict) else {}
        context = draft.get('context_json') if isinstance(draft.get('context_json'), dict) else {}
    content = record.get('content_json')
    return {'version': version, 'topic': topic, 'status_json': status, 'context_json': context,
            'content_json': content, 'legacy_snapshot': bool(legacy)}


def freeze_base(record, base_version, draft=None):
    """冻结指定基版本；校验版本归属、正文存在、基稿 JSON ≤24000 码点，完整不留裁剪。"""
    if not _is_int(base_version) or base_version <= 0:
        _fail('请明确选择基版本（必须是正整数版本号）')
    if isinstance(record, dict) and isinstance(draft, dict):
        left, right = record.get('draft_uid'), draft.get('draft_uid')
        if isinstance(left, str) and isinstance(right, str) and left != right:
            _fail('基版本不属于该研究稿')
    resolved = resolve_base_snapshot(record, draft)
    if resolved['version'] != base_version:
        _fail('基版本不属于该研究稿（请求 v%d，记录 v%d）' % (base_version, resolved['version']))
    content = resolved['content_json']
    if not isinstance(content, dict) or not content:
        _fail('基版本内容为空，无法优化')
    body = content.get('draft_markdown')
    if not isinstance(body, str) or not body.strip():
        _fail('基版本缺少正文，无法优化')
    base_text = json.dumps(content, ensure_ascii=False)
    if len(base_text) > MAX_BASE_JSON:
        _fail('基稿超出支持范围（%d 码点 > %d），请先精简后再优化'
              % (len(base_text), MAX_BASE_JSON))
    refs = _base_refs(resolved['context_json'])
    strategy = frozen_strategy({'context': resolved['context_json']})
    inherited = _inherited_artifacts(resolved['context_json'])
    return {'version': resolved['version'], 'topic': resolved['topic'],
            'status': resolved['status_json'], 'context': resolved['context_json'],
            'content': content, 'refs': refs, 'legacy': resolved['legacy_snapshot'],
            'body': body, 'strategy': strategy, 'inherited': inherited}


def _base_refs(context):
    raw = context.get('refs')
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail('基版本资料格式无效')
    refs, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            _fail('基版本资料格式无效')
        ident = item.get('id')
        if not isinstance(ident, str) or not _REF_ID_RE.fullmatch(ident):
            _fail('基版本资料引用号无效')
        if ident in seen:
            _fail('基版本资料引用号重复：%s' % ident)
        seen.add(ident)
        text = item.get('text')
        if text is None:
            text = ''
        if not isinstance(text, str):
            _fail('基版本资料原文无效：%s' % ident)
        refs.append({'id': ident, 'text': text,
                     'role': item.get('role') if isinstance(item.get('role'), str) else '',
                     'source': item.get('source') if isinstance(item.get('source'), str) else ''})
    return refs


def _strategy_snapshot(raw, origin):
    """规范化一份冻结策略快照；空字典视为未提供，错类型受控拒绝，不补默认内容。"""
    if not isinstance(raw, dict):
        _fail('基版本冻结策略格式无效')
    if not raw:
        return None
    version = raw.get('version', 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        _fail('基版本冻结策略版本无效')
    confirmed = raw.get('confirmed', False)
    if isinstance(confirmed, bool):
        pass
    elif isinstance(confirmed, int) and confirmed in (0, 1):
        confirmed = bool(confirmed)
    else:
        _fail('基版本冻结策略确认状态无效')
    data = raw.get('data')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _fail('基版本冻结策略内容无效')
    return {'available': True, 'origin': origin, 'version': version,
            'confirmed': confirmed, 'data': data}


def _strategy_value(container):
    """按字段存在性取策略：缺省/None 视为未提供；其余值（含 false/0/[]/""/{}）交类型校验。"""
    if not isinstance(container, dict) or 'strategy' not in container:
        return _MISSING
    value = container['strategy']
    if value is None:
        return _MISSING
    return value


def frozen_strategy(base):
    """该基版本自己的冻结策略：root context 优先；空字典按兼容口径回退来源快照；否则未提供。

    错误类型（false/0/[]/"" 等）必须受控拒绝，不能被 truthiness 当作缺失而回退。
    """
    context = (base or {}).get('context')
    if not isinstance(context, dict):
        context = {}
    root = _strategy_value(context)
    if root is not _MISSING:
        snapshot = _strategy_snapshot(root, 'context')
        if snapshot is not None:
            return snapshot
    source = context.get('research_source')
    if isinstance(source, dict):
        raw = _strategy_value(source)
        if raw is not _MISSING:
            snapshot = _strategy_snapshot(raw, 'research_source')
            if snapshot is not None:
                return snapshot
    return {'available': False, 'origin': None, 'version': 0, 'confirmed': False, 'data': {}}


def freeze_extras(records):
    """冻结本次另选的 A/C 记录（D2 已完成 UID 权威加载与归档/演练/归属核验）。"""
    if records is None:
        return []
    if not isinstance(records, list):
        _fail('附加资料必须是数组')
    if len(records) > MAX_ADDITIONAL:
        _fail('本次最多 12 条附加资料')
    result, seen = [], set()
    for item in records:
        frozen = _normalize_artifact(item)
        if frozen['artifact_uid'] in seen:
            _fail('附加资料重复：%s' % frozen['artifact_uid'])
        seen.add(frozen['artifact_uid'])
        result.append(frozen)
    return result


def _normalize_artifact(item):
    """校验一条已分析 A/C 记录的规范化形状；source 保留生产者原值。"""
    if not isinstance(item, dict):
        _fail('附加资料记录无效')
    uid = item.get('artifact_uid')
    if not isinstance(uid, str) or not _UID_RE.fullmatch(uid):
        _fail('附加资料 UID 无效')
    kind = item.get('kind')
    if kind not in ('research', 'adaptation'):
        _fail('附加资料只能是已分析的研究（research）或适配（adaptation）记录：%s' % uid)
    frozen_result = item.get('result')
    if not isinstance(frozen_result, dict) or not frozen_result:
        _fail('附加资料尚未分析，不能附加：%s' % uid)
    source = item.get('source')
    if source not in EXTRA_SOURCES:
        _fail('附加资料来源无效（支持 %s）：%s' % ('/'.join(EXTRA_SOURCES), uid))
    topic = item.get('topic') if isinstance(item.get('topic'), str) else ''
    parent = item.get('parent_uid') if isinstance(item.get('parent_uid'), str) else ''
    created = item.get('created_at')
    if created is not None and (isinstance(created, bool)
                                or not isinstance(created, (int, float))):
        _fail('附加资料保存时间无效：%s' % uid)
    row = {'artifact_uid': uid, 'kind': kind, 'parent_uid': parent, 'topic': topic,
           'source': source, 'created_at': created,
           'refs': _extra_refs(item.get('refs'), uid),
           'result': copy.deepcopy(frozen_result)}
    note = item.get('note', '')
    if note is None:
        note = ''
    if not isinstance(note, str):
        _fail('附加资料说明必须是字符串：%s' % uid)
    if len(note) > 1000:
        _fail('附加资料说明超过 1000 码点上限：%s' % uid)
    if note:
        row['note'] = note
    selected_version = item.get('selected_base_version')
    if selected_version is not None:
        if not _is_int(selected_version) or selected_version <= 0:
            _fail('附加资料选入版本无效：%s' % uid)
        row['selected_base_version'] = selected_version
    return row


def _inherited_artifacts(context):
    """基版本自身冻结的附加依据：新版 inherited/selected 两表 + 旧 D1 单表兼容。"""
    meta = context.get('draft_optimization')
    if meta is None:
        return []
    if not isinstance(meta, dict):
        _fail('基版本优化元信息格式无效')
    batches = []
    for key in ('inherited_artifacts', 'selected_artifacts', 'additional_artifacts'):
        value = meta.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            _fail('基版本附加依据格式无效：%s' % key)
        batches.extend(value)
    items, index = [], {}
    for raw in batches:
        frozen = _normalize_artifact(raw)
        uid = frozen['artifact_uid']
        if uid in index:
            if (json.dumps(index[uid], ensure_ascii=False, sort_keys=True)
                    != json.dumps(frozen, ensure_ascii=False, sort_keys=True)):
                _fail('基版本附加依据冲突：%s' % uid)
            continue
        index[uid] = frozen
        items.append(frozen)
    return items


_ARTIFACT_FINGERPRINT_KEYS = ('kind', 'parent_uid', 'topic', 'source', 'refs', 'result',
                              'note')


def _artifact_fingerprint(item):
    """记录本身的冻结内容指纹：不含 created_at 与本次选入元信息（selected_base_version）。"""
    data = {}
    for key in _ARTIFACT_FINGERPRINT_KEYS:
        value = item.get(key)
        if value is None and key in ('parent_uid', 'topic'):
            value = ''
        data[key] = value
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def effective_extras(base, extras=()):
    """本次新增附加资料：与基版继承链同 UID 时比较冻结快照，相同才去重，不同受控冲突。"""
    inherited = (base or {}).get('inherited') or []
    index = {}
    for item in inherited:
        index[item.get('artifact_uid')] = item
    selected = []
    for item in extras or []:
        uid = item.get('artifact_uid')
        current = index.get(uid)
        if current is not None:
            if _artifact_fingerprint(current) != _artifact_fingerprint(item):
                _fail('本次重选的附加资料与基版本已继承快照不一致：%s'
                      '（保留继承快照，不能覆盖、改名或静默忽略）' % uid)
            continue
        selected.append(item)
    return selected


def _extra_refs(raw, uid):
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail('附加资料的引用映射无效：%s' % uid)
    refs, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            _fail('附加资料的引用映射无效：%s' % uid)
        ident = item.get('id')
        if not isinstance(ident, str) or not _REF_ID_RE.fullmatch(ident):
            _fail('附加资料的引用号无效：%s' % uid)
        if ident in seen:
            _fail('附加资料的引用号重复：%s（%s）' % (ident, uid))
        seen.add(ident)
        text = item.get('text')
        if not isinstance(text, str):
            _fail('附加资料的引用原文无效：%s（%s）' % (ident, uid))
        origin = item.get('origin')
        refs.append({'id': ident, 'text': text,
                     'role': item.get('role') if isinstance(item.get('role'), str) else '',
                     'origin': copy.deepcopy(origin) if isinstance(origin, dict) else None})
    return refs


def allowed_refs(base, extras=()):
    """本次可引用 id：基版本原映射 + 继承依据 + 本次新增；同号冲突直接拒绝。"""
    ids, seen = [], set()

    def add(item, label):
        for ref in item.get('refs') or []:
            ident = ref['id']
            if ident in seen:
                _fail('%s引用号冲突：%s（需服务端建立明确映射，不能互相覆盖）'
                      % (label, ident))
            seen.add(ident)
            ids.append(ident)

    for ref in base.get('refs') or []:
        ident = ref['id']
        if ident in seen:
            _fail('基版本资料引用号重复：%s' % ident)
        seen.add(ident)
        ids.append(ident)
    for item in base.get('inherited') or []:
        add(item, '继承附加依据')
    for item in effective_extras(base, extras):
        add(item, '本次附加资料')
    return ids


def prompt_context(base, extras=()):
    """输入研究上下文：基版本冻结 context（含继承依据）+ 本次新增附加记录快照。"""
    context = copy.deepcopy(base.get('context') or {})
    selected = effective_extras(base, extras)
    if selected:
        context['additional_artifacts'] = copy.deepcopy(list(selected))
    return context


def context_chars(context):
    return len(json.dumps(context or {}, ensure_ascii=False, separators=(',', ':')))


def status_lines(status):
    lines = []
    for key, label in STATUS_LABELS:
        value = (status or {}).get(key)
        lines.append('- %s：%s' % (label, value if isinstance(value, str) and value else '未填写'))
    return '\n'.join(lines)


def _ref_lines(base):
    lines = []
    for ref in base.get('refs') or []:
        role = ('（角色 %s）' % ref['role']) if ref.get('role') else ''
        lines.append('- %s%s：%s' % (ref['id'], role, ref.get('text') or ''))
    if not lines:
        lines.append('（该版本没有固定资料；不得假设库内其他资料可用）')
    return lines


def _strategy_lines(strategy):
    """渲染该基版本自己的冻结策略边界；未提供时明示，不补默认已确认策略。"""
    if not strategy or not strategy.get('available'):
        return ['未提供（该版本没有冻结策略快照；不得假设策略已确认，也不得补默认策略）']
    origin = STRATEGY_ORIGIN_LABELS.get(strategy.get('origin'), '该版本冻结快照')
    lines = ['- 版本：v%s · %s（来源：%s；以下为保存该版本时的边界，不由本次优化改写）' % (
        strategy.get('version') or 0,
        '已确认' if strategy.get('confirmed') else '未确认',
        origin)]
    data = strategy.get('data') or {}
    if not data:
        lines.append('- 未提供策略内容（该快照没有策略字段）')
    for key, value in data.items():
        lines.append('- %s：%s' % (key, _flat(value)))
    return lines


def _research_source_lines(base):
    context = base.get('context') or {}
    source = context.get('research_source')
    if not isinstance(source, dict) or source.get('kind') != 'topics':
        return []
    lines = ['', '研究建议来源（M05-B 冻结快照；模型/演示建议不是事实，不得当事实引用）：',
             '- B 记录：%s；父 A 记录：%s；候选 id：%s；研究状态：%s；来源：%s' % (
                 source.get('artifact_uid') or '', source.get('parent_uid') or '',
                 source.get('candidate_id') or '', source.get('state') or '',
                 source.get('source') or '')]
    candidate = source.get('candidate') if isinstance(source.get('candidate'), dict) else {}
    lines.append('- 候选主题：%s' % (candidate.get('topic') or source.get('topic') or ''))
    if candidate.get('audience_problem'):
        lines.append('- 受众问题：%s' % candidate['audience_problem'])
    if candidate.get('fit_reason'):
        lines.append('- 适配理由：%s' % candidate['fit_reason'])
    if candidate.get('why'):
        lines.append('- 为什么：%s' % candidate['why'])
    for key in ('conditions', 'gaps'):
        if candidate.get(key):
            lines.append('- %s：%s' % (key, '；'.join(str(item) for item in candidate[key])))
    if candidate.get('next_step'):
        lines.append('- 下一步：%s' % candidate['next_step'])
    for row in source.get('basis_chain') or []:
        if not isinstance(row, dict):
            continue
        lines.append('- 来源 %s（角色 %s；需求角色 %s）；出处：%s' % (
            row.get('source_id') or '', row.get('role') or '', row.get('demand_role') or '无',
            row.get('source') or '未提供'))
        origin = row.get('origin')
        if isinstance(origin, dict):
            lines.append('  真实身份：%s' % _identity_lines(origin))
        if row.get('declaration'):
            declaration = row['declaration']
            role = declaration.get('role') if isinstance(declaration, dict) else ''
            lines.append('  人工声明：%s（人工声明，未独立核实）' % (role or ''))
    current = context.get('current_strategy')
    if isinstance(current, dict) and current.get('changed'):
        lines.append('- 当前策略状态（仅供对照，不覆盖冻结边界）：v%s · %s' % (
            current.get('version') or 0, '已确认' if current.get('confirmed') else '未确认'))
    return lines


def _identity_lines(origin):
    parts = []
    for key in ('kind', 'id', 'uid', 'version', 'index', 'manual_index'):
        if origin.get(key) is not None:
            parts.append('%s=%s' % (key, origin.get(key)))
    return '，'.join(parts) or '未提供'


def _artifact_lines(extras):
    if not extras:
        return ['（本次未另选资料）']
    lines = []
    for index, item in enumerate(extras, 1):
        lines.append('记录 %d · kind=%s · uid=%s · 主题=%s · 来源=%s · 父记录=%s' % (
            index, item.get('kind'), item.get('artifact_uid'), item.get('topic') or '未提供',
            item.get('source'), item.get('parent_uid') or '无'))
        lines.append('- 以下内容是该记录保存时的冻结快照；其中的模型/演示推断不是事实，'
                     '也不能覆盖上面基版本的事实、来源与限制。')
        if item.get('note'):
            lines.append('- 本次说明（用户输入；未独立核实）：%s' % item['note'])
        if item.get('refs'):
            lines.append('- 该记录的资料原文与真实身份（引用号只在本记录范围内有效）：')
            for ref in item['refs']:
                lines.append('  - %s%s：%s' % (ref['id'], ('（角色 %s）' % ref['role'])
                                               if ref.get('role') else '', ref.get('text') or ''))
                if ref.get('origin'):
                    lines.append('    真实身份：%s' % _identity_lines(ref['origin']))
        else:
            lines.append('- 该记录没有可引用的资料映射。')
        lines.append('- 该记录的冻结结果（字段原样展开；不含本次新增推测）：')
        lines.extend(_value_lines(item.get('result'), '  '))
    return lines


def _value_lines(value, indent=''):
    """把冻结结果按字段完整展开；不截断、不丢弃来源角色与条件。"""
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (list, dict)):
                lines.append('%s- %s：' % (indent, key))
                lines.extend(_value_lines(item, indent + '  '))
            else:
                lines.append('%s- %s：%s' % (indent, key, item))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                text = item.get('text')
                if text is None:
                    text = item.get('action')
                if text is None:
                    text = item.get('summary')
                if isinstance(text, str) and text:
                    lines.append('%s- %s' % (indent, text))
                    for key, value in item.items():
                        if key == 'text':
                            continue
                        if (isinstance(value, list)
                                and all(not isinstance(part, (dict, list)) for part in value)):
                            lines.append('%s  - %s：%s' % (indent, key, _flat(value)))
                        elif isinstance(value, (list, dict)):
                            lines.append('%s  - %s：' % (indent, key))
                            lines.extend(_value_lines(value, indent + '    '))
                        else:
                            lines.append('%s  - %s：%s' % (indent, key, value))
                else:
                    lines.append('%s- %s' % (indent, json.dumps(item, ensure_ascii=False)))
            elif isinstance(item, (list, dict)):
                lines.append('%s- %s' % (indent, json.dumps(item, ensure_ascii=False)))
            else:
                lines.append('%s- %s' % (indent, item))
    else:
        lines.append('%s%s' % (indent, value))
    return lines


def _flat(value):
    if isinstance(value, list):
        return '；'.join(str(item) for item in value) or '无'
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def build_messages(spec, base, extras=()):
    """构造最终 messages 的 (system, user)；任何超限都在调用模型前失败。"""
    optimization = (spec or {}).get('optimization')
    if not isinstance(optimization, dict):
        _fail('本请求未提供 optimization，不能进入 D 深度优化')
    if not isinstance(base, dict) or not isinstance(base.get('content'), dict):
        _fail('基版本冻结快照无效')
    content = base['content']
    base_text = json.dumps(content, ensure_ascii=False)
    if len(base_text) > MAX_BASE_JSON:
        _fail('基稿超出支持范围（%d 码点 > %d），请先精简后再优化'
              % (len(base_text), MAX_BASE_JSON))
    context = prompt_context(base, extras)
    size = context_chars(context)
    if size > MAX_CONTEXT_JSON:
        _fail('研究上下文超过 %d 码点上限（当前 %d），请减少附加资料或来源原文'
              % (MAX_CONTEXT_JSON, size))
    allowed_refs(base, extras)
    targets = optimization.get('targets') or []
    limit = optimization.get('max_body_chars')
    instruction = spec.get('instruction') or ''
    lines = [
        '本次优化基于版本：v%d' % base.get('version'),
        '',
        '研究稿主题（该版本保存时，优化后必须保持不变）：%s' % (base.get('topic') or '未记录'),
        '',
        '业务现状（该版本保存时）：',
        status_lines(base.get('status') or {}),
        '',
        '该版本冻结的策略边界（保存该版本时的快照；不由本次优化改写）：',
    ]
    lines.extend(_strategy_lines(base.get('strategy') or frozen_strategy(base)))
    lines.extend([
        '',
        '本次优化目标（用户多选，必须全部落实；不得用编造案例、夸大或删除限制来制造效果）：',
        '- ' + '；'.join('%s（%s）' % (TARGET_LABELS[item], item) for item in targets),
        '本次优化说明：%s' % (instruction if instruction else '（未提供本次说明；只按优化目标修改）'),
        '正文字符硬上限：%s' % (
            '%d 码点（按实际保存的正文原串计，含空白、标点、Markdown 标记与换行）' % limit
            if limit is not None else '未指定（仍受 %d 码点总上限）' % MAX_BODY),
        '',
        '当前研究稿（该版本完整 JSON 原文；不可截断、不可只改片段）：',
        base_text,
        '',
        '该版本固定的资料来源（basis 只能使用下列 id；原文完整，限制与条件不得删改）：',
    ])
    lines.extend(_ref_lines(base))
    lines.extend(_research_source_lines(base))
    inherited = base.get('inherited') or []
    if inherited:
        lines.extend(['', '该基版本已保存的附加依据（继承自更早轮次；属于该基版本自身的冻结依据，'
                          '本轮未重新勾选也不得删除、改名或改写）：'])
        lines.extend(_artifact_lines(inherited))
    selected = effective_extras(base, extras)
    lines.extend(['', '本次另选资料（本轮明确选择；只在本轮生效，只能作为补充参考，'
                      '不得覆盖上面基版本的事实、来源与限制）：'])
    lines.extend(_artifact_lines(selected))
    lines.extend([
        '',
        '要求：',
        '1. 主题不变；保留仍成立的事实、限定条件、来源与依据；不编造案例、数字、资质、承诺或指标。',
        '2. 输出完整新正文：draft_markdown 必须是原始字符串（不要只给片段、不要自行截断、'
        '不要省略空白或 Markdown 标记），以实际保存的原串计码点 ≤%d%s。' % (
            MAX_BODY,
            '；本次硬上限 %d 码点，超过即判为不合法（不要靠截断凑长度）' % limit
            if limit is not None else ''),
        '3. facts 的 basis 只能使用上面列出的引用 id；没有依据的表述写进 gaps/questions 并标待验证'
        '；facts/changes 的 id 只用字母、数字、下划线、连字符，≤20 且组内唯一。',
        '4. changes 必填 %d–%d 项，逐项说明改了什么、为什么、依据、条件、缺口、下一步；'
        '没有依据的调整 basis 留空，不得伪造依据。' % (1, MAX_CHANGES),
        '5. 只输出 JSON，不要解释；结构：',
        _SCHEMA,
    ])
    return _SYSTEM, '\n'.join(lines)


def validate_result(data, allowed=None, max_body_chars=None):
    """严格校验模型结果（或 demo 结果）：不 strip、不 slice、不静默删项。"""
    if not isinstance(data, dict):
        _fail('模型输出结构无效')
    unknown = sorted(str(key) for key in data if key not in _RESULT_KEYS)
    if unknown:
        _fail('模型输出包含不支持的字段：%s' % '、'.join(unknown))
    title = data.get('title')
    if not isinstance(title, str) or not title.strip():
        _fail('缺少标题')
    if len(title) > MAX_TITLE:
        _fail('标题超过 %d 码点上限' % MAX_TITLE)
    summary = data.get('summary', '')
    if not isinstance(summary, str):
        _fail('摘要必须是字符串')
    if len(summary) > MAX_SUMMARY:
        _fail('摘要超过 %d 码点上限' % MAX_SUMMARY)
    allowed_set = set(allowed or [])
    for ref in allowed_set:
        if not isinstance(ref, str):
            _fail('本次引用映射无效')
    facts = _facts(data, allowed_set)
    outline = _text_list(data, 'outline', '结构')
    gaps = _text_list(data, 'gaps', '缺口')
    questions = _text_list(data, 'questions', '待决定')
    body = data.get('draft_markdown')
    if not isinstance(body, str) or not body.strip():
        _fail('缺少正文')
    if len(body) > MAX_BODY:
        _fail('正文超过 %d 码点总上限（当前 %d）' % (MAX_BODY, len(body)))
    if max_body_chars is not None:
        if not _is_int(max_body_chars):
            _fail('正文字符硬上限无效')
        if len(body) > max_body_chars:
            _fail('正文超过本次硬上限 %d 码点（当前 %d，按保存原串计）'
                  % (max_body_chars, len(body)))
    changes = _changes(data.get('changes'), allowed_set)
    return {'title': title, 'summary': summary, 'facts': facts, 'outline': outline,
            'draft_markdown': body, 'gaps': gaps, 'questions': questions, 'changes': changes}


def _facts(data, allowed):
    if 'facts' not in data:
        return []
    value = data['facts']
    if not isinstance(value, list):
        _fail('facts 必须是数组')
    if len(value) > MAX_FACTS:
        _fail('事实最多 %d 条' % MAX_FACTS)
    rows, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            _fail('事实行必须是对象')
        unknown = sorted(str(key) for key in item if key not in _FACT_KEYS)
        if unknown:
            _fail('事实行含不支持的字段：%s' % '、'.join(unknown))
        ident = item.get('id')
        if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
            _fail('事实 ID 必须是 %s 范围内的安全字符串' % '[A-Za-z0-9_-]{1,20}')
        if ident in seen:
            _fail('事实 ID 重复：%s' % ident)
        seen.add(ident)
        text = item.get('text')
        if not isinstance(text, str) or not text.strip():
            _fail('事实缺少正文')
        if len(text) > MAX_FACT_TEXT:
            _fail('事实正文超过 %d 码点上限' % MAX_FACT_TEXT)
        basis = item.get('basis', [])
        if not isinstance(basis, list) or any(not isinstance(ref, str) for ref in basis):
            _fail('事实 basis 必须是字符串数组')
        unknown_basis = [ref for ref in basis if ref not in allowed]
        if unknown_basis:
            _fail('事实引用了本次未提供的依据：%s' % '、'.join(unknown_basis))
        if len(set(basis)) != len(basis):
            _fail('事实 basis 重复')
        source = item.get('source', '')
        if not isinstance(source, str):
            _fail('事实来源必须是字符串')
        unverified = item.get('unverified', not basis)
        if not isinstance(unverified, bool):
            _fail('事实的待验证标记必须是布尔值')
        if not basis and unverified is False:
            _fail('空依据的事实不能声明为已验证（unverified=false）；没有依据必须标待验证')
        row = {'id': ident, 'text': text, 'source': source, 'basis': list(basis)}
        if unverified:
            row['unverified'] = True
        rows.append(row)
    return rows


def _text_list(data, key, name):
    if key not in data:
        return []
    value = data[key]
    if not isinstance(value, list):
        _fail('%s必须是字符串数组' % name)
    if len(value) > MAX_LIST_ITEMS:
        _fail('%s最多 %d 条' % (name, MAX_LIST_ITEMS))
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _fail('%s的每一项必须是非空字符串' % name)
        if len(item) > MAX_LIST_TEXT:
            _fail('%s的每一项超过 %d 码点上限' % (name, MAX_LIST_TEXT))
        result.append(item)
    return result


def _changes(value, allowed):
    if not isinstance(value, list):
        _fail('缺少修改说明 changes（必须是数组）')
    if not 1 <= len(value) <= MAX_CHANGES:
        _fail('修改说明必须是 1–%d 项' % MAX_CHANGES)
    rows, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            _fail('修改说明的每一项必须是对象')
        unknown = sorted(str(key) for key in item if key not in _CHANGE_KEYS)
        if unknown:
            _fail('修改说明含不支持的字段：%s' % '、'.join(unknown))
        missing = [key for key in _CHANGE_KEYS if key not in item]
        if missing:
            _fail('修改说明缺少字段：%s' % '、'.join(missing))
        ident = item['id']
        if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
            _fail('修改说明 ID 必须是 %s 范围内的安全字符串' % '[A-Za-z0-9_-]{1,20}')
        if ident in seen:
            _fail('修改说明 ID 重复：%s' % ident)
        seen.add(ident)
        text = item['text']
        if not isinstance(text, str) or not text.strip():
            _fail('修改说明缺少“改了什么”')
        if len(text) > MAX_CHANGE_TEXT:
            _fail('修改说明“改了什么”超过 %d 码点上限' % MAX_CHANGE_TEXT)
        why = item['why']
        if not isinstance(why, str) or not why.strip():
            _fail('修改说明缺少“为什么”')
        if len(why) > MAX_CHANGE_WHY:
            _fail('修改说明“为什么”超过 %d 码点上限' % MAX_CHANGE_WHY)
        basis = item['basis']
        if not isinstance(basis, list) or any(not isinstance(ref, str) for ref in basis):
            _fail('修改说明 basis 必须是字符串数组')
        if len(basis) > MAX_CHANGE_BASIS:
            _fail('修改说明 basis 最多 %d 个' % MAX_CHANGE_BASIS)
        if len(set(basis)) != len(basis):
            _fail('修改说明 basis 重复')
        unknown_basis = [ref for ref in basis if ref not in allowed]
        if unknown_basis:
            _fail('修改说明引用了本次未提供的依据：%s' % '、'.join(unknown_basis))
        conditions = _text_items(item['conditions'], '修改说明 conditions')
        gaps = _text_items(item['gaps'], '修改说明 gaps')
        next_step = item['next_step']
        if not isinstance(next_step, str):
            _fail('修改说明 next_step 必须是字符串')
        if len(next_step) > MAX_NEXT_STEP:
            _fail('修改说明 next_step 超过 %d 码点上限' % MAX_NEXT_STEP)
        rows.append({'id': ident, 'text': text, 'why': why, 'basis': list(basis),
                     'conditions': conditions, 'gaps': gaps, 'next_step': next_step})
    return rows


def _text_items(value, name):
    if not isinstance(value, list):
        _fail('%s 必须是字符串数组' % name)
    if len(value) > MAX_CHANGE_ITEMS:
        _fail('%s 最多 %d 条' % (name, MAX_CHANGE_ITEMS))
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _fail('%s 的每一项必须是非空字符串' % name)
        if len(item) > MAX_CHANGE_ITEM_TEXT:
            _fail('%s 的每一项超过 %d 码点上限' % (name, MAX_CHANGE_ITEM_TEXT))
        result.append(item)
    return result


def parse_result(text, allowed=None, max_body_chars=None):
    """解析模型原始输出；失败直接拒绝，不二次调用、不二次清洗。"""
    if not isinstance(text, str) or not text.strip():
        _fail('模型输出为空')
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        _fail('模型输出不是合法 JSON')
    return validate_result(data, allowed, max_body_chars)


def run_once(invoke, spec, base, extras=()):
    """一次性调用：构造 messages → invoke → 严格解析；不重试、不补救。"""
    if not callable(invoke):
        _fail('模型调用入口无效')
    system, user = build_messages(spec, base, extras)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    text = invoke(messages)
    if not isinstance(text, str) or not text.strip():
        _fail('模型调用返回为空')
    optimization = (spec or {}).get('optimization') or {}
    return parse_result(text, allowed_refs(base, extras), optimization.get('max_body_chars'))


def demo_result(spec, base, extras=()):
    """中性本地 demo：只追加“未实际重写/压缩”的说明，同样过全部校验。"""
    optimization = (spec or {}).get('optimization')
    if not isinstance(optimization, dict):
        _fail('本请求未提供 optimization，不能进入 D 深度优化')
    content = (base or {}).get('content')
    if not isinstance(content, dict):
        _fail('基版本冻结快照无效')
    body = content.get('draft_markdown')
    if not isinstance(body, str) or not body.strip():
        _fail('基版本缺少正文，无法优化')
    note = '\n\n> 本地演示：未实际重写或压缩正文，仅追加本次说明。'
    data = {
        'title': content.get('title') if isinstance(content.get('title'), str) else '',
        'summary': '本地演示：未实际重写正文，仅验证优化流程与长度约束，不代表真实模型质量。',
        'facts': content.get('facts') if isinstance(content.get('facts'), list) else [],
        'outline': content.get('outline') if isinstance(content.get('outline'), list) else [],
        'draft_markdown': body + note,
        'gaps': content.get('gaps') if isinstance(content.get('gaps'), list) else [],
        'questions': content.get('questions') if isinstance(content.get('questions'), list) else [],
        'changes': [{
            'id': 'demo1',
            'text': '本地演示：未实际重写或压缩正文，仅追加本次说明',
            'why': '演示只验证流程、版本与长度约束；真实改写质量需在真实模型分支另行验收',
            'basis': [],
            'conditions': ['真实改写需在配置完成后另行确认调用'],
            'gaps': ['本次未产生真实改写内容'],
            'next_step': '如需真实改写，请在模型配置完成后单独确认调用',
        }],
    }
    return validate_result(data, allowed_refs(base, extras), optimization.get('max_body_chars'))


def industry_snapshot(base):
    """基版本已有行业字段则原样冻结；没有就明确未提供，不伪造行业已配置。"""
    for holder in ((base or {}).get('context'), (base or {}).get('content')):
        if isinstance(holder, dict):
            raw = holder.get('industry')
            if isinstance(raw, dict) and raw:
                return {'status': 'frozen', 'data': copy.deepcopy(raw)}
            if isinstance(raw, str) and raw.strip():
                return {'status': 'frozen', 'code': raw}
    return {'status': 'not_provided'}


def version_context(spec, base, result, extras=(), source='demo'):
    """新版本 context_json：保留基版冻结 context，并新增本次优化的元信息快照。

    附加依据分两栏：inherited_artifacts（随基版继承，不因本轮未勾选而删除）与
    selected_artifacts（本轮明确选择，记录选入时的基版本）。旧版本行不修改。
    """
    optimization = (spec or {}).get('optimization') or {}
    targets = list(optimization.get('targets') or [])
    inherited = copy.deepcopy(list(base.get('inherited') or []))
    selected = copy.deepcopy(effective_extras(base, extras))
    for item in selected:
        item['selected_base_version'] = base.get('version')
    context = copy.deepcopy(base.get('context') or {})
    context['draft_optimization'] = {
        'base_version': base.get('version'),
        'targets': targets,
        'target_labels': [TARGET_LABELS[item] for item in targets],
        'instruction': (spec or {}).get('instruction') or '',
        'max_body_chars': optimization.get('max_body_chars'),
        'body_chars': body_chars((result or {}).get('draft_markdown')),
        'source': source,
        'inherited_artifacts': inherited,
        'selected_artifacts': selected,
        'industry': industry_snapshot(base),
    }
    return context


def version_payload(spec, base, result, extras=(), source='demo'):
    """交给 ops.add_draft_version 的载荷（不含 draft_uid/model/run_id/usage）。"""
    if source not in ('demo', 'llm'):
        _fail('版本来源必须是 demo 或 llm')
    if not isinstance(result, dict):
        _fail('优化结果无效')
    return {'content': result,
            'instruction': (spec or {}).get('instruction') or '',
            'source': source,
            'topic': base.get('topic') or '',
            'status': base.get('status') or {},
            'context': version_context(spec, base, result, extras, source),
            'base_version': base.get('version'),
            'legacy_snapshot': bool(base.get('legacy'))}


def changes_markdown(result):
    """把结构化修改说明渲染为 Markdown（供 D2 导出；不改旧 M02 导出函数）。"""
    lines = ['## 本次修改说明', '']
    for item in (result or {}).get('changes') or []:
        lines.append('### %s. %s' % (item.get('id'), item.get('text')))
        lines.append('- 为什么：%s' % item.get('why'))
        lines.append('- 依据：%s' % ('、'.join(item.get('basis') or []) or '无（表达调整，无新增依据）'))
        conditions = item.get('conditions') or []
        gaps = item.get('gaps') or []
        if conditions:
            lines.append('- 适用条件：%s' % '；'.join(conditions))
        if gaps:
            lines.append('- 缺口：%s' % '；'.join(gaps))
        if item.get('next_step'):
            lines.append('- 下一步：%s' % item.get('next_step'))
        lines.append('')
    return '\n'.join(lines).rstrip('\n')
