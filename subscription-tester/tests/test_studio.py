import base64
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import studio_server as studio
from video_rules import validate_video

PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\nmock').decode()
IMAGE = {'url': PNG}
def request(**extras):
    return {'model':'grok-imagine-video-1.5','duration':5,'aspect_ratio':'16:9','resolution':'480p','prompt':'A scene', **extras}

class RulesTests(unittest.TestCase):
    def test_provider_voice_roster_rejects_removed_ids_before_submission(self):
        from video_rules import VOICES
        self.assertEqual(len(VOICES), 26)
        for voice in ('liora', 'aurora'):
            with self.subTest(voice=voice), self.assertRaisesRegex(ValueError, 'preset roster'):
                validate_video(request(reference_audios=[{'voice_id':voice}]), studio.CONFIG)
        for voice in VOICES:
            validate_video(request(reference_audios=[{'voice_id':voice.upper()}]), studio.CONFIG)

    def test_combined_request_and_first_frame_tags(self):
        body=request(image=IMAGE,reference_images=[IMAGE]*7,reference_audios=[{'voice_id':'eve'}],
            keyframes=[{'image':IMAGE,'timestamp_s':1/3},{'image':IMAGE,'timestamp_s':14/3}],last_frame=IMAGE,
            prompt='Move <IMAGE_7> while <AUDIO_0> speaks.')
        self.assertEqual(validate_video(body,studio.CONFIG),body)
        with self.assertRaisesRegex(ValueError,'does not exist'):
            validate_video({**body,'prompt':'<IMAGE_8>'},studio.CONFIG)
    def test_grid_bounds_and_collisions(self):
        for values in [(0,), (5,), (.1,), (4.9,), (1/3,1/3), (float('nan'),)]:
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate_video(request(keyframes=[{'image':IMAGE,'timestamp_s':v} for v in values]),studio.CONFIG)
        validate_video(request(keyframes=[{'image':IMAGE,'timestamp_s':1/3}]),studio.CONFIG)
    def test_retired_model_and_reference_resolution(self):
        for field in ({'reference_audios':[{'voice_id':'eve'}]},{'last_frame':IMAGE},{'keyframes':[{'image':IMAGE,'timestamp_s':1}]},{'image':IMAGE,'reference_images':[IMAGE]},{'generate_audio':False}):
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_video(request(model='grok-imagine-video',**field),studio.CONFIG)
        with self.assertRaisesRegex(ValueError,'two documented'):
            validate_video(request(model='grok-imagine-video',reference_images=[IMAGE]),studio.CONFIG)
        with self.assertRaises(ValueError):validate_video(request(reference_images=[IMAGE],resolution='1080p'),studio.CONFIG)
        validate_video(request(resolution='1080p'),studio.CONFIG)
    def test_visual_prompt_optional_and_limits(self):
        validate_video(request(prompt='',last_frame=IMAGE),studio.CONFIG)
        for extra in ({'prompt':''},{'reference_images':[IMAGE]*15},{'reference_audios':[{'voice_id':'fake'}]},
                      {'reference_audios':[{'voice_id':'eve'}],'generate_audio':False},{'duration':True},{'aspect_ratio':'auto'},
                      {'image':{'url':'http://local/image.png'}},{'prompt':'<IMAGE_REMOVED_0>'}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):validate_video(request(**extra),studio.CONFIG)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_upload_resolve_mock_history_and_download(self):
        asset=self.app.upload({'data_url':PNG,'name':'test.png'})
        settings=request(reference_images=[{'asset_id':asset['id']}])
        self.assertEqual(self.app.resolve(settings)['reference_images'],[IMAGE])
        with self.assertRaises(ValueError):self.app.start_video(settings,True)
        self.app.update(signed_in=True)
        with self.assertRaises(ValueError):self.app.start_video(settings,False)
        identity=self.app.start_video(settings,True)
        with self.assertRaises(ValueError):self.app.start_video(settings,True)
        for _ in range(30):
            if self.app.snapshot()['phase']=='done':break
            time.sleep(.1)
        self.assertEqual(self.app.snapshot()['phase'],'done')
        self.assertTrue(self.app.download(identity).exists())
        restored=studio.Studio(mock=True,storage=self.temp.name)
        self.assertEqual(restored.records()[0]['settings'],settings)
        self.assertNotIn('Authorization',json.dumps(restored.records()))
    def test_live_gate_blocks_before_oauth(self):
        self.app.mock=False;self.app.update(signed_in=True)
        with patch.dict(studio.CONFIG,{'live_generations_enabled':False}),patch.object(studio,'oauth_headers') as auth,self.assertRaisesRegex(ValueError,'locked'):
            self.app.start_video(request(),True)
        auth.assert_not_called()
    def test_oauth_only_one_post_poll_and_no_secrets(self):
        import hermes_cli.auth as auth
        self.app.mock=False
        job={'id':'job','mock':False,'status':'pending','settings':request(),'request_id':None,'video':None}
        self.app.history=[job]
        client=MagicMock();client.post.return_value.status_code=200;client.post.return_value.json.return_value={'request_id':'req_1'}
        client.get.return_value.status_code=200;client.get.return_value.json.return_value={'status':'done','video':{'url':'https://vidgen.x.ai/example.mp4','respect_moderation':True}}
        with patch.object(auth,'resolve_xai_oauth_runtime_credentials',return_value={'provider':'xai-oauth','auth_mode':'oauth_device_code','api_key':'private-secret'}),patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            self.app.video_worker(request(),job)
        self.assertEqual(client.post.call_count,1);self.assertEqual(client.get.call_count,1)
        self.assertEqual(client.post.call_args.args[0],studio.VIDEO_ENDPOINT)
        self.assertNotIn('private-secret',json.dumps(self.app.snapshot())+json.dumps(self.app.records()))
        client.reset_mock();job['status']='error'
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake'}),patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            self.app.video_worker(None,job)
        client.post.assert_not_called();client.get.assert_called_once()
    def test_polling_202_continues_without_another_generation(self):
        import httpx
        self.app.mock=False
        job={'id':'job','mock':False,'status':'pending','request_id':'req_202'}
        self.app.history=[job]
        client=MagicMock()
        client.get.side_effect=[httpx.Response(202), httpx.Response(202,json={'status':'pending'}),
            httpx.Response(200,json={'status':'done','video':{'url':'https://vidgen.x.ai/a.mp4','duration':1},'usage':{'video_duration':1}})]
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake'}),patch('httpx.Client') as factory,patch.object(studio.time,'sleep'):
            factory.return_value.__enter__.return_value=client
            self.app.video_worker(None,job)
        client.post.assert_not_called()
        self.assertEqual(client.get.call_count,3)
        self.assertEqual(job['status'],'done')
        self.assertEqual(job['output_duration'],1)

    def test_upstream_error_is_shown_and_sanitized_without_retry(self):
        import httpx
        self.app.mock=False
        job={'id':'error-job','status':'pending','request_id':None};self.app.history=[job]
        client=MagicMock()
        client.post.return_value=httpx.Response(400,json={'error':{'message':'Unknown model. Bearer private-token https://example.invalid/?token=private-token'}})
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer private-token'}),patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            self.app.video_worker(request(),job)
        client.post.assert_called_once();client.get.assert_not_called()
        self.assertEqual(job['http_status'],400)
        self.assertIn('Unknown model',job['message'])
        self.assertNotIn('private-token',json.dumps(self.app.records()))
        self.assertNotIn('example.invalid',job['message'])
        self.assertEqual(studio.upstream_error(httpx.Response(400,text='<html>proxy error</html>')), '')

    def test_recorded_audio_denial_closes_relay_and_never_retries(self):
        import httpx
        self.app.mock=False
        raw=b'RIFF'+b'\0'*4+b'WAVE'+b'\0'*20
        body=request(reference_audios=[{'url':'data:audio/wav;base64,'+base64.b64encode(raw).decode()}])
        job={'id':'audio-denied','status':'pending','request_id':None};self.app.history=[job]
        client=MagicMock()
        client.get.return_value=httpx.Response(200,content=raw)
        client.post.return_value=httpx.Response(403,json={'error':{'message':'Caller-supplied URLs in `reference_audios` are not enabled for this team.'}})
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fixture'}),patch('httpx.Client') as factory,patch('recording_relay.RecordingRelay') as relay:
            factory.return_value.__enter__.return_value=client
            relay.return_value.__enter__.return_value.url='https://fixture.trycloudflare.com/private.wav'
            self.app.video_worker(body,job)
            relay.return_value.__exit__.assert_called_once()
        client.post.assert_called_once()
        self.assertEqual(job['audio_reference_access'],'denied')
        self.assertIn('Ask xAI',job['message'])
        self.assertTrue(job['audio_provider_uploads'][0]['delivery_verified'])
        self.assertNotIn('private.wav',json.dumps(job))

    def test_key_and_denied_response_never_fall_back(self):
        import hermes_cli.auth as auth
        with patch.object(auth,'resolve_xai_oauth_runtime_credentials',return_value={'provider':'xai-oauth','auth_mode':'oauth_device_code','api_key':'xai-key'}),self.assertRaises(ValueError):studio.oauth_headers()
        self.app.mock=False
        job={'id':'job','status':'pending','request_id':None};self.app.history=[job]
        client=MagicMock();client.post.return_value.status_code=403
        with patch.object(studio,'oauth_headers',return_value={'Authorization':'Bearer fake'}),patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            self.app.video_worker(request(),job)
        self.assertEqual(client.post.call_count,1);client.get.assert_not_called();self.assertEqual(job['status'],'error')

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.http=studio.ThreadingHTTPServer(('127.0.0.1',0),studio.StudioHandler)
        self.http.tester=studio.Studio(mock=True,storage=self.temp.name)
        self.base=f'http://127.0.0.1:{self.http.server_port}'
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.temp.cleanup()
    def call(self,path,body=None,origin=None):
        import urllib.request,urllib.error
        headers={'Origin':origin or self.base,'X-Tester':'local','Content-Type':'application/json'}
        data=None if body is None else json.dumps(body).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base+path,data,headers)) as response:
                return response.status,response.read(),response.headers
        except urllib.error.HTTPError as error:
            with error:return error.code,error.read(),error.headers
    def test_page_stylesheets_are_served_as_css(self):
        import re
        status,page,_=self.call('/')
        self.assertEqual(status,200)
        styles=re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"',page.decode())
        self.assertIn('/static/editing-workbench.css',[url.split('?',1)[0] for url in styles])
        for url in styles:
            with self.subTest(url=url):
                status,body,headers=self.call(url)
                self.assertEqual(status,200)
                self.assertTrue(headers['Content-Type'].startswith('text/css'))
                self.assertTrue(body.strip())
                if url.split('?',1)[0]=='/static/editing-workbench.css':
                    self.assertIn(b'.ed-workbench-grid{display:grid',body)
                    self.assertIn(b'.production-shell.edit-workspace{grid-template-columns:minmax(0,1fr)}',body)

    def test_server_routes_exact_request_and_origin(self):
        for path in ('/','/tester','/static/studio.js','/static/studio.css','/static/mock-video.mp4','/api/config'):
            self.assertEqual(self.call(path)[0],200,path)
        status,raw,_=self.call('/api/upload',{'name':'a.png','data_url':PNG})
        self.assertEqual(status,201);asset=json.loads(raw)
        status,raw,_=self.call('/api/validate',{'settings':request(reference_images=[{'asset_id':asset['id']}])})
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['request']['reference_images'],[IMAGE])
        self.assertEqual(self.call('/api/video',{'settings':request(),'approved':True},origin='https://other.example')[0],403)
        self.assertEqual(self.call('/api/video',{'settings':request(),'approved':False})[0],400)
    def test_validation_message_and_unfinished_download(self):
        status,raw,_=self.call('/api/validate',{'settings':request(prompt='<IMAGE_9>')})
        self.assertEqual(status,400);self.assertIn('does not exist',json.loads(raw)['error'])
        self.assertEqual(self.call('/api/download/not-a-job')[0],400)
        self.assertNotIn('token',json.dumps(json.loads(self.call('/api/state')[1])))

if __name__=='__main__':unittest.main()
