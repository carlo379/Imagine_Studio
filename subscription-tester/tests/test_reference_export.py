import copy
import tempfile
import unittest
from unittest.mock import patch
from studio_server import Studio, CONFIG
from agent_api import APIError
from reference_suggestions import suggest
from test_studio import PNG

class ReferenceExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.temp.name)
        self.asset=self.app.upload({'data_url':PNG,'name':'lab.png'})
        self.asset.update(generated=True,approved=True)
        self.job={'id':'lab-job','mock':True,'status':'done','outputs':[copy.deepcopy(self.asset)],'draft':{'id':'draft','title':'New image','settings':{'prompt':'Create an image of a futuristic robotics laboratory with glass walls, blue lighting and workbenches.'}}}
        self.app.images.db['jobs'].append(self.job)
    def tearDown(self):self.temp.cleanup()
    def call(self,action,data=None):return self.app.agent.dispatch('POST','/agent/v1/image-studio/jobs/lab-job/'+action,{'asset_id':self.asset['id'],**(data or {})})[1]
    def test_prompt_suggestion_and_editable_export(self):
        with patch('httpx.Client') as network:
            suggestion=self.call('reference-suggestion');self.assertEqual(suggestion['title'],'Futuristic Robotics Laboratory');self.assertEqual(suggestion['category'],'Location');self.assertIn('glass walls',suggestion['description']);self.assertNotIn('Create an image',suggestion['description'])
            record=self.call('reference',{'title':'SampleHero Lab','handle':'SampleHero_Lab','description':'Blue-lit robotics lab with glass walls.','category':'Location'})
            network.assert_not_called()
        self.assertEqual(record['images'],[{'asset_id':self.asset['id']}]);self.assertEqual(record['title'],'SampleHero Lab')
        restored=Studio(mock=True,storage=self.temp.name);saved=restored.named_library()[0]
        self.assertEqual({k:saved[k] for k in record},record);self.assertFalse(saved['needs_replacement'])
    def test_approval_revocation_and_wrong_asset_rejected(self):
        for where in (self.asset,self.job['outputs'][0]):
            where['approved']=False
            for action in ('reference','reference-suggestion'):
                with self.assertRaises(APIError):self.call(action)
            where['approved']=True
        with self.assertRaises(APIError):self.call('reference',{'asset_id':'wrong'})
        with self.assertRaises(APIError):self.call('reference',{'images':[]})
        self.assertEqual(self.app.references,[])
    def test_names_unique_and_description_bounded(self):
        record=self.call('reference');suggestion=self.call('reference-suggestion');self.assertNotEqual(record['handle'],suggestion['handle'])
        self.job['draft']['settings']['prompt']='a'*10000
        suggestion=self.call('reference-suggestion');self.assertLessEqual(len(suggestion['description']),CONFIG['reference_description_limit'])
        self.assertTrue(suggestion['title'])
    def test_original_job_prompt_and_category_choices(self):
        for category in ('Location','Character','Prop'):
            result=self.call('reference-suggestion',{'category':category});self.assertEqual(result['category'],category)
        with self.assertRaises(APIError):self.call('reference',{'category':'Item'})
        self.assertIn('workbenches',self.call('reference-suggestion')['description'])
    def test_reusable_in_image_and_video(self):
        ref=self.call('reference')
        video=self.app.agent.create({'title':'Lab scene','named_references':[ref['handle']]})
        self.assertEqual(video['scene']['refs'][0]['source']['id'],self.asset['id'])
        image=self.app.images.create({'title':'Another lab view','settings':{},'named_references':[ref['handle']]})
        self.assertEqual(image['settings']['bindings'][0]['snapshot']['id'],ref['id'])
    def test_direct_video_reference_transfer(self):
        scene=self.app.agent.create({'title':'Lab motion'})
        result=self.call('transfer',{'scene_id':scene['id'],'expected_revision':scene['revision'],'target':'reference'})
        self.assertEqual(result['scene']['refs'][0]['source']['id'],self.asset['id'])
