import tempfile
import unittest
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError

class VideoPromptReviewTests(unittest.TestCase):
    def test_agent_review_is_recorded_and_edits_make_it_stale_without_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Studio(mock=True,storage=folder);self.addCleanup(app.productions.sql.close)
            scene=app.agent.create({'scene':{'prompt':'Locked camera. A leaf falls.'}})
            route='/agent/v1/scenes/'+scene['id']
            data=dict(expected_revision=scene['revision'],reviewed=True,authored_by='agent')
            with patch.object(app,'spawn',side_effect=AssertionError('No generation or writer')):
                result=app.agent.dispatch('POST',route+'/review-prompt',data)[1]
                proof=app.agent.validation(result)['prompt_provenance']
                self.assertEqual(proof['authored_by'],'agent');self.assertTrue(proof['current'])
                self.assertTrue(proof['request_fingerprint'])
                changed=app.agent.edit(scene['id'],dict(expected_revision=scene['revision'],scene={**scene['scene'],'prompt':'A second leaf falls.'}))
                self.assertFalse(app.agent.validation(changed)['prompt_review_provenance']['current'])
                with self.assertRaises(APIError):app.agent.dispatch('POST',route+'/review-prompt',data)
                data['expected_revision']=changed['revision'];data['reviewed']=False
                with self.assertRaises(APIError):app.agent.dispatch('POST',route+'/review-prompt',data)
            self.assertEqual(app.history,[])
