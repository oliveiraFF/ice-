import json
import hashlib
import sqlite3
import tempfile
import unittest
import shutil
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent_tasks import AgentTasks


class AgentTaskTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'radar.sqlite3'
        self.store = AgentTasks(self.path, 'test rules v1')
        self.media = self.store.put_media(b'\x00\x00\x00\x18ftypisom0000', 'video/mp4', 'sample.mp4')
        self.inputs = {'product': '收纳盒', 'transcript': '人工台词', 'frames': [{'at': 0}]}
        self.strategy = {'version': 3, 'confirmed': 1, 'data': {'direction': '整理方法'}}

    def save(self, **kwargs):
        return self.store.save(self.inputs, self.media['media_id'], self.strategy, **kwargs)

    def test_reopen_preserves_account_media_inputs_rules_and_result(self):
        first = self.save(result={'summary': '合成测试结果'}, source='test')
        reopened = AgentTasks(self.path, 'changed rules v2').get(first['task_uid'])
        self.assertEqual(reopened['account']['account_uid'], self.store.account()['account_uid'])
        self.assertEqual(reopened['input'], self.inputs)
        self.assertEqual(reopened['strategy'], self.strategy)
        self.assertEqual(reopened['rules']['text'], 'test rules v1')
        self.assertEqual(reopened['result']['summary'], '合成测试结果')
        self.assertEqual(self.store.read_media(self.media['media_id'])['data'], b'\x00\x00\x00\x18ftypisom0000')

    def test_versions_remain_immutable_and_conflicting_save_is_rejected(self):
        first = self.save()
        self.inputs['transcript'] = '修改台词'
        second = self.save(task_uid=first['task_uid'], expected_version=1)
        self.assertEqual(second['version'], 2)
        self.assertEqual(self.store.get(first['task_uid'], 1)['input']['transcript'], '人工台词')
        with self.assertRaisesRegex(ValueError, '版本'):
            self.save(task_uid=first['task_uid'], expected_version=1)
        self.assertEqual(len(self.store.get(first['task_uid'])['versions']), 2)

    def test_media_is_deduplicated_and_invalid_type_is_rejected(self):
        same = self.store.put_media(b'\x00\x00\x00\x18ftypisom0000', 'video/mp4', 'other.mp4')
        self.assertEqual(same['media_id'], self.media['media_id'])
        with self.assertRaises(ValueError):
            self.store.put_media(b'not video', 'video/mp4', 'wrong.mp4')
        with self.assertRaises(ValueError):
            self.store.put_media(b'\x00\x00\x00\x18ftypisom0000', 'text/html', 'wrong.html')

    def test_unknown_media_cannot_create_task(self):
        with self.assertRaises(ValueError):
            self.store.save(self.inputs, '0' * 64, self.strategy)
        self.assertEqual(self.store.list(), [])

    def test_migration_backs_up_old_database_without_changing_old_columns(self):
        old = Path(self.folder.name) / 'old.sqlite3'
        with closing(sqlite3.connect(old)) as db, db:
            db.execute('CREATE TABLE legacy(id INTEGER PRIMARY KEY, note TEXT)')
            db.execute('INSERT INTO legacy VALUES(1, ?)', ('keep me',))
        AgentTasks(old, 'rules')
        backups = list((old.parent / 'backups').glob('*.sqlite3'))
        self.assertEqual(len(backups), 1)
        for path in [old, backups[0]]:
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT * FROM legacy').fetchall(), [(1, 'keep me')])

    def test_failed_backup_prevents_migration(self):
        old = Path(self.folder.name) / 'cannot-back-up.sqlite3'
        with closing(sqlite3.connect(old)) as db, db:
            db.execute('CREATE TABLE legacy(id INTEGER)')
        with patch('agent_tasks.backup_database', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                AgentTasks(old, 'rules')
        with closing(sqlite3.connect(old)) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='agent_task'").fetchone())

    def test_interrupted_attempt_becomes_uncertain_without_losing_raw_response(self):
        task = self.save()
        ident = self.store.begin_attempt(task, 'offline-model')
        self.store.archive_response(ident, b'original transport bytes')
        reopened = AgentTasks(self.path, 'new rules').get(task['task_uid'])
        self.assertEqual(reopened['attempts'][0]['status'], 'result_unconfirmed')
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT raw_response FROM agent_task_attempt').fetchone()[0], b'original transport bytes')

    def test_wal_backup_has_verified_manifest_and_can_restore_old_schema(self):
        old = Path(self.folder.name) / 'wal.sqlite3'
        with closing(sqlite3.connect(old)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE legacy(id INTEGER PRIMARY KEY, note TEXT)')
            writer.execute("INSERT INTO legacy VALUES(1,'committed WAL data')")
            writer.commit()
            self.assertTrue(Path(str(old) + '-wal').exists())
            AgentTasks(old, 'rules')
        backup = next((old.parent / 'backups').glob('*.sqlite3'))
        meta = json.loads(backup.with_suffix('.json').read_text('utf-8'))
        self.assertEqual(meta['sha256'], hashlib.sha256(backup.read_bytes()).hexdigest())
        self.assertEqual(meta['tables']['legacy'], 1)
        restored = old.with_name('restored.sqlite3')
        shutil.copy2(backup, restored)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute('SELECT note FROM legacy').fetchone()[0], 'committed WAL data')
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='agent_task'").fetchone())
        self.assertTrue(old.exists())

    def test_interrupted_migration_rolls_back_all_new_tables(self):
        old = Path(self.folder.name) / 'interrupted.sqlite3'
        with closing(sqlite3.connect(old)) as db, db:
            db.execute('CREATE TABLE legacy(id INTEGER)')
        import agent_tasks
        with patch.object(agent_tasks, 'SCHEMA', agent_tasks.SCHEMA + '\nINVALID MIGRATION;'):
            with self.assertRaises(sqlite3.OperationalError):
                AgentTasks(old, 'rules')
        with closing(sqlite3.connect(old)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('legacy',)])


if __name__ == '__main__':
    unittest.main()
