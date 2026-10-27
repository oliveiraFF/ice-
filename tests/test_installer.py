import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_installer import validate_release, payload_scripts


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'ice运营台.exe').write_bytes(b'MZ-unit-fixture')
        (self.root/'SOURCE.json').write_text(json.dumps(dict(edition='owner-exe',source_dirty=False,source_commit='a'*40)),encoding='utf-8')
        self.manifest()

    def manifest(self):
        lines=[hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(self.root).as_posix()
               for p in self.root.rglob('*') if p.is_file() and p.name!='MANIFEST.sha256']
        (self.root/'MANIFEST.sha256').write_text('\n'.join(lines),encoding='utf-8')

    def test_verified_payload_produces_exact_nonrecursive_uninstall_list(self):
        files=validate_release(self.root)
        install,uninstall=payload_scripts(self.root,files)
        self.assertIn('ice运营台.exe',install)
        self.assertIn('Delete "$INSTDIR\\ice运营台.exe"',uninstall)
        self.assertNotIn('/r',uninstall)
        self.assertNotIn('*',uninstall)
        self.assertNotIn('data',uninstall)

    def test_tampered_and_unlisted_files_are_rejected(self):
        (self.root/'ice运营台.exe').write_bytes(b'changed')
        with self.assertRaises(ValueError):validate_release(self.root)
        self.manifest();(self.root/'extra.txt').write_text('unlisted')
        with self.assertRaises(ValueError):validate_release(self.root)

    def test_private_database_is_rejected_even_if_listed(self):
        (self.root/'data').mkdir();(self.root/'data/radar.sqlite3').write_bytes(b'private fixture')
        self.manifest()
        with self.assertRaises(ValueError):validate_release(self.root)

    def test_manifest_cannot_escape_payload_and_dirty_source_is_rejected(self):
        with (self.root/'MANIFEST.sha256').open('a') as f:f.write('\n'+'0'*64+'  ../outside.txt')
        with self.assertRaises(ValueError):validate_release(self.root)
        (self.root/'SOURCE.json').write_text(json.dumps(dict(edition='owner-exe',source_dirty=True,source_commit='a'*40)))
        self.manifest()
        with self.assertRaises(ValueError):validate_release(self.root)
