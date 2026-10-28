import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import studio_server as studio
from agent_api import APIError,blank
from agent_client import StudioClient,AgentError
from test_studio import PNG

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name);self.api=self.app.agent
        self.asset=self.app.upload({'name':'view.png','data_url':PNG})
    def tearDown(self):self.temp.cleanup()
    def call(self,method,path,data=None,key=None):return self.api.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def reference(self):return self.call('POST','references',{'title':'SampleHero','handle':'SampleHero','category':'Character','description':'A friendly robot.','voice':'rex','images':[{'asset_id':self.asset['id']}]})
    def scene(self):return self.call('POST','scenes',{'title':'Intro','scene':{'prompt':'@SampleHero waves and says “Hello.”'},'named_references':['SampleHero']})
    def test_reference_compile_snapshots_and_retaging(self):
        ref=self.reference();scene=self.scene();validation=self.call('POST',f"scenes/{scene['id']}/validate")
        self.assertTrue(validation['valid']);self.assertIn('<AUDIO_0>',validation['request']['prompt']);self.assertNotIn('_studio_scene',validation['request'])
        self.assertEqual(validation['request']['reference_images'][0]['url'],PNG)
        self.call('PUT','references/'+ref['id'],{**ref,'description':'Changed reference.'})
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':{'first':{'asset_id':self.asset['id']}}})
        prompt=self.call('POST',f"scenes/{scene['id']}/validate")['request']['prompt']
        self.assertIn("Preserve SampleHero's exact appearance as shown in <IMAGE_1> throughout the shot.",prompt)
        self.assertNotIn('A friendly robot.',prompt);self.assertNotIn('Changed reference.',prompt)
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':{'prompt':'Watch <IMAGE_1>.'}})
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':{'first':None}})
        self.assertEqual(scene['scene']['prompt'],'Watch <IMAGE_0>.')
        self.call('POST','references/'+ref['id']+'/archive',{'archived':True})
        self.assertTrue(self.call('POST',f"scenes/{scene['id']}/validate")['valid'])
    def test_workspace_revision_conflicts_and_restart(self):
        scene=self.call('POST','workspace',{'title':'Browser draft','scene':{'prompt':'A slow orbit.'}})
        changed=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':1,'changes':{'duration':8}})
        self.assertEqual(self.call('GET','workspace')['scene']['duration'],8)
        with self.assertRaises(APIError) as error:self.call('PUT','scenes/'+scene['id'],{'expected_revision':1,'scene':scene['scene']})
        self.assertEqual(error.exception.status,409)
        restored=studio.Studio(mock=True,storage=self.temp.name)
        self.assertEqual(restored.agent.workspace(),changed)
        self.assertEqual(restored.agent.token,self.api.token)
        self.assertEqual(self.api.token_path.stat().st_mode & 0o777,0o600)
    def test_approval_idempotency_download_and_reuse(self):
        self.reference();scene=self.scene();self.app.update(signed_in=True)
        route=f"scenes/{scene['id']}/generate"
        with self.assertRaises(APIError):self.call('POST',route,{'expected_revision':1},'approved-mock-once')
        with patch('httpx.Client') as network:
            job=self.call('POST',route,{'expected_revision':1,'approved':True},'approved-mock-once')
            repeated=self.call('POST',route,{'expected_revision':1,'approved':True},'approved-mock-once')
            self.assertEqual(job['id'],repeated['id']);self.assertEqual(len(self.app.records()),1)
            for _ in range(30):
                if self.app.records()[0]['status']=='done':break
                time.sleep(.1)
            network.assert_not_called()
        output=self.call('GET',f"jobs/{job['id']}/download")
        self.assertEqual(output[1],'video/mp4');self.assertGreater(len(output[0]),100)
        reused=self.call('POST',f"jobs/{job['id']}/reuse",{'title':'Next scene'})
        self.assertEqual(reused['scene']['prompt'],scene['scene']['prompt']);self.assertEqual(reused['scene']['named'],scene['scene']['named'])
        restarted=studio.Studio(mock=True,storage=self.temp.name)
        self.assertEqual(restarted.agent.dispatch('POST','/agent/v1/'+route,{'expected_revision':1,'approved':True},'approved-mock-once')[1]['id'],job['id'])
        with self.assertRaises(APIError):self.call('POST',f"scenes/{reused['id']}/generate",{'expected_revision':1,'approved':True},'approved-mock-once')
    def test_direct_author_warnings_match_browser_validation_and_stay_nonblocking(self):
        self.reference()
        scene = self.call('POST', 'scenes', dict(scene=dict(prompt='Use Rex with <AUDIO_0>.'),
            named_references=['SampleHero']))
        validation = self.call('POST', f"scenes/{scene['id']}/validate")
        expected = {'voice_tag_repeated', 'voice_name_in_body', 'character_without_direction'}
        self.assertEqual({i['code'] for i in validation['prompt_issues']}, expected)
        self.assertTrue(validation['valid'])
        self.assertFalse(validation['prompt_generation_blocked'])
        self.assertTrue(all(i['severity'] == 'warning' for i in validation['prompt_issues']))
        for issue in validation['prompt_issues']:
            self.assertIn(issue['message'], validation['warnings'])
        request = validation['request']
        browser = self.app.prompting.request_status(request, scene['id'], scene['scene'])
        self.assertEqual(browser['prompt_issues'], validation['prompt_issues'])
        raw = self.app.prompting.request_status(request)
        self.assertEqual(raw['prompt_issues'], validation['prompt_issues'])
        changed = self.call('PATCH', 'scenes/'+scene['id'], dict(expected_revision=scene['revision'],
            changes=dict(prompt='SampleHero waits, then says “Hello.”')))
        clean = self.call('POST', f"scenes/{changed['id']}/validate")
        self.assertEqual(clean['prompt_issues'], [])
        self.assertEqual(clean['warnings'], [])

    def test_leo_first_name_and_voice_exemption_reach_api_validation(self):
        for title, handle, voice in [('Eve Foster','EveFoster','eve'), ('Eve Fox','LeoFox',None)]:
            self.call('POST','references',dict(title=title,handle=handle,category='Character',
                description='',voice=voice,images=[{'asset_id':self.asset['id']}]))
        scene = self.call('POST','scenes',dict(scene=dict(prompt='Eve stays crouched, mouth closed.'),
            named_references=['EveFoster']))
        validation = self.call('POST',f"scenes/{scene['id']}/validate")
        self.assertEqual(validation['prompt_issues'], [])
        self.assertIn("Preserve Eve Foster's exact appearance",validation['request']['prompt'])
        scene = self.call('POST','scenes',dict(scene=dict(prompt='Eve waits.'),
            named_references=['EveFoster','LeoFox']))
        issues = self.call('POST',f"scenes/{scene['id']}/validate")['prompt_issues']
        self.assertEqual(len(issues),2)
        self.assertTrue(all(i['code']=='character_without_direction' for i in issues))

    def test_shared_voice_binding_warns_on_duplicate_tags_in_compiler_header(self):
        self.reference()
        record = self.scene()
        scene = record['scene']
        scene['named'].append({**scene['named'][0], 'id':'narrator', 'handle':'Narrator',
            'title':'Narrator', 'images':[], 'refIds':[]})
        record = self.call('PATCH', 'scenes/'+record['id'], dict(expected_revision=record['revision'],
            changes=dict(named=scene['named'])))
        validation = self.call('POST', f"scenes/{record['id']}/validate")
        self.assertEqual(validation['request']['prompt'].count('<AUDIO_0>'), 2)
        self.assertEqual([i['code'] for i in validation['prompt_issues']], ['voice_tag_repeated'])
        self.assertFalse(validation['prompt_generation_blocked'])

    def test_draft_validation_and_no_network_when_live_locked(self):
        scene=self.call('POST','scenes',{'scene':{'prompt':'x'*4097}})
        self.assertFalse(self.call('POST',f"scenes/{scene['id']}/validate")['valid'])
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':1,'changes':{'prompt':'A slow orbit.'}})
        self.app.mock=False;self.app.update(signed_in=True)
        with patch.dict(studio.CONFIG,{'live_generations_enabled':False}),patch.object(studio,'oauth_headers') as oauth,self.assertRaises(ValueError):
            self.call('POST',f"scenes/{scene['id']}/generate",{'expected_revision':scene['revision'],'approved':True},'locked-render-key')
        oauth.assert_not_called();self.assertEqual(self.app.records(),[])
    def test_restore_missing_reference_and_schema(self):
        self.reference();scene=self.scene()
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':1,'changes':{'refs':[]}})
        self.assertFalse(self.call('POST',f"scenes/{scene['id']}/validate")['valid'])
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'restore_named_references':['SampleHero']})
        self.assertTrue(self.call('POST',f"scenes/{scene['id']}/validate")['valid'])
        spec=self.call('GET','openapi.json')
        self.assertEqual(spec['openapi'],'3.1.0')
        self.assertIn('/scenes/{id}/generate',spec['paths'])
        with self.assertRaises(APIError):self.call('POST','scenes',{'scene':{'refs':[{'source':None}]}})

    def test_url_archive_restore_and_manual_inputs(self):
        self.call('POST','urls',{'url':'https://example.invalid/view.png'})
        self.assertEqual(len(self.call('GET','urls')),1)
        scene=self.call('POST','scenes',{'scene':{'prompt':'A slow orbit of <IMAGE_0>.','refs':[{'source':{'asset_id':self.asset['id']}}], 'keys':[{'source':{'asset_id':self.asset['id']},'slot':3}]}})
        self.assertTrue(self.call('POST',f"scenes/{scene['id']}/validate")['valid'])
        scene=self.call('POST',f"scenes/{scene['id']}/archive",{'expected_revision':1})
        self.assertTrue(scene['archived'])
        self.assertFalse(self.call('POST',f"scenes/{scene['id']}/archive",{'expected_revision':2,'archived':False})['archived'])

class AgentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),studio.StudioHandler);self.server.tester=self.app
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.client=StudioClient(self.base,self.app.agent.token_path)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def test_http_auth_schema_and_entire_agent_flow(self):
        with self.assertRaises(HTTPError) as error:urlopen(self.base+'/agent/v1/schema')
        self.assertEqual(error.exception.code,403);error.exception.close()
        with self.assertRaises(HTTPError) as error:urlopen(Request(self.base+'/agent/v1/schema',headers={'Authorization':'Bearer '+self.app.agent.token,'Origin':'https://malicious.invalid'}))
        error.exception.close()
        self.assertEqual(self.client.request('schema')['config']['prompt_limit_chars'],4096)
        self.client.request('account/login','POST',{})
        for _ in range(20):
            if self.client.request('account')['signed_in']:break
            time.sleep(.05)
        asset=self.client.request('assets','POST',{'name':'view.png','data_url':PNG})
        scene=self.client.create_scene('HTTP scene',{'prompt':'Gentle motion.','refs':[{'source':{'asset_id':asset['id']}}]})
        self.client.show_in_browser(scene)
        self.assertEqual(self.client.request('workspace')['id'],scene['id'])
        self.assertTrue(self.client.validate(scene)['valid'])
        with self.assertRaises(AgentError) as error:self.client.generate(scene,idempotency_key='no-approval-key')
        self.assertEqual(error.exception.code,'approval_required')
        job=self.client.generate(scene,approved=True,idempotency_key='http-approved-once')
        self.assertEqual(self.client.wait_for_job(job['id'],timeout=5,interval=.1)['status'],'done')
        path=Path(self.temp.name)/'output.mp4';self.client.download(job['id'],path);self.assertGreater(path.stat().st_size,100)
        # Browser origin remains usable without revealing the local agent token.
        data=json.dumps({'expected_revision':1,'changes':{'duration':6}}).encode()
        with urlopen(Request(self.base+'/api/agent/scenes/'+scene['id'],data=data,method='PATCH',headers={'Content-Type':'application/json','X-Tester':'local','Origin':self.base})) as response:
            self.assertEqual(json.load(response)['scene']['duration'],6)
        with self.assertRaises(HTTPError) as error:urlopen(Request(self.base+'/api/agent/scenes',data=b'{}',method='POST',headers={'X-Tester':'local'}))
        error.exception.close()
        self.assertNotIn(self.app.agent.token,json.dumps(self.client.request('account')))
        self.assertNotIn(self.app.agent.token,json.dumps(self.client.request('schema')))

if __name__=='__main__':unittest.main()
