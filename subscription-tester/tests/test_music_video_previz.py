import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import mv_fixtures as fx
from agent_api import APIError
from music_video import audio_io, previz
from studio_server import Studio

SHOTS = [dict(id='s001', kind='cutaway', start=0.0, end=2.5), dict(id='s002', kind='sung_cut', start=2.5, end=5.0, section='Verse 1'),
         dict(id='s003', kind='spoken', start=5.0, end=8.0, section='Final')]
ANALYSIS = dict(duration=8.0, bpm=120)
HAVE_RENDERER = bool(previz.find_browser()) and bool(__import__('shutil').which('node'))


class SpecTests(unittest.TestCase):
    def test_default_specs_validate_for_both_stories(self):
        for story in previz.STORIES:
            spec = previz.default_spec(SHOTS, ANALYSIS, [dict(text='hello there', start=2.6, end=4)], story=story)
            self.assertEqual(len(spec['shots']), 3)
            self.assertTrue(all(s['camera']['from'] for s in spec['shots']))

    def test_bedside_story_opens_the_machine_eyes_on_the_spoken_shot(self):
        spec = previz.default_spec(SHOTS, ANALYSIS, story='bedside_machine')
        eyes = next(t for t in spec['tracks'] if t['prop'] == 'eyes')
        opened = next(k for k in eyes['keys'] if k[1] == 1)
        self.assertGreaterEqual(opened[0], 5.0)

    def test_framings_vary_so_the_video_is_not_one_shot_repeated(self):
        spec = previz.default_spec(SHOTS * 4 and [dict(id=f's{i}', kind='sung_cut', start=i * 2, end=i * 2 + 2) for i in range(8)],
                                   dict(duration=16, bpm=120), story='bedside_machine')
        self.assertGreaterEqual(len({s['framing'] for s in spec['shots']}), 3)

    def test_validation_refuses_bad_input(self):
        good = previz.default_spec(SHOTS, ANALYSIS)
        for mutate in (lambda s: s.update(width=10), lambda s: s['shots'][0]['camera'].update(**{'from': [0, 0]}),
                       lambda s: s['shots'][0].update(end=0), lambda s: s['tracks'].append(dict(actor='nobody', prop='glow', keys=[[0, 1]])),
                       lambda s: s['actors'].append(dict(id='x', type='dragon')), lambda s: s['set'].update(preset='moon'),
                       lambda s: s['tracks'].append(dict(actor='subject', prop='pose', keys=[[0, 'dance']]))):
            bad = json.loads(json.dumps(good))
            mutate(bad)
            with self.assertRaises(previz.PrevizError):
                previz.validate(bad)

    def test_validation_cleans_unknown_fields(self):
        spec = previz.default_spec(SHOTS, ANALYSIS)
        spec['evil'] = '<script>'
        spec['shots'][0]['note'] = 'x'
        self.assertNotIn('evil', previz.validate(spec))


@unittest.skipUnless(HAVE_RENDERER, 'needs node and a headless browser')
class RenderTests(unittest.TestCase):
    def test_short_render_has_the_right_size_and_length(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            samples, _ = fx.song(seconds=8)
            fx.write_wav(d / 'song.wav', samples)
            spec = previz.default_spec(SHOTS, ANALYSIS, [dict(text='hello there friend', start=2.6, end=4.5)], story='bedside_machine', width=270, height=480, fps=12)
            out = previz.render(spec, d / 'p.mp4', audio=d / 'song.wav', start=2, end=5)
            self.assertAlmostEqual(audio_io.duration(out['file']), 3, delta=.2)

    def test_same_time_gives_the_same_frame(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            spec = previz.default_spec(SHOTS, ANALYSIS, story='bedside_machine', width=200, height=360, fps=8)
            a = previz.render(spec, d / 'a.mp4', start=3, end=3.5)
            b = previz.render(spec, d / 'b.mp4', start=3, end=3.5)
            self.assertEqual(audio_io.duration(a['file']), audio_io.duration(b['file']))
            ha = __import__('subprocess').run([audio_io.ffmpeg_path(), '-v', 'error', '-i', a['file'], '-f', 'framemd5', '-'], capture_output=True, text=True).stdout
            hb = __import__('subprocess').run([audio_io.ffmpeg_path(), '-v', 'error', '-i', b['file'], '-f', 'framemd5', '-'], capture_output=True, text=True).stdout
            self.assertEqual(ha, hb)


class PrevizApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Studio(mock=True, storage=self.root / 'state')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.app.productions.sql.close)
        self.app.generate = Mock(side_effect=AssertionError('No provider generation allowed'))
        prod = self.app.productions.dispatch('POST', [], dict(kind='quick', title='MV'))[1]['production']
        samples, _ = fx.song(seconds=24, bpm=124)
        fx.write_wav(self.root / 'song.wav', samples)
        m = self.app.editing.upload(dict(name='song.wav', base64=base64.b64encode((self.root / 'song.wav').read_bytes()).decode()))
        sheet = '[Verse]\nI woke up in a city.\n[Hook]\nI am not a robot.\n'
        self.p = self.call('POST', 'projects', dict(title='V', production_id=prod['id'], mode='spoken_hooks', master=dict(kind='upload', id=m['id']), lyrics=sheet))

    def call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/music-video/' + path, data or {}, None)[1]

    def test_previz_needs_a_board_then_roundtrips_and_is_cleared_by_a_redraft(self):
        pid = self.p['id']
        with self.assertRaises(APIError):
            self.call('POST', f'projects/{pid}/previz', dict(expected_revision=self.p['revision']))
        p = self.call('POST', f'projects/{pid}/analyze', dict(expected_revision=self.p['revision']))
        p = self.call('POST', f'projects/{pid}/board/draft', dict(expected_revision=p['revision']))
        made = self.call('POST', f'projects/{pid}/previz', dict(expected_revision=p['revision'], story='bedside_machine', width=270, height=480))
        self.assertEqual(len(made['spec']['shots']), len(p['shots']))
        got = self.call('GET', f'projects/{pid}/previz')
        self.assertEqual(got['spec']['width'], 270)
        spec = got['spec']
        spec['shots'][0]['camera']['fov'] = 55
        put = self.call('PUT', f'projects/{pid}/previz', dict(expected_revision=got['revision'], spec=spec))
        self.assertEqual(put['spec']['shots'][0]['camera']['fov'], 55)
        with self.assertRaises(APIError) as e:
            self.call('PUT', f'projects/{pid}/previz', dict(expected_revision=put['revision'], spec=dict(width=1)))
        self.assertEqual(e.exception.code, 'invalid_previz')
        p = self.call('POST', f'projects/{pid}/board/draft', dict(expected_revision=put['revision']))
        with self.assertRaises(APIError) as e:
            self.call('GET', f'projects/{pid}/previz')
        self.assertEqual(e.exception.code, 'previz_required')

    @unittest.skipUnless(HAVE_RENDERER, 'needs node and a headless browser')
    def test_api_render_writes_an_mp4_into_the_workspace(self):
        pid = self.p['id']
        p = self.call('POST', f'projects/{pid}/analyze', dict(expected_revision=self.p['revision']))
        p = self.call('POST', f'projects/{pid}/board/draft', dict(expected_revision=p['revision']))
        made = self.call('POST', f'projects/{pid}/previz', dict(expected_revision=p['revision'], width=180, height=320, fps=8))
        out = self.call('POST', f'projects/{pid}/previz/render', dict(expected_revision=made['revision'], start=0, end=3))
        self.assertTrue((self.app.storage / out['file']).is_file())
        self.assertAlmostEqual(out['duration'], 3, delta=.3)


if __name__ == '__main__':
    unittest.main()
