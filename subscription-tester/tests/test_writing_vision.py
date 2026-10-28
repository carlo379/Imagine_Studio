"""Actual pixel attachments and frozen frame evidence, with no live model calls."""
import base64,copy,hashlib,io,json,tempfile,unittest
import httpx
from unittest.mock import Mock,patch
from PIL import Image
from studio_server import Studio
from video_direction import SCHEMA,POLICY
import writing_vision
import story_studio
import prompt_guides as guides

class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.app.productions.sql.close)
        buf=io.BytesIO();Image.new('RGB',(24,16),'red').save(buf,format='PNG')
        self.asset=self.app.upload({'name':'captured.png','data_url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()})
        self.scene=self.app.agent.create({'scene':{'prompt':'Open the right door.','first':self.asset,'last':self.asset,'keys':[{'id':'middle','source':self.asset,'slot':3}]}})
        self.context={'_visual_frames':writing_vision.frames(self.app,self.scene['scene'])}
    def test_freeze_roles_pixels_and_reject_changed_missing_frames(self):
        frozen=copy.deepcopy(self.context);attached=writing_vision.attach(self.app,frozen)
        self.assertEqual([f['role'] for f in attached['visual_frames']],['first frame','last frame','keyframe'])
        self.assertEqual(attached['visual_frames'][2]['time_seconds'],1)
        self.assertEqual(len(attached['_writing_images']),3)
        self.assertTrue(all(i['url'].startswith('data:image/png;base64,') for i in attached['_writing_images']))
        self.assertNotIn('data:image',json.dumps(frozen))
        _,path=self.app.asset(self.asset['id']);path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):writing_vision.attach(self.app,frozen)
    def reference_scene(self):
        scene=copy.deepcopy(self.scene['scene'])
        scene['refs']=[dict(id='robot-ref',source=self.asset),dict(id='human-ref',source=self.asset)]
        scene['named']=[dict(handle='SampleHero2',title='SampleHero',category='Character',refIds=['robot-ref']),
            dict(handle='Mark',title='Mark',category='Character',refIds=['human-ref'])]
        return scene
    def test_reference_pixels_and_exact_generation_tags_are_separate_from_attachment_order(self):
        scene=self.reference_scene()
        plan=writing_vision.frames(self.app,scene)
        attached=writing_vision.attach(self.app,{'_visual_frames':plan})
        frames=attached['visual_frames']
        self.assertEqual([f['role'] for f in frames],['first frame','last frame','keyframe','reference image','reference image'])
        self.assertEqual([f['prompt_tag'] for f in frames],['<IMAGE_0>',None,None,'<IMAGE_1>','<IMAGE_2>'])
        self.assertEqual(frames[3]['attachment_index'],4)
        self.assertEqual(frames[3]['identities'],[dict(handle='SampleHero2',name='SampleHero',category='Character')])
        _,path=self.app.asset(self.asset['id'])
        expected=hashlib.sha256(path.read_bytes()).hexdigest()
        for index,image in enumerate(attached['_writing_images']):
            raw=base64.b64decode(image['url'].split(',',1)[1])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),expected)
            self.assertEqual(frames[index]['sha256'],expected)
        self.assertNotIn('base64',json.dumps(plan))
        scene['first']=None
        plan=writing_vision.frames(self.app,scene)
        self.assertEqual([p['prompt_tag'] for p in plan[-2:]],['<IMAGE_0>','<IMAGE_1>'])
        scene['refs'].reverse()
        plan=writing_vision.frames(self.app,scene)
        self.assertEqual(plan[-2]['identities'][0]['name'],'Mark')
        self.assertEqual(plan[-2]['prompt_tag'],'<IMAGE_0>')
    def test_reference_changes_invalidate_frozen_plan_even_when_source_id_is_unchanged(self):
        scene=self.reference_scene();scene.update(first=None,last=None,keys=[])
        frozen=writing_vision.frames(self.app,scene)
        buf=io.BytesIO();Image.new('RGB',(24,16),'blue').save(buf,format='PNG')
        _,path=self.app.asset(self.asset['id']);path.write_bytes(buf.getvalue())
        self.assertNotEqual(frozen,writing_vision.frames(self.app,scene))
        with self.assertRaisesRegex(ValueError,'changed'):
            writing_vision.attach(self.app,{'_visual_frames':frozen})
    def test_public_reference_is_hash_frozen_and_changes_are_rejected(self):
        scene=self.reference_scene();scene.update(first=None,last=None,keys=[])
        scene['refs']=scene['refs'][:1];scene['refs'][0]['source']={'url':'https://example.com/robot.png','name':'Robot'}
        _,path=self.app.asset(self.asset['id']);raw=path.read_bytes()
        with patch.object(writing_vision.openai_images,'source_bytes',return_value=(raw,'image/png')):
            plan=writing_vision.frames(self.app,scene)
            attached=writing_vision.attach(self.app,{'_visual_frames':plan})
        self.assertEqual(attached['visual_frames'][0]['sha256'],hashlib.sha256(raw).hexdigest())
        with patch.object(writing_vision.openai_images,'source_bytes',return_value=(raw+b'changed','image/png')):
            with self.assertRaisesRegex(ValueError,'changed'):
                writing_vision.attach(self.app,{'_visual_frames':plan})
        with patch.object(writing_vision.openai_images,'source_bytes',side_effect=httpx.ReadTimeout('offline')):
            with self.assertRaisesRegex(ValueError,'could not be read'):
                writing_vision.frames(self.app,scene)
    def test_preparation_proof_covers_reference_pixels_not_only_frame_pixels(self):
        scene=copy.deepcopy(self.scene['scene']);scene.update(first=None,last=None,keys=[],
            refs=[dict(id='identity',source=self.asset)])
        record=self.app.agent.create({'scene':scene})
        context=guides.capture({'_visual_frames':writing_vision.frames(self.app,record['scene'])},
            [dict(model=scene['model'],fields=['prompt'],operation='reference-to-video')])
        marked=self.app.prompting.mark('video',record,context,'fixture','codex')
        self.assertTrue(self.app.prompting.current('video',marked))
        buf=io.BytesIO();Image.new('RGB',(24,16),'green').save(buf,format='PNG')
        _,path=self.app.asset(self.asset['id']);path.write_bytes(buf.getvalue())
        self.assertFalse(self.app.prompting.current('video',marked))
    def test_codex_attaches_pixels_outside_text_with_tools_disabled(self):
        calls=[];schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer']}
        class RPC:
            def __init__(self,**kwargs):pass
            def account(self):return {'signed_in':True}
            def rpc(self,method,data):calls.append((method,data));return {'thread':{'id':'fixture'}} if method=='thread/start' else {}
            def receive(self):
                if not hasattr(self,'sent'):
                    self.sent=True;return {'method':'item/completed','params':{'item':{'type':'agentMessage','text':'{"answer":"Visible: closed rear doors."}'}}}
                return {'method':'turn/completed','params':{'turn':{'status':'completed'}}}
            def close(self):pass
        with patch.object(story_studio.openai_images,'CodexRPC',RPC):
            context={'_visual_frames':writing_vision.frames(self.app,self.reference_scene())}
            result=story_studio.writing_reply(writing_vision.attach(self.app,context),schema,writing_vision.POLICY)
        turn=next(data for method,data in calls if method=='turn/start')
        self.assertEqual([i['type'] for i in turn['input']],['text']+['image']*5)
        self.assertNotIn('base64',turn['input'][0]['text']);self.assertNotIn('_writing_images',turn['input'][0]['text'])
        self.assertIn('SampleHero2',turn['input'][0]['text']);self.assertIn('<IMAGE_1>',turn['input'][0]['text'])
        thread=next(data for method,data in calls if method=='thread/start')
        self.assertFalse(thread['config']['features.view_image']);self.assertIn('Visible:',result['answer'])
    def test_grok_attaches_images_and_text_without_changing_auth_route(self):
        response=Mock(status_code=200);response.json.return_value={'choices':[{'message':{'content':'{"answer":"Visible: closed doors."}'}}]}
        with patch('studio_server.oauth_headers',return_value={'Authorization':'Bearer fixture'}),patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value=response
            context={'_visual_frames':writing_vision.frames(self.app,self.reference_scene())}
            self.app.filmmaking.request_plan('grok',context,{'type':'object','properties':{'answer':{'type':'string'}}},'Observe frames.')
            call=client.return_value.__enter__.return_value.post.call_args
            self.assertEqual(call.args[0],'https://api.x.ai/v1/chat/completions')
            content=call.kwargs['json']['messages'][1]['content']
            self.assertEqual([i['type'] for i in content],['text']+['image_url']*5)
            self.assertNotIn('base64',content[0]['text']);self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png'))
            self.assertIn('reference image',content[0]['text']);self.assertIn('<IMAGE_2>',content[0]['text'])
    def test_shot_direction_returns_observations_and_proof_without_changing_frames(self):
        out=self.app.productions.dispatch('POST',[],{'kind':'quick','title':'Shot'})[1];shot=out['shots'][0]
        video=self.app.agent.record(shot['video_id'])
        self.app.agent.edit(video['id'],{'expected_revision':video['revision'],'scene':self.scene['scene']})
        self.app.mock=False;self.app.spawn=lambda fn,*args:fn(*args)
        self.app.filmmaking.series.writing_access=Mock()
        reply=guides.WritingResult({'direction':'Mark opens the right door.','asset_summaries':[],'duration_seconds':5,'duration_reason':'One action.','notes':[],'starting_frame_observations':['Visible: closed hinged doors.','Uncertain: obscured left handle.']})
        self.app.filmmaking.request_plan=Mock(return_value=reply)
        video=self.app.agent.record(video['id']);shot=self.app.productions.get(shot['id'],'shot')
        job=self.app.filmmaking.video_directions.prepare(shot['id'],{'expected_revision':shot['revision'],'expected_video_revision':video['revision'],'approved':True},'vision-shot-test')
        self.assertEqual(job['status'],'done',job.get('error'))
        self.assertEqual(len(job['result']['starting_frame_observations']),2)
        applied=self.app.filmmaking.video_directions.apply(shot['id'],{'job_id':job['id'],'expected_revision':job['revision'],'expected_video_revision':video['revision'],'replace_settings':True})
        self.assertEqual(applied['draft']['scene']['first'],video['scene']['first'])
        self.assertTrue(self.app.prompting.current('video',applied['draft']))
        self.assertNotIn('Visible:',applied['draft']['scene']['prompt'])
        _,path=self.app.asset(self.asset['id']);path.write_bytes(b'changed')
        self.assertFalse(self.app.prompting.current('video',applied['draft']))
