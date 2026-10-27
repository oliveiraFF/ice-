"""T01: export an allowlisted owner source bundle without private working data."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

RADAR = Path(__file__).resolve().parent
OPS = Path('D:/自媒体运营/project')
BUILD_ROOT = Path('E:/leida-build/fusion-owner')
RADAR_MODULES = (
    'app.py', 'agent_bridge.py', 'catalog.py', 'free_tools.py', 'browser_collector.py', 'demo.py',
    'ai_directions.py', 'video_creative.py', 'agent_tasks.py', 'local_asr.py', 'ops.py', 'customer_api.py', 'client_credentials.py',
    'topics.py', 'reviews.py',
)
OPS_FILES = (
    'fixtures/sample_facts.json',
    'fixtures/sample_posts.json',
    'skills/__init__.py',
    'skills/script_writing.py',
    'skills/topic_discovery.py',
    'tools/__init__.py',
    'tools/facts.py',
    'tools/fetch_douyin.py',
    'tools/llm_call.py',
    'tools/llm_script.py',
    'tools/run_log.py',
    'workflows/__init__.py',
    'workflows/conversion_observation.py',
    'workflows/draft_optimization.py',
    'workflows/industry_templates.py',
    'workflows/keyword_to_topics.py',
    'workflows/media_review.py',
    'workflows/ops_advice.py',
    'workflows/ops_reminders.py',
    'workflows/research.py',
    'workflows/research_draft.py',
    'workflows/topic_to_script.py',
)
ASSET_SUFFIXES = {'.html', '.css', '.js', '.json', '.svg', '.txt', '.md', '.zip', '.ttf', '.jpg', '.ico'}


def sha256(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(output=BUILD_ROOT, build_id=None, radar=RADAR, ops=OPS):
    radar, ops, output = Path(radar).resolve(), Path(ops).resolve(), Path(output).resolve()
    build_id = build_id or (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', build_id):
        raise ValueError('build_id must be a simple directory name')
    target = output / build_id
    archive_path = output / ('radar-owner-' + build_id + '.zip')
    for source in (radar, ops):
        if target == source or source in target.parents:
            raise ValueError('release output must be outside source directories')
    if target.exists() or archive_path.exists():
        raise FileExistsError('refusing to overwrite an existing release: ' + str(target))

    copies = [(radar / name, name, 'radar') for name in RADAR_MODULES]
    copies.extend((radar / name, name, 'radar') for name in ('catalog.json', 'radar.ico'))
    for path in sorted((radar / 'static').rglob('*')):
        if path.is_file():
            if path.suffix.lower() not in ASSET_SUFFIXES or path.name.startswith('.'):
                raise ValueError('unlisted static asset: ' + str(path.relative_to(radar)))
            copies.append((path, path.relative_to(radar).as_posix(), 'radar'))
    copies.extend((ops / name, '_ops/' + name, 'ops') for name in OPS_FILES)
    copies.extend((radar / name, name, 'radar') for name in ('使用说明.txt', 'M05-使用说明.md'))
    for source, _, _ in copies:
        if not source.is_file():
            raise FileNotFoundError('required release input is missing: ' + str(source))
    commit = subprocess.check_output(
        ['git', '-C', str(ops), 'rev-parse', 'HEAD'], universal_newlines=True).strip()
    dirty = bool(subprocess.check_output(
        ['git', '-C', str(ops), 'status', '--porcelain'], universal_newlines=True).strip())

    target.mkdir(parents=True, exist_ok=False)
    source_files = []
    for source, relative, owner in copies:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(destination))
        source_files.append({'file': relative, 'source': owner, 'sha256': sha256(destination)})
    (target / 'data').mkdir()
    provenance = {
        'build_id': build_id, 'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'edition': 'owner-source', 'python_built_with': sys.version.split()[0],
        'radar_source': str(radar), 'ops_source': str(ops), 'ops_commit': commit,
        'ops_worktree_dirty': dirty, 'files': source_files,
        'excluded': ['.env and credentials', 'working databases', 'logs', 'downloads',
                     'browser profiles', 'backups', 'trial material', 'tests and build helpers'],
    }
    (target / 'SOURCE.json').write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / 'release.marker').write_text(
        json.dumps({'mode': 'release', 'build_id': build_id}), encoding='utf-8')
    (target / '启动.bat').write_bytes(
        b'@echo off\r\ncd /d "%~dp0"\r\npython app.py --port 8765 --open-browser\r\npause\r\n')
    (target / 'README-内测说明.md').write_text(
        '# ice运营台 owner 源码内测包\n\n'
        '- 请使用 Python 3.12；本次验证的精确版本见外部交付报告。'
        '使用标准库，以浏览器运行，不是免安装 exe，也不是桌面壳分发包。\n'
        '- 双击 启动.bat；或用 Python 执行本目录 app.py。默认端口 8765；'
        '占用时可指定 --port 其他端口。服务只接受本机访问。\n'
        '- /、/tools、/creative、/dashboard、/script 保留；使用说明以页面能力为准。\n'
        '- 当前窗口按 Ctrl+C 停止服务，停止后再备份。'
        '运行数据在 data/，视频缓存下载在 downloads/，浏览器导出由用户选择保存位置。'
        '不要在程序写入时直接复制正在运行的数据库。\n'
        '- 发布包从 _ops 加载工作流，不需要开发机 D/E 盘目录。'
        '不要设置指向其他项目的 OPS_PROJECT_ROOT；此变量仅供开发时显式覆盖。\n'
        '- 新 data/ 不含私人数据库。应用自带的 demo 与用户导入的 live 数据隔离；'
        '脚本页默认用雷达 live 作品，无匹配会阻断；示例模式需要主动选择。\n'
        '- 模型设置中填写服务地址、模型名和密钥；密钥只在内存，重启需重填。'
        '包不读取或携带开发机 .env。测试模式不调用模型。\n'
        '- 真实模型需要已有 owner 付费许可、服务进程 LLM_ALLOW_PAID=1 和页面本次确认；'
        '保存模型配置不发送请求。不自动重试。当前包的验证没有付费请求。\n'
        '- 运营工作台、运营建议、研究稿、成片审阅与咨询记录已在本包提供；已保存的建议/稿件/审阅记录重启后保留，未保存的表单需及时导出。\n'
        '- 列表/详情只返回范围元数据与摘要，不回传采样图；历史记录恢复文字与关联版本，不恢复原视频。\n'
        '- 真实模型调用需服务进程 LLM_ALLOW_PAID=1 的独立付费许可；页面本次确认不能替代，软件不会自动开启。\n'
        '- MANIFEST.sha256 校验分发文件（不含清单自身）；SOURCE.json 记录源码来源。'
        '运行后产生的数据不属于原分发清单。customer/免安装包尚未在本批验收。\n',
        encoding='utf-8')
    manifest = ['%s  %s' % (sha256(p), p.relative_to(target).as_posix())
                for p in sorted(target.rglob('*')) if p.is_file()]
    (target / 'MANIFEST.sha256').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    with zipfile.ZipFile(str(archive_path), 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.write(str(target / 'data'), 'data/')
        for path in sorted(target.rglob('*')):
            if path.is_file():
                archive.write(str(path), path.relative_to(target).as_posix())
    (output / (archive_path.name + '.sha256')).write_text(
        sha256(archive_path) + '  ' + archive_path.name + '\n', encoding='utf-8')
    return {'directory': str(target), 'zip': str(archive_path),
            'zip_sha256': sha256(archive_path), 'files': len(manifest) + 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BUILD_ROOT)
    parser.add_argument('--ops-root', type=Path, default=OPS)
    parser.add_argument('--build-id')
    args = parser.parse_args()
    print(json.dumps(build_snapshot(args.output, args.build_id, ops=args.ops_root),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

