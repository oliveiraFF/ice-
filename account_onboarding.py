"""Local account setup from a bundled neutral template; no network or credential storage."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
import subprocess
import sys
from pathlib import Path
import re
import threading
import uuid
import zipfile

from agent_bridge import read_workspace_config, save_workspace_config

TEMPLATE=Path(__file__).resolve().parent/'_runtime/account-workspace-template.json'


def packed(value):
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(packed(value));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def load(path):
    return json.loads(path.read_text('utf-8'))


class AccountOnboarding:
    def __init__(self,data_dir,ops,secrets_provider=lambda:(),environment_workspace=''):
        self.data=Path(data_dir).resolve();self.ops=ops;self.secrets_provider=secrets_provider
        self.lock=threading.RLock();self.journal=self.data/'account-initialization.json'
        self.environment_workspace=environment_workspace

    def bound(self):
        if self.environment_workspace:return Path(self.environment_workspace).resolve()
        path,error=read_workspace_config(self.data)
        if error:raise ValueError('账号连接配置不可读，请先在高级设置检查；不会覆盖原配置')
        return Path(path).resolve() if path else None

    def managed(self,root):
        if not root:return None
        root=root.resolve()
        if not root.is_relative_to(self.data/'workspaces') or not re.fullmatch('[a-f0-9]{32}',root.name):return None
        marker=root/'ice-account.json'
        if not marker.is_file():return None
        value=load(marker)
        if value.get('account_uid')!=root.name or value.get('owner')!='ice-account-onboarding-v1':return None
        with closing(self.ops.connect()) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_local_account'").fetchone()
            local=db.execute('SELECT account_uid FROM agent_local_account WHERE id=1').fetchone() if exists else None
        current_uid=local['account_uid'] if local else (load(self.journal).get('account_uid') if self.journal.is_file() else None)
        return value if current_uid==root.name else None

    def state(self):
        with self.lock:
            root=self.bound();record=self.ops.get_strategy()
            has_strategy=bool(record['version'] or record.get('data') or record.get('confirmed') or record.get('updated_at'))
            marker=self.managed(root)
            if marker and has_strategy:
                error=self.sync_strategy()
                return dict(kind='managed',can_create=False,account_uid=marker['account_uid'],
                    account=dict(marker['input'],**{k:record['data'].get(k,'') for k in ('direction','audience','resources','goal')}),workspace_path=str(root),strategy_version=record['version'],
                    strategy_confirmed=bool(record['confirmed']),sync_error=error)
            if root and not marker:return dict(kind='external',can_create=False,message='已连接已有资料目录（只读），原有策略未被替换。')
            if self.journal.is_file():
                pending=load(self.journal)
                if not has_strategy:
                    return dict(kind='pending',can_create=True,input=pending['input'],request_id=pending['request_id'])
            if has_strategy:return dict(kind='legacy',can_create=False,message='已有账号策略，请继续完善；可在高级设置连接原资料目录。')
            return dict(kind='new',can_create=True)

    @staticmethod
    def inputs(body):
        if not re.fullmatch('[a-f0-9]{32}',str(body.get('request_id') or '')):raise ValueError('创建请求已失效，请刷新页面')
        result={}
        for key,label,maximum in [('name','账号名称',100),('direction','内容方向',300),('audience','目标人群',300),
                                  ('platform','平台',60),('resources','制作条件',500),('goal','阶段目标',300)]:
            value=body.get(key,'')
            if not isinstance(value,str) or len(value)>maximum or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):raise ValueError(label+'格式或长度不合适')
            value=value.strip()
            if key in ('name','direction','audience') and not value:raise ValueError('请填写'+label)
            if re.search(r'sk-[A-Za-z0-9_-]{16,}',value) or re.fullmatch(r'[A-Za-z0-9_./+=-]{40,500}',value):
                raise ValueError('账号资料中请勿填写密钥，请到数据源或模型设置保存')
            result[key]=value
        return result

    @staticmethod
    def validate(root):
        manifest=load(root/'project.manifest.json');contract=load(root/'data.contract.json');policy=load(root/'workspace.policy.json')
        if manifest['project_id']!=contract['workspace_id'] or manifest['operating_mode']!=policy['mode']:raise ValueError('工作区标识或策略模式不一致')
        for section in ('current','workflow_manifests'):
            if not isinstance(manifest.get(section),dict) or not manifest[section]:raise ValueError('工作区配置不完整')
            for relative in manifest[section].values():
                path=(root/relative).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('工作区配置缺失或路径越界')
                load(path)
        for name in ('account_profile','audience_profile','offer_profile','strategy_brief'):
            if name not in manifest['current']:raise ValueError('账号资料模板不完整')
        return manifest

    def create(self,body):
        with self.lock,closing(self.ops.connect()) as db:
            if self.environment_workspace:raise ValueError('开发环境指定了资料目录，请先使用现有连接；不会覆盖')
            values=self.inputs(body);request_id=body['request_id'];uid=request_id
            account_table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_local_account'").fetchone()
            if account_table:
                account=db.execute('SELECT account_uid FROM agent_local_account WHERE id=1').fetchone()
                if account:uid=account['account_uid']
            if not re.fullmatch('[a-f0-9]{32}',uid):raise ValueError('本机账号标识异常，请先备份并检查')
            root=self.data/'workspaces'/uid
            if self.journal.is_file():
                pending=load(self.journal)
                if pending['account_uid']!=uid or pending['request_id']!=request_id or pending['input']!=values:raise ValueError('已有账号或未完成的创建，请继续原账号；不会覆盖资料')
            bound=self.bound();current=self.ops.get_strategy()
            if bound==root and self.managed(root) and current['version']:return self.state()
            if bound and bound!=root:raise ValueError('已有资料目录，创建不会替换现有连接')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM account_profile WHERE id=1').fetchone():
                saved=load(self.journal) if self.journal.is_file() else {}
                if saved.get('request_id')==request_id and saved.get('input')==values and self.bound()==root and self.managed(root):return self.state()
                raise ValueError('已有账号策略，创建不会覆盖原资料')
            created=datetime.now(timezone.utc).isoformat()
            if not self.journal.exists():write_json(self.journal,dict(account_uid=uid,request_id=request_id,input=values,created_at=created))
            old_config=(self.data/'agent-workspace.json').read_bytes() if (self.data/'agent-workspace.json').exists() else None
            try:
                if not root.exists():
                    template=load(TEMPLATE);staging=root.with_name('.'+uid+'-'+uuid.uuid4().hex)
                    staging.mkdir(parents=True)
                    for relative,text in template['files'].items():
                        path=(staging/relative).resolve()
                        if not path.is_relative_to(staging.resolve()):raise ValueError('模板路径越界')
                        path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_text(text.replace('__ACCOUNT_ID__',uid).replace('__INIT_DATE__',created[:10]).replace('__INIT_AT__',created),encoding='utf-8',newline='\n')
                    for relative in template['directories']:
                        path=(staging/relative).resolve()
                        if not path.is_relative_to(staging.resolve()):raise ValueError('模板目录越界')
                        path.mkdir(parents=True,exist_ok=True)
                    write_json(staging/'ice-account.json',dict(owner='ice-account-onboarding-v1',account_uid=uid,input=values,created_at=created))
                    self.validate(staging);os.rename(staging,root)
                marker=self.managed(root)
                if not marker or marker['input']!=values:raise ValueError('目标资料已存在且内容不同，不覆盖')
                draft=dict(direction=values['direction'],audience=values['audience'],resources=values['resources'],goal=values['goal'],
                           principles='',exclusions='',takeover='',experiment_allowed=False)
                # Participate in this transaction so a binding failure rolls the draft back too.
                self.ops.save_strategy(draft,'账号初始化:'+uid,0,database=db)
                if account_table:db.execute('UPDATE agent_local_account SET label=? WHERE id=1',(values['name'],))
                self.sync_strategy(root=root,record=dict(data=draft,version=1,confirmed=0),strict=True)
                save_workspace_config(self.data,root)
                db.commit()
            except Exception:
                db.rollback()
                config=self.data/'agent-workspace.json'
                if old_config is None:config.unlink(missing_ok=True)
                else:write_json(config,json.loads(old_config))
                raise
            return self.state()

    def ensure_confirmable(self):
        try:root=self.bound()
        except (OSError,ValueError):return  # Existing local strategy editing does not require a workspace.
        if not self.managed(root):return
        data=self.ops.get_strategy()['data']
        missing=[label for key,label in [('direction','账号方向'),('audience','受众'),('resources','真实资源 / 证明'),('goal','阶段目标')]
                 if not str(data.get(key) or '').strip()]
        if missing:raise ValueError('正式策略还缺：'+'、'.join(missing)+'；请补充并保存草稿')

    def sync_strategy(self,root=None,record=None,strict=False):
        with self.lock:
            try:
                root=root or self.bound();marker=self.managed(root)
                if not marker:return ''
                record=record or self.ops.get_strategy();data=record['data'];uid=marker['account_uid']
                confirmed=bool(record['confirmed']);tag='v%s-%s-%s'%(record['version'],int(confirmed),hashlib.sha256(packed(data)).hexdigest()[:12])
                prefix='config/ice/'+tag+'/'
                prior=root/prefix/'strategy_brief.json'
                confirmed_at=(load(prior).get('confirmed_at') if prior.exists() else datetime.now(timezone.utc).isoformat()) if confirmed else ''
                stamp=dict(status='confirmed' if confirmed else 'draft',confirmed_by_user=confirmed,
                    source_type='direct_user_confirmation' if confirmed else 'unconfirmed_intake',
                    positioning_source_type='direct_user_confirmation' if confirmed else 'unconfirmed_intake',
                    positioning_source_ref=prefix+'strategy_brief.json',confirmation_quote='用户在账号策略页确认以上内容' if confirmed else '',
                    confirmed_at=confirmed_at,sqlite_strategy_version=record['version'])
                profiles=dict(
                    account_profile=dict(account_id=uid,account_name=marker['input']['name'],platform=marker['input']['platform'],
                        platform_identity_status='unverified',industry='',positioning=data.get('direction',''),resources=data.get('resources',''),**stamp),
                    audience_profile=dict(audience=data.get('audience',''),primary_audiences=[dict(audience_id='audience-'+uid,label=data.get('audience',''))],disqualified_audiences=[],**stamp),
                    offer_profile=dict(offer_name='',offer_type='',resources=data.get('resources',''),conversion_paths=[data['takeover']] if data.get('takeover') else [],service_boundaries=[],**stamp),
                    strategy_brief=dict(strategy_id='strategy-'+uid,stage_goal=data.get('goal',''),target_audience_ids=['audience-'+uid],priority_pain_ids=[],
                        primary_strategy=data.get('direction',''),content_pillars=[],scoring_weights={},source_policy=dict(user_data_first=True,reference_content_role='structure_only',allow_generic_tutorials=False),
                        avoid=[data['exclusions']] if data.get('exclusions') else [],content_principles=data.get('principles',''),conversion_path=data.get('takeover',''),**stamp))
                manifest=self.validate(root);changed=False
                for key,value in profiles.items():
                    relative=prefix+key+'.json';path=root/relative
                    if path.exists() and load(path)!=value:raise ValueError('资料版本在软件外被修改，请保留备份后检查')
                    if not path.exists():write_json(path,value)
                    if manifest['current'][key]!=relative:manifest['current'][key]=relative;changed=True
                if changed:write_json(root/'project.manifest.json',manifest)
                return ''
            except (OSError,ValueError,KeyError) as exc:
                if strict:raise
                return '账号策略已保存在软件中，资料目录同步未完成：'+type(exc).__name__+'；请检查目录权限后刷新重试'

    def backup(self):
        with self.lock:
            root=self.bound()
            if not self.managed(root):raise ValueError('此入口只备份软件创建的账号资料；已有外部目录请用原备份方式')
            error=self.sync_strategy()
            if error:raise ValueError(error)
            buffer=BytesIO();total=0;count=0
            secrets=[str(s).encode() for s in self.secrets_provider() if s]
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(root.rglob('*')):
                    if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('资料含外部链接，未生成备份')
                    if not path.is_file():continue
                    name=path.relative_to(root).as_posix();normalized=re.sub('[^a-z]','',path.name.lower())
                    if any(part in normalized for part in ('apikey','credential','password','accesstoken')) or path.name.startswith('.env'):
                        raise ValueError('资料目录中含凭据文件，请将密钥移到设置后再备份')
                    total+=path.stat().st_size;count+=1
                    if total>20*1024*1024 or count>1000:raise ValueError('资料超过本机快速备份上限，请使用文件夹备份')
                    raw=path.read_bytes()
                    if any(secret in raw for secret in secrets):raise ValueError('资料含密钥，未生成备份')
                    if path.suffix=='.json':
                        def credential(value):
                            if isinstance(value,dict):
                                return any((str(k).lower() in ('api_key','access_token','refresh_token','authorization','password','secret_key') and isinstance(v,str) and bool(v.strip())) or credential(v) for k,v in value.items())
                            if isinstance(value,list):return any(credential(v) for v in value)
                            return False
                        if credential(json.loads(raw)):raise ValueError('资料中含凭据字段，未生成备份')
                    archive.writestr(name,raw)
            return buffer.getvalue()

    def open_folder(self):
        root=self.bound()
        if not self.managed(root):raise ValueError('没有软件管理的账号资料目录')
        if sys.platform == 'darwin':
            subprocess.run(['/usr/bin/open', str(root)], check=True, timeout=10)
        else:
            os.startfile(str(root))
