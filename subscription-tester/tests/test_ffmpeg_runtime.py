"""Minimum Linux media tools; synthetic version banners, no provider calls."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import ffmpeg_runtime as runtime


class FFmpegRuntimeTests(unittest.TestCase):
    def setUp(self):
        runtime.installed_version.cache_clear()
        self.addCleanup(runtime.installed_version.cache_clear)
        folder = tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for name in ('ffmpeg', 'ffprobe'):
            (self.folder / name).touch()

    def check(self, versions):
        def run(command, **kwargs):
            tool = Path(command[0]).name
            return SimpleNamespace(stdout=f'{tool} version {versions[tool]} Copyright FFmpeg developers\n')
        with patch.object(runtime.sys, 'platform', 'linux'), patch.object(runtime.shutil, 'which', side_effect=lambda tool: str(self.folder / tool)), patch.object(runtime.subprocess, 'run', side_effect=run) as probe:
            runtime.require_supported_linux()
            runtime.require_supported_linux()
            self.assertEqual(probe.call_count, 2, 'Each tool is probed once per executable version.')

    def test_minimum_and_newer_releases_are_supported(self):
        for version in ('9.0.1', '9.0.1-ubuntu1', 'n9.1', '10.0'):
            with self.subTest(version=version):
                runtime.installed_version.cache_clear()
                self.check(dict(ffmpeg=version, ffprobe=version))

    def test_either_old_tool_is_rejected(self):
        for tool in ('ffmpeg', 'ffprobe'):
            for version in ('6.1.1', '7.1.5', '8.1.2', '9.0'):
                with self.subTest(tool=tool, version=version):
                    runtime.installed_version.cache_clear()
                    versions=dict(ffmpeg='9.0.1',ffprobe='9.0.1');versions[tool]=version
                    with self.assertRaisesRegex(RuntimeError, 'Linux requires FFmpeg and FFprobe 9.0.1 or newer'):
                        self.check(versions)

    def test_unknown_development_banner_is_not_assumed_supported(self):
        with self.assertRaisesRegex(RuntimeError, 'stable ffmpeg release'):
            self.check(dict(ffmpeg='N-12345-gabcdef',ffprobe='9.0.1'))

    def test_missing_tool_and_probe_failure_have_actionable_messages(self):
        with patch.object(runtime.sys, 'platform', 'linux'), patch.object(runtime.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'not found.*Install a supported release'):
                runtime.require_supported_linux()
        with patch.object(runtime.sys, 'platform', 'linux'), patch.object(runtime.shutil, 'which', return_value=str(self.folder/'ffmpeg')), patch.object(runtime.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg',5)):
            with self.assertRaisesRegex(RuntimeError, 'Could not check ffmpeg'):
                runtime.require_supported_linux()

    def test_non_linux_platforms_keep_existing_behavior(self):
        for platform in ('darwin','win32'):
            with patch.object(runtime.sys,'platform',platform),patch.object(runtime.shutil,'which') as find:
                runtime.require_supported_linux();find.assert_not_called()

    def test_server_checks_before_initializing_workspace_services(self):
        from server import Tester
        with patch.object(runtime,'require_supported_linux',side_effect=RuntimeError('unsupported toolchain')),patch('diagnostic_requests.DiagnosticRequests') as service:
            with self.assertRaisesRegex(RuntimeError,'unsupported toolchain'):Tester(mock=True)
            service.assert_not_called()
