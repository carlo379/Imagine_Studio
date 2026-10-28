"""Contract and recovery regression tests; temporary storage and mocked providers only."""
import base64
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
import httpx
import image_studio
import openai_images
import studio_server as studio
from agent_api import APIError
from video_rules import MODELS, RATIOS, validate_video
from test_studio import IMAGE, PNG, request

RAW = base64.b64decode(PNG.split(',', 1)[1])

class CapabilityRulesTests(unittest.TestCase):
    def test_only_current_video_models_and_wide_ratios(self):
        for model in MODELS:
            for ratio in ('21:9', '5:2'):
                validate_video(request(model=model, aspect_ratio=ratio, resolution='1080p', generate_audio=False), studio.CONFIG)
        with self.assertRaisesRegex(ValueError, 'two documented'):
            validate_video(request(model='grok-imagine-video'), studio.CONFIG)

    def test_lite_first_frame_and_rejection_of_every_advanced_input(self):
        validate_video(request(model=MODELS[1], image=IMAGE, prompt=''), studio.CONFIG)
        for extras in ({'reference_images':[IMAGE]}, {'reference_audios':[{'voice_id':'EVE'}]},
                       {'last_frame':IMAGE}, {'keyframes':[{'image':IMAGE,'timestamp_s':1}]}):
            with self.subTest(extras=extras), self.assertRaisesRegex(ValueError, 'Lite'):
                validate_video(request(model=MODELS[1], **extras), studio.CONFIG)

    def test_maximum_combined_15_support_and_case_normalization(self):
        body=request(image=IMAGE, reference_images=[IMAGE]*14, last_frame=IMAGE,
                     reference_audios=[{'voice_id':v} for v in ('EVE','Eve','rex')],
                     keyframes=[{'image':IMAGE,'timestamp_s':t} for t in (1,2,3,4)],
                     prompt='<IMAGE_14> speaks with <AUDIO_2>.')
        validated=validate_video(body, studio.CONFIG)
        self.assertEqual([v['voice_id'] for v in validated['reference_audios']], ['eve','eve','rex'])
        for extras in ({'reference_images':[IMAGE]*15},{'reference_audios':[{'voice_id':'eve'}]*4}):
            with self.assertRaisesRegex(ValueError,'14 references, 3 voices'):
                validate_video(request(**extras),studio.CONFIG)

    def test_reference_limit_is_utf8_bytes_including_visual_only_modes(self):
        for extras in ({'reference_images':[IMAGE]}, {'last_frame':IMAGE}, {'keyframes':[{'image':IMAGE,'timestamp_s':1}]}):
            validate_video(request(prompt='🙂'*1024, **extras), studio.CONFIG)
            with self.assertRaisesRegex(ValueError, 'UTF-8 bytes'):
                validate_video(request(prompt='🙂'*1025, **extras), studio.CONFIG)
        validate_video(request(prompt='🙂'*4096), studio.CONFIG)

    def test_keyframe_snap_and_rounded_collision(self):
        body=validate_video(request(keyframes=[{'image':IMAGE,'timestamp_s':1.2}]),studio.CONFIG)
        self.assertEqual(body['keyframes'][0]['timestamp_s'],4/3)
        for times in ((1.2,1.3),(.1,), (4.9,)):
            with self.assertRaises(ValueError):
                validate_video(request(keyframes=[{'image':IMAGE,'timestamp_s':t} for t in times]),studio.CONFIG)

class ImageCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=False,storage=self.temp.name)
        self.images=self.app.images;self.app.update(signed_in=True)
    def tearDown(self):self.temp.cleanup()
    def draft(self, **settings):
        return self.images.create({'title':'Candidates','settings':{'prompt':'A landscape.', **settings}})
    def queued(self, draft):
        from prompt_fixtures import reviewed_prompt
        reviewed_prompt(self.app,'image',draft)
        with patch.dict(self.images.config,{'live_generations_enabled':True}),patch.object(self.app,'spawn'):
            self.images.generate(draft['id'],{'approved':True,'expected_revision':draft['revision']},'capability-test-key')
        return self.images.db['jobs'][0]
    def run_worker(self, job, client, body=None):
        with patch('httpx.Client') as factory,patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer mock-auth'}),patch('image_studio.time.sleep'):
            factory.return_value.__enter__.return_value=client
            self.images.worker(job,job['endpoint'],body)
    def result(self,n=1,model=True):
        return {'status':'done','data':[{'url':f'https://images.x.ai/candidate-{i}.png'} for i in range(n)],
                **({'model':'served-image-model'} if model else {})}

    def test_compiles_deferred_generation_and_editing_with_15k(self):
        draft=self.draft(resolution='1.5k',n=4)
        endpoint,body,count=self.images.compile(draft)
        self.assertTrue(endpoint.endswith('/generations'));self.assertEqual((body['n'],body['resolution'],body['deferred'],body['response_format']), (4,'1.5k',True,'url'))
        asset=self.app.upload({'data_url':PNG,'name':'base.png'})
        edited=self.draft(base={'asset_id':asset['id']},n=2,resolution='1.5k')
        endpoint,body,count=self.images.compile(edited)
        self.assertTrue(endpoint.endswith('/edits'));self.assertEqual(body['n'],2);self.assertTrue(body['deferred']);self.assertEqual(count,1)
        self.assertEqual(len(image_studio.IMAGE_RATIOS),len(set(image_studio.IMAGE_RATIOS)))

    def test_count_options_match_transport_and_do_not_silently_ignore(self):
        for model in openai_images.API_MODELS:
            endpoint,body,_=self.images.compile(self.draft(model=model,n=4))
            self.assertEqual(body['n'],4)
        self.images.compile(self.draft(model='gpt-image-2'))
        for count in (2,4,True,3):
            with self.assertRaises(APIError):self.draft(model='gpt-image-2',n=count)
        for count in (True,0,3,5):
            with self.assertRaises(APIError):self.draft(n=count)

    def test_post_once_poll_202_then_cache_all_candidates_with_metadata(self):
        draft=self.draft(n=4);job=self.queued(draft);body=self.images.compile(draft)[1]
        client=Mock();client.post.return_value=httpx.Response(202,json={'request_id':'request-once'})
        client.get.side_effect=[httpx.Response(202),httpx.Response(202,json={'status':'pending'}),httpx.Response(200,json=self.result(4))]
        with patch.object(openai_images,'grok_result_bytes',return_value=(RAW,'image/png')) as download:
            self.run_worker(job,client,body)
        self.assertEqual(job['status'],'done',job['message']);self.assertEqual(client.post.call_count,1);self.assertEqual(client.get.call_count,3)
        self.assertEqual(download.call_count,4);self.assertEqual(len(job['outputs']),4);self.assertEqual(len({o['id'] for o in job['outputs']}),4)
        self.assertEqual(job['request_id'],'request-once');self.assertEqual(job['requested_model'],image_studio.IMAGE_MODEL)
        self.assertEqual(job['returned_model'],'served-image-model');self.assertEqual(job['model_identity'],'confirmed');self.assertFalse(job['recoverable'])
        # Per-candidate review, download, refinement and transfer operate on the chosen ID.
        output=job['outputs'][2];other=job['outputs'][0]
        self.images.dispatch('POST',['jobs',job['id'],'approve'],{'asset_id':output['id'],'approved':True},None)
        self.assertFalse(other['approved']);self.assertTrue(output['approved'])
        _,downloaded=self.images.dispatch('GET',['jobs',job['id'],'outputs',output['id']],{},None)
        self.assertEqual(downloaded,(RAW,'image/png'))
        _,refinement=self.images.dispatch('POST',['jobs',job['id'],'refine'],{'asset_id':output['id'],'prompt':'Closer view.'},None)
        self.assertEqual(refinement['settings']['base'],{'asset_id':output['id']})
        _,scene=self.images.dispatch('POST',['jobs',job['id'],'transfer'],{'asset_id':output['id'],'new_scene':True,'target':'first'},None)
        self.assertEqual(scene['scene']['first']['id'],output['id'])
        self.assertEqual(json.loads(self.images.path.read_text())['jobs'][0]['request_id'],'request-once')

    def test_restart_and_resume_never_resubmit_and_preserve_partial_cache(self):
        draft=self.draft(n=2);job=self.queued(draft);job.update(request_id='saved-request',recoverable=True)
        output=self.images.cache(RAW,job);output['candidate_index']=0;job['outputs']=[output];self.images.persist()
        app=studio.Studio(mock=False,storage=self.temp.name);self.app=app;self.images=app.images;job=self.images.job(job['id'])
        self.assertEqual(job['status'],'error');self.assertTrue(job['recoverable'])
        with patch.dict(self.images.config,{'live_generations_enabled':True}),self.assertRaisesRegex(APIError,'Resume'):
            self.images.generate(draft['id'],{'approved':True,'expected_revision':draft['revision']},'new-duplicate-key')
        with patch.object(app,'spawn') as spawn:
            resumed=self.images.resume(job)
        self.assertEqual(resumed['status'],'pending');self.assertIsNone(spawn.call_args.args[-1])
        client=Mock();client.get.return_value=httpx.Response(200,json=self.result(2,False))
        with patch.object(openai_images,'grok_result_bytes',return_value=(RAW,'image/png')) as download:
            self.run_worker(job,client)
        client.post.assert_not_called();download.assert_called_once();self.assertEqual(job['outputs'][0]['id'],output['id'])
        self.assertEqual(job['status'],'done');self.assertEqual(job['model_identity'],'unconfirmed');self.assertIsNone(job['returned_model'])

    def test_network_failure_with_id_allows_resume_but_no_id_does_not(self):
        draft=self.draft();job=self.queued(draft);client=Mock()
        client.post.return_value=httpx.Response(200,json={'request_id':'durable-id'});client.get.side_effect=httpx.ReadError('interrupted')
        self.run_worker(job,client,self.images.compile(draft)[1]);self.assertEqual(job['status'],'error');self.assertTrue(job['recoverable'])
        client.post.assert_called_once();self.assertEqual(job['request_id'],'durable-id')
        # A second job whose submission was interrupted has no safe replay path.
        job2=copy.deepcopy(job);job2.update(id='unknown-job',request_id=None,recoverable=False);self.images.db['jobs'].append(job2)
        client.reset_mock();client.post.side_effect=httpx.ReadError('unknown submission state')
        self.run_worker(job2,client,self.images.compile(draft)[1]);self.assertFalse(job2['recoverable'])
        with self.assertRaises(APIError):self.images.resume(job2)

    def test_failed_and_moderated_jobs_terminal_no_automatic_retry(self):
        draft=self.draft();job=self.queued(draft);job.update(request_id='failed-request',recoverable=True)
        client=Mock();client.get.return_value=httpx.Response(200,json={'status':'failed','error':{'message':'Provider failure'}})
        self.run_worker(job,client);client.post.assert_not_called();self.assertFalse(job['recoverable']);self.assertEqual(job['status'],'error')
        job['recoverable']=True;payload=self.result();payload['data'][0]['respect_moderation']=False
        client.get.return_value=httpx.Response(200,json=payload)
        with patch.object(openai_images,'grok_result_bytes') as download:self.run_worker(job,client)
        download.assert_not_called();self.assertFalse(job['recoverable']);self.assertEqual(job['outputs'],[])

    def test_openai_api_batches_return_each_candidate_and_real_metadata(self):
        client=Mock();client.post.return_value=httpx.Response(200,json={'model':'served-api-image','data':[{'b64_json':base64.b64encode(RAW).decode()}]*4},headers={'x-request-id':'openai-request'})
        with patch.object(openai_images,'api_key',return_value='mock-key'),patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            outputs,metadata=openai_images.generate_api('https://api.openai.com/v1/images/generations',{'model':openai_images.API_MODELS[0],'prompt':'Landscape.','n':4},self.images.config)
        self.assertEqual(outputs,[RAW]*4);self.assertEqual(metadata['returned_model'],'served-api-image')
        self.assertEqual(metadata['model_identity'],'confirmed');self.assertEqual(client.post.call_args.kwargs['json']['n'],4)

    def test_image_output_download_never_sends_provider_authorization(self):
        client=MagicMock();response=client.stream.return_value.__enter__.return_value
        response.status_code=200;response.headers={'content-type':'image/png'};response.iter_bytes.return_value=[RAW]
        with patch('openai_images.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            raw,mime=openai_images.source_bytes('https://images.x.ai/result.png',1000)
        self.assertEqual(raw,RAW);self.assertEqual(client.stream.call_args.args,('GET','https://images.x.ai/result.png'))
        self.assertNotIn('headers',client.stream.call_args.kwargs);self.assertFalse(factory.call_args.kwargs['trust_env'])

    def test_video_metadata_without_reported_model_stays_unconfirmed(self):
        for payload_model in (None,'served-video-model'):
            job={'id':'video','settings':request(),'status':'pending','request_id':'saved-video'};self.app.history=[job]
            client=Mock();client.get.return_value=httpx.Response(200,json={'status':'done','video':{'url':'https://vidgen.x.ai/clip.mp4'},**({'model':payload_model} if payload_model else {})})
            with patch('httpx.Client') as factory,patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer mock-auth'}):
                factory.return_value.__enter__.return_value=client;self.app.video_worker(None,job)
            self.assertEqual(job['requested_model'],MODELS[0]);self.assertEqual(job['returned_model'],payload_model)
            self.assertEqual(job['model_identity'],'confirmed' if payload_model else 'unconfirmed')

    def test_historical_scene_preserved_but_cannot_generate_and_lite_does_not_drop_voices(self):
        old=self.app.agent.create({'scene':{'model':'grok-imagine-video','prompt':'Historical.'}})
        self.assertEqual(self.app.agent.record(old['id'])['scene']['model'],'grok-imagine-video')
        self.assertFalse(self.app.agent.validation(old)['valid'])
        lite=self.app.agent.create({'scene':{'model':MODELS[1],'audio':False,'voices':[{'voice':'EVE'}],'prompt':'Motion.'}})
        self.assertFalse(self.app.agent.validation(lite)['valid']);self.assertEqual(lite['scene']['voices'][0]['voice'],'eve')

if __name__=='__main__':unittest.main()
