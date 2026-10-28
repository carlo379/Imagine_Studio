import base64
import copy
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
import studio_server as studio
from agent_api import APIError
from image_studio import IMAGE_MODEL
from test_studio import PNG
from prompt_fixtures import reviewed_prompt

class ImageStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name)
        self.api=self.app.agent;self.app.update(signed_in=True)
        self.asset=self.app.upload({'name':'identity.png','data_url':PNG})
        self.ref=self.call('POST','references',{'title':'SampleHero','handle':'SampleHero','category':'Character','description':'A friendly gold robot.','images':[{'asset_id':self.asset['id']}]})
    def tearDown(self):
        for _ in range(100):
            if all(j['status']!='pending' for j in self.app.images.db['jobs']):break
            time.sleep(.02)
        self.temp.cleanup()
    def call(self,method,path,data=None,key=None):return self.api.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def image(self,prompt='@SampleHero sits at a desk.'):
        return self.call('POST','image-studio/drafts',{'title':'Desk','settings':{'prompt':prompt},'named_references':['SampleHero']})
    def validate(self,r):return self.call('POST',f"image-studio/drafts/{r['id']}/validate")
    def generate(self,r,key='image-test-once'):
        if not self.app.mock:reviewed_prompt(self.app,'image',r)
        job=self.call('POST',f"image-studio/drafts/{r['id']}/generate",{'expected_revision':r['revision'],'approved':True},key)
        for _ in range(100):
            j=self.call('GET','image-studio/jobs/'+job['id'])
            if j['status']!='pending':return j
            time.sleep(.02)
        self.fail('Image worker timed out')
    def test_request_compilation_and_immutable_identity(self):
        r=self.image();v=self.validate(r)
        self.assertTrue(v['valid']);self.assertTrue(v['endpoint'].endswith('/images/edits'));self.assertEqual(v['source_count'],1)
        body=v['request'];self.assertEqual(body['image'],{'type':'image_url','url':PNG});self.assertEqual(body['model'],IMAGE_MODEL)
        self.assertEqual(r['settings']['quality'],'auto');self.assertNotIn('quality',body)
        self.assertNotIn('@SampleHero',body['prompt']);self.assertIn('input image(s) 1',body['prompt']);self.assertNotIn('reference_images',body)
        self.call('PUT','references/'+self.ref['id'],{**self.ref,'description':'A blue robot.'})
        self.assertIn('gold robot',self.validate(r)['request']['prompt'])
        self.call('POST','references/'+self.ref['id']+'/archive',{'archived':True})
        self.assertTrue(self.validate(r)['valid'])
        plain=self.call('POST','image-studio/drafts',{'settings':{'prompt':'A mountain.'}})
        self.assertEqual(self.validate(plain)['request']['n'],1);self.assertTrue(self.validate(plain)['endpoint'].endswith('/images/generations'))
    def test_grok_auto_migration_preserves_history_and_runs_once(self):
        from image_studio import ImageStudio
        r=self.image();self.app.images.db.pop('grok_auto_quality_migrated')
        self.app.images.draft(r['id'])['settings']['quality']='low'
        self.app.images.db['jobs'].append({'id':'old-request','status':'error','draft':{'settings':{'quality':'low'}}})
        self.app.images.persist()
        migrated=ImageStudio(self.app,self.app.images.config,self.app.images.save)
        self.assertEqual(migrated.draft(r['id'])['settings']['quality'],'auto')
        self.assertEqual(migrated.draft(r['id'])['revision'],2)
        self.assertEqual(migrated.db['jobs'][0]['draft']['settings']['quality'],'low')
        migrated.draft(r['id'])['settings']['quality']='low';migrated.persist()
        reloaded=ImageStudio(self.app,migrated.config,migrated.save)
        self.assertEqual(reloaded.draft(r['id'])['settings']['quality'],'low')

    def test_gpt_refinement_source_limits_and_switch_preserve_inputs(self):
        for model in ('gpt-image-2.5-flare','gpt-image-2.5-sunburst'):
            r=self.image();settings=copy.deepcopy(r['settings'])
            settings.update(model=model,resolution='auto',quality='auto',base={'asset_id':self.asset['id']},extras=[{'asset_id':self.asset['id']}]*4)
            r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
            result=self.validate(r)
            self.assertTrue(result['valid'],result)
            self.assertEqual(result['source_count'],6)
            self.assertEqual(len(result['request']['images']),6)
            settings['extras']=[{'asset_id':self.asset['id']}]*14
            r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
            self.assertEqual(self.validate(r)['source_count'],16)
            settings['extras'].append({'asset_id':self.asset['id']})
            r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
            self.assertIn('16 source',str(self.validate(r)['errors']))
            settings.update(model=IMAGE_MODEL,resolution='1k')
            r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
            self.assertEqual(len(r['settings']['extras']),15)
            self.assertIn('five source',str(self.validate(r)['errors']))
        schema=self.app.images.schema()
        self.assertEqual(schema['models']['gpt-image-2']['max_sources'],5)
        self.assertEqual(schema['models'][IMAGE_MODEL]['max_sources'],5)
        settings.update(model='gpt-image-2',resolution='auto')
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
        self.assertEqual(len(r['settings']['extras']),15)
        self.assertIn('five source',str(self.validate(r)['errors']))
        settings['extras']=settings['extras'][:3]
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
        self.assertEqual(self.validate(r)['source_count'],5)

    def test_limits_and_revision_protection(self):
        r=self.image();s=copy.deepcopy(r['settings']);s['extras']=[{'asset_id':self.asset['id']}]*5
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':1,'settings':s})
        self.assertFalse(self.validate(r)['valid']);self.assertIn('five',self.validate(r)['errors'][0])
        with self.assertRaises(APIError) as e:self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':1})
        self.assertEqual(e.exception.status,409)

        s['extras']=[];s['prompt']='@Missing stands here.'
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':2,'settings':s})
        self.assertFalse(self.validate(r)['valid'])
        s['prompt']='x'*4097
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':3,'settings':s})
        self.assertFalse(self.validate(r)['valid'])
        for bad in ({'ratio':'7:8'},{'quality':'high'},{'extras':[None]}):
            with self.assertRaises(APIError):self.call('POST','image-studio/drafts',{'settings':bad})

    def test_deselected_reference_is_excluded_from_compiler_and_writer(self):
        r=self.image();settings=copy.deepcopy(r['settings'])
        settings.update(model='gpt-image-2',resolution='auto',base={'asset_id':self.asset['id']},prompt='Move the family; preserve the setting.')
        settings['bindings'][0]['selected']=[]
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
        v=self.validate(r)
        self.assertTrue(v['valid'],v)
        self.assertEqual(v['source_count'],1)
        self.assertNotIn('A friendly gold robot.',v['request']['prompt'])
        self.assertEqual(len(r['settings']['bindings']),1)
        context=self.app.prompting.context('image',r,{'instruction':'Keep everything else.'})
        self.assertEqual(context['settings']['bindings'],[])
        self.assertEqual(len(context['reference_mapping']),1)
        settings['prompt']='Move @SampleHero.'
        r=self.call('PUT','image-studio/drafts/'+r['id'],{'expected_revision':r['revision'],'settings':settings})
        self.assertTrue(self.validate(r)['valid'])
        self.assertEqual(self.validate(r)['source_count'],1)

    def test_prompt_auto_attaches_and_preserves_views(self):
        record=self.call('POST','image-studio/drafts',{'settings':{'prompt':'@samplehero at work; @SampleHero again. user@SampleHero.example'}})
        self.assertEqual(len(record['settings']['bindings']),1)
        self.assertEqual(record['settings']['bindings'][0]['selected'],[0])
        settings=copy.deepcopy(record['settings']);settings['bindings'][0]['selected']=[]
        edited=self.call('PUT','image-studio/drafts/'+record['id'],{'expected_revision':record['revision'],'settings':settings})
        self.assertEqual(edited['settings']['bindings'][0]['selected'],[])
        self.assertFalse(self.validate(edited)['valid'])
        email=self.call('POST','image-studio/drafts',{'settings':{'prompt':'user@SampleHero.example @SampleHeroOther'}})
        self.assertEqual(email['settings']['bindings'],[])

    def test_prompt_auto_attach_limits_and_later_save(self):
        record=self.call('POST','image-studio/drafts',{'settings':{'prompt':'@SampleHero on a desk','extras':[{'asset_id':self.asset['id']}]*5}})
        self.assertEqual(record['settings']['bindings'],[])
        self.assertIn('five source',str(self.validate(record)['errors']))
        settings=copy.deepcopy(record['settings']);settings['extras'].pop()
        edited=self.call('PUT','image-studio/drafts/'+record['id'],{'expected_revision':1,'settings':settings})
        self.assertEqual(len(edited['settings']['bindings']),1)
        self.assertTrue(self.validate(edited)['valid'])

    def test_transfer_to_new_scene(self):
        job=self.generate(self.image());output=job['outputs'][0]
        route='image-studio/jobs/'+job['id']+'/transfer'
        payload={'asset_id':output['id'],'new_scene':True,'title':'New video','target':'first'}
        before=len(self.api.db['scenes'])
        with self.assertRaises(APIError):self.call('POST',route,payload)
        self.assertEqual(len(self.api.db['scenes']),before)
        self.call('POST','image-studio/jobs/'+job['id']+'/approve',{'asset_id':output['id'],'approved':True})
        for target in ('first','last','reference','keyframe'):
            record=self.call('POST',route,{**payload,'target':target,'slot':3})
            self.assertEqual(record['title'],'New video')
            self.assertEqual(record['scene']['model'],'grok-imagine-video-1.5')
            self.assertTrue(record['scene'][{'reference':'refs','keyframe':'keys'}.get(target,target)])
        count=len(self.api.db['scenes'])
        with self.assertRaises(APIError):self.call('POST',route,{**payload,'target':'keyframe','slot':999})
        self.assertEqual(len(self.api.db['scenes']),count)

    def test_mock_history_refinement_approval_and_transfer(self):
        r=self.image()
        with patch('httpx.Client') as network:j=self.generate(r);network.assert_not_called()
        self.assertEqual(j['status'],'done');o=j['outputs'][0];self.assertFalse(o['approved'])
        downloaded=self.call('GET','image-studio/jobs/'+j['id']+'/download');self.assertEqual(downloaded[1],'image/png')
        scene=self.call('POST','scenes',{'scene':{'duration':5,'prompt':'Camera follows <IMAGE_0>.','refs':[{'source':{'asset_id':self.asset['id']}}]}})
        transfer={'asset_id':o['id'],'scene_id':scene['id'],'expected_revision':1,'target':'first'}
        with self.assertRaises(APIError):self.call('POST','image-studio/jobs/'+j['id']+'/transfer',transfer)
        unapproved=self.call('POST','scenes',{'scene':{'prompt':'Motion.','first':{'asset_id':o['id']}}})
        self.assertFalse(self.call('POST','scenes/'+unapproved['id']+'/validate')['valid'])
        self.call('POST','image-studio/jobs/'+j['id']+'/approve',{'asset_id':o['id'],'approved':True})
        scene=self.call('POST','image-studio/jobs/'+j['id']+'/transfer',transfer)
        self.assertEqual(scene['scene']['first']['id'],o['id']);self.assertIn('<IMAGE_1>',scene['scene']['prompt'])
        transfer.update(expected_revision=scene['revision'])
        with self.assertRaises(APIError):self.call('POST','image-studio/jobs/'+j['id']+'/transfer',transfer)
        transfer.update(target='keyframe',slot=3)
        scene=self.call('POST','image-studio/jobs/'+j['id']+'/transfer',transfer)
        transfer.update(expected_revision=scene['revision'])
        with self.assertRaises(APIError):self.call('POST','image-studio/jobs/'+j['id']+'/transfer',transfer)
        transfer.update(target='last')
        self.assertIsNotNone(self.call('POST','image-studio/jobs/'+j['id']+'/transfer',transfer)['scene']['last'])
        refined=self.call('POST','image-studio/jobs/'+j['id']+'/refine',{'asset_id':o['id'],'prompt':'Change the light to dusk.'})
        v=self.validate(refined);self.assertEqual(v['source_count'],1);self.assertIn('scene to refine',v['request']['prompt'])
        reused=self.call('POST','image-studio/jobs/'+j['id']+'/reuse');self.assertEqual(reused['settings'],r['settings'])
    def test_approval_idempotency_restart_and_live_lock(self):
        r=self.image();route='image-studio/drafts/'+r['id']+'/generate'
        with self.assertRaises(APIError):self.call('POST',route,{'expected_revision':1},'missing-approval')
        j=self.generate(r)
        self.assertEqual(self.call('POST',route,{'expected_revision':1,'approved':True},'image-test-once')['id'],j['id'])
        restarted=studio.Studio(mock=True,storage=self.temp.name)
        self.assertEqual(restarted.agent.dispatch('POST','/agent/v1/'+route,{'expected_revision':1,'approved':True},'image-test-once')[1]['id'],j['id'])
        other=self.image()
        with self.assertRaises(APIError):self.generate(other,'image-test-once')
        self.app.mock=False
        with patch.dict(studio.CONFIG,{'live_generations_enabled':False}),patch('httpx.Client') as network:
            with self.assertRaises(APIError):self.generate(r,'live-image-locked')
            network.assert_not_called()
        spec=self.call('GET','openapi.json');self.assertIn('/image-studio/jobs/{id}/transfer',spec['paths'])
    def test_provider_rejection_is_redacted_and_not_retried(self):
        r=self.image();self.app.mock=False
        response=Mock(status_code=403);response.json.return_value={'error':{'message':'Denied Bearer fake-test-only https://private.invalid/path'}}
        with patch.dict(studio.CONFIG,{'live_generations_enabled':True}),patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake-test-only'}),patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=response
            j=self.generate(r,'stub-rejection-once')
            self.assertEqual(j['status'],'error');self.assertIn('HTTP 403',j['message'])
            self.assertNotIn('fake-test-only',str(j));self.assertNotIn('private.invalid',str(j))
            repeated=self.call('POST','image-studio/drafts/'+r['id']+'/generate',{'expected_revision':1,'approved':True},'stub-rejection-once')
            self.assertEqual(repeated['id'],j['id']);self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)

    def test_live_transport_stub_no_real_network(self):
        r=self.image();self.app.mock=False
        response=Mock(status_code=200);response.json.return_value={'data':[{'b64_json':PNG.split(',')[1]}]}
        with patch.dict(studio.CONFIG,{'live_generations_enabled':True}),patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake-test-only'}),patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=response
            j=self.generate(r,'stub-live-image')
            self.assertEqual(j['status'],'done');self.assertEqual(client.return_value.__enter__.return_value.post.call_count,1)
            self.assertEqual(client.return_value.__enter__.return_value.post.call_args.kwargs['json']['response_format'],'url')
            self.assertTrue(client.return_value.__enter__.return_value.post.call_args.kwargs['json']['deferred'])
        self.assertNotIn('fake-test-only',str(j))

    def test_grok_500_context_keeps_connection_and_never_retries(self):
        r=self.image();self.app.mock=False
        response=Mock(status_code=500);response.json.return_value={'error':{'message':'Auth context expired.'}}
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake-test-only'}),patch('httpx.Client') as client:
            post=client.return_value.__enter__.return_value.post;post.return_value=response
            j=self.generate(r,'expired-auth-once')
            self.assertEqual(j['status'],'error');self.assertEqual(j['error_kind'],'upstream_auth_context')
            self.assertTrue(self.app.state['signed_in'])
            self.assertIn('Your connection was kept',j['message'])
            self.assertEqual(post.call_count,1);self.assertEqual(j['outputs'],[])

    def test_grok_401_requires_reconnection(self):
        r=self.image();self.app.mock=False
        response=Mock(status_code=401);response.json.return_value={'error':{'message':'Invalid token'}}
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake-test-only'}),patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=response
            j=self.generate(r,'auth-401-once')
            self.assertEqual(j['error_kind'],'authentication_expired');self.assertFalse(self.app.state['signed_in'])

    def test_grok_connection_check_contacts_provider_without_generation(self):
        self.app.mock=False
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake-test-only'}),patch('httpx.Client') as client:
            transport=client.return_value.__enter__.return_value
            transport.get.return_value=Mock(status_code=200)
            self.assertTrue(self.app.check_grok_connection()['signed_in'])
            self.assertEqual(transport.get.call_args.kwargs['headers']['Authorization'],'Bearer fake-test-only')
            transport.get.return_value=Mock(status_code=500)
            with self.assertRaises(ValueError):self.app.check_grok_connection()
            self.assertTrue(self.app.state['signed_in'])
            transport.get.return_value=Mock(status_code=401)
            self.assertFalse(self.app.check_grok_connection()['signed_in'])
            transport.post.assert_not_called()

if __name__=='__main__':unittest.main()
