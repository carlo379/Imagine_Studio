import unittest

from music_video import board, lyric_text


def analysis(bpm=120, bars=16):
    bar_s = 4 * 60 / bpm
    return dict(duration=bars * bar_s, bars=[round(i * bar_s, 3) for i in range(bars)], bpm=bpm)


SHEET = '[Verse]\nI woke up in a city made of glass.\nEvery window shows a face that I forgot.\n[Hook]\nI am not a robot, I swear.\n'


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.a = analysis()
        self.shots = board.draft(self.a, SHEET)

    def test_draft_is_contiguous_and_on_bars(self):
        ordered = sorted(self.shots, key=lambda s: s['start'])
        self.assertEqual(ordered[0]['start'], 0.0)
        for a, b in zip(ordered, ordered[1:]):
            self.assertAlmostEqual(a['end'], b['start'], places=2)
        self.assertAlmostEqual(ordered[-1]['end'], self.a['duration'], places=2)
        self.assertEqual(sum(s['kind'] == 'spoken' for s in self.shots), 3)

    def test_fresh_draft_fails_audit_until_filled(self):
        r = board.audit(self.shots, self.a, SHEET)
        self.assertFalse(r['ok'])
        self.assertIn('todo', {f['kind'] for f in r['findings']})

    def test_filled_board_passes_and_quote_mismatch_is_caught(self):
        for s in self.shots:
            s['purpose'] = 'beat'
            s['prompt'] = f'She says: "{s["text"]}"' if s['kind'] == 'spoken' else 'City at dusk'
        self.assertTrue(board.audit(self.shots, self.a, SHEET)['ok'])
        spoken = next(s for s in self.shots if s['kind'] == 'spoken')
        spoken['prompt'] = 'She says: "something else"'
        kinds = {f['kind'] for f in board.audit(self.shots, self.a, SHEET)['findings']}
        self.assertIn('quote_mismatch', kinds)

    def test_uncovered_line_and_off_bar_cut(self):
        spoken = [s for s in self.shots if s['kind'] == 'spoken']
        kinds = {f['kind'] for f in board.audit([s for s in self.shots if s is not spoken[0]], self.a, SHEET)['findings']}
        self.assertIn('line_uncovered', kinds)
        self.shots[1]['start'] += .2
        self.assertIn('off_bar', {f['kind'] for f in board.audit(self.shots, self.a, SHEET)['findings']})

    def test_cost_ceiling(self):
        est = board.estimate(self.shots, .05)
        self.assertEqual(est['cost_ceiling'], round(est['planned_seconds'] * 2 * .05, 2))


class LyricTextTests(unittest.TestCase):
    def test_gate_counts_words(self):
        entries = [dict(text='I am not a robot, I swear.', start=1, end=3)]
        self.assertTrue(lyric_text.lyric_gate(entries, 'I am not a robot, I swear.')['ok'])
        self.assertFalse(lyric_text.lyric_gate(entries, 'I am not a robot')['ok'])

    def test_ass_has_one_karaoke_tag_per_word(self):
        ass = lyric_text.build_ass([dict(text='I am not a robot', start=1, end=2.5)])
        self.assertEqual(ass.count('{\\k'), 5)
        self.assertIn('Dialogue: 0,0:00:01.00', ass)


if __name__ == '__main__':
    unittest.main()
