import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

import studio_server
import httpx
from grok_debug_trace import Trace, post, utc

class TraceTests(unittest.TestCase):
    def test_network_timings_and_credential_redaction(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                time.sleep(.03)
                raw=b'{"error":"Auth context expired"}'
                self.send_response(500)
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Set-Cookie','secret-cookie-value')
                self.send_header('Authorization','secret-response-auth')
                self.send_header('X-Private-Credential','secret-unknown-header')
                self.send_header('X-Request-ID','test-provider-id')
                self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        payload=base64.urlsafe_b64encode(json.dumps({'iat':1,'exp':2,'email':'private-email'}).encode()).decode().rstrip('=')
        token='eyJhbGciOiJub25lIn0.'+payload+'.secret-signature'
        try:
            with tempfile.TemporaryDirectory() as folder:
                app=SimpleNamespace(storage=Path(folder));trace=Trace(app,'test-job','Bearer '+token,utc(),.001)
                with httpx.Client(timeout=2,trust_env=False) as client:
                    response=post(client,f'http://127.0.0.1:{server.server_port}/',{'Authorization':'Bearer '+token,'Cookie':'secret-request-cookie'},{'image':'private-image-bytes'},trace)
                self.assertEqual(response.status_code,500)
                raw=trace.path.read_text();data=json.loads(raw)
                for secret in [token,'private-email','secret-cookie-value','secret-request-cookie','secret-response-auth','secret-unknown-header','private-image-bytes']:
                    self.assertNotIn(secret,raw)
                self.assertEqual(data['connections_created'],1)
                self.assertFalse(data['reused_connection'])
                self.assertGreater(data['time_to_first_byte_seconds'],.03)
                self.assertEqual(data['provider_request_id'],'test-provider-id')
                self.assertEqual(data['retries'],0)
                self.assertEqual(data['exception_type'],None)
                self.assertEqual(data['response_headers']['set-cookie'],'[REDACTED]')
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
