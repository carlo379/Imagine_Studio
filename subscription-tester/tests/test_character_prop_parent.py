import copy
import unittest
from agent_api import APIError
from script_production import ScriptProduction

class CharacterPropParentTests(unittest.TestCase):
    def test_character_sheet_supplies_hat_reference_without_duplicate_prop(self):
        planner=ScriptProduction.__new__(ScriptProduction)
        source='SCENE 1 — INT. STUDIO — DAY\nSampleHero wears a brown striped scarf.'
        foundation={'id':'samplehero','name':'SampleHero','category':'Character','description':'Robot wearing a brown striped scarf.','reference':{'images':[{'asset_id':'sheet'}]}}
        mention={'id':'hat','name':'brown striped scarf','category':'Prop','description':'A brown hat.','asset_id':None,'candidate_ids':[],'container_candidate_ids':['samplehero'],'review_required':True}
        job={'source_script':source,'catalog':[foundation],'completion':{'reviewed':True,'mentions':[mention],'resolutions':{'hat':'included:samplehero'},'accepted_dialogue':[],'dialogue_changes':[]},'result':{'assets':[],'scenes':[{'title':'SCENE 1 — INT. STUDIO — DAY','text':'SampleHero wears a brown striped scarf.','shots':[{'title':'SampleHero','image_prompt':'SampleHero wears a brown striped scarf.','video_prompt':'SampleHero adjusts his brown striped scarf.','asset_mentions':['hat']}]}]}}
        original=copy.deepcopy(job)
        plan,reused=planner.final_plan(job)
        self.assertEqual(plan['assets'],[])
        self.assertEqual(reused,[foundation])
        shot=plan['scenes'][0]['shots'][0]
        self.assertEqual(shot['asset_ids'],['samplehero']);self.assertEqual(shot['characters'],['SampleHero'])
        self.assertEqual(shot['contained_assets'][0]['name'],'brown striped scarf')
        self.assertIn('brown striped scarf (Prop) is included in SampleHero (Character)',shot['image_prompt'])
        self.assertEqual(plan['scenes'][0]['text'],job['result']['scenes'][0]['text']);self.assertEqual(job,original)
        with self.assertRaises(APIError):planner.match_asset(mention,'samplehero',{'samplehero':foundation})
        with self.assertRaises(APIError):planner.match_asset({'category':'Character','asset_id':None},'included:samplehero',{'samplehero':foundation})
