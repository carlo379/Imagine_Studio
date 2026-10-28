"""Node/Skia renderer boundaries; no browser, provider or saved-state calls."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from agent_api import APIError
import camera_renderer as renderer


class RendererBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stage = json.loads(renderer.CATALOG.read_text())['defaults']

    def png(self, size=(1280, 720)):
        out = io.BytesIO()
        Image.new('RGB', size, '#192d2b').save(out, format='PNG')
        return out.getvalue()

    def settings(self, directory):
        return dict(node=Path('/trusted/node'), native=Path('/trusted/skia.node'),
                    timeout=15, temporary=Path(directory), sandbox=None)

    def fake_child(self, raw=None, timeout=False, returncode=0):
        captures = []

        def start(args, **kwargs):
            captures.append((args, kwargs))
            kwargs['stdout'].write(raw or self.png())

            class Child:
                pid = 987654321
                def __init__(self):
                    self.returncode = returncode
                def communicate(self, input=None, timeout=None):
                    if timeout and timeout_flag:
                        raise subprocess.TimeoutExpired(args, timeout)
                    return b'', b''
                def wait(self, timeout=None):
                    return self.returncode

            timeout_flag = timeout
            return Child()

        return start, captures

    def test_node_command_never_discovers_desktop_browser_or_library(self):
        with tempfile.TemporaryDirectory(prefix='imagine-camera-', dir='/tmp') as directory:
            settings = self.settings(directory)
            args = renderer._command(settings, Path(directory))
            self.assertEqual(args[:2], ['/trusted/node', str(renderer.WORKER)])
            self.assertNotIn('--headless', args)
            self.assertNotIn('/Applications', ' '.join(map(str, args)))
            self.assertNotIn(str(Path.home() / 'Library'), ' '.join(map(str, args)))
            environment = renderer._environment(settings, Path(directory))
            self.assertNotIn('HOME', environment)
            self.assertEqual(environment['DISABLE_SYSTEM_FONTS_LOAD'], '1')
            self.assertEqual(environment['NAPI_RS_NATIVE_LIBRARY_PATH'], str(settings['native']))

    def test_configuration_rejects_applications_and_personal_library(self):
        for candidate in ('/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
                          str(Path.home() / 'Library' / 'Node')):
            with self.subTest(candidate=candidate), patch.dict('os.environ', {'IMAGINE_CAMERA_NODE': candidate}, clear=False):
                with self.assertRaises(APIError) as error:
                    renderer.runtime_settings()
                self.assertEqual(error.exception.code, 'camera_renderer_unavailable')

    def test_worker_source_guards_applications_and_library_access(self):
        source = (renderer.ROOT / 'scripts/camera-isolation.cjs').read_text()
        self.assertIn("'Applications'", source)
        self.assertIn("path.join(os.homedir(), 'Library')", source)
        self.assertIn("globalThis.fetch = violation", source)
        self.assertIn('spawnSync', source)

    def test_success_uses_owned_node_process_and_cleans_temp(self):
        start, captures = self.fake_child()
        before = set(Path('/tmp').glob('imagine-camera-*'))
        with tempfile.TemporaryDirectory(prefix='imagine-camera-test-', dir='/tmp') as base, \
             patch.object(renderer, 'runtime_settings', return_value=self.settings(base)), \
             patch.object(renderer.subprocess, 'Popen', side_effect=start), \
             patch.object(renderer.os, 'killpg') as kill:
            self.assertEqual(renderer.render_reference(self.stage), self.png())
        args, kwargs = captures[0]
        self.assertEqual(args[:2], ['/trusted/node', str(renderer.WORKER)])
        render_directory = Path(kwargs['cwd'])
        self.assertTrue(render_directory.is_relative_to(Path(base)))
        self.assertNotEqual(render_directory, Path(base))
        self.assertTrue(render_directory.name.startswith('imagine-camera-'))
        self.assertTrue(kwargs['start_new_session'])
        allowed = {'PATH', 'LANG', 'LC_ALL', 'DISABLE_SYSTEM_FONTS_LOAD', 'NAPI_RS_NATIVE_LIBRARY_PATH',
                   'TMPDIR', 'TMP', 'TEMP', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'}
        self.assertTrue(set(kwargs['env']) <= allowed)
        kill.assert_called_once_with(987654321, renderer.signal.SIGKILL)
        self.assertFalse(render_directory.exists())
        self.assertEqual(set(Path('/tmp').glob('imagine-camera-*')), before)

    def test_timeout_invalid_png_and_start_failure_release_lock(self):
        cases = [('camera_renderer_timeout', self.fake_child(timeout=True)[0]),
                 ('camera_renderer_failed', self.fake_child(raw=self.png((10, 10)))[0]),
                 ('camera_renderer_unavailable', OSError('private child details'))]
        with tempfile.TemporaryDirectory(prefix='imagine-camera-test-', dir='/tmp') as base:
            for code, start in cases:
                with self.subTest(code=code), patch.object(renderer, 'runtime_settings', return_value=self.settings(base)), \
                     patch.object(renderer.subprocess, 'Popen', side_effect=start), patch.object(renderer.os, 'killpg'):
                    with self.assertRaises(APIError) as error:
                        renderer.render_reference(self.stage)
                    self.assertEqual(error.exception.code, code)
                    self.assertNotIn('private child details', str(error.exception))
                    self.assertFalse(renderer._render_lock.locked())


if __name__ == '__main__':
    unittest.main()
