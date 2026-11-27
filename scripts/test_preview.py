import importlib.util
import contextlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('preview', Path(__file__).with_name('preview.py'))
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class TestPreview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gva-preview-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('ROOT', self.root / 'source'), ('STATE', self.root / 'state')]:
            p = patch.object(preview, name, value)
            p.start()
            self.addCleanup(p.stop)
        preview.ROOT.mkdir()
        preview.directory().mkdir(parents=True)

    def record(self):
        build = 'a' * 32
        runtime = preview.directory() / 'builds' / build / 'server'
        return {'root': str(preview.ROOT), 'buildId': build, 'runtime': str(runtime),
                'binary': str(runtime / 'server'), 'url': 'http://127.0.0.1:43210'}

    def test_worktrees_have_different_directories(self):
        first = preview.directory()
        with patch.object(preview, 'ROOT', self.root / 'other-source'):
            self.assertNotEqual(first, preview.directory())

    def test_state_inside_checkout_is_rejected(self):
        with patch.object(preview, 'STATE', preview.ROOT / 'private-data'):
            with self.assertRaisesRegex(RuntimeError, 'outside the source'):
                with preview.locked():
                    self.fail('checkout-local state accepted')

    def test_smoke_cleanup_failure_retains_registration_and_attempts_both_instances(self):
        spec = importlib.util.spec_from_file_location('preview_smoke', Path(__file__).with_name('preview-smoke.py'))
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        retained = self.root / 'retained-smoke'
        retained.mkdir()
        calls = []
        def call(state, action):
            calls.append((state.name, action))
            if action == 'up':
                raise RuntimeError('intentional startup failure')
            if state.name == 'first':
                raise RuntimeError('intentional cleanup failure')
            return {'status': 'absent'}
        with patch.object(smoke.tempfile, 'mkdtemp', return_value=str(retained)), patch.object(smoke, 'call', side_effect=call):
            with self.assertRaisesRegex(RuntimeError, 'state retained'):
                smoke.main()
        self.assertTrue(retained.exists())
        self.assertIn(('second', 'destroy'), calls)

    def test_owned_state_and_private_credentials(self):
        credentials = preview.initialize_files(43210)
        home = preview.directory()
        self.assertGreaterEqual(len(credentials['password']), 24)
        self.assertEqual((home / 'credentials.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        config = json.loads((home / 'config.yaml').read_text())
        self.assertEqual(config['system']['listen-host'], '127.0.0.1')
        self.assertEqual(config['system']['db-type'], 'sqlite')
        preview.save(self.record())
        self.assertEqual(preview.load()['buildId'], 'a' * 32)
        with patch.object(preview, 'ROOT', self.root / 'another-root'), patch.object(preview, 'directory', return_value=home):
            with self.assertRaisesRegex(RuntimeError, 'ownership'):
                preview.load()

    def test_reject_foreign_runtime_and_public_url(self):
        for field, value in [('binary', '/bin/sh'), ('url', 'https://example.com'), ('buildId', '../escape')]:
            record = self.record()
            record[field] = value
            preview.save(record)
            with self.assertRaises(RuntimeError):
                preview.load()

    def test_pid_identity_mismatch_never_signals(self):
        record = {**self.record(), 'pid': 123, 'processStart': 'original'}
        with patch.object(preview, 'owns_process', return_value=False), patch.object(preview, 'process_start', return_value='original'), patch.object(preview.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                preview.stop(record)
            kill.assert_not_called()

    def test_failed_refresh_restores_database_and_config(self):
        home = preview.directory()
        preview.initialize_files(43210)
        database = home / 'data/preview.db'
        with contextlib.closing(sqlite3.connect(database)) as db, db:
            db.execute('create table marker(value text)')
            db.execute("insert into marker values ('original')")
        original_config = (home / 'config.yaml').read_bytes()
        for name, content in [('build/server', b'binary'), ('server/go.mod', b'module fixture\n'), ('web/dist/index.html', b'index'), ('server/resource/template.txt', b'template')]:
            file = preview.ROOT / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        previous = self.record()
        preview.save(previous)
        calls = []
        def spawn(record):
            calls.append(record['buildId'])
            if record['buildId'] != previous['buildId']:
                with contextlib.closing(sqlite3.connect(database)) as db, db:
                    db.execute("update marker set value='candidate'")
                (home / 'config.yaml').write_text('candidate config')
                raise RuntimeError('intentional candidate failure')
        with patch.object(preview, 'source_identity', return_value={'fingerprint': 'same'}), patch.object(preview.subprocess, 'run'), patch.object(preview, 'spawn', side_effect=spawn), patch.object(preview, 'owns_process', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'intentional candidate failure'):
                preview.up(refresh=True)
        with contextlib.closing(sqlite3.connect(database)) as db, db:
            self.assertEqual(db.execute('select value from marker').fetchone()[0], 'original')
        self.assertEqual((home / 'config.yaml').read_bytes(), original_config)
        self.assertEqual(calls[-1], previous['buildId'])


if __name__ == '__main__':
    unittest.main()
