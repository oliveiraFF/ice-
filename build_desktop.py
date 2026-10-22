"""Build in an isolated environment: python build_desktop.py --output E:/leida-build/releases."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
from build_release import OPS_FILES


def sha256(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    target = args.output.resolve() / time.strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--windowed', '--name', 'ice运营台',
               '--distpath', str(target), '--workpath', str(target / 'build'), '--specpath', str(target / 'spec'),
               '--icon', str(ROOT / 'radar.ico'), '--add-data', str(ROOT / 'static') + ';static',
               '--add-data', str(ROOT / 'catalog.json') + ';.', '--add-data', str(ROOT / 'radar.ico') + ';.',
               '--hidden-import', 'webview.platforms.edgechromium', '--hidden-import', 'webview.platforms.winforms',
               '--exclude-module', 'webview.platforms.qt', '--exclude-module', 'webview.platforms.gtk',
               '--exclude-module', 'webview.platforms.cef', str(ROOT / 'desktop.py')]
    subprocess.check_call(command, cwd=str(ROOT))
    release = target / 'ice运营台'
    (release / 'data').mkdir()
    ops = ROOT / '_ops'
    for name in OPS_FILES:
        source = ops / name
        if not source.is_file():
            raise FileNotFoundError('missing ops input: ' + str(source))
        destination = release / '_ops' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(destination))
    (release / 'release.marker').write_text('owner', encoding='utf-8')
    shutil.copy2(ROOT / '使用说明.txt', release / '使用说明.txt')
    licenses = release / 'licenses'
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get('Name', 'unknown')
        for file in distribution.files or []:
            if file.name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    folder = licenses / name
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(source), str(folder / file.name))
    source_identity = json.loads((ROOT / 'SOURCE.json').read_text(encoding='utf-8'))
    ops_commit, ops_dirty = source_identity.get('ops_commit', 'unknown'), source_identity.get('ops_worktree_dirty')
    shutil.copy2(ROOT / 'BUILD-INPUTS.json', release / 'BUILD-INPUTS.json')
    shutil.copy2(ROOT / 'M05-使用说明.md', release / 'M05-使用说明.md')
    provenance = {
        'edition': 'owner-exe',
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'build_id': source_identity['build_id'],
        'build_run': target.name,
        'source_zip_sha256': json.loads((ROOT / 'BUILD-INPUTS.json').read_text(encoding='utf-8'))['source_zip_sha256'],
        'build_inputs_sha256': sha256(ROOT / 'BUILD-INPUTS.json'),
        'radar_source': str(ROOT),
        'ops_source': str(ops),
        'ops_commit': ops_commit,
        'ops_worktree_dirty': ops_dirty,
        'pyinstaller': importlib.metadata.version('pyinstaller'),
        'python': sys.version.split()[0],
        'files': 'see MANIFEST.sha256',
    }
    (release / 'SOURCE.json').write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = ['%s  %s' % (sha256(item), item.relative_to(release).as_posix())
                for item in sorted(release.rglob('*'))
                if item.is_file() and item.name != 'MANIFEST.sha256']
    (release / 'MANIFEST.sha256').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    (target / 'release-path.txt').write_text(str(release), encoding='utf-8')
    (target / 'build-versions.json').write_text(json.dumps({d.metadata['Name']: d.version for d in importlib.metadata.distributions()}, indent=2), encoding='utf-8')
    print('RELEASE=' + str(release), flush=True)


if __name__ == '__main__':
    main()
