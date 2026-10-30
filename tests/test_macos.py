"""Platform contracts; fake Keychain tests are not native macOS acceptance."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import app
import desktop
import client_credentials as credentials
import build_macos
from account_onboarding import AccountOnboarding
from local_asr import LocalASR


class MacPlatformTests(unittest.TestCase):
    def test_windows_cannot_emit_a_fake_mac_bundle(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build_macos.sys, 'platform', 'win32'):
            output = Path(directory) / 'release'
            with self.assertRaises(ValueError):
                build_macos.build(output, '2026.10.30.1')
            self.assertFalse(output.exists())

    def test_mac_build_inputs_include_the_packager_and_exclude_user_data(self):
        names = {row['file'] for row in build_macos.mac_inputs(build_macos.ROOT)}
        self.assertIn('build_macos.py', names)
        self.assertIn('packaging/requirements-macos.txt', names)
        self.assertFalse(any('/data/' in '/' + name or name.endswith('credential.bin') for name in names))

    def test_data_stays_outside_app_bundle_and_windows_default_is_preserved(self):
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(Path, 'home', return_value=Path('/Users/test')):
            self.assertEqual(desktop.default_data_dir(), Path('/Users/test/Library/Application Support/ICEOps/data'))
        with patch.object(desktop.sys, 'platform', 'win32'):
            self.assertEqual(desktop.default_data_dir(), desktop.portable_home() / 'data')

    def test_native_renderer_and_frozen_workflow_resources(self):
        with patch.object(desktop.sys, 'platform', 'darwin'):
            self.assertEqual(desktop.renderer_options(), {'gui': 'cocoa'})
        with patch.object(desktop.sys, 'platform', 'win32'):
            self.assertEqual(desktop.renderer_options()['gui'], 'edgechromium')
        with patch.object(app.sys, 'platform', 'darwin'), patch.object(app.sys, 'frozen', True, create=True), patch.object(app.sys, '_MEIPASS', '/bundle/Contents/Frameworks', create=True):
            root = app._executable_dir()
            self.assertEqual(root, Path('/bundle/Contents/Frameworks'))

    def test_open_workspace_passes_path_as_one_argument(self):
        service = AccountOnboarding.__new__(AccountOnboarding)
        root = Path('/Users/test/Library/Application Support/ICEOps/账号')
        with patch.object(service, 'bound', return_value=root), patch.object(service, 'managed', return_value=True), patch('account_onboarding.sys.platform', 'darwin'), patch('account_onboarding.subprocess.run') as run:
            service.open_folder()
        run.assert_called_once_with(['/usr/bin/open', str(root)], check=True, timeout=10)

    def test_macos_asr_accepts_native_executables_and_rejects_windows_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for field, name in [('ffmpeg', 'ffmpeg'), ('whisper', 'whisper-cli'), ('model', 'model.bin')]:
                path = root / name
                path.write_bytes(b'isolated-path-test')
                paths[field] = str(path)
            with patch('local_asr.sys.platform', 'darwin'), patch('local_asr.os.access', return_value=True):
                self.assertEqual(LocalASR(root).paths(paths), paths)
                wrong = root / 'ffmpeg.exe'
                wrong.write_bytes(b'not-a-mac-binary')
                with self.assertRaises(ValueError):
                    LocalASR(root).paths(dict(paths, ffmpeg=str(wrong)))
            with patch('local_asr.sys.platform', 'darwin'), patch('local_asr.os.access', return_value=False):
                with self.assertRaises(ValueError):
                    LocalASR(root).paths(paths)


class FakeKeychain:
    def __init__(self):
        self.values = {}

    def set_password(self, service, account, raw):
        self.values[service, account] = raw

    def get_password(self, service, account):
        return self.values.get((service, account))

    def delete_password(self, service, account):
        del self.values[service, account]


class MacCredentialContracts(unittest.TestCase):
    def test_keychain_restart_isolated_identity_and_forget_without_plaintext(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(credentials.sys, 'platform', 'darwin'), patch.object(credentials, 'macos_keyring', return_value=FakeKeychain()) as backend:
            vault = credentials.CredentialVault(Path(directory) / 'one')
            other = credentials.CredentialVault(Path(directory) / 'two')
            key = 'synthetic-secret-not-valid'
            self.assertEqual(vault.load(), ('', ''))
            vault.save('owner-tikhub', key)
            self.assertNotIn(key.encode(), vault.path.read_bytes())
            self.assertEqual(credentials.CredentialVault(vault.path.parent).load(), ('owner-tikhub', key))
            self.assertEqual(other.load(), ('', ''))
            other.save('other', 'other-synthetic-secret')
            vault.forget()
            self.assertFalse(vault.path.exists())
            self.assertEqual(other.load()[0], 'other')
            self.assertEqual(len(backend.return_value.values), 1)

    def test_keychain_denial_does_not_echo_error_or_leave_claimed_saved_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(credentials.sys, 'platform', 'darwin'), patch.object(credentials, 'macos_keyring', side_effect=RuntimeError('synthetic-secret-in-native-error')):
            vault = credentials.CredentialVault(directory)
            with self.assertRaises(ValueError) as caught:
                vault.save('owner', 'synthetic-secret')
            self.assertNotIn('synthetic-secret', str(caught.exception))
            self.assertFalse(vault.path.exists())

    def test_marker_failure_cleans_new_keychain_item(self):
        backend = FakeKeychain()
        with tempfile.TemporaryDirectory() as directory, patch.object(credentials.sys, 'platform', 'darwin'), patch.object(credentials, 'macos_keyring', return_value=backend), patch.object(credentials.CredentialVault, '_write', side_effect=OSError('disk full')):
            vault = credentials.CredentialVault(directory)
            with self.assertRaises(ValueError):
                vault.save('owner', 'synthetic-secret')
            self.assertEqual(backend.values, {})
            self.assertFalse(vault.path.exists())

    def test_missing_keychain_item_and_migrated_windows_blob_need_reentry(self):
        backend = FakeKeychain()
        with tempfile.TemporaryDirectory() as directory, patch.object(credentials.sys, 'platform', 'darwin'), patch.object(credentials, 'macos_keyring', return_value=backend):
            vault = credentials.CredentialVault(directory)
            vault.save('owner', 'synthetic-secret')
            backend.values.clear()
            with self.assertRaises(ValueError):
                vault.load()
            vault.path.write_bytes(b'RADAR-C1\0Windows-only-blob')
            with self.assertRaises(ValueError):
                vault.load()


@unittest.skipUnless(sys.platform in ('darwin', 'win32'), 'requires supported desktop OS locking')
class NativeLockTests(unittest.TestCase):
    def test_second_process_cannot_lock_until_first_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = desktop.acquire_lock(Path(directory))
            program = 'from pathlib import Path; import desktop,sys; lock=desktop.acquire_lock(Path(sys.argv[1]))'
            try:
                blocked = subprocess.run([sys.executable, '-c', program, directory], capture_output=True, timeout=10)
                self.assertNotEqual(blocked.returncode, 0)
            finally:
                lock.close()
            allowed = subprocess.run([sys.executable, '-c', program, directory], capture_output=True, timeout=10)
            self.assertEqual(allowed.returncode, 0, allowed.stderr.decode())
