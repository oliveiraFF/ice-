import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_loop import AgentLoop
from ops import OpsStore, ensure_tables
from app import Store
from ai_directions import AIDirections


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Store(self.root/'radar.sqlite3')
        self.ops = OpsStore(self.root/'radar.sqlite3')
        self.ai = AIDirections(self.root/'radar.sqlite3')
        self.loop = AgentLoop(self.root,self.ops,self.ai,test_enabled=True)
        workspace=self.root/'workspace';workspace.mkdir()
        self.workspace=workspace
        self.write(workspace/'ice-test-scope.json',{'test_only':True})
        files={k:'config/'+k+'.json' for k in ['account_profile','audience_profile','offer_profile','strategy_brief']}
        self.write(workspace/'project.manifest.json',{'current':files})
        for key,path in files.items():
            self.write(workspace/path,{'confirmed_by_user':True,'confirmed_at':'2026-10-27T00:00:00Z','confirmation_quote':'用户明确批准仅用于隔离测试','status':'confirmed','positioning':'AI视频实测','audience':'个人创作者','primary_strategy':'录屏配音，不露脸','stage_goal':'积累作品，暂不变现'})
        self.write(self.root/'agent-workspace.json',{'workspace_path':str(workspace)})

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')

    def create(self):
        return self.loop.create({'title':'隔离流程测试','confirm_test':True})

    def test_formal_workspace_and_unconfirmed_profile_are_never_writable(self):
        (self.workspace/'ice-test-scope.json').unlink()
        with self.assertRaises(ValueError):self.create()
        self.write(self.workspace/'ice-test-scope.json',{'test_only':True})
        self.write(self.workspace/'config/account_profile.json',{'confirmed_by_user':False})
        with self.assertRaises(ValueError):self.create()

    def test_diagnosis_does_not_invent_account_metrics_and_selection_keeps_evidence(self):
        run=self.create()
        run=self.loop.diagnose(run['run_uid'],run['version'])
        self.assertEqual(run['diagnosis']['performance_conclusions'],[])
        self.assertTrue(run['diagnosis']['missing'])
        run=self.loop.select(run['run_uid'],run['version'],{'title':'自动字幕怎样校对','role':'market_task','source_url':'https://support.google.com/youtube/answer/6373554','excerpt':'官方说明需要检查自动字幕','observed_at':'2026-10-27'})
        self.assertEqual(run['topic']['strategy_version'],run['strategy']['version'])
        self.assertEqual(run['topic']['evidence']['role'],'market_task')
        with self.assertRaises(ValueError):self.loop.select(run['run_uid'],0,{})

    def test_cumulative_authorization_rejects_replay_and_extra_calls(self):
        self.write(self.root/'agent-loop-authorization.json',{'authorization_id':'offline-unit','providers':{'deepseek':{'max_requests':2,'max_cny':1}}})
        self.loop.claim('deepseek','reference','a'*12,.1,{'hash':'x'})
        with self.assertRaises(ValueError):self.loop.claim('deepseek','reference','a'*12,.1,{})
        self.loop.claim('deepseek','creation','a'*12,.1,{})
        with self.assertRaises(ValueError):self.loop.claim('deepseek','creation','b'*12,.1,{})

    def test_source_paths_cannot_escape_workspace(self):
        self.write(self.workspace/'project.manifest.json',{'current':{'account_profile':'../outside.json'}})
        with self.assertRaises(ValueError):self.create()

    def test_handoff_is_idempotent_and_simulation_never_enters_formal_feedback(self):
        run=self.create()
        run['topic']={'title':'字幕校对','evidence':{'role':'market_task'}}
        run['reference']={'title':'真实标题范围的单元测试占位'}
        run['creation']={'beats':[{'beat':str(i),'text':'待拍测试','shot':'录屏','seconds':5} for i in range(4)],'video_prompt':'待拍'}
        run=self.loop.save(run,'unit_fixture')
        run=self.loop.handoff(run['run_uid'],run['version'])
        task_uid=run['content_task']['task_uid']
        run=self.loop.handoff(run['run_uid'],run['version'])
        self.assertEqual(run['content_task']['task_uid'],task_uid)
        self.ops.approve_content_task(task_uid,1)
        with self.assertRaisesRegex(ValueError,'不能登记为真实发布'):
            self.ops.save_publish_record(task_uid,1,'dy','7063277801121615112',
                'https://www.douyin.com/video/7063277801121615112','2026-10-27T00:00:00Z')
        run=self.loop.feedback(run['run_uid'],run['version'],{})
        run=self.loop.feedback(run['run_uid'],run['version'],{'simulated':True,'confirm_simulated':True,'metrics':{'plays':100,'comments':2}})
        run=self.loop.review(run['run_uid'],run['version'])
        self.assertEqual(run['review']['actual']['status'],'insufficient')
        self.assertTrue(run['review']['simulation']['simulated'])
        reopened=AgentLoop(self.root,self.ops,self.ai,test_enabled=True).get(run['run_uid'])
        self.assertEqual(reopened,run)
        self.assertEqual(self.loop.get(run['run_uid'],1)['status'],'created')
        with closing(self.ops.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM review_record').fetchone()[0],0)

    def test_no_automatic_retry_after_fetch_failure_or_restart(self):
        self.write(self.root/'agent-loop-authorization.json',{'authorization_id':'failure-test','providers':{'tikhub':{'max_requests':1,'max_cny':1}}})
        run=self.create();run['topic']={'title':'字幕校对'};run=self.loop.save(run,'unit_fixture')
        calls=[]
        def fail(video_id):
            calls.append(video_id);raise TimeoutError()
        run=self.loop.fetch(run['run_uid'],run['version'],{'video_id':'7063277801121615112'},fail)
        self.assertEqual(run['status'],'reference_failed_no_retry')
        restarted=AgentLoop(self.root,self.ops,self.ai,test_enabled=True)
        with self.assertRaises(ValueError):restarted.fetch(run['run_uid'],run['version'],{'video_id':'7063277801121615112'},fail)
        self.assertEqual(len(calls),1)

    def test_interrupted_checkpoint_keeps_last_complete_version_readable(self):
        run=self.create()
        with patch('agent_loop.os.link',side_effect=OSError('injected interruption')):
            with self.assertRaises(OSError):self.loop.save(run,'interrupted')
        reopened=AgentLoop(self.root,self.ops,self.ai,test_enabled=True)
        self.assertEqual(reopened.get(run['run_uid'])['version'],1)
        self.assertEqual(len(reopened.listing()['runs']),1)
        self.assertEqual(list(self.loop.folder(run['run_uid']).glob('*.tmp')),[])

    def test_second_instance_cannot_claim_while_budget_is_locked(self):
        self.loop.root.mkdir(parents=True)
        (self.loop.root/'budget.lock').write_text('interrupted or another process')
        other=AgentLoop(self.root,self.ops,self.ai,test_enabled=True)
        with self.assertRaisesRegex(ValueError,'账本正被占用'):
            other.claim('deepseek','creation','a'*12,.1,{})
