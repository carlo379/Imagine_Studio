import base64
import tempfile
import unittest
from image_studio import mock_png
from studio_server import Studio

class VideoTagMappingTests(unittest.TestCase):
    def test_first_frame_reserves_zero_and_reference_numbers_follow_it(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Studio(mock=True,storage=folder);self.addCleanup(app.productions.sql.close)
            asset=app.upload({'name':'Synthetic.png','data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode()})
            source={'asset_id':asset['id']}
            for first,prompt in ((source,'Match <IMAGE_0>, then hold <IMAGE_1>.'),(None,'Hold <IMAGE_0>.')):
                scene=app.agent.create({'scene':{'first':first,'refs':[{'source':source}],'prompt':prompt}})
                result=app.agent.validation(scene)
                self.assertTrue(result['valid'],result)
                self.assertEqual(result['request']['prompt'],prompt)
                self.assertEqual('image' in result['request'],first is not None)
                self.assertEqual(len(result['request']['reference_images']),1)
            scene=app.agent.create({'scene':{'first':source,'prompt':'Match <IMAGE_0> exactly.'}})
            self.assertTrue(app.agent.validation(scene)['valid'])
            scene['scene']['prompt']='Use absent <IMAGE_1>.'
            self.assertFalse(app.agent.validation(scene)['valid'])
