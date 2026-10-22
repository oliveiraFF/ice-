"""Evidence-based sampled-video analysis. No credentials or media are persisted."""
import base64
import binascii
import json
import math
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from ai_directions import NoRedirect, request_completion

MAX_VIDEO_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 5 * 1024 * 1024
RULES = (Path(__file__).resolve().parent / 'static' / 'creative-rules.txt').read_text(encoding='utf-8')
OUTPUTS = ('shooting', 'video_prompt', 'writing_prompt')
DIMENSIONS = ('目标人群','需求场景','开头设计','核心卖点','卖点证明','内容结构','视听表达','互动动机','商品说服力','改编可行性')


def text(value, name, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError('{}{}，最多{}字'.format('请填写' if required else '请检查', name, limit))
    return value.strip()


def request_transcription(endpoint, key, model, media, mime):
    boundary = 'Radar' + secrets.token_hex(16)
    extension = 'mp4' if mime == 'video/mp4' else 'webm'
    body = ('--{0}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{1}\r\n'
            '--{0}\r\nContent-Disposition: form-data; name="file"; filename="reference.{2}"\r\n'
            'Content-Type: {3}\r\n\r\n').format(boundary, model, extension, mime).encode() + media
    body += ('\r\n--' + boundary + '--\r\n').encode()
    headers = {'Content-Type':'multipart/form-data; boundary='+boundary,'Accept':'application/json'}
    if key: headers['Authorization'] = 'Bearer ' + key
    try:
        with build_opener(NoRedirect()).open(Request(endpoint, body, headers), timeout=90) as response:
            raw = response.read(262145)
            if len(raw) > 262144: raise ValueError('转写响应过大；不会自动重试')
            result = json.loads(raw.decode('utf-8'))
            return text(result.get('text'), '转写结果', 30000, True)
    except HTTPError as exc:
        raise ValueError('口播转写服务返回 HTTP {}，请核对转写模型与服务支持情况；不会自动重试'.format(exc.code)) from None
    except (URLError, OSError):
        raise ValueError('口播转写连接失败或超时，可能已计费；不会自动重试') from None
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        raise ValueError('口播转写响应格式无效；不会自动重试') from None


class VideoCreative:
    dimensions = DIMENSIONS

    def __init__(self, ai):
        self.ai = ai

    def connection(self):
        config = self.ai.config()
        if not config['endpoint'] or not config['model'] or not self.ai.key and not config['local']:
            raise ValueError('请先配置支持图片输入的模型地址、模型名及密钥；重启后需重新填写密钥')
        return config

    def transcribe(self, media, mime, model, confirmed):
        if confirmed is not True: raise ValueError('请先确认发送视频用于口播转写')
        if (not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,149}',model)):
            raise ValueError('请填写有效的转写模型标识（英文、数字及._:/-）')
        valid = mime == 'video/mp4' and media[4:8] == b'ftyp' or mime == 'video/webm' and media[:4] == b'\x1aE\xdf\xa3'
        if not valid or not 12 <= len(media) <= MAX_VIDEO_BYTES:
            raise ValueError('请选择20MB以内的MP4或WebM视频')
        with self.ai.lock:
            config = self.connection()
            endpoint = config['endpoint'][:-len('/chat/completions')] + '/audio/transcriptions'
            return dict(text=request_transcription(endpoint,self.ai.key,model,media,mime), source='transcription')

    def prepare(self, body):
        if body.get('confirmed') is not True: raise ValueError('请先确认发送范围及模型调用')
        duration=body.get('duration')
        if type(duration) not in (int,float) or not math.isfinite(duration) or not 0 < duration <= 180:
            raise ValueError('参考视频需在3分钟以内')
        outputs=body.get('outputs')
        if (not isinstance(outputs,list) or not outputs or any(k not in OUTPUTS for k in outputs)
                or len(set(outputs)) != len(outputs)):
            raise ValueError('请至少选择一类成果，且不要重复选择')
        seconds=body.get('target_seconds')
        if type(seconds) is not int or not 10 <= seconds <= 180: raise ValueError('目标时长需为10至180秒整数')
        data = {key:text(body.get(key,''),name,limit,required) for key,name,limit,required in (
            ('product','商品名称',150,True),('audience','目标人群',500,True),('facts','真实卖点',3000,True),
            ('conditions','拍摄条件',1500,False),('details','补充资料',3000,False),('transcript','参考视频台词',30000,False))}
        choices = {'goal':('吸引观看','解释商品','展示卖点','回答购买顾虑','引导进一步了解'),
                   'format':('口播讲解','实测演示','前后对比','场景故事','问答解惑'),
                   'style':('自然分享','专业讲解','简洁直接','轻松有趣'),
                   'reference':('借鉴整体结构','只借鉴开头','只借鉴证明方式')}
        for key,values in choices.items():
            if body.get(key) not in values: raise ValueError('请检查创作选项')
            data[key]=body[key]
        frames=body.get('frames')
        if not isinstance(frames,list) or not 1 <= len(frames) <= 16: raise ValueError('需提供1至16张本机提取的关键画面')
        cleaned=[]; previous=-1
        for frame in frames:
            if not isinstance(frame,dict): raise ValueError('关键画面格式无效')
            at,image=frame.get('at'),frame.get('image')
            if type(at) not in (int,float) or not math.isfinite(at) or not 0 <= at <= duration or at <= previous:
                raise ValueError('关键画面时间必须递增且位于视频时长内')
            if not isinstance(image,str) or not image.startswith('data:image/jpeg;base64,') or len(image)>280000:
                raise ValueError('关键画面必须为200KB以内的本机JPEG图片')
            try: raw=base64.b64decode(image.split(',',1)[1],validate=True)
            except (ValueError,binascii.Error): raise ValueError('关键画面编码无效') from None
            if not raw.startswith(b'\xff\xd8') or not raw.endswith(b'\xff\xd9') or len(raw)>204800:
                raise ValueError('关键画面不是有效的JPEG数据')
            cleaned.append(dict(at=at,image=image)); previous=at
        data.update(duration=duration,outputs=outputs,target_seconds=seconds,
                    frames=[dict(frame=i+1,at=f['at']) for i,f in enumerate(cleaned)],
                    audio='转写文字（非音轨听觉分析）' if data['transcript'] else '未读取音轨')
        return data,cleaned

    def validate(self, report, count, outputs):
        if not isinstance(report,dict): raise ValueError()
        report['summary']=text(report.get('summary'),'分析摘要',6000,True)
        observations=report.get('observations')
        if not isinstance(observations,list) or not 1 <= len(observations) <= 24: raise ValueError()
        for row in observations:
            if type(row.get('frame')) is not int or not 1 <= row['frame'] <= count: raise ValueError()
            for key in ('evidence','inference','advice'): row[key]=text(row.get(key),key,3000,True)
        evaluations=report.get('evaluations')
        if not isinstance(evaluations,list) or len(evaluations)!=len(DIMENSIONS): raise ValueError()
        seen=[]
        for row in evaluations:
            seen.append(row.get('dimension')); refs=row.get('frames')
            if row.get('verdict') not in ('明确','部分具备','缺失','无法判断'): raise ValueError()
            if (not isinstance(refs,list) or any(type(i) is not int or not 1 <= i <= count for i in refs)
                    or row['verdict']!='无法判断' and not refs): raise ValueError()
            row['reason']=text(row.get('reason'),'评价依据',3000,True)
        if sorted(seen)!=sorted(DIMENSIONS): raise ValueError()
        def lines(value):
            if not isinstance(value,list) or len(value)>40: raise ValueError()
            return [text(v,'说明',2000,True) for v in value]
        adaptation=report.get('adaptation')
        report['adaptation']={key:lines(adaptation[key]) for key in ('reuse','adjust','avoid')}
        report['missing']=lines(report.get('missing'))
        deliverables=report.get('deliverables')
        if not isinstance(deliverables,dict) or set(deliverables)!=set(outputs): raise ValueError()
        report['deliverables']={key:text(deliverables[key],'生成成果',40000,True) for key in outputs}
        return {key:report[key] for key in ('summary','observations','evaluations','adaptation','missing','deliverables')}

    def generate(self, body):
        data,frames=self.prepare(body)
        with self.ai.lock:
            config=self.connection()
            content=[dict(type='text',text=json.dumps(data,ensure_ascii=False))]
            for i,frame in enumerate(frames):
                content.extend([dict(type='text',text='frame={}，采样时间={:.2f}秒'.format(i+1,frame['at'])),
                                dict(type='image_url',image_url=dict(url=frame['image']))])
            payload=dict(model=config['model'],stream=False,messages=[dict(role='system',content=RULES),dict(role='user',content=content)])
            try: response=request_completion(config['endpoint'],self.ai.key,payload)
            except ValueError as exc: raise ValueError(str(exc).replace('分类','视频分析')) from None
        try:
            raw=response['choices'][0]['message']['content']
            if not isinstance(raw,str): raise ValueError()
            raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip())
            report=self.validate(json.loads(raw),len(frames),data['outputs'])
        except (ValueError,TypeError,KeyError,IndexError,AttributeError):
            raise ValueError('模型结果缺少所选成果、分析维度或有效证据，未采用；请求可能已计费，不会自动重试') from None
        writing = report['deliverables'].get('writing_prompt','')
        if any(phrase in writing for phrase in ('你要做的是可复用的写稿指令','不是一次性成稿')):
            raise ValueError('写稿提示词包含让下游再次生成提示词的冲突指令，未采用；请求可能已计费，不会自动重试')
        return dict(version='creative-v1.1',model=config['model'],report=report,
                    scope=dict(duration=data['duration'],frames=data['frames'],audio=data['audio'],
                               limitation='仅分析采样画面与已提供文字，无法验证完整动作、音轨或真实传播和成交效果'))
