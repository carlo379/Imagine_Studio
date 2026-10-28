import copy
import tempfile
import unittest
from studio_server import Studio
from agent_api import APIError
from test_studio import PNG

class AssetRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.temp.name)
        self.a=self.app.upload({'data_url':PNG});self.b=self.app.upload({'data_url':PNG})
        self.ref=self.app.save_reference({'title':'Old Lab','handle':'OldLab','category':'Location','description':'Old','images':[{'asset_id':self.a['id']},{'asset_id':self.b['id']}]})
        self.draft=self.app.images.create({'title':'Scene','settings':{'prompt':'Visit @OldLab with @OldLabOther.'},'named_references':['OldLab']})
    def tearDown(self):self.temp.cleanup()
    def refresh(self,**data):return self.app.agent.dispatch('POST','/agent/v1/image-studio/drafts/'+self.draft['id']+'/refresh-reference',{'expected_revision':self.draft['revision'],'reference_id':self.ref['id'],**data})[1]
    def test_refresh_maps_selected_images_and_renames_prompt_only_here(self):
        other=self.app.images.create({'title':'Other','settings':{},'named_references':['OldLab']})
        self.app.save_reference({**self.ref,'title':'New Lab','handle':'NewLab','description':'Glass walls','images':list(reversed(self.ref['images']))})
        r=self.refresh();b=r['settings']['bindings'][0]
        self.assertEqual(b['selected'],[1]);self.assertEqual(b['snapshot']['description'],'Glass walls');self.assertEqual(r['settings']['prompt'],'Visit @NewLab with @OldLabOther.')
        self.assertEqual(self.app.images.draft(other['id'])['settings']['bindings'][0]['snapshot']['handle'],'OldLab')
    def test_removed_view_is_deselected_not_substituted(self):
        self.app.save_reference({**self.ref,'images':[{'asset_id':self.b['id']}]})
        self.assertEqual(self.refresh()['settings']['bindings'][0]['selected'],[])
    def test_revision_and_reference_validation_preserves_draft(self):
        before=copy.deepcopy(self.app.images.draft(self.draft['id']))
        for data in ({'expected_revision':999},{'reference_id':'missing'}):
            with self.assertRaises(APIError):self.refresh(**data)
        self.assertEqual(before,self.app.images.draft(self.draft['id']))
