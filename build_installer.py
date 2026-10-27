"""Build a per-user Windows installer from a verified, data-free desktop release."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT=Path(__file__).resolve().parent


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_release(release):
    release=Path(release).resolve()
    source=json.loads((release/'SOURCE.json').read_text('utf-8'))
    if source.get('edition')!='owner-exe' or source.get('source_dirty') is not False or not re.fullmatch('[a-f0-9]{40}',source.get('source_commit','')):
        raise ValueError('安装源必须是干净提交构建的 owner-exe')
    files=[]
    for line in (release/'MANIFEST.sha256').read_text('utf-8').splitlines():
        checksum,name=line.split('  ',1)
        relative=PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name
                or any(c in name for c in '\r\n\x00$"') or name in files
                or not re.fullmatch('[a-f0-9]{64}',checksum)):
            raise ValueError('安装源清单路径或哈希无效')
        path=release.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(release) or not path.is_file() or sha256(path)!=checksum:
            raise ValueError('安装源文件缺失、越界或被修改')
        parts=[p.lower() for p in relative.parts]
        if (parts[0] in ('data','downloads','workspace','backups','agent-loop')
                or path.suffix.lower() in ('.sqlite3','.sqlite','.db','.key')
                or path.name.lower().startswith('.env') or '密钥' in name):
            raise ValueError('安装源含用户数据或凭据文件，拒绝打包')
        files.append(name)
    files.append('MANIFEST.sha256')
    actual={p.relative_to(release).as_posix() for p in release.rglob('*') if p.is_file()}
    if actual!=set(files) or 'ice运营台.exe' not in files:
        raise ValueError('安装源含清单以外的文件或缺少主程序')
    return sorted(files)


def quote(value):
    return '"'+str(value).replace('$','$$').replace('"','$\\"')+'"'


def payload_scripts(release,files):
    install=[];uninstall=[];directories=set()
    for name in files:
        relative=PurePosixPath(name)
        folder=relative.parent.as_posix().replace('/','\\')
        destination='$INSTDIR'+('\\'+folder if folder!='.' else '')
        install.extend(['SetOutPath "'+destination+'"','File '+quote(Path(release).joinpath(*relative.parts))])
        uninstall.append('Delete "$INSTDIR\\'+name.replace('/','\\')+'"')
        for parent in relative.parents:
            if parent.as_posix()!='.':directories.add(parent.as_posix())
    # Only empty directories are removed. No wildcard or recursive user-data deletion.
    uninstall.extend('RMDir "$INSTDIR\\'+d.replace('/','\\')+'"' for d in sorted(directories,key=lambda d:(-d.count('/'),d)))
    return '\n'.join(install)+'\n','\n'.join(uninstall)+'\n'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--compiler',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--version',default='2026.10.27.1');args=parser.parse_args()
    if not re.fullmatch(r'\d{1,5}(\.\d{1,5}){3}',args.version) or any(int(n)>65535 for n in args.version.split('.')):
        raise ValueError('版本号须为四段Windows数字版本')
    if args.output.exists():raise ValueError('输出已存在，拒绝覆盖')
    files=validate_release(args.release)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    staging=args.output.with_suffix('.build');staging.mkdir(exist_ok=False)
    install,uninstall=payload_scripts(args.release,files)
    (staging/'payload-install.nsh').write_text(install,encoding='utf-8-sig')
    (staging/'payload-uninstall.nsh').write_text(uninstall,encoding='utf-8-sig')
    source=json.loads((args.release/'SOURCE.json').read_text('utf-8'))
    compiler_version=subprocess.check_output([str(args.compiler),'/VERSION'],encoding='utf-8').strip()
    subprocess.run([str(args.compiler),'/INPUTCHARSET','UTF8','/DPAYLOAD_INCLUDE='+str(staging.resolve()),
        '/DOUTPUT_FILE='+str(args.output.resolve()),'/DAPP_VERSION='+args.version,
        '/DPROJECT_ICON='+str(ROOT/'radar.ico'),str(ROOT/'packaging/windows-installer.nsi')],check=True)
    if validate_release(args.release)!=files:raise ValueError('编译期间安装源变化')
    receipt=dict(installer=str(args.output.resolve()),sha256=sha256(args.output),version=args.version,
        source_commit=source['source_commit'],source_files=len(files),compiler=compiler_version,
        installer_source_commit=subprocess.check_output(['git','rev-parse','HEAD'],encoding='utf-8').strip(),
        installer_source_dirty=bool(subprocess.check_output(['git','status','--porcelain']).strip()),
        per_user=True,uninstall_preserves_data=True,contains_user_workspace_or_test_database=False)
    args.output.with_suffix('.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
