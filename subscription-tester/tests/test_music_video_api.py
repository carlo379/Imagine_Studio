import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import mv_fixtures as fx
from test_music_video_lyrics_speech import talk
from agent_api import APIError
from music_video import audio_io
from studio_server import Studio

SHEET = '[Verse]\nI woke up in a city.\n[Hook]\nI am not a robot.\n'


class MusicVideoApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Studio(mock=True, storage=self.root / 'state')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.app.productions.sql.close)
        self.app.generate = Mock(side_effect=AssertionError('No provider generation allowed'))
        self.app.begin = Mock(side_effect=AssertionError('No provider action allowed'))
        self.production = self.app.productions.dispatch('POST', [], dict(kind='quick', title='MV'))[1]['production']

    def call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/music-video/' + path, data or {}, None)[1]

    def upload(self, path):
        m = self.app.editing.upload(dict(name=path.name, base64=base64.b64encode(path.read_bytes()).decode()))
        return dict(kind='upload', id=m['id'])

    def video(self, name, seconds, speech=False):
        path = self.root / (name + '.mp4')
        ff = audio_io.ffmpeg_path()
        if speech:
            fx.write_wav(self.root / (name + '.wav'), talk([(.6 + i * .25, .17) for i in range(8)], seconds))
            audio = ['-i', str(self.root / (name + '.wav'))]
        else:
            audio = ['-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono']
        subprocess.run([ff, '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color=c=teal:s=160x120:d={seconds}:r=24', *audio,
                        '-shortest', '-pix_fmt', 'yuv420p', str(path)], check=True)
        return self.upload(path)

    def project(self, mode='spoken_hooks', **extra):
        samples, _ = fx.song(seconds=24, bpm=124)
        fx.write_wav(self.root / 'song.wav', samples)
        return self.call('POST', 'projects', dict(title='Video', production_id=self.production['id'], mode=mode,
                                                  master=self.upload(self.root / 'song.wav'), lyrics=SHEET, **extra))

    def test_schema_and_no_generation(self):
        s = self.call('GET', 'schema')
        self.assertFalse(s['generation'])
        self.assertEqual(set(s['modes']), {'spoken_word', 'spoken_hooks', 'muted_spans'})
        self.assertEqual(self.app.agent.dispatch('GET', '/agent/v1/schema', {}, None)[0], 200)

    def test_full_flow_hooks_mode(self):
        p = self.project()
        with self.assertRaises(APIError) as e:
            self.call('POST', f"projects/{p['id']}/board/draft", dict(expected_revision=p['revision']))
        self.assertEqual(e.exception.code, 'analysis_required')
        p = self.call('POST', f"projects/{p['id']}/analyze", dict(expected_revision=p['revision']))
        self.assertAlmostEqual(p['analysis']['bpm'], 124, delta=2)
        p = self.call('POST', f"projects/{p['id']}/board/draft", dict(expected_revision=p['revision']))
        kinds = {s['kind'] for s in p['shots']}
        self.assertTrue({'spoken', 'sung_cut'} <= kinds)
        self.assertFalse(self.call('GET', f"projects/{p['id']}/audit")['ok'])
        edits = []
        for s in p['shots']:
            edits.append(dict(id=s['id'], purpose='beat', prompt=f'She says: "{s["text"]}"' if s['kind'] == 'spoken' else 'Neon street, slow push in. No speech.'))
        p = self.call('PATCH', f"projects/{p['id']}/board", dict(expected_revision=p['revision'], shots=edits))
        audit = self.call('GET', f"projects/{p['id']}/audit")
        self.assertTrue(audit['ok'], audit['findings'])
        for s in p['shots']:
            clip = self.video('c' + s['id'], max(3, int(s['end'] - s['start']) + 3), speech=s['kind'] == 'spoken')
            out = self.call('POST', f"projects/{p['id']}/takes", dict(expected_revision=p['revision'], shot_id=s['id'], source=clip,
                                                                       heard_words=s['text'].replace('.', '').split() if s['kind'] == 'spoken' else None) if s['kind'] == 'spoken' else
                            dict(expected_revision=p['revision'], shot_id=s['id'], source=clip))
            p = self.call('GET', f"projects/{p['id']}")
            if s['kind'] == 'spoken':
                self.assertTrue(out['take']['placement']['ok'], out['take'])
                self.assertEqual(out['take']['words']['verdict'], 'match')
            else:
                self.assertFalse(out['take']['audio_used'])
        plan = self.call('POST', f"projects/{p['id']}/render-plan", dict(expected_revision=p['revision'], width=180, height=320))
        self.assertEqual(plan['mute_spans'], [])
        self.assertTrue(any(x['speech'] for x in plan['placements']))
        done = self.call('POST', f"projects/{p['id']}/render", dict(expected_revision=p['revision'], width=180, height=320))
        self.assertTrue((self.app.storage / done['file']).is_file())
        self.assertAlmostEqual(done['duration'], 24, delta=.6)

    def test_changing_mode_clears_the_board_and_revision_conflicts(self):
        p = self.project()
        p = self.call('POST', f"projects/{p['id']}/analyze", dict(expected_revision=p['revision']))
        p = self.call('POST', f"projects/{p['id']}/board/draft", dict(expected_revision=p['revision']))
        stale = p['revision']
        p = self.call('PATCH', f"projects/{p['id']}", dict(expected_revision=p['revision'], mode='spoken_word'))
        self.assertEqual(p['shots'], [])
        with self.assertRaises(APIError) as e:
            self.call('PATCH', f"projects/{p['id']}", dict(expected_revision=stale, mode='muted_spans'))
        self.assertEqual(e.exception.code, 'revision_conflict')

    def test_muted_spans_audit_demands_stems_and_a_bad_mode_is_refused(self):
        p = self.project('muted_spans')
        p = self.call('POST', f"projects/{p['id']}/analyze", dict(expected_revision=p['revision']))
        p = self.call('POST', f"projects/{p['id']}/board/draft", dict(expected_revision=p['revision']))
        kinds = {f['kind'] for f in self.call('GET', f"projects/{p['id']}/audit")['findings']}
        self.assertIn('missing_vocal_stem', kinds)
        with self.assertRaises(APIError):
            self.call('PATCH', f"projects/{p['id']}", dict(expected_revision=p['revision'], mode='singing'))

    def test_board_edit_cannot_change_kind_or_timing(self):
        p = self.project()
        p = self.call('POST', f"projects/{p['id']}/analyze", dict(expected_revision=p['revision']))
        p = self.call('POST', f"projects/{p['id']}/board/draft", dict(expected_revision=p['revision']))
        with self.assertRaises(APIError):
            self.call('PATCH', f"projects/{p['id']}/board", dict(expected_revision=p['revision'], shots=[dict(id=p['shots'][0]['id'], start=1.0)]))


if __name__ == '__main__':
    unittest.main()
