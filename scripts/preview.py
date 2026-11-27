#!/usr/bin/env python3
"""Linux loopback previews: one private SQLite/data directory per worktree."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get('GVA_PREVIEW_STATE', Path.home() / '.local/state/gva-preview')).resolve()
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def key():
    return hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20]


def directory():
    return STATE / key()


def private_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    with open(temporary, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def source_identity():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).split(b'\0')
    digest = hashlib.sha256()
    for name in sorted(set(names) - {b''}):
        path = ROOT / os.fsdecode(name)
        digest.update(name + b'\0')
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            digest.update(str(path.stat().st_mode & 0o111).encode())
        else:
            digest.update(b'<deleted>')
    environment = {k: v for k, v in os.environ.items() if k.startswith('VITE_') or k in ('NODE_ENV', 'GOFLAGS', 'GOOS', 'GOARCH', 'CGO_ENABLED')}
    digest.update(json.dumps(environment, sort_keys=True).encode())
    return {'commit': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
            'fingerprint': digest.hexdigest(), 'dirty': bool(git('status', '--porcelain'))}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process_start(pid):
    try:
        # Field 22 of /proc/PID/stat; comm may itself contain spaces or parentheses.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def owns_process(record):
    pid = record.get('pid')
    if not pid or process_start(pid) != record.get('processStart'):
        return False
    try:
        return Path(f'/proc/{pid}/exe').resolve(strict=True) == Path(record['binary']).resolve(strict=True)
    except OSError:
        return False


def load():
    path = directory() / 'instance.json'
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get('root') != str(ROOT.resolve()):
        raise RuntimeError('preview ownership does not match this worktree')
    build_id = record.get('buildId', '')
    if len(build_id) != 32 or any(c not in '0123456789abcdef' for c in build_id):
        raise RuntimeError('invalid preview build identity')
    expected = directory() / 'builds' / build_id / 'server'
    if record.get('runtime') != str(expected) or record.get('binary') != str(expected / 'server'):
        raise RuntimeError('preview runtime is outside its owned build directory')
    url = urlsplit(record.get('url', ''))
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.path or url.query or url.fragment:
        raise RuntimeError('preview URL must be an explicit loopback HTTP port')
    return record


def save(record):
    private_json(directory() / 'instance.json', record)


@contextlib.contextmanager
def locked():
    if STATE.is_relative_to(ROOT.resolve()):
        raise RuntimeError('preview state must stay outside the source checkout')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    locks = STATE / '.locks'
    locks.mkdir(exist_ok=True, mode=0o700)
    with (locks / (key() + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def request(record, path, data=None, token=None):
    headers = {}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    if token:
        headers['x-token'] = token
    req = urllib.request.Request(record['url'] + path, data=body, headers=headers)
    try:
        response = HTTP.open(req, timeout=60)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        if response.headers.get('X-GVA-Preview-Build') != record['buildId']:
            raise RuntimeError('HTTP port is serving a different preview build')
        return response.status, response.read()


def api(record, path, data=None, token=None):
    status, body = request(record, path, data, token)
    value = json.loads(body)
    if status != 200 or value.get('code') != 0:
        # Do not echo login requests, tokens or credential-bearing responses.
        raise RuntimeError(f'{path}: HTTP {status}, code={value.get("code")}, msg={value.get("msg")}')
    return value.get('data')


def stop(record):
    if owns_process(record):
        os.kill(record['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while owns_process(record) and time.monotonic() < deadline:
            time.sleep(0.1)
        if owns_process(record):
            raise RuntimeError('preview did not stop; process and data retained')
    elif record.get('pid') and process_start(record['pid']) == record.get('processStart'):
        raise RuntimeError('process identity mismatch; refusing to signal or destroy')
    record.pop('pid', None)
    record.pop('processStart', None)
    save(record)


def spawn(record):
    log_path = directory() / 'server.log'
    with open(log_path, 'ab', opener=lambda p, flags: os.open(p, flags, 0o600)) as log:
        process = subprocess.Popen([record['binary'], '-c', str(directory() / 'config.yaml')],
                                   cwd=record['runtime'], stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True,
                                   env={**os.environ, 'GIN_MODE': 'release', 'GVA_PREVIEW_BUILD_ID': record['buildId'],
                                        'GVA_PREVIEW_DATA_DIR': str(directory() / 'data'),
                                        'GVA_PREVIEW_PORT': str(urlsplit(record['url']).port)})
    record['pid'] = process.pid
    record['processStart'] = process_start(process.pid)
    save(record)  # Keep ownership metadata even if startup fails.
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'preview exited; inspect private log {log_path}')
        try:
            status, body = request(record, '/api/health')
            if status == 200 and json.loads(body) == 'ok':
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    stop(record)
    raise RuntimeError(f'preview readiness timed out; inspect private log {log_path}')


def initialize_files(port):
    home = directory()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    for name in ('data', 'uploads/file', 'log', 'builds'):
        (home / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    credentials = {'username': 'admin', 'password': secrets.token_urlsafe(24)}
    private_json(home / 'credentials.json', credentials)
    config = {
        'jwt': {'signing-key': secrets.token_urlsafe(32), 'expires-time': '7d', 'buffer-time': '1d', 'issuer': 'gva-preview'},
        'zap': {'level': 'info', 'format': 'json', 'director': str(home / 'log'), 'retention-day': 3},
        'system': {'listen-host': '127.0.0.1', 'addr': port, 'db-type': 'sqlite', 'oss-type': 'local',
                   'router-prefix': '', 'iplimit-count': 15000, 'iplimit-time': 3600},
        'sqlite': {'path': str(home / 'data'), 'db-name': '', 'max-idle-conns': 1, 'max-open-conns': 1},
        'local': {'path': 'uploads/file', 'store-path': 'uploads/file'},
        'captcha': {'key-long': 6, 'img-width': 240, 'img-height': 80, 'open-captcha': 1000000, 'open-captcha-timeout': 3600},
        'autocode': {'server': 'server', 'web': 'web/src', 'module': 'github.com/flipped-aurora/gin-vue-admin/server'},
        'db-list': [], 'excel': {'dir': 'resource/excel'},
    }
    # JSON is a YAML subset understood by Viper; no third-party Python dependency.
    private_json(home / 'config.yaml', config)
    return credentials


def check(record, login=False):
    if not owns_process(record):
        raise RuntimeError('preview is not running with the recorded process identity')
    status, body = request(record, '/')
    if status != 200 or hashlib.sha256(body).hexdigest() != record['indexSha256']:
        raise RuntimeError('served frontend does not match the recorded build')
    status, body = request(record, '/api/health')
    if status != 200 or json.loads(body) != 'ok':
        raise RuntimeError('health check failed')
    if login:
        if source_identity()['fingerprint'] != record['source']['fingerprint']:
            raise RuntimeError('preview source changed; run make preview-refresh before acceptance')
        credentials = json.loads((directory() / 'credentials.json').read_text())
        if api(record, '/api/init/checkdb', {})['needInit']:
            raise RuntimeError('preview database is not initialized')
        status, _ = request(record, '/api/user/getUserInfo')
        if status != 401:
            raise RuntimeError('anonymous user request was not rejected')
        value = api(record, '/api/base/login', credentials)
        api(record, '/api/user/getUserInfo', token=value['token'])


def up(refresh=False):
    previous = load()
    if previous and owns_process(previous) and not refresh:
        return status()
    before = source_identity()
    subprocess.run(['make', 'build-embed'], cwd=ROOT, check=True, stdout=sys.stderr)
    if source_identity()['fingerprint'] != before['fingerprint']:
        raise RuntimeError('source changed during build; stop editing and rebuild')
    build_id = uuid.uuid4().hex
    home = directory()
    runtime = home / 'builds' / build_id / 'server'
    runtime.mkdir(parents=True, mode=0o700)
    shutil.copy2(ROOT / 'build/server', runtime / 'server')
    shutil.copy2(ROOT / 'server/go.mod', runtime / 'go.mod')
    shutil.copytree(ROOT / 'server/resource', runtime / 'resource')
    # Keep generated uploads and code under the instance, outside the source tree.
    (runtime / 'uploads').symlink_to(home / 'uploads', target_is_directory=True)
    record = {'root': str(ROOT.resolve()), 'buildId': build_id, 'source': before,
              'runtime': str(runtime), 'binary': str(runtime / 'server'),
              'binarySha256': sha(runtime / 'server'), 'indexSha256': sha(ROOT / 'web/dist/index.html')}
    fresh = previous is None
    backup = None
    old_config = None
    if fresh:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        credentials = initialize_files(port)
        record['url'] = f'http://127.0.0.1:{port}'
    else:
        database = home / 'data/preview.db'
        if database.exists():
            backup = home / 'data' / (build_id + '.backup.db')
            with contextlib.closing(sqlite3.connect(database)) as source, contextlib.closing(sqlite3.connect(backup)) as target:
                source.backup(target)
        old_config = (home / 'config.yaml').read_bytes()
        stop(previous)
        record['url'] = previous['url']
        # The private config retains SQLite and the initialized JWT key.
    try:
        spawn(record)
        if fresh:
            api(record, '/api/init/initdb', {'adminPassword': credentials['password'], 'dbType': 'sqlite',
                                           'dbName': 'preview', 'dbPath': str(home / 'data')})
            stop(record)
            spawn(record)
        check(record, login=True)
    except Exception:
        stop(record)
        # Failed refreshes keep prior runtime and data; restore its process when possible.
        if previous:
            if backup:
                for suffix in ('-wal', '-shm'):
                    (home / ('data/preview.db' + suffix)).unlink(missing_ok=True)
                shutil.copy2(backup, home / 'data/preview.db')
            (home / 'config.yaml').write_bytes(old_config)
            spawn(previous)
        raise
    if backup:
        backup.unlink()
    record['ready'] = True
    save(record)
    return status()


def status():
    record = load()
    if record is None:
        return {'status': 'absent'}
    running = owns_process(record)
    result = {k: record[k] for k in ('url', 'buildId', 'source', 'binarySha256')}
    result.update(status='running' if running else 'stopped',
                  sourceChanged=source_identity()['fingerprint'] != record['source']['fingerprint'],
                  credentialsFile=str(directory() / 'credentials.json'),
                  logFile=str(directory() / 'server.log'))
    if running:
        try:
            check(record)
            result['localProbe'] = 'passed'
        except (OSError, ValueError, RuntimeError) as error:
            result['localProbe'] = str(error)
    return result


def main():
    import preview_network
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'refresh', 'status', 'url', 'check', 'stop', 'destroy'])
    parser.add_argument('--if-exists', action='store_true')
    action = parser.parse_args().action
    with locked():
        record = load()
        if action in ('up', 'refresh'):
            result = up(refresh=action == 'refresh')
            preview_network.start(directory(), ROOT, refresh=action == 'refresh')
        elif action in ('stop', 'destroy'):
            preview_network.stop(directory())
            if record:
                stop(record)
                if action == 'destroy':
                    shutil.rmtree(directory())
            result = {'status': 'absent' if action == 'destroy' else 'stopped'}
        elif action == 'check':
            if record is None:
                raise RuntimeError('preview does not exist')
            check(record, login=True)
            result = status()
        else:
            result = status()
        if preview_network.config(directory()):
            result.update(preview_network.status(directory()))
            if result.get('status') == 'running':
                try:
                    result.update(preview_network.check(directory(), load()))
                except (OSError, RuntimeError) as error:
                    result['networkProbe'] = str(error)
                    if action == 'check':
                        raise
        if action == 'url':
            if 'url' not in result:
                raise RuntimeError('preview does not exist')
            print(result['url'])
        else:
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Preview failed: {error}', file=sys.stderr)
        sys.exit(1)
