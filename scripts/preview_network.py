#!/usr/bin/env python3
"""Explicit LAN gateway and public tunnel for an owned preview."""
import argparse
import contextlib
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import urllib.request
import uuid

import preview


def config(home):
    file = home / 'network.json'
    return json.loads(file.read_text()) if file.exists() else None


def units(home):
    key = hashlib.sha256(str(home).encode()).hexdigest()[:16]
    return 'gva-lan-' + key, 'gva-public-' + key


def active(unit):
    return subprocess.run(['systemctl', '--user', 'is-active', '--quiet', unit]).returncode == 0


def stop(home):
    if not config(home):
        return
    for unit in reversed(units(home)):
        result = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'LoadState', '--value'], capture_output=True, text=True)
        if result.stdout.strip() not in ('', 'not-found'):
            subprocess.run(['systemctl', '--user', 'stop', unit], check=True, stdout=subprocess.DEVNULL)


def public_url(home):
    settings = config(home)
    if settings and settings.get('hostname'):
        return 'https://' + settings['hostname']
    file = home / 'network/tunnel.log'
    urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', file.read_text(errors='replace')) if file.exists() else []
    return urls[-1] if urls else None


def start(home, root, refresh=False):
    settings = config(home)
    if not settings:
        return
    gateway, tunnel = units(home)
    if refresh:
        stop(home)
    common = ['systemd-run', '--user', '--collect', '--property=Restart=on-failure', '--property=RestartSec=2']
    if not active(gateway):
        subprocess.run(common + ['--unit=' + gateway, sys.executable, '-B', str(root / 'scripts/preview_network.py'),
                                'gateway', '--state', str(preview.STATE)], check=True, stdout=sys.stderr)
    record = preview.load()
    deadline = time.monotonic() + 15
    while True:
        try:
            probe(f'http://127.0.0.1:{settings["port"]}', record)
            break
        except (OSError, RuntimeError):
            if time.monotonic() >= deadline:
                raise RuntimeError('LAN gateway did not serve the owned preview; public tunnel not started')
            time.sleep(0.2)
    old_url = public_url(home)
    started = not active(tunnel)
    if started:
        cloudflared = shutil.which('cloudflared')
        if not cloudflared:
            raise RuntimeError('cloudflared is not installed')
        if settings.get('tunnelId'):
            tunnel_config = home / 'network/cloudflared.yml'
            preview.private_json(tunnel_config, {
                'tunnel': settings['tunnelId'],
                'credentials-file': str(home / 'network/credentials.json'),
                'ingress': [{'hostname': settings['hostname'], 'service': f'http://127.0.0.1:{settings["port"]}'},
                            {'service': 'http_status:404'}],
            })
            command = [cloudflared, 'tunnel', '--config', str(tunnel_config), '--no-autoupdate',
                       '--protocol', 'http2', '--logfile', str(home / 'network/tunnel.log'), 'run', settings['tunnelId']]
        else:
            command = [cloudflared, 'tunnel', '--config', '/dev/null', '--no-autoupdate', '--protocol', 'http2',
                       '--url', f'http://127.0.0.1:{settings["port"]}', '--logfile', str(home / 'network/tunnel.log')]
        subprocess.run(common + ['--unit=' + tunnel] + command, check=True, stdout=sys.stderr)
    deadline = time.monotonic() + 45
    changed_quick_url = started and not settings.get('tunnelId')
    while (not public_url(home) or (changed_quick_url and public_url(home) == old_url)) and time.monotonic() < deadline:
        time.sleep(0.2)
    if not public_url(home) or (changed_quick_url and public_url(home) == old_url):
        raise RuntimeError('public tunnel has no URL yet; inspect network/tunnel.log')
    deadline = time.monotonic() + 45
    while True:
        try:
            check(home, record)
            break
        except (OSError, RuntimeError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def status(home):
    settings = config(home)
    if not settings:
        return {}
    gateway, tunnel = units(home)
    return {'lanUrl': f'http://{settings["host"]}:{settings["port"]}', 'publicUrl': public_url(home),
            'publicMode': 'named' if settings.get('tunnelId') else 'temporary',
            'lanService': 'running' if active(gateway) else 'stopped',
            'publicService': 'running' if active(tunnel) else 'stopped'}


def probe(url, record):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def fetch(address, require_build=False):
        request = urllib.request.Request(address, headers={'User-Agent': 'GVA-Preview-Probe/1.0'})
        with opener.open(request, timeout=15) as response:
            if response.status != 200 or (require_build and response.headers.get('X-GVA-Preview-Build') != record['buildId']):
                raise RuntimeError('network endpoint serves a different preview')
            return response.read()
    body = fetch(url.rstrip('/') + '/', require_build=True)
    digest = hashlib.sha256(body).hexdigest()
    verified = 0
    if digest != record['indexSha256']:
        # An edge may inject analytics into HTML. Verify the owned origin and
        # every local entry asset instead of accepting only the build header.
        original = fetch(record['url'].rstrip('/') + '/', require_build=True)
        if hashlib.sha256(original).hexdigest() != record['indexSha256']:
            raise RuntimeError('network endpoint serves a different preview')
        class Assets(HTMLParser):
            def __init__(self, html):
                super().__init__()
                self.paths = set()
                self.feed(html.decode('utf-8'))
            def handle_starttag(self, tag, attrs):
                if tag in ('script', 'link'):
                    for name, value in attrs:
                        if name in ('src', 'href') and value and re.fullmatch(r'/assets/[^/?#]+\.(?:js|css)', value):
                            self.paths.add(value)
        expected = Assets(original).paths
        if not expected or Assets(body).paths != expected:
            raise RuntimeError('network endpoint frontend asset references differ from the preview')
        for path in sorted(expected):
            source = fetch(record['url'].rstrip('/') + path)
            delivered = fetch(url.rstrip('/') + path)
            if not source or hashlib.sha256(source).digest() != hashlib.sha256(delivered).digest():
                raise RuntimeError('network endpoint frontend asset differs from the preview: ' + path)
            verified += 1
    return {'indexSha256': digest, 'indexBytes': len(body), 'assetsVerified': verified}


def check(home, record):
    endpoints = status(home)
    if endpoints.get('lanService') != 'running' or endpoints.get('publicService') != 'running' or not endpoints.get('publicUrl'):
        raise RuntimeError('configured preview network services are not running')
    lan = probe(endpoints['lanUrl'], record)
    public = probe(endpoints['publicUrl'], record)
    return {'lanProbe': 'passed', 'publicProbe': 'passed', 'networkIntegrity': {'lan': lan, 'public': public}}


class Forwarder(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            record = preview.load()
            if not record or not preview.owns_process(record):
                self.request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return
            target = urlsplit(record['url'])
            with socket.create_connection(('127.0.0.1', target.port), timeout=5) as backend:
                backend.settimeout(None)
                def pump(source, destination):
                    try:
                        while True:
                            data = source.recv(65536)
                            if not data:
                                break
                            destination.sendall(data)
                    except OSError:
                        pass
                    finally:
                        with contextlib.suppress(OSError):
                            destination.shutdown(socket.SHUT_WR)
                thread = threading.Thread(target=pump, args=(self.request, backend), daemon=True)
                thread.start()
                pump(backend, self.request)
        except (OSError, ValueError, RuntimeError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def gateway(home):
    settings = config(home)
    with Server(('127.0.0.1', settings['port']), Forwarder) as local, Server((settings['host'], settings['port']), Forwarder) as lan:
        threading.Thread(target=local.serve_forever, daemon=True).start()
        lan.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['configure', 'gateway', 'status', 'stop'])
    parser.add_argument('--state')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--hostname')
    parser.add_argument('--tunnel-id')
    parser.add_argument('--credentials')
    args = parser.parse_args()
    if args.state:
        preview.STATE = Path(args.state).resolve()
    home = preview.directory()
    if args.action == 'gateway':
        gateway(home)
        return
    with preview.locked():
        if args.action == 'configure':
            address = ipaddress.ip_address(args.host)
            ranges = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
            if not any(address in r for r in ranges) or not 1024 <= args.port <= 65535:
                raise RuntimeError('an explicit RFC1918 address and unprivileged port are required')
            if not preview.load():
                raise RuntimeError('start the owned preview first')
            settings = {**(config(home) or {}), 'host': args.host, 'port': args.port}
            credentials = None
            if any((args.hostname, args.tunnel_id, args.credentials)):
                if not all((args.hostname, args.tunnel_id, args.credentials)):
                    raise RuntimeError('named tunnels require --hostname, --tunnel-id and --credentials together')
                hostname = args.hostname.lower()
                if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}', hostname):
                    raise RuntimeError('invalid public hostname')
                tunnel_id = str(uuid.UUID(args.tunnel_id))
                credentials = json.loads(Path(args.credentials).read_text())
                if str(uuid.UUID(credentials.get('TunnelID', ''))) != tunnel_id:
                    raise RuntimeError('tunnel credentials do not match the requested tunnel')
                settings.update(hostname=hostname, tunnelId=tunnel_id)
            if config(home):
                stop(home)
            # Validate both binds before saving the network configuration.
            with Server(('127.0.0.1', args.port), Forwarder), Server((args.host, args.port), Forwarder):
                pass
            (home / 'network').mkdir(exist_ok=True, mode=0o700)
            if credentials is not None:
                preview.private_json(home / 'network/credentials.json', credentials)
            preview.private_json(home / 'network.json', settings)
            start(home, preview.ROOT)
        elif args.action == 'stop':
            stop(home)
        print(json.dumps(status(home), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Preview network failed: {error}', file=sys.stderr)
        sys.exit(1)
