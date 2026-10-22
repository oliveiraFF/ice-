"""运营建议：业务现状 → 有依据的研究建议与本周动作（不确认策略、不建正式计划）。

- 纯函数：build_advice_prompt / parse_advice / demo_advice。
- 引用只允许本次上下文提供的 ref；不存在的引用标待验证。
- 模型输出按不可信数据处理：严格结构、ID 安全格式与唯一性、缺正文拒绝。
"""
import json
import re

STATUS_FIELDS = ('business', 'audience', 'goal', 'resources', 'capacity', 'question')
_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')

_SYSTEM = ('你是本地单用户运营助手。只基于给定资料判断；把事实、同品类线索、演示与推断分开；'
           '不编造商品成分、价格、效果或账号数据；不替用户确认策略、批准稿件或发布。'
           '输出必须是 JSON，不要额外说明。')

_SCHEMA = '''{
 "can_judge": ["基于现有资料能判断什么"],
 "cannot_judge": ["暂时不能判断什么"],
 "priorities": [{"id": "p1", "text": "最优先的问题或机会", "basis": ["pain:1"], "confidence": "high|medium|low"}],
 "directions": [{"id": "d1", "text": "建议方向", "why": "理由", "conditions": "适用条件", "basis": ["pain:1"], "status": "待用户决定"}],
 "week_actions": [{"id": "a1", "action": "本周做什么", "why": "为什么", "proof": "所需证明", "capacity": "产能/顺序", "order": 1, "next": "下一动作", "basis": ["pain:1"], "conditions": "适用条件", "gaps": "缺口"}],
 "decisions": ["需要用户决定的事项"],
 "continue_without": ["不依赖这些决定、可以继续做的部分"]
}'''


def validate_status(body):
    if not isinstance(body, dict):
        raise ValueError('业务现状格式无效')
    status = {}
    for key in STATUS_FIELDS:
        value = body.get(key)
        if value is None:
            status[key] = ''
        elif isinstance(value, str):
            value = value.strip()
            if len(value) > 2000:
                raise ValueError('字段 %s 超过 2000 字符上限，请精简' % key)
            status[key] = value
        else:
            raise ValueError('字段 %s 必须是文本' % key)
    return status


def _ref_lines(context):
    lines = []
    for ref in (context or {}).get('refs') or []:
        lines.append('- %s：%s' % (ref.get('id'), str(ref.get('text') or '')[:1000]))
    for error in (context or {}).get('read_errors') or []:
        lines.append('- [读取失败] %s' % str(error)[:300])
    if not lines:
        lines.append('（未选择本次资料；不得假设库内其他资料可用）')
    return '\n'.join(lines)


def build_advice_prompt(status, context, question=None, parent=None):
    status_lines = []
    for key, label in (('business', '业务/商品或服务（用户提供）'), ('audience', '目标受众（用户提供）'),
                       ('goal', '阶段目标（用户提供）'), ('resources', '真实资源（用户提供）'),
                       ('capacity', '每周可用时间/产能（用户提供）'), ('question', '当前问题（用户提供）')):
        status_lines.append('- %s：%s' % (label, status.get(key) or '未填写'))
    parent_block = ''
    if parent:
        parent_block = ('\n追问上下文（有界；含祖先问题/回答、限制与动作进度）：\n%s\n'
                        % str(parent.get('summary') or '')[:4500])
    question_block = '\n用户追问：%s\n' % question if question else ''
    user = (
        '业务现状：\n%s\n\n'
        '本次选择的资料（引用只能使用下列 id；未选择就明确无所选资料）：\n%s\n\n'
        '%s%s'
        '要求：\n'
        '1. 资料不足时，说明能判断/不能判断什么，仍给出可执行的研究建议；不要只返回 blocked。\n'
        '2. 策略未确认时，建议标为研究草案；不写正式组合、不承诺效果。\n'
        '3. 没有自有指标时，不报运营效果或健康评分；不把同品类线索/演示数据写成本商品事实。\n'
        '4. 本周动作按真实产能给条数；不固定 7 条、不凑 2+1。\n'
        '5. 每条核心建议带 id（仅字母数字下划线连字符，≤20）、依据引用 basis、适用条件 conditions、缺口 gaps、下一动作 next。\n'
        '6. 只输出 JSON，结构：\n%s'
    ) % ('\n'.join(status_lines), _ref_lines(context), parent_block, question_block, _SCHEMA)
    return _SYSTEM, user


def _basis(value):
    if value is None:
        raise ValueError('basis 不能为 null')
    if not isinstance(value, list):
        raise ValueError('basis 必须是数组')
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('basis 元素必须是字符串')
        result.append(item.strip())
    return result


def parse_advice(text, allowed_refs):
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError('模型输出不是合法 JSON')
    if not isinstance(data, dict):
        raise ValueError('模型输出结构无效')
    allowed = set(allowed_refs or [])
    result = {'can_judge': [], 'cannot_judge': [], 'priorities': [], 'directions': [],
              'week_actions': [], 'decisions': [], 'continue_without': [], 'unverified': []}
    for key in ('can_judge', 'cannot_judge', 'decisions', 'continue_without'):
        if key in data and not isinstance(data[key], list):
            raise ValueError('%s 必须是数组' % key)
        value = data.get(key) or []
        if any(not isinstance(item, str) for item in value):
            raise ValueError('%s 必须是字符串数组' % key)
        result[key] = [item[:300] for item in value if item.strip()][:10]
    seen = set()

    def row_id(value):
        text_id = str(value or '').strip()
        if not _ID_RE.match(text_id):
            raise ValueError('建议 ID 格式无效')
        if text_id in seen:
            raise ValueError('建议 ID 重复')
        seen.add(text_id)
        return text_id

    for key, prefix, need in (('priorities', 'p', 'text'), ('directions', 'd', 'text'),
                              ('week_actions', 'a', 'action')):
        if key in data and not isinstance(data[key], list):
            raise ValueError('%s 必须是数组' % key)
        value = data.get(key) or []
        items = []
        for index, item in enumerate(value, 1):
            if not isinstance(item, dict):
                raise ValueError('%s 行必须是对象' % key)
            if not str(item.get(need) or '').strip():
                raise ValueError('%s 缺少%s' % (key, '正文' if need == 'text' else '动作'))
            row = {'id': row_id(item.get('id') or ('%s%d' % (prefix, index)))}
            for field in ('text', 'action', 'why', 'proof', 'capacity', 'next', 'conditions', 'gaps', 'status'):
                if field in item:
                    if not isinstance(item.get(field), str):
                        raise ValueError('%s.%s 必须是字符串' % (key, field))
                    row[field] = item.get(field)[:600]
            if key == 'week_actions':
                try:
                    row['order'] = int(item.get('order') or index)
                except (TypeError, ValueError):
                    row['order'] = index
            confidence = item.get('confidence')
            row['confidence'] = confidence[:10] if isinstance(confidence, str) else ''
            basis = _basis(item['basis']) if 'basis' in item else []
            row['basis'] = [ref for ref in basis if ref in allowed]
            if not row['basis']:
                row['unverified'] = True
                result['unverified'].append(row['id'])
            items.append(row)
        result[key] = items[:12]
    if not (result['priorities'] or result['week_actions'] or result['directions']):
        raise ValueError('模型输出缺少可执行建议')
    return result


def demo_advice(status, context):
    """显式演示：中性、基于实际填写的业务与上下文；source=demo，不冒充模型判断。"""
    business = (status.get('business') or '').strip()
    capacity = (status.get('capacity') or '').strip() or '未填写'
    refs = (context or {}).get('refs') or []
    ref_ids = [ref.get('id') for ref in refs if ref.get('id')]
    pains = [ref for ref in refs if str(ref.get('id') or '').startswith('pain:')]
    has_metrics = bool((context or {}).get('has_metrics'))
    confirmed = bool((context or {}).get('strategy_confirmed'))
    if not business:
        return {
            'can_judge': [], 'cannot_judge': ['业务/商品或服务未填写，无法给出具体建议'],
            'priorities': [], 'directions': [], 'week_actions': [],
            'decisions': ['请补充：业务/商品或服务是什么？', '目标受众是谁？', '本周可用时间/产能？'],
            'continue_without': ['先写下业务与目标，再分析'], 'unverified': [], 'source': 'demo',
        }
    short = business[:40]
    can = ['已填写业务：%s' % short]
    if refs:
        can.append('本次已选 %d 条资料' % len(refs))
    cannot = []
    if not has_metrics:
        cannot.append('没有自有发布指标，效果判断未评估')
    if not confirmed:
        cannot.append('策略未确认，只能给研究草案，不能生成正式组合')
    priorities = [{
        'id': 'p1',
        'text': ('先厘清“%s”相关的真实疑问，再决定内容角度' % short) if pains else
                ('先用现有资料把“%s”的信息整理成可核对清单' % short),
        'basis': [pains[0].get('id')] if pains else ref_ids[:1],
        'confidence': 'medium' if pains else 'low',
    }]
    directions = [{
        'id': 'd1',
        'text': '围绕“%s”做一条信息介绍或服务说明：先讲已知，再列出未确认' % short,
        'why': '不依赖未确认的策略或指标，可先做',
        'conditions': '只使用已提供的资料',
        'basis': ref_ids[:1], 'status': '待用户决定',
    }]
    actions = [{
        'id': 'a1',
        'action': '整理“%s”的资料/案例清单，标出来源与缺口' % short,
        'why': '任何业务都可先做，不需要模型', 'proof': '可引用的图片或资料',
        'capacity': capacity, 'order': 1, 'next': '清单完成后决定是否写研究稿',
        'basis': ref_ids[:1], 'conditions': '只用已提供资料', 'gaps': '未提供的证明材料',
    }]
    return {
        'can_judge': can, 'cannot_judge': cannot, 'priorities': priorities,
        'directions': directions, 'week_actions': actions,
        'decisions': ['是否确认当前策略（研究建议不依赖它也可继续）'],
        'continue_without': ['整理已提供的资料与缺口', '写一版研究稿（非正式、未批准）'],
        'unverified': [], 'source': 'demo',
    }
