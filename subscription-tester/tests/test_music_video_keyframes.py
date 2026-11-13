import base64
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import mv_fixtures as fx
from agent_api import APIError
from music_video import keyframes, previz
from studio_server import Studio

SHOTS = [dict(id='s001', kind='cutaway', start=0.0, end=2.5),
         dict(id='s002', kind='sung_cut', start=2.5, end=5.0, section='Verse 1', line=0, text='Hush now little engine of the night'),
         dict(id='s003', kind='spoken', start=5.0, end=8.0, section='Final', line=1, text='I know I was awake')]
ANALYSIS = dict(duration=8.0, bpm=120)
HAVE_RENDERER = bool(previz.find_browser()) and bool(__import__('shutil').which('node'))
PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\nmock').decode()
REFS = dict(character='a1', machine='a2', set='a3')


def spec():
    return previz.default_spec(SHOTS, ANALYSIS, story='bedside_machine')


class StateTests(unittest.TestCase):
    def test_a_later_track_only_takes_over_from_its_first_key(self):
        s = spec()
        early, late = previz.state_at(s, 1.0), previz.state_at(s, 7.5)
        self.assertLess(early['actors']['machine']['eyes'], .5)
        self.assertGreater(late['actors']['machine']['eyes'], .5)
        breathing = next(t for t in s['tracks'] if t['prop'] == 'glow')
        self.assertEqual(early['actors']['machine']['glow'], previz.sample_track(breathing['keys'], 1.0, 'glow'))
        self.assertEqual(previz.state_at(s, 2.6)['shot']['id'], 's002')


class PlanTests(unittest.TestCase):
    def test_one_opening_still_per_shot_and_a_closing_still_for_the_spoken_reveal(self):
        plan = keyframes.draft(SHOTS, spec(), story='bedside_machine', references=REFS, candidates=2, price_per_image=.04)
        counts = {s['shot_id']: [x['role'] for x in s['stills']] for s in plan['shots']}
        self.assertEqual(counts, {'s001': ['first'], 's002': ['first'], 's003': ['first', 'last']})
        self.assertEqual(plan['estimate'], dict(stills=4, candidates_per_still=2, images=8, cost_ceiling=.32))
        first = plan['shots'][0]['stills'][0]
        self.assertAlmostEqual(first['t'], keyframes.FIRST_OFFSET)

    def test_the_spoken_reveal_opens_closed_eyed_and_ends_open_eyed(self):
        plan = keyframes.draft(SHOTS, spec(), story='bedside_machine', references=REFS)
        first, last = plan['shots'][2]['stills']
        self.assertIn('eyes closed', first['moment'])
        self.assertIn('eyes open', last['moment'])

    def test_drafted_prompts_are_clean_and_name_only_attached_references(self):
        plan = keyframes.draft(SHOTS, spec(), story='bedside_machine', references=dict(character='a1', machine='a2'))
        result = keyframes.check(plan, SHOTS)
        self.assertEqual([f['kind'] for f in result['findings'] if f['severity'] == 'error'], [])
        self.assertIn('no_set_reference', [f['kind'] for f in result['findings']])
        prompt = plan['shots'][1]['stills'][0]['prompt']
        self.assertIn('[character reference]', prompt)
        self.assertNotIn('[set reference]', prompt)
        self.assertNotIn('Hush', prompt)

    def test_check_refuses_quotes_lyrics_performance_and_missing_references(self):
        plan = keyframes.draft(SHOTS, spec(), story='bedside_machine')
        bad = {'s001-first': 'The room with a sign that says "sleep".',
               's002-first': 'Hush now little engine of the night, painted across the wall.',
               's003-first': 'The carer sings to the machine. Match [machine reference] exactly.'}
        keyframes.edit(plan, [dict(name=n, prompt=p) for n, p in bad.items()])
        kinds = {f['kind'] for f in keyframes.check(plan, SHOTS)['findings']}
        self.assertTrue({'quoted_words', 'lyric_in_still', 'performance_in_still', 'reference_not_attached',
                         'no_character_reference', 'no_machine_reference', 'text_on_screen'} <= kinds)

    def test_check_notices_a_changed_board(self):
        plan = keyframes.draft(SHOTS, spec(), story='bedside_machine', references=REFS)
        moved = copy.deepcopy(SHOTS)
        moved[1]['end'] = 5.5
        moved.append(dict(id='s004', kind='cutaway', start=8, end=9))
        kinds = {f['kind'] for f in keyframes.check(plan, moved)['findings']}
        self.assertTrue({'stale_timing', 'shot_missing'} <= kinds)

    def test_edit_rules(self):
        plan = keyframes.draft(SHOTS, None, story='generic')
        keyframes.edit(plan, [dict(name='s002-first', t=3.0, moment='m', prompt='p')])
        still = plan['shots'][1]['stills'][0]
        self.assertEqual((still['t'], still['moment'], still['prompt']), (3.0, 'm', 'p'))
        for change in (dict(name='nope'), dict(name='s002-first', t=9.0), dict(name='s002-first', role='last')):
            with self.assertRaises(keyframes.KeyframeError):
                keyframes.edit(plan, [change])
        with self.assertRaises(keyframes.KeyframeError):
            keyframes.draft(SHOTS, references=dict(villain='x'))


class KeyframeApiTests(unittest.TestCase):
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
        p = self.call('POST', 'projects', dict(title='V', production_id=prod['id'], mode='spoken_hooks', master=dict(kind='upload', id=m['id']), lyrics=sheet))
        self.pid = p['id']
        p = self.call('POST', f'projects/{self.pid}/analyze', dict(expected_revision=p['revision']))
        self.p = self.call('POST', f'projects/{self.pid}/board/draft', dict(expected_revision=p['revision']))

    def call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/music-video/' + path, data or {}, None)[1]

    def upload(self):
        return self.app.upload({'name': 'ref.png', 'data_url': PNG})['id']

    def test_draft_edit_and_redraft_flow(self):
        with self.assertRaises(APIError) as e:
            self.call('GET', f'projects/{self.pid}/keyframes')
        self.assertEqual(e.exception.code, 'keyframes_required')
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{self.pid}/keyframes', dict(expected_revision=self.p['revision'], references=dict(character='missing')))
        self.assertEqual(e.exception.code, 'unknown_asset')
        made = self.call('POST', f'projects/{self.pid}/keyframes', dict(expected_revision=self.p['revision'], price_per_image=.05))
        self.assertEqual(len(made['plan']['shots']), len(self.p['shots']))
        self.assertFalse(made['check']['ok'])                       # no character reference yet
        self.assertIn('no_previz', [f['kind'] for f in made['check']['findings']])
        char = self.upload()
        patched = self.call('PATCH', f'projects/{self.pid}/keyframes', dict(expected_revision=made['revision'], references=dict(character=char), candidates=3))
        self.assertTrue(patched['check']['ok'], patched['check']['findings'])
        self.assertIn('[character reference]', patched['plan']['shots'][0]['stills'][0]['prompt'])
        self.assertEqual(patched['check']['estimate']['images'], 3 * patched['check']['estimate']['stills'])
        with self.assertRaises(APIError):
            self.call('PATCH', f'projects/{self.pid}/keyframes', dict(expected_revision=patched['revision'], stills=[dict(name='zzz')]))
        got = self.call('GET', f'projects/{self.pid}/keyframes')
        self.assertEqual(got['revision'], patched['revision'])
        p = self.call('POST', f'projects/{self.pid}/board/draft', dict(expected_revision=got['revision']))
        with self.assertRaises(APIError) as e:
            self.call('GET', f'projects/{self.pid}/keyframes')
        self.assertEqual(e.exception.code, 'keyframes_required')

    def test_a_changed_previz_marks_the_plan_stale(self):
        made = self.call('POST', f'projects/{self.pid}/previz', dict(expected_revision=self.p['revision'], story='bedside_machine'))
        plan = self.call('POST', f'projects/{self.pid}/keyframes', dict(expected_revision=made['revision']))
        self.assertEqual(plan['plan']['story'], 'bedside_machine')
        self.assertFalse(plan['previz_stale'])
        spec = made['spec']
        spec['shots'][0]['camera']['fov'] = 60
        self.call('PUT', f'projects/{self.pid}/previz', dict(expected_revision=plan['revision'], spec=spec))
        self.assertTrue(self.call('GET', f'projects/{self.pid}/keyframes')['previz_stale'])

    def test_stills_need_a_previz(self):
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{self.pid}/previz/stills', dict(expected_revision=self.p['revision']))
        self.assertEqual(e.exception.code, 'previz_required')

    @unittest.skipUnless(HAVE_RENDERER, 'needs node and a headless browser')
    def test_stills_render_at_the_plan_times_and_are_recorded_on_the_plan(self):
        made = self.call('POST', f'projects/{self.pid}/previz', dict(expected_revision=self.p['revision'], story='bedside_machine', width=180, height=320))
        plan = self.call('POST', f'projects/{self.pid}/keyframes', dict(expected_revision=made['revision']))
        out = self.call('POST', f'projects/{self.pid}/previz/stills', dict(expected_revision=plan['revision']))
        names = [x['name'] for s in plan['plan']['shots'] for x in s['stills']]
        self.assertEqual([s['name'] for s in out['stills']], names)
        for s in out['stills']:
            data = (self.app.storage / s['file']).read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(int.from_bytes(data[16:20], 'big'), 180)
        got = self.call('GET', f'projects/{self.pid}/keyframes')
        self.assertEqual(got['revision'], out['revision'])
        self.assertTrue(all(x['previz_still'] for s in got['plan']['shots'] for x in s['stills']))
        with self.assertRaises(APIError):
            self.call('POST', f'projects/{self.pid}/previz/stills', dict(expected_revision=out['revision'], stills=[dict(name='../x', t=1)]))


if __name__ == '__main__':
    unittest.main()
