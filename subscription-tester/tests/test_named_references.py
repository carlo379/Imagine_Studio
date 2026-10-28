import json
import tempfile
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_server as studio
from test_studio import PNG, request

class NamedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name)
        self.asset=self.app.upload({'data_url':PNG,'name':'view.png'})
        self.data={'title':'SampleHero','handle':'SampleHero','description':'A consistent robot.','category':'Character',
                   'voice':'rex','images':[{'asset_id':self.asset['id']}]}
    def tearDown(self):self.temp.cleanup()
    def test_save_update_archive_restore_and_restart(self):
        with patch('httpx.Client') as network:
            record=self.app.save_reference(self.data)
            network.assert_not_called()
        duplicate={**self.data,'handle':'samplehero'}
        with self.assertRaisesRegex(ValueError,'already used'):self.app.save_reference(duplicate)
        edited=self.app.save_reference({**record,'description':'Updated robot.'})
        self.assertEqual(record['id'],edited['id']);self.assertEqual(len(self.app.named_library()),1)
        self.app.archive_reference(record['id'],True)
        restored=studio.Studio(mock=True,storage=self.temp.name)
        self.assertTrue(restored.named_library()[0]['archived'])
        restored.archive_reference(record['id'],False)
        self.assertFalse(restored.named_library()[0]['archived'])
    def test_invalid_inputs_and_voice_only(self):
        for extra in ({'handle':'bad name'},{'category':'Person'},{'voice':'clone-id'},{'images':[],'voice':None},
                      {'images':[{'asset_id':'missing'}]},{'images':[{'url':'http://example.invalid/a.png'}]},
                      {'images':[{'asset_id':self.asset['id']}]*8},{'title':''}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.app.save_reference({**self.data,**extra})
        self.app.save_reference({**self.data,'images':[]})
    def test_expanded_prompt_length_limit(self):
        body=request(prompt='x'*4096)
        self.app.resolve(body)
        with self.assertRaisesRegex(ValueError,'4097 characters; the limit is 4096'):
            self.app.resolve(request(prompt='x'*4097))

    def test_scene_metadata_is_local_and_cannot_expand_api_fields(self):
        body=self.app.resolve(request(_studio_scene={'named':[self.data]},reference_images=[{'asset_id':self.asset['id']}]))
        self.assertNotIn('_studio_scene',body)
        self.assertEqual(body['reference_images'][0]['url'],PNG)
        with self.assertRaises(ValueError):self.app.resolve(request(category='Character'))

if __name__=='__main__':unittest.main()
