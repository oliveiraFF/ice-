"""Explicit, resumable TEST-only operations loop. Never writes a formal workspace."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid

from ai_directions import request_completion
from reviews import build_review


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic publication; cannot overwrite an existing version/claim.
    finally:
        temporary.unlink(missing_ok=True)


class AgentLoop:
    def __init__(self, data_dir, ops, ai, test_enabled=False):
        self.data = Path(data_dir).resolve()
        self.root = self.data / 'agent-loop'
        self.ops, self.ai, self.enabled = ops, ai, test_enabled
        self.lock = threading.RLock()

    def workspace(self):
        if not self.enabled:
            raise ValueError('隔离测试未开启；正式 workspace 不允许写入')
        config = json.loads((self.data/'agent-workspace.json').read_text('utf-8'))
        workspace = Path(config.get('workspace_path', '')).resolve()
        if not workspace.is_relative_to(self.data) or workspace == self.data:
            raise ValueError('测试 workspace 必须在本实例数据目录内')
        marker = workspace/'ice-test-scope.json'
        if not marker.is_file() or json.loads(marker.read_text('utf-8')).get('test_only') is not True:
            raise ValueError('缺少隔离测试标记，不会修改正式 workspace')
        return workspace

    def profiles(self):
        workspace = self.workspace()
        manifest = json.loads((workspace/'project.manifest.json').read_text('utf-8'))
        profiles = {}
        for name in ('account_profile','audience_profile','offer_profile','strategy_brief'):
            relative = manifest.get('current', {}).get(name)
            if not isinstance(relative, str):
                raise ValueError('manifest 缺少 '+name)
            path = (workspace/relative).resolve()
            if not path.is_relative_to(workspace):
                raise ValueError('manifest 路径超出测试 workspace')
            value = json.loads(path.read_text('utf-8'))
            if (value.get('confirmed_by_user') is not True or not value.get('confirmed_at')
                    or not value.get('confirmation_quote')):
                raise ValueError(name+' 尚未确认测试用途')
            profiles[name] = dict(path=relative, sha256=digest(value), data=value)
        return profiles

    def folder(self, uid):
        if not isinstance(uid, str) or not re.fullmatch('[a-f0-9]{12}', uid):
            raise ValueError('运行编号无效')
        return self.root/'runs'/uid

    def get(self, uid, version=None):
        folder = self.folder(uid)
        files = sorted(folder.glob('v*.json'))
        if not files:
            raise ValueError('运行不存在')
        file = folder/('v%06d.json' % int(version)) if version else files[-1]
        if not file.is_file():
            raise ValueError('版本不存在')
        return json.loads(file.read_text('utf-8'))

    def listing(self):
        if not self.enabled:
            return dict(enabled=False, runs=[])
        runs = [self.get(p.name) for p in (self.root/'runs').glob('*') if p.is_dir()]
        return dict(enabled=True, runs=sorted(runs, key=lambda x:x['updated_at'], reverse=True))

    def save(self, run, action):
        workspace = self.workspace()
        run['version'] += 1
        run['updated_at'] = now()
        run.setdefault('events', []).append(dict(action=action, at=run['updated_at'], version=run['version']))
        name = 'v%06d.json' % run['version']
        # The app checkpoint is authoritative. The workspace receives an exact artifact copy.
        write_new(self.folder(run['run_uid'])/name, run)
        write_new(workspace/'runs'/run['run_uid']/'outputs'/name, run)
        return run

    def current(self, uid, expected):
        run = self.get(uid)
        if expected != run['version']:
            raise ValueError('运行版本已改变，请刷新后继续')
        if run['strategy']['version'] != digest(self.profiles()):
            raise ValueError('账号资料或策略已改变；请建立新测试运行')
        return run

    def create(self, body):
        with self.lock:
            profiles = self.profiles()
            if body.get('confirm_test') is not True:
                raise ValueError('请确认仅运行隔离测试')
            run = dict(run_uid=uuid.uuid4().hex[:12], version=0, test_only=True,
                       title=str(body.get('title') or 'Agent 隔离流程')[:100], created_at=now(),
                       rule_version='ice-test-loop-v1', strategy=dict(version=digest(profiles), profiles=profiles),
                       status='created', quality='awaiting_user_review')
            return self.save(run, 'create')

    def diagnose(self, uid, expected):
        with self.lock:
            run = self.current(uid, expected)
            profiles = run['strategy']['profiles']
            run['diagnosis'] = dict(rule_version='profile-only-v1', sample_threshold=None,
                profile_findings=[dict(source=p['path'], sha256=p['sha256'], facts=p['data']) for p in profiles.values()],
                performance_conclusions=[], missing=[dict(kind='作品表现', current=0, required=None,
                    reason='未配置表现类门槛，且没有经确认的作品指标',
                    next_action='先确定门槛；实际发布后补作品链接、日期、同口径指标和来源')])
            run['status'] = 'diagnosed_with_gaps'
            return self.save(run, 'diagnose')

    def select(self, uid, expected, body):
        with self.lock:
            run = self.current(uid, expected)
            if not run.get('diagnosis'):
                raise ValueError('请先完成账号资料诊断')
            if body.get('role') != 'market_task':
                raise ValueError('本轮只接受任务型原始证据，不把对标热度当需求')
            for key in ('title','source_url','excerpt','observed_at'):
                if not isinstance(body.get(key), str) or not body[key].strip():
                    raise ValueError('选题缺少 '+key)
            if not body['source_url'].startswith('https://') or len(encoded(body))>8000:
                raise ValueError('选题证据格式无效')
            if run.get('reference'):
                raise ValueError('已有对标请求，不可改选题；请新建运行')
            run['topic'] = dict(title=body['title'][:200], strategy_version=run['strategy']['version'],
                selected_at=now(), scope='单选题技术测试；不代表正式日计划2+1验收',
                evidence={k:body[k] for k in ('role','source_url','excerpt','observed_at')})
            run['status'] = 'topic_selected'
            return self.save(run, 'select')

    def claim(self, provider, stage, uid, cny, details):
        with self.lock:
            self.root.mkdir(parents=True,exist_ok=True)
            lockfile=self.root/'budget.lock'
            try:
                descriptor=os.open(lockfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            except FileExistsError:
                raise ValueError('预算账本正被占用；中断遗留锁需人工核验，未发起请求') from None
            try:
                return self._claim(provider,stage,uid,cny,details)
            finally:
                os.close(descriptor);lockfile.unlink()

    def _claim(self, provider, stage, uid, cny, details):
            self.workspace(); self.folder(uid)
            auth = json.loads((self.data/'agent-loop-authorization.json').read_text('utf-8'))
            limit = auth.get('providers', {}).get(provider, {})
            cap = min(float(limit.get('max_cny',0)), 1.0)
            count = min(int(limit.get('max_requests',0)), 1 if provider=='tikhub' else 2)
            if provider not in ('tikhub','deepseek') or stage not in (
                    ('fetch',) if provider=='tikhub' else ('reference','creation')):
                raise ValueError('未授权的请求类型')
            if not isinstance(cny,(int,float)) or not math.isfinite(cny) or not 0<cny<=cap:
                raise ValueError('请求费用超出授权上限')
            auth_id = str(auth.get('authorization_id') or '')
            if not auth_id:
                raise ValueError('缺少本机授权编号')
            folder = self.root/'claims'/hashlib.sha256(auth_id.encode()).hexdigest()[:20]
            claims = [json.loads(p.read_text('utf-8')) for p in folder.glob(provider+'-*.json')]
            if len(claims)>=count or sum(c['reserved_cny'] for c in claims)+cny>cap:
                raise ValueError('本轮次数或预留预算已用完；不会自动重试或释放预算')
            path = folder/(provider+'-'+stage+'-'+uid+'.json')
            if path.exists():
                raise ValueError('此步骤已请求过；不会自动重试')
            receipt = dict(authorization_id=auth_id,provider=provider,stage=stage,run_uid=uid,
                           reserved_cny=cny, at=now(), retry=False, details=details)
            write_new(path, receipt)
            return receipt

    def fetch(self, uid, expected, body, callback):
        with self.lock:
            run = self.current(uid, expected)
            video_id = str(body.get('video_id') or '')
            if not run.get('topic') or not re.fullmatch(r'\d{15,22}', video_id):
                raise ValueError('请先选题并填写公开抖音作品ID')
            if run.get('reference'):
                raise ValueError('对标步骤已有记录，不自动重试')
            receipt = self.claim('tikhub','fetch',uid,1,dict(video_id=video_id))
            run['reference'] = dict(video_id=video_id, status='requested', receipt=receipt)
            self.save(run, 'fetch_requested')
            try:
                run['reference'].update(callback(video_id), status='fetched',
                    scope='仅标题和描述；未观看画面、未核验教程现行有效性')
                run['status'] = 'reference_fetched'
            except Exception:
                run['reference']['status']='result_unconfirmed'
                run['status']='reference_failed_no_retry'
            return self.save(run, 'fetch_finished')

    def model(self, uid, expected, stage):
        with self.lock:
            run = self.current(uid, expected)
            if stage not in ('reference','creation'):
                raise ValueError('模型步骤无效')
            if run.get(stage+'_attempt'):
                raise ValueError('此步骤已请求过，不自动重试')
            if run.get('reference',{}).get('status')!='fetched':
                raise ValueError('缺少真实抓取的对标资料')
            if stage=='creation' and not run.get('reference_analysis'):
                raise ValueError('请先完成参考资料分析')
            config = self.ai.snapshot()
            if config['endpoint']!='https://api.deepseek.com/chat/completions' or config['model']!='deepseek-flash' or not config['key']:
                raise ValueError('本轮只授权已配置密钥的 DeepSeek Flash 官方服务')
            context = dict(test_only=True, strategy=run['strategy'], topic=run['topic'],
                reference=run['reference'], reference_analysis=run.get('reference_analysis'))
            instruction = ('你是短视频运营助手。只用输入中已证实的资料，不编造个人经历、指标、免费承诺或视频画面。'
                '参考资料只有标题描述，不能推断具体镜头、节奏或效果。面向个人创作者，录屏配音不露脸，积累作品暂不变现。'
                '不是电商，不按成交、产品化或变现潜力选题。只返回JSON。')
            schema = ('返回 {"patterns":[{"pattern":"可借鉴的标题表达","basis":"对应标题原文"}],'
                      '"limitations":["未看画面等限制"]}；只分析可直接观察的标题表达。') if stage=='reference' else (
                '围绕已选题写一条60秒以内的录屏教程草稿。用户尚未亲自拍摄，操作用待拍指令，不得说已经实测成功。'
                '先呈现建议拍摄的结果，再讲关键步骤及如何验证；资料未支持的操作必须标待核验。口播短句。'
                '返回 {"title":"标题","beats":[{"beat":"钩子/问题/证明/承接",'
                '"text":"口播","shot":"逐镜录屏动作与待拍证据","seconds":5}],'
                '"video_prompt":"AI视频辅助画面提示词；教程界面必须来自实际录屏，不能伪造UI与结果",'
                '"missing":["拍摄与人工校对待完成"]}。4到12镜，总时长不超过60秒。')
            payload = dict(model=config['model'],max_tokens=4000,messages=[
                dict(role='system',content=instruction+schema),dict(role='user',content=encoded(context).decode())])
            # Peak/cache-miss prices, UTF-8 bytes + 1024 as conservative input-token bound, FX safety factor 10.
            reserved = ((len(encoded(payload))+1024)*.30 + 4000*1.20)/1000000*10
            receipt = self.claim('deepseek',stage,uid,reserved,dict(payload_sha256=digest(payload),
                max_tokens=4000,input_token_bound=len(encoded(payload))+1024, usd_to_cny=10,
                price_source='https://api-docs.deepseek.com/quick_start/pricing/'))
            run[stage+'_attempt']=dict(status='requested',receipt=receipt)
            self.save(run, stage+'_requested')
            raw_path=self.folder(uid)/(stage+'-response.json')
            def sink(raw):
                raw=raw.replace(config['key'].encode(),b'[REDACTED]')
                raw_path.write_bytes(raw)
            try:
                response=request_completion(config['endpoint'],config['key'],payload,response_sink=sink)
                text=response['choices'][0]['message']['content']
                value=json.loads(text.strip().removeprefix('```json').removesuffix('```').strip())
                if stage=='reference':
                    if not isinstance(value.get('patterns'),list) or not isinstance(value.get('limitations'),list):
                        raise ValueError('参考分析结构无效')
                    run['reference_analysis']=value
                else:
                    self.validate_script(value)
                    run['creation']=value
                run[stage+'_attempt'].update(status='validated',usage=response.get('usage'),raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
                run['status']=stage+'_ready'
            except Exception:
                run[stage+'_attempt']['status']='result_unconfirmed'
                run['status']=stage+'_failed_no_retry'
            return self.save(run, stage+'_finished')

    @staticmethod
    def validate_script(value):
        beats=value.get('beats')
        if not isinstance(beats,list) or not 4<=len(beats)<=12:
            raise ValueError('分镜数量无效')
        for beat in beats:
            if not all(isinstance(beat.get(k),str) and beat[k].strip() for k in ('beat','text','shot')):
                raise ValueError('分镜缺少口播或录屏动作')
            if type(beat.get('seconds')) not in (int,float) or not 0<beat['seconds']<=60:
                raise ValueError('分镜时长无效')
        if sum(b['seconds'] for b in beats)>60 or not isinstance(value.get('video_prompt'),str) or not value['video_prompt'].strip():
            raise ValueError('缺少提示词或总时长超限')

    def handoff(self, uid, expected):
        with self.lock:
            run=self.current(uid,expected)
            if not run.get('creation'):
                raise ValueError('没有已验证的创作结果')
            with closing(self.ops.connect()) as db:
                row=db.execute("SELECT task_uid FROM content_task WHERE source='agent_loop' AND run_id=?",(uid,)).fetchone()
            if row:
                task=self.ops.get_content_task(row['task_uid'])
            else:
                task=self.ops.create_content_task(dict(product=run['topic']['title'],audience='AI短视频个人创作者',
                    model_beats=[dict(beat=b['beat'],text=b['text'],fact_ids=[]) for b in run['creation']['beats']],
                    source='agent_loop',run_id=uid,data_source='agent_test',model='deepseek-flash',model_mode='real',formal=False,
                    usage=run.get('creation_attempt',{}).get('usage',{}),
                    references=[run['topic']['evidence'],run['reference']],missing=run['creation'].get('missing',[]),
                    plan=dict(test_only=True,strategy=run['strategy'],topic=run['topic'],creation=run['creation'],run_uid=uid,
                        topic_snapshot=dict(topic=run['topic']['title']),
                        duration_seconds=sum(b['seconds'] for b in run['creation']['beats']),
                        shots=[str(b['seconds'])+'秒 · '+b['shot'] for b in run['creation']['beats']],
                        video_prompt=run['creation']['video_prompt'],
                        proof='实际录屏与人工校对待完成；参考资料仅标题描述',
                        next_action='完成拍摄与人工评审；本稿不得登记为真实发布')))
            run['content_task']=dict(task_uid=task['task']['task_uid'],version=task['task']['current_version'],formal=False)
            run['status']='draft_saved'
            return self.save(run,'handoff')

    def feedback(self, uid, expected, body):
        with self.lock:
            run=self.current(uid,expected)
            if not run.get('content_task'):
                raise ValueError('请先保存创作稿')
            feedback=run.setdefault('feedback',{})
            if body.get('simulated') is True:
                if body.get('confirm_simulated') is not True:
                    raise ValueError('请确认合成数据仅用于演练')
                metrics=body.get('metrics',{})
                if not metrics or any(k not in ('plays','likes','comments','favorites','inquiries') or type(v)!=int or not 0<=v<=1000000 for k,v in metrics.items()):
                    raise ValueError('演练指标必须是已知非负整数')
                feedback['simulation']=dict(simulated=True,source='explicit_synthetic',collected_at=now(),
                    definition='合成累计指标，仅测试机制',metrics=metrics)
            else:
                if body.get('metrics') or body.get('platform_post_id'):
                    raise ValueError('本轮未实际发布，不可填写真实经营指标')
                feedback['actual']=dict(published=False,source='user_test_scenario',metrics=None,
                    missing=['实际作品链接与发布时间','同口径指标、采集时间与来源'])
            run['status']='feedback_saved'
            return self.save(run,'feedback')

    def review(self, uid, expected):
        with self.lock:
            run=self.current(uid,expected)
            feedback=run.get('feedback',{})
            if 'actual' not in feedback:
                raise ValueError('请先登记未发布状态')
            run['review']=dict(actual=build_review({},[]),test_only=True,
                next_action='完成真实拍摄与人工审核，实际发布后再登记指标；当前不推断账号效果')
            if feedback.get('simulation'):
                run['review']['simulation']=dict(build_review({},[feedback['simulation']]),simulated=True,
                    scope='仅隔离演练，不进入正式复盘表或策略变更')
            run['status']='test_loop_complete'
            return self.save(run,'review')
