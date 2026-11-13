import subprocess
import tempfile
import unittest
from pathlib import Path

import math
import mv_fixtures as fx
from music_video import audio_io, board, modes, render

SHEET = ('[Verse]\nI woke up in a city made of glass.\nEvery window shows a face that I forgot.\n'
         '[Hook]\nI am not a robot, I swear.\n[Verse 2]\nThe rain keeps falling on the empty street.\n')


def analysis(bpm=120, bars=20):
    bar_s = 4 * 60 / bpm
    return dict(duration=bars * bar_s, bars=[round(i * bar_s, 3) for i in range(bars)], bpm=bpm)


def fill(shots):
    for s in shots:
        s['purpose'] = 'beat'
        if s['kind'] == 'spoken':
            s['prompt'] = f'She looks at camera and says: "{s["text"]}"'
        else:
            s['prompt'] = 'Rain on a neon street at dusk, slow push in. No speech.'
    return shots


class DeliveryTests(unittest.TestCase):
    a = analysis()

    def kinds(self, mode, **kw):
        return [(s['kind'], s.get('line')) for s in board.draft(self.a, SHEET, mode=mode, **kw) if s['kind'] != 'cutaway']

    def test_spoken_word_speaks_every_line(self):
        self.assertEqual({k for k, _ in self.kinds('spoken_word')}, {'spoken'})

    def test_hooks_speak_only_the_hook_and_song_carries_the_rest(self):
        kinds = dict((l, k) for k, l in self.kinds('spoken_hooks'))
        self.assertEqual(kinds, {0: 'sung_cut', 1: 'sung_cut', 2: 'spoken', 3: 'sung_cut'})

    def test_explicit_line_choice_overrides(self):
        kinds = dict((l, k) for k, l in self.kinds('muted_spans', spoken_lines=[0, 3]))
        self.assertEqual([kinds[i] for i in range(4)], ['spoken', 'sung_cut', 'sung_cut', 'spoken'])

    def test_visual_shots_never_generate_audio(self):
        for s in board.draft(self.a, SHEET, mode='spoken_hooks'):
            self.assertEqual(s.get('audio', 'none'), 'take' if s['kind'] == 'spoken' else 'none')

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            board.draft(self.a, SHEET, mode='lip_sync_singing')


class AuditRuleTests(unittest.TestCase):
    a = analysis()

    def kinds(self, shots, **kw):
        return {f['kind'] for f in board.audit(shots, self.a, SHEET, **kw)['findings']}

    def test_clean_hooks_board_passes(self):
        shots = fill(board.draft(self.a, SHEET, mode='spoken_hooks'))
        r = board.audit(shots, self.a, SHEET, mode='spoken_hooks')
        self.assertTrue(r['ok'], r['findings'])

    def test_grok_audio_on_a_visual_shot_is_an_error(self):
        shots = fill(board.draft(self.a, SHEET, mode='spoken_hooks'))
        next(s for s in shots if s['kind'] == 'sung_cut')['audio'] = 'take'
        self.assertIn('grok_audio_in_visual_shot', self.kinds(shots))

    def test_singing_or_quoting_in_a_visual_prompt_is_an_error(self):
        for bad in ('She sings to the camera', 'Her lips move as she mouths the words', 'Caption "hello"'):
            shots = fill(board.draft(self.a, SHEET, mode='spoken_hooks'))
            next(s for s in shots if s['kind'] == 'sung_cut')['prompt'] = bad
            self.assertIn('vocal_in_visual_prompt', self.kinds(shots), bad)
        shots = fill(board.draft(self.a, SHEET, mode='spoken_hooks'))
        next(s for s in shots if s['kind'] == 'sung_cut')['prompt'] = 'Wide street, no singing, no speech.'
        self.assertNotIn('vocal_in_visual_prompt', self.kinds(shots))

    def test_spoken_word_rejects_a_song_with_vocals(self):
        shots = fill(board.draft(self.a, SHEET, mode='spoken_word'))
        self.assertIn('song_has_vocals', self.kinds(shots, options=dict(song_has_vocals=True)))

    def test_muted_spans_needs_both_stems(self):
        shots = fill(board.draft(self.a, SHEET, mode='muted_spans'))
        k = self.kinds(shots)
        self.assertTrue({'missing_vocal_stem', 'missing_instrumental_stem'} <= k)
        self.assertFalse({'missing_vocal_stem', 'missing_instrumental_stem'} & self.kinds(shots, options=dict(vocal_stem='v.wav', instrumental_stem='i.wav')))

    def test_spoken_shot_must_generate_audio(self):
        shots = fill(board.draft(self.a, SHEET, mode='spoken_word'))
        shots[0]['audio'] = 'none'
        self.assertIn('spoken_audio_off', self.kinds(shots))


class SpanTests(unittest.TestCase):
    def test_mute_spans_pad_and_merge(self):
        self.assertEqual(modes.mute_spans([(10, 12), (12.05, 14), (20, 21)], pad=.1), [[9.9, 14.1], [19.9, 21.1]])

    def test_gain_expression(self):
        self.assertEqual(modes.gain_expression([]), '1')
        self.assertIn('clip(min', modes.gain_expression([(1, 2)]))

    def test_speech_spans_prefers_measured(self):
        shots = [dict(kind='spoken', id='s1', start=4.0, end=8.0, speech_s=2.0, lead_in_s=.3)]
        self.assertEqual(modes.speech_spans(shots), [(4.3, 6.3)])
        self.assertEqual(modes.speech_spans(shots, [dict(shot='s1', speech_start=4.5, speech_end=6.9)]), [(4.5, 6.9)])


class RenderModeTests(unittest.TestCase):
    def test_generated_singing_audio_is_refused(self):
        with self.assertRaises(ValueError):
            render.build_command('s.wav', [dict(clip='a.mp4', start=0, duration=2, speech=True, kind='sung_cut')], 'o.mp4')

    def test_muted_spans_requires_stems(self):
        with self.assertRaises(ValueError):
            render.build_command('s.wav', [dict(clip='a.mp4', start=0, duration=2)], 'o.mp4', mode='muted_spans')

    def test_muted_spans_silences_only_the_vocal_in_the_span(self):
        ff = audio_io.ffmpeg_path()
        rate = fx.RATE
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inst, _ = fx.song(seconds=8)
            vocal = [.3 * math.sin(2 * math.pi * 1000 * i / rate) for i in range(8 * rate)]
            fx.write_wav(d / 'inst.wav', inst)
            fx.write_wav(d / 'vocal.wav', vocal)
            fx.write_wav(d / 'song.wav', [a + b for a, b in zip(inst, vocal)])
            subprocess.run([ff, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=green:s=160x120:d=8:r=24', '-pix_fmt', 'yuv420p', str(d / 'a.mp4')], check=True)
            cmd = render.build_command(d / 'song.wav', [dict(clip=d / 'a.mp4', start=0, duration=8, speech=False, kind='sung_cut')],
                                       d / 'o.mp4', 160, 120, mode='muted_spans', vocal_stem=d / 'vocal.wav',
                                       instrumental_stem=d / 'inst.wav', mute_spans=[[3.0, 5.0]], song_end=8)
            render.run(cmd)
            def level(a, b):
                x = audio_io.decode(d / 'o.mp4', filter_chain='bandpass=f=1000:width_type=h:w=200', start=a, length=b - a)
                return (sum(v * v for v in x) / len(x)) ** .5
            inside, outside = level(3.3, 4.7), level(0.5, 2.5)
            self.assertLess(inside, outside * .1, (inside, outside))


if __name__ == '__main__':
    unittest.main()
