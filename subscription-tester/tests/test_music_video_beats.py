import statistics
import tempfile
import unittest
from pathlib import Path

import mv_fixtures as fx
from music_video import beats


class BeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        samples, cls.truth = fx.song()
        cls.path = Path(cls.dir.name) / 'song.wav'
        fx.write_wav(cls.path, samples)
        cls.result = beats.analyze(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_tempo(self):
        self.assertAlmostEqual(self.result['bpm'], 124, delta=1.5)
        self.assertTrue(self.result['tempo_steady'])

    def test_beats_land_on_kicks(self):
        errors = [min(abs(b - t) for b in self.result['beats']) for t in self.truth[2:-2]]
        self.assertLess(statistics.median(errors), .02)
        self.assertLess(max(errors), .05)

    def test_downbeat_phase_is_a_valid_guess_and_bars_follow_it(self):
        r = self.result
        self.assertEqual(r['phase_source'], 'guess')
        first_bar = r['bars'][0]
        index = min(range(len(self.truth)), key=lambda i: abs(self.truth[i] - first_bar))
        self.assertEqual(index % 4, 0, 'the first bar line must be a downbeat of the synthetic song')

    def test_director_phase_overrides_without_reanalysis(self):
        r = beats.rebar(self.result, (self.result['downbeat_phase'] + 1) % 4)
        self.assertEqual(r['phase_source'], 'director')
        self.assertNotEqual(r['bars'][0], self.result['bars'][0])

    def test_sections_cover_the_song_on_bar_lines(self):
        s = self.result['sections']
        self.assertEqual(s[0]['start'], 0.0)
        self.assertAlmostEqual(s[-1]['end'], self.result['duration'], places=2)
        for a, b in zip(s, s[1:]):
            self.assertEqual(a['end'], b['start'])
            self.assertIn(b['start'], self.result['bars'])

    def test_snap(self):
        self.assertEqual(beats.snap(1.01, [1.0, 2.0], .05), 1.0)
        self.assertEqual(beats.snap(1.5, [1.0, 2.0], .05), 1.5)

    def test_silence_is_refused(self):
        p = Path(self.dir.name) / 'silence.wav'
        fx.write_wav(p, [0.0] * fx.RATE * 4)
        with self.assertRaises(ValueError):
            beats.analyze(p)


if __name__ == '__main__':
    unittest.main()
