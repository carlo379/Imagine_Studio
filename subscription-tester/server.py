"""Local diagnostic harness for the xAI-endorsed Hermes OAuth integration."""
import argparse
import base64
import json
import logging
import os
import re
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from agent_api import APIError

ROOT = Path(__file__).resolve().parent
HERMES = ROOT / '.deps' / 'hermes'
sys.path.insert(0, str(HERMES))
# A dedicated Hermes root avoids touching the user's normal Hermes account/config.
from user_data import data_home
os.environ['HERMES_HOME'] = str(data_home() / 'hermes')
for name in ('XAI_API_KEY', 'XAI_BASE_URL', 'XAI_OAUTH_BASE_URL'):
    os.environ.pop(name, None)
logging.disable(logging.CRITICAL)
MODEL = 'grok-imagine-image'
ENDPOINT = 'https://api.x.ai/v1/images/generations'


class Tester:
    def __init__(self, mock=False):
        from ffmpeg_runtime import require_supported_linux
        require_supported_linux()
        self.mock = mock
        self.lock = threading.Lock()
        self.state = {'phase': 'idle', 'message': 'Ready to sign in.', 'mock': mock,
                      'signed_in': False, 'auth_status':'disconnected', 'auth_error':None, 'billing': 'Not independently verified', 'image': None}
        from diagnostic_requests import DiagnosticRequests
        self.diagnostics = DiagnosticRequests(self)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def begin(self, action, prompt='', on_complete=None):
        with self.lock:
            if self.state['phase'] in ('connecting', 'waiting', 'generating'):
                raise ValueError('An operation is already running.')
            if action == 'generate' and not self.state['signed_in']:
                raise ValueError('Sign in before sending an image request.')
            self.state.update(phase='connecting' if action == 'login' else 'generating',
                              message='Starting sign-in…' if action == 'login' else 'Sending one image request…',
                              verification_url=None, user_code=None, http_status=None)
            if action == 'login':
                self.state.update(signed_in=False,auth_status='connecting',auth_error=None,auth_expires_at=None)
        operation=self.login if action=='login' else self.generate
        def target(*args):
            try:operation(*args)
            finally:
                if on_complete:on_complete(self.snapshot())
        if hasattr(self,'spawn'):self.spawn(target,*(() if action=='login' else (prompt,)))
        else:threading.Thread(target=target,args=() if action=='login' else (prompt,),daemon=True).start()

    def login(self):
        stage = 'OAuth discovery'
        try:
            if self.mock:
                time.sleep(.3)
                self.update(phase='ready', signed_in=True, auth_status='connected', auth_error=None, message='Mock login complete. No account was contacted.')
                return
            import httpx
            from hermes_cli.auth import (_xai_oauth_discovery, _xai_oauth_request_device_code,
                                         _xai_oauth_poll_device_token, _save_xai_oauth_tokens)
            discovery = _xai_oauth_discovery(20)
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                stage = 'device-code request'
                device = _xai_oauth_request_device_code(client)
                url = str(device.get('verification_uri_complete') or device['verification_uri'])
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.hostname not in ('accounts.x.ai', 'auth.x.ai'):
                    raise ValueError('Unexpected verification URL')
                self.update(phase='waiting', auth_status='waiting', auth_expires_at=time.time()+int(device['expires_in']), verification_url=url, user_code=str(device['user_code']),
                            message='Open the xAI sign-in page and approve Hermes access.',
                            expires_in=int(device['expires_in']))
                stage = 'authorization approval'
                payload = _xai_oauth_poll_device_token(client, token_endpoint=discovery['token_endpoint'],
                             device_code=device['device_code'], expires_in=int(device['expires_in']),
                             poll_interval=int(device['interval']))
            # Use the actual Hermes persistence/refresh implementation, without copying client IDs.
            stage = 'local credential storage'
            _save_xai_oauth_tokens(payload, discovery=discovery)
            self.update(phase='ready', signed_in=True, auth_status='connected', auth_error=None, auth_expires_at=None, verification_url=None, user_code=None,
                        message='OAuth login complete. Image entitlement and billing are still unverified.')
        except Exception as exc:
            # Upstream exception text may contain credential material; never expose it.
            match = re.search(r'HTTP (\d{3})\b', str(exc))
            self.update(phase='error', signed_in=False, auth_status='error', auth_error=f'Sign-in failed at {stage}. Approval may have expired or been denied. Try signing in again.', auth_expires_at=None, verification_url=None, user_code=None,
                        http_status=int(match[1]) if match else None,
                        message=f'Sign-in failed at {stage}. It may have expired or been denied. No API-key fallback was used.')

    def generate(self, prompt):
        try:
            if self.mock:
                time.sleep(.5)
                svg = '<svg xmlns="http://www.w3.org/2000/svg" width="768" height="768"><rect width="768" height="768" fill="#172638"/><circle cx="384" cy="350" r="150" fill="#71dfb0"/><text x="384" y="580" text-anchor="middle" font-family="sans-serif" font-size="26" fill="white">Mock image · no API request</text></svg>'
                self.update(phase='done', http_status=200, image='data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode(),
                            message='Mock request complete. No subscription usage consumed.')
                return
            import httpx
            from studio_server import oauth_headers
            headers=oauth_headers()
            with httpx.Client(timeout=180, follow_redirects=False) as client:
                response = client.post(ENDPOINT, headers=headers,
                                       json=request_body(prompt))
            status = response.status_code
            if status != 200:
                messages = {401: 'OAuth token was rejected. Sign in again.',
                            403: 'xAI denied image access for this OAuth account or subscription tier.',
                            402: 'xAI requires additional billing or usage allowance.',
                            429: 'xAI reported a rate or usage limit. No automatic retry was made.'}
                self.update(phase='error', http_status=status, image=None,
                            message=messages.get(status, 'xAI rejected the image request. No automatic retry or API-key fallback was made.'))
                return
            data = response.json()
            item = data.get('data', [{}])[0]
            image = item.get('url')
            if image and urlparse(image).scheme != 'https':
                image = None
            if not image and item.get('b64_json'):
                raw = base64.b64decode(item['b64_json'], validate=True)
                mime = 'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None
                if mime:
                    image = f'data:{mime};base64,' + item['b64_json']
            self.update(phase='done', http_status=status, image=image,
                        message='Image API accepted OAuth. Check Grok Settings → Usage to verify the subscription deduction.' if image else 'API returned 200, but no supported image was returned.')
        except Exception:
            self.update(phase='error', image=None,
                        message='The request could not complete. Token refresh, network, or response validation failed. No automatic retry was made.')


def request_body(prompt):
    return {'model': MODEL, 'prompt': prompt, 'n': 1}


class Handler(BaseHTTPRequestHandler):
    @property
    def app(self):return getattr(self,'request_app',self.server.tester)
    def log_message(self, *args):
        pass

    def send(self, status, data, mime='application/json'):
        raw = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def allowed_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403, {'error': 'Local access only.'})
        if self.path == '/':
            return self.send(200, (ROOT / 'tester.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/state':
            return self.send(200, self.app.snapshot())
        return self.send(404, {'error': 'Not found.'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        if (not self.allowed_host() or self.headers.get('X-Tester') != 'local'
                or origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')):
            return self.send(403, {'error': 'Local browser origin required.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/login':
                self.app.begin('login')
            elif self.path == '/api/generate':
                status,result=self.app.diagnostics.start(body,self.headers.get('Idempotency-Key'),1000)
                return self.send(status,result)
            else:
                return self.send(404, {'error': 'Not found.'})
            self.send(202, {'ok': True})
        except APIError as e:
            self.send(e.status, {'error': {'code':e.code,'message':str(e)}})
        except (ValueError, TypeError, AttributeError):
            self.send(400, {'error': 'Request invalid, operation already running, or sign-in/confirmation required.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.tester = Tester(args.mock)
    print(f'Tester: http://127.0.0.1:{args.port} ({"mock" if args.mock else "live; requests require a click"})', flush=True)
    server.serve_forever()
