import math
import random
import tempfile
import unittest
from pathlib import Path

import mv_fixtures as fx
from music_video import lyrics, speech


def talk(bursts, total, rate=fx.RATE, seed=1):
    """Speech-like audio: syllable bursts (start, length) of voiced noise over silence."""
    rng = random.Random(seed)
    out = [0.0] * int(total * rate)
    for start, length in bursts:
        for i in range(int(length * rate)):
            j = int(start * rate) + i
            if j < len(out):
                out[j] = .5 * math.sin(math.pi * i / (length * rate)) * math.sin(2 * math.pi * 180 * j / rate) * (.8 + .2 * rng.random())
    return out


class LyricTests(unittest.TestCase):
    sheet = '[Verse - spoken]\nLook one. Plus twenty-five.\nI am not a robot, I swear.\n\n[Hook]\nA G I\n'

    def test_parse_skips_tags_and_keeps_order(self):
        lines = lyrics.parse(self.sheet)
        self.assertEqual([l['text'] for l in lines][0], 'Look one. Plus twenty-five.')
        self.assertEqual(lines[2]['section'], 'Hook')
        self.assertEqual(len(lines), 3)

    def test_lint_flags_digits_and_acronyms(self):
        kinds = {i['kind'] for i in lyrics.lint('Take 5 steps\nA G I\nTHE END\n+25%')}
        self.assertTrue({'digits', 'symbols', 'acronym'} <= kinds)

    def test_syllables(self):
        self.assertEqual([lyrics.syllables(w) for w in ('robot', 'swear', 'twenty', 'make')], [2, 1, 2, 1])

    def test_fit_flags_long_and_sparse(self):
        lines = lyrics.parse('Hi.\n' + ' '.join(['wonderful'] * 22) + '.')
        fit = lyrics.fit_to_grid(lines, bar_seconds=1.9)
        self.assertEqual(fit[0]['verdict'].split(':')[0], 'sparse')
        self.assertTrue(fit[1]['verdict'].startswith('too_long'))

    def test_studio_rule_matches(self):
        t = lyrics.spoken_seconds(lyrics.parse('one two three four five')[0])
        self.assertEqual(t['studio_clip_s'], 3.0)


class SpeechTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        bursts = [(.8 + i * .24, .16) for i in range(10)]
        cls.path = Path(cls.dir.name) / 'take.wav'
        fx.write_wav(cls.path, talk(bursts, 4.0))
        cls.take = speech.measure(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_measures_speech_window_and_syllables(self):
        t = self.take
        self.assertTrue(t['speech'])
        self.assertAlmostEqual(t['first_speech_s'], .8, delta=.06)
        self.assertAlmostEqual(t['last_speech_s'], .8 + 9 * .24 + .16, delta=.08)
        self.assertAlmostEqual(t['syllables_heard'], 10, delta=2)

    def test_silence_has_no_speech(self):
        p = Path(self.dir.name) / 'quiet.wav'
        fx.write_wav(p, [0.0] * fx.RATE * 2)
        self.assertFalse(speech.measure(p)['speech'])

    def test_place_on_beat_slips_not_stretches(self):
        beats = [i * .5 for i in range(40)]
        placed = speech.place_on_beat(self.take, beats, target_start=4.0)
        self.assertTrue(placed['ok'])
        self.assertAlmostEqual(placed['timeline_start_s'] + self.take['first_speech_s'], placed['lands_on_beat_s'], places=2)
        self.assertLessEqual(abs(placed['slip_s']), .35)

    def test_place_refuses_a_large_slip(self):
        beats = [4.0 + 10 * i for i in range(3)]
        self.assertFalse(speech.place_on_beat(self.take, beats, 4.0, max_slip=.05)['ok'] and False)
        far = speech.place_on_beat(self.take, [5.9], target_start=4.0, max_slip=.2)
        self.assertFalse(far['ok'])

    def test_word_error_rate(self):
        ok = speech.compare_words('I am not a robot', ['i', 'am', 'not', 'a', 'robot'])
        bad = speech.compare_words('I am not a robot', ['i', 'am', 'a', 'bottle'])
        self.assertEqual(ok['verdict'], 'match')
        self.assertEqual(bad['verdict'], 'mismatch')

    def test_pace_check(self):
        self.assertTrue(speech.pace_check(self.take, 2.4)['ok'])
        self.assertFalse(speech.pace_check(self.take, 1.0)['ok'])


if __name__ == '__main__':
    unittest.main()


class AlignTests(unittest.TestCase):
    sheet = 'Hush now, little model.\nGoodnight. The door is open.\nSing it again.'

    def heard(self, words, start=1.0, step=.4):
        return [dict(w=w, s=round(start + i * step, 3), e=round(start + i * step + .3, 3)) for i, w in enumerate(words)]

    def test_lines_get_times_despite_a_split_word_and_a_misheard_word(self):
        heard = self.heard('hush now little modal good night the door is open sing it again'.split())
        t = lyrics.align_words(self.sheet, heard)
        self.assertEqual([x['line'] for x in t], [0, 1, 2])
        self.assertEqual(t[0]['start'], 1.0)
        self.assertEqual(t[1]['start'], heard[4]['s'])            # "good night" starts line 1
        self.assertEqual(t[2]['end'], heard[-1]['e'])

    def test_missing_line_is_reported_not_guessed(self):
        t = lyrics.align_words(self.sheet, self.heard('hush now little model sing it again'.split()))
        self.assertIsNone(t[1]['start'])
        self.assertIsNotNone(t[2]['start'])


class CompareTests(unittest.TestCase):
    def test_punctuation_and_case_in_a_transcript_do_not_count_as_errors(self):
        r = speech.compare_words('Hush now, little model.', ['Hush', 'now,', 'little', 'model.'])
        self.assertEqual(r['errors'], 0)
