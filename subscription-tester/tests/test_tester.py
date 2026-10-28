import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class FlowTests(unittest.TestCase):
    def test_mock_flow_requires_signin_and_completes(self):
        tester = server.Tester(mock=True)
        with self.assertRaises(ValueError):
            tester.begin('generate', 'apple')
        tester.begin('login')
        with self.assertRaises(ValueError):
            tester.begin('login')
        time.sleep(.4)
        self.assertTrue(tester.snapshot()['signed_in'])
        self.assertEqual(tester.snapshot()['auth_status'], 'connected')
        tester.begin('generate', 'apple')
        time.sleep(.6)
        result = tester.snapshot()
        self.assertEqual(result['http_status'], 200)
        self.assertTrue(result['image'].startswith('data:image/'))

    def test_image_uses_only_oauth_and_does_not_expose_token(self):
        import hermes_cli.auth as auth
        credentials = {'provider': 'xai-oauth', 'auth_mode': 'oauth_device_code', 'api_key': 'test-secret-oauth'}
        client = MagicMock()
        response = client.post.return_value
        response.status_code = 200
        response.json.return_value = {'data': [{'url': 'https://example.com/image.png'}]}
        with patch.object(auth, 'resolve_xai_oauth_runtime_credentials', return_value=credentials), patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value = client
            tester = server.Tester()
            tester.generate('apple')
        client.post.assert_called_once_with(server.ENDPOINT, headers={'Authorization': 'Bearer test-secret-oauth'},
                                            json={'model': server.MODEL, 'prompt': 'apple', 'n': 1})
        self.assertNotIn('test-secret-oauth', json.dumps(tester.snapshot()))

    def test_denied_oauth_does_not_retry_or_echo_response(self):
        import hermes_cli.auth as auth
        client = MagicMock()
        client.post.return_value.status_code = 403
        client.post.return_value.text = 'secret echoed by upstream'
        with patch.object(auth, 'resolve_xai_oauth_runtime_credentials', return_value={
                'provider': 'xai-oauth', 'auth_mode': 'oauth_device_code', 'api_key': 'test-secret'}), patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value = client
            tester = server.Tester()
            tester.generate('apple')
        self.assertEqual(client.post.call_count, 1)
        self.assertEqual(tester.snapshot()['http_status'], 403)
        self.assertNotIn('secret', json.dumps(tester.snapshot()))

    def test_api_key_credentials_rejected(self):
        import hermes_cli.auth as auth
        with patch.object(auth, 'resolve_xai_oauth_runtime_credentials', return_value={
                'provider': 'xai-oauth', 'auth_mode': 'oauth_device_code', 'api_key': 'xai-fake-key'}), patch('httpx.Client') as factory:
            tester = server.Tester()
            tester.generate('apple')
            factory.assert_not_called()
        self.assertEqual(tester.snapshot()['phase'], 'error')

    def test_login_uses_hermes_flow_and_exposes_no_tokens(self):
        import hermes_cli.auth as auth
        device = {'verification_uri_complete': 'https://accounts.x.ai/verify', 'user_code': 'DEMO',
                  'expires_in': 600, 'interval': 5, 'device_code': 'private-device-secret'}
        tokens = {'access_token': 'private-access-secret', 'refresh_token': 'private-refresh-secret'}
        with patch.object(auth, '_xai_oauth_discovery', return_value={'token_endpoint': 'https://auth.x.ai/token'}), \
                patch.object(auth, '_xai_oauth_request_device_code', return_value=device), \
                patch.object(auth, '_xai_oauth_poll_device_token', return_value=tokens) as poll, \
                patch.object(auth, '_save_xai_oauth_tokens') as save:
            tester = server.Tester()
            tester.login()
            save.assert_called_once()
            self.assertEqual(poll.call_args.kwargs['poll_interval'], 5)
        result = tester.snapshot()
        self.assertTrue(result['signed_in'])
        self.assertEqual(result['auth_status'], 'connected')
        self.assertIsNone(result['verification_url'])
        self.assertIsNone(result['user_code'])
        self.assertNotIn('private', json.dumps(result))

    def test_failed_login_has_safe_independent_auth_status(self):
        import hermes_cli.auth as auth
        with patch.object(auth, '_xai_oauth_discovery', side_effect=RuntimeError('private-token-secret')):
            tester = server.Tester()
            tester.login()
        result = tester.snapshot()
        self.assertEqual(result['auth_status'], 'error')
        self.assertFalse(result['signed_in'])
        self.assertIn('Try signing in again', result['auth_error'])
        self.assertNotIn('private-token-secret', json.dumps(result))


class LocalAccessTests(unittest.TestCase):
    def setUp(self):
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.http.tester = server.Tester(mock=True)
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()

    def post(self, path, body, origin=None, host=None, key=None):
        headers = {'Content-Type': 'application/json', 'X-Tester': 'local', 'Origin': origin or self.base}
        if host:
            headers['Host'] = host
        if key:headers['Idempotency-Key']=key
        request = urllib.request.Request(self.base + path, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code

    def test_foreign_origin_and_host_blocked(self):
        self.assertEqual(self.post('/api/login', {}, origin='https://other.example'), 403)
        self.assertEqual(self.post('/api/login', {}, host='other.example'), 403)

    def test_confirmation_and_prompt_required(self):
        self.http.tester.update(signed_in=True)
        self.assertEqual(self.post('/api/generate', {'prompt': 'apple'}), 403)
        self.assertEqual(self.post('/api/generate', {'prompt': '', 'approved': True}), 400)
        self.assertEqual(self.post('/api/generate', {'prompt': 'apple', 'approved': True}), 400)
        self.assertEqual(self.post('/api/generate', {'prompt': 'apple', 'approved': True},key='tester-mock-once'), 202)
        self.assertEqual(self.post('/api/generate', {'prompt': 'apple', 'approved': True},key='tester-mock-once'), 200)
        self.assertEqual(self.post('/api/generate', {'prompt': 'pear', 'approved': True},key='tester-mock-once'), 409)


if __name__ == '__main__':
    unittest.main()
