import copy
import unittest
from script_production import ScriptProduction

class ContainerWarningsTests(unittest.TestCase):
    def setUp(self):
        self.planner=ScriptProduction.__new__(ScriptProduction)
        self.job={'source_script':'Robin sets a lamp in the Living Room.', 'catalog':[{'id':'robin','name':'Robin','category':'Character','description':'A woman.'},{'id':'room','name':'Living Room','category':'Location','description':'A room.'}], 'context':{'source_scenes':[{'title':'Scene 1','text':'Robin sets a lamp in the Living Room.'}],'dialogue_units':[]},'allow_dialogue_polish':False}
        self.result={'logline':'A lamp is placed.','synopsis':'Robin places a lamp.','visual_style':'Western','mentions':[{'id':'lamp','name':'lamp','category':'Prop','evidence':'lamp','description':'A lamp.','candidate_ids':[],'container_candidate_ids':['room','robin','missing']}],'scenes':[{'scene_index':0,'shots':[{'title':'Lamp','image_prompt':'Robin with the lamp.','video_prompt':'Robin places the lamp.','asset_mentions':['lamp']}]}],'dialogue_changes':[]}
    def test_invalid_optional_parents_are_identified_and_valid_plan_preserved(self):
        original=copy.deepcopy(self.job)
        plan,details=self.planner.normalize(self.job,self.result)
        self.assertEqual(details['mentions'][0]['container_candidate_ids'],['room','robin'])
        self.assertEqual(len(details['warnings']),1)
        self.assertTrue(all(w['asset_name']=='lamp' for w in details['warnings']))
        self.assertIn('not in the saved asset list',details['warnings'][0]['message'])
        self.assertEqual(plan['scenes'][0]['text'],self.job['source_script'])
        self.assertFalse(details['reviewed']);self.assertEqual(self.job,original)
    def test_non_prop_and_malformed_list_are_ignored(self):
        for category,parents in [('Character',['room']),('Prop','room')]:
            value=copy.deepcopy(self.result);mention=value['mentions'][0]
            mention.update(name='Robin' if category=='Character' else 'lamp',category=category,evidence='Robin' if category=='Character' else 'lamp',container_candidate_ids=parents)
            _,details=self.planner.normalize(self.job,value)
            self.assertEqual(details['mentions'][0]['container_candidate_ids'],[])
            self.assertEqual(len(details['warnings']),1)
    def test_required_scene_and_asset_checks_still_fail(self):
        for field,bad in [('shots',[]),('candidate_ids',['missing'])]:
            value=copy.deepcopy(self.result)
            if field=='shots':value['scenes'][0]['shots']=bad
            else:value['mentions'][0][field]=bad
            with self.assertRaises(ValueError):self.planner.normalize(self.job,value)
