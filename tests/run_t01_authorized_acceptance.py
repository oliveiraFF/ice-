"""Explicit single paid request; synthetic schematic video, isolated packaged app data."""
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
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from PIL import Image, ImageDraw, ImageFont
from check_frozen_owner_lifecycle import launch, close_cleanly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_creative import VideoCreative


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--execute-authorized-once', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 22)
    small = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 17)
    titles = ['先核对空间', '量宽与厚，判断进入方向', '先确认材质，小范围轻刷', '按扣拆头，清水冲洗', '通风晾干，核对后再选']
    notes = ['示意图不是产品实拍', '宽20mm / 厚8mm / 柄长200mm', '不保证适合任意缝隙或表面', '不附清洁剂，不承诺消毒效果', '无销量、评价或功效证据']
    for i, title in enumerate(titles):
        im = Image.new('RGB', (432, 768), '#f3f0e8')
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 432, 75), fill='#9b342a')
        d.text((18, 20), '合成测试 · 动作示意 · 非实拍', font=font, fill='white')
        d.text((20, 115), f'{i+1}. {title}', font=font, fill='#202c35')
        d.rectangle((35, 300, 390, 410), outline='#77838b', width=4)
        d.rectangle((35, 350, 390, 365), fill='#27333c')
        x = 160 if i != 3 else 210
        d.rounded_rectangle((x, 230, x+35, 340), radius=9, fill='#419e97')
        d.rectangle((x-18, 335 if i != 3 else 390, x+53, 359 if i != 3 else 414), fill='#b7bfc1')
        if i == 1:
            d.line((110, 440, 300, 440), fill='#bd8b24', width=7)
            for t in range(110, 301, 19): d.line((t, 430, t, 450), fill='#333333', width=2)
        if i == 2:
            d.text((80, 465), '← 轻刷动作方向 →', font=font, fill='#202c35')
        if i == 3:
            for xdrop in (220, 250, 280): d.line((xdrop, 460, xdrop-10, 485), fill='#4b9bca', width=4)
        d.text((18, 550), notes[i], font=small, fill='#202c35')
        d.text((18, 640), '仅验证采样图文与保存流程', font=font, fill='#9b342a')
        d.text((18, 690), '无音轨；旁白是人工拟拍文本', font=small, fill='#202c35')
        im.save(out / f'panel{i+1}.png')
    video = out / 'T01-synthetic.mp4'
    subprocess.run([str(args.ffmpeg), '-v', 'error', '-framerate', '1/6', '-i', str(out/'panel%d.png'),
                    '-t', '30', '-r', '24', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
    subprocess.run([str(args.ffmpeg), '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
    body = json.loads((ROOT/'docs/acceptance-20261024/T01-完整模拟输入.json').read_text('utf-8'))['input_draft']
    body.update(duration=30, confirmed=True, frames=[])
    body['details'] += '参考视频是本地绘制的五段动作示意卡，不是产品实拍；无真实清洁效果、真实手部操作或音轨。只能评价示意卡，不把图示当作效果证据。'
    for i in range(5):
        frame = out/f'frame{i+1}.jpg'
        subprocess.run([str(args.ffmpeg), '-v', 'error', '-ss', str(i*6+1), '-i', str(video), '-frames:v', '1', str(frame)], check=True)
        body['frames'].append(dict(at=i*6+1, image='data:image/jpeg;base64,'+base64.b64encode(frame.read_bytes()).decode()))
    VideoCreative(None).prepare(body)
    dump(out/'input.json', body)
    data = out/'data'
    data.mkdir()
    process, origin = launch(args.exe.resolve(), data)
    def request(path, value=None):
        options = {}
        if value is not None:
            with urlopen(origin+'/api/state?mode=live', timeout=10) as r: token = json.load(r)['token']
            options = dict(data=value if isinstance(value, bytes) else json.dumps(value).encode(), headers={
                'Origin':origin, 'X-Radar-Token':token, 'Content-Type':'video/mp4' if isinstance(value,bytes) else 'application/json', 'X-Radar-Filename':'T01-synthetic.mp4'})
        try:
            with urlopen(Request(origin+path, **options), timeout=85) as r: return json.load(r)
        except HTTPError as e:
            with e: return {'http_error':e.code, 'body':json.loads(e.read())}
    result = {'external_paid_requests':0, 'synthetic_only':True, 'normal_exits':0}
    try:
        strategy = json.loads((ROOT/'docs/acceptance-20261024/T01-完整模拟输入.json').read_text('utf-8'))['strategy']['data']
        request('/api/strategy/save', {'expected_version':0, 'data':strategy})
        media = request('/api/agent/media', video.read_bytes())
        task = request('/api/agent/task/save', {'input':body, 'media_id':media['media_id'], 'expected_version':0})
        dump(out/'task-before.json', task)
        prepared, frames = VideoCreative(None).prepare(body)
        prepared['account_context'] = {k:task[k] for k in ('account','strategy')}
        content = [dict(type='text',text=json.dumps(prepared,ensure_ascii=False))]
        for i,f in enumerate(frames):
            content += [dict(type='text',text='frame={}，采样时间={:.2f}秒'.format(i+1,f['at'])),dict(type='image_url',image_url=dict(url=f['image']))]
        payload = dict(model='deepseek-flash',stream=False,max_tokens=6000,thinking={'type':'disabled'},response_format={'type':'json_object'},messages=[dict(role='system',content=task['rules']['text']),dict(role='user',content=content)])
        dump(out/'request-frozen.json', payload)
        text_bytes = len(task['rules']['text'].encode())+sum(len(c['text'].encode()) for c in content if c['type']=='text')
        bound_tokens = text_bytes+4096+5*1024
        ceiling_cny = (bound_tokens*.30+6000*1.20)/1_000_000*10
        assert ceiling_cny < 1
        budget = dict(authorized_max_cny=1,requests_allowed=1,retry=False,input_token_conservative_bound=bound_tokens,output_tokens_max=6000,usd_to_cny_safety_factor=10,estimated_cny_ceiling=ceiling_cny,pricing='peak cache-miss input $0.30/M; output $1.20/M',sources=['https://api-docs.deepseek.com/quick_start/pricing/','https://api-docs.deepseek.com/guides/vision/'])
        dump(out/'budget.json', budget)
        frozen = [video,out/'input.json',out/'request-frozen.json',out/'task-before.json',out/'budget.json']+[out/f'frame{i+1}.jpg' for i in range(5)]
        dump(out/'frozen-hashes.json', {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen})
        if args.execute_authorized_once:
            raw_key = args.key_file.read_text('utf-8-sig').strip()
            candidates = re.findall(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}', raw_key)
            if len(candidates)!=1: raise ValueError('Key file must contain exactly one recognizable key; content not displayed')
            config = request('/api/ai/config', {'endpoint':'https://api.deepseek.com','model':'deepseek-flash','key':candidates[0]})
            assert config.get('connected'), 'model credential configuration failed'
            # Exclusive durable claim is written before the only paid call; never retry it.
            with (out.parent/'T01-single-call-authorization-claimed.json').open('x',encoding='utf-8') as f:
                json.dump(dict(request_count=1,authorization='user single request <= CNY1',request_sha256=hashlib.sha256((out/'request-frozen.json').read_bytes()).hexdigest()),f)
                f.flush()
                os.fsync(f.fileno())
            result['external_paid_requests']=1
            generated = request('/api/agent/task/generate', {'task_uid':task['task_uid'],'expected_version':1,'confirm':True})
            dump(out/'generation-result.json', generated)
            result['generation_success']='result' in generated and generated.get('version')==2
            request('/api/ai/config', {'endpoint':'https://api.deepseek.com','model':'deepseek-flash','clear_key':True})
            del raw_key,candidates
        close_cleanly(process,origin,data)
        result['normal_exits']+=1
        process,origin=launch(args.exe.resolve(),data)
        reopened=request('/api/agent/task?id='+task['task_uid'])
        dump(out/'task-reopened.json',reopened)
        if args.execute_authorized_once and result['generation_success']:
            assert reopened['result']==generated['result']
            assert request('/api/agent/task?id='+task['task_uid']+'&version=1')['result'] is None
            result['reopen_matches']=True
            export='\n\n'.join(k+'\n'+v for k,v in reopened['result']['report']['deliverables'].items())
            (out/'review-deliverables.txt').write_text(export,encoding='utf-8')
        close_cleanly(process,origin,data)
        result['normal_exits']+=1
        for db in data.glob('*.sqlite3'):
            with sqlite3.connect(db) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='agent_task_attempt'").fetchone(): continue
                attempts=conn.execute('SELECT status,raw_response,validation_json FROM agent_task_attempt').fetchall()
                result['attempt_count']=len(attempts)
                for status,raw,validation in attempts:
                    result['attempt_status']=status
                    if raw:
                        (out/'response-raw.json').write_bytes(raw)
                        usage=json.loads(raw).get('usage',{})
                        result['usage']=usage
                        result['peak_cost_cny_estimate']=(usage.get('prompt_tokens',0)*.30+usage.get('completion_tokens',0)*1.20)/1_000_000*10
        dump(out/'result.json',result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        if process.poll() is None:
            try: close_cleanly(process,origin,data)
            except Exception: process.terminate();process.wait(15)


if __name__=='__main__':
    main()
