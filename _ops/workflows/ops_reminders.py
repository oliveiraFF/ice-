"""M05-F1 本地提醒核心（纯函数，FC 独立模块）。

只做内存内的确定工作：严格输入校验、父对象权威核验（调用方已加载）、
显示状态计算、带行版本的本地更新、以及不依赖机器时区的本地时间换算。

不读文件/数据库/环境/网络，不偷读真实时钟：`now`、`created_at`、`uid` 全部由调用方显式传入。
创建后绑定对象不可改绑；编辑只允许 title/note/due_at/status。
"""
import datetime
import math

TARGET_KINDS = ('advice_action', 'draft_version')
STATUSES = ('open', 'done', 'cancelled')
STATE_LABELS = {'upcoming': '未到期', 'due': '已到期', 'done': '完成', 'cancelled': '取消'}

MAX_TITLE = 200
MAX_NOTE = 1000
MAX_UID = 64
MAX_ACTION_ID = 64
DUE_MIN = 0
DUE_MAX = 253402300799

_CREATE_FIELDS = ('title', 'note', 'target_kind', 'target_uid', 'target_sub_id', 'due_at')
_UPDATE_FIELDS = ('title', 'note', 'due_at', 'status', 'expected_row_version')
_UID_CHARS = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')


class ReminderConflict(ValueError):
    """行版本冲突；FI 映射为 409，FC 只抛受控异常。"""


def _fail(message):
    raise ValueError(message)


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail('%s 必须是有限数字' % name)
    if isinstance(value, int):
        # R1：整数先比较已定义范围，绝不把任意大 int 隐式转 float。
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


def _text(value, name, minimum, maximum):
    if not isinstance(value, str):
        _fail('%s 必须是字符串' % name)
    if len(value) < minimum:
        _fail('%s 长度不足' % name)
    if len(value) > maximum:
        _fail('%s 超过 %d 码点上限' % (name, maximum))
    if minimum >= 1 and not value.strip():
        _fail('%s 不能是空白' % name)
    return value


def _uid(value, name='UID'):
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_UID:
        _fail('%s 无效' % name)
    if any(char not in _UID_CHARS for char in value):
        _fail('%s 无效' % name)
    return value


def validate_due_at(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail('到期时间必须是 UTC Unix 秒数字')
    if isinstance(value, int):
        if value < DUE_MIN or value > DUE_MAX:
            _fail('到期时间超出允许范围（%d–%d 秒）' % (DUE_MIN, DUE_MAX))
        return value
    if not math.isfinite(value):
        _fail('到期时间必须是有限数字')
    if value < DUE_MIN or value > DUE_MAX:
        _fail('到期时间超出允许范围（%d–%d 秒）' % (DUE_MIN, DUE_MAX))
    return value


def validate_target(target_kind, target_uid, target_sub_id):
    if target_kind not in TARGET_KINDS:
        _fail('绑定类型只能是 advice_action 或 draft_version')
    target_uid = _uid(target_uid, '绑定对象 UID')
    if target_kind == 'advice_action':
        if not isinstance(target_sub_id, str) or not target_sub_id:
            _fail('动作 ID 必须是非空字符串')
        if len(target_sub_id) > MAX_ACTION_ID:
            _fail('动作 ID 过长')
        return target_kind, target_uid, target_sub_id
    if isinstance(target_sub_id, bool) or not isinstance(target_sub_id, int) or target_sub_id <= 0:
        _fail('研究稿版本必须是正整数（不接受字符串/小数/布尔）')
    return target_kind, target_uid, target_sub_id


def validate_parent(target_kind, target_uid, target_sub_id, parent):
    """父对象权威核验（parent 由 FI 按权威接口加载）；返回精简身份快照。"""
    if target_kind == 'advice_action':
        if not isinstance(parent, dict):
            _fail('建议对象无效')
        if parent.get('advice_uid') != target_uid:
            _fail('建议不存在或归属不符')
        if parent.get('archived'):
            _fail('建议已归档')
        if parent.get('simulated'):
            _fail('演练建议不能用于提醒')
        result = parent.get('result_json')
        if not isinstance(result, dict):
            _fail('建议还没有分析结果，不能绑定动作')
        rows = result.get('week_actions')
        if not isinstance(rows, list):
            _fail('建议动作集合无效')
        for row in rows:
            if (isinstance(row, dict) and isinstance(row.get('id'), str)
                    and row.get('id') == target_sub_id):
                return {'kind': target_kind, 'uid': target_uid, 'sub_id': target_sub_id,
                        'title': str(row.get('action') or '')[:MAX_TITLE]}
        _fail('该动作不属于所选建议')
    if target_kind != 'draft_version':
        _fail('绑定类型无效')
    if not isinstance(parent, dict):
        _fail('研究稿对象无效')
    draft = parent.get('draft')
    version = parent.get('version')
    if not isinstance(draft, dict) or not isinstance(version, dict):
        _fail('研究稿与版本必须同时提供')
    if draft.get('draft_uid') != target_uid:
        _fail('研究稿不存在或归属不符')
    if draft.get('archived'):
        _fail('研究稿已归档')
    if draft.get('simulated'):
        _fail('演练研究稿不能用于提醒')
    owner = version.get('draft_uid')
    if not isinstance(owner, str) or owner != target_uid:
        _fail('版本缺少归属或不属于该研究稿')
    stored_version = version.get('version')
    if (isinstance(stored_version, bool) or not isinstance(stored_version, int)
            or stored_version != target_sub_id):
        _fail('研究稿版本不存在或格式无效')
    title = version.get('topic') or draft.get('topic') or ''
    return {'kind': target_kind, 'uid': target_uid, 'sub_id': target_sub_id,
            'title': str(title)[:MAX_TITLE]}


def validate_create(payload, parent, now, uid):
    """创建提醒：客户端不能覆盖 uid/时间/版本/状态等服务器字段。"""
    if not isinstance(payload, dict):
        _fail('提醒请求格式无效')
    unknown = sorted(str(key) for key in payload if key not in _CREATE_FIELDS)
    if unknown:
        _fail('提醒请求包含不支持的字段：%s' % '、'.join(unknown))
    title = _text(payload.get('title'), '提醒标题', 1, MAX_TITLE)
    note = payload.get('note', '')
    note = _text(note, '备注', 0, MAX_NOTE)
    due_at = validate_due_at(payload.get('due_at'))
    kind, target_uid, target_sub_id = validate_target(payload.get('target_kind'),
                                                      payload.get('target_uid'),
                                                      payload.get('target_sub_id'))
    snapshot = validate_parent(kind, target_uid, target_sub_id, parent)
    now = _number(now, '创建时间', 0, DUE_MAX)
    return {'uid': _uid(uid, '提醒 UID'), 'title': title, 'note': note,
            'target_kind': kind, 'target_uid': target_uid, 'target_sub_id': target_sub_id,
            'due_at': due_at, 'status': 'open', 'row_version': 1,
            'created_at': now, 'updated_at': now, 'parent': snapshot}


def validate_update(payload):
    """编辑/状态变更：只允许 title/note/due_at/status + expected_row_version。"""
    if not isinstance(payload, dict):
        _fail('提醒更新格式无效')
    unknown = sorted(str(key) for key in payload if key not in _UPDATE_FIELDS)
    if unknown:
        _fail('提醒更新包含不支持的字段：%s' % '、'.join(unknown))
    expected = payload.get('expected_row_version')
    if isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0:
        _fail('expected_row_version 必须是正整数')
    if not any(key in payload for key in ('title', 'note', 'due_at', 'status')):
        _fail('没有可更新的字段')
    patch = {'expected_row_version': expected}
    if 'title' in payload:
        patch['title'] = _text(payload['title'], '提醒标题', 1, MAX_TITLE)
    if 'note' in payload:
        patch['note'] = _text(payload['note'], '备注', 0, MAX_NOTE)
    if 'due_at' in payload:
        patch['due_at'] = validate_due_at(payload['due_at'])
    if 'status' in payload:
        if payload['status'] not in STATUSES:
            _fail('提醒状态只能是 open/done/cancelled')
        patch['status'] = payload['status']
    return patch


def apply_update(reminder, payload, now):
    """带行版本的本地更新；冲突抛 ReminderConflict（FI 映射 409）。"""
    if not isinstance(reminder, dict):
        _fail('提醒对象无效')
    current = reminder.get('row_version')
    if isinstance(current, bool) or not isinstance(current, int) or current <= 0:
        _fail('提醒行版本无效')
    patch = validate_update(payload)
    if patch['expected_row_version'] != current:
        raise ReminderConflict('提醒已被更新，请刷新后重试')
    now = _number(now, '更新时间', 0, DUE_MAX)
    updated = dict(reminder)
    for key in ('title', 'note', 'due_at', 'status'):
        if key in patch:
            updated[key] = patch[key]
    updated['row_version'] = current + 1
    updated['updated_at'] = now
    return updated


def display_state(reminder, now):
    """open 且 due_at <= now 为已到期；done/cancelled 不因时间改变。"""
    if not isinstance(reminder, dict):
        _fail('提醒对象无效')
    status = reminder.get('status')
    if status not in STATUSES:
        _fail('提醒状态无效')
    now = _number(now, '当前时间', 0, DUE_MAX)
    if status == 'done':
        return 'done'
    if status == 'cancelled':
        return 'cancelled'
    due_at = validate_due_at(reminder.get('due_at'))
    return 'due' if due_at <= now else 'upcoming'


def state_label(state):
    if state not in STATE_LABELS:
        _fail('提醒状态无效')
    return STATE_LABELS[state]


# ---------------------------------------------------------------- 时区换算

def _parse_local(value):
    if not isinstance(value, str):
        _fail('本地时间必须是字符串')
    text = value
    if len(text) == 16:
        fmt = '%Y-%m-%dT%H:%M'
    elif len(text) == 19:
        fmt = '%Y-%m-%dT%H:%M:%S'
    else:
        _fail('本地时间格式必须是 YYYY-MM-DDTHH:MM[:SS]')
    try:
        return datetime.datetime.strptime(text, fmt)
    except ValueError:
        _fail('本地时间无效')


def _offset_minutes(value, name='UTC 偏移'):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail('%s 必须是整数分钟' % name)
    if value < -840 or value > 840:
        _fail('%s 超出范围' % name)
    return value


def local_to_epoch(value, offset_minutes):
    """本地墙钟 + 明确偏移 → UTC Unix 秒（只换算一次，不把墙钟当 UTC）。"""
    wall = _parse_local(value)
    offset = _offset_minutes(offset_minutes)
    try:
        wall_seconds = _naive_seconds(wall)
    except (OverflowError, OSError, ValueError):
        _fail('本地时间超出可转换范围')
    epoch = wall_seconds - offset * 60
    return int(epoch) if epoch == int(epoch) else epoch


def epoch_to_local(epoch, offset_minutes):
    """UTC Unix 秒 + 明确偏移 → 本地墙钟字符串。"""
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)):
        _fail('时间点必须是数字')
    if isinstance(epoch, int):
        # R1：整数先比较范围，避免把任意大 int 转 float。
        if epoch < DUE_MIN or epoch > DUE_MAX:
            _fail('时间点超出允许范围')
    else:
        if not math.isfinite(epoch):
            _fail('时间点必须是有限数字')
        if epoch < DUE_MIN or epoch > DUE_MAX:
            _fail('时间点超出允许范围')
    offset = _offset_minutes(offset_minutes)
    try:
        local = datetime.datetime(1970, 1, 1) + datetime.timedelta(
            seconds=epoch + offset * 60)
    except (OverflowError, OSError, ValueError):
        _fail('本地时间超出可显示范围，无法转换')
    if local.second or local.microsecond:
        return local.strftime('%Y-%m-%dT%H:%M:%S')
    return local.strftime('%Y-%m-%dT%H:%M')


def format_offset(offset_minutes):
    offset = _offset_minutes(offset_minutes)
    sign = '+' if offset >= 0 else '-'
    total = abs(offset)
    return '%s%02d:%02d' % (sign, total // 60, total % 60)


def _naive_seconds(wall):
    base = datetime.datetime(1970, 1, 1)
    return (wall - base).total_seconds()


def local_time_status(value, transition_epoch, offset_before, offset_after):
    """判断本地墙钟在给定时区切换点附近是唯一、重复（歧义）还是不存在（gap）。"""
    wall = _parse_local(value)
    transition = _number(transition_epoch, '时区切换时间点', 0, DUE_MAX)
    before = _offset_minutes(offset_before, '切换前偏移')
    after = _offset_minutes(offset_after, '切换后偏移')
    if before == after:
        _fail('时区切换前后偏移不能相同')
    wall_seconds = _naive_seconds(wall)
    epoch_before = wall_seconds - before * 60
    epoch_after = wall_seconds - after * 60
    valid_before = epoch_before < transition
    valid_after = epoch_after >= transition
    if valid_before and valid_after:
        return {'status': 'ambiguous', 'epochs': [int(epoch_before), int(epoch_after)]}
    if valid_before:
        return {'status': 'unique', 'epochs': [int(epoch_before)]}
    if valid_after:
        return {'status': 'unique', 'epochs': [int(epoch_after)]}
    return {'status': 'gap', 'epochs': []}


def resolve_local_epoch(value, offset_minutes=None, transition_epoch=None,
                        offset_before=None, offset_after=None, fold=None):
    """解析本地墙钟为绝对 UTC 点；gap 拒绝，歧义必须显式 fold（0 前/1 后）。"""
    if transition_epoch is None:
        if offset_minutes is None:
            _fail('固定偏移或时区切换参数必须提供其一')
        return local_to_epoch(value, offset_minutes)
    status = local_time_status(value, transition_epoch, offset_before, offset_after)
    if status['status'] == 'gap':
        _fail('本地时间在该时区不存在（夏令时跳变），请核对实际时刻')
    if status['status'] == 'ambiguous':
        if isinstance(fold, bool) or not isinstance(fold, int) or fold not in (0, 1):
            _fail('本地时间在该时区出现两次，请明确选择实际时刻（0 或 1）')
        return status['epochs'][fold]
    return status['epochs'][0]
