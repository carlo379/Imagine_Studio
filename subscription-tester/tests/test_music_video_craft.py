"""Claudia-derived craft rules: corrections (no slowdowns, no first frames, no default grade), stem line times, Grok
prompt writer and linter, board gates, cut review and flash check, code-made shots and painted plates."""
import tempfile
import unittest
from pathlib import Path

import mv_fixtures as fx
from agent_api import APIError
from music_video import gates, grade, grokprompt, plates, previz, release, render, speech, stemtimes, triage
import test_music_video_finish as finish
from test_music_video_finish import ff, moving_clip
from test_music_video_previz import HAVE_RENDERER


class CorrectionTests(unittest.TestCase):
    def test_windows_never_show_the_first_two_frames_and_do_not_slow_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            r = triage.scan(moving_clip(Path(d) / 'm.mp4', 3))
        w = triage.best_window(r, 2.0)
        self.assertGreaterEqual(w['in_point_s'], speech.SKIP_S - 1e-3)
        self.assertFalse(w['retimed'])
        self.assertFalse(triage.best_window(r, 2.95)['ok'])      # 2.95 s + the skipped frames do not fit in 3 s at 1x

    def test_spoken_placement_trims_the_first_frames_and_reports_the_beat_error(self):
        take = dict(speech=True, first_speech_s=1.0, syllable_onsets=[1.0])
        out = speech.place_on_beat(take, [10.0, 11.0], 10.0, trim_only=True, min_in_point=speech.SKIP_S)
        self.assertGreaterEqual(out['in_point_s'], round(speech.SKIP_S, 3))
        self.assertLessEqual(abs(out['beat_error_s']), .1)
        self.assertTrue(out['ok'])
        # The dry run's case: speech 19 ms before a beat cannot be delayed by trimming; trim nearly to the first
        # syllable instead, landing 0.04 s after the bar's downbeat.
        late = speech.place_on_beat(dict(speech=True, first_speech_s=.599), [62.007, 62.625, 63.243], 62.007, trim_only=True, min_in_point=speech.SKIP_S)
        self.assertTrue(late['ok'], late)
        self.assertEqual(late['lands_on_beat_s'], 62.007)
        self.assertAlmostEqual(late['beat_error_s'], .04, places=3)
        far = speech.place_on_beat(dict(speech=True, first_speech_s=.2), [10.6], 10.0, trim_only=True, min_in_point=speech.SKIP_S)
        self.assertFalse(far['ok'])

    def test_no_grade_or_grain_until_asked_and_metadata_is_stripped(self):
        look = grade.settings()
        self.assertFalse(look['match'])
        self.assertEqual(look['grain'], 0)
        cmd = render.build_command('s.wav', [dict(clip='a.mp4', start=0, duration=2, speech=False, kind='visual')], 'o.mp4')
        self.assertIn('-map_metadata', cmd)
        self.assertNotIn('noise=', ' '.join(cmd))


class StemTimeTests(unittest.TestCase):
    def test_lines_move_onto_the_voiced_edges(self):
        env = [0.001] * 800
        for i in range(200, 350):
            env[i] = .3                 # line 0 sung 2.00-3.50 s
        for i in range(500, 620):
            env[i] = .25                # line 1 sung 5.00-6.20 s
        times = [dict(line=0, start=.4, end=3.3), dict(line=1, start=4.9, end=5.9)]   # transcript starts both early
        out = {t['line']: t for t in stemtimes.refine(times, env=env)}
        self.assertAlmostEqual(out[0]['start'], 2.0, delta=.02)
        self.assertAlmostEqual(out[0]['end'], 3.5, delta=.02)
        self.assertAlmostEqual(out[1]['start'], 5.0, delta=.02)
        self.assertAlmostEqual(out[1]['end'], 6.2, delta=.02)
        self.assertEqual(out[0]['source'], 'stem')

    def test_a_line_with_no_voice_nearby_keeps_its_transcript_time(self):
        out = stemtimes.refine([dict(line=0, start=1.0, end=2.0)], env=[0.001] * 300 + [.3] * 10)
        self.assertEqual(out[0]['source'], 'transcript')


class GrokPromptTests(unittest.TestCase):
    SPOKEN = dict(id='s9', kind='spoken', start=60, end=65, text='I know. I was awake. Sing it again.', lead_in_s=.3)
    VISUAL = dict(id='s2', kind='sung_cut', start=5, end=10, text='Hush now')

    def kinds(self, prompt, kind='sung_cut', text=None, seconds=None):
        return {f['kind'] for f in grokprompt.lint(prompt, kind, text, seconds)}

    def test_written_prompts_lint_clean(self):
        spoken = grokprompt.write(self.SPOKEN, 'A small machine on a bed, eyes closed.', 'push_in', 'the machine')
        self.assertIn('"I know, I was awake, sing it again."', spoken)
        self.assertEqual(self.kinds(spoken, 'spoken', self.SPOKEN['text'], 5), set())
        visual = grokprompt.write(self.VISUAL, 'Wide shot of a dim bedroom.', 'orbit_left')
        self.assertEqual(self.kinds(visual, seconds=5), set())

    def test_the_failure_modes_are_caught(self):
        bad = ('She stands perfectly still, deadpan, eyes on the lens, smiling: "I know. I was awake." The camera pulls back '
               'in a 360 orbit past a sign that says hello. She looks behind herself.')
        found = self.kinds(bad, 'spoken', 'I know. I was awake.', 20)
        self.assertTrue({'mood_words', 'posture_rule', 'smile_while_speaking', 'full_stop_inside_line', 'pull_back', 'big_move',
                         'on_screen_text', 'look_past_lens', 'first_frame', 'no_text_line', 'over_take_limit'} <= found, found)
        self.assertIn('vocal_in_visual_prompt', self.kinds('As in the first frame, she sings softly. No on-screen text.'))
        self.assertIn('no_movement', self.kinds('As in the first frame: a quiet bedroom. No on-screen text.'))
        self.assertIn('quote_mismatch', self.kinds('As in the first frame she nods: "Other words." No on-screen text.', 'spoken', 'I know'))


class GateTests(unittest.TestCase):
    def test_board_gates(self):
        shots = [dict(id='a', start=0, end=4.5, section=None), dict(id='b', start=4.5, end=5.2, section='V'),
                 dict(id='c', start=5.2, end=7.2, section='V'), dict(id='d', start=7.2, end=9.2, section='V'),
                 dict(id='e', start=9.2, end=11.2, section='V'), dict(id='f', start=11.2, end=13.2, section='V')]
        spec = dict(shots=[dict(id='a', framing='wide', move='drift_high'), dict(id='b', framing='wide', move='drift_high'),
                           dict(id='c', framing='medium', move='push_in'), dict(id='d', framing='close', move='low_push'),
                           dict(id='e', framing='medium', move='orbit_left'), dict(id='f', framing='close', move='push_in')])
        first = lambda sid, asset, **kw: dict(shot_id=sid, stills=[dict(role='first', approved=dict(asset_id=asset), **kw)])
        kf = dict(shots=[first('c', 'X'), first('d', 'Y'), first('e', 'X'), first('f', 'Z', continues='c')])
        found = {(f['kind'], f['shot']) for f in gates.check(shots, spec, kf)}
        for want in (('same_setup', 'b'), ('short_shot', 'b'), ('same_length_run', 'c'), ('slow_hook', 'a'), ('mood_open', 'a'),
                     ('shared_first_frame', 'e'), ('close_not_derived', 'd'), ('continuation_gap', 'f'), ('continuation_frame', 'f')):
            self.assertIn(want, found)


class FlashTests(unittest.TestCase):
    def test_strobe_fails_and_ordinary_motion_passes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            strobe = d / 's.mp4'
            ff('-f', 'lavfi', '-i', 'color=c=black:s=64x112:r=24:d=2', '-vf', "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='lt(mod(n,4),2)'",
               '-pix_fmt', 'yuv420p', str(strobe))
            bad = release.flash_check(strobe)
            self.assertFalse(bad['ok'])
            self.assertTrue(bad['failing_windows'])
            self.assertTrue(release.flash_check(moving_clip(d / 'm.mp4', 3))['ok'])


class PlateTests(unittest.TestCase):
    def test_paint_validates_and_refuses_unsafe_svg(self):
        svg = plates.paint(400, 300, '#101a3a', [dict(kind='rect', x=10, y=20, w=100, h=50, fill='#e8a060', depth=2),
                                                 dict(kind='polygon', points=[[0, 300], [200, 150], [400, 300]], fill='#3a5a8c')],
                           palette=['#e8a060', '#3a5a8c'])
        self.assertTrue(svg.startswith('<svg') and 'feDropShadow' in svg)
        with self.assertRaises(plates.PlateError):
            plates.paint(400, 300, '#101a3a', [dict(kind='rect', fill='#ff0000')], palette=['#e8a060'])
        for bad in ('<svg><script>alert(1)</script></svg>', '<svg onload="x()"></svg>', '<svg><image href="http://x/y.png"/></svg>', 'hello'):
            with self.assertRaises(plates.PlateError):
                plates.check_svg(bad)
        self.assertTrue(plates.check_svg('<svg><rect fill="url(#g)"/></svg>'))

    @unittest.skipUnless(HAVE_RENDERER, 'needs node and a headless browser')
    def test_plate_renders_to_png(self):
        with tempfile.TemporaryDirectory() as d:
            svg = plates.paint(200, 120, '#101a3a', [dict(kind='ellipse', cx=100, cy=60, rx=40, ry=30, fill='#ffb870', depth=3)])
            out = plates.render(svg, Path(d) / 'p.png', 200, 120)
            from PIL import Image
            with Image.open(out) as im:
                self.assertEqual(im.size, (200, 120))
                self.assertGreater(im.convert('RGB').getpixel((100, 60))[0], 150)


class CraftApiTests(finish.FinishApiTests):
    # helpers only: the parent's own tests run in their module
    test_triage_on_attach_sound_look_and_release = None
    test_candidates_review_approval_sheet_and_handoff = None

    def attach_all(self, p):
        pid = p['id']
        for s in p['shots']:
            src = self.take('c' + s['id'], max(3, int(s['end'] - s['start']) + 2), s['kind'] == 'spoken')
            body = dict(expected_revision=p['revision'], shot_id=s['id'], source=src)
            if s['kind'] == 'spoken':
                body['heard_words'] = s['text'].replace('.', '').split()
            self.call('POST', f'projects/{pid}/takes', body)
            p = self.call('GET', f'projects/{pid}')
        return p

    def test_prompts_draft_lint_and_audit_warnings(self):
        p = self.board()
        pid = p['id']
        reset = self.call('PATCH', f'projects/{pid}/board', dict(expected_revision=p['revision'], shots=[dict(id=s['id'], prompt='TODO') for s in p['shots']]))
        out = self.call('POST', f'projects/{pid}/prompts/draft', dict(expected_revision=reset['revision'], speaker='she'))
        self.assertEqual(set(out['written']), {s['id'] for s in p['shots']})
        spoken = next(s for s in out['project']['shots'] if s['kind'] == 'spoken')
        self.assertIn('as in the first frame', spoken['prompt'].lower())
        self.assertTrue(all(not [f for f in row['findings'] if f['severity'] == 'error'] for row in out['lint']), out['lint'])
        audit = self.call('GET', f'projects/{pid}/audit')
        self.assertFalse([f for f in audit['findings'] if f['severity'] == 'error' and f['kind'].startswith('prompt_')])
        bad = self.call('PATCH', f'projects/{pid}/board', dict(expected_revision=out['project']['revision'], shots=[
            dict(id=spoken['id'], prompt=f'She stands perfectly still, deadpan: "{spoken["text"]}"')]))
        kinds = {f['kind'] for f in self.call('GET', f'projects/{pid}/audit')['findings'] if f['shot'] == spoken['id']}
        self.assertTrue({'prompt_posture_rule', 'prompt_mood_words'} <= kinds)
        self.assertEqual(self.call('GET', f'projects/{pid}/prompts')['revision'], bad['revision'])

    def test_refine_lines_needs_a_vocal_stem_and_uses_it(self):
        p = self.board()
        pid = p['id']
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/line-times/refine', dict(expected_revision=p['revision']))
        self.assertEqual(e.exception.code, 'line_times_required')
        p = self.call('POST', f'projects/{pid}/align', dict(expected_revision=p['revision'], words=[
            dict(w=w, s=1.0 + i * .3, e=1.2 + i * .3) for i, w in enumerate('I woke up in a city I am not a robot'.split())]))['project']
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/line-times/refine', dict(expected_revision=p['revision']))
        self.assertEqual(e.exception.code, 'vocal_stem_required')
        samples, _ = fx.song(seconds=24, bpm=124)
        fx.write_wav(self.root / 'vocal.wav', samples)
        p = self.call('PATCH', f'projects/{pid}', dict(expected_revision=p['revision'], stems=dict(vocal=self.media(self.root / 'vocal.wav'))))
        out = self.call('POST', f'projects/{pid}/line-times/refine', dict(expected_revision=p['revision']))
        self.assertTrue(all(t['source'] in ('stem', 'transcript') for t in out['project']['line_times']))

    def test_cut_sheets_reviews_and_release_flash(self):
        p = self.attach_all(self.board())
        pid = p['id']
        done = self.call('POST', f'projects/{pid}/render', dict(expected_revision=p['revision'], width=180, height=320))
        sheets = self.call('POST', f'projects/{pid}/cut/sheets', dict(file=done['file']))
        listed = self.call('GET', f'projects/{pid}/files')['files']
        cut = next(f for f in listed if f['file'] == done['file'])
        status, (body, mime) = self.app.agent.dispatch('GET', f"/agent/v1/music-video/projects/{pid}/files/{cut['file_id']}", {}, None)
        self.assertEqual((status, mime, body[4:8]), (200, 'video/mp4', b'ftyp'))
        with self.assertRaises(APIError):
            self.call('GET', f'projects/{pid}/files/0000000000000000')
        self.assertEqual(len(sheets['sheets']), len(p['shots']))
        self.assertTrue(all((self.app.storage / s['file']).is_file() for s in sheets['sheets']))
        self.assertIn('ok', sheets['flash'])
        with self.assertRaises(APIError):
            self.call('POST', f'projects/{pid}/cut/sheets', dict(file='../../etc/passwd'))
        self.app.director_review.set_roles({'reviewer': {'model': 'rev-model'}}, source='human')
        ids = [s['id'] for s in p['shots']]
        review = lambda session, verdict='ok': dict(reviewer=dict(model='rev-model', session_id=session), frames_examined=8 * len(ids), summary='',
                                                     shots=[dict(shot_id=i, verdict=verdict, problem='' if verdict == 'ok' else 'pop at 2s') for i in ids])
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/cut/reviews', dict(expected_revision=p['revision'], file=done['file'], review=dict(review('r1'), shots=[])))
        self.assertEqual(e.exception.code, 'invalid_review')
        one = self.call('POST', f'projects/{pid}/cut/reviews', dict(expected_revision=p['revision'], file=done['file'], review=review('r1')))
        self.assertEqual(one['reviews'], 1)
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/cut/reviews', dict(expected_revision=one['revision'], file=done['file'], review=review('r1')))
        self.assertEqual(e.exception.code, 'reviewer_not_independent')
        two = self.call('POST', f'projects/{pid}/cut/reviews', dict(expected_revision=one['revision'], file=done['file'], review=review('r2', 'blocking')))
        self.assertEqual(two['blocking'], ids)

    def test_last_frame_becomes_the_next_opening_candidate(self):
        p = self.attach_all(self.board())
        pid = p['id']
        made = self.call('POST', f'projects/{pid}/keyframes', dict(expected_revision=p['revision']))
        a, b = p['shots'][0]['id'], p['shots'][1]['id']
        out = self.call('POST', f'projects/{pid}/takes/last-frame', dict(expected_revision=made['revision'], shot_id=a, to_shot=b))
        plan = self.call('GET', f'projects/{pid}/keyframes')['plan']
        still = next(x for s in plan['shots'] for x in s['stills'] if x['name'] == f'{b}-first')
        self.assertEqual((still['candidates'], still['continues'], still['from_take_last_frame']), ([out['asset_id']], a, True))

    def test_transcribe_job_then_align(self):
        p = self.board()
        pid = p['id']
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/transcribe', {})
        self.assertEqual(e.exception.code, 'vocal_stem_required')
        heard = [dict(w=w, s=1.0 + i * .3, e=1.2 + i * .3) for i, w in enumerate('I woke up in a city I am not a robot'.split())]
        self.app.music_video.transcriber = lambda path: heard
        job = self.call('POST', f'projects/{pid}/transcribe', dict(source='master'))
        import time
        for _ in range(100):
            got = self.call('GET', f"transcribe-jobs/{job['id']}")
            if got['status'] in ('done', 'error'):
                break
            time.sleep(.05)
        self.assertEqual(got['status'], 'done', got)
        self.assertEqual(got['words'], heard)
        p = self.call('GET', f'projects/{pid}')
        out = self.call('POST', f'projects/{pid}/align', dict(expected_revision=p['revision'], words=got['words']))
        self.assertEqual(out['unmatched_lines'], [])
        self.app.music_video.transcriber = lambda path: (_ for _ in ()).throw(RuntimeError('model broke'))
        bad = self.call('POST', f'projects/{pid}/transcribe', dict(source='master'))
        for _ in range(100):
            got = self.call('GET', f"transcribe-jobs/{bad['id']}")
            if got['status'] in ('done', 'error'):
                break
            time.sleep(.05)
        self.assertEqual(got['status'], 'error')

    def test_scenes_from_board_are_made_once_and_feed_the_handoff(self):
        p = self.board()
        pid = p['id']
        out = self.call('POST', f'projects/{pid}/scenes', dict(expected_revision=p['revision']))
        self.assertEqual(set(out['scenes']), {s['id'] for s in p['shots']})
        self.assertEqual(len(out['created']), len(p['shots']))
        again = self.call('POST', f'projects/{pid}/scenes', dict(expected_revision=out['revision']))
        self.assertEqual((again['created'], again['scenes']), ([], out['scenes']))
        scene = self.agent('GET', f"scenes/{out['scenes'][p['shots'][0]['id']]}")
        self.assertIn(p['shots'][0]['id'], scene['title'])
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/keyframes/handoff', dict(expected_revision=again['revision']))
        self.assertEqual(e.exception.code, 'keyframes_required')
        kf = self.call('POST', f'projects/{pid}/keyframes', dict(expected_revision=again['revision']))
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/keyframes/handoff', dict(expected_revision=kf['revision']))
        self.assertEqual(e.exception.code, 'nothing_to_hand_off')
        first = kf['plan']['shots'][0]
        asset = self.image()
        kf = self.call('PATCH', f'projects/{pid}/keyframes', dict(expected_revision=kf['revision'], stills=[
            dict(name=x['name'], candidates=[asset]) for x in first['stills']]))
        kf = self.call('PATCH', f'projects/{pid}/keyframes', dict(expected_revision=kf['revision'], stills=[
            dict(name=x['name'], approve=dict(asset_id=asset, human_words='Yes.')) for x in first['stills']]))
        done = self.call('POST', f'projects/{pid}/keyframes/handoff', dict(expected_revision=kf['revision']))
        self.assertEqual([r['shot_id'] for r in done['handed_off']], [first['shot_id']])

    @unittest.skipUnless(HAVE_RENDERER, 'needs node and a headless browser')
    def test_code_shot_and_plate(self):
        p = self.board()
        pid = p['id']
        made = self.call('POST', f'projects/{pid}/previz', dict(expected_revision=p['revision'], story='bedside_machine', width=180, height=320, fps=12))
        visual = next(s for s in p['shots'] if s['kind'] != 'spoken')
        spoken = next(s for s in p['shots'] if s['kind'] == 'spoken')
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/code-shots', dict(expected_revision=made['revision'], shot_id=spoken['id']))
        self.assertEqual(e.exception.code, 'spoken_needs_a_take')
        out = self.call('POST', f'projects/{pid}/code-shots', dict(expected_revision=made['revision'], shot_id=visual['id']))
        take = self.call('GET', f'projects/{pid}')['takes'][visual['id']]
        self.assertTrue(take['code'])
        self.assertGreaterEqual(take['clip_duration'], visual['end'] - visual['start'])
        kf = self.call('POST', f'projects/{pid}/keyframes', dict(expected_revision=out['revision']))
        plate = self.call('POST', f'projects/{pid}/plates', dict(expected_revision=kf['revision'], name='room', width=180, height=320, use_as_set=True,
                                                                 background='#101a3a', layers=[dict(kind='rect', x=20, y=200, w=140, h=60, fill='#e8a060', depth=2)]))
        self.assertTrue((self.app.storage / plate['file']).is_file())
        plan = self.call('GET', f'projects/{pid}/keyframes')['plan']
        self.assertEqual(plan['references']['set'], plate['asset_id'])
        self.assertIn('[set reference]', plan['shots'][0]['stills'][0]['prompt'])
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/plates', dict(expected_revision=plate['revision'], name='bad', svg='<svg><script>x</script></svg>'))
        self.assertEqual(e.exception.code, 'invalid_plate')


if __name__ == '__main__':
    unittest.main()
