"""Windows current-user protection for a single installation's individual credential."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


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
        protected = b'RADAR-C1\0' + windows_protect(raw)
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
            raw = self.path.read_bytes()
            if not raw.startswith(b'RADAR-C1\0'): raise ValueError()
            value = json.loads(windows_protect(raw[9:], decrypt=True).decode('utf-8'))
            customer, key = value['customer'], value['key']
            if not isinstance(customer, str) or not isinstance(key, str) or not customer or not key: raise ValueError()
            return customer, key
        except (ValueError, KeyError, TypeError, OSError, UnicodeError):
            raise ValueError('加密凭据不可用，请在当前 Windows 账户重新配置') from None

    def forget(self):
        if self.path.exists(): self.path.unlink()
