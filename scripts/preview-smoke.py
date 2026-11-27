#!/usr/bin/env python3
"""Opt-in real two-instance lifecycle test; all SQLite/uploads are disposable."""
import contextlib
import json
import os
import shutil
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(state, action):
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/preview.py'), action], cwd=ROOT,
                            env={**os.environ, 'GVA_PREVIEW_STATE': str(state)}, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{action} failed: {result.stderr[-1500:]}')
    return json.loads(result.stdout)


def manifest(state):
    files = list(state.glob('*/instance.json'))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text())


def fetch(record, path):
    with HTTP.open(record['url'] + path, timeout=5) as response:
        assert response.headers['X-GVA-Preview-Build'] == record['buildId']
        return response.read()


def post(record, path, data, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['x-token'] = token
    req = urllib.request.Request(record['url'] + path, data=json.dumps(data).encode(), headers=headers)
    with HTTP.open(req, timeout=10) as response:
        assert response.headers['X-GVA-Preview-Build'] == record['buildId']
        return json.loads(response.read())


def main():
    tmp = tempfile.mkdtemp(prefix='gva-preview-smoke-')
    first, second = Path(tmp) / 'first', Path(tmp) / 'second'
    try:
        a, b = call(first, 'up'), call(second, 'up')
        assert a['url'] != b['url'] and a['buildId'] != b['buildId']
        path_a, ra = manifest(first)
        path_b, rb = manifest(second)
        home_a, home_b = path_a.parent, path_b.parent
        credential_a = (home_a / 'credentials.json').read_bytes()
        assert credential_a != (home_b / 'credentials.json').read_bytes()
        original_record = path_a.read_bytes()
        stale = json.loads(original_record)
        stale['source']['fingerprint'] = 'outdated'
        path_a.write_text(json.dumps(stale))
        assert call(first, 'status')['sourceChanged']
        try:
            call(first, 'check')
            raise AssertionError('stale build accepted')
        except RuntimeError as error:
            assert 'source changed' in str(error)
        finally:
            path_a.write_bytes(original_record)
        credentials = json.loads(credential_a)
        wrong = post(ra, '/api/base/login', {**credentials, 'password': 'intentional-wrong-password'})
        assert wrong['code'] != 0
        token = post(ra, '/api/base/login', credentials)['data']['token']
        config = post(ra, '/api/system/getSystemConfig', {}, token)['data']['config']
        config['system'].update({'listen-host': '0.0.0.0', 'addr': int(b['url'].rsplit(':', 1)[1]), 'db-type': 'mysql', 'use-redis': True})
        config['autocode']['root'] = str(ROOT)
        result = post(ra, '/api/system/setSystemConfig', {'config': config}, token)
        assert result['code'] == 0
        for _ in range(50):
            local = post(ra, '/api/system/getSystemConfig', {}, token)['data']['config']
            if local['system']['db-type'] == 'sqlite':
                break
            time.sleep(0.1)
        assert local['system']['listen-host'] == '127.0.0.1'
        assert local['system']['addr'] == int(a['url'].rsplit(':', 1)[1])
        assert local['system']['db-type'] == 'sqlite' and not local['system']['use-redis']
        assert local['autocode']['root'] != str(ROOT)
        for home, text in ((home_a, b'first'), (home_b, b'second')):
            (home / 'uploads/file/check.txt').write_bytes(text)
        assert fetch(ra, '/api/uploads/file/check.txt') == b'first'
        assert fetch(rb, '/api/uploads/file/check.txt') == b'second'
        with contextlib.closing(sqlite3.connect(home_a / 'data/preview.db')) as db, db:
            db.execute('create table preview_smoke_marker(value text)')
            db.execute("insert into preview_smoke_marker values ('retained')")
        with contextlib.closing(sqlite3.connect(home_b / 'data/preview.db')) as db:
            assert db.execute("select count(*) from sqlite_master where name='preview_smoke_marker'").fetchone()[0] == 0
        refreshed = call(first, 'refresh')
        assert refreshed['url'] == a['url'] and refreshed['buildId'] != a['buildId']
        assert not refreshed['sourceChanged'] and refreshed['localProbe'] == 'passed'
        assert (home_a / 'credentials.json').read_bytes() == credential_a
        with contextlib.closing(sqlite3.connect(home_a / 'data/preview.db')) as db:
            assert db.execute('select value from preview_smoke_marker').fetchone()[0] == 'retained'
        _, ra = manifest(first)
        assert fetch(ra, '/api/uploads/file/check.txt') == b'first'
        call(first, 'check')
        call(first, 'stop')
        assert call(first, 'status')['status'] == 'stopped'
        assert json.loads(fetch(rb, '/api/health')) == 'ok'
        restarted = call(first, 'up')
        assert restarted['localProbe'] == 'passed'
        assert (home_a / 'credentials.json').read_bytes() == credential_a
        call(first, 'destroy')
        assert not home_a.exists()
        assert call(first, 'destroy')['status'] == 'absent'
        call(second, 'check')
        print('PASS: distinct ports/credentials/SQLite/uploads; stale check rejected; wrong-password denied; config reload stays local; refresh/stop/restart retain data; destroy independent and idempotent.')
    finally:
        errors = []
        for state in (first, second):
            try:
                call(state, 'destroy')
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError(f'Cleanup failed; preview state retained at {tmp}') from errors[0]
        assert not list(Path(tmp).glob('*/*/instance.json'))
        shutil.rmtree(tmp)
        print('PASS: disposable instances and their registered data cleaned.')


if __name__ == '__main__':
    main()
