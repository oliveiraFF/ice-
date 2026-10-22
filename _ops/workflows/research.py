"""M05-A 多源研究：输入契约、提示构建、严格解析与中性演示。

- 只把服务端冻结的 s1…sN 资料交给模型；模型引用号必须属于本次映射。
- 角色分离：业务限制/自有表现/受众需求/外部参考/人工摘录/模型推断。
- 输出严格校验；超限拒绝，不静默截断。
"""
import json
import re

ROLE_LABELS = {
    'pain': '受众痛点（评论/咨询原文）',
    'reference': '外部参考',
    'draft': '本业务研究稿版本',
    'record': '本业务已登记作品',
    'consultation': '本业务咨询摘录（人工记录，非平台核验）',
    'review': '本业务复盘（冻结快照）',
    'manual': '人工摘录（人工提供，未独立核实）',
    'strategy': '业务/策略限制',
    'metrics': '自有经营表现',
}

MAX_TOPIC = 200
MAX_FIELD = 2000
MAX_QUESTION = 1000
MAX_SOURCES = 12
MAX_MANUAL = 6000
MAX_CONTEXT = 24000
MAX_SUMMARY = 2000
MAX_TEXT = 1500
MAX_ITEMS = 12
MAX_BASIS = 12
MAX_CONDITIONS = 8
MAX_CONDITION_TEXT = 500
MAX_NEXT = 500

_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')
_FIELDS = ('business', 'audience', 'goal', 'resources', 'capacity', 'question')

_SYSTEM = ('你是本地单用户研究助手。只基于本次提供的资料研究；把业务/策略限制、自有经营表现、'
           '受众需求信号、外部参考、人工摘录与模型推断分开。外部参考的热度不能证明本业务需求；'
           '自有表现不能证明受众需求；人工摘录由用户提供，未独立核实；模型推断不得当事实。'
           '只能引用本次给出的 s1…sN 资料号；不得编造数据、出处、案例、身份或承诺。'
           '输出必须是 JSON，不要额外说明。')

_SCHEMA = '''{
  "summary": "本次研究摘要（不超过2000字）",
  "observations": [{"id": "o1", "text": "有原始资料支持的观察", "basis": ["s1"]}],
  "inferences": [{"id": "i1", "text": "明确标注的推断", "why": "推断理由", "basis": ["s1"], "conditions": ["成立条件"], "gaps": ["缺口"], "next_step": "下一步"}],
  "suggestions": [{"id": "g1", "text": "可执行建议", "why": "理由", "basis": ["s1"], "conditions": ["适用条件"], "gaps": ["缺口"], "next_step": "下一步"}],
  "conflicts": [{"text": "相互冲突的资料或说法", "why": "冲突说明", "basis": ["s1", "s2"]}],
  "cannot_judge": ["仍不能判断的问题"]
}'''


def _text(value, name, limit, required=True):
    if value is None:
        if required:
            raise ValueError('%s不能为空' % name)
        return ''
    if not isinstance(value, str):
        raise ValueError('%s必须是文本' % name)
    value = value.strip()
    if required and not value:
        raise ValueError('%s不能为空' % name)
    if len(value) > limit:
        raise ValueError('%s超过 %d 字符上限' % (name, limit))
    return value


def _str_list(value, name, limit=MAX_CONDITIONS, cap=MAX_CONDITION_TEXT):
    if not isinstance(value, list):
        raise ValueError('%s必须是数组' % name)
    if len(value) > limit:
        raise ValueError('%s最多 %d 条' % (name, limit))
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('%s每项必须是文本' % name)
        item = item.strip()
        if not item:
            raise ValueError('%s每项不能为空' % name)
        if len(item) > cap:
            raise ValueError('%s每项超过 %d 字符上限' % (name, cap))
        result.append(item)
    return result


def _int(value, name):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('%s必须是非负整数' % name)
    return value


def validate_input(body):
    if not isinstance(body, dict):
        raise ValueError('请求格式无效')
    topic = _text(body.get('topic'), '研究主题', MAX_TOPIC)
    if 'question' in body:
        raw_question = body['question']
        if not isinstance(raw_question, str):
            raise ValueError('本次问题必须是文本')
        question = _text(raw_question, '本次问题', MAX_QUESTION, required=False)
    else:
        question = ''
    if 'business' in body:
        raw_business = body['business']
        if not isinstance(raw_business, dict):
            raise ValueError('业务现状格式无效')
    else:
        raw_business = {}
    status = {}
    for key in _FIELDS:
        if key not in raw_business:
            status[key] = ''
            continue
        value = raw_business[key]
        if not isinstance(value, str):
            raise ValueError('业务字段 %s 必须是文本' % key)
        status[key] = _text(value, '业务字段 %s' % key, MAX_FIELD, required=False)
    if 'selected' in body:
        selected = body['selected']
        if not isinstance(selected, dict):
            raise ValueError('所选资料格式无效')
    else:
        selected = {}
    result = {'topic': topic, 'question': question, 'business': status,
              'selected': {'pain_ids': [], 'reference_ids': [], 'draft_uid': '', 'draft_version': 0,
                           'record_uid': '', 'consultation_ids': [], 'review_uids': [],
                           'manual_excerpts': []}}
    for key in ('pain_ids', 'reference_ids'):
        if key not in selected:
            continue
        value = selected[key]
        if not isinstance(value, list):
            raise ValueError('%s 必须是数组' % key)
        if len(value) > MAX_SOURCES:
            raise ValueError('%s 最多 %d 条' % (key, MAX_SOURCES))
        ids = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError('%s 必须是正整数 ID' % key)
            ids.append(item)
        result['selected'][key] = ids
    draft_uid = selected.get('draft_uid', '')
    draft_version = selected.get('draft_version', 0)
    if 'draft_uid' in selected and (not isinstance(draft_uid, str)):
        raise ValueError('研究稿 UID 无效')
    if draft_uid:
        if isinstance(draft_version, bool) or not isinstance(draft_version, int) or draft_version <= 0:
            raise ValueError('研究稿版本必须是正整数')
        result['selected']['draft_uid'] = draft_uid.strip()
        result['selected']['draft_version'] = draft_version
    elif draft_version not in ('', 0):
        raise ValueError('选择研究稿版本时必须同时提供 UID')
    record_uid = selected.get('record_uid', '')
    if 'record_uid' in selected and not isinstance(record_uid, str):
        raise ValueError('作品登记 UID 无效')
    if record_uid:
        result['selected']['record_uid'] = record_uid.strip()
    for key in ('consultation_ids', 'review_uids'):
        if key not in selected:
            continue
        value = selected[key]
        if not isinstance(value, list):
            raise ValueError('%s 必须是数组' % key)
        if len(value) > MAX_SOURCES:
            raise ValueError('%s 最多 %d 条' % (key, MAX_SOURCES))
        ids = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError('%s 必须是非空字符串' % key)
            ids.append(item.strip())
        result['selected'][key] = ids
    if 'manual_excerpts' in selected:
        excerpts = selected['manual_excerpts']
        if not isinstance(excerpts, list):
            raise ValueError('人工摘录必须是数组')
        if len(excerpts) > MAX_SOURCES:
            raise ValueError('人工摘录最多 %d 条' % MAX_SOURCES)
        rows = []
        for item in excerpts:
            if not isinstance(item, dict):
                raise ValueError('人工摘录每行必须是对象')
            text = _text(item.get('text'), '人工摘录正文', MAX_MANUAL)
            source = _text(item.get('source'), '人工摘录出处', 300)
            rows.append({'text': text, 'source': source})
        result['selected']['manual_excerpts'] = rows
    total = (len(result['selected']['pain_ids']) + len(result['selected']['reference_ids'])
             + len(result['selected']['consultation_ids']) + len(result['selected']['review_uids'])
             + len(result['selected']['manual_excerpts'])
             + (1 if result['selected']['draft_uid'] else 0)
             + (1 if result['selected']['record_uid'] else 0))
    if total > MAX_SOURCES:
        raise ValueError('显式选择资料最多 %d 条' % MAX_SOURCES)
    return result


def _strategy_lines(strategy):
    data = (strategy or {}).get('data') or {}
    lines = ['版本 v%s · %s' % ((strategy or {}).get('version') or 0,
                               '已确认' if (strategy or {}).get('confirmed') else '未确认')]
    if not isinstance(data, dict) or not data:
        lines.append('（未提供策略内容；不得假设存在默认已确认策略）')
        return lines
    for key, value in data.items():
        if isinstance(value, list):
            value = '；'.join(str(item) for item in value)
        lines.append('- %s：%s' % (key, value))
    return lines


def _ref_lines(refs):
    if not refs:
        return ['（无所选资料）']
    lines = []
    for ref in refs:
        lines.append('- %s [%s] %s' % (ref['id'], ref['label'], ref['text']))
        if ref.get('source'):
            lines.append('  出处：%s' % ref['source'])
    return lines


def build_research_prompt(input_data, context):
    business = input_data.get('business') or {}
    strategy = (context or {}).get('strategy') or {}
    refs = (context or {}).get('refs') or []
    user = ('研究主题：%s\n本次问题：%s\n\n业务现状：\n- 业务：%s\n- 受众：%s\n- 目标：%s\n'
            '- 资源：%s\n- 产能：%s\n- 当前问题：%s\n\n策略边界：\n%s\n\n'
            '本次所选资料（只能引用下列 s 号，未列出的资料不可用）：\n%s\n\n'
            '要求：\n'
            '1. 观察必须有原始资料 basis；推断和建议必须给出 why、basis、条件、缺口与下一步。\n'
            '2. 外部参考的热度只是参考，不等于本业务需求；自有指标只是经营表现，不证明受众需求。\n'
            '3. 人工摘录标注“人工提供，未独立核实”，不得升级为已验证需求。\n'
            '4. 资料冲突或不足必须显式保留，不用“共识”抹平；不能判断的写入 cannot_judge。\n'
            '5. 只能使用 s1…sN；不得编造资料号、事实、案例或身份。\n'
            '输出结构（JSON）：\n%s'
            ) % (input_data.get('topic'), input_data.get('question') or '未提供',
                 business.get('business') or '未填写', business.get('audience') or '未填写',
                 business.get('goal') or '未填写', business.get('resources') or '未填写',
                 business.get('capacity') or '未填写', business.get('question') or '未填写',
                 '\n'.join(_strategy_lines(strategy)), '\n'.join(_ref_lines(refs)), _SCHEMA)
    return _SYSTEM, user


def _row(item, name, basis_keys, kind):
    if not isinstance(item, dict):
        raise ValueError('%s 每行必须是对象' % name)
    text = _text(item.get('text'), '%s 正文' % name, MAX_TEXT)
    why = (_text(item['why'], '%s 理由' % name, 1000, required=(kind != 'observation'))
           if 'why' in item else '')
    basis = item.get('basis')
    if basis is None:
        basis = []
    if not isinstance(basis, list):
        raise ValueError('%s 的 basis 必须是数组' % name)
    if not basis:
        raise ValueError('%s 缺少依据' % name)
    if len(basis) > MAX_BASIS:
        raise ValueError('%s 依据最多 %d 个' % (name, MAX_BASIS))
    seen = set()
    clean = []
    for ref in basis:
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError('%s 依据必须是资料号字符串' % name)
        ref = ref.strip()
        if ref not in basis_keys:
            raise ValueError('%s 引用了未知资料号 %s' % (name, ref))
        if ref in seen:
            raise ValueError('%s 依据重复 %s' % (name, ref))
        seen.add(ref)
        clean.append(ref)
    conditions = _str_list(item['conditions'], '%s 条件' % name) if 'conditions' in item else []
    gaps = _str_list(item['gaps'], '%s 缺口' % name) if 'gaps' in item else []
    next_step = (_text(item['next_step'], '%s 下一步' % name, MAX_NEXT,
                       required=(kind != 'observation'))
                 if 'next_step' in item else '')
    row = {'text': text, 'why': why, 'basis': clean,
           'conditions': conditions, 'gaps': gaps, 'next_step': next_step}
    if kind != 'observation':
        if not row['why']:
            raise ValueError('%s 必须说明理由' % name)
        if not row['next_step']:
            raise ValueError('%s 必须给出下一步' % name)
    if 'id' in item:
        row_id = item['id']
        if not isinstance(row_id, str) or not _ID_RE.match(row_id):
            raise ValueError('%s 的 ID 无效' % name)
    else:
        row_id = ''
    row['id'] = row_id
    return row


def parse_research(text, ref_map):
    if not isinstance(ref_map, dict) or not ref_map:
        ref_map = {}
    basis_keys = set(ref_map.keys())
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError('研究输出不是合法 JSON')
    if not isinstance(data, dict):
        raise ValueError('研究输出必须是对象')
    summary = _text(data.get('summary'), '摘要', MAX_SUMMARY)
    result = {'summary': summary, 'observations': [], 'inferences': [], 'suggestions': [],
              'conflicts': [], 'cannot_judge': []}

    def _rows(key, name, kind):
        if key not in data:
            return []
        value = data[key]
        if not isinstance(value, list):
            raise ValueError('%s 必须是数组' % name)
        if len(value) > MAX_ITEMS:
            raise ValueError('%s 最多 %d 条' % (name, MAX_ITEMS))
        return value

    for index, item in enumerate(_rows('observations', '观察', 'observation'), 1):
        row = _row(item, '观察', basis_keys, 'observation')
        row['id'] = row['id'] or 'o%d' % index
        result['observations'].append(row)
    for key, name, prefix, kind in (('inferences', '推断', 'i', 'inference'),
                                    ('suggestions', '建议', 'g', 'suggestion')):
        for index, item in enumerate(_rows(key, name, kind), 1):
            row = _row(item, name, basis_keys, kind)
            row['id'] = row['id'] or '%s%d' % (prefix, index)
            result[key].append(row)
    for index, item in enumerate(_rows('conflicts', '冲突', 'conflict'), 1):
        if not isinstance(item, dict):
            raise ValueError('冲突每行必须是对象')
        row = {'text': _text(item.get('text'), '冲突正文', MAX_TEXT),
               'why': _text(item.get('why'), '冲突理由', 1000),
               'basis': item.get('basis')}
        if not isinstance(row['basis'], list) or len(row['basis']) < 2:
            raise ValueError('冲突至少需要两条依据')
        if len(row['basis']) > MAX_BASIS:
            raise ValueError('冲突依据最多 %d 个' % MAX_BASIS)
        clean, seen = [], set()
        for ref in row['basis']:
            if not isinstance(ref, str) or ref not in basis_keys:
                raise ValueError('冲突引用了未知资料号')
            if ref in seen:
                raise ValueError('冲突依据重复')
            seen.add(ref)
            clean.append(ref)
        row['basis'] = clean
        result['conflicts'].append(row)
    cannot = _rows('cannot_judge', '不能判断', 'cannot')
    for item in cannot:
        if not isinstance(item, str):
            raise ValueError('不能判断的每项必须是文本')
        item = item.strip()
        if not item:
            raise ValueError('不能判断的项不能为空')
        if len(item) > MAX_CONDITION_TEXT:
            raise ValueError('不能判断的项超过 %d 字符' % MAX_CONDITION_TEXT)
        result['cannot_judge'].append(item)
    groups = (result['observations'], result['inferences'], result['suggestions'])
    for rows in groups:
        ids = [row['id'] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError('同一组内 ID 重复')
    if not (result['observations'] or result['suggestions'] or result['conflicts']
            or result['cannot_judge']):
        raise ValueError('研究输出缺少观察、建议、冲突或问题')
    return result


def demo_research(input_data, context):
    refs = (context or {}).get('refs') or []
    strategy = (context or {}).get('strategy') or {}
    counts = {}
    for ref in refs:
        counts[ref.get('role') or 'other'] = counts.get(ref.get('role') or 'other', 0) + 1
    roles = '、'.join('%s %d 条' % (ROLE_LABELS.get(key, key), counts[key]) for key in counts)
    strategy_note = '策略边界 v%s（%s）。' % (
        strategy.get('version') or 0, '已确认' if strategy.get('confirmed') else '未确认')
    observations = []
    inferences = []
    suggestions = []
    conflicts = []
    cannot = ['演示模式未调用模型，不能判断真实受众需求或内容质量。',
              '没有完整观看素材，不能判断画面/音轨。']
    if refs:
        basis = [ref['id'] for ref in refs][:MAX_BASIS]
        observations.append({'id': 'o1', 'text': '本次显式选择资料 %d 条（%s）；%s'
                             % (len(refs), roles or '无', strategy_note),
                             'why': '', 'basis': basis,
                             'conditions': [], 'gaps': [], 'next_step': ''})
        inferences.append({'id': 'i1', 'text': '演示研究只校验资料选择与流程，不代表真实内容判断。',
                           'why': '演示模式不调用模型', 'basis': basis[:1],
                           'conditions': ['需要真实模型与人工复核'], 'gaps': ['未做真实语义分析'],
                           'next_step': '配置模型后单独执行真实研究'})
        suggestions.append({'id': 'g1', 'text': '先补齐所选资料的原文、出处与时间，再执行真实研究。',
                            'why': '资料不足时推断会失去依据', 'basis': basis[:1],
                            'conditions': ['用户确认资料范围'], 'gaps': ['缺少可核验来源'],
                            'next_step': '补充资料后重试'})
        if any(ref.get('role') == 'reference' for ref in refs) and any(
                ref.get('role') in ('record', 'draft', 'metrics') for ref in refs):
            first = [ref['id'] for ref in refs if ref.get('role') == 'reference'][0]
            second = [ref['id'] for ref in refs
                      if ref.get('role') in ('record', 'draft', 'metrics')][0]
            conflicts.append({'text': '外部参考与本业务记录的角色不同，不能互相证明。',
                              'why': '参考热度不等于本业务需求；自有表现不等于受众需求。',
                              'basis': [first, second]})
    else:
        cannot.append('本次没有选择任何资料：只能列问题清单，不能形成需求或效果结论。')
    return {'summary': '演示研究：仅验证资料角色、来源映射与保存流程，未真实分析内容。'
                       + ('本次无所选资料。' if not refs else ''),
            'observations': observations, 'inferences': inferences, 'suggestions': suggestions,
            'conflicts': conflicts, 'cannot_judge': cannot, 'source': 'demo'}


# ---------------------------------------------------------------------------
# M05-B 语义选题建议（kind=topics）：需求角色、严格输出契约与中性演示。
# 只做研究用途候选，不是正式选题、批准或发布；不证明真实需求已验证。
# ---------------------------------------------------------------------------

DEMAND_ROLES = ('audience_pain', 'search_interest', 'hot_topic',
                'industry_signal', 'market_task', 'content_gap')
DEMAND_ROLE_LABELS = {
    'audience_pain': '受众痛点/咨询原文依据',
    'search_interest': '搜索兴趣依据',
    'hot_topic': '热点话题依据',
    'industry_signal': '行业信号依据',
    'market_task': '市场任务依据',
    'content_gap': '内容缺口依据',
}
MAX_CANDIDATES = 6
MAX_CANDIDATE_ID = 20
MAX_AUDIENCE_PROBLEM = 1500
MAX_FIT = 1000
MAX_WHY = 1000
MAX_CANNOT = 12
MAX_CANNOT_TEXT = 500
MAX_TOPICS_SUMMARY = 2000
TOPIC_STATES = ('research_candidate', 'needs_validation')

_TOPICS_SYSTEM = ('你是本地单用户研究助手，只生成研究用途的选题建议。只基于本次提供的父记录冻结资料：'
                  '父记录的业务/策略边界、s1…sN 原始来源、以及父记录自己的模型观察/推断（必须按模型输出标注，'
                  '不得当成新的事实）。外部参考热度不等于本业务需求；自有指标不等于受众需求；复盘建议、'
                  '研究稿正文与模型推断都不是需求证据。人工声明的需求角色由用户提供，未独立核实。'
                  '只能引用本次给出的 s1…sN；不得编造资料号、出处、身份、数据或结论。'
                  '选题建议不是正式选题，状态只能是 research_candidate（研究候选）或 needs_validation（待验证）。'
                  '不要输出 ready/formal/approved，也不要承诺爆款、效果或需求已验证。输出必须是 JSON。')

_TOPICS_SCHEMA = '''{
  "summary": "本次选题建议摘要（不超过2000字符）",
  "candidates": [{
    "id": "c1",
    "topic": "研究用途选题（1-200字符）",
    "audience_problem": "受众问题/需求描述（1-1500字符）",
    "basis": ["s1"],
    "demand_basis": ["s1"],
    "fit_reason": "与父记录策略边界的适配理由（1-1000字符）",
    "why": "为什么值得研究（1-1000字符）",
    "conditions": ["成立条件"],
    "gaps": ["缺口"],
    "next_step": "下一步（不超过500字符）",
    "state": "research_candidate | needs_validation"
  }],
  "cannot_judge": ["仍不能判断、需要人工核实的问题（每项不超过500字符）"]
}'''


_CANDIDATE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')


def _candidate_id(value, name, legacy_ids=False):
    if (legacy_ids and isinstance(value, int) and not isinstance(value, bool)
            and 1 <= value <= MAX_CANDIDATE_ID):
        return str(value)
    if not isinstance(value, str) or not _CANDIDATE_ID_RE.fullmatch(value):
        raise ValueError('%s 必须是 1–20 位 [A-Za-z0-9_-] 字符串' % name)
    return value


def _basis_list(value, name, basis_ids):
    if value is None:
        raise ValueError('%s 不能为 null' % name)
    if not isinstance(value, list):
        raise ValueError('%s 必须是数组' % name)
    if len(value) > MAX_BASIS:
        raise ValueError('%s 最多 %d 个' % (name, MAX_BASIS))
    clean = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError('%s 每项必须是非空资料号字符串' % name)
        item = item.strip()
        if item not in basis_ids:
            raise ValueError('%s 引用了未知资料号 %s' % (name, item))
        if item in seen:
            raise ValueError('%s 依据重复 %s' % (name, item))
        seen.add(item)
        clean.append(item)
    return clean


def _topics_text_list(value, name, limit, cap):
    if value is None:
        raise ValueError('%s 不能为 null' % name)
    if not isinstance(value, list):
        raise ValueError('%s 必须是数组' % name)
    if len(value) > limit:
        raise ValueError('%s 最多 %d 条' % (name, limit))
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('%s 每项必须是文本' % name)
        item = item.strip()
        if not item:
            raise ValueError('%s 每项不能为空' % name)
        if len(item) > cap:
            raise ValueError('%s 每项超过 %d 字符上限' % (name, cap))
        result.append(item)
    return result


def _topics_text(value, name, limit):
    if value is None:
        raise ValueError('%s 不能为空' % name)
    if not isinstance(value, str):
        raise ValueError('%s 必须是文本' % name)
    value = value.strip()
    if not value:
        raise ValueError('%s 不能为空' % name)
    if len(value) > limit:
        raise ValueError('%s 超过 %d 字符上限' % (name, limit))
    return value


def validate_candidate(item, basis_ids, demand_basis_allowed, strategy_confirmed, index,
                       legacy_ids=False):
    """校验单个 B 候选；basis_ids/demand_basis_allowed 为服务端认定的集合。

    R4：id 为字符串；basis/demand_basis/conditions/gaps 四项必填（可为空数组）。
    legacy_ids 仅用于读取旧整数 ID 记录的明确兼容分支，不放宽新模型输出。
    """
    if not isinstance(item, dict):
        raise ValueError('候选 %s 必须是对象' % index)
    name = '候选 %s' % index
    cid = _candidate_id(item.get('id'), '%s 的 id' % name, legacy_ids)
    topic = _topics_text(item.get('topic'), '%s 的 topic' % name, MAX_TOPIC)
    problem = _topics_text(item.get('audience_problem'),
                           '%s 的 audience_problem' % name, MAX_AUDIENCE_PROBLEM)
    for field in ('basis', 'demand_basis', 'conditions', 'gaps'):
        if field not in item:
            raise ValueError('%s 缺少 %s（可为空数组，但不能缺省）' % (name, field))
    basis = _basis_list(item['basis'], '%s 的 basis' % name, basis_ids)
    demand = _basis_list(item['demand_basis'], '%s 的 demand_basis' % name, basis_ids)
    for ident in demand:
        if ident not in basis:
            raise ValueError('%s 的 demand_basis 必须是 basis 的子集' % name)
        if ident not in demand_basis_allowed:
            raise ValueError('%s 的 demand_basis 引用了非需求角色来源 %s' % (name, ident))
    fit = _topics_text(item.get('fit_reason'), '%s 的 fit_reason' % name, MAX_FIT)
    why = _topics_text(item.get('why'), '%s 的 why' % name, MAX_WHY)
    conditions = _topics_text_list(item['conditions'], '%s 的 conditions' % name,
                                   MAX_CONDITIONS, MAX_CONDITION_TEXT)
    gaps = _topics_text_list(item['gaps'], '%s 的 gaps' % name,
                             MAX_CONDITIONS, MAX_CONDITION_TEXT)
    next_step = _topics_text(item.get('next_step'), '%s 的 next_step' % name, MAX_NEXT)
    state = item.get('state')
    if not isinstance(state, str) or state not in TOPIC_STATES:
        raise ValueError('%s 的 state 只能是 research_candidate 或 needs_validation' % name)
    if state == 'research_candidate':
        if not strategy_confirmed:
            raise ValueError('%s 声称 research_candidate，但父快照策略未确认' % name)
        if not demand:
            raise ValueError('%s 声称 research_candidate，但缺少有效 demand_basis' % name)
    return {'id': cid, 'topic': topic, 'audience_problem': problem,
            'basis': basis, 'demand_basis': demand,
            'fit_reason': fit, 'why': why,
            'conditions': conditions, 'gaps': gaps,
            'next_step': next_step, 'state': state}


def parse_topics(text, basis_ids, demand_basis_allowed, strategy_confirmed):
    """严格解析 B 输出；不截断、不强转、不静默删行。"""
    basis_ids = set(basis_ids or [])
    demand_basis_allowed = set(demand_basis_allowed or [])
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError('选题输出不是合法 JSON')
    if not isinstance(data, dict):
        raise ValueError('选题输出必须是对象')
    if 'summary' not in data or data.get('summary') is None:
        raise ValueError('摘要不能为空')
    if not isinstance(data.get('summary'), str):
        raise ValueError('摘要必须是文本')
    summary = data['summary'].strip()
    if len(summary) > MAX_TOPICS_SUMMARY:
        raise ValueError('摘要超过 %d 字符上限' % MAX_TOPICS_SUMMARY)
    if 'candidates' not in data or data['candidates'] is None:
        raise ValueError('candidates 不能为空值')
    rows = data['candidates']
    if not isinstance(rows, list):
        raise ValueError('candidates 必须是数组')
    if len(rows) > MAX_CANDIDATES:
        raise ValueError('candidates 最多 %d 条' % MAX_CANDIDATES)
    candidates = []
    seen = set()
    for index, row in enumerate(rows, 1):
        candidate = validate_candidate(row, basis_ids, demand_basis_allowed,
                                       strategy_confirmed, index)
        if candidate['id'] in seen:
            raise ValueError('候选 id 重复：%s' % candidate['id'])
        seen.add(candidate['id'])
        candidates.append(candidate)
    cannot = (_topics_text_list(data['cannot_judge'], 'cannot_judge',
                                MAX_CANNOT, MAX_CANNOT_TEXT)
              if 'cannot_judge' in data else [])
    return {'summary': summary, 'candidates': candidates, 'cannot_judge': cannot}


def _topics_parent_business(input_data):
    business = (input_data or {}).get('business') or {}
    if not isinstance(business, dict):
        business = {}
    result = {}
    for key in _FIELDS:
        value = business.get(key)
        if value is None:
            result[key] = ''
        elif isinstance(value, str):
            result[key] = value.strip()[:MAX_FIELD]
        else:
            raise ValueError('父记录业务字段 %s 不是文本' % key)
    return result


def _topics_parent_result_lines(result):
    if not result:
        return ['（父记录未分析：只能按已有资料提出研究问题，不得虚构父研究结论）']
    lines = []
    summary = result.get('summary')
    if isinstance(summary, str) and summary.strip():
        lines.append('父记录模型摘要（模型输出，不是原始事实）：%s' % summary.strip())
    for title, key, prefix in (('观察', 'observations', '父观察'),
                               ('推断', 'inferences', '父推断'),
                               ('建议', 'suggestions', '父建议')):
        for row in result.get(key) or []:
            if not isinstance(row, dict):
                continue
            parts = [('%s：%s' % (prefix, row.get('text') or ''))]
            if row.get('why'):
                parts.append('理由：%s' % row.get('why'))
            if row.get('basis'):
                parts.append('依据：%s' % '、'.join(str(item) for item in row.get('basis')))
            if row.get('conditions'):
                parts.append('条件：%s' % '；'.join(str(item) for item in row.get('conditions')))
            if row.get('gaps'):
                parts.append('缺口：%s' % '；'.join(str(item) for item in row.get('gaps')))
            if row.get('next_step'):
                parts.append('下一步：%s' % row.get('next_step'))
            parts.append('角色：父记录的模型输出，不是新的原始事实')
            lines.append('；'.join(parts))
    for row in result.get('conflicts') or []:
        if isinstance(row, dict):
            lines.append('父冲突记录（模型标注，不是事实）：%s；依据：%s；说明：%s' % (
                row.get('text') or '', '、'.join(str(item) for item in (row.get('basis') or [])),
                row.get('why') or ''))
    for item in result.get('cannot_judge') or []:
        lines.append('父记录仍不能判断（模型输出）：%s' % str(item))
    return lines or ['（父记录没有可用的模型输出）']


def build_topics_prompt(context):
    """构建 B 最终 messages；父记录冻结资料完整进入，不截断。"""
    context = context or {}
    parent = context.get('parent') or {}
    input_data = context.get('parent_input') or {}
    business = _topics_parent_business(input_data)
    strategy = context.get('strategy') or {}
    refs = context.get('refs') or []
    demand_roles = context.get('demand_roles') or {}
    declarations = context.get('source_roles') or []
    parent_result = context.get('parent_result') or {}
    declar = {}
    for item in declarations:
        declar[item.get('source_id')] = item.get('role')
    ref_lines = []
    for ref in refs:
        ident = ref.get('id')
        role = ref.get('role') or ''
        line = '- %s [%s] %s' % (ident, ROLE_LABELS.get(role, role), ref.get('text') or '')
        if ref.get('source'):
            line += '\n  出处：%s' % ref.get('source')
        if ident in declar:
            line += '\n  人工声明需求角色：%s（人工声明，未独立核实；只写入本次 B 快照，不修改 A）' % (
                DEMAND_ROLE_LABELS.get(declar[ident], declar[ident]))
        ref_lines.append(line)
    demand_lines = []
    for ref in refs:
        ident = ref.get('id')
        if ident in demand_roles:
            demand_lines.append('- %s：%s（由服务端认定为本次可用需求依据）' % (
                ident, DEMAND_ROLE_LABELS.get(demand_roles[ident], demand_roles[ident])))
    if not demand_lines:
        demand_lines.append('（没有服务端认定的需求角色来源；demand_basis 只能为空，候选只能是 needs_validation）')
    demand_notes = context.get('demand_notes') or []
    if demand_notes:
        demand_lines.append('未计入需求角色的来源（保守规则；不表示需求不成立，只能作背景或待验证）：')
        for note in demand_notes:
            if isinstance(note, dict):
                demand_lines.append('- %s：%s' % (note.get('source_id') or '',
                                                 note.get('reason') or '证据不足'))
    business_lines = ['- 业务/商品或服务：%s' % (business.get('business') or '未填写'),
                      '- 目标受众：%s' % (business.get('audience') or '未填写'),
                      '- 阶段目标：%s' % (business.get('goal') or '未填写'),
                      '- 真实资源：%s' % (business.get('resources') or '未填写'),
                      '- 每周可用时间/产能：%s' % (business.get('capacity') or '未填写'),
                      '- 当前问题：%s' % (business.get('question') or '未填写')]
    strategy_lines = _strategy_lines(strategy)
    user = ('父记录 A：%s；主题：%s；状态：%s。\n'
            '本次问题：%s\n\n'
            '父记录冻结业务现状（用户当时保存，不得被当前业务覆盖）：\n%s\n\n'
            '父记录冻结策略边界（版本与确认状态以父快照为准，当前策略不得替换）：\n%s\n\n'
            '父记录冻结来源（只能引用下列 s 号；原文与出处如下，不得编造）：\n%s\n\n'
            '父记录 M05-A 的模型输出（按原角色进入：观察/推断/冲突/不能判断都不是新的原始事实）：\n%s\n\n'
            '本次可用需求角色（demand_basis 只能从这里选；外部参考、指标、研究稿正文、复盘建议、'
            '模型推断本身不能作为需求依据）：\n%s\n\n'
            '要求：\n'
            '1. 最多 %d 个研究用途候选；没有足够材料时可以返回 0 个候选并列出具体问题，不要凑数。\n'
            '2. 每个候选的 id 必须是 1–20 位 [A-Za-z0-9_-] 字符串（如 c1、candidate_2）且组内唯一；'
            'basis、demand_basis、conditions、gaps 四项必须输出数组（可为空数组，缺省或错类型会被拒绝）。'
            'basis 只能引用上面的 s 号；demand_basis 必须是 basis 的子集且只能引用上面列出的需求角色来源。\n'
            '3. state 只能是 research_candidate 或 needs_validation。只有父快照策略已确认、demand_basis 非空、'
            '适配理由与限制明确时才可写 research_candidate；否则必须写 needs_validation 并在 gaps 说明缺口。\n'
            '4. 不得把父记录模型摘要包装成原始事实；人工声明标注“人工声明，未独立核实”；不联网、不核实热度。\n'
            '5. 输出结构（JSON）：\n%s'
            ) % (parent.get('artifact_uid') or '', input_data.get('topic') or '',
                 '父记录未分析' if not parent.get('analyzed') else '父记录已分析',
                 input_data.get('question') or '未提供',
                 '\n'.join(business_lines), '\n'.join(strategy_lines),
                 '\n'.join(ref_lines) or '（父记录无可引用来源）',
                 '\n'.join(_topics_parent_result_lines(parent_result)),
                 '\n'.join(demand_lines), MAX_CANDIDATES, _TOPICS_SCHEMA)
    return _TOPICS_SYSTEM, user


def _clip(value, limit):
    text = str(value or '').strip()
    return text[:limit]


def demo_topics(context):
    """中性本地规则演示：不调用模型；缺少前提时输出 needs_validation。"""
    context = context or {}
    parent = context.get('parent') or {}
    input_data = context.get('parent_input') or {}
    refs = context.get('refs') or []
    demand_roles = context.get('demand_roles') or {}
    strategy = context.get('strategy') or {}
    confirmed = bool(strategy.get('confirmed'))
    parent_topic = _clip(input_data.get('topic') or parent.get('topic') or '父记录主题', 120)
    refs_by_id = {ref.get('id'): ref for ref in refs}
    demand_ids = [ref.get('id') for ref in refs if ref.get('id') in demand_roles]
    background_ids = [ref.get('id') for ref in refs if ref.get('id') not in demand_roles]
    candidates = []
    cannot = ['演示模式未调用模型，不能判断真实选题质量，也不能证明需求已验证。',
              '未联网核实平台热度、搜索量、行业信号或外部参考。',
              '人工声明仅代表用户声明，未独立核实。']
    for note in context.get('demand_notes') or []:
        if isinstance(note, dict) and note.get('reason'):
            cannot.append('来源 %s 未计入需求角色：%s（不保证需求成立，只能作背景或待验证）'
                          % (note.get('source_id') or '', note.get('reason')))
    if not parent.get('analyzed'):
        cannot.append('父记录未分析：本建议只基于父记录已有资料，不虚构父研究结论。')
    if not refs:
        cannot.append('父记录没有可引用的冻结来源，不能形成候选；请先补充痛点/咨询或人工摘录。')
    else:
        if demand_ids:
            role = demand_roles.get(demand_ids[0])
            source = refs_by_id.get(demand_ids[0]) or {}
            state = 'research_candidate' if confirmed else 'needs_validation'
            gaps = ['未做真实需求核验；需人工复核来源原文与出处。']
            if not confirmed:
                gaps.insert(0, '父记录策略未确认，只能作为待验证研究问题。')
            candidates.append({
                'id': 'c%d' % (len(candidates) + 1),
                'topic': _clip('围绕「%s」验证%s' % (
                    parent_topic, DEMAND_ROLE_LABELS.get(role, role).replace('依据', '')), MAX_TOPIC),
                'audience_problem': _clip(source.get('text') or '父记录冻结来源中的受众问题', MAX_AUDIENCE_PROBLEM),
                'basis': demand_ids[:MAX_BASIS],
                'demand_basis': demand_ids[:MAX_BASIS],
                'fit_reason': _clip('父快照策略 v%s（%s）；来源 %s 由用户显式选择并冻结；'
                                    '适配理由仅来自父记录，不代表需求已验证。' % (
                                        strategy.get('version') or 0,
                                        '已确认' if confirmed else '未确认',
                                        '、'.join(demand_ids[:MAX_BASIS])), MAX_FIT),
                'why': _clip('父记录中存在可追溯的受众/需求原文，适合先做一条研究用途的选题验证。', MAX_WHY),
                'conditions': ['按父快照策略边界执行', '人工复核来源原文、出处与身份'],
                'gaps': gaps[:MAX_CONDITIONS],
                'next_step': '先人工复核来源原文，再决定是否转为 M02 研究稿输入。',
                'state': state,
            })
        if background_ids:
            background = refs_by_id.get(background_ids[0]) or {}
            candidates.append({
                'id': 'c%d' % (len(candidates) + 1),
                'topic': _clip('「%s」的背景资料能否支持一个研究选题' % parent_topic, MAX_TOPIC),
                'audience_problem': _clip('目前只有背景/参考资料，尚不能确认受众问题：%s'
                                          % (background.get('text') or ''), MAX_AUDIENCE_PROBLEM),
                'basis': background_ids[:MAX_BASIS],
                'demand_basis': [],
                'fit_reason': _clip('背景资料只能作为研究背景，不能证明本业务需求；与父快照策略 v%s 的关系需人工判断。'
                                    % (strategy.get('version') or 0), MAX_FIT),
                'why': _clip('外部参考、指标或研究稿正文不是需求证据，需要先提出待验证问题。', MAX_WHY),
                'conditions': ['需要补齐可追溯的受众/咨询原文'],
                'gaps': ['缺少服务端认定的需求角色依据', '未核实背景资料与父记录边界是否一致'],
                'next_step': '补充受众问题原文或人工摘录，并声明需求角色后重试。',
                'state': 'needs_validation',
            })
        if parent.get('analyzed'):
            unresolved = (context.get('parent_result') or {}).get('cannot_judge') or []
            if unresolved:
                candidates.append({
                    'id': 'c%d' % (len(candidates) + 1),
                    'topic': _clip('父研究未判断问题：「%s」' % unresolved[0], MAX_TOPIC),
                    'audience_problem': _clip('父记录未能判断：%s' % unresolved[0], MAX_AUDIENCE_PROBLEM),
                    'basis': (demand_ids or background_ids)[:MAX_BASIS],
                    'demand_basis': [],
                    'fit_reason': _clip('这是父记录明确的不能判断项，只能作为待验证研究问题。', MAX_FIT),
                    'why': _clip('父记录自己标注为不能判断，不能包装成需求或结论。', MAX_WHY),
                    'conditions': ['需要新的、可追溯的原始资料'],
                    'gaps': ['父记录不能判断的问题尚未解决'],
                    'next_step': '补齐原始资料后单独研究，不要直接进入正式选题。',
                    'state': 'needs_validation',
                })
    summary = _clip('演示选题：本地规则示例（未调用模型），基于父记录 A %s（%s）。'
                    '不证明真实选题质量，也不代表需求已验证；人工声明未独立核实。' % (
                        parent.get('artifact_uid') or '',
                        '已分析' if parent.get('analyzed') else '未分析'), MAX_TOPICS_SUMMARY)
    return {'summary': summary, 'candidates': candidates[:MAX_CANDIDATES],
            'cannot_judge': cannot[:MAX_CANNOT]}


# ---------------------------------------------------------------------------
# M05-C 参考适配（kind=adaptation）：明确主题/候选 + 一条明确外部参考 → 适配计划。
# 输出是计划（开头/结构/证明/节奏/承接的替换方式），不是正文、需求验证或效果承诺。
# ---------------------------------------------------------------------------

ADAPTATION_ASPECTS = ('hook', 'structure', 'proof', 'pacing', 'cta')
ADAPTATION_ASPECT_LABELS = {
    'hook': '开头',
    'structure': '结构',
    'proof': '证明方式',
    'pacing': '节奏',
    'cta': '承接',
}
MAX_ADAPT_SUMMARY = 2000
MAX_PATTERNS = 12
MAX_NON_TRANSFERABLE = 12
MAX_BUSINESS_BASIS = 12
MAX_INSTRUCTION = 1000
MAX_REFERENCE_EXCERPT = 200
MAX_ADAPT_SELECTED = 12
MAX_ITEM_CANNOT = 12
ADAPT_MAX_CONTEXT = 24000

_ADAPT_SYSTEM = (
    '你是本地单用户内容参考适配助手。只基于本次提供的资料生成“参考适配计划”，不是完整原创正文、'
    '不是需求验证、不是经营效果或发布建议。把本次指定外部参考与本业务资料分开：外部参考中的案例、'
    '数字、销量、身份、资质、承诺与热度只能标注为“参考中声称”，不是我方事实，也不是本业务需求。'
    '每条计划必须说明能借什么、为什么可借鉴及边界、适用条件、本业务已提供什么、缺什么、如何用本业务'
    '内容替换；不能照搬的案例/数字/身份/承诺单列。只能引用本次给出的 s1…sN 资料号；不得编造资料号、'
    '出处、身份、数据或结论。business_basis 只能引用本业务输入/原始资料（不能是外部参考或模型摘要）。'
    '证明方式（proof）必须给出缺口或验证下一步，不能把参考案例替代本业务证明。输出必须是 JSON。'
)

_ADAPT_SCHEMA = '''{
  "summary": "本次适配计划摘要（不超过2000字符）",
  "patterns": [{
    "id": "p1",
    "aspect": "hook | structure | proof | pacing | cta",
    "text": "如何用本业务内容替换参考的哪一部分（1-1500字符）",
    "why": "为什么可借鉴、边界是什么（1-1000字符）",
    "basis": ["s1"],
    "business_basis": [],
    "conditions": ["适用条件"],
    "gaps": ["缺口"],
    "next_step": "下一步",
    "reference_excerpt": "仅必要短摘录（不超过200字符）"
  }],
  "non_transferable": [{
    "id": "n1",
    "text": "不能照搬的案例/数字/身份/承诺及原因（1-1500字符）",
    "why": "为什么不能照搬（1-1000字符）",
    "basis": ["s1"],
    "conditions": ["适用条件"],
    "gaps": ["缺口"],
    "next_step": "下一步"
  }],
  "cannot_judge": ["仍不能判断的问题（每项不超过500字符）"]
}'''


def _adapt_positive_id(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('%s必须是 JSON 正整数' % name)
    return value


def _adapt_uid(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{12}', value):
        raise ValueError('%s必须是有效的 12 位记录 UID' % name)
    return value


def _adapt_business(value):
    """R2：缺省可以空串；存在但 null 必须按声明类型拒绝，不做 None→空值静默消错。"""
    if not isinstance(value, dict):
        raise ValueError('业务现状必须是对象')
    result = {}
    for key in _FIELDS:
        raw = value.get(key, '')
        if not isinstance(raw, str):
            raise ValueError('业务字段 %s 必须是文本' % key)
        raw = raw.strip()
        if len(raw) > MAX_FIELD:
            raise ValueError('业务字段 %s 超过 %d 字符上限' % (key, MAX_FIELD))
        result[key] = raw
    return result


def _adapt_selected(value):
    if not isinstance(value, dict):
        raise ValueError('selected 必须是对象')
    allowed = {'pain_ids', 'manual_excerpts', 'draft_uid', 'draft_version'}
    extra = set(value) - allowed
    if extra:
        raise ValueError('selected 含不支持的字段：%s（C 只支持痛点、人工摘录和成对稿件版本）'
                         % '、'.join(sorted(extra)))
    pain_ids = value.get('pain_ids', [])
    if not isinstance(pain_ids, list):
        raise ValueError('pain_ids 必须是数组')
    ids, seen = [], set()
    for item in pain_ids:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError('pain_ids 只能包含 JSON 正整数 ID')
        if item in seen:
            continue
        seen.add(item)
        ids.append(item)
    excerpts = value.get('manual_excerpts', [])
    if not isinstance(excerpts, list):
        raise ValueError('人工摘录必须是数组')
    rows, seen_excerpt = [], set()
    for item in excerpts:
        if not isinstance(item, dict):
            raise ValueError('人工摘录每行必须是对象')
        text = _text(item.get('text'), '人工摘录正文', MAX_MANUAL)
        source = _text(item.get('source'), '人工摘录出处', 300)
        key = (text, source)
        if key in seen_excerpt:
            continue
        seen_excerpt.add(key)
        rows.append({'text': text, 'source': source})
    has_uid = 'draft_uid' in value
    has_version = 'draft_version' in value
    draft_uid = ''
    draft_version = 0
    if has_uid or has_version:
        if not (has_uid and has_version):
            raise ValueError('稿件 UID 与版本必须成对提供')
        draft_uid = _adapt_uid(value.get('draft_uid'), '研究稿 UID')
        draft_version = value.get('draft_version')
        if (isinstance(draft_version, bool) or not isinstance(draft_version, int)
                or draft_version <= 0):
            raise ValueError('研究稿版本必须是 JSON 正整数')
    selected = {'pain_ids': ids, 'manual_excerpts': rows,
                'draft_uid': draft_uid, 'draft_version': draft_version}
    total = 1 + len(ids) + (1 if draft_uid else 0) + len(rows)
    if total > MAX_ADAPT_SELECTED:
        raise ValueError('显式选择最多 %d 条（含指定参考）' % MAX_ADAPT_SELECTED)
    return selected


def validate_adaptation_input(body, require_mode=True):
    """校验 C 输入结构；mode/confirm 只在生成接口必填。"""
    if not isinstance(body, dict):
        raise ValueError('请求格式无效')
    allowed = {'subject', 'reference_id', 'selected', 'instruction'}
    if require_mode:
        allowed |= {'model_mode', 'confirm'}
    else:
        allowed.add('kind')
    extra = set(body) - allowed
    if extra:
        raise ValueError('适配请求含未识别字段：%s' % '、'.join(sorted(extra)))
    subject = body.get('subject')
    if not isinstance(subject, dict):
        raise ValueError('subject 必须是对象')
    kind = subject.get('kind')
    if kind == 'manual':
        extra = set(subject) - {'kind', 'topic', 'business'}
        if extra:
            raise ValueError('manual subject 只接受 kind/topic/business，不能覆盖：%s'
                             % '、'.join(sorted(extra)))
        topic = _topics_text(subject.get('topic'), '适配主题', MAX_TOPIC)
        if 'business' not in subject:
            raise ValueError('manual subject 必须提供 business 对象')
        clean_subject = {'kind': 'manual', 'topic': topic,
                         'business': _adapt_business(subject.get('business'))}
    elif kind == 'candidate':
        extra = set(subject) - {'kind', 'artifact_uid', 'candidate_id'}
        if extra:
            raise ValueError('candidate subject 只接受 kind/artifact_uid/candidate_id：%s'
                             % '、'.join(sorted(extra)))
        clean_subject = {'kind': 'candidate',
                         'artifact_uid': _adapt_uid(subject.get('artifact_uid'),
                                                    'B 选题记录 UID'),
                         'candidate_id': _candidate_id(subject.get('candidate_id'),
                                                       'B 候选 ID')}
    else:
        raise ValueError('subject.kind 只能是 manual 或 candidate')
    if 'reference_id' not in body:
        raise ValueError('必须明确选择一条外部参考 reference_id')
    reference_id = _adapt_positive_id(body.get('reference_id'), '参考 ID')
    selected = _adapt_selected(body.get('selected', {}) if 'selected' in body else {})
    instruction = body.get('instruction', '') if 'instruction' in body else ''
    if not isinstance(instruction, str):
        raise ValueError('instruction 必须是文本')
    instruction = instruction.strip()
    if len(instruction) > MAX_INSTRUCTION:
        raise ValueError('instruction 超过 %d 字符上限' % MAX_INSTRUCTION)
    result = {'subject': clean_subject, 'reference_id': reference_id,
              'selected': selected, 'instruction': instruction}
    if require_mode:
        mode = body.get('model_mode')
        if mode not in ('test', 'real'):
            raise ValueError('模型模式无效')
        confirm = body.get('confirm')
        if not isinstance(confirm, bool):
            raise ValueError('confirm 必须是布尔值（true/false）')
        result['model_mode'] = mode
        result['confirm'] = confirm
    return result


def _adapt_role_line(role):
    return ROLE_LABELS.get(role, role or '来源')


def build_adaptation_prompt(context):
    """构建 C 最终 messages：指定参考、业务六字段、冻结策略、全部 s 号原样进入。"""
    context = context or {}
    subject = context.get('subject') or {}
    business = subject.get('business') or {}
    strategy = context.get('strategy') or {}
    refs = context.get('refs') or []
    reference = context.get('reference') or {}
    candidate = context.get('candidate') or {}
    business_ids = context.get('business_source_ids') or []
    ref_lines = []
    for ref in refs:
        line = '- %s [%s] %s' % (ref.get('id'), _adapt_role_line(ref.get('role')),
                                 ref.get('text') or '')
        if ref.get('source'):
            line += '\n  出处：%s' % ref.get('source')
        if ref.get('id') == 's1':
            line += '\n  角色：本次指定外部参考（只作结构参考，不是本业务事实）'
        ref_lines.append(line)
    if not ref_lines:
        ref_lines.append('（没有可引用来源）')
    business_lines = ['- 业务/商品或服务：%s' % (business.get('business') or '未填写'),
                      '- 目标受众：%s' % (business.get('audience') or '未填写'),
                      '- 阶段目标：%s' % (business.get('goal') or '未填写'),
                      '- 真实资源：%s' % (business.get('resources') or '未填写'),
                      '- 每周可用时间/产能：%s' % (business.get('capacity') or '未填写'),
                      '- 当前问题：%s' % (business.get('question') or '未填写')]
    strategy_lines = _strategy_lines(strategy)
    subject_line = ('目标主题（%s）：%s' % (
        '手工主题' if subject.get('kind') == 'manual' else 'B 候选主题',
        subject.get('topic') or context.get('topic') or ''))
    candidate_lines = []
    if subject.get('kind') == 'candidate':
        candidate_lines = ['B 候选：%s；研究状态：%s；父 A 记录：%s' % (
            candidate.get('id') or '', candidate.get('state') or '',
            (context.get('parent') or {}).get('parent_uid') or '')]
        for label, key in (('候选受众问题', 'audience_problem'),
                           ('候选适配理由', 'fit_reason'),
                           ('候选为什么', 'why')):
            if candidate.get(key):
                candidate_lines.append('%s：%s' % (label, candidate[key]))
        for label, key in (('候选条件', 'conditions'), ('候选缺口', 'gaps')):
            if candidate.get(key):
                candidate_lines.append('%s：%s' % (label, '；'.join(candidate[key])))
        if candidate.get('next_step'):
            candidate_lines.append('候选下一步：%s' % candidate['next_step'])
    reference_lines = ['指定外部参考（%s）：%s' % (
        'B 候选冻结链路来源，按 B 快照为准' if reference.get('snapshot_source') == 'b_frozen'
        else '本次明确选择，按原记录快照', reference.get('title') or '')]
    if reference.get('source'):
        reference_lines.append('参考出处：%s' % reference['source'])
    if reference.get('scope'):
        reference_lines.append('观察范围：%s' % reference['scope'])
    reference_lines.append('原记录时间：%s' % (reference.get('created_at') or '未提供'))
    if reference.get('excerpt'):
        reference_lines.append('参考短摘录：%s' % reference['excerpt'])
    if reference.get('note'):
        reference_lines.append('快照说明：%s' % reference['note'])
    business_ids_text = '、'.join(business_ids) or '（本业务没有可引用的原始资料）'
    user = (
        '%s\n\n'
        '本次说明/限制：%s\n\n'
        '本业务六字段（用户提供，未独立核实）：\n%s\n\n'
        '冻结策略边界（版本、确认状态与完整排除项以下为准，不得被当前策略替换）：\n%s\n\n'
        '%s\n\n'
        '本次可引用资料（只能引用下列 s 号；s1 是本次指定外部参考）：\n%s\n\n'
        '本业务原始资料号（business_basis 只能从这里选，且必须是 basis 的子集；外部参考和模型摘要不能放入）：%s\n\n'
        '要求：\n'
        '1. 生成适配计划，不写完整原创正文；每项写“如何用本业务内容替换”，不冒名改写参考。\n'
        '2. patterns 最多 %d 项，aspect 只能用 hook/structure/proof/pacing/cta（开头/结构/证明/节奏/承接）；'
        '每项必须有 id、aspect、text、why、basis、business_basis、conditions、gaps、next_step；'
        'basis 必须包含 s1，conditions/gaps 必须是数组（可为空数组）。\n'
        '3. 证明方式（proof）必须给出缺口或验证下一步；business_basis 非空只表示用户提供了对应资料，'
        '不表示效果已验证；为空时明确本业务证明未提供。\n'
        '4. non_transferable 单列不能照搬的他人案例、数字、身份、资质、承诺及原因，basis 必须包含 s1。'
        '参考中的销量/播放/案例只能写“参考中声称”，不能变成我方事实。\n'
        '5. cannot_judge 列出仍不能判断的问题；资料不足时给条件化计划与缺口，不要编造数据。\n'
        '6. reference_excerpt 只放必要短摘录（≤200 字符），不得把参考全文伪装成新正文。\n'
        '输出结构（JSON）：\n%s'
    ) % (subject_line, context.get('instruction') or '未提供',
         '\n'.join(business_lines), '\n'.join(strategy_lines),
         '\n'.join(candidate_lines + reference_lines),
         '\n'.join(ref_lines), business_ids_text,
         MAX_PATTERNS, _ADAPT_SCHEMA)
    return _ADAPT_SYSTEM, user


def _adapt_str_list(value, name, limit, cap):
    if value is None:
        raise ValueError('%s 不能为 null' % name)
    if not isinstance(value, list):
        raise ValueError('%s 必须是数组' % name)
    if len(value) > limit:
        raise ValueError('%s 最多 %d 条' % (name, limit))
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('%s 每项必须是文本' % name)
        item = item.strip()
        if not item:
            raise ValueError('%s 每项不能为空' % name)
        if len(item) > cap:
            raise ValueError('%s 每项超过 %d 字符上限' % (name, cap))
        result.append(item)
    return result


def _adapt_text(value, name, limit, required=True):
    if not isinstance(value, str):
        raise ValueError('%s 必须是文本' % name)
    text = value.strip()
    if required and not text:
        raise ValueError('%s 不能为空' % name)
    if len(text) > limit:
        raise ValueError('%s 超过 %d 字符上限' % (name, limit))
    return text


def _adapt_basis(value, name, ref_ids, reference_sid):
    if value is None:
        raise ValueError('%s 不能为 null' % name)
    if not isinstance(value, list):
        raise ValueError('%s 必须是数组' % name)
    if not value:
        raise ValueError('%s 不能为空' % name)
    if len(value) > MAX_BASIS:
        raise ValueError('%s 最多 %d 个' % (name, MAX_BASIS))
    clean, seen = [], set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError('%s 每项必须是非空资料号字符串' % name)
        item = item.strip()
        if item not in ref_ids:
            raise ValueError('%s 引用了未知资料号 %s' % (name, item))
        if item in seen:
            raise ValueError('%s 依据重复 %s' % (name, item))
        seen.add(item)
        clean.append(item)
    if reference_sid not in clean:
        raise ValueError('%s 必须包含本次指定外部参考 %s' % (name, reference_sid))
    return clean


def _adapt_row_id(value, name):
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError('%s 必须是 1–20 位 [A-Za-z0-9_-] 字符串（不 trim 后接受）' % name)
    return value


def _adapt_pattern(item, index, ref_ids, business_ids, reference_sid):
    if not isinstance(item, dict):
        raise ValueError('patterns 第 %d 项必须是对象' % index)
    allowed = {'id', 'aspect', 'text', 'why', 'basis', 'business_basis',
               'conditions', 'gaps', 'next_step', 'reference_excerpt'}
    extra = set(item) - allowed
    if extra:
        raise ValueError('patterns 第 %d 项含未识别字段：%s'
                         % (index, '、'.join(sorted(extra))))
    pattern_id = _adapt_row_id(item.get('id'), 'patterns 第 %d 项 id' % index)
    aspect = item.get('aspect')
    if not isinstance(aspect, str) or aspect not in ADAPTATION_ASPECTS:
        raise ValueError('patterns 第 %d 项 aspect 只能是 %s'
                         % (index, '/'.join(ADAPTATION_ASPECTS)))
    text = _adapt_text(item.get('text'), 'patterns 第 %d 项 text' % index, MAX_TEXT)
    why = _adapt_text(item.get('why'), 'patterns 第 %d 项 why' % index, 1000)
    basis = _adapt_basis(item.get('basis'), 'patterns 第 %d 项 basis' % index,
                         ref_ids, reference_sid)
    if 'business_basis' not in item:
        raise ValueError('patterns 第 %d 项缺少 business_basis（可为空数组，但不能缺省）' % index)
    raw_business = item['business_basis']
    if not isinstance(raw_business, list):
        raise ValueError('patterns 第 %d 项 business_basis 必须是数组' % index)
    if len(raw_business) > MAX_BUSINESS_BASIS:
        raise ValueError('patterns 第 %d 项 business_basis 最多 %d 个'
                         % (index, MAX_BUSINESS_BASIS))
    business_basis, seen = [], set()
    for ident in raw_business:
        if not isinstance(ident, str) or not ident.strip():
            raise ValueError('patterns 第 %d 项 business_basis 每项必须是非空资料号' % index)
        ident = ident.strip()
        if ident not in basis:
            raise ValueError('patterns 第 %d 项 business_basis 必须是 basis 的子集' % index)
        if ident not in business_ids:
            raise ValueError('patterns 第 %d 项 business_basis 不能指向外部参考/模型摘要 %s'
                             % (index, ident))
        if ident in seen:
            raise ValueError('patterns 第 %d 项 business_basis 重复 %s' % (index, ident))
        seen.add(ident)
        business_basis.append(ident)
    conditions = _adapt_str_list(item.get('conditions'),
                                 'patterns 第 %d 项 conditions' % index,
                                 MAX_CONDITIONS, MAX_CONDITION_TEXT)
    gaps = _adapt_str_list(item.get('gaps'), 'patterns 第 %d 项 gaps' % index,
                           MAX_CONDITIONS, MAX_CONDITION_TEXT)
    next_step = item.get('next_step')
    if not isinstance(next_step, str):
        raise ValueError('patterns 第 %d 项 next_step 必须是文本（可为空串）' % index)
    next_step = next_step.strip()
    if len(next_step) > MAX_NEXT:
        raise ValueError('patterns 第 %d 项 next_step 超过 %d 字符' % (index, MAX_NEXT))
    if aspect == 'proof' and not (gaps or next_step):
        raise ValueError('patterns 第 %d 项是 proof，必须给出缺口或验证下一步' % index)
    excerpt = item.get('reference_excerpt', '')
    if not isinstance(excerpt, str):
        raise ValueError('patterns 第 %d 项 reference_excerpt 必须是文本' % index)
    excerpt = excerpt.strip()
    if len(excerpt) > MAX_REFERENCE_EXCERPT:
        raise ValueError('patterns 第 %d 项 reference_excerpt 超过 %d 字符'
                         % (index, MAX_REFERENCE_EXCERPT))
    return {'id': pattern_id, 'aspect': aspect, 'text': text, 'why': why,
            'basis': basis, 'business_basis': business_basis,
            'conditions': conditions, 'gaps': gaps,
            'next_step': next_step, 'reference_excerpt': excerpt}


def _adapt_non_row(item, index, ref_ids, reference_sid):
    if not isinstance(item, dict):
        raise ValueError('non_transferable 第 %d 项必须是对象' % index)
    allowed = {'id', 'text', 'why', 'basis', 'conditions', 'gaps', 'next_step'}
    extra = set(item) - allowed
    if extra:
        raise ValueError('non_transferable 第 %d 项含未识别字段：%s'
                         % (index, '、'.join(sorted(extra))))
    row_id = _adapt_row_id(item.get('id'), 'non_transferable 第 %d 项 id' % index)
    text = _adapt_text(item.get('text'), 'non_transferable 第 %d 项 text' % index, MAX_TEXT)
    why = _adapt_text(item.get('why'), 'non_transferable 第 %d 项 why' % index, 1000)
    basis = _adapt_basis(item.get('basis'), 'non_transferable 第 %d 项 basis' % index,
                         ref_ids, reference_sid)
    conditions = _adapt_str_list(item.get('conditions'),
                                 'non_transferable 第 %d 项 conditions' % index,
                                 MAX_CONDITIONS, MAX_CONDITION_TEXT)
    gaps = _adapt_str_list(item.get('gaps'), 'non_transferable 第 %d 项 gaps' % index,
                           MAX_CONDITIONS, MAX_CONDITION_TEXT)
    next_step = item.get('next_step')
    if not isinstance(next_step, str):
        raise ValueError('non_transferable 第 %d 项 next_step 必须是文本' % index)
    next_step = next_step.strip()
    if len(next_step) > MAX_NEXT:
        raise ValueError('non_transferable 第 %d 项 next_step 超过 %d 字符'
                         % (index, MAX_NEXT))
    return {'id': row_id, 'text': text, 'why': why, 'basis': basis,
            'conditions': conditions, 'gaps': gaps, 'next_step': next_step}


def parse_adaptation(text, ref_ids, business_ids, reference_sid='s1'):
    """严格解析 C 输出；不截断、不强转、不静默删行。"""
    ref_ids = set(ref_ids or [])
    business_ids = set(business_ids or [])
    if reference_sid not in ref_ids:
        raise ValueError('适配输出缺少本次指定外部参考号')
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError('适配输出不是合法 JSON')
    if not isinstance(data, dict):
        raise ValueError('适配输出必须是对象')
    allowed = {'summary', 'patterns', 'non_transferable', 'cannot_judge'}
    extra = set(data) - allowed
    if extra:
        raise ValueError('适配输出含未识别字段：%s（不能接收完整正文冒充计划）'
                         % '、'.join(sorted(extra)))
    for key in ('summary', 'patterns', 'non_transferable', 'cannot_judge'):
        if key not in data:
            raise ValueError('适配输出缺少 %s（数组可为空，但不能缺省）' % key)
    summary = _adapt_text(data.get('summary'), '摘要', MAX_ADAPT_SUMMARY)
    rows = data['patterns']
    if rows is None:
        raise ValueError('patterns 不能为 null')
    if not isinstance(rows, list):
        raise ValueError('patterns 必须是数组')
    if len(rows) > MAX_PATTERNS:
        raise ValueError('patterns 最多 %d 条' % MAX_PATTERNS)
    patterns, seen_ids = [], set()
    for index, item in enumerate(rows, 1):
        pattern = _adapt_pattern(item, index, ref_ids, business_ids, reference_sid)
        if pattern['id'] in seen_ids:
            raise ValueError('patterns 的 ID 重复：%s' % pattern['id'])
        seen_ids.add(pattern['id'])
        patterns.append(pattern)
    rows = data['non_transferable']
    if rows is None:
        raise ValueError('non_transferable 不能为 null')
    if not isinstance(rows, list):
        raise ValueError('non_transferable 必须是数组')
    if len(rows) > MAX_NON_TRANSFERABLE:
        raise ValueError('non_transferable 最多 %d 条' % MAX_NON_TRANSFERABLE)
    non_rows, non_ids = [], set()
    for index, item in enumerate(rows, 1):
        row = _adapt_non_row(item, index, ref_ids, reference_sid)
        if row['id'] in non_ids:
            raise ValueError('non_transferable 的 ID 重复：%s' % row['id'])
        non_ids.add(row['id'])
        non_rows.append(row)
    cannot = data['cannot_judge']
    if cannot is None:
        raise ValueError('cannot_judge 不能为 null')
    if not isinstance(cannot, list):
        raise ValueError('cannot_judge 必须是数组')
    if len(cannot) > MAX_ITEM_CANNOT:
        raise ValueError('cannot_judge 最多 %d 条' % MAX_ITEM_CANNOT)
    clean_cannot = []
    for item in cannot:
        if not isinstance(item, str):
            raise ValueError('cannot_judge 每项必须是文本')
        item = item.strip()
        if not item:
            raise ValueError('cannot_judge 每项不能为空')
        if len(item) > MAX_CONDITION_TEXT:
            raise ValueError('cannot_judge 每项超过 %d 字符' % MAX_CONDITION_TEXT)
        clean_cannot.append(item)
    return {'summary': summary, 'patterns': patterns,
            'non_transferable': non_rows, 'cannot_judge': clean_cannot}


def demo_adaptation(context):
    """中性本地流程示例：不调用模型；不固定行业/平台；不捏造数字/资质；给条件与缺口。"""
    context = context or {}
    business_ids = context.get('business_source_ids') or []
    subject = context.get('subject') or {}
    reference = context.get('reference') or {}
    strategy = context.get('strategy') or {}
    ref_sid = 's1'
    business_sid = business_ids[0] if business_ids else ''
    business_basis = [business_sid] if business_sid else []
    basis = [ref_sid] + ([business_sid] if business_sid else [])
    plan_texts = {
        'hook': '开头：参考的提问/场景开场可以借结构，但必须换成目标主题「%s」的真实问题，'
                '不使用参考中的人物、数字或身份。' % (subject.get('topic') or context.get('topic') or ''),
        'structure': '结构：按“问题—可确认信息—缺口—下一步”重排；只借段落功能，不复制参考的原句与顺序细节。',
        'proof': '证明方式：只能使用本业务已提供资料；参考中的销量/案例是“参考中声称”，'
                 '不能作为本业务的替代证明。',
        'pacing': '节奏：借参考的信息密度与停顿位置；本业务缺少的素材不要用虚构案例填充。',
        'cta': '承接：把参考的收束方式换成与本业务资料一致的下一步（补充真实资料或人工复核），'
               '不做无法兑现的承诺。',
    }
    patterns = []
    for index, aspect in enumerate(ADAPTATION_ASPECTS, 1):
        gap = ['演示模式未调用模型，未做真实参考/本业务匹配判断']
        if aspect == 'proof':
            gap = ['本业务证明未提供' if not business_basis else '未核实本业务资料能否支撑该证明',
                   '参考案例不能替代本业务证明']
        patterns.append({
            'id': 'p%d' % index,
            'aspect': aspect,
            'text': _clip(plan_texts[aspect], MAX_TEXT),
            'why': _clip('只借鉴可迁移的结构与表达方式，边界是不使用他人的案例、数字与身份。', 1000),
            'basis': basis,
            'business_basis': business_basis,
            'conditions': ['目标主题与本业务资料一致', '人工复核参考原文与出处'],
            'gaps': gap[:MAX_CONDITIONS],
            'next_step': '补齐本业务真实资料后，再决定是否采用该适配计划',
            'reference_excerpt': _clip(reference.get('excerpt') or '', MAX_REFERENCE_EXCERPT),
        })
    non_rows = [{
        'id': 'n1',
        'text': _clip('参考中声称的销量、案例、身份、资质与承诺属于他人信息，不能照搬为我方事实。',
                      MAX_TEXT),
        'why': _clip('这些内容没有本业务证据支持，照搬会构成虚假或无法兑现的表述。', 1000),
        'basis': [ref_sid],
        'conditions': ['仅作结构参考'],
        'gaps': ['本业务没有对应可核验数据'],
        'next_step': '用本业务真实资料或明确标注“未提供”',
    }]
    cannot = ['演示模式未调用模型，不能判断参考与本业务是否真正匹配。',
              '未联网核实参考的来源、时间与热度；参考中的数字仅属“参考中声称”。']
    if not business_ids:
        cannot.append('本业务没有提供可引用的原始资料：证明方式只能给缺口与验证下一步。')
    if not strategy.get('confirmed'):
        cannot.append('当前策略未确认或缺失：适配计划只能作为研究草案。')
    return {
        'summary': _clip('演示适配：仅验证输入、来源角色、计划结构与保存流程，未调用模型；'
                         '不证明真实适配质量、需求或经营效果。', MAX_ADAPT_SUMMARY),
        'patterns': patterns, 'non_transferable': non_rows,
        'cannot_judge': cannot[:MAX_ITEM_CANNOT],
    }
