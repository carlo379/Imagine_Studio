"""One-recording HTTPS relay through the user's cf CLI.

The tunnel exposes a dedicated loopback server, never Imagine Studio. The URL
is a bearer capability: retain it only for the approved provider request.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import threading


class RecordingRelayError(ValueError):
    pass


def _handler(raw, mime, path):
    class AudioHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _empty(self, status, **headers):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            for key, value in headers.items():
                self.send_header(key.replace('_', '-'), value)
            self.end_headers()

        def _audio(self, head=False):
            if self.path != path:
                self._empty(404)
                return
            start, end = 0, len(raw) - 1
            partial = self.headers.get('Range')
            if partial:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', partial)
                try:
                    if not match or not any(match.groups()):
                        raise ValueError()
                    left, right = match.groups()
                    if left:
                        start = int(left)
                        end = min(int(right), end) if right else end
                    else:
                        count = int(right)
                        if count <= 0:
                            raise ValueError()
                        start = max(0, len(raw) - count)
                    if start > end or start >= len(raw):
                        raise ValueError()
                except ValueError:
                    self._empty(416, Content_Range=f'bytes */{len(raw)}')
                    return
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(raw)}')
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(raw[start:end + 1])
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_GET(self):
            self._audio()

        def do_HEAD(self):
            self._audio(head=True)

        def do_POST(self):
            self._empty(405, Allow='GET, HEAD')

        do_PUT = do_POST
        do_DELETE = do_POST
        do_PATCH = do_POST
        do_OPTIONS = do_POST
    return AudioHandler


def _terminate(process):
    if process is None:
        return
    # cf starts cloudflared as a child. Terminate the dedicated process group so
    # a tunnel cannot outlive its recording server when the CLI has children.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    if process.stdout:
        process.stdout.close()


@contextmanager
def serve_recording(raw, mime, *, startup_timeout=30, ttl_seconds=3600):
    """Yield a temporary HTTPS URL and close it on exit/error or TTL expiry.

    Uses ``cf tunnels quick-start``. Only one in-memory recording is exposed at
    an unguessable 256-bit path. No files, credentials, or Studio routes are served.
    """
    if not isinstance(raw, bytes) or not raw or len(raw) > 64 * 1024 * 1024:
        raise RecordingRelayError('Use a nonempty recording of at most 64 MB.')
    if mime not in ('audio/wav', 'audio/mpeg'):
        raise RecordingRelayError('The recording relay supports WAV and MP3 audio.')
    if not 0 < startup_timeout <= 120 or not 0 < ttl_seconds <= 3600:
        raise RecordingRelayError('Invalid recording relay timeout.')
    executable = shutil.which('cf')
    if not executable:
        raise RecordingRelayError('Install the Cloudflare cf CLI to deliver recording references.')
    path = '/' + secrets.token_urlsafe(32) + ('.wav' if mime == 'audio/wav' else '.mp3')
    server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(raw, mime, path))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    process = None
    timer = None
    closed = threading.Event()
    lock = threading.Lock()

    def cleanup():
        with lock:
            if closed.is_set():
                return
            closed.set()
            if timer:
                timer.cancel()
            try:
                _terminate(process)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    try:
        process = subprocess.Popen(
            [executable, 'tunnels', 'quick-start', f'http://127.0.0.1:{server.server_port}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True, bufsize=1,
        )
        found = queue.Queue(maxsize=1)

        def read_output():
            try:
                for line in process.stdout:
                    match = re.search(r'https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com\b', line)
                    if match:
                        try:
                            found.put_nowait(match.group(0))
                        except queue.Full:
                            pass
            finally:
                try:
                    found.put_nowait(None)
                except queue.Full:
                    pass

        threading.Thread(target=read_output, daemon=True).start()
        try:
            origin = found.get(timeout=startup_timeout)
        except queue.Empty:
            raise RecordingRelayError('The temporary recording tunnel did not become ready in time.') from None
        if not origin or process.poll() is not None:
            raise RecordingRelayError('The temporary recording tunnel stopped before becoming ready.')
        timer = threading.Timer(ttl_seconds, cleanup)
        timer.daemon = True
        timer.start()
        yield origin + path
    except OSError as error:
        raise RecordingRelayError('Could not start the temporary recording relay.') from error
    finally:
        cleanup()


class RecordingRelay:
    """Object-style wrapper for an ExitStack-managed one-recording relay."""
    def __init__(self, raw, mime, **options):
        self._context = serve_recording(raw, mime, **options)
        self.url = None

    def __enter__(self):
        self.url = self._context.__enter__()
        return self

    def __exit__(self, *exc):
        return self._context.__exit__(*exc)
