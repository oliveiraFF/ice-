from contextlib import closing
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from app import Store
from ops import OpsStore,ensure_tables
from account_onboarding import AccountOnboarding


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);Store(self.root/'radar.sqlite3')
        self.ops=OpsStore(self.root/'radar.sqlite3')
        self.service=AccountOnboarding(self.root,self.ops)
        self.body=dict(request_id='a'*32,name='客户测试账号',direction='手工制作过程',audience='手工爱好者')

    def test_create_complete_workspace_once_and_seed_unconfirmed_strategy(self):
        result=self.service.create(self.body)
        self.assertEqual(result['kind'],'managed')
        root=Path(result['workspace_path']);manifest=json.loads((root/'project.manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['project_id'],json.loads((root/'data.contract.json').read_text('utf-8'))['workspace_id'])
        for section in ('current','workflow_manifests'):
            for path in manifest[section].values():self.assertTrue((root/path).is_file(),path)
        strategy=self.ops.get_strategy();self.assertEqual(strategy['data']['direction'],self.body['direction'])
        self.assertEqual(strategy['confirmed'],0)
        self.assertEqual(self.service.create(self.body)['account_uid'],result['account_uid'])
        self.assertEqual(self.ops.get_strategy()['version'],1)
        self.assertEqual(AccountOnboarding(self.root,self.ops).state()['account_uid'],result['account_uid'])

    def test_existing_strategy_or_external_binding_are_never_overwritten(self):
        self.ops.save_strategy({'direction':'原始资料'},'legacy',0)
        with self.assertRaises(ValueError):self.service.create(self.body)
        self.assertEqual(self.ops.get_strategy()['data']['direction'],'原始资料')
        with closing(self.ops.connect()) as db:db.execute('DELETE FROM account_profile');db.commit()
        self.root.joinpath('agent-workspace.json').write_text(json.dumps({'workspace_path':str(self.root/'external')}))
        with self.assertRaises(ValueError):self.service.create(self.body)

    def test_binding_failure_rolls_back_database_and_retry_reuses_identity(self):
        with patch('account_onboarding.save_workspace_config',side_effect=OSError('injected')):
            with self.assertRaises(OSError):self.service.create(self.body)
        self.assertEqual(self.ops.get_strategy()['version'],0)
        self.assertFalse((self.root/'agent-workspace.json').exists())
        result=self.service.create(self.body)
        self.assertEqual(result['account_uid'],self.body['request_id'])
        self.assertEqual(len([p for p in (self.root/'workspaces').iterdir() if not p.name.startswith('.')]),1)

    def test_invalid_input_and_new_request_cannot_replace_current_account(self):
        for change in ({'name':' '},{'direction':'sk-'+'a'*30},{'request_id':'../bad'}):
            with self.assertRaises(ValueError):self.service.create(dict(self.body,**change))
        self.service.create(self.body)
        with self.assertRaises(ValueError):self.service.create(dict(self.body,request_id='b'*32))

    def test_existing_local_identity_is_preserved(self):
        from agent_tasks import AgentTasks
        tasks=AgentTasks(self.root/'radar.sqlite3','unit rules')
        uid=tasks.account()['account_uid']
        result=self.service.create(self.body)
        self.assertEqual(result['account_uid'],uid)
        self.assertEqual(tasks.account()['label'],self.body['name'])

    def test_two_instances_replaying_one_request_create_only_one_account(self):
        other=AccountOnboarding(self.root,self.ops)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda s:s.create(self.body),[self.service,other]))
        self.assertEqual(results[0]['account_uid'],results[1]['account_uid'])
        self.assertEqual(self.ops.get_strategy()['version'],1)

    def test_legacy_version_zero_profile_is_not_shown_as_new(self):
        self.ops.save_strategy({'direction':'旧资料'},'legacy',0)
        with closing(self.ops.connect()) as db:db.execute('UPDATE account_profile SET version=0');db.commit()
        self.assertEqual(self.service.state()['kind'],'legacy')

    def test_interrupted_binding_before_database_commit_can_resume(self):
        result=self.service.create(self.body)
        with closing(self.ops.connect()) as db:db.execute('DELETE FROM account_profile');db.commit()
        restarted=AccountOnboarding(self.root,self.ops)
        self.assertEqual(restarted.state()['kind'],'pending')
        self.assertEqual(restarted.create(self.body)['account_uid'],result['account_uid'])
        self.assertEqual(self.ops.get_strategy()['version'],1)

    def test_binding_a_different_account_uid_stays_read_only(self):
        from agent_tasks import AgentTasks
        AgentTasks(self.root/'radar.sqlite3','unit rules')
        created=self.service.create(self.body);other=self.root/'workspaces'/('b'*32)
        shutil.copytree(created['workspace_path'],other)
        marker=json.loads((other/'ice-account.json').read_text('utf-8'));marker['account_uid']='b'*32
        (other/'ice-account.json').write_text(json.dumps(marker))
        before={p.relative_to(other).as_posix():p.read_bytes() for p in other.rglob('*') if p.is_file()}
        (self.root/'agent-workspace.json').write_text(json.dumps({'workspace_path':str(other)}))
        self.assertEqual(self.service.state()['kind'],'external')
        self.ops.save_strategy({'direction':'仅改本机策略'},'unit',1);self.service.sync_strategy()
        self.assertEqual(before,{p.relative_to(other).as_posix():p.read_bytes() for p in other.rglob('*') if p.is_file()})

    def test_strategy_sync_and_backup_keep_confirmation_explicit_and_credentials_out(self):
        result=self.service.create(self.body)
        with self.assertRaises(ValueError):self.service.ensure_confirmable()
        data=dict(self.ops.get_strategy()['data'],resources='本人的制作录屏',goal='积累作品')
        self.ops.save_strategy(data,'页面填写',1);self.service.sync_strategy()
        self.service.ensure_confirmable();self.ops.confirm_strategy(2);self.service.sync_strategy()
        root=Path(result['workspace_path']);manifest=json.loads((root/'project.manifest.json').read_text('utf-8'))
        self.assertTrue(json.loads((root/manifest['current']['strategy_brief']).read_text('utf-8'))['confirmed_by_user'])
        backup=self.service.backup();self.assertTrue(backup.startswith(b'PK'))
        (root/'private-api-key.txt').write_text('secret')
        with self.assertRaises(ValueError):self.service.backup()
        (root/'private-api-key.txt').unlink()
        (root/'data/custom.json').write_text(json.dumps({'api_key':'synthetic-test-credential'}))
        with self.assertRaises(ValueError):self.service.backup()
