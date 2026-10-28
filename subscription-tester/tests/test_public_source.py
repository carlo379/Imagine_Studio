"""Public release boundaries: paths only, never inspect credentials or state."""
from pathlib import Path
import runpy
import unittest


class PublicSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts' / 'prepare_public_source.py'))

    def test_private_records_and_history_are_excluded(self):
        for name in ['HANDOFF.md', 'codex-reports/review.md', 'docs/episode-shot-restructure.json',
                     'subscription-tester/scripts/apply_episode_restructure_20261010.py',
                     'subscription-tester/private-production.json', '.git/config']:
            with self.subTest(path=name):
                self.assertFalse(self.policy['eligible'](name))

    def test_local_state_and_environment_paths_are_excluded(self):
        for name in ['subscription-tester/.env.local', 'subscription-tester/.state/history.json',
                     'subscription-tester/user-data/private.py', 'subscription-tester/workspaces/private.py',
                     'subscription-tester/node_modules/react/index.js', 'subscription-tester/.deps/auth.py']:
            with self.subTest(path=name):
                self.assertFalse(self.policy['eligible'](name))

    def test_uncleared_copies_and_binary_video_are_excluded(self):
        for name in ['subscription-tester/docs/voices.html', 'subscription-tester/docs/video-generation.md',
                     'subscription-tester/static/mock-video.mp4', 'subscription-tester/static/production.png',
                     'docs/prompting-guides/grok-imagine-video-1.5-legacy-reference.md']:
            with self.subTest(path=name):
                self.assertFalse(self.policy['eligible'](name))

    def test_runtime_sources_and_attributed_fixture_are_included(self):
        for name in ['subscription-tester/scripts/demo_song_performance.py', '.github/dependabot.yml', 'LICENSE', 'subscription-tester/AGENT_API_REFERENCE.md', 'LICENSES/CC-BY-4.0.txt', 'subscription-tester/editing_tools.py',
                     'subscription-tester/static/build/manifest.json',
                     'subscription-tester/tests/fixtures/ducking-speech.wav',
                     'subscription-tester/tests/fixtures/ducking-speech.md',
                     'docs/prompting-guides/Grok_Imagine_Prompting_Guide.md']:
            with self.subTest(path=name):
                self.assertTrue(self.policy['eligible'](name))
