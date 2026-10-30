"""Current-user credentials: Windows DPAPI or the native macOS Keychain only."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import sys
import uuid


MAC_SERVICE = 'io.iceops.desktop.credentials'
MAC_MARKER = b'ICE-KC1\0'


def macos_keyring():
    # Select the native backend explicitly: never fall back to a plaintext backend.
    from keyring.backends.macOS import Keyring
    backend = Keyring()
    backend.priority
    return backend


def windows_protect(raw, decrypt=False):
    if os.name != 'nt':
        raise ValueError('加密保存仅支持 Windows；可取消记住密钥，仅在本次运行使用')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    def blob(value):
        buffer = ctypes.create_string_buffer(value)
        return Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer
    source, source_buffer = blob(raw)
    entropy, entropy_buffer = blob(b'GoodRadar/IndividualCredential/v1')
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise ValueError('无法读取此 Windows 账户的加密凭据，请重新配置专属密钥')
    free = ctypes.WinDLL('kernel32').LocalFree
    free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free(output.data)


class CredentialVault:
    def __init__(self, folder):
        self.path = Path(folder) / 'credential.bin'

    def save(self, customer, key):
        raw = json.dumps(dict(customer=customer, key=key), ensure_ascii=False).encode('utf-8')
        if sys.platform == 'darwin':
            return self._save_macos(raw.decode('utf-8'))
        protected = b'RADAR-C1\0' + windows_protect(raw)
        self._write(protected)

    def _write(self, protected):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=str(self.path.parent), prefix='.credential-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(protected); stream.flush(); os.fsync(stream.fileno())
            os.replace(str(temporary), str(self.path))
        finally:
            if temporary is not None and temporary.exists(): temporary.unlink()

    def load(self):
        if not self.path.exists(): return '', ''
        try:
            if self.path.stat().st_size > 16384: raise ValueError()
            if sys.platform == 'darwin':
                try:
                    raw = macos_keyring().get_password(MAC_SERVICE, self._mac_account())
                    if raw is None: raise ValueError()
                except Exception:
                    raise ValueError() from None
            else:
                raw = self.path.read_bytes()
                if not raw.startswith(b'RADAR-C1\0'): raise ValueError()
                raw = windows_protect(raw[9:], decrypt=True).decode('utf-8')
            value = json.loads(raw)
            customer, key = value['customer'], value['key']
            if not isinstance(customer, str) or not isinstance(key, str) or not customer or not key: raise ValueError()
            return customer, key
        except (ValueError, KeyError, TypeError, OSError, UnicodeError):
            raise ValueError('加密凭据不可用，请在当前系统账户重新配置') from None

    def forget(self):
        if sys.platform == 'darwin' and self.path.exists():
            try:
                account = self._mac_account()
            except ValueError:
                account = None
            if account is not None:
                try:
                    backend = macos_keyring()
                    if backend.get_password(MAC_SERVICE, account) is not None:
                        backend.delete_password(MAC_SERVICE, account)
                except Exception:
                    raise ValueError('无法清除系统钥匙串凭据，请解锁后再试') from None
        if self.path.exists(): self.path.unlink()

    def _mac_account(self):
        if self.path.stat().st_size > 16384:
            raise ValueError('钥匙串标识无效')
        raw = self.path.read_bytes()
        account = raw[len(MAC_MARKER):].decode('ascii') if raw.startswith(MAC_MARKER) else ''
        if len(account) != 32 or any(c not in '0123456789abcdef' for c in account):
            raise ValueError('钥匙串标识无效')
        return account

    def _save_macos(self, raw):
        fresh, backend, account = True, None, None
        try:
            if self.path.exists():
                try:
                    account = self._mac_account()
                    fresh = False
                except (ValueError, UnicodeError):
                    pass
            account = account or uuid.uuid4().hex
            backend = macos_keyring()
            backend.set_password(MAC_SERVICE, account, raw)
            if fresh:
                self._write(MAC_MARKER + account.encode('ascii'))
        except Exception:
            if fresh and backend is not None and account is not None:
                try:
                    backend.delete_password(MAC_SERVICE, account)
                except Exception:
                    pass
            raise ValueError('无法安全保存系统钥匙串凭据，请解锁后再试；未改为明文保存') from None
