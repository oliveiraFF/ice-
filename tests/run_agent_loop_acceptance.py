"""Prepare an isolated, explicitly authorized test scenario. Never imports private profiles."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FORMAL=Path('E:/deepseek工作区/short-video-ops-data/my-account')
TEMPLATE=Path('E:/deepseek工作区/short-video-ops-kit/templates/project-workspace')


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--verify-formal',action='store_true');args=parser.parse_args()
    if args.verify_formal:
        original=json.loads((args.output/'formal-before.json').read_text('utf-8'))
        assert hashes(FORMAL)==original,'Formal workspace changed'
        dump(args.output/'formal-unchanged.json',{'unchanged':True,'files':len(original)})
        print('Formal workspace hashes unchanged:',len(original));return
    args.output.mkdir(parents=True,exist_ok=False)
    dump(args.output/'formal-before.json',hashes(FORMAL))
    data=args.output/'data';workspace=data/'workspace'
    shutil.copytree(TEMPLATE,workspace)
    manifest=json.loads((workspace/'project.manifest.json').read_text('utf-8'))
    manifest['project_id']='ice-isolated-ai-creator-test'
    dump(workspace/'project.manifest.json',manifest)
    common=dict(test_only=True,confirmed_by_user=True,confirmed_at='2026-10-27T00:00:00Z',
        confirmation_quote='用户确认：仅在独立测试 workspace 和数据库中实跑，不写入正式账号')
    data_by_name={
        'account_profile':dict(account_id='isolated-test-account',platform='douyin',industry='AI视频创作',
            positioning='AI视频创作实测：建议先展示成片，再分享所用工具和关键做法',
            production='边学边做，录屏配音、不露脸',content_boundaries=['不编造实测经历、效果或免费承诺','暂不按变现与产品化潜力选题']),
        'audience_profile':dict(audience_id='personal-creators-test',name='想用AI做短视频的个人创作者',
            audiences=[dict(id='personal-creators-test',name='想用AI做短视频的个人创作者')]),
        'offer_profile':dict(offers=[],monetization='暂不设置变现',resources=['本地录屏','配音','离线字幕能力；结果需人工校对']),
        'strategy_brief':dict(strategy_id='isolated-ai-video-test-v1',status='confirmed',
            stage_goal='积累作品并稳定更新；频率与投入时间待补',target_audience_ids=['personal-creators-test'],
            priority_pain_ids=[],primary_strategy='先展示AI成片，再分享工具、关键步骤与可验证的测试结果',
            dashboard_direction='AI视频创作测试',content_pillars=['AI视频成片','制作过程','工具校验'],
            source_policy=dict(user_data_first=True,reference_content_role='structure_only',allow_generic_tutorials=False),
            conversion_path='暂无变现目标',avoid=['未经实际测试的第一人称效果宣称','将对标表现当作自有表现'])}
    for name,value in data_by_name.items():dump(workspace/manifest['current'][name],dict(value,**common))
    dump(workspace/'ice-test-scope.json',dict(common,scope='本机隔离测试；不是正式账号配置'))
    dump(data/'agent-workspace.json',dict(workspace_path=str(workspace)))
    dump(data/'agent-loop-authorization.json',dict(authorization_id='agent-loop-20261027-approved-2cny',
        providers=dict(tikhub=dict(max_requests=1,max_cny=1),deepseek=dict(max_requests=2,max_cny=1)),
        retry=False,scope='仅本轮用户明确授权；旧账本不改动'))
    print(str(data))


if __name__=='__main__':main()
