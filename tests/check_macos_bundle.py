"""Native bundle/Keychain/reopen smoke test, isolated data and synthetic key only.

This checks an actual Cocoa window exists, not its pixels or final user acceptance.
No provider request, ASR inference, publishing or model generation is performed.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_macos import NAME, require_native_mac
from client_credentials import CredentialVault


def request(origin, route, body=None):
    headers = {}
    if body is not None:
        with urlopen(origin + '/api/state?mode=live', timeout=5) as stream:
            token = json.load(stream)['token']
        headers = {'Origin': origin, 'X-Radar-Token': token, 'Content-Type': 'application/json'}
    message = Request(origin + route, data=None if body is None else json.dumps(body).encode('utf-8'), headers=headers)
    with urlopen(message, timeout=10) as stream:
        return stream.read()


def launch(bundle, data):
    session = data / 'desktop-session.json'
    if session.exists():
        raise AssertionError('上次运行没有正常清理会话')
    env = dict(os.environ, TIKHUB_API_KEY='', LLM_ALLOW_PAID='0', SHORT_VIDEO_OPS_WORKSPACE='')
    process = subprocess.Popen([str(bundle / 'Contents/MacOS' / NAME), '--data-dir', str(data)], env=env)
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise AssertionError('应用在准备就绪前退出')
            if session.exists():
                state = json.loads(session.read_text('utf-8'))
                if state['pid'] == process.pid:
                    origin = 'http://127.0.0.1:' + str(state['port'])
                    request(origin, '/api/state?mode=live')
                    return process, origin
            time.sleep(.25)
        raise AssertionError('应用启动超时')
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        raise


def native_window(pid):
    import Quartz
    for _ in range(120):
        windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
        for window in windows:
            bounds = window.get('kCGWindowBounds', {})
            if window.get('kCGWindowOwnerPID') == pid and bounds.get('Width', 0) >= 900 and bounds.get('Height', 0) >= 600:
                return True
        time.sleep(.25)
    raise AssertionError('未观察到原生 Cocoa 主窗口，不能将只有 HTTP 服务记为桌面启动通过')


def stop(process, origin, data):
    request(origin, '/api/desktop/exit', {'confirm': True})
    if process.wait(timeout=20) != 0 or (data / 'desktop-session.json').exists():
        raise AssertionError('应用没有正常退出或清理会话')


def verify_files(bundle, manifest):
    for line in manifest.read_text('utf-8').splitlines():
        expected, name = line.split('  ', 1)
        path = bundle / name
        if not path.resolve().is_relative_to(bundle.resolve()):
            raise AssertionError('应用清单越界')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise AssertionError('应用文件校验失败: ' + name)


def main():
    require_native_mac()
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    release = args.release.resolve()
    receipt = json.loads((release / 'receipt.json').read_text('utf-8'))
    bundle = Path(receipt['bundle'])
    verify_files(bundle, release / 'MANIFEST.sha256')
    with tempfile.TemporaryDirectory(prefix='ice-mac-acceptance-') as temporary:
        root = Path(temporary)
        data = root / 'isolated-data'
        mounted = root / 'mounted'
        mounted.mkdir()
        process, origin, attached = None, None, False
        try:
            process, origin = launch(bundle, data)
            native_window(process.pid)
            state = json.loads(request(origin, '/api/state?mode=live'))
            assert not state['connected']
            for route in ('/dashboard', '/creative', '/market', '/tools', '/api/catalog'):
                assert request(origin, route)
            account = json.loads(request(origin, '/api/agent/onboarding/create', dict(
                request_id='a' * 32, name='Mac隔离技术测试', direction='合成测试资料', audience='测试人员')))
            assert account['kind'] == 'managed'
            assert json.loads(request(origin, '/api/strategy'))['confirmed'] == 0
            secret = 'synthetic-mac-acceptance-no-provider-access'
            saved = json.loads(request(origin, '/api/connect', {'key': secret}))
            assert saved['remembered'] is True
            assert secret.encode() not in (data / 'owner-tikhub/credential.bin').read_bytes()
            backup = request(origin, '/api/agent/onboarding/backup', {})
            with zipfile.ZipFile(io.BytesIO(backup)) as archive:
                assert archive.namelist()
                assert all(secret.encode() not in archive.read(name) for name in archive.namelist())
            for path in data.rglob('*'):
                if path.is_file():
                    assert secret.encode() not in path.read_bytes(), '密钥不得写入数据库、日志或配置'
            stop(process, origin, data)
            process = None
            subprocess.run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mounted), receipt['dmg']], check=True, timeout=60)
            attached = True
            mounted_bundle = mounted / bundle.name
            verify_files(mounted_bundle, release / 'MANIFEST.sha256')
            process, origin = launch(mounted_bundle, data)
            native_window(process.pid)
            reopened = json.loads(request(origin, '/api/agent/onboarding'))
            assert reopened['account_uid'] == account['account_uid']
            state = json.loads(request(origin, '/api/state?mode=live'))
            assert state['connected'] and state['credential_remembered']
            assert secret not in json.dumps(state)
            assert json.loads(request(origin, '/api/connect', {'key': ''}))['remembered'] is False
            stop(process, origin, data)
            process = None
            verify_files(bundle, release / 'MANIFEST.sha256')
            verify_files(mounted_bundle, release / 'MANIFEST.sha256')
            result = dict(passed=True, native_cocoa_window=True, readonly_dmg_launch=True,
                          keychain_save_reopen_forget=True, workspace_backup_and_reopen=True,
                          original_bundle_unchanged=True, synthetic_key_only=True, provider_calls=0,
                          visual_review='pending', asr_inference='not_run', real_model_analysis='not_run')
        finally:
            if process is not None and process.poll() is None:
                try:
                    stop(process, origin, data)
                except Exception:
                    process.terminate()
                    process.wait(timeout=10)
            if attached:
                subprocess.run(['/usr/bin/hdiutil', 'detach', str(mounted)], check=True, timeout=30)
            # Remove only this run's synthetic Keychain item, even if a check failed.
            CredentialVault(data / 'owner-tikhub').forget()
    receipt['native_acceptance'] = 'native-smoke-passed; visual and real-provider acceptance pending'
    (release / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    (release / 'native-smoke.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
