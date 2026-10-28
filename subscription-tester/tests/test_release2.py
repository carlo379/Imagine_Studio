import base64
import copy
import io
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from PIL import Image
from studio_server import Studio
from agent_api import APIError
from image_studio import mock_png

class Release2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.out=self.call('POST','productions',{'kind':'quick','title':'SampleHero test'})
        self.shot=self.out['shots'][0];self.pid=self.out['production']['id']
    def tearDown(self):self.app.productions.sql.close();self.tmp.cleanup()
    def call(self,method,path,data=None,key=None):return self.app.agent.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def request(self,**fields):return dict(production_id=self.pid,shot_id=self.shot['id'],scope='shot',stage='generate',message='SampleHero enters the quiet laboratory.',approved=True,**fields)
    def chat(self):
        j=self.call('POST','creative/messages',self.request(),'release2-test-key')
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            j=self.call('GET','creative/messages/'+j['id'])
            if j['status']!='pending':break
            time.sleep(.01)
        self.assertEqual(j['status'],'done',j.get('error'));return j
    def upload(self):return self.app.upload(dict(name='Test reference',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
    def reference(self):
        a=self.upload();return self.call('POST','asset-studio',dict(title='SampleHero',handle='SampleHero',description='A cream and black robot.',category='Character',images=[{'asset_id':a['id']}]))
    def test_assistant_apply_undo_and_no_generation(self):
        old=copy.deepcopy(self.app.agent.record(self.shot['video_id'])['scene'])
        with patch.object(self.app,'start_video',side_effect=AssertionError('No generation')):
            j=self.chat();self.assertEqual(len(j['actions']),2)
            self.assertEqual(self.app.agent.record(self.shot['video_id'])['scene'],old)
            j=self.call('POST','creative/messages/'+j['id']+'/apply')
            self.assertTrue(j['applied']);self.assertEqual(self.app.agent.record(self.shot['video_id'])['scene']['prompt'],self.request()['message'])
            self.call('POST','creative/messages/'+j['id']+'/undo')
            self.assertEqual(self.app.agent.record(self.shot['video_id'])['scene'],old)
    def test_assistant_stale_proposal_is_atomic(self):
        j=self.chat();r=self.app.agent.record(self.shot['video_id']);self.app.agent.edit(r['id'],dict(expected_revision=r['revision'],title='Changed elsewhere'))
        before=copy.deepcopy(self.app.images.draft(self.shot['image_id']))
        with self.assertRaises(APIError):self.call('POST','creative/messages/'+j['id']+'/apply')
        self.assertEqual(self.app.images.draft(self.shot['image_id']),before)
    def test_apply_rolls_back_sql_and_json_after_mid_action_failure(self):
        ctx=self.app.creative.context(dict(production_id=self.pid,scope='production',stage='develop'))
        before=self.app.productions.get(self.pid,'production');image=copy.deepcopy(self.app.images.draft(self.shot['image_id']))
        result=dict(reply='Coordinated proposal',actions=[dict(kind='brief',target_id=self.pid,values_json=json.dumps({'brief':'New brief'})),dict(kind='image',target_id=image['id'],values_json=json.dumps({'title':'New image title'})),dict(kind='video',target_id=self.shot['video_id'],values_json=json.dumps({'title':'New video title'}))])
        actions=self.app.creative.parse(result,ctx)
        with self.app.productions.sql:j=self.app.productions.new('assistant',status='done',mock=True,actions=actions,context=ctx,production_id=self.pid,episode_id=None,scene_id=None)
        execute=self.app.creative.execute
        def fail_last(action,job):
            if action['kind']=='video':raise RuntimeError('Simulated final action failure')
            return execute(action,job)
        with patch.object(self.app.creative,'execute',side_effect=fail_last),self.assertRaises(RuntimeError):self.app.creative.apply(j)
        self.assertEqual(self.app.productions.get(self.pid,'production'),before)
        self.assertEqual(self.app.images.draft(image['id']),image)
        self.assertFalse(self.app.productions.get(j['id'],'assistant').get('applied',False))
    def test_scope_and_action_allowlist(self):
        ctx=self.call('POST','creative/context',self.request());other=self.call('POST','productions',dict(kind='quick',title='Other'))
        for kind,target in [('video',other['shots'][0]['video_id']),('generate',self.shot['video_id'])]:
            with self.assertRaises(APIError):self.app.creative.parse(dict(reply='Test',actions=[dict(kind=kind,target_id=target,values_json='{"title":"No"}')]),ctx)
    def test_existing_shot_revision_and_asset_mentions_apply(self):
        asset=self.reference()
        shot=self.call('PUT','productions/shots/'+self.shot['id'],dict(expected_revision=self.shot['revision'],notes='Existing notes'))
        ctx=self.app.creative.context(self.request());self.assertEqual(ctx['shots'][0]['revision'],shot['revision'])
        scene=copy.deepcopy(self.app.agent.record(self.shot['video_id'])['scene']);scene['prompt']='A close-up of @SampleHero.'
        result=dict(reply='Improve the shot',actions=[dict(kind='shot',target_id=shot['id'],values_json=json.dumps({'notes':'Improved notes'})),dict(kind='video',target_id=self.shot['video_id'],values_json=json.dumps({'scene':scene}))])
        actions=self.app.creative.parse(result,ctx)
        with self.app.productions.sql:j=self.app.productions.new('assistant',status='done',mock=True,actions=actions,context=ctx,production_id=self.pid,episode_id=None,scene_id=None)
        self.app.creative.apply(j)
        self.assertEqual(self.app.productions.get(shot['id'],'shot')['notes'],'Improved notes')
        self.assertEqual(self.app.agent.record(self.shot['video_id'])['scene']['named'][0]['id'],asset['id'])
    def test_idempotency_and_approval(self):
        d=self.request();d['approved']=False
        with self.assertRaises(APIError):self.call('POST','creative/messages',d,'release2-approval')
        j=self.chat();same=self.call('POST','creative/messages',self.request(),'release2-test-key');self.assertEqual(same['id'],j['id'])
        d=self.request();d['message']='Changed'
        with self.assertRaises(APIError):self.call('POST','creative/messages',d,'release2-test-key')
    def test_undo_rejects_later_edits(self):
        j=self.chat();self.call('POST','creative/messages/'+j['id']+'/apply');r=self.app.images.draft(self.shot['image_id']);self.app.images.edit(r['id'],dict(expected_revision=r['revision'],title='Keep newer edits'))
        with self.assertRaises(APIError):self.call('POST','creative/messages/'+j['id']+'/undo')
        self.assertEqual(self.app.images.draft(r['id'])['title'],'Keep newer edits')
    def test_asset_versions_restore_and_saved_snapshot(self):
        a=self.reference();draft=self.app.images.create(dict(title='Old shot',named_references=['SampleHero']))
        old=copy.deepcopy(draft['settings']['bindings'][0]['snapshot'])
        newer=self.call('PUT','asset-studio/'+a['id'],dict(expected_revision=1,description='A robot with a hat.'))
        self.assertEqual(newer['revision'],2);self.assertEqual(self.app.images.draft(draft['id'])['settings']['bindings'][0]['snapshot'],old)
        restored=self.call('POST','asset-studio/'+a['id']+'/restore',dict(expected_revision=2,revision=1));self.assertEqual(restored['description'],a['description']);self.assertEqual(restored['revision'],3)
        self.assertEqual(len(self.call('GET','asset-studio/'+a['id']+'/versions')),3)
        with self.assertRaises(APIError):self.call('PUT','asset-studio/'+a['id'],dict(expected_revision=1,description='stale'))
    def test_asset_development_and_approval_gate(self):
        a=self.reference();d=self.call('POST','asset-studio/'+a['id']+'/develop',dict(expected_revision=1))
        self.assertEqual(d['settings']['bindings'][0]['snapshot']['id'],a['id'])
        self.assertEqual(self.call('POST','asset-studio/development/lookup',dict(draft_id=d['id']))['id'],a['id'])
        output=self.app.images.cache(mock_png(),dict(id='fake',mock=True,draft=d))
        with self.assertRaises(APIError):self.call('POST','asset-studio/'+a['id']+'/adopt',dict(expected_revision=1,asset_id=output['id']))
    def test_local_crop_rotate_resize_preserves_original(self):
        a=self.upload();_,path=self.app.asset(a['id']);raw=path.read_bytes()
        j=self.call('POST','precision/edits',dict(asset_id=a['id'],draft_id=self.shot['image_id'],operations=[dict(kind='crop',region=dict(x=0,y=0,width=.5,height=1)),dict(kind='rotate',degrees=90),dict(kind='resize',width=128,height=64)]))
        self.assertEqual(path.read_bytes(),raw);o=j['outputs'][0];self.assertEqual((o['width'],o['height']),(128,64));self.assertFalse(o['approved']);self.assertEqual(j['provider'],'local')
    def test_local_erase_alpha_and_invalid_inputs(self):
        a=self.upload();j=self.call('POST','precision/edits',dict(asset_id=a['id'],operations=[dict(kind='erase',points=[[.5,.5]],width=.1)]));_,path=self.app.asset(j['outputs'][0]['id']);im=Image.open(path);self.assertEqual(im.getpixel((im.width//2,im.height//2))[3],0)
        for op in [dict(kind='resize',width=100000,height=100000),dict(kind='crop',region=dict(x=.9,y=0,width=.5,height=1)),dict(kind='erase',points=[[float('nan'),0]])]:
            with self.assertRaises(APIError):self.call('POST','precision/edits',dict(asset_id=a['id'],operations=[op]))
    def test_region_refinement_forks_source_and_guards_stale_revision(self):
        asset=self.upload();original=self.app.images.create({'title':'Original prop','settings':{'prompt':'Original instructions'}})
        before=copy.deepcopy(self.app.images.draft(original['id']))
        data=dict(asset_id=asset['id'],draft_id=original['id'],expected_revision=original['revision'],region=dict(x=.1,y=.1,width=.2,height=.2),settings={**original['settings'],'prompt':'Correct the selected area'})
        with patch.object(self.app,'spawn') as spawn:
            refined=self.call('POST','precision/refine',data);spawn.assert_not_called()
        self.assertNotEqual(refined['id'],original['id'])
        self.assertEqual(self.app.images.draft(original['id']),before)
        self.assertEqual(refined['settings']['base'],{'asset_id':asset['id']})
        self.assertEqual(refined['settings']['edit_region'],data['region'])
        count=len(self.app.images.db['drafts'])
        with self.assertRaises(APIError):self.call('POST','precision/refine',{**data,'expected_revision':999})
        self.assertEqual(len(self.app.images.db['drafts']),count)

    def test_region_mask_only_for_api_and_no_generation(self):
        a=self.upload();r=dict(x=.1,y=.2,width=.3,height=.4)
        for model in ['gpt-image-2.5-sunburst','gpt-image-2','grok-imagine-image-2.0']:
            d=self.call('POST','precision/refine',dict(asset_id=a['id'],region=r,settings=dict(model=model,prompt='Correct the hand.')))
            endpoint,body,_=self.app.images.compile(d)
            self.assertEqual('mask' in body,model.startswith('gpt-image-2.5'))
            self.assertIn('Edit only the region',body['prompt'])
            if 'mask' in body:
                im=Image.open(io.BytesIO(base64.b64decode(body['mask']['url'].split(',')[1])));self.assertEqual(im.mode,'RGBA');self.assertEqual(im.getpixel((100,100))[3],0);self.assertEqual(im.getpixel((0,0))[3],255)
    def test_state_restored_after_restart(self):
        a=self.reference();j=self.chat();self.app.productions.sql.close();self.app=Studio(mock=True,storage=self.tmp.name)
        self.assertEqual(self.call('GET','creative/messages/'+j['id'])['status'],'done');self.assertEqual(self.call('GET','asset-studio/'+a['id'])['revision'],1)
    def test_multi_shot_creation_and_undo_preserve_drafts(self):
        ctx=self.app.creative.context(dict(production_id=self.pid,scope='production',stage='storyboard'))
        result=dict(reply='Add two shots',actions=[dict(kind='add_shot',target_id=self.pid,values_json=json.dumps({'title':name})) for name in ('Close-up','Reverse')])
        actions=self.app.creative.parse(result,ctx)
        with self.app.productions.sql:j=self.app.productions.new('assistant',status='done',mock=True,actions=actions,context=ctx,production_id=self.pid,episode_id=None,scene_id=None)
        self.app.creative.apply(j);self.assertEqual(len(self.call('GET','productions/'+self.pid)['shots']),3)
        j=self.app.productions.get(j['id'],'assistant');self.app.creative.apply(j,undo=True)
        self.assertEqual(len(self.call('GET','productions/'+self.pid)['shots']),1)
        self.assertEqual(len(self.app.images.db['drafts']),3)
    def test_reference_revision_change_blocks_stale_media_proposal(self):
        a=self.reference();data=self.request();data['message']='A close-up of @SampleHero.'
        j=self.call('POST','creative/messages',data,'reference-change-key')
        for _ in range(100):
            j=self.call('GET','creative/messages/'+j['id'])
            if j['status']!='pending':break
            time.sleep(.01)
        self.call('PUT','asset-studio/'+a['id'],dict(expected_revision=1,description='New identity'))
        with self.assertRaises(APIError):self.call('POST','creative/messages/'+j['id']+'/apply')
    def test_undo_new_shot_keeps_later_local_candidate(self):
        ctx=self.app.creative.context(dict(production_id=self.pid,scope='production',stage='storyboard'))
        actions=self.app.creative.parse(dict(reply='Add a shot',actions=[dict(kind='add_shot',target_id=self.pid,values_json='{"title":"New shot"}')]),ctx)
        with self.app.productions.sql:j=self.app.productions.new('assistant',status='done',mock=True,actions=actions,context=ctx,production_id=self.pid,episode_id=None,scene_id=None)
        j=self.app.creative.apply(j);shot=self.app.productions.get(j['actions'][0]['created_id'],'shot');a=self.upload()
        self.call('POST','precision/edits',dict(asset_id=a['id'],draft_id=shot['image_id'],operations=[dict(kind='rotate',degrees=90)]))
        with self.assertRaises(APIError):self.app.creative.apply(j,undo=True)
        self.assertFalse(self.app.productions.get(shot['id'],'shot').get('archived',False))
    def test_grok_structured_oauth_reply_has_no_api_fallback(self):
        ctx=self.app.creative.context(self.request());ctx['message']='Discuss continuity'
        with self.app.productions.sql:j=self.app.productions.new('assistant',production_id=self.pid,scope='shot',episode_id=None,scene_id=None,shot_id=self.shot['id'],mock=False,status='pending',provider='grok',model='grok-4.3',context=ctx,actions=[])
        with patch('studio_server.oauth_headers',return_value={'Authorization':'Bearer private-subscription-token'}),patch('httpx.Client') as factory:
            client=factory.return_value.__enter__.return_value;client.post.return_value.status_code=200;client.post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(dict(reply='Continuity looks good.',actions=[]))}}]}
            self.app.creative.worker(j)
            client.post.assert_called_once();args=client.post.call_args
            self.assertEqual(args.args[0],'https://api.x.ai/v1/chat/completions');self.assertEqual(args.kwargs['json']['response_format']['type'],'json_schema')
        saved=self.app.productions.get(j['id'],'assistant');self.assertEqual(saved['status'],'done');self.assertNotIn('private-subscription-token',json.dumps(saved))
    def test_openai_mask_is_multipart_not_json(self):
        import openai_images
        a=self.upload();d=self.call('POST','precision/refine',dict(asset_id=a['id'],region=dict(x=.1,y=.1,width=.2,height=.2),settings=dict(model='gpt-image-2.5-flare',prompt='Correct this region')))
        endpoint,body,_=self.app.images.compile(d)
        with patch.object(openai_images,'api_key',return_value='private-key'),patch('httpx.Client') as factory:
            c=factory.return_value.__enter__.return_value;c.post.return_value.status_code=200;c.post.return_value.json.return_value={'data':[{'b64_json':base64.b64encode(mock_png()).decode()}]}
            openai_images.generate_api(endpoint,body,self.app.agent.config)
            args=c.post.call_args.kwargs;self.assertNotIn('mask',args['data']);self.assertEqual([f[0] for f in args['files']],['image[]','mask'])
