"""研究稿：指定主题的一条稿件生成、优化、版本保存与 Markdown 导出（M02）。

- 纯函数：build_draft_prompt / build_optimize_prompt / parse_draft / demo_draft / to_markdown。
- 不是正式稿件批准：不写 topic_candidates、不建组合、不进 2+1 审批、不发布。
- 输出按不可信数据处理：严格类型、引用只允许本次上下文、缺正文拒绝。
"""
import json
import re

from workflows.ops_advice import STATUS_FIELDS, validate_status  # noqa: F401  (re-export)

TOPIC_MAX = 200
_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')

_SYSTEM = ('你是本地单用户运营助手。只基于给定资料写研究稿；把事实、同品类线索、演示与推断分开；'
           '不编造商品成分、价格、效果或账号数据；不替用户确认策略、批准稿件或发布。'
           '输出必须是 JSON，不要额外说明。')

_SCHEMA = '''{
 "title": "研究稿标题",
 "summary": "一句话摘要",
 "facts": [{"id": "f1", "text": "可引用的事实", "basis": ["pain:1"], "source": "资料|用户"}],
 "outline": ["一、…", "二、…"],
 "draft_markdown": "## 小节\\n正文（Markdown）",
 "gaps": ["缺少的资料/不能判断的部分"],
 "questions": ["需要用户决定的事项"]
}'''


def validate_topic(topic):
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError('请填写研究稿主题')
    topic = topic.strip()
    if len(topic) > TOPIC_MAX:
        raise ValueError('研究稿主题超过 %d 字符上限，请精简' % TOPIC_MAX)
    return topic


def _source_strategy(context, source):
    for raw in (source.get('strategy'), (context or {}).get('strategy')):
        if isinstance(raw, dict):
            data = raw.get('data')
            return {'version': raw.get('version') if isinstance(raw.get('version'), int)
                    and not isinstance(raw.get('version'), bool) else 0,
                    'confirmed': bool(raw.get('confirmed')),
                    'data': data if isinstance(data, dict) else {}}
    return {'version': 0, 'confirmed': False, 'data': {}}


def _strategy_lines(strategy):
    lines = ['- 冻结策略（父 A 保存时；版本、确认状态与完整排除项以下为准）：v%s · %s' % (
        strategy.get('version') or 0, '已确认' if strategy.get('confirmed') else '未确认')]
    data = strategy.get('data') or {}
    if not data:
        lines.append('  - 未提供策略内容')
    for key, value in data.items():
        if isinstance(value, list):
            value = '；'.join(str(item) for item in value)
        lines.append('  - %s：%s' % (key, value))
    return lines


def _b_source_lines(context, source):
    """R2：B 导入稿的冻结策略与来源全文完整进入提示，不截断。"""
    lines = ['', '研究建议来源（来自 M05-B；模型/演示建议，不是事实，不得作为事实引用）：']
    lines.append('- B 记录：%s；父 A 记录：%s；候选 id：%s；研究状态：%s；来源：%s' % (
        source.get('artifact_uid') or '', source.get('parent_uid') or '',
        source.get('candidate_id') or '', source.get('state') or '',
        source.get('source') or ''))
    lines.extend(_strategy_lines(_source_strategy(context, source)))
    current = (context or {}).get('current_strategy')
    if isinstance(current, dict) and current.get('changed'):
        lines.append('- 当前策略状态（仅供对照，不覆盖上面的冻结边界）：v%s · %s（已变更）' % (
            current.get('version') or 0, '已确认' if current.get('confirmed') else '未确认'))
    candidate = source.get('candidate') or {}
    lines.append('- 候选主题：%s' % (candidate.get('topic') or source.get('topic') or ''))
    lines.append('- 受众问题：%s' % (candidate.get('audience_problem') or ''))
    if candidate.get('fit_reason'):
        lines.append('- 适配理由：%s' % candidate['fit_reason'])
    if candidate.get('why'):
        lines.append('- 为什么：%s' % candidate['why'])
    if candidate.get('conditions'):
        lines.append('- 条件：%s' % '；'.join(str(item) for item in candidate['conditions']))
    if candidate.get('gaps'):
        lines.append('- 缺口：%s' % '；'.join(str(item) for item in candidate['gaps']))
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
            identity = ['kind=%s' % origin.get('kind')]
            for key in ('id', 'uid', 'version', 'index'):
                if origin.get(key) is not None:
                    identity.append('%s=%s' % (key, origin.get(key)))
            lines.append('  真实身份：%s' % '，'.join(identity))
        if row.get('declaration'):
            lines.append('  人工声明：%s（人工声明，未独立核实）' % (
                (row['declaration'] or {}).get('role') or ''))
    return lines


def _c_source_lines(context, source):
    """C 适配计划完整进入 M02 提示：计划、不能照搬、缺口、冻结策略与来源，不截断。"""
    labels = {'hook': '开头', 'structure': '结构', 'proof': '证明方式',
              'pacing': '节奏', 'cta': '承接'}
    lines = ['', '参考适配计划（M05-C；计划是推断，不是事实，也不是完整正文；'
                 '不得照搬参考中的案例/数字/身份/承诺）：']
    lines.append('- C 记录：%s；父 B 记录：%s；候选 id：%s；主题：%s；来源：%s' % (
        source.get('artifact_uid') or '', source.get('parent_uid') or '无',
        source.get('candidate_id') or '无', source.get('topic') or '',
        source.get('source') or ''))
    lines.extend(_strategy_lines(_source_strategy(context, source)))
    subject = source.get('subject') or {}
    business = subject.get('business') or {}
    for key, label in (('business', '业务/商品或服务'), ('audience', '目标受众'),
                       ('goal', '阶段目标'), ('resources', '真实资源'),
                       ('capacity', '每周可用时间/产能'), ('question', '当前问题')):
        lines.append('- %s（用户提供，未独立核实）：%s' % (label, business.get(key) or '未填写'))
    # R3：C 的说明/限制是独立冻结输入，不能依赖模型恰好在计划正文里复述。
    lines.append('- 本次说明/限制（用户输入，未独立核实；本稿必须遵守，不因计划正文未复述而失效）：%s'
                 % (source.get('instruction') or '未填写'))
    lines.append('- 适配摘要：%s' % (source.get('summary') or ''))
    for item in source.get('patterns') or []:
        if not isinstance(item, dict):
            continue
        lines.append('- 计划 %s [%s]：%s' % (
            item.get('id') or '', labels.get(item.get('aspect'), item.get('aspect') or ''),
            item.get('text') or ''))
        lines.append('  为什么/边界：%s' % (item.get('why') or ''))
        lines.append('  依据：%s；本业务依据：%s' % (
            '、'.join(item.get('basis') or []) or '无',
            '、'.join(item.get('business_basis') or []) or '无（本业务证明未提供）'))
        lines.append('  条件：%s；缺口：%s；下一步：%s' % (
            '；'.join(item.get('conditions') or []) or '无',
            '；'.join(item.get('gaps') or []) or '无',
            item.get('next_step') or '未提供'))
        if item.get('reference_excerpt'):
            lines.append('  参考短摘录：%s' % item['reference_excerpt'])
    lines.append('- 不能照搬（他人案例/数字/身份/承诺）：')
    for item in source.get('non_transferable') or []:
        if not isinstance(item, dict):
            continue
        lines.append('  - %s：%s（原因：%s；依据：%s；条件：%s；缺口：%s；下一步：%s）' % (
            item.get('id') or '', item.get('text') or '', item.get('why') or '',
            '、'.join(item.get('basis') or []) or '无',
            '；'.join(item.get('conditions') or []) or '无',
            '；'.join(item.get('gaps') or []) or '无',
            item.get('next_step') or '未提供'))
    lines.append('- 仍不能判断：%s' % ('；'.join(source.get('cannot_judge') or []) or '无'))
    lines.append('- 限制：计划不是正式正文、需求验证、批准或发布；business_basis 非空只表示用户提供了'
                 '对应资料，不表示效果已验证；外部参考内容是“参考中声称”，不是我方事实。')
    return lines


def _ref_lines(context):
    context = context or {}
    source = context.get('research_source')
    kind = source.get('kind') if isinstance(source, dict) else None
    has_source = kind in ('topics', 'adaptation')
    lines = []
    for ref in context.get('refs') or []:
        text = str(ref.get('text') or '')
        lines.append('- %s：%s' % (ref.get('id'), text if has_source else text[:1000]))
    for error in context.get('read_errors') or []:
        lines.append('- [读取失败] %s' % str(error)[:300])
    if not lines:
        lines.append('（未选择本次资料；不得假设库内其他资料可用）')
    if kind == 'topics':
        lines.extend(_b_source_lines(context, source))
    elif kind == 'adaptation':
        lines.extend(_c_source_lines(context, source))
    return '\n'.join(lines)


def _status_lines(status):
    labels = (('business', '业务/商品或服务（用户提供）'), ('audience', '目标受众（用户提供）'),
              ('goal', '阶段目标（用户提供）'), ('resources', '真实资源（用户提供）'),
              ('capacity', '每周可用时间/产能（用户提供）'), ('question', '当前问题（用户提供）'))
    return '\n'.join('- %s：%s' % (label, (status or {}).get(key) or '未填写')
                     for key, label in labels)


def build_draft_prompt(status, topic, context):
    user = (
        '研究稿主题（用户指定）：%s\n\n'
        '业务现状：\n%s\n\n'
        '本次选择的资料（引用只能使用下列 id）：\n%s\n\n'
        '要求：\n'
        '1. 只写一条研究稿，不生成选题组合、不进入审批、不发布。\n'
        '2. 事实与推断分开；没有自有指标时不写效果结论；策略未确认时标研究草案。\n'
        '3. 每条事实带 basis（引用上述 id）；没有有效引用的标待验证。\n'
        '4. draft_markdown 为可导出的 Markdown 正文；gaps/questions 说明缺口与待定。\n'
        '5. 只输出 JSON，结构：\n%s'
    ) % (topic, _status_lines(status), _ref_lines(context), _SCHEMA)
    return _SYSTEM, user


def build_optimize_prompt(content, instruction, context, topic='', status=None, base_version=0):
    base_text = json.dumps(content or {}, ensure_ascii=False)
    if len(base_text) > 24000:
        raise ValueError('基稿超出支持范围（%d 字符），请先精简后再优化' % len(base_text))
    user = (
        '本次优化基于版本：v%s\n\n'
        '研究稿主题（该版本保存时）：%s\n\n'
        '业务现状（该版本保存时）：\n%s\n\n'
        '当前研究稿（JSON，原文，不可截断）：\n%s\n\n'
        '本次优化要求：%s\n\n'
        '本次资料（引用只能使用下列 id）：\n%s\n\n'
        '要求：保留仍成立的事实、依据与结构，按优化要求修改；不编造；事实带 basis；'
        '输出同样结构的 JSON，不要只给片段。结构：\n%s'
    ) % (base_version or '未记录', topic or '未记录', _status_lines(status or {}), base_text,
         str(instruction)[:1000], _ref_lines(context), _SCHEMA)
    return _SYSTEM, user


def _str_list(value, name, limit=20, cap=500):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('%s 必须是字符串数组' % name)
    return [item.strip()[:cap] for item in value if item.strip()][:limit]


def _str_list_checked(data, key):
    if key in data and not isinstance(data[key], list):
        raise ValueError('%s 必须是字符串数组' % key)
    return _str_list(data.get(key), key)


def parse_draft(text, allowed_refs):
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError('模型输出不是合法 JSON')
    if not isinstance(data, dict):
        raise ValueError('模型输出结构无效')
    allowed = set(allowed_refs or [])
    title = data.get('title')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('缺少标题')
    markdown = data.get('draft_markdown')
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError('缺少正文')
    summary = data.get('summary')
    if summary is not None and not isinstance(summary, str):
        raise ValueError('摘要必须是字符串')
    facts = []
    if 'facts' in data and not isinstance(data['facts'], list):
        raise ValueError('facts 必须是数组')
    for index, item in enumerate(data.get('facts') or []):
        if not isinstance(item, dict):
            raise ValueError('事实行必须是对象')
        if not isinstance(item.get('text'), str) or not item.get('text').strip():
            raise ValueError('事实缺少正文')
        if 'basis' in item:
            basis = item['basis']
            if not isinstance(basis, list) or any(not isinstance(ref, str) for ref in basis):
                raise ValueError('事实 basis 必须是字符串数组')
        else:
            basis = []
        row = {'id': str(item.get('id') or ('f%d' % index))[:20],
               'text': item.get('text').strip()[:800],
               'source': item.get('source') if isinstance(item.get('source'), str) else '',
               'basis': [ref for ref in basis if ref in allowed]}
        if not row['basis']:
            row['unverified'] = True
        facts.append(row)
    result = {
        'title': title.strip()[:200],
        'summary': (summary or '').strip()[:500],
        'facts': facts[:20],
        'outline': _str_list_checked(data, 'outline'),
        'draft_markdown': markdown.strip()[:20000],
        'gaps': _str_list_checked(data, 'gaps'),
        'questions': _str_list_checked(data, 'questions'),
    }
    return result


def demo_draft(status, topic, context):
    """显式演示：中性、基于主题与所选资料；source=demo，不冒充模型判断。"""
    refs = (context or {}).get('refs') or []
    ref_ids = [ref.get('id') for ref in refs if str(ref.get('id') or '').startswith(('pain:', 'ref:'))]
    facts = []
    for ref in refs:
        rid = str(ref.get('id') or '')
        if rid.startswith('pain:'):
            facts.append({'id': 'f%d' % (len(facts) + 1), 'text': str(ref.get('text'))[:200],
                          'source': '同品类线索', 'basis': [rid]})
        elif rid.startswith('ref:'):
            facts.append({'id': 'f%d' % (len(facts) + 1), 'text': str(ref.get('text'))[:200],
                          'source': '参考', 'basis': [rid]})
    has_metrics = any(str(ref.get('id') or '').startswith('metric:') for ref in refs)
    has_external = any(str(ref.get('id') or '').startswith('ref:') for ref in refs)
    gaps = ['缺少可用于核验本业务/商品的关键资料，相关结论不作为事实']
    if not has_metrics:
        gaps.append('没有自有发布指标，效果结论未评估')
    if has_external:
        gaps.append('外部参考的播放/评论是他人数据，不代表本业务表现')
    outline = ['一、这篇稿子回答什么', '二、目前能确认的信息', '三、还不能确认的部分', '四、下一步']
    markdown = ('## 一、这篇稿子回答什么\n围绕“%s”做一条研究稿，只使用现有资料。\n\n'
                '## 二、目前能确认的信息\n%s\n\n'
                '## 三、还不能确认的部分\n%s\n\n'
                '## 四、下一步\n先补齐缺失资料，再决定是否进入正式稿件流程。' % (
                    topic, '\n'.join('- ' + item['text'] for item in facts) or '（未选资料）',
                    '\n'.join('- ' + gap for gap in gaps)))
    return {
        'title': '%s（研究稿·演示）' % topic,
        'summary': '演示生成，仅验证流程，不代表真实运营判断。',
        'facts': facts,
        'outline': outline,
        'draft_markdown': markdown,
        'gaps': gaps,
        'questions': ['是否补齐可用于核验的关键资料？', '是否进入正式稿件流程（本稿不批准）？'],
        'source': 'demo',
    }


def to_markdown(draft):
    draft = draft or {}
    lines = ['# %s' % (draft.get('title') or '研究稿'), '']
    if draft.get('summary'):
        lines.extend(['> %s' % draft['summary'], ''])
    lines.append('来源：%s%s' % (draft.get('source') or 'demo',
                              (' · ' + draft['model']) if draft.get('model') else ''))
    lines.append('')
    if draft.get('facts'):
        lines.append('## 事实与依据')
        for item in draft['facts']:
            basis = '（依据 %s%s）' % ('、'.join(item.get('basis') or []) or '无',
                                       '，待验证' if item.get('unverified') else '')
            lines.append('- %s %s' % (item.get('text') or '', basis))
        lines.append('')
    if draft.get('outline'):
        lines.append('## 结构')
        lines.extend('- %s' % item for item in draft['outline'])
        lines.append('')
    lines.extend(['## 正文', '', draft.get('draft_markdown') or '（空）', ''])
    if draft.get('gaps'):
        lines.append('## 缺口')
        lines.extend('- %s' % item for item in draft['gaps'])
        lines.append('')
    if draft.get('questions'):
        lines.append('## 待决定')
        lines.extend('- %s' % item for item in draft['questions'])
    return '\n'.join(lines)

def demo_optimize(content, instruction):
    """演示优化：保留原稿结构，按优化要求加一节；source=demo。"""
    content = dict(content or {})
    markdown = str(content.get('draft_markdown') or '')
    note = '## 本次调整\n按优化要求：%s（演示执行：仅追加说明，未真正改写正文）' % str(instruction or '')
    content['draft_markdown'] = (markdown + '\n\n' + note).strip()[:20000]
    content['summary'] = ('按优化要求调整后的演示稿。%s' % (content.get('summary') or ''))[:500]
    content['source'] = 'demo'
    return content

