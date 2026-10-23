"""成片审阅：本机采样帧 + 人工台词 → 有引用/可执行修改项（M03）。

- 纯函数：validate_input / build_review_prompt / parse_review / demo_review。
- 只基于本次采样帧与用户文字；不听音轨、不完整观看；不宣称真实视觉质量。
- 输入：超限拒绝（不静默截断），类型严格，图片按解码字节校验。
- 输出：严格契约；可见观察必须有帧依据，台词观察必须有 manual 台词；
  修改项必须有 why 与可执行解释；未知来源拒绝；推断显式标明。
"""
import base64
import hashlib
import json
import math
import re

MAX_DURATION = 180.0
MAX_FRAMES = 16
MAX_IMAGE_CHARS = 280000
MAX_IMAGE_BYTES = 204800
MAX_TEXT = 2000
MAX_TRANSCRIPT = 5000
MAX_MANUSCRIPT = 20000
MAX_OBSERVATIONS = 12
MAX_CHANGES = 12
_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,20}$')
_SOURCE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_:.-]{0,63}$')

_SYSTEM = ('你是本地单用户成片审阅助手。只根据本次提供的采样帧和人工文字判断；'
           '你听不到音轨，也没有完整观看；不要编造画面、声音或效果结论；'
           '把可见/文字内容与推断分开；输出必须是 JSON，不要额外说明。')

_SCHEMA = '''{
 "summary": "本次审阅摘要",
 "observations": [{"id": "o1", "text": "观察", "kind": "visible|transcript|inference", "frames": [1], "sources": ["frame:1"], "basis": "可读依据"}],
 "changes": [{"id": "c1", "what": "改什么", "why": "为什么", "sources": ["frame:1"], "frames": [1], "basis": "可读依据", "conditions": "适用条件", "gaps": "缺口", "next": "下一步"}],
 "cannot_judge": ["不能判断的（声音/完整观看/效果等）"],
 "gaps": ["资料缺口"],
 "next": ["下一步动作"]
}'''


def _text(value, name, limit, required=False):
    if value is None:
        if required:
            raise ValueError('请填写%s' % name)
        return ''
    if not isinstance(value, str):
        raise ValueError('%s必须是文本' % name)
    text = value.strip()
    if required and not text:
        raise ValueError('请填写%s' % name)
    if len(text) > limit:
        raise ValueError('%s超过 %d 字上限，请精简后再提交' % (name, limit))
    return text


def validate_input(body):
    if not isinstance(body, dict):
        raise ValueError('审阅输入格式无效')
    goal = _text(body.get('goal'), '审阅目标', MAX_TEXT, required=True)
    business = _text(body.get('business'), '业务/商品或服务', MAX_TEXT)
    audience = _text(body.get('audience'), '目标受众', MAX_TEXT)
    resources = _text(body.get('resources'), '真实资源/限制', MAX_TEXT)
    duration = body.get('duration')
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
        raise ValueError('视频时长需为 0–180 秒')
    frames = body.get('frames')
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError('需提供 1–16 张本机采样帧')
    cleaned = []
    for index, frame in enumerate(frames, 1):
        if not isinstance(frame, dict):
            raise ValueError('采样帧格式无效')
        at, image = frame.get('at'), frame.get('image')
        if type(at) not in (int, float) or not math.isfinite(at) or not 0 <= at <= duration:
            raise ValueError('采样帧时间无效')
        if (not isinstance(image, str) or not image.startswith('data:image/jpeg;base64,')
                or len(image) > MAX_IMAGE_CHARS):
            raise ValueError('采样帧必须为本机 JPEG（编码长度超限）')
        try:
            raw = base64.b64decode(image.split(',', 1)[1], validate=True)
        except Exception:
            raise ValueError('采样帧不是有效 JPEG 数据')
        if len(raw) < 4 or not raw.startswith(b'\xff\xd8') or not raw.endswith(b'\xff\xd9'):
            raise ValueError('采样帧不是有效 JPEG 数据')
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('采样帧解码后超过 200KB 上限')
        cleaned.append({'frame': index, 'at': round(float(at), 2), 'image': image,
                        'sha256': hashlib.sha256(raw).hexdigest()})
    if len({round(item['at'], 2) for item in cleaned}) != len(cleaned):
        raise ValueError('采样帧时间不能重复')
    if 'transcript' in body:
        transcript = body['transcript']
        if not isinstance(transcript, dict):
            raise ValueError('台词来源格式无效')
    else:
        transcript = {}
    source = transcript.get('source') or 'none'
    if source not in ('none', 'manual'):
        raise ValueError('台词来源只能是 none 或 manual')
    text = transcript.get('text')
    if source == 'none':
        if text not in (None, ''):
            raise ValueError('台词来源为 none 时不能携带台词文字')
        text = ''
    else:
        text = _text(text, '人工台词', MAX_TRANSCRIPT, required=True)
    complete = transcript.get('complete', body.get('transcript_complete'))
    if complete is None:
        complete = False
    if not isinstance(complete, bool):
        raise ValueError('台词完整性必须为布尔值')
    return {'goal': goal, 'business': business, 'audience': audience, 'resources': resources,
            'duration': round(float(duration), 2), 'frames': cleaned,
            'transcript': {'source': source, 'text': text},
            'transcript_complete': complete}


def _refs_lines(refs):
    return '\n'.join('- %s：%s' % (ref.get('id'), str(ref.get('text') or '')[:1000]) for ref in refs or [])


def build_review_prompt(input_data, manuscript, extra_context=None, base_version=None):
    manuscript_text = ''
    if manuscript:
        status = manuscript.get('status_json') or {}
        context = manuscript.get('context_json') or {}
        if (manuscript.get('legacy_snapshot') or not manuscript.get('topic')) and not status and not context:
            manuscript_text = ('关联研究稿（旧记录：无版本快照，兼容回退到稿件级）：%s v%s\n'
                               % (manuscript.get('draft_uid'), manuscript.get('version')))
        else:
            manuscript_text = (
                '关联研究稿（该版本当时冻结，不得改写%s）：%s v%s\n主题：%s\n业务：%s\n受众：%s\n'
                '目标：%s\n真实资源/限制：%s\n可投入产能/时间：%s\n当前问题：%s\n'
                '版本正文（不可截断）：\n%s\n该版本当时的资料：\n%s\n'
                % ('；旧记录：无版本快照，已兼容回退到稿件级资料' if manuscript.get('legacy_snapshot') else '',
                   manuscript.get('draft_uid'), manuscript.get('version'),
                   manuscript.get('topic') or '未记录', status.get('business') or '未填写',
                   status.get('audience') or '未填写', status.get('goal') or '未填写',
                   status.get('resources') or '未填写', status.get('capacity') or '未填写',
                   status.get('question') or '未填写',
                   (manuscript.get('content_json') or {}).get('draft_markdown') or '（空）',
                   _refs_lines(context.get('refs')) or '（无）')
            )
    extra = ''
    if extra_context and (extra_context.get('refs') or []):
        extra = ('本次另外明确选择的资料（与稿件冻结资料区分，不得混为同一时点）：\n%s\n'
                 % _refs_lines(extra_context.get('refs')))
    frame_desc = '；'.join('帧%d=%.2f秒' % (item['frame'], item['at']) for item in input_data['frames'])
    transcript = input_data['transcript']
    user = (
        '审阅目标：%s\n'
        '业务/商品或服务：%s\n目标受众：%s\n真实资源/限制：%s\n\n'
        '本次观察范围：时长 %.2f 秒；采样帧 %s；台词来源=%s%s；模型不听音轨、未完整观看。\n\n'
        '人工台词：%s\n\n'
        '%s%s'
        '要求：\n'
        '1. 观察 kind：visible 必须引用本次帧编号；transcript 必须确有 manual 台词；inference 是推断。\n'
        '2. sources 用结构化标识：frame:N、transcript、manuscript，以及已加载资料 id；未知来源不要写。\n'
        '3. 修改项给 what/why（必填）/conditions/gaps/next，帧依据只引用本次帧编号。\n'
        '4. 不判断声音质量、完整观看、传播/转化效果；这些写入 cannot_judge。\n'
        '5. 只输出 JSON：\n%s'
    ) % (input_data['goal'], input_data['business'] or '未填写', input_data['audience'] or '未填写',
         input_data['resources'] or '未填写', input_data['duration'], frame_desc,
         transcript['source'], ('（用户声明完整）' if input_data.get('transcript_complete') else ''),
         transcript['text'] or '（无）', manuscript_text, extra, _SCHEMA)
    allowed_sources = {'frame:%d' % item['frame'] for item in input_data['frames']}
    if transcript['source'] == 'manual':
        allowed_sources.add('transcript')
    if manuscript:
        allowed_sources.add('manuscript')
        allowed_sources.update(str(ref['id']) for ref in
                               (manuscript.get('context_json') or {}).get('refs') or []
                               if ref.get('id'))
    allowed_sources.update(str(ref['id']) for ref in (extra_context or {}).get('refs') or []
                           if ref.get('id'))
    user += ('\n本次可用来源标识（完整白名单）：%s\n'
             'sources 每项必须从此清单逐字选择，不能创建别名。业务、目标、资源是输入文字，'
             '不能据此另造 business/goal/resources/user 等来源标识；不含 manuscript 或 transcript '
             '时不得引用它们。不能直接引用合法来源的判断写为 inference 或 cannot_judge；'
             '修改项没有合法来源时不凑 changes。\n'
             '帧与来源必须成对：每当 observations 或 changes 的 frames 列出 N，sources 必须同时包含 '
             'frame:N。纯台词修改使用 frames:[]、sources:["transcript"]；基于帧1的修改使用 '
             'frames:[1]、sources:["frame:1"]，不得只写其他来源却仍声明 frames:[1]。\n'
             % json.dumps(sorted(allowed_sources), ensure_ascii=False))
    return _SYSTEM, user


def _str_list(value, name, limit=12, cap=500):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('%s 必须是字符串数组' % name)
    return [item.strip()[:cap] for item in value if item.strip()][:limit]


def _checked_list(data, key, limit=12):
    if key in data and not isinstance(data[key], list):
        raise ValueError('%s 必须是数组' % key)
    value = data.get(key)
    if isinstance(value, list) and len(value) > limit:
        raise ValueError('%s 条数超过上限' % key)
    return _str_list(value, key)


def parse_review(text, scope):
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError('模型输出不是合法 JSON')
    if not isinstance(data, dict):
        raise ValueError('模型输出结构无效')
    summary = data.get('summary')
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('缺少摘要')
    frame_count = int(scope.get('frame_count') or 0)
    transcript_available = scope.get('transcript') == 'manual'
    manuscript = bool(scope.get('manuscript'))
    allowed_sources = {'frame:%d' % index for index in range(1, frame_count + 1)}
    if transcript_available:
        allowed_sources.add('transcript')
    if manuscript:
        allowed_sources.add('manuscript')
    allowed_sources.update(scope.get('refs') or [])
    result = {'summary': summary.strip()[:2000], 'observations': [], 'changes': [],
              'cannot_judge': _checked_list(data, 'cannot_judge'),
              'gaps': _checked_list(data, 'gaps'),
              'next': _checked_list(data, 'next')}
    seen = set()

    def row_id(value, prefix, index):
        text_id = str(value or ('%s%d' % (prefix, index))).strip()
        if not _ID_RE.match(text_id):
            raise ValueError('审阅条目 ID 格式无效')
        if text_id in seen:
            raise ValueError('审阅条目 ID 重复')
        seen.add(text_id)
        return text_id

    def sources_of(item, required):
        if 'sources' in item:
            sources = item['sources']
            if not isinstance(sources, list):
                raise ValueError('sources 必须是数组')
        else:
            sources = []
        cleaned = []
        for source in sources or []:
            if not isinstance(source, str) or not _SOURCE_RE.match(source):
                raise ValueError('sources 含无效来源标识')
            if source not in allowed_sources:
                raise ValueError('sources 引用了本次不可用的来源')
            if source not in cleaned:
                cleaned.append(source)
        if required and not cleaned:
            raise ValueError('该条目缺少有效依据来源')
        return cleaned

    def frames_of(item):
        if 'frames' in item:
            frames = item['frames']
            if not isinstance(frames, list):
                raise ValueError('frames 必须是数组')
        else:
            frames = []
        cleaned = []
        for frame in frames or []:
            if type(frame) is not int or not 1 <= frame <= frame_count:
                raise ValueError('引用了不存在的帧')
            if frame not in cleaned:
                cleaned.append(frame)
        return cleaned

    if 'observations' in data:
        raw_observations = data['observations']
        if not isinstance(raw_observations, list):
            raise ValueError('observations 必须是数组')
        if len(raw_observations) > MAX_OBSERVATIONS:
            raise ValueError('observations 条数超过上限')
    else:
        raw_observations = []
    for index, item in enumerate(raw_observations or [], 1):
        if not isinstance(item, dict):
            raise ValueError('观察行必须是对象')
        if not isinstance(item.get('text'), str) or not item['text'].strip():
            raise ValueError('观察缺少正文')
        kind = item.get('kind') or 'inference'
        if kind not in ('visible', 'transcript', 'inference'):
            raise ValueError('观察类型无效')
        frames = frames_of(item)
        sources = sources_of(item, required=(kind != 'inference'))
        if kind == 'visible' and not frames:
            raise ValueError('可见观察必须引用本次帧')
        if kind == 'transcript' and not transcript_available:
            raise ValueError('没有人工台词，不能作为台词观察')
        if kind == 'visible' and any(('frame:%d' % frame) not in sources for frame in frames):
            raise ValueError('可见观察的帧必须同时出现在 sources')
        if 'basis' in item and not isinstance(item['basis'], str):
            raise ValueError('观察的 basis 必须是字符串')
        basis = item.get('basis') or ''
        result['observations'].append({
            'id': row_id(item.get('id'), 'o', index), 'text': item['text'].strip()[:1000],
            'kind': kind, 'frames': frames, 'sources': sources,
            'basis': (basis or '')[:500],
            'unverified': kind == 'inference'})
    if 'changes' in data:
        raw_changes = data['changes']
        if not isinstance(raw_changes, list):
            raise ValueError('changes 必须是数组')
        if len(raw_changes) > MAX_CHANGES:
            raise ValueError('changes 条数超过上限')
    else:
        raw_changes = []
    for index, item in enumerate(raw_changes or [], 1):
        if not isinstance(item, dict):
            raise ValueError('修改项必须是对象')
        if not isinstance(item.get('what'), str) or not item['what'].strip():
            raise ValueError('修改项缺少正文')
        if not isinstance(item.get('why'), str) or not item['why'].strip():
            raise ValueError('修改项缺少 why（为什么改）')
        frames = frames_of(item)
        sources = sources_of(item, required=True)
        for frame in frames:
            if ('frame:%d' % frame) not in sources:
                raise ValueError('修改项声明了帧 %d，但来源中没有 frame:%d' % (frame, frame))
        row = {'id': row_id(item.get('id'), 'c', index), 'what': item['what'].strip()[:1000],
               'why': item['why'].strip()[:500], 'frames': frames, 'sources': sources}
        for field in ('basis', 'conditions', 'gaps', 'next'):
            if field in item and not isinstance(item[field], str):
                raise ValueError('修改项的 %s 必须是字符串' % field)
            row[field] = (item.get(field) or '')[:500]
        for field in ('conditions', 'gaps', 'next'):
            if not row[field].strip():
                raise ValueError('修改项缺少 %s（可写“未知/待确认/不适用”）' % field)
        row['unverified'] = False
        result['changes'].append(row)
    if not (result['observations'] or result['changes']):
        raise ValueError('模型输出缺少观察或修改项')
    return result


def demo_review(input_data, manuscript):
    frames = input_data['frames']
    observations = [{
        'id': 'o1', 'text': '本次采样帧 %d 张（时间 %s）'
        % (len(frames), '、'.join('帧%d=%.2f秒' % (item['frame'], item['at']) for item in frames)),
        'kind': 'inference', 'frames': [], 'sources': [], 'basis': '本次素材范围', 'unverified': True}]
    if input_data['transcript']['source'] == 'manual':
        observations.append({'id': 'o2', 'text': '用户提供人工台词 %d 字，可用于措辞/结构判断'
                             % len(input_data['transcript']['text']), 'kind': 'transcript',
                             'frames': [], 'sources': ['transcript'], 'basis': '人工文字来源：manual',
                             'unverified': False})
    changes = [{
        'id': 'c1', 'what': '对照审阅目标“%s”，逐帧检查开场是否交代主题' % input_data['goal'][:40],
        'why': '只基于采样帧的流程演示', 'sources': ['frame:1'], 'frames': [1],
        'basis': '采样帧 %d 张' % len(frames), 'conditions': '用户自行观看原片后确认',
        'gaps': '未提供完整观看与音轨', 'next': '用户确认后，再决定是否作为正式修改项', 'unverified': False}]
    if manuscript:
        observations.append({'id': 'o3', 'text': '已关联研究稿 %s v%s，用于对照结构'
                             % (manuscript.get('draft_uid'), manuscript.get('version')),
                             'kind': 'inference', 'frames': [], 'sources': ['manuscript'],
                             'basis': '稿件快照', 'unverified': True})
    return {'summary': '演示审阅：仅验证流程，未真实识别画面，不代表内容质量判断。',
            'observations': observations, 'changes': changes,
            'cannot_judge': ['模型没有听音轨，不能判断声音/配乐/口型', '只看采样帧，不能声称完整观看',
                             '没有发布指标，不能判断传播/转化效果'],
            'gaps': ['缺少可用于核验的完整台词（如未提供）'],
            'next': ['补齐台词/完整观看后再审', '如有正式指标，再单独评估效果'],
            'source': 'demo'}

