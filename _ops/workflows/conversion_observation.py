"""M05-F2 确定性转化观察核心（纯函数，FC 独立模块）。

一条发布登记 + 一份明确指定的指标快照 + 用户明确选中的咨询摘录 →
按冻结口径做确定性规则计算，输出新规则复盘载荷与 Markdown。

不读文件/数据库/环境/网络，不偷读时钟（created_at 由调用方传入），零模型。
规则只描述事实、口径与补充观察建议，不推断因果、不写经营效果。
"""
import copy
import json
import math
import re
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

KIND = 'conversion_observation'
RULE_VERSION = 1
LABEL = '转化观察（规则）'
METRIC_LABEL = '每100次播放的咨询事件数'
FORMULA = 'inquiries / plays × 100'
MAX_COUNT = 9007199254740991          # 2^53-1，浏览器整数安全边界
MAX_CONSULTATIONS = 12
MAX_UID = 64
MAX_CONTEXT_CHARS = 24000
MAX_DUE = 253402300799

# 旧报告缺字段时的固定回退：显式、可追溯，不读取当前可变常量。
LEGACY_LABEL = '转化观察（规则）'
LEGACY_METRIC = '每100次播放的咨询事件数'
LEGACY_FORMULA = 'inquiries / plays × 100'
LEGACY_LIMITS = (
    '计算项是每 100 次播放的咨询事件数，不是去重用户转化率、下单率或经营效果。',
    '咨询摘录条数是人工样本，不等于指标中的咨询次数，不能相加或互相替代。',
    '规则结果不推断因果，也不证明内容或账号改善。',
)

_REQUEST_FIELDS = ('record_uid', 'snapshot_id', 'consultation_ids', 'comparable')
_UID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')

LIMITS = [
    '计算项是每 100 次播放的咨询事件数，不是去重用户转化率、下单率或经营效果。',
    '咨询摘录条数是人工样本，不等于指标中的咨询次数，不能相加或互相替代。',
    '规则结果不推断因果，也不证明内容或账号改善。',
]

# R4：独立 Decimal Context，不继承调用线程精度/舍入/陷阱，也不改全局 context。
_DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP)


def _fail(message):
    raise ValueError(message)


def _uid(value, name):
    if not isinstance(value, str) or not _UID_RE.fullmatch(value):
        _fail('%s 无效' % name)
    return value


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail('%s 必须是数字' % name)
    if isinstance(value, int):
        # R1：整数先比较范围，避免把任意大 int 转 float。
        if minimum is not None and value < minimum:
            _fail('%s 超出允许范围' % name)
        if maximum is not None and value > maximum:
            _fail('%s 超出允许范围' % name)
        return value
    if not math.isfinite(value):
        _fail('%s 必须是有限数字' % name)
    if minimum is not None and value < minimum:
        _fail('%s 超出允许范围' % name)
    if maximum is not None and value > maximum:
        _fail('%s 超出允许范围' % name)
    return value


def _text_or_empty(value, name):
    if value is None:
        return ''
    if not isinstance(value, str):
        _fail('%s 必须是字符串' % name)
    return value


def validate_request(payload):
    """只接受 record_uid/snapshot_id/consultation_ids/comparable；客户端不能覆盖指标。"""
    if not isinstance(payload, dict):
        _fail('转化观察请求格式无效')
    unknown = sorted(str(key) for key in payload if key not in _REQUEST_FIELDS)
    if unknown:
        _fail('请求包含不支持的字段：%s' % '、'.join(unknown))
    record_uid = _uid(payload.get('record_uid'), '登记 UID')
    snapshot_id = payload.get('snapshot_id')
    if isinstance(snapshot_id, bool) or not isinstance(snapshot_id, int) or snapshot_id <= 0:
        _fail('必须指定一份指标快照（正整数 id）')
    ids = payload.get('consultation_ids', [])
    if not isinstance(ids, list):
        _fail('咨询选择必须是字符串数组')
    if len(ids) > MAX_CONSULTATIONS:
        _fail('最多选择 %d 条咨询摘录' % MAX_CONSULTATIONS)
    seen = set()
    for item in ids:
        _uid(item, '咨询 UID')
        if item in seen:
            _fail('咨询选择重复：%s' % item)
        seen.add(item)
    comparable = payload.get('comparable', False)
    if not isinstance(comparable, bool):
        _fail('comparable 必须是布尔值')
    return {'record_uid': record_uid, 'snapshot_id': snapshot_id,
            'consultation_ids': list(ids), 'comparable': comparable}


def _check_record(record_uid, record):
    if not isinstance(record, dict):
        _fail('发布登记对象无效')
    if record.get('record_uid') != record_uid:
        _fail('登记不存在或归属不符')
    if record.get('archived'):
        _fail('登记已归档')
    if record.get('simulated'):
        _fail('演练登记不能生成正式报告')


def _check_snapshot(record_uid, snapshot_id, snapshot):
    if not isinstance(snapshot, dict):
        _fail('指标快照对象无效')
    stored_id = snapshot.get('id')
    if isinstance(stored_id, bool) or not isinstance(stored_id, int) or stored_id != snapshot_id:
        _fail('指标快照不存在或归属不符')
    if not isinstance(snapshot.get('record_uid'), str) or snapshot.get('record_uid') != record_uid:
        _fail('指标快照缺少归属或不属于该登记')
    if snapshot.get('archived'):
        _fail('指标快照已归档')
    if snapshot.get('simulated'):
        _fail('演练快照不能生成正式报告')
    if not isinstance(snapshot.get('metrics'), dict):
        _fail('指标快照格式无效')


def _check_consultations(record_uid, selected_ids, consultations):
    if not isinstance(consultations, list):
        _fail('咨询摘录对象无效')
    by_id = {}
    for item in consultations:
        if not isinstance(item, dict):
            _fail('咨询摘录对象无效')
        note_uid = _uid(item.get('note_uid'), '咨询 UID')
        if not isinstance(item.get('record_uid'), str) or item.get('record_uid') != record_uid:
            _fail('咨询摘录缺少归属或不属于该登记')
        if item.get('archived'):
            _fail('咨询摘录已归档')
        if item.get('simulated'):
            _fail('演练咨询摘录不能使用')
        if note_uid in by_id:
            _fail('权威咨询摘录出现重复 UID：%s' % note_uid)
        by_id[note_uid] = item
    missing = [ident for ident in selected_ids if ident not in by_id]
    if missing:
        _fail('所选咨询摘录不可用：%s' % '、'.join(missing))
    extra = [ident for ident in by_id if ident not in set(selected_ids)]
    if extra:
        _fail('加载了未选择的咨询摘录：%s' % '、'.join(extra))
    return [by_id[ident] for ident in selected_ids]


def _count(metrics, key):
    value = metrics.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _fail('%s 必须是非负整数或留空' % key)
    if value < 0:
        _fail('%s 必须是非负整数或留空' % key)
    if value > MAX_COUNT:
        _fail('%s 超出可安全表示的范围（>2^53-1）' % key)
    return value


def _definition(value):
    if value is None:
        return None, 'missing'
    if not isinstance(value, str):
        _fail('口径必须是字符串')
    if not value.strip():
        return None, 'missing'
    return value, 'provided'


def _decimal_result(inquiries, plays):
    try:
        # R4：每次计算使用独立 context，不受调用方 prec/rounding/trap 影响。
        with localcontext(_DECIMAL_CONTEXT):
            value = (Decimal(inquiries) / Decimal(plays) * Decimal(100)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ZeroDivisionError, OverflowError):
        _fail('规则计算失败')
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text or '0'


def compute(payload, record, snapshot, consultations=()):
    """权威归属核验 + 确定性计算；不写库、不读时钟。"""
    request = validate_request(payload)
    _check_record(request['record_uid'], record)
    _check_snapshot(request['record_uid'], request['snapshot_id'], snapshot)
    selected = _check_consultations(request['record_uid'], request['consultation_ids'],
                                    list(consultations))
    metrics = snapshot['metrics']
    plays = _count(metrics, 'plays')
    inquiries = _count(metrics, 'inquiries')
    definition, definition_status = _definition(snapshot.get('definition'))
    comparable = request['comparable']
    gaps = []
    if plays is None:
        gaps.append('播放未知')
    elif plays == 0:
        gaps.append('零分母')
    if inquiries is None:
        gaps.append('咨询未知')
    if not comparable:
        gaps.append('未声明可比')
    if definition_status == 'missing':
        gaps.append('口径缺失')
    value = None
    if comparable and definition_status == 'provided' and plays is not None and plays > 0 \
            and inquiries is not None:
        value = _decimal_result(inquiries, plays)
    return {'request': request,
            'record': {'record_uid': record['record_uid'],
                       'platform': _text_or_empty(record.get('platform'), '平台'),
                       'platform_post_id': _text_or_empty(record.get('platform_post_id'),
                                                          '平台作品标识'),
                       'published_at': _text_or_empty(record.get('published_at'), '发布时间'),
                       'source': _text_or_empty(record.get('source'), '登记来源')},
            'snapshot': {'id': snapshot['id'],
                         'snapshot_key': _text_or_empty(snapshot.get('snapshot_key'), '快照标识'),
                         'record_uid': snapshot['record_uid'],
                         'collected_at': _text_or_empty(snapshot.get('collected_at'), '采集时间'),
                         'source': _text_or_empty(snapshot.get('source'), '快照来源'),
                         'definition': definition,
                         'metrics': copy.deepcopy(metrics)},
            'consultations': [{'note_uid': item.get('note_uid'),
                               'text': _text_or_empty(item.get('text'), '咨询原文'),
                               'source': _text_or_empty(item.get('source'), '咨询来源'),
                               'occurred_at': item.get('occurred_at'),
                               'note_key': item.get('note_key')}
                              for item in selected],
            'plays': plays, 'inquiries': inquiries,
            'definition': definition, 'definition_status': definition_status,
            'comparable': comparable, 'value': value, 'gaps': gaps}


def _observations(computed):
    lines = [
        '登记 %s（平台 %s）指定快照 #%s：采集 %s，来源 %s。' % (
            computed['record']['record_uid'], computed['record']['platform'] or '未提供',
            computed['snapshot']['id'], computed['snapshot']['collected_at'] or '未提供',
            computed['snapshot']['source'] or '未提供'),
        '播放 %s；咨询次数 %s。' % (
            '未知' if computed['plays'] is None else computed['plays'],
            '未知' if computed['inquiries'] is None else computed['inquiries']),
        '口径：%s。' % (computed['definition'] or '未提供'),
        '可比声明：%s。' % ('已声明本快照播放与咨询可按同一统计范围比较'
                        if computed['comparable'] else '未声明可比'),
    ]
    if computed['value'] is not None:
        lines.append('规则结果：每100次播放的咨询事件数 = %s。' % computed['value'])
    else:
        lines.append('未计算：%s。' % '、'.join(computed['gaps']))
    if computed['consultations']:
        lines.append('咨询摘录 %d 条（人工样本，不能替代指标中的咨询次数）。'
                     % len(computed['consultations']))
    return lines


def _suggestions(computed):
    suggestions = []
    if computed['value'] is None:
        suggestions.append({
            'text': '先补齐缺口，再按同一口径重新观察',
            'basis': '本次未计算：%s' % '、'.join(computed['gaps']),
            'conditions': '同一条登记、同一份快照口径、明确声明可比',
            'pending': '缺口补齐前不判断效果',
        })
    else:
        suggestions.append({
            'text': '保持同一统计范围，补充后续同口径快照再观察',
            'basis': '本次规则结果 %s（原计数播放 %s、咨询 %s）' % (
                computed['value'], computed['plays'], computed['inquiries']),
            'conditions': '同一登记、同一口径、后续快照',
            'pending': '单次比值不能说明改善或因果',
        })
    if computed['consultations']:
        suggestions.append({
            'text': '核对咨询摘录是否覆盖同一统计范围，避免用样本数替代咨询次数',
            'basis': '本次选择 %d 条咨询摘录' % len(computed['consultations']),
            'conditions': '人工记录；摘录条数独立于指标',
            'pending': '需按同一口径补录后复核',
        })
    return suggestions


def build_report(payload, record, snapshot, consultations=(), created_at=None):
    """生成 save_review 兼容载荷：data/observations/suggestions/snapshot_ids。"""
    created_at = _number(created_at, '创建时间', 0, MAX_DUE)
    computed = compute(payload, record, snapshot, consultations)
    data = {
        'kind': KIND,
        'rule_version': RULE_VERSION,
        'label': LABEL,
        'created_at': created_at,
        'record': computed['record'],
        'snapshot': computed['snapshot'],
        'metric_snapshots': [{
            'id': computed['snapshot']['id'],
            'snapshot_key': computed['snapshot']['snapshot_key'],
            'collected_at': computed['snapshot']['collected_at'],
            'definition': computed['snapshot']['definition'] or '',
            'source': computed['snapshot']['source'],
            'metrics': copy.deepcopy(computed['snapshot']['metrics']),
        }],
        'consultation_ids': [item['note_uid'] for item in computed['consultations']],
        'consultation_snapshot': copy.deepcopy(computed['consultations']),
        'comparable': computed['comparable'],
        'counts': {'plays': computed['plays'], 'inquiries': computed['inquiries']},
        'result': {
            'metric': METRIC_LABEL,
            'formula': FORMULA,
            'value': computed['value'],
            'gaps': computed['gaps'],
            'definition_status': computed['definition_status'],
            'limits': list(LIMITS),
        },
        'observations': _observations(computed),
        'suggestions': _suggestions(computed),
    }
    size = len(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    if size > MAX_CONTEXT_CHARS:
        _fail('转化观察冻结上下文超过 %d 码点上限（当前 %d），请减少咨询摘录'
              % (MAX_CONTEXT_CHARS, size))
    return {'snapshot_ids': [computed['snapshot']['id']],
            'data': data,
            'observations': data['observations'],
            'suggestions': data['suggestions']}


def is_conversion(data):
    return isinstance(data, dict) and data.get('kind') == 'conversion_observation'


def _escape(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&#39;'))


_MD_ESCAPE_CHARS = ('\\', '`', '*', '_', '{', '}', '[', ']', '(', ')', '#', '+', '-',
                    '.', '!', '|', '>', '~', '=')


def _md(value):
    """不信任字段按纯文本输出：HTML 转义 + Markdown 结构字符转义。"""
    text = _escape(value)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    for char in _MD_ESCAPE_CHARS:
        text = text.replace(char, '\\' + char)
    lines = []
    for line in text.split('\n'):
        stripped = line.lstrip(' ')
        if stripped != line:
            line = '&nbsp;' * (len(line) - len(stripped)) + stripped
        line = line.replace('\t', '&nbsp;' * 4)
        lines.append(line)
    return '\n'.join(lines)


def _shown(value, blank_is_missing=False):
    if value is None:
        return '未提供'
    if blank_is_missing and isinstance(value, str) and not value.strip():
        return '未提供'
    return value


def _frozen_text(data, key, fallback):
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def report_markdown(data):
    """只读冻结 data_json 渲染；字段与当前规则常量解耦，不重算、不读当前库。"""
    if not is_conversion(data):
        _fail('不是转化观察报告')
    record = data.get('record') if isinstance(data.get('record'), dict) else {}
    snapshot = data.get('snapshot') if isinstance(data.get('snapshot'), dict) else {}
    result = data.get('result') if isinstance(data.get('result'), dict) else {}
    counts = data.get('counts') if isinstance(data.get('counts'), dict) else {}
    label = _frozen_text(data, 'label', LEGACY_LABEL)
    metric = _frozen_text(result, 'metric', LEGACY_METRIC)
    formula = _frozen_text(result, 'formula', LEGACY_FORMULA)
    limits = result.get('limits')
    if not isinstance(limits, list) or not limits:
        limits = list(LEGACY_LIMITS)
    lines = ['# %s' % _md(label), '',
             '登记：%s（平台 %s）' % (
                 _md(_shown(record.get('record_uid'))),
                 _md(_shown(record.get('platform')))),
             '指定快照：#%s（采集 %s；来源 %s）' % (
                 _md(_shown(snapshot.get('id'))),
                 _md(_shown(snapshot.get('collected_at'))),
                 _md(_shown(snapshot.get('source')))),
             '口径：%s' % _md(_shown(snapshot.get('definition'), blank_is_missing=True)),
             '可比声明：%s' % ('是（本快照播放与咨询按同一统计范围比较）'
                          if data.get('comparable') else '未声明'),
             '']
    version = data.get('rule_version')
    if isinstance(version, int) and not isinstance(version, bool):
        lines.extend(['规则版本：v%d' % version, ''])
    lines.extend([
        '## 原计数',
        '- 播放：%s' % ('未知' if counts.get('plays') is None
                       else _md(counts.get('plays'))),
        '- 咨询次数：%s' % ('未知' if counts.get('inquiries') is None
                        else _md(counts.get('inquiries'))),
        '',
        '## 规则结果',
        '计算项：%s' % _md(metric),
        '公式：%s' % _md(formula),
    ])
    if result.get('value') is not None:
        lines.append('结果：%s' % _md(result['value']))
    else:
        lines.append('结果：未计算')
        for gap in result.get('gaps') or []:
            lines.append('- 缺口：%s' % _md(gap))
    lines.extend(['', '## 咨询摘录（人工样本）'])
    consultations = data.get('consultation_snapshot') or []
    if not consultations:
        lines.append('- 未选择咨询摘录')
    for item in consultations:
        if not isinstance(item, dict):
            _fail('咨询摘录快照格式无效')
        lines.append('- %s（UID %s；来源 %s；时间 %s）' % (
            _md(_shown(item.get('text'))),
            _md(_shown(item.get('note_uid'))),
            _md(_shown(item.get('source'))),
            _md(_shown(item.get('occurred_at')))))
    lines.extend(['', '## 口径与限制'])
    for limit in limits:
        lines.append('- %s' % _md(limit))
    lines.append('- 生成时间（服务端）：%s' % _md(_shown(data.get('created_at'))))
    return '\n'.join(lines)
