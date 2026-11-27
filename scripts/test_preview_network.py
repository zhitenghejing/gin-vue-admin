import contextlib
import http.server
import json
import hashlib
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import preview_network as network


class TestGateway(unittest.TestCase):
    def test_probe_identifies_itself_and_verifies_assets_after_edge_html_injection(self):
        original = b'<html><script src="/assets/app.12345678.js"></script></html>'
        public = original.replace(b'</html>', b'<script src="https://static.cloudflareinsights.com/beacon.js"></script></html>')
        asset = b'console.log("current")'
        class Handler(http.server.BaseHTTPRequestHandler):
            damaged = False
            def do_GET(self):
                if self.headers.get('User-Agent') != 'GVA-Preview-Probe/1.0':
                    self.send_error(403)
                    return
                body = public if self.path == '/public/' else original
                if self.path.endswith('.js'):
                    body = b'wrong build' if self.damaged and self.path.startswith('/public/') else asset
                self.send_response(200)
                self.send_header('X-GVA-Preview-Build', 'owned-build')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}'
            record = {'url': base + '/origin', 'buildId': 'owned-build', 'indexSha256': hashlib.sha256(original).hexdigest()}
            try:
                network.probe(base + '/public', record)
                Handler.damaged = True
                with self.assertRaisesRegex(RuntimeError, 'asset'):
                    network.probe(base + '/public', record)
            finally:
                server.shutdown()

    def test_current_owned_backend_streams_without_buffering(self):
        release = threading.Event()
        first, second = b'data: first\n\n', b'data: second\n\n'
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(first + second)))
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(first)
                self.wfile.flush()
                release.wait(3)
                self.wfile.write(second)
            def log_message(self, *args):
                pass
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as backend, network.Server(('127.0.0.1', 0), network.Forwarder) as gateway:
            for server in (backend, gateway):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            record = {'url': f'http://127.0.0.1:{backend.server_port}'}
            try:
                with patch.object(network.preview, 'load', return_value=record), patch.object(network.preview, 'owns_process', return_value=True):
                    with socket.create_connection(gateway.server_address, timeout=2) as client:
                        client.sendall(b'GET / HTTP/1.0\r\n\r\n')
                        data = b''
                        while first not in data:
                            data += client.recv(65536)
                        self.assertNotIn(second, data)
                        release.set()
                        while True:
                            chunk = client.recv(65536)
                            if not chunk:
                                break
                            data += chunk
                        self.assertIn(second, data)
            finally:
                release.set()
                gateway.shutdown()
                backend.shutdown()

    def test_stopped_or_reused_process_is_not_forwarded(self):
        with network.Server(('127.0.0.1', 0), network.Forwarder) as gateway:
            threading.Thread(target=gateway.serve_forever, daemon=True).start()
            try:
                with patch.object(network.preview, 'load', return_value={'url': 'http://127.0.0.1:1'}), patch.object(network.preview, 'owns_process', return_value=False):
                    with socket.create_connection(gateway.server_address, timeout=2) as client:
                        client.sendall(b'GET / HTTP/1.0\r\n\r\n')
                        self.assertIn(b'503 Service Unavailable', client.recv(65536))
            finally:
                gateway.shutdown()

    def test_temporary_hostname_tracks_latest_tunnel(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            (home / 'network').mkdir()
            (home / 'network/tunnel.log').write_text('https://first.trycloudflare.com\nhttps://latest.trycloudflare.com\n')
            self.assertEqual(network.public_url(home), 'https://latest.trycloudflare.com')

    def test_named_hostname_ignores_old_temporary_log(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            (home / 'network').mkdir()
            (home / 'network/tunnel.log').write_text('https://old.trycloudflare.com\n')
            network.preview.private_json(home / 'network.json', {'hostname': 'gva.example.com'})
            self.assertEqual(network.public_url(home), 'https://gva.example.com')

    def test_named_start_uses_private_credentials_and_exact_host_ingress(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            (home / 'network').mkdir()
            tunnel_id = '11111111-1111-4111-8111-111111111111'
            network.preview.private_json(home / 'network.json', {
                'host': '192.168.0.10', 'port': 30410, 'hostname': 'gva.example.com', 'tunnelId': tunnel_id,
            })
            with patch.object(network, 'active', return_value=False), patch.object(network, 'probe'), patch.object(network, 'check'), patch.object(network.preview, 'load', return_value={}), patch.object(network.shutil, 'which', return_value='/usr/bin/cloudflared'), patch.object(network.subprocess, 'run') as run:
                network.start(home, home)
            command = run.call_args_list[-1].args[0]
            self.assertEqual(command[-2:], ['run', tunnel_id])
            self.assertNotIn('--url', command)
            file = home / 'network/cloudflared.yml'
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            config = json.loads(file.read_text())
            self.assertEqual(config['ingress'], [{'hostname': 'gva.example.com', 'service': 'http://127.0.0.1:30410'}, {'service': 'http_status:404'}])
            self.assertEqual(config['credentials-file'], str(home / 'network/credentials.json'))


if __name__ == '__main__':
    unittest.main()
