"""Provider prose stays identical across browser and agent authoring paths."""
import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from agent_api import AgentAPI, blank


class NamedSceneParityTests(unittest.TestCase):
    def test_image_identity_voice_dialogue_reorder_and_legacy_cleanup(self):
        if not shutil.which('node'):self.skipTest('Node is required for browser compiler parity')
        api=AgentAPI.__new__(AgentAPI)
        api.normalize=copy.deepcopy
        robot=dict(id='robot',title='SampleHero',handle='SampleHero2',category='Character',
                   description='Long biography and an obsolete appearance.',video_summary='Wrong gold boots.',
                   refIds=['front','side'],voiceId='robot-voice')
        location=dict(id='set',title='Family Home',handle='Home',category='Location',
                      description='Long architectural description.',refIds=['set'],voiceId=None)
        narrator=dict(id='speaker',title='Narrator',handle='Narrator',category='Character',
                      description='Warm conversational delivery.',refIds=[],voiceId='narrator-voice')
        base={**blank(), 'prompt':'@SampleHero2 looks toward @Home. Mark says: "You wore it!"',
              'refs':[dict(id=name) for name in ('front','side','set')],
              'voices':[dict(id='robot-voice'),dict(id='narrator-voice')],
              'named':[robot,location,narrator]}
        scenes=[base,{**base,'first':dict(id='opening')},
                {**base,'refs':list(reversed(base['refs'])),'voices':list(reversed(base['voices']))},
                {**base,'prompt':base['prompt']+'\n\nAsset cues:\n@SampleHero2: Wrong gold boots.\n@Home: Long architectural description.\n\nReference context:\nCharacter: SampleHero (<IMAGE_8>). Stale biography.'}]
        for scene in scenes:
            with self.subTest(first=bool(scene['first']),refs=scene['refs']):
                expected=api.expanded_prompt(scene)
                script="const n=require('./static/named-scene.js'),s=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(n.expand(s.prompt,s.named,s.refs,s.audio?s.voices:[],s.first)));"
                result=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(scene).encode(),cwd=Path(__file__).resolve().parents[1]))
                self.assertEqual(result['errors'],[])
                self.assertEqual(result['prompt'],expected)
                self.assertEqual(expected.count("Preserve SampleHero's exact appearance"),1)
                self.assertNotIn('SampleHero2',expected)
                self.assertNotIn('Wrong gold boots',expected)
                self.assertNotIn('biography',expected)
                self.assertNotIn('architectural description',expected)
                self.assertIn('Warm conversational delivery.',expected)
                self.assertIn('Mark says: "You wore it!"',expected)
                self.assertEqual(api.expanded_prompt({**scene,'prompt':expected}),expected)


if __name__=='__main__':unittest.main()
