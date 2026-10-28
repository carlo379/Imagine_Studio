"""Offline relay tests: no Cloudflare network, credentials or generation."""
import io
from http.server import ThreadingHTTPServer
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from recording_relay import _handler, serve_recording, RecordingRelayError


class RecordingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.raw = b'0123456789'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(self.raw, 'audio/wav', '/secret.wav'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, path='/secret.wav', **kwargs):
        return urlopen(Request(self.origin + path, **kwargs), timeout=2)

    def test_exact_bytes_and_head(self):
        with self.request() as response:
            self.assertEqual(response.read(), self.raw)
            self.assertEqual(response.headers['Content-Type'], 'audio/wav')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.request(method='HEAD') as response:
            self.assertEqual(response.read(), b'')
            self.assertEqual(response.headers['Content-Length'], '10')

    def test_range_and_suffix(self):
        for header, expected, extent in (('bytes=2-4', b'234', 'bytes 2-4/10'),
                                         ('bytes=8-', b'89', 'bytes 8-9/10'),
                                         ('bytes=-3', b'789', 'bytes 7-9/10')):
            with self.request(headers={'Range': header}) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), expected)
                self.assertEqual(response.headers['Content-Range'], extent)
        for header in ('bytes=10-', 'bytes=-0', 'bytes=4-2', 'bytes=0-1,4-5'):
            with self.assertRaises(HTTPError) as error:
                self.request(headers={'Range': header})
            self.assertEqual(error.exception.code, 416)
            error.exception.close()

    def test_no_other_paths_or_mutations(self):
        for path in ('/', '/secret.wav?extra', '/other.wav', '/../../studio'):
            with self.assertRaises(HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request(method='POST', data=b'change')
        self.assertEqual(error.exception.code, 405)
        error.exception.close()


class RelayLifecycleTests(unittest.TestCase):
    def process(self, output):
        process = Mock()
        process.stdout = io.StringIO(output)
        process.poll.return_value = None
        return process

    @patch('recording_relay._terminate')
    @patch('recording_relay.subprocess.Popen')
    @patch('recording_relay.shutil.which', return_value='/fake/cf')
    def test_context_uses_cli_and_cleans_up_on_consumer_error(self, which, popen, terminate):
        process = self.process('Tunnel: https://quiet-example.trycloudflare.com\n')
        popen.return_value = process
        with self.assertRaisesRegex(RuntimeError, 'consumer'):
            with serve_recording(b'fixture', 'audio/wav') as url:
                self.assertRegex(url, r'^https://quiet-example\.trycloudflare\.com/[A-Za-z0-9_-]{43}\.wav$')
                command = popen.call_args.args[0]
                self.assertEqual(command[:3], ['/fake/cf', 'tunnels', 'quick-start'])
                self.assertTrue(command[3].startswith('http://127.0.0.1:'))
                self.assertTrue(popen.call_args.kwargs['start_new_session'])
                raise RuntimeError('consumer')
        terminate.assert_called_once_with(process)
        # The isolated local listener is closed when the consumer exits.
        with self.assertRaises(OSError):
            urlopen(command[3], timeout=.2)

    @patch('recording_relay._terminate')
    @patch('recording_relay.subprocess.Popen')
    @patch('recording_relay.shutil.which', return_value='/fake/cf')
    def test_startup_failure_cleans_up(self, which, popen, terminate):
        process = self.process('failed before URL\n')
        popen.return_value = process
        with self.assertRaisesRegex(RecordingRelayError, 'stopped'):
            with serve_recording(b'fixture', 'audio/wav'):
                self.fail('must not enter')
        terminate.assert_called_once_with(process)

    @patch('recording_relay.shutil.which', return_value=None)
    def test_missing_cli_is_explicit(self, which):
        with self.assertRaisesRegex(RecordingRelayError, 'cf CLI'):
            with serve_recording(b'fixture', 'audio/wav'):
                self.fail('must not enter')


if __name__ == '__main__':
    unittest.main()
