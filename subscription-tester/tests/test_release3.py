import base64
import copy
import io
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from PIL import Image
from studio_server import Studio,StudioHandler
from workspace_accounts import WorkspaceAccounts,CURRENT_PROFILE,digest
from agent_api import APIError
import openai_images

class EditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ffmpeg=shutil.which('ffmpeg') or ('/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').is_file() else None)
        if not ffmpeg:raise unittest.SkipTest('Install FFmpeg to run the real editing export tests.')
        cls.fixtures=tempfile.TemporaryDirectory();root=Path(cls.fixtures.name);cls.red=root/'red.mp4';cls.blue=root/'blue.mp4';cls.audio=root/'score.wav'
        cls.addClassCleanup(cls.fixtures.cleanup)
        subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=c=red:s=160x90:r=24:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(cls.red)],check=True)
        subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x90:r=24:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(cls.blue)],check=True)
        subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','sine=frequency=880:duration=3',str(cls.audio)],check=True)
    @classmethod
    def tearDownClass(cls):cls.fixtures.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name);self.e=self.app.editing
        self.o=self.app.productions.dispatch('POST',[],{'kind':'quick','title':'SampleHero teaser'})[1];self.t=self.e.timeline(self.o['production']['id'])
    def tearDown(self):self.app.productions.sql.close();self.tmp.cleanup()
    def upload(self,path):return self.e.upload({'name':path.name,'base64':base64.b64encode(path.read_bytes()).decode()})
    def settings(self):
        a=self.upload(self.red);b=self.upload(self.blue);music=self.upload(self.audio)
        clip=lambda m,i,left,right:dict(id=i,source={'kind':'upload','id':m['id']},**{'in':left,'out':right},volume=.5,label=i)
        return dict(title='SampleHero / laboratory',clips=[clip(a,'red',.5,2),clip(b,'blue',.25,1)],audio=[dict(clip(music,'music',0,3),start=.2,volume=.3)],titles=[dict(id='title',text="100%: SampleHero's [lab]\nOpening",start=0,end=1,position='bottom',size=36,color='#ffffff')],output=dict(ratio='16:9',resolution='720p',fps=24))
    def wait(self,j):
        limit=time.monotonic()+40
        while time.monotonic()<limit:
            with self.app.agent.lock:job=self.e.p.get(j['id'],'export')
            if job['status'] not in ('queued','rendering'):return job
            time.sleep(.05)
        self.fail('Export did not complete')
    def test_real_export_trimming_sequence_titles_audio_and_snapshot(self):
        s=self.settings();t=self.e.save(self.t['id'],dict(s,expected_revision=1));j=self.e.export(t['id'],{'expected_revision':2},'test-export-1')
        updated=self.e.save(t['id'],dict(expected_revision=2,title='A later edit'))
        done=self.wait(j);self.assertEqual(done['status'],'done',done.get('error'));self.assertEqual(done['snapshot']['title'],s['title']);self.assertEqual(updated['revision'],3)
        file=self.e.file(j['id']);info=self.e.probe(file);self.assertAlmostEqual(info['duration'],2.25,delta=.09);self.assertEqual((info['width'],info['height']),(1280,720));self.assertTrue(info['audio'])
        def pixel(at):
            r=subprocess.run([self.e.ffmpeg,'-v','error','-ss',str(at),'-i',str(file),'-frames:v','1','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True);return Image.open(io.BytesIO(r.stdout)).getpixel((640,240))
        red=pixel(.2);blue=pixel(1.8);self.assertGreater(red[0],red[2]+150);self.assertGreater(blue[2],blue[0]+150)
        raw=subprocess.run([self.e.ffmpeg,'-v','error','-i',str(file),'-map','0:a','-f','s16le','-'],capture_output=True,check=True).stdout;self.assertGreater(len(set(raw[:48000])),20)
        manifest=json.loads(self.e.file(j['id'],True).read_text());self.assertEqual(manifest['revision'],2)
    def test_invalid_timeline_and_stale_revision_preserve_edit(self):
        s=self.settings();saved=self.e.save(self.t['id'],dict(s,expected_revision=1))
        for bad in [dict(clips=[dict(s['clips'][0],out=3)]),dict(titles=[dict(s['titles'][0],end=10)]),dict(audio=[dict(s['audio'][0],start=20)]),dict(output={'ratio':'4:3','resolution':'720p','fps':24}),dict(clips=[dict(s['clips'][0],volume=float('nan'))])]:
            with self.assertRaises(APIError):self.e.save(self.t['id'],dict(bad,expected_revision=2))
            self.assertEqual(self.e.p.get(self.t['id'],'timeline'),saved)
        with self.assertRaises(APIError):self.e.save(self.t['id'],dict(title='Stale',expected_revision=1))
    def test_source_scope_upload_validation_and_episode_ownership(self):
        self.assertTrue(self.app.storage.is_absolute())
        m=self.upload(self.red)
        with tempfile.TemporaryDirectory() as root:
            other=Studio(mock=True,storage=root)
            with self.assertRaises(APIError):other.editing.source({'kind':'upload','id':m['id']})
            with self.assertRaises(APIError):other.editing.p.get(self.t['id'],'timeline')
            other.productions.sql.close()
        for bad in ({'kind':'path','id':str(self.red)},{'kind':'upload','id':m['id'],'path':str(self.red)}):
            with self.assertRaises(APIError):self.e.source(bad)
        with self.assertRaises(APIError):self.e.upload({'name':'bad.mp4','base64':base64.b64encode(b'garbage').decode()})
        story=self.app.productions.dispatch('POST',[],{'kind':'story','title':'Story'})[1]
        with self.assertRaises(APIError):self.e.timeline(story['production']['id'],'foreign-episode')
    def test_relative_state_directory_exports_after_worker_changes_directory(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            app=Studio(mock=True,storage=Path(root).relative_to(Path.cwd()))
            try:
                editor=app.editing
                production=app.productions.dispatch('POST',[],{'kind':'quick','title':'Relative state'})[1]
                timeline=editor.timeline(production['production']['id'])
                media=editor.upload({'name':'red.mp4','base64':base64.b64encode(self.red.read_bytes()).decode()})
                timeline=editor.save(timeline['id'],dict(expected_revision=1,clips=[dict(id='clip',source={'kind':'upload','id':media['id']},**{'in':0,'out':1},volume=1,label='Opening')]))
                job=editor.export(timeline['id'],{'expected_revision':timeline['revision']},'relative-state-export')
                deadline=time.monotonic()+40
                while time.monotonic()<deadline:
                    with app.agent.lock:result=editor.p.get(job['id'],'export')
                    if result['status'] not in ('queued','rendering'):break
                    time.sleep(.05)
                self.assertEqual(result['status'],'done',result.get('error'))
                self.assertAlmostEqual(editor.probe(editor.file(job['id']))['duration'],1,delta=.09)
            finally:app.productions.sql.close()
    def test_export_idempotency_and_cancellation(self):
        s=self.settings();t=self.e.save(self.t['id'],dict(s,expected_revision=1));gate=threading.Event();original=self.e.worker
        def held(identity):gate.wait(5);original(identity)
        with patch.object(self.e,'worker',held):
            j=self.e.export(t['id'],{'expected_revision':2},'repeat-key');self.assertEqual(j['id'],self.e.export(t['id'],{'expected_revision':2},'repeat-key')['id'])
            self.e.dispatch('POST',['exports',j['id'],'cancel'],{},None);gate.set()
            done=self.wait(j);self.assertEqual(done['status'],'cancelled');self.assertFalse((self.app.storage/'exports'/j['id']/'export.mp4').exists())
    def test_collaborator_edit_context_review_apply_and_undo(self):
        s=self.settings();t=self.e.save(self.t['id'],dict(s,expected_revision=1));ctx=self.app.creative.context({'production_id':self.o['production']['id'],'stage':'edit','scope':'production'})
        result={'reply':'Reverse the two clips','actions':[dict(kind='timeline',target_id=t['id'],values_json=json.dumps({'clips':list(reversed(t['clips']))}))]}
        actions=self.app.creative.parse(result,ctx)
        with self.e.p.sql:job=self.e.p.new('assistant',mock=True,status='done',context=ctx,actions=actions,result=result,episode_id=None,scene_id=None)
        applied=self.app.creative.apply(job);self.assertEqual(self.e.p.get(t['id'],'timeline')['clips'][0]['id'],'blue')
        self.app.creative.apply(applied,undo=True);self.assertEqual(self.e.p.get(t['id'],'timeline')['clips'][0]['id'],'red')

    def picture(self,color='blue'):
        buf=io.BytesIO();Image.new('RGB',(160,90),color).save(buf,format='PNG')
        return self.app.upload({'name':'lab.png','data_url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()})
    def test_grouped_library_recurses_and_excludes_trashed_subtree(self):
        p=self.app.productions
        root=p.dispatch('POST',[],{'kind':'story','title':'Example Series'})[1]
        child=p.dispatch('POST',[],{'kind':'story','title':'Related story'})[1]
        quick=self.o
        p.dispatch('POST',[child['production']['id'],'membership'],{'expected_revision':1,'parent_production_id':root['production']['id']})
        p.dispatch('POST',[quick['production']['id'],'membership'],{'expected_revision':1,'parent_production_id':child['production']['id']})
        shot=quick['shots'][0];self.app.history.append(dict(id='take',status='done',video='local-fixture',created_at=1,settings={'_studio_video_id':shot['video_id']}))
        job=dict(id='image-job',mock=True,draft=self.app.images.draft(shot['image_id']),status='done',created_at=2)
        from image_studio import mock_png
        a=self.app.images.cache(mock_png(),job);job['outputs']=[a];self.app.images.db['jobs'].append(job)
        pic=self.picture();self.app.save_reference({'title':'Training Lab','handle':'Training_Lab','category':'Location','description':'A laboratory.','images':[{'asset_id':pic['id']}]})
        library=self.e.sources(root['production']['id'],root['episodes'][0]['id'])
        self.assertEqual(library['scope']['production_count'],3);self.assertEqual(library['takes'][0]['source']['id'],'take')
        self.assertEqual(library['images'][0]['source']['id'],a['id']);self.assertFalse(library['images'][0]['approved'])
        self.assertEqual(library['assets'][0]['source']['id'],pic['id'])
        self.assertIn(pic['id'],[m['source']['id'] for m in library['uploads']])
        p.dispatch('POST',[child['production']['id'],'trash'],{'expected_revision':2})
        library=self.e.sources(root['production']['id'],root['episodes'][0]['id']);self.assertEqual(library['takes'],[]);self.assertEqual(library['images'],[])
    def test_image_approval_scope_and_transition_validation(self):
        from image_studio import mock_png
        job=dict(id='image-job',mock=True,draft={'title':'Test image','settings':{'ratio':'16:9'}});a=self.app.images.cache(mock_png(),job)
        with self.assertRaises(APIError):self.e.source({'kind':'image','id':a['id']})
        next(x for x in self.app.assets if x['id']==a['id'])['approved']=True
        self.assertTrue(self.e.source({'kind':'image','id':a['id']})[0]['image'])
        with tempfile.TemporaryDirectory() as root:
            other=Studio(mock=True,storage=root)
            try:
                with self.assertRaises(APIError):other.editing.source({'kind':'image','id':a['id']})
            finally:other.productions.sql.close()
        pic=self.picture();clip=dict(id='pic',source={'kind':'image','id':pic['id']},**{'in':0,'out':2},volume=0,label='Lab')
        s=dict(title='Images',clips=[clip,dict(clip,id='pic2',transition={'type':'dissolve','duration':.5})],audio=[],titles=[],output={'ratio':'16:9','resolution':'720p','fps':24})
        from editing_studio import timeline_duration
        self.assertEqual(timeline_duration(self.e.validate(s)['clips']),3.5)
        for changes in ({'in':1},{'transition':{'type':'dissolve','duration':.5}}):
            with self.assertRaises(APIError):self.e.validate({**s,'clips':[dict(clip,**changes)]})
        for tr in ({'type':'wipe','duration':.5},{'type':'cut','duration':.5},{'type':'fade','duration':1.5},{'type':'fade','duration':.52}):
            with self.assertRaises(APIError):self.e.validate({**s,'clips':[clip,dict(clip,id='pic2',transition=tr)]})
        with self.assertRaises(APIError):self.e.upload({'name':'fake.png','base64':base64.b64encode(b'not an image').decode()})
    def test_video_to_image_transition_export_duration_and_pixels(self):
        red=self.upload(self.red);pic=self.picture()
        clip=lambda source,identity:dict(id=identity,source=source,**{'in':0,'out':2},volume=.5,label=identity)
        for fps,effect in ((24,'dissolve'),(24,'fade'),(30,'dissolve'),(30,'fade')):
            clips=[clip({'kind':'upload','id':red['id']},'opening'),dict(clip({'kind':'image','id':pic['id']},'lab'),transition={'type':effect,'duration':.5})]
            old=self.e.p.get(self.t['id'],'timeline');saved=self.e.save(old['id'],dict(expected_revision=old['revision'],clips=clips,output=dict(ratio='16:9',resolution='720p',fps=fps)))
            result=self.wait(self.e.export(saved['id'],{'expected_revision':saved['revision']},f'test-transition-{fps}-{effect}'))
            self.assertEqual(result['status'],'done',result.get('error'));path=self.e.file(result['id']);self.assertAlmostEqual(self.e.probe(path)['duration'],3.5,delta=.1)
            rate=subprocess.run([self.e.ffprobe,'-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,check=True).stdout.strip()
            self.assertEqual(rate,f'{fps}/1')
            def pixel(at):
                r=subprocess.run([self.e.ffmpeg,'-v','error','-ss',str(at),'-i',str(path),'-frames:v','1','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True)
                return Image.open(io.BytesIO(r.stdout)).getpixel((640,240))
            opening,middle,end=pixel(.3),pixel(1.75),pixel(3)
            self.assertGreater(opening[0],200);self.assertGreater(end[2],200)
            if effect=='dissolve':self.assertGreater(middle[0],60);self.assertGreater(middle[2],60)
            else:
                # Decode in sequence rather than seeking to a timestamp, which
                # can select a neighboring frame across MP4 concatenation cuts.
                # At 30 fps the exact midpoint lies between two encoded frames.
                raw=subprocess.run([self.e.ffmpeg,'-v','error','-i',str(path),'-vf','crop=2:2:640:240,format=rgb24','-fps_mode','passthrough','-f','rawvideo','-'],capture_output=True,check=True).stdout
                frames=[tuple(raw[i:i+3]) for i in range(0,len(raw),12)]
                center=1.75*fps
                nearby=frames[int(center)-1:int(center)+3]
                darkest=min(max(rgb) for rgb in nearby)
                self.assertLess(darkest,60,f'{fps} fps fade never reaches black near its midpoint: {nearby}')
                # Both sides must approach and leave black, then reach blue.
                self.assertGreater(frames[round(1.5*fps)][0],150)
                self.assertGreater(frames[round(2*fps)][2],150)
            self.assertFalse(list(path.parent.glob('trans-*.mp4')))
    def test_failed_saved_video_download_has_recovery_message_without_changing_edit(self):
        self.app.history.append(dict(id='expired-take',status='done',video='https://result.invalid/expired',settings={}))
        with patch.object(self.app,'download',side_effect=ValueError('Download failed.')):
            with self.assertRaises(APIError) as error:self.e.source({'kind':'take','id':'expired-take'})
        self.assertEqual(error.exception.code,'missing_media');self.assertIn('Upload your saved MP4',str(error.exception));self.assertEqual(self.e.p.get(self.t['id'],'timeline'),self.t)
    def test_uploaded_still_image_can_export_without_video(self):
        pic=self.picture('green');m=self.upload(self.app.asset(pic['id'])[1]);self.assertTrue(m['image'])
        saved=self.e.save(self.t['id'],{'expected_revision':1,'clips':[dict(id='still',source={'kind':'upload','id':m['id']},**{'in':0,'out':1},volume=0,label='Still') ]})
        result=self.wait(self.e.export(saved['id'],{'expected_revision':2},'still-image-export'))
        self.assertEqual(result['status'],'done',result.get('error'));self.assertAlmostEqual(result['media']['duration'],1,delta=.09)

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name);self.accounts=WorkspaceAccounts(self.app,True)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);self.http.tester=self.app;self.http.accounts=self.accounts;self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.base=f'http://127.0.0.1:{self.http.server_port}';self.a=httpx.Client(base_url=self.base);self.b=httpx.Client(base_url=self.base);self.a.get('/');self.b.get('/')
    def tearDown(self):
        self.a.close();self.b.close();self.http.shutdown();self.http.server_close();self.thread.join()
        for app in self.accounts.apps.values():app.productions.sql.close()
        self.accounts.sql.close();self.tmp.cleanup()
    def post(self,c,path,data):return c.post(path,json=data,headers={'Origin':self.base,'X-Tester':'local'})
    def test_private_browser_records_assets_jobs_and_tokens(self):
        aid=self.a.get('/api/studio-account').json()['workspace_id'];bid=self.b.get('/api/studio-account').json()['workspace_id'];self.assertNotEqual(aid,bid)
        r=self.post(self.a,'/api/agent/productions',{'kind':'quick','title':'Private scene'});self.assertEqual(r.status_code,201);pid=r.json()['production']['id']
        self.assertEqual(self.b.get('/api/agent/productions/'+pid).status_code,404);self.assertEqual(self.b.get('/api/agent/productions').json(),[])
        from image_studio import mock_png
        app=self.accounts.app(aid);asset=app.upload({'name':'test.png','data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode()})
        self.assertEqual(self.b.get('/api/assets/'+asset['id']).status_code,404)
        token=app.agent.token
        r=httpx.get(self.base+'/agent/v1/productions/'+pid,headers={'Authorization':'Bearer '+token});self.assertEqual(r.status_code,200)
        r=httpx.get(self.base+'/agent/v1/productions/'+pid,headers={'Authorization':'Bearer '+self.accounts.app(bid).agent.token});self.assertEqual(r.status_code,404)
    def test_csrf_stale_tabs_and_cookie_expiry_fail_closed(self):
        self.assertEqual(self.a.post('/api/studio-account/guest',json={},headers={'Origin':'https://evil.example','X-Tester':'local'}).status_code,403)
        aid=self.a.get('/api/studio-account').json()['workspace_id'];self.post(self.a,'/api/studio-account/guest',{})
        self.assertEqual(self.a.get('/api/agent/productions',headers={'X-Workspace-ID':aid}).status_code,409)
        self.a.cookies.clear();self.assertEqual(self.a.get('/api/agent/productions').status_code,401);self.assertEqual(self.a.get('/').status_code,200)
        header=self.a.get('/').headers.get('set-cookie','')
        fresh=httpx.get(self.base+'/');self.assertIn('HttpOnly',fresh.headers['set-cookie']);self.assertIn('SameSite=Lax',fresh.headers['set-cookie'])
    def test_encrypted_credentials_and_worker_context_isolation(self):
        aid=self.a.get('/api/studio-account').json()['workspace_id'];bid=self.b.get('/api/studio-account').json()['workspace_id']
        fake='sk-test-not-a-real-key'
        self.assertEqual(self.post(self.a,'/api/studio-account/api-key',{'key':fake}).status_code,200)
        profile=self.accounts.profile(aid);self.assertEqual(profile.get('api-key'),fake);self.assertNotIn(fake.encode(),(profile.root/'api-key.enc').read_bytes());self.assertIsNone(self.accounts.profile(bid).get('api-key'))
        with patch.dict('os.environ',{'OPENAI_API_KEY':'sk-host-secret'}):
            token=CURRENT_PROFILE.set(self.accounts.profile(bid))
            try:self.assertEqual(openai_images.api_key(),'')
            finally:CURRENT_PROFILE.reset(token)
        values={};a=self.accounts.app(aid);b=self.accounts.app(bid)
        a.spawn(lambda:values.update(a=openai_images.api_key())).join();b.spawn(lambda:values.update(b=openai_images.api_key())).join();self.assertEqual(values,{'a':fake,'b':''})
        profile.set('codex',{'auth_mode':'chatgpt','tokens':{'secret':'test-secret'}})
        with profile.codex_home() as home:self.assertEqual(json.loads((home/'auth.json').read_text())['auth_mode'],'chatgpt')
        self.assertFalse(home.exists());self.assertNotIn(b'test-secret',(profile.root/'codex.enc').read_bytes())
    def test_oidc_state_binding_expiry_and_one_time_callback(self):
        login=self.post(self.a,'/api/studio-account/signin',{}).json();from urllib.parse import urlsplit,parse_qs
        params=parse_qs(urlsplit(login['url']).query);self.assertEqual(params['client_id'],['dynamic_agent_client']);self.assertEqual(params['code_challenge_method'],['S256']);state=params['state'][0]
        url='/auth/callback?'+urlencode_safe(dict(state=state,code='code',client_id='oaiapp_test'))
        self.assertEqual(self.b.get(url).status_code,400)
        claims={'sub':'verified-sub','name':'John Doe','email':'a@example.com'}
        with patch.object(self.accounts,'validate_identity',return_value=claims),patch('httpx.post',return_value=SimpleNamespace(status_code=200,json=lambda:{'id_token':'test','access_token':'private','scope':'openid profile email chatgpt.tokens.use.direct','expires_in':3600})):
            response=self.a.get(url);self.assertEqual(response.status_code,200)
        status=self.a.get('/api/studio-account').json();self.assertTrue(status['verified']);self.assertEqual(status['name'],'John Doe');self.assertNotIn('private',response.text);self.assertEqual(self.a.get(url).status_code,400)
        login=self.post(self.b,'/api/studio-account/signin',{}).json();state=parse_qs(urlsplit(login['url']).query)['state'][0]
        with self.accounts.sql:self.accounts.sql.execute('UPDATE oauth SET expires=0 WHERE state=?',(digest(state),))
        self.assertEqual(self.b.get('/auth/callback?state='+state).status_code,400)
    def test_verified_jwt_signature_audience_nonce_and_email_not_identity(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048);claims={'iss':'https://auth.openai.com','sub':'user','aud':'oaiapp_test','nonce':'nonce','iat':int(time.time()),'exp':int(time.time()+300)}
        with patch('jwt.PyJWKClient.get_signing_key_from_jwt',return_value=SimpleNamespace(key=key.public_key())):
            signed=jwt.encode(claims,key,algorithm='RS256');self.assertEqual(self.accounts.validate_identity(signed,'oaiapp_test','nonce')['sub'],'user')
            for client,nonce in [('other','nonce'),('oaiapp_test','wrong')]:
                with self.assertRaises(APIError):self.accounts.validate_identity(signed,client,nonce)
            for change in [{'iss':'https://evil.test'},{'exp':0},{'aud':['oaiapp_test','other'],'azp':'other'}]:
                with self.assertRaises(APIError):self.accounts.validate_identity(jwt.encode({**claims,**change},key,algorithm='RS256'),'oaiapp_test','nonce')
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with patch('jwt.PyJWKClient.get_signing_key_from_jwt',return_value=SimpleNamespace(key=key.public_key())),self.assertRaises(APIError):self.accounts.validate_identity(jwt.encode(claims,other,algorithm='RS256'),'oaiapp_test','nonce')
    def test_workspace_namespace_security_headers_and_logout_rotation(self):
        script=self.a.get('/static/workspace.js');self.assertIn('studioStoragePrefix',script.text);self.assertIn("frame-ancestors 'none'",script.headers['content-security-policy']);self.assertEqual(script.headers['x-frame-options'],'DENY')
        before=self.a.get('/api/studio-account').json()['workspace_id'];self.assertEqual(self.post(self.a,'/api/studio-account/logout',{}).status_code,200);after=self.a.get('/api/studio-account').json()['workspace_id'];self.assertNotEqual(before,after)
    def test_guest_work_is_recoverable_and_account_names_are_private(self):
        aid=self.a.get('/api/studio-account').json()['workspace_id']
        with self.accounts.sql:self.accounts.sql.execute("UPDATE workspaces SET kind='account',name='Private account',identity='trusted-test' WHERE id=?",(aid,))
        self.assertEqual(self.b.get('/api/studio-account').json()['accounts'],[])
        original=self.b.get('/api/studio-account').json()['workspace_id'];self.post(self.b,'/api/studio-account/guest',{})
        self.assertTrue(self.b.get('/api/studio-account').json()['can_restore_guest']);self.post(self.b,'/api/studio-account/restore-guest',{})
        self.assertEqual(self.b.get('/api/studio-account').json()['workspace_id'],original)
    def test_mock_identity_never_contacts_provider_and_is_not_verified(self):
        self.accounts.mock_identity=True
        with patch('httpx.post',side_effect=AssertionError('Mock sign-in must not contact OpenAI')):
            login=self.post(self.a,'/api/studio-account/signin',{}).json();response=self.a.get(login['url']);self.assertEqual(response.status_code,200)
        status=self.a.get('/api/studio-account').json();self.assertEqual(status['kind'],'mock-account');self.assertFalse(status['verified'])
    def test_returning_identity_mismatch_preserves_account_and_credentials(self):
        from urllib.parse import parse_qs,urlsplit
        aid=self.a.get('/api/studio-account').json()['workspace_id']
        old=json.dumps(['https://auth.openai.com','oaiapp_return','original'],separators=(',',':'))
        with self.accounts.sql:self.accounts.sql.execute("UPDATE workspaces SET kind='account',identity=? WHERE id=?",(old,aid))
        profile=self.accounts.profile(aid);profile.set('openai',{'client_id':'oaiapp_return','access_token':'original-token'})
        login=self.post(self.b,'/api/studio-account/signin',{'account_id':aid}).json();state=parse_qs(urlsplit(login['url']).query)['state'][0]
        with patch.object(self.accounts,'validate_identity',return_value={'sub':'different','email':'same@example.com'}),patch('httpx.post',return_value=SimpleNamespace(status_code=200,json=lambda:{'id_token':'different','access_token':'wrong-token'})):
            response=self.b.get('/auth/callback?'+urlencode_safe(dict(state=state,code='code',client_id='oaiapp_return')));self.assertEqual(response.status_code,400)
        self.assertEqual(profile.get('openai')['access_token'],'original-token');self.assertFalse(self.b.get('/api/studio-account').json()['verified'])

def urlencode_safe(value):
    from urllib.parse import urlencode
    return urlencode(value)

if __name__=='__main__':unittest.main()
