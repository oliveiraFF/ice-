import io
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ai_directions import request_completion
from video_creative import parse_report


class ResponseRecoveryTests(unittest.TestCase):
    def test_only_bom_and_complete_fence_are_repaired(self):
        raw = '\ufeff```json\n{"summary":"原文"}\n```'
        report, repairs = parse_report(raw)
        self.assertEqual(report, {'summary': '原文'})
        self.assertEqual(repairs, ['remove_bom', 'remove_code_fence'])

    def test_multiple_objects_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for raw in ['{} {}', '{"a":1,"a":2}', '{"a":NaN}', '说明文字 {}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_report(raw)

    def test_transport_archives_original_bytes_before_decoding(self):
        raw = b'not valid transport JSON'
        captured = []
        with patch('ai_directions.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(raw)
            with self.assertRaises(ValueError):
                request_completion('http://127.0.0.1/v1/chat/completions', '', {}, response_sink=captured.append)
        self.assertEqual(captured, [raw])

    def test_timeout_is_uncertain_and_never_retried(self):
        with patch('ai_directions.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('timeout')
            with self.assertRaises(ValueError) as error:
                request_completion('http://127.0.0.1/v1/chat/completions', '', {})
            self.assertEqual(error.exception.state, 'result_unconfirmed')
            self.assertEqual(opener.return_value.open.call_count, 1)
