"""T05：策略约束的选题候选池（纯规则，不调用模型）。"""
import datetime
import re

LANE_CONSERVATIVE = 'conservative'
LANE_EXPERIMENTAL = 'experimental'


def split_exclusions(text):
    return [part.strip() for part in re.split(r'[，,、;；\n]', str(text or '')) if part.strip()]


def _excluded(value, exclusions):
    return any(word in value for word in exclusions)


def _norm(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def _angle(post):
    text = str(post.get('title') or '') + ' ' + ' '.join(post.get('tags') or [])
    for words, angle in ((('误区', '做错', '避坑'), '误区纠正'),
                         (('对比', '前后', '实测'), '对比实测'),
                         (('清单', '合集'), '清单合集')):
        if any(word in text for word in words):
            return angle
    return '结构复刻'


def _conservative(keyword, pain, version):
    text = str(pain.get('pain') or '').strip()
    return {
        'topic_id': 'p%d' % pain.get('id'),
        'batch_id': '',
        'topic': '「%s」%s' % (keyword, text[:40]),
        'audience_question': text,
        'lane': LANE_CONSERVATIVE,
        'strategy_version': version,
        'signals': [{'type': 'pain', 'id': pain.get('id'),
                     'source': pain.get('source') or '',
                     'excerpt': pain.get('evidence') or text}],
        'reason': '评论证据线索；未写成已验证需求',
    }


def _experimental(keyword, post, version, expires_at):
    return {
        'topic_id': 'e%d' % post.get('id'),
        'batch_id': '',
        'topic': '「%s」%s' % (keyword, _angle(post)),
        'audience_question': '这个角度是否值得试？',
        'lane': LANE_EXPERIMENTAL,
        'strategy_version': version,
        'signals': [{'type': 'post', 'id': post.get('id'), 'source': 'radar',
                     'excerpt': str(post.get('title') or '')}],
        'reason': '参考作品角度；仅作实验假设，不是需求已验证',
        'hypothesis': '该角度可能带来更高完播',
        'risk': '热门作品不等于受众需求',
        'metric': '完播率/互动（待验证目标）',
        'expires_at': expires_at,
    }


def _observation(keyword, pain, version, expires_at):
    text = str(pain.get('pain') or '').strip()
    return {
        'topic_id': 'u%d' % pain.get('id'),
        'batch_id': '',
        'topic': '「%s」%s' % (keyword, text[:40]),
        'audience_question': text,
        'lane': LANE_EXPERIMENTAL,
        'strategy_version': version,
        'signals': [{'type': 'pain', 'id': pain.get('id'), 'source': 'user_observation',
                     'excerpt': text}],
        'reason': '用户观察；仅作假设，不是评论证据',
        'hypothesis': '用户观察线索，待验证',
        'risk': '没有评论证据，不能当已验证需求',
        'metric': '互动/评论（待验证目标）',
        'expires_at': expires_at,
    }


def build_candidates(keyword, strategy, posts, pains, references=None):
    strategy = strategy or {}
    data = strategy.get('data') or {}
    version = int(strategy.get('version') or 0)
    exclusions = split_exclusions(data.get('exclusions'))
    result = {'candidates': [], 'gap': {'conservative': 6, 'experimental': 4},
              'blocked': '', 'notes': []}
    if not strategy.get('confirmed'):
        result['blocked'] = '账号策略未确认，只能做研究草稿'
        return result
    experiment_allowed = data.get('experiment_allowed') is True
    expires_at = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
    context = [term for term in (str(data.get('direction') or '').strip(),
                                 str(data.get('audience') or '').strip(), keyword) if term]
    seen = set()
    skipped = 0
    conservative = []
    for pain in pains or []:
        text = str(pain.get('pain') or '').strip()
        if not text:
            continue
        if pain.get('evidence_role') != 'comment_evidence':
            skipped += 1
            continue
        topic = '「%s」%s' % (keyword, text[:40])
        if _excluded(topic, exclusions) or _excluded(text, exclusions):
            continue
        if context and not any(term in text for term in context):
            skipped += 1
            continue
        key = _norm(topic) + '|' + _norm(text)
        if key in seen:
            continue
        seen.add(key)
        conservative.append(_conservative(keyword, pain, version))
        if len(conservative) >= 6:
            break
    if skipped:
        result['notes'].append('%d 条痛点与当前策略无关或非评论证据，未入保守池' % skipped)
    experimental = []
    if experiment_allowed:
        for post in posts or []:
            topic = '「%s」%s' % (keyword, _angle(post))
            if _excluded(topic, exclusions):
                continue
            key = _norm(topic) + '|' + _norm('这个角度是否值得试？')
            if key in seen:
                continue
            seen.add(key)
            experimental.append(_experimental(keyword, post, version, expires_at))
            if len(experimental) >= 4:
                break
        for pain in pains or []:
            if len(experimental) >= 4:
                break
            if pain.get('evidence_role') != 'user_observation':
                continue
            text = str(pain.get('pain') or '').strip()
            topic = '「%s」%s' % (keyword, text[:40])
            if not text or _excluded(topic, exclusions):
                continue
            if context and not any(term in text for term in context):
                result['notes'].append('存在与当前方向无关的用户观察，标待核对')
                continue
            key = _norm(topic) + '|' + _norm(text)
            if key in seen:
                continue
            seen.add(key)
            experimental.append(_observation(keyword, pain, version, expires_at))
    else:
        result['notes'].append('未获实验许可，实验池为空')
    result['candidates'] = conservative + experimental
    result['gap'] = {'conservative': 6 - len(conservative),
                     'experimental': 4 - len(experimental)}
    return result


def validate_combo(candidates, conservative_ids, experimental_ids, strategy_version):
    by_id = {int(item['id']): item for item in candidates}
    con_ids = [int(x) for x in conservative_ids]
    exp_ids = [int(x) for x in experimental_ids]
    if len(con_ids) != 2 or len(exp_ids) != 1:
        raise ValueError('当日组合必须是 2 保守 + 1 实验')
    if len(set(con_ids + exp_ids)) != 3:
        raise ValueError('组合 ID 不能重复')
    picked = []
    for ident in con_ids + exp_ids:
        item = by_id.get(ident)
        if not item:
            raise ValueError('候选不存在')
        if int(item.get('strategy_version') or 0) != int(strategy_version):
            raise ValueError('候选与当前策略版本不一致')
        if item.get('expires_at') and str(item['expires_at']) < datetime.date.today().isoformat():
            raise ValueError('实验候选已过期')
        picked.append(item)
    if any(item['lane'] != LANE_CONSERVATIVE for item in picked[:2]):
        raise ValueError('保守池配比不正确')
    if picked[2]['lane'] != LANE_EXPERIMENTAL:
        raise ValueError('实验池配比不正确')
    batch_ids = {item.get('batch_id') for item in picked}
    if len(batch_ids) != 1:
        raise ValueError('候选不属于同一批次')
    return picked
