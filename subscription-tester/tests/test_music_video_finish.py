"""Take triage, sound design, color script and grade matching, still review and hand-off, consistency review, release."""
import base64
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import mv_fixtures as fx
from agent_api import APIError
from music_video import audio_io, grade, release, render, review, sound, triage
from studio_server import Studio
from test_music_video_api import SHEET, talk


def ff(*args):
    subprocess.run([audio_io.ffmpeg_path(), '-y', '-v', 'error', *args], check=True)


def flawed_clip(path):
    """2 s of moving test pattern, 0.5 s black, then the pattern frozen for 1.5 s."""
    ff('-f', 'lavfi', '-i', 'testsrc2=s=160x284:r=24:d=2', '-f', 'lavfi', '-i', 'color=c=black:s=160x284:r=24:d=0.5',
       '-filter_complex', '[0:v]split[a][b];[b]trim=start=1.95,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1.5,trim=duration=1.5[f];'
                          '[a][1:v][f]concat=n=3:v=1:a=0,format=yuv420p[v]', '-map', '[v]', str(path))
    return path


def moving_clip(path, seconds=3, color='teal'):
    ff('-f', 'lavfi', '-i', f'testsrc2=s=160x284:r=24:d={seconds}', '-f', 'lavfi', '-i', f'color=c={color}:s=160x284:r=24:d={seconds}',
       '-filter_complex', '[0:v][1:v]blend=all_mode=average,format=yuv420p[v]', '-map', '[v]', str(path))
    return path


def png(color=(40, 60, 120), size=(90, 160)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_scan_finds_black_and_frozen_moments(self):
        r = triage.scan(flawed_clip(self.root / 'f.mp4'))
        kinds = {i['kind'] for i in r['issues']}
        self.assertTrue({'black', 'frozen'} <= kinds, r['issues'])
        black = next(i for i in r['issues'] if i['kind'] == 'black')
        self.assertAlmostEqual(black['start'], 2.0, delta=.2)
        self.assertEqual(r['verdict'], 'flawed')

    def test_best_window_avoids_the_flaws_and_retimes_only_when_allowed(self):
        r = triage.scan(flawed_clip(self.root / 'f.mp4'))
        w = triage.best_window(r, 1.5, beat_offsets=[0, .5, 1.0])
        self.assertTrue(w['ok'])
        self.assertLessEqual(w['in_point_s'] + w['source_span_s'], 2.0 + 1 / 12)
        self.assertEqual(w['flagged'], 0)
        short = triage.scan(moving_clip(self.root / 'm.mp4', seconds=3))
        self.assertFalse(triage.best_window(short, 3.5)['ok'])
        slowed = triage.best_window(short, 3.5, allow_retime=True)
        self.assertTrue(slowed['ok'])
        self.assertLess(slowed['speed'], 1)
        self.assertGreaterEqual(slowed['speed'], triage.MIN_SPEED)

    def test_render_refuses_to_retime_speech(self):
        with self.assertRaises(ValueError):
            render.build_command('s.wav', [dict(clip='c.mp4', start=0, duration=2, speech=True, kind='spoken', speed=.9)], 'o.mp4')


class SoundTests(unittest.TestCase):
    PLACEMENTS = [dict(clip='a.mp4', start=0, duration=4, speech=False, kind='visual', shot='s001'),
                  dict(clip='b.mp4', start=4, duration=4, speech=True, kind='spoken', shot='s002', speech_start=4.6, speech_end=6.8)]

    def test_settings_validate_and_merge(self):
        cfg = sound.settings(None, dict(hum=dict(enabled=True, level_db=-30)))
        self.assertTrue(cfg['hum']['enabled'])
        self.assertEqual(cfg['reveal']['depth_db'], 18.0)
        for bad in (dict(reveal=dict(depth_db=200)), dict(hum=dict(colour=1)), dict(echo={}), dict(reveal=dict(enabled='yes'))):
            with self.assertRaises(sound.SoundError):
                sound.settings(None, bad)

    def test_reveal_dip_hum_and_room_reach_the_render_graph(self):
        cfg = sound.settings(None, dict(hum=dict(enabled=True)))
        frag = sound.filters(cfg, self.PLACEMENTS, 8)
        self.assertEqual(frag['plan']['reveal'], dict(dip_start=4.0, speech_start=4.6, speech_end=6.8, depth_db=18.0))
        cmd = ' '.join(render.build_command('s.wav', self.PLACEMENTS, 'o.mp4', sound=frag))
        self.assertIn("volume='if(lt(t,4.000)", cmd)
        self.assertIn('aevalsrc=', cmd)
        self.assertIn('aecho=', cmd)
        off = sound.filters(sound.settings(None, dict(reveal=dict(enabled=False), voice=dict(room=0))), self.PLACEMENTS, 8)
        self.assertEqual((off['music'], off['voice'], off['hum']), ('', '', None))

    def test_dip_expression_reaches_the_floor(self):
        expr = sound.dip_expression(1, 3, .25, 1, 20)
        value = lambda t: eval(expr.replace('if(', 'iff(').replace('lt(', 'ltf('), dict(iff=lambda c, a, b: a if c else b, ltf=lambda a, b: a < b, t=t))
        self.assertAlmostEqual(value(0), 1)
        self.assertAlmostEqual(value(2), .1, places=3)
        self.assertAlmostEqual(value(5), 1)


class GradeTests(unittest.TestCase):
    def test_color_script_follows_sections_and_overrides(self):
        shots = [dict(id='s1', start=0, end=2, section=None), dict(id='s2', start=2, end=4, section='Verse 1'),
                 dict(id='s3', start=4, end=6, section='Hook'), dict(id='s4', start=6, end=8, section='Final')]
        rows = grade.color_script(shots)
        self.assertIn('moonlight', rows[1]['phrase'])
        self.assertIn('cyan', rows[3]['phrase'])
        look = grade.settings(None, dict(sections={'Hook': dict(phrase='red neon', palette=['#ff0000'])}))
        self.assertEqual(grade.color_script(shots, look)[2]['phrase'], 'red neon')
        for bad in (dict(grain=3), dict(sections={'x': dict(phrase='a', palette=['red'])}), dict(match='yes')):
            with self.assertRaises(grade.GradeError):
                grade.settings(None, bad)
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(Path(grade.strip(rows, Path(d) / 's.png')).is_file())

    def test_match_moves_toward_the_reference_within_limits(self):
        take = dict(r=[100, 20], g=[100, 20], b=[100, 20])
        ref = dict(r=[140, 20], g=[100, 20], b=[60, 80])
        c = grade.match(take, ref, strength=1)
        self.assertAlmostEqual(c['r'][0] * 100 + c['r'][1], 140, delta=.5)
        self.assertLessEqual(c['b'][0], 1.4)
        self.assertIn("lutrgb=r='clip(val*", grade.lut_filter(c))

    def test_stats_reads_images_and_video(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'r.png').write_bytes(base64.b64decode(png((200, 50, 50)).split(',')[1]))
            s = grade.stats(d / 'r.png')
            self.assertAlmostEqual(s['r'][0], 200, delta=1)
            v = grade.stats(moving_clip(d / 'm.mp4', 2), start=0, length=2)
            self.assertTrue(all(0 < v[c][0] < 255 for c in 'rgb'))


class ReviewTests(unittest.TestCase):
    GOOD = dict(reviewer=dict(model='rev', session_id='r1'), scores=dict(person=9, machine=8, room=9, look=8), issues=[], images_examined=4, summary='ok')

    def test_validation_and_suggestion(self):
        self.assertEqual(review.validate(dict(self.GOOD))['suggestion'], 'consistent')
        weak = dict(self.GOOD, scores=dict(person=7, machine=9, room=9, look=9))
        self.assertEqual(review.validate(weak)['suggestion'], 'usable_with_fixes')
        blocked = dict(self.GOOD, issues=[dict(severity='blocking', aspect='person', problem='different face', fix='attach the sheet')])
        self.assertEqual(review.validate(blocked)['suggestion'], 'regenerate')
        with self.assertRaises(review.ReviewError):
            review.validate(dict(self.GOOD), chosen_reviewer=dict(model='other'))
        with self.assertRaises(review.ReviewError):
            review.validate(dict(self.GOOD), director_session='r1')
        for bad in (dict(self.GOOD, scores=dict(person=9)), dict(self.GOOD, images_examined=0), dict(self.GOOD, extra=1)):
            with self.assertRaises(review.ReviewError):
                review.validate(bad)

    def test_sheet_and_local_checks(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'a.png').write_bytes(base64.b64decode(png().split(',')[1]))
            (d / 'wide.png').write_bytes(base64.b64decode(png(size=(160, 90)).split(',')[1]))
            (d / 'bad.png').write_bytes(b'nope')
            rows = [dict(label='s001-first', line='Hush now', previz=None, candidates=[dict(label='A', path=d / 'a.png', approved=True, suggestion='consistent'),
                                                                                         dict(label='B', path=d / 'bad.png')])]
            self.assertTrue(Path(review.sheet(rows, d / 'sheet.png')).is_file())
            self.assertEqual([x['kind'] for x in review.local_checks(d / 'wide.png')], ['wrong_shape', 'small'])
            self.assertEqual(review.local_checks(d / 'bad.png')[0]['kind'], 'unreadable')


class ReleaseTests(unittest.TestCase):
    def test_srt_hook_and_thumbnails(self):
        text = release.srt([dict(text='Second line', start=3.5, end=5), dict(text='First', start=1.0, end=1.2)])
        self.assertTrue(text.startswith('1\n00:00:01,000 --> 00:00:01,500\nFirst\n'))
        self.assertIn('2\n00:00:03,500 --> 00:00:05,000\nSecond line', text)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dark = d / 'dark.mp4'
            ff('-f', 'lavfi', '-i', 'color=c=black:s=160x284:r=24:d=4', '-pix_fmt', 'yuv420p', str(dark))
            kinds = {f['kind'] for f in release.hook_check(dark, [dict(start=0, end=4)])['findings']}
            self.assertTrue({'black_open', 'dark_open', 'static_open', 'slow_first_cut'} <= kinds)
            lively = moving_clip(d / 'm.mp4', 6)
            self.assertTrue(release.hook_check(lively, [dict(start=0, end=1.5), dict(start=1.5, end=6)])['ok'])
            thumbs = release.thumbnails(lively, d / 'kit', [dict(start=0), dict(start=3)], count=2)
            self.assertEqual(len(thumbs), 2)
            self.assertGreaterEqual(abs(thumbs[0]['t'] - thumbs[1]['t']), 2)
            self.assertTrue(all(t['file'].is_file() for t in thumbs))


class FinishApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Studio(mock=True, storage=self.root / 'state')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.app.productions.sql.close)
        self.app.update(signed_in=True)
        network = patch('httpx.Client')
        network.start()
        self.addCleanup(network.stop)
        self.app.generate = Mock(side_effect=AssertionError('No provider generation allowed'))
        self.app.begin = Mock(side_effect=AssertionError('No provider action allowed'))
        self.production = self.app.productions.dispatch('POST', [], dict(kind='quick', title='MV'))[1]['production']

    def call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/music-video/' + path, data or {}, None)[1]

    def agent(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/' + path, data or {}, None)[1]

    def media(self, path):
        m = self.app.editing.upload(dict(name=path.name, base64=base64.b64encode(path.read_bytes()).decode()))
        return dict(kind='upload', id=m['id'])

    def take(self, name, seconds, speech):
        path = self.root / f'{name}.mp4'
        if speech:
            fx.write_wav(self.root / f'{name}.wav', talk([(.6 + i * .25, .17) for i in range(8)], seconds))
            ff('-f', 'lavfi', '-i', f'testsrc2=s=160x284:r=24:d={seconds}', '-i', str(self.root / f'{name}.wav'), '-shortest', '-pix_fmt', 'yuv420p', str(path))
        else:
            moving_clip(path, seconds)
        return self.media(path)

    def image(self, color=(40, 60, 120)):
        return self.app.upload({'name': 'still.png', 'data_url': png(color)})['id']

    def board(self):
        samples, _ = fx.song(seconds=24, bpm=124)
        fx.write_wav(self.root / 'song.wav', samples)
        p = self.call('POST', 'projects', dict(title='Video', production_id=self.production['id'], mode='spoken_hooks',
                                               master=self.media(self.root / 'song.wav'), lyrics=SHEET))
        p = self.call('POST', f"projects/{p['id']}/analyze", dict(expected_revision=p['revision']))
        p = self.call('POST', f"projects/{p['id']}/board/draft", dict(expected_revision=p['revision']))
        edits = [dict(id=s['id'], purpose='beat', prompt=f'She says: "{s["text"]}"' if s['kind'] == 'spoken' else 'Neon street, slow push in. No speech.')
                 for s in p['shots']]
        return self.call('PATCH', f"projects/{p['id']}/board", dict(expected_revision=p['revision'], shots=edits))

    def test_triage_on_attach_sound_look_and_release(self):
        p = self.board()
        pid = p['id']
        visual = next(s for s in p['shots'] if s['kind'] != 'spoken')
        probe = self.call('POST', f'projects/{pid}/triage', dict(shot_id=visual['id'], source=self.take('probe', 2, False)))
        self.assertIn('window', probe)
        for s in p['shots']:
            slot = s['end'] - s['start']
            src = self.take('c' + s['id'], max(3, int(slot) + 2), s['kind'] == 'spoken')
            body = dict(expected_revision=p['revision'], shot_id=s['id'], source=src)
            if s['kind'] == 'spoken':
                body['heard_words'] = s['text'].replace('.', '').split()
            out = self.call('POST', f'projects/{pid}/takes', body)
            self.assertIn('triage', out['take'])
            if s['kind'] != 'spoken':
                self.assertTrue(out['take']['window']['ok'], out['take']['window'])
            p = self.call('GET', f'projects/{pid}')
        with self.assertRaises(APIError):
            self.call('POST', f'projects/{pid}/takes', dict(expected_revision=p['revision'], shot_id=visual['id'], source=src, window=dict(in_point_s=0, speed=.5)))
        snd = self.call('PATCH', f'projects/{pid}/sound', dict(expected_revision=p['revision'], sound=dict(hum=dict(enabled=True))))
        look = self.call('PATCH', f'projects/{pid}/look', dict(expected_revision=snd['revision'], look=dict(grain=.4)))
        self.assertTrue((self.app.storage / look['strip']).is_file())
        self.assertEqual(len(look['color_script']), len(p['shots']))
        plan = self.call('POST', f'projects/{pid}/render-plan', dict(expected_revision=look['revision'], width=180, height=320))
        self.assertIn('reveal', plan['sound'])
        self.assertIn('hum', plan['sound'])
        out = self.call('POST', f'projects/{pid}/release', dict(expected_revision=look['revision'], formats=['9:16', '16:9'], max_side=320, thumbnails=2))
        for f, (w, h) in {'9:16': (180, 320), '16:9': (320, 180)}.items():
            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                                    str(self.app.storage / out['formats'][f]['file'])], capture_output=True, text=True).stdout.strip()
            self.assertEqual(probe, f'{w},{h}')
        self.assertIn('findings', out['hook'])
        self.assertEqual(len(out['thumbnails']), 2)
        self.assertIn('-->', (self.app.storage / out['captions']).read_text())

    def test_candidates_review_approval_sheet_and_handoff(self):
        p = self.board()
        pid = p['id']
        self.app.director_review.set_roles({'reviewer': {'model': 'rev-model'}}, source='human')
        refs = dict(character=self.image(), machine=self.image())
        made = self.call('POST', f'projects/{pid}/keyframes', dict(expected_revision=p['revision'], references=refs))
        spoken = next(s for s in made['plan']['shots'] if s['kind'] == 'spoken')
        a, b, last = self.image((50, 70, 130)), self.image((200, 0, 0)), self.image()
        with self.assertRaises(APIError) as e:
            self.call('PATCH', f'projects/{pid}/keyframes', dict(expected_revision=made['revision'], stills=[dict(name=f"{spoken['shot_id']}-first", candidates=['nope'])]))
        self.assertEqual(e.exception.code, 'unknown_asset')
        first, closing = f"{spoken['shot_id']}-first", f"{spoken['shot_id']}-last"
        plan = self.call('PATCH', f'projects/{pid}/keyframes', dict(
            expected_revision=made['revision'], agent=dict(model='director-model', session_id='d1'),
            stills=[dict(name=first, candidates=[a, b]), dict(name=closing, candidates=[last], made_from_first=True)]))
        self.assertEqual(plan['check']['progress']['with_candidates'], 2)
        packet = self.call('POST', f'projects/{pid}/keyframes/packet', dict(still=first, asset_id=a))
        self.assertEqual(set(packet['references']), {'character', 'machine'})
        self.assertEqual(packet['reviewer_model'], 'rev-model')
        self.assertEqual(packet['local_checks'][0]['kind'], 'small')
        good = dict(ReviewTests.GOOD, reviewer=dict(model='rev-model', session_id='r9'))
        for reviewer, code in ((dict(model='other', session_id='r9'), 'wrong_reviewer_model'), (dict(model='rev-model', session_id='d1'), 'reviewer_not_independent')):
            with self.assertRaises(APIError) as e:
                self.call('POST', f'projects/{pid}/keyframes/reviews', dict(expected_revision=plan['revision'], still=first, asset_id=a, review=dict(good, reviewer=reviewer)))
            self.assertEqual(e.exception.code, code)
        rev = self.call('POST', f'projects/{pid}/keyframes/reviews', dict(expected_revision=plan['revision'], still=first, asset_id=a, review=good))
        self.assertEqual(rev['review']['suggestion'], 'consistent')
        with self.assertRaises(APIError):
            self.call('PATCH', f'projects/{pid}/keyframes', dict(expected_revision=rev['revision'], stills=[dict(name=first, approve=dict(asset_id=a, human_words=' '))]))
        plan = self.call('PATCH', f'projects/{pid}/keyframes', dict(expected_revision=rev['revision'], stills=[
            dict(name=first, approve=dict(asset_id=a, human_words='Use A, it is her.'))]))
        sheet = self.call('POST', f'projects/{pid}/keyframes/sheet', dict(shots=[spoken['shot_id']]))
        self.assertTrue((self.app.storage / sheet['sheets'][0]['file']).is_file())
        scene = self.agent('POST', 'scenes', {'title': 'Reveal', 'scene': {'prompt': 'The machine opens its eyes.'}})
        with self.assertRaises(APIError) as e:
            self.call('POST', f'projects/{pid}/keyframes/handoff', dict(expected_revision=plan['revision'], scenes={spoken['shot_id']: scene['id']}))
        self.assertEqual(e.exception.code, 'still_not_approved')          # the closing still is not approved yet
        plan = self.call('PATCH', f'projects/{pid}/keyframes', dict(expected_revision=plan['revision'], stills=[
            dict(name=closing, approve=dict(asset_id=last, human_words='Yes, that ending.'))]))
        done = self.call('POST', f'projects/{pid}/keyframes/handoff', dict(expected_revision=plan['revision'], scenes={spoken['shot_id']: scene['id']}))
        row = done['handed_off'][0]
        self.assertNotIn('first_frame', row['kit_missing'])
        self.assertNotIn('last_frame', row['kit_missing'])
        self.assertNotIn('last_from_first', row['kit_missing'])
        kit = self.agent('GET', f"scenes/{scene['id']}/kit")
        self.assertTrue(kit['checks'])


if __name__ == '__main__':
    unittest.main()
