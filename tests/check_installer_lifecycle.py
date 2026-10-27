"""Explicit native installer acceptance in a new directory; no paid calls or real user data."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

from check_frozen_owner_lifecycle import launch, close_cleanly, request

UNINSTALL=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ICEOps'


def registry_present():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,UNINSTALL,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY):return True
    except FileNotFoundError:return False


def shell_folder(kind):
    result=ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None,kind,None,0,result):raise OSError('Shell folder lookup failed')
    return Path(result.value)


def execute(executable,args):
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    return subprocess.run([str(executable),*args],startupinfo=startup,timeout=90).returncode


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--installer',type=Path,required=True)
    parser.add_argument('--release',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    target=(args.output/'安装目录').resolve()
    assert target.is_relative_to(args.output.resolve()) and not target.exists()
    desktop=shell_folder(0x10)/'ice运营台.lnk';menu=shell_folder(2)/'ice运营台'
    assert not registry_present() and not desktop.exists() and not menu.exists(),'Existing install/shortcuts found; test refuses to overwrite'
    assert execute(args.installer,['/S','/D='+str(target)])==0
    assert registry_present() and desktop.is_file() and (menu/'ice运营台.lnk').is_file()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,UNINSTALL,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        assert winreg.QueryValueEx(key,'InstallLocation')[0]==str(target)
        assert 'UninstallICE.exe' in winreg.QueryValueEx(key,'UninstallString')[0]
    expected={p.relative_to(args.release).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in args.release.rglob('*') if p.is_file()}
    for name,checksum in expected.items():assert hashlib.sha256((target/name).read_bytes()).hexdigest()==checksum
    exe=target/'ice运营台.exe';data=target/'data';process,origin=launch(exe,data)
    try:
        assert not request(origin,'/api/state?mode=live')['connected']
        request(origin,'/api/keyword',{'name':'installer-retention-test'})
        # Actual running executable is protected; no process termination by installer/uninstaller.
        assert execute(args.installer,['/S','/D='+str(target)])==2
        assert process.poll() is None
        # _?= skips the NSIS temporary launcher, so this is the actual blocked process exit code.
        assert execute(target/'UninstallICE.exe',['/S','_?='+str(target)])==2
        assert process.poll() is None and exe.exists() and registry_present()
    finally:close_cleanly(process,origin,data)
    extra=['data/keep-user-config.json','downloads/keep-user-file.txt','workspace/keep-user-file.txt','_internal/keep-user-note.txt']
    for name in extra:
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('explicit synthetic retention sentinel',encoding='utf-8')
    preserved=['data/radar.sqlite3',*extra]
    before={name:hashlib.sha256((target/name).read_bytes()).hexdigest() for name in preserved}
    assert execute(args.installer,['/S','/D='+str(target)])==0
    for name,checksum in before.items():assert hashlib.sha256((target/name).read_bytes()).hexdigest()==checksum
    process,origin=launch(exe,data)
    try:
        state=request(origin,'/api/state?mode=live')
        assert any(k['name']=='installer-retention-test' for k in state['keywords'])
    finally:close_cleanly(process,origin,data)
    before={name:hashlib.sha256((target/name).read_bytes()).hexdigest() for name in preserved}
    assert execute(target/'UninstallICE.exe',['/S'])==0
    for _ in range(120):
        if not exe.exists() and not (target/'UninstallICE.exe').exists() and not registry_present():break
        time.sleep(.25)
    assert not exe.exists() and not (target/'UninstallICE.exe').exists() and not registry_present()
    assert not desktop.exists() and not menu.exists()
    for name in expected:assert not (target/name).exists(),name
    for name,checksum in before.items():assert hashlib.sha256((target/name).read_bytes()).hexdigest()==checksum
    result=dict(passed=True,installer_sha256=hashlib.sha256(args.installer.read_bytes()).hexdigest(),
        install_files_verified=len(expected),installed_exe_start_exit=True,upgrade_preserved_data=True,
        upgrade_while_running_rejected=True,uninstall_while_running_rejected=True,uninstall_preserved_files=preserved,
        shortcuts_and_uninstall_registry=True,uninstall_removed_program_files=True,paid_calls=0)
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
