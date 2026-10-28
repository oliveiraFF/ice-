from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from catalog import Catalog


FAILED = 'GET /api/v1/douyin/app/v1/fetch_hashtag_search_result'
SHARE = 'GET /api/v1/douyin/app/v3/fetch_one_video_by_share_url'


class Catalog404GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'catalog.sqlite3'
        self.catalog = Catalog(Path(__file__).resolve().parents[1] / 'catalog.json', self.database)
        self.catalog.configure_access(True, '1', allow_balance=True)
        self.catalog.manage(FAILED, 'add')
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE tools SET enabled=1,last_at=123,last_ok=0,last_result=? WHERE id=?',
                       ('数据服务 HTTP 404：Not Found', FAILED))
            db.execute('INSERT INTO api_requests(tool_id,cost,at,outcome) VALUES(?,?,?,?)',
                       (FAILED, '0.001', 123, 'uncertain'))
            db.commit()

    def snapshot(self):
        with closing(sqlite3.connect(self.database)) as db:
            return (db.execute('SELECT * FROM tools WHERE id=?', (FAILED,)).fetchone(),
                    db.execute('SELECT * FROM api_requests').fetchall())

    def test_previously_enabled_failed_route_is_blocked_before_any_supplier_call(self):
        before = self.snapshot()
        supplier = Mock(side_effect=AssertionError('No supplier request is authorized'))
        with self.assertRaisesRegex(ValueError, '404'):
            self.catalog.run(FAILED, 'synthetic-credential', {'keyword': 'AI'}, None, supplier)
        supplier.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_cannot_reenable_but_can_disable_without_erasing_history(self):
        with self.assertRaisesRegex(ValueError, '404'):
            self.catalog.manage(FAILED, 'enable')
        self.catalog.manage(FAILED, 'disable')
        self.assertFalse(self.catalog.state()['tools'][FAILED]['enabled'])
        self.assertEqual(self.catalog.detail(FAILED)['last_result'], '数据服务 HTTP 404：Not Found')
        self.assertEqual(self.snapshot()[1][0][-1], 'uncertain')

    def test_list_and_detail_distinguish_unavailable_history_and_verified_response(self):
        state = self.catalog.state()
        unavailable = next(item for item in state['items'] if item['id'] == FAILED)
        self.assertEqual(unavailable['availability'], 'unavailable')
        self.assertEqual(self.catalog.detail(FAILED)['availability'], 'unavailable')
        share = next(item for item in state['items'] if item['id'] == SHARE)
        self.assertEqual(share['availability'], 'unverified')
        self.assertFalse(share['execution_reason'])
        legacy = next(item for item in state['items'] if item.get('legacy_documentation')
                      and item['id'] != FAILED and not item['execution_reason'])
        self.assertEqual(legacy['availability'], 'legacy')
        self.catalog.manage(SHARE, 'add')
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE tools SET last_ok=1 WHERE id=?', (SHARE,)); db.commit()
        self.assertEqual(self.catalog.detail(SHARE)['availability'], 'verified_response')
        self.assertIn('响应', self.catalog.detail(SHARE)['availability_label'])


if __name__ == '__main__':
    unittest.main()
