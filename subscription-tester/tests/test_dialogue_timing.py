import unittest
from video_prompt_checks import checks, dialogue_words, blocked

class DialogueTimingTests(unittest.TestCase):
    def test_thirty_words_need_thirteen_seconds_without_changing_the_scene(self):
        line=' '.join(['word']*30)
        scene=dict(prompt='[Audio]\nHero says: “'+line+'”',duration=10,audio=True)
        warnings=[i for i in checks(scene) if i['code']=='dialogue_timing']
        self.assertEqual(len(warnings),1);self.assertIn('30 spoken words need about 13s',warnings[0]['message'])
        self.assertFalse(blocked(warnings));self.assertEqual(scene['duration'],10)
        scene['duration']=13
        self.assertNotIn('dialogue_timing',[i['code'] for i in checks(scene)])

    def test_multiple_speakers_script_fallback_and_visual_quotes(self):
        self.assertEqual(dialogue_words('Hero: "One two." Friend: “Three four.”'),4)
        self.assertEqual(dialogue_words('Hero says "Don’t stop moving."'),3)
        self.assertEqual(dialogue_words('A sign reads "These words are not spoken dialogue."'),0)
        line='Hero: "'+' '.join(['word']*30)+'"'
        issues=checks(dict(prompt=line,duration=10,audio=True),script=line)
        warning=next(i for i in issues if i['code']=='dialogue_timing')
        self.assertIn('30 spoken words',warning['message'])
        self.assertIn('dialogue_timing',[i['code'] for i in checks(dict(prompt='Locked camera.',duration=10,audio=True),script=line)])
