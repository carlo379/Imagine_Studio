"""Use synthetic tokens and isolated HTTP servers, never provider credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from agent_client import AgentError, StudioClient


class ClientSecurityTests(unittest.TestCase):
    def server(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def client(self, origin):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        token = Path(folder.name) / 'token'
        token.write_text('synthetic-test-token')
        return StudioClient(origin, token)

    def test_redirect_never_receives_bearer_token(self):
        received = []
        class Sink(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                self.send_response(200); self.end_headers()
        destination = self.server(Sink)
        for code in (301, 302, 303, 307, 308):
            class Redirect(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_GET(self):
                    self.send_response(code)
                    self.send_header('Location', destination + '/capture')
                    self.end_headers()
            with self.subTest(code=code), self.assertRaises(AgentError):
                self.client(self.server(Redirect)).request('schema')
        self.assertEqual(received, [])

    def test_environment_proxy_is_not_used_for_local_token(self):
        class Local(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers(); self.wfile.write(b'{"local":true}')
        with patch.dict('os.environ', {'http_proxy':'http://127.0.0.1:1', 'HTTP_PROXY':'http://127.0.0.1:1', 'no_proxy':'', 'NO_PROXY':''}):
            self.assertEqual(self.client(self.server(Local)).request('schema'), {'local':True})
