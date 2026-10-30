"""Build an ad-hoc signed Apple Silicon test app and DMG on native macOS only."""
import argparse
from datetime import date
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import struct
import subprocess
import sys

from build_desktop import collect_inputs, sha256
from build_release import OPS_FILES

ROOT = Path(__file__).resolve().parent
NAME = 'ice运营台'


def require_native_mac():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise ValueError('必须在原生 Apple Silicon macOS 环境构建；Windows 不可交叉生成 Mac 安装包')


def mac_inputs(root):
    rows = collect_inputs(root)
    for name in ('build_macos.py', 'packaging/requirements-macos.txt', 'packaging/macOS-使用说明.md'):
        rows.append(dict(file=name, sha256=sha256(root / name)))
    return rows


def create_icon(staging):
    raw = (ROOT / 'radar.ico').read_bytes()
    images = []
    for index in range(struct.unpack_from('<H', raw, 4)[0]):
        width, height, _, _, _, _, size, offset = struct.unpack_from('<BBBBHHII', raw, 6 + 16 * index)
        if raw[offset:offset + 8] == b'\x89PNG\r\n\x1a\n':
            images.append(((width or 256) * (height or 256), raw[offset:offset + size]))
    if not images:
        raise ValueError('原图标没有可用的 PNG 图层')
    source = staging / 'icon-source.png'
    source.write_bytes(max(images, key=lambda row: row[0])[1])
    iconset = staging / 'radar.iconset'
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            output = iconset / ('icon_%dx%d%s.png' % (size, size, '@2x' if scale == 2 else ''))
            subprocess.run(['/usr/bin/sips', '-z', str(size * scale), str(size * scale), str(source), '--out', str(output)], check=True, stdout=subprocess.DEVNULL)
    icon = staging / 'radar.icns'
    subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(icon)], check=True)
    return icon


def build(output, version):
    require_native_mac()
    if not re.fullmatch(r'20\d{2}\.\d{1,2}\.\d{1,2}\.\d{1,2}', version):
        raise ValueError('版本须为 YYYY.MM.DD.N')
    year, month, day, revision = map(int, version.split('.'))
    date(year, month, day)
    if revision < 1:
        raise ValueError('版本修订号须为 1 到 99')
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('构建输出必须在源码目录之外')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise ValueError('只允许从干净提交构建')
    inputs = mac_inputs(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    staging = output / 'staging'
    staging.mkdir()
    provenance = dict(platform='macOS', architecture='arm64', version=version,
                      source_commit=commit, source_dirty=False, files=inputs,
                      signing='ad-hoc', notarized=False)
    (staging / 'BUILD-INPUTS.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    licenses = staging / 'licenses'
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            source = Path(distribution.locate_file(file))
            if file.name.lower().startswith(('license', 'copying', 'notice')) and source.is_file():
                destination = licenses / distribution.metadata.get('Name', 'unknown') / file.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    info = dict(CFBundleDisplayName=NAME, CFBundleShortVersionString='%d.%d.%d' % (year, month, day),
                CFBundleVersion='%d.%d.%d' % ((year % 100) * 100 + month, day, revision), LSMinimumSystemVersion='14.0',
                NSHighResolutionCapable=True, NSRequiresAquaSystemAppearance=False,
                NSAppTransportSecurity={'NSAllowsLocalNetworking': True})
    icon = create_icon(staging)
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--windowed', '--name', NAME,
               '--distpath', str(output / 'dist'), '--workpath', str(output / 'work'),
               '--specpath', str(output / 'spec'), '--target-architecture', 'arm64',
               '--osx-bundle-identifier', 'io.iceops.desktop', '--codesign-identity', '-',
               '--icon', str(icon), '--hidden-import', 'webview.platforms.cocoa',
               '--hidden-import', 'keyring.backends.macOS', '--collect-submodules', 'keyring.backends.macOS',
               '--exclude-module', 'webview.platforms.edgechromium', '--exclude-module', 'webview.platforms.winforms',
               '--exclude-module', 'webview.platforms.qt', '--exclude-module', 'webview.platforms.gtk',
               '--exclude-module', 'webview.platforms.cef']
    # Only listed workflow files are added, never the developer's data or workspace.
    data = [(ROOT / 'static', 'static'), (ROOT / 'catalog.json', '.'),
            (ROOT / '_runtime/codex-rejected-cas.pem', '.'),
            (ROOT / '_runtime/account-workspace-template.json', '_runtime'),
            (staging / 'BUILD-INPUTS.json', '.'), (licenses, 'licenses'),
            (ROOT / 'packaging/macOS-使用说明.md', '.')]
    data += [(ROOT / '_ops' / name, str(Path('_ops') / Path(name).parent)) for name in OPS_FILES]
    for source, destination in data:
        command += ['--add-data', str(source) + ':' + destination]
    command.append(str(ROOT / 'desktop.py'))
    subprocess.run(command, check=True, cwd=ROOT, env=dict(os.environ, MACOSX_DEPLOYMENT_TARGET='14.0'))
    bundle = output / 'dist' / (NAME + '.app')
    # Set Info.plist before the final ad-hoc signature, then keep the bundle immutable.
    plist = bundle / 'Contents/Info.plist'
    with plist.open('rb') as stream:
        bundled_info = plistlib.load(stream)
    bundled_info.update(info)
    with plist.open('wb') as stream:
        plistlib.dump(bundled_info, stream)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    architecture = subprocess.check_output(['/usr/bin/lipo', '-archs', str(bundle / 'Contents/MacOS' / NAME)], text=True).strip()
    if architecture != 'arm64' or mac_inputs(ROOT) != inputs:
        raise ValueError('构建架构或构建输入发生变化')
    manifest = ['%s  %s' % (sha256(path), path.relative_to(bundle).as_posix())
                for path in sorted(bundle.rglob('*')) if path.is_file()]
    (output / 'MANIFEST.sha256').write_text('\n'.join(manifest) + '\n', encoding='utf-8')
    image_root = output / 'image'
    image_root.mkdir()
    subprocess.run(['/usr/bin/ditto', str(bundle), str(image_root / bundle.name)], check=True)
    (image_root / 'Applications').symlink_to('/Applications', target_is_directory=True)
    shutil.copy2(ROOT / 'packaging/macOS-使用说明.md', image_root / '使用说明.md')
    dmg = output / ('ICE-' + version + '-macOS-arm64.dmg')
    subprocess.run(['/usr/bin/hdiutil', 'create', '-volname', NAME, '-srcfolder', str(image_root),
                    '-format', 'UDZO', str(dmg)], check=True)
    subprocess.run(['/usr/bin/hdiutil', 'verify', str(dmg)], check=True)
    receipt = dict(provenance, bundle=str(bundle), dmg=str(dmg), dmg_sha256=sha256(dmg),
                   native_acceptance='pending', dependencies={d.metadata['Name']: d.version for d in importlib.metadata.distributions()})
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(bundle=str(bundle), dmg=str(dmg), source_commit=commit), ensure_ascii=False))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.output, args.version)
