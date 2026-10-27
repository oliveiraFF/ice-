"""Offline guards for the opt-in acceptance script; no live credentials or requests."""
from pathlib import Path
import tempfile
import unittest

from run_public_video_acceptance import claim, key_from


class CredentialInputTests(unittest.TestCase):
    def test_base64_secret_is_not_truncated_at_plus_slash_or_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.txt'
            key = 'A' * 38 + '/' + 'b' * 7 + '+' + 'C' * 11 + '=='
            for wrapped in (key, 'Bearer ' + key, 'API Key: "' + key + '"'):
                path.write_text(wrapped, encoding='utf-8-sig')
                self.assertEqual(key_from(path, 'tikhub'), key)

    def test_ambiguous_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.txt'
            path.write_text('A'*30 + '\n' + 'B'*30, encoding='utf-8')
            with self.assertRaises(ValueError):
                key_from(path, 'tikhub')

    def test_claim_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'artifacts'
            out.mkdir()
            claim(out, 'tikhub', {}, 'offline-test')
            with self.assertRaises(FileExistsError):
                claim(out, 'tikhub', {}, 'offline-test')


if __name__ == '__main__':
    unittest.main()
