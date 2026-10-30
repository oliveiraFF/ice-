import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import wave

from local_asr import LocalASR, parse_segments


class LocalASRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = LocalASR(self.root / 'data')
        self.tools = self.root / '中文工具'
        self.tools.mkdir()
        self.paths = {}
        suffix = '' if sys.platform == 'darwin' else '.exe'
        for key, name in [('ffmpeg', 'ffmpeg' + suffix), ('whisper', 'whisper-cli' + suffix), ('model', 'model.bin')]:
            path = self.tools / name
            path.write_bytes(b'test-only-not-executable')
            if sys.platform == 'darwin' and key != 'model':
                path.chmod(0o700)
            self.paths[key] = str(path)

    def test_timestamps_are_parsed_and_invalid_or_missing_output_is_not_success(self):
        rows = parse_segments('[00:00:00.000 --> 00:00:01.200]  测试一句\n[00:00:01.200 --> 00:00:02.000]  第二句', 2)
        self.assertEqual(rows[1], dict(start=1.2, end=2.0, text='第二句'))
        for raw in ['', '[00:00:02.000 --> 00:00:01.000] 倒序',
                    '[00:00:00.000 --> 00:00:05.000] 越界',
                    '[00:00:00.000 --> 00:00:01.200] 一\n[00:00:01.000 --> 00:00:02.000] 重叠']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_segments(raw, 2)

    def test_config_is_local_and_survives_restart_but_missing_files_disable_it(self):
        self.assertFalse(self.service.config()['configured'])
        self.service.configure(self.paths)
        self.assertTrue(LocalASR(self.root / 'data').config()['configured'])
        Path(self.paths['model']).unlink()
        self.assertFalse(self.service.config()['configured'])

    def fake_process(self, args, **kwargs):
        self.calls.append((args, kwargs))
        folder = Path(kwargs['cwd'])
        self.assertTrue(str(folder).isascii())
        if Path(args[0]).name in ('ffmpeg', 'ffmpeg.exe'):
            with wave.open(str(folder / 'audio.wav'), 'wb') as f:
                f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                f.writeframes((b'\x10\x00' if not self.silent else b'\x00\x00') * 32000)
            return type('Process', (), {'returncode': 0, 'stdout': b''})()
        self.assertEqual(args[args.index('-m') + 1], 'model.bin')
        self.assertEqual(args[args.index('-f') + 1], 'audio.wav')
        self.assertNotIn('-osrt', args)
        return type('Process', (), {'returncode': 0, 'stdout': '[00:00:00.000 --> 00:00:02.000] 本地测试句'.encode()})()

    def test_local_execution_produces_verifiable_receipt_without_network_or_ai_key(self):
        self.service.configure(self.paths)
        self.calls, self.silent = [], False
        media = b'\x00\x00\x00\x18ftypisom0000'
        with patch('local_asr.subprocess.run', side_effect=self.fake_process):
            result = self.service.transcribe(media, 'video/mp4', True)
        self.assertEqual(len(self.calls), 2)
        inputs = dict(transcript=result['text'], transcript_source='local_asr',
                      transcript_segments=result['segments'], transcript_asr=result['metadata'])
        self.service.verify(inputs, result['metadata']['media_sha256'])
        self.assertEqual(result['metadata']['reviewed'], False)
        self.assertNotIn(str(self.tools), json.dumps(result))
        with self.assertRaises(ValueError):
            self.service.verify(dict(inputs, transcript='擅自改成其他文字'), result['metadata']['media_sha256'])
        with self.assertRaises(ValueError):
            self.service.verify(inputs, '0' * 64)

    def test_no_consent_or_silence_cannot_start_recognition(self):
        self.service.configure(self.paths)
        with patch('local_asr.subprocess.run') as run, self.assertRaises(ValueError):
            self.service.transcribe(b'', 'video/mp4', False)
        run.assert_not_called()
        self.calls, self.silent = [], True
        with patch('local_asr.subprocess.run', side_effect=self.fake_process), self.assertRaises(ValueError):
            self.service.transcribe(b'\x00\x00\x00\x18ftypisom0000', 'video/mp4', True)
        self.assertEqual(len(self.calls), 1)
