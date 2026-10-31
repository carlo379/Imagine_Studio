import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import test_browser_handoff as fixtures
from agent_client import StudioClient
import base64
from image_studio import mock_png

class DawnDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.BrowserHandoffHTTPTests.setUpClass.__func__(cls)
    def test_download_routes_explain_browser_vs_agent_auth_and_keep_isolation(self):
        asset=self.app.upload(dict(name='Local.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        with self.assertRaises(HTTPError) as error:urlopen(self.base+'/api/assets/'+asset['id'])
        with error.exception as response:detail=json.load(response)
        self.assertEqual(error.exception.code,401)
        self.assertIn('download_image_candidate',detail['error']['message']);self.assertIn('IMAGE JOB',StudioClient.download_image_candidate.__doc__)
        request=Request(self.base+'/api/assets/'+asset['id'],headers={'Authorization':'Bearer '+self.client.token})
        with urlopen(request) as response:self.assertEqual(response.read(),self.app.asset(asset['id'])[1].read_bytes())
        foreign_id=self.manager.new_guest();foreign=StudioClient(self.base,self.manager.app(foreign_id).storage/'agent-token')
        with self.assertRaises(HTTPError) as error:urlopen(Request(self.base+'/api/assets/'+asset['id'],headers={'Authorization':'Bearer '+foreign.token}))
        self.assertEqual(error.exception.code,404);error.exception.close()
