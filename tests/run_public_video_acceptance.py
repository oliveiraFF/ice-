"""Opt-in public-document sample acceptance; one durable claim per paid provider.

Artifacts and credentials stay outside Git. Fetch uses the production TikHub
adapter once, then imports its actual response into the packaged application.
It does not use the catalogue's additional authenticated balance lookup.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from check_frozen_owner_lifecycle import launch, close_cleanly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import extract_posts, tikhub_json
from free_tools import download_cached_video
from video_creative import VideoCreative

ROUTE = '/api/v1/douyin/app/v3/fetch_one_video_by_share_url'
SAMPLE = 'https://v.douyin.com/e3x2fjE/'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def load(path):
    return json.loads(path.read_text('utf-8'))


def key_from(path, provider):
    raw = path.read_text('utf-8-sig').strip()
    pattern = r'sk-[A-Za-z0-9_-]{16,}' if provider == 'deepseek' else r'(?<![A-Za-z0-9_./+=-])[A-Za-z0-9_./+=-]{24,500}(?![A-Za-z0-9_./+=-])'
    candidates = re.findall(pattern, raw)
    if len(candidates) != 1:
        raise ValueError('Credential file must contain exactly one recognizable key; contents hidden')
    return candidates[0]


def claim(out, provider, details, run_id='R01-20261027'):
    # The global run ID prevents a new output subfolder from granting a retry.
    with (out.parent / (run_id + '-' + provider + '-claimed.json')).open('x', encoding='utf-8') as f:
        json.dump(dict(details, run_id=run_id, provider=provider,
                       max_requests=1, max_cny=1, retry=False), f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())


def request(origin, path, value=None):
    options = {}
    if value is not None:
        with urlopen(origin + '/api/state?mode=live', timeout=10) as r:
            token = json.load(r)['token']
        options = dict(data=value if isinstance(value, bytes) else json.dumps(value).encode(), headers={
            'Origin': origin, 'X-Radar-Token': token,
            'Content-Type': 'video/mp4' if isinstance(value, bytes) else 'application/json',
            'X-Radar-Filename': 'R01-public-sample.mp4'})
    try:
        with urlopen(Request(origin + path, **options), timeout=120) as r:
            result = json.load(r)
    except HTTPError as e:
        raise ValueError('Local application HTTP ' + str(e.code)) from None
    if isinstance(result, dict) and result.get('error'):
        raise ValueError(result['error'])
    return result


def fetch(args, out):
    key = key_from(args.tikhub_key, 'tikhub')
    info = tikhub_json('/api/v1/tikhub/user/get_endpoint_info', params={'endpoint': ROUTE})
    dump(out / 'tikhub-price.json', info)
    price = info.get('data') or {}
    cost = float(price['endpoint_cost'])
    assert price['endpoint_uri'] == ROUTE and 0 <= cost * 10 <= 1
    # Also honor the original durable R01 filename used before run IDs were explicit.
    if args.run_id == 'R01-20261027' and (out.parent/'R01-tikhub-claimed.json').exists():
        raise FileExistsError('Original R01 TikHub authorization already claimed')
    claim(out, 'tikhub', dict(route=ROUTE, sample=SAMPLE, usd=cost,
          usd_to_cny_safety_factor=10, conservative_cny=cost * 10,
          pricing_lookup='unauthenticated public metadata; no balance lookup'), args.run_id)
    try:
        payload = tikhub_json(ROUTE, key=key, params={'share_url': SAMPLE})
        # Never persist a credential, even if an upstream service echoed it.
        payload = json.loads(json.dumps(payload, ensure_ascii=False).replace(key, '[REDACTED]'))
        dump(out / 'tikhub-response.json', payload)
        posts = extract_posts(payload, 'dy')
        dump(out / 'posts.json', posts)
        result = dict(authenticated_requests=1, automatic_retries=0, code=payload.get('code'),
                      posts=len(posts), priced_usd=cost, cny_safety_ceiling=cost * 10,
                      sample=SAMPLE, documentation='https://docs.tikhub.io/186826220e0')
        dump(out / 'fetch-result.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:
        dump(out / 'fetch-failed.json', dict(type=type(exc).__name__, retry=False))
        raise


def prepare(args, out):
    posts = load(out / 'posts.json')
    assert posts and posts[0].get('video_url'), 'Public sample did not return a playable video; no retry allowed'
    downloaded = download_cached_video(dict(posts[0], id=1), out / 'source-media')
    source = out / 'source-media' / downloaded['filename']
    video = out / 'R01-public-sample.mp4'
    # Re-encode only to meet the existing app upload limit; retain the original.
    subprocess.run([str(args.ffmpeg), '-v', 'error', '-i', str(source), '-t', '180',
                    '-vf', 'scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '28', '-c:a', 'aac',
                    '-b:a', '64k', '-movflags', '+faststart', str(video)], check=True)
    assert video.stat().st_size <= 20 * 1024 * 1024
    probe = subprocess.run([str(args.ffmpeg), '-i', str(video)], capture_output=True)
    metadata = probe.stderr.decode('utf-8', errors='replace')
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', metadata)
    assert match, 'Cannot determine actual media duration'
    duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
    duration = min(180, duration)
    audio = 'Audio:' in metadata
    if audio:
        subprocess.run([str(args.ffmpeg), '-v', 'error', '-i', str(video), '-vn',
                        '-ac', '1', '-ar', '16000', str(out / 'audio.wav')], check=True)
    body = dict(product='公开样本结构复盘（技术验收，未提供商品资料）',
        audience='本轮仅检查公开视频的内容结构；目标经营受众尚未确认',
        facts='已核实的来源：TikHub 官方文档公开样本。标题：' + posts[0]['title'][:700] +
              '。只允许引用采样画面可见内容；未提供商品规格、价格、功效和真实经营指标。',
        conditions='仅输出待人工确认的拍摄结构草稿；没有授权认领作者身份或原视频商品。',
        details='来源：https://docs.tikhub.io/186826220e0；样本：' + SAMPLE +
                '。真实抓取媒体，最多取前180秒。缺少逐字稿，本轮不调用ASR，不评价音轨。'
                '不要编造台词、商品证明、账号表现或已完成拍摄。未确认项列入待补信息。',
        transcript='', transcript_source='none', goal='吸引观看', format='场景故事',
        style='自然分享', reference='借鉴整体结构', outputs=['shooting', 'video_prompt'],
        target_seconds=30, duration=duration, confirmed=True, frames=[])
    for i in range(5):
        at = round(duration * (i + .5) / 5, 3)
        frame = out / ('frame%d.jpg' % (i + 1))
        subprocess.run([str(args.ffmpeg), '-v', 'error', '-ss', str(at), '-i', str(video),
                        '-frames:v', '1', '-q:v', '5', str(frame)], check=True)
        body['frames'].append(dict(at=at, image='data:image/jpeg;base64,' + base64.b64encode(frame.read_bytes()).decode()))
    VideoCreative(None).prepare(body)
    dump(out / 'input.json', body)
    dump(out / 'media-result.json', dict(original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
         upload_sha256=hashlib.sha256(video.read_bytes()).hexdigest(), duration=duration,
         bytes=video.stat().st_size, extracted_audio=audio, transcription=False, frames=5))
    print('Actual public video decoded, audio availability recorded, five actual frames prepared', flush=True)


def generate(args, out):
    data = out / 'app-data'
    data.mkdir(exist_ok=False)
    process, origin = launch(args.exe.resolve(), data)
    dump(out / 'session-origin.json', dict(origin=origin))
    try:
        posts = load(out / 'posts.json')
        imported = request(origin, '/api/import', {'posts': posts, 'keyword': 'R01官方公开样本技术验收'})
        assert imported['count'] == len(posts)
        # Local, unconfirmed test strategy only; actual Agent workspace is untouched.
        request(origin, '/api/strategy/save', {'expected_version': 0, 'data': {
            'direction': '公开样本结构复盘技术验收；非真实账号策略',
            'audience': '经营受众未确认', 'resources': '文档公开样本，不包含用户私有资料'}})
        media = request(origin, '/api/agent/media', (out / 'R01-public-sample.mp4').read_bytes())
        body = load(out / 'input.json')
        task = request(origin, '/api/agent/task/save', {'input': body, 'media_id': media['media_id'], 'expected_version': 0})
        dump(out / 'task-before.json', task)
        prepared, frames = VideoCreative(None).prepare(body)
        prepared['account_context'] = {k: task[k] for k in ('account', 'strategy')}
        content = [dict(type='text', text=json.dumps(prepared, ensure_ascii=False))]
        for i, frame in enumerate(frames):
            content.extend([dict(type='text', text='frame={}，采样时间={:.2f}秒'.format(i+1, frame['at'])),
                            dict(type='image_url', image_url=dict(url=frame['image']))])
        payload = dict(model='deepseek-flash', stream=False, max_tokens=6000, thinking={'type': 'disabled'},
                       response_format={'type': 'json_object'}, messages=[
                       dict(role='system', content=task['rules']['text']), dict(role='user', content=content)])
        dump(out / 'request-frozen.json', payload)
        tokens = len(task['rules']['text'].encode()) + sum(len(c['text'].encode()) for c in content if c['type']=='text') + 4096 + len(frames) * 1024
        ceiling = (tokens * .30 + 6000 * 1.20) / 1_000_000 * 10
        assert ceiling < 1
        budget = dict(max_cny=1, max_requests=1, retries=False, input_token_bound=tokens,
                      output_token_limit=6000, usd_to_cny_safety_factor=10, estimated_cny_ceiling=ceiling,
                      pricing_source='https://api-docs.deepseek.com/quick_start/pricing/')
        dump(out / 'deepseek-budget.json', budget)
        key = key_from(args.deepseek_key, 'deepseek')
        assert request(origin, '/api/ai/config', {'endpoint':'https://api.deepseek.com', 'model':'deepseek-flash', 'key':key})['connected']
        # TikHub retries do not grant another model invocation. All sample runs
        # share the original DeepSeek authorization and its single durable claim.
        claim(out, 'deepseek', dict(media_run_id=args.run_id,
              request_sha256=hashlib.sha256((out/'request-frozen.json').read_bytes()).hexdigest(),
              **budget), 'R01-20261027')
        try:
            generated = request(origin, '/api/agent/task/generate', {'task_uid':task['task_uid'], 'expected_version':1, 'confirm':True})
            dump(out / 'generation-result.json', generated)
            assert generated['version'] == 2 and generated['result']
        finally:
            request(origin, '/api/ai/config', {'endpoint':'https://api.deepseek.com', 'model':'deepseek-flash', 'clear_key':True})
        close_cleanly(process, origin, data)
        process, origin = launch(args.exe.resolve(), data)
        reopened = request(origin, '/api/agent/task?id=' + task['task_uid'])
        dump(out / 'task-reopened.json', reopened)
        assert reopened['result'] == generated['result']
        assert request(origin, '/api/agent/task?id=' + task['task_uid'] + '&version=1')['result'] is None
        dump(out / 'generation-check.json', dict(model_requests=1, retries=0, saved_version=2,
             exe_reopen_matches=True, historical_v1_without_result=True, normal_exits=2))
        print('Packaged app generation saved; actual EXE exit/restart and version history match', flush=True)
    finally:
        if process.poll() is None:
            close_cleanly(process, origin, data)
        for db in data.glob('*.sqlite3'):
            with sqlite3.connect(db) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agent_task_attempt'").fetchone():
                    continue
                attempts = conn.execute('SELECT status,raw_response,validation_json FROM agent_task_attempt').fetchall()
                evidence = dict(attempt_count=len(attempts), statuses=[r[0] for r in attempts])
                for status, raw, validation in attempts:
                    if raw:
                        response = json.loads(raw)
                        usage = response.get('usage', {})
                        evidence['usage'] = usage
                        evidence['peak_cny_estimate'] = (usage.get('prompt_tokens',0)*.30 + usage.get('completion_tokens',0)*1.20)/1_000_000*10
                        dump(out / 'response-raw.json', response)
                dump(out / 'model-attempts.json', evidence)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['fetch', 'prepare', 'generate'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--ffmpeg', type=Path)
    parser.add_argument('--tikhub-key', type=Path)
    parser.add_argument('--deepseek-key', type=Path)
    parser.add_argument('--execute-authorized-once', action='store_true')
    parser.add_argument('--run-id', choices=['R01-20261027', 'R02-20261027', 'R03-20261027'], default='R01-20261027')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.stage in ('fetch', 'generate') and not args.execute_authorized_once:
        raise ValueError('Live calls require explicit single-call opt-in')
    globals()[args.stage](args, out)


if __name__ == '__main__':
    main()
