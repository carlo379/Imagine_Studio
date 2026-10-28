"""Local Node/Skia export of the shared Camera Control drawing module.

No browser discovery, provider calls, system fonts or creative-state writes.
Only server-normalized saved staging is passed to the trusted worker on stdin.
"""
import copy
import io
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tempfile
import threading

from agent_api import APIError

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / 'static/camera-renderer.cjs'
WORKER = ROOT / 'scripts/camera-reference.cjs'
CATALOG = ROOT / 'static/camera-presets.json'
CANVAS_VERSION = '1.0.10'
TIMEOUT_SECONDS = 15
MAX_PNG_BYTES = 3 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024
_render_lock = threading.Lock()


def _unavailable(message):
    return APIError('camera_renderer_unavailable', message, 503)


def _safe_path(path):
    resolved = Path(path).expanduser().resolve()
    # Reject desktop executables and personal Library locations, including symlinks.
    for value in (Path(path).expanduser().absolute(), resolved):
        if 'Applications' in value.parts or value.is_relative_to(Path.home() / 'Library'):
            raise _unavailable('Camera rendering cannot use desktop applications or personal Library paths.')
    return resolved


def runtime_settings():
    """Read administrator config; no process, browser or network probe.

    Availability means prerequisites exist, not successful pixel parity.
    Request bodies cannot override any of these settings.
    """
    candidate = os.environ.get('IMAGINE_CAMERA_NODE') or shutil.which('node')
    if not candidate:
        raise _unavailable('Camera rendering requires Node.js 22+ on PATH, or IMAGINE_CAMERA_NODE.')
    node = _safe_path(candidate)
    if not node.is_file() or not os.access(node, os.X_OK):
        raise _unavailable('IMAGINE_CAMERA_NODE must point to an executable Node.js runtime.')
    try:
        timeout = int(os.environ.get('IMAGINE_CAMERA_TIMEOUT_SECONDS', TIMEOUT_SECONDS))
    except ValueError:
        raise _unavailable('IMAGINE_CAMERA_TIMEOUT_SECONDS must be an integer from 1 to 60.') from None
    if not 1 <= timeout <= 60:
        raise _unavailable('IMAGINE_CAMERA_TIMEOUT_SECONDS must be an integer from 1 to 60.')
    temporary = _safe_path(os.environ.get('IMAGINE_CAMERA_TEMP_DIR', '/tmp'))
    if not temporary.is_dir() or not os.access(temporary, os.W_OK):
        raise _unavailable('IMAGINE_CAMERA_TEMP_DIR must be an existing writable temporary directory.')
    if not BUNDLE.is_file() or not WORKER.is_file():
        raise _unavailable('Build the shared Camera Control worker with npm run build:camera.')
    system = platform.system()
    machine = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x64', 'AMD64': 'x64'}.get(platform.machine())
    if system not in ('Darwin', 'Linux') or not machine:
        raise _unavailable('Camera rendering supports macOS and Linux on arm64 or x64.')
    suffix = ('darwin-' if system == 'Darwin' else 'linux-') + machine
    if system == 'Linux':
        libc = os.environ.get('IMAGINE_CAMERA_LIBC') or ('musl' if list(Path('/lib').glob('ld-musl-*.so.1')) else 'gnu')
        if libc not in ('gnu', 'musl'):
            raise _unavailable('IMAGINE_CAMERA_LIBC must be gnu or musl.')
        suffix += '-' + libc
    native_dir = ROOT / 'node_modules/@napi-rs' / ('canvas-' + suffix)
    try:
        package = json.loads((ROOT / 'node_modules/@napi-rs/canvas/package.json').read_text())
        native = json.loads((native_dir / 'package.json').read_text())
        binary = _safe_path(native_dir / native['main'])
        if package['version'] != CANVAS_VERSION or native['version'] != CANVAS_VERSION or not binary.is_relative_to(native_dir.resolve()) or not binary.is_file():
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise _unavailable('Install the pinned camera dependency for this platform with npm ci --ignore-scripts --no-audit --no-fund (keep optional dependencies).') from None
    sandbox = shutil.which('sandbox-exec') if system == 'Darwin' else None
    if system == 'Darwin' and not sandbox:
        raise _unavailable('Camera rendering on macOS requires sandbox-exec to protect personal Library access.')
    return dict(node=node, native=binary, timeout=timeout, temporary=temporary, sandbox=sandbox)


def preset_catalog():
    value = json.loads(CATALOG.read_text())
    for preset in value['camera']:
        preset['camera'] = {**value['defaults']['camera'], **preset['patch']}
    try:
        settings = runtime_settings()
        available, timeout = True, settings['timeout']
    except APIError:
        available, timeout = False, TIMEOUT_SECONDS
    value['renderer'] = dict(engine='Node Skia Canvas 2D', local_only=True,
        available=available, saved_only=True, guides=False, timeout_seconds=timeout,
        reference_route='filmmaking/shots/{id}/reference.png')
    return value


def _command(settings, directory):
    args = [str(settings['node']), str(WORKER)]
    if settings['sandbox']:
        # OS policy protects native-library access too. Node needs no startup
        # sockets, personal fonts, other processes or network.
        policy = directory / 'isolation.sb'
        quoted = lambda p: json.dumps(str(p))
        policy.write_text('(version 1)\n(allow default)\n(deny network*)\n'
            '(deny file-read* file-write* (subpath ' + quoted(Path.home() / 'Library') + '))\n'
            '(deny file-read* (subpath "/Applications"))\n'
            '(deny file-write*)\n(allow file-write* (subpath ' + quoted(directory) + ') (literal "/dev/null"))\n'
            '(deny process-exec)\n(allow process-exec (literal ' + quoted(settings['node']) + '))\n')
        policy.chmod(0o600)
        args = [settings['sandbox'], '-f', str(policy), *args]
    return args


def _environment(settings, directory):
    value = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
    # Never inherit NODE_OPTIONS, provider keys, proxy settings or addon paths.
    value.update(DISABLE_SYSTEM_FONTS_LOAD='1', NAPI_RS_NATIVE_LIBRARY_PATH=str(settings['native']),
        TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory),
        XDG_CACHE_HOME=str(directory / 'cache'), XDG_CONFIG_HOME=str(directory / 'config'),
        XDG_DATA_HOME=str(directory / 'data'))
    return value


def _terminate_owned_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def render_reference(stage):
    settings = runtime_settings()  # Missing dependencies fail before lock/process.
    try:
        payload = json.dumps(copy.deepcopy(stage), ensure_ascii=True, allow_nan=False).encode()
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError()
    except (ValueError, TypeError):
        raise APIError('camera_renderer_failed', 'Check the saved Camera Control staging.', 503) from None
    if not _render_lock.acquire(timeout=1):
        raise APIError('camera_renderer_busy', 'Another local reference export is running. Try again when it finishes.', 503)
    try:
        with tempfile.TemporaryDirectory(prefix='imagine-camera-', dir=settings['temporary']) as temporary:
            directory = Path(temporary)
            output, errors = directory / 'reference.png', directory / 'stderr.json'
            with output.open('wb') as stdout, errors.open('wb') as stderr:
                output.chmod(0o600); errors.chmod(0o600)
                try:
                    process = subprocess.Popen(_command(settings, directory), stdin=subprocess.PIPE,
                        stdout=stdout, stderr=stderr, env=_environment(settings, directory),
                        start_new_session=True, cwd=directory)
                except OSError:
                    raise _unavailable('The configured Node camera worker could not start.') from None
                try:
                    process.communicate(input=payload, timeout=settings['timeout'])
                except subprocess.TimeoutExpired:
                    raise APIError('camera_renderer_timeout', 'Local reference rendering timed out. No saved work changed.', 503) from None
                finally:
                    _terminate_owned_group(process)
            if process.returncode != 0:
                # Only explicit constant error codes cross the API boundary.
                if errors.stat().st_size < 4096:
                    try:
                        error = json.loads(errors.read_text())
                        if error.get('code') == 'camera_renderer_unavailable':
                            raise _unavailable('The pinned Node canvas dependency could not load. Use Node.js 22+ and npm ci --ignore-scripts --no-audit --no-fund on this platform.')
                        if error.get('code') == 'camera_renderer_isolation':
                            raise APIError('camera_renderer_isolation', 'The local worker blocked a filesystem, process or network access. No saved work changed.', 503)
                    except (ValueError, OSError, AttributeError):
                        pass
                raise APIError('camera_renderer_failed', 'Local reference rendering failed. No saved work changed.', 503)
            try:
                if output.stat().st_size > MAX_PNG_BYTES:
                    raise ValueError()
                raw = output.read_bytes()
                from PIL import Image
                dimensions = json.loads(CATALOG.read_text())['frame_sizes'][stage['ratio']]
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != 'PNG' or image.size != (dimensions['width'], dimensions['height']):
                        raise ValueError()
                    image.verify()
            except (ValueError, KeyError, OSError, TypeError):
                raise APIError('camera_renderer_failed', 'The local renderer did not return a valid reference PNG. No saved work changed.', 503) from None
            return raw
    finally:
        _render_lock.release()
