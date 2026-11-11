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
from test_studio import PNG,request

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
    def wait_job(self,job_id):
        for _ in range(50):
            job=next(j for j in self.app.records() if j['id']==job_id)
            if job['status']!='pending':return job
            time.sleep(.1)
        self.fail('mock generation did not finish')
    def agent_generate(self,scene,key):
        return self.call('POST',f"scenes/{scene['id']}/generate",{'expected_revision':scene['revision'],'approved':True},key)
    def test_agent_generation_pauses_until_human_review(self):
        self.reference();self.app.update(signed_in=True)
        first=self.scene();second=self.scene()
        with patch('httpx.Client'):
            job=self.agent_generate(first,'review-pause-first')
            done=self.wait_job(job['id'])
            self.assertEqual(done['status'],'done');self.assertEqual(done['human_review']['status'],'pending')
            with self.assertRaises(APIError) as error:self.agent_generate(second,'review-pause-second')
            self.assertEqual(error.exception.code,'human_review_required');self.assertEqual(error.exception.status,409)
            self.assertIn(job['id'],str(error.exception))
            # The pause survives a restart.
            restarted=studio.Studio(mock=True,storage=self.temp.name)
            self.assertEqual([j['id'] for j in restarted.pending_human_review()],[job['id']])
            # Browser mode: the human clicks a verdict.
            reviewed=self.app.record_human_review(job['id'],{'id':job['id'],'verdict':'keep','tags':['great','great'],'usage_after_percent':2.5},source='browser')
            self.assertEqual(reviewed['human_review']['verdict'],'keep');self.assertEqual(reviewed['human_review']['tags'],['great'])
            self.assertEqual(reviewed['human_review']['source'],'browser')
            with self.assertRaises(ValueError):self.app.record_human_review(job['id'],{'verdict':'keep'},source='browser')
            following=self.agent_generate(second,'review-pause-second')
            self.assertEqual(self.wait_job(following['id'])['human_review']['status'],'pending')
    def test_browser_verdict_validation(self):
        self.reference();self.app.update(signed_in=True);scene=self.scene()
        with patch('httpx.Client'):job=self.agent_generate(scene,'browser-verdict-one');self.wait_job(job['id'])
        for bad in ({'verdict':'maybe'},{'verdict':'retry'},{'verdict':'reject','notes':'  '},
                    {'verdict':'keep','tags':['nice']},{'verdict':'keep','usage_after_percent':101},
                    {'verdict':'keep','usage_after_percent':True},{'verdict':'keep','usage_reading_unavailable':'yes'},{'verdict':'keep','human_words':'ok'}):
            with self.assertRaises(ValueError,msg=bad):self.app.record_human_review(job['id'],bad,source='browser')
        self.assertEqual(self.app.pending_human_review()[0]['id'],job['id'])
    def test_agent_relays_verdict_with_human_words_and_reject_needs_a_changed_scene(self):
        self.reference();self.app.update(signed_in=True);scene=self.scene()
        with patch('httpx.Client'):
            job=self.agent_generate(scene,'relay-reject-one');self.wait_job(job['id'])
            route=f"jobs/{job['id']}/human-review"
            with self.assertRaises(ValueError):self.call('POST',route,{'verdict':'reject'})  # no human words
            with self.assertRaises(ValueError):self.call('POST',route,{'verdict':'reject','human_words':'   '})
            reviewed=self.call('POST',route,{'verdict':'reject','human_words':'No. The tavern looks fake, try a different angle.','tags':['continuity']})
            self.assertEqual(reviewed['human_review']['source'],'agent_relay')
            self.assertEqual(reviewed['human_review']['human_words'],'No. The tavern looks fake, try a different angle.')
            # The same, unchanged scene may not be rerolled after a reject.
            with self.assertRaises(APIError) as error:self.agent_generate(scene,'relay-reject-two')
            self.assertEqual(error.exception.code,'shot_rejected')
            changed=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':{'prompt':'@SampleHero waves from the doorway and says “Hello.”'}})
            retry=self.agent_generate(changed,'relay-reject-three');self.wait_job(retry['id'])
            self.call('POST',f"jobs/{retry['id']}/human-review",{'verdict':'retry','human_words':'Closer, but she smiles too early.','notes':'Delay the smile until after the line.','usage_after_percent':4})
        reviews=self.call('GET','human-reviews')
        self.assertEqual([r['verdict'] for r in reviews],['retry','reject'])
        self.assertEqual(reviews[0]['scene_id'],scene['id']);self.assertEqual(reviews[0]['usage_after_percent'],4)
        self.assertEqual(reviews[1]['human_words'],'No. The tavern looks fake, try a different angle.')
        self.assertEqual(self.app.human_reviews(),reviews)
    def test_agent_must_ask_for_usage_readings_until_calibrated(self):
        import usage_calibration
        self.reference();self.app.update(signed_in=True);scene=self.scene()
        route=f"scenes/{scene['id']}/generate"
        with patch.object(self.app,'mock',False),patch.object(self.app,'spawn'):
            with self.assertRaises(APIError) as error:self.call('POST',route,{'expected_revision':scene['revision'],'approved':True},'usage-needed-1')
            self.assertEqual(error.exception.code,'usage_reading_required');self.assertIn('Settings → Usage',str(error.exception))
            with self.assertRaises(ValueError):self.call('POST',route,{'expected_revision':scene['revision'],'approved':True,'usage_before_percent':150},'usage-needed-2')
            job=self.call('POST',route,{'expected_revision':scene['revision'],'approved':True,'usage_before_percent':12.5},'usage-needed-3')
            self.assertEqual(job['usage'],{'before':12.5,'after':None,'unavailable':False})
        for record in self.app.history:record['status']='done'  # finish the unspawned take
        self.app.update(phase='done')
        with patch.object(self.app,'mock',False),patch.object(self.app,'spawn'),patch.object(usage_calibration,'required',return_value=False):
            self.app.history[0]['human_review']={'status':'reviewed'}
            other=self.scene()
            job=self.call('POST',f"scenes/{other['id']}/generate",{'expected_revision':other['revision'],'approved':True},'usage-established-1')
            self.assertIsNone(job['usage']['before'])
        with patch.object(self.app,'mock',False),patch.object(self.app,'spawn'):
            self.app.history[0]['status']='done';self.app.history[0]['human_review']={'status':'reviewed'};self.app.update(phase='done')
            third=self.scene()
            job=self.call('POST',f"scenes/{third['id']}/generate",{'expected_revision':third['revision'],'approved':True,'usage_reading_unavailable':True},'usage-unavailable-1')
            self.assertTrue(job['usage']['unavailable'])
    def test_relayed_verdict_needs_the_after_reading_and_browser_records_it_separately(self):
        self.reference();self.app.update(signed_in=True);scene=self.scene()
        with patch('httpx.Client'):
            job=self.call('POST',f"scenes/{scene['id']}/generate",{'expected_revision':scene['revision'],'approved':True,'usage_before_percent':20},'usage-relay-1')
            self.wait_job(job['id'])
            route=f"jobs/{job['id']}/human-review"
            with self.assertRaises(APIError) as error:self.call('POST',route,{'verdict':'keep','human_words':'Keep it.'})
            self.assertEqual(error.exception.code,'usage_reading_required')
            reviewed=self.call('POST',route,{'verdict':'keep','human_words':'Keep it.','usage_after_percent':21.5})
            self.assertEqual(reviewed['usage']['after'],21.5);self.assertIsNotNone(reviewed['usage']['after_at'])
            row=self.call('GET','human-reviews')[0]
            self.assertEqual((row['usage_before_percent'],row['usage_after_percent']),(20,21.5))
            identity=self.app.start_video(request(),True,usage_before=30)
            self.wait_job(identity)
            with self.assertRaises(ValueError):self.app.record_usage_after(identity,{'usage_after_percent':-1})
            self.assertEqual(self.app.record_usage_after(identity,{'id':identity,'usage_after_percent':31})['usage']['after'],31)
            with self.assertRaises(ValueError):self.app.record_usage_after(identity,{'usage_after_percent':32})
            # Mock takes cost nothing, so they never count toward calibration.
            self.assertEqual(self.call('GET','usage/calibration')['samples'],[])
    def test_browser_generation_is_not_paused_by_human_review(self):
        self.app.update(signed_in=True)
        with patch('httpx.Client'):
            identity=self.app.start_video(request(),True)
            for _ in range(50):
                job=next(j for j in self.app.records() if j['id']==identity)
                if job['status']!='pending':break
                time.sleep(.1)
        self.assertNotIn('human_review',job);self.assertEqual(self.app.pending_human_review(),[])
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
    def test_http_browser_and_agent_review_routes(self):
        asset=self.app.upload({'name':'view.png','data_url':PNG});self.app.update(signed_in=True)
        self.client.request('references','POST',{'title':'SampleHero','handle':'SampleHero','category':'Character','description':'A robot.','images':[{'asset_id':asset['id']}]})
        def browser(path,data=None):
            headers={'Origin':self.base,'X-Tester':'local','Content-Type':'application/json'}
            request=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=headers,method='GET' if data is None else 'POST')
            with urlopen(request) as response:return json.loads(response.read())
        def finished(job_id):
            for _ in range(50):
                job=self.client.request('jobs/'+job_id)
                if job['status']!='pending':return job
                time.sleep(.1)
        with patch('httpx.Client'):
            for index,mode in enumerate(('browser','agent')):
                scene=self.client.request('scenes','POST',{'title':'Shot','scene':{'prompt':f'@SampleHero waves, take {index}.'},'named_references':['SampleHero']})
                job=self.client.generate(scene,approved=True,idempotency_key=f'http-review-{mode}');finished(job['id'])
                if mode=='browser':
                    with self.assertRaises(HTTPError) as error:browser('/api/video/human-review',{'id':job['id'],'verdict':'retry'})
                    self.assertEqual(error.exception.code,400);error.exception.close()
                    browser('/api/video/human-review',{'id':job['id'],'verdict':'keep','tags':['great']})
                else:
                    with self.assertRaises(AgentError):self.client.request(f"jobs/{job['id']}/human-review",'POST',{'verdict':'keep'})
                    self.client.request(f"jobs/{job['id']}/human-review",'POST',{'verdict':'keep','human_words':'Looks great, keep it.'})
        self.assertEqual([r['source'] for r in browser('/api/human-reviews')],['agent_relay','browser'])
        self.assertEqual(browser('/api/human-reviews'),self.client.request('human-reviews'))
        self.assertEqual(browser('/api/usage-calibration'),self.client.request('usage/calibration'))
        self.assertEqual(set(browser('/api/usage-calibration')['resolutions']),{'480p','720p','1080p'})
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
