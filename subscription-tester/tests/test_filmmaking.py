import base64
import copy
import tempfile
import time
import unittest
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError
from image_studio import mock_png

class FilmmakingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name);self.f=self.app.filmmaking;self.p=self.app.productions
        self.out=self.p.dispatch('POST',[],dict(kind='story',title='A robot finds a signal'))[1];self.pid=self.out['production']['id']
    def tearDown(self):self.p.sql.close();self.tmp.cleanup()
    def world(self):return self.f.save_world(self.pid,dict(expected_revision=0,answers=dict(idea='A robot discovers a mysterious signal.',characters='SampleHero, a small silver robot.',locations='A warm workshop.',plot='Discovery, a choice, and a new friendship.',style='Cinematic natural light.')))
    def plan(self,provider='codex'):
        w=self.world()
        with patch.object(self.app,'spawn',lambda fn,j:fn(j)):
            j=self.f.plan(self.pid,dict(expected_revision=w['revision'],approved=True,provider=provider),'world-plan-key')
        return self.p.get(j['id'],'world-job')
    def apply(self):
        j=self.plan();return self.f.apply(j,dict(expected_revision=j['revision'],image_model='gpt-image-2'))
    def staging(self):return dict(camera=dict(yaw=0,elevation=8,distance=5,target_x=0,target_y=1,target_z=0,lens=35),subjects=[dict(name='SampleHero',asset_id=None,x=0,z=0,rotation=0,pose='stand',arms=0,head=0)],ratio='16:9',environment='Workshop',style='Natural light')
    def image(self,r,approved=False):
        j=dict(id='job-'+r['id'],mock=True,draft=copy.deepcopy(self.app.images.draft(r['draft_id'])),status='done',created_at=time.time())
        a=self.app.images.cache(mock_png(),j);j['outputs']=[a];self.app.images.db['jobs'].append(j)
        if approved:self.app.images.dispatch('POST',['jobs',j['id'],'approve'],dict(asset_id=a['id'],approved=True),None)
        return a,j
    def test_plan_apply_preserves_originals_and_links_everything_without_generation(self):
        original=copy.deepcopy(self.out);w=self.world();self.assertNotEqual(w['id'],self.pid);self.assertEqual(self.p.get(self.pid,'production'),original['production'])
        with patch.object(self.app,'spawn',lambda fn,j:fn(j)):
            j=self.f.plan(self.pid,dict(expected_revision=1,approved=True),'world-plan-key')
        j=self.p.get(j['id'],'world-job');self.assertEqual(j['status'],'done')
        result=copy.deepcopy(j['result']);result['synopsis']='My revised synopsis.'
        j=self.f.edit_plan(j,dict(expected_revision=j['revision'],result=result));applied=self.f.apply(j,dict(expected_revision=j['revision']))
        o=self.p.outline(self.pid);self.assertEqual(o['production'],original['production']);self.assertEqual(o['episodes'][0],original['episodes'][0]);self.assertEqual(len(o['episodes']),2);self.assertEqual(len(applied['shot_ids']),2)
        self.assertEqual(applied['applied_plan']['synopsis'],'My revised synopsis.');self.assertEqual(len(applied['asset_ids']),4)
        for sid in applied['shot_ids']:
            s=self.p.get(sid,'shot');self.assertEqual(s['episode_id'],applied['episode_id']);self.assertEqual(self.app.images.draft(s['image_id'])['settings']['model'],'gpt-image-2');self.assertTrue(self.app.agent.record(s['video_id'])['scene']['prompt'])
        for aid in applied['asset_ids']:
            a=self.p.get(aid,'world-asset');child=self.p.get(a['media_production_id'],'production');self.assertEqual(child['parent_production_id'],self.pid);self.assertEqual(child['world_origin_id'],self.pid)
        count=len(self.p.all('production'));self.f.apply(applied,{});self.assertEqual(len(self.p.all('production')),count);self.assertEqual(self.app.images.db['jobs'],[]);self.assertEqual(self.app.records(),[])
    def test_revisions_idempotency_and_strict_validation(self):
        j=self.plan();w=self.f.save_world(self.pid,dict(expected_revision=1,answers=dict(idea='New idea')))
        self.assertEqual(self.f.plan(self.pid,dict(expected_revision=1,approved=True,provider='codex'),'world-plan-key')['id'],j['id'])
        with self.assertRaises(APIError):self.f.apply(j,dict(expected_revision=j['revision']))
        with self.assertRaises(APIError):self.f.save_world(self.pid,dict(expected_revision=1,answers={}))
        with self.assertRaises(APIError):self.f.plan(self.pid,dict(expected_revision=w['revision'],approved=True),'world-plan-key')
        bad=copy.deepcopy(j['result']);bad['scenes'][0]['shots'][0]['image_prompt']='x'*2201
        with self.assertRaises(APIError):self.f.edit_plan(j,dict(expected_revision=j['revision'],result=bad))
        self.assertEqual(self.p.get(j['id'],'world-job')['result'],j['result'])
    def test_adopt_requires_approved_own_candidate_and_links_later_views(self):
        j=self.apply();r=self.p.get(j['asset_ids'][0],'world-asset');a,job=self.image(r)
        with self.assertRaises(APIError):self.f.adopt(r['id'],dict(expected_revision=1,asset_id=a['id']))
        self.app.images.dispatch('POST',['jobs',job['id'],'approve'],dict(asset_id=a['id'],approved=True),None)
        adopted=self.f.adopt(r['id'],dict(expected_revision=1,asset_id=a['id']));ref=self.app.asset_studio.get(adopted['reference_id']);self.assertEqual(ref['category'],'Character')
        later=self.p.get(j['asset_ids'][1],'world-asset');draft=self.app.images.draft(later['draft_id']);self.assertEqual(draft['settings']['bindings'][0]['snapshot']['id'],ref['id'])
        other,_=self.image(later,True)
        with self.assertRaises(APIError):self.f.adopt(r['id'],dict(expected_revision=2,asset_id=other['id']))
        next_view=self.f.adopt(later['id'],dict(expected_revision=1,asset_id=other['id']));self.assertEqual(next_view['reference_id'],ref['id']);self.assertEqual(len(self.app.asset_studio.get(ref['id'])['images']),2)
    def test_composition_and_movement_preserve_settings_and_reject_conflicts(self):
        j=self.apply();sid=j['shot_ids'][0];shot=self.p.get(sid,'shot');image=self.app.images.draft(shot['image_id']);stage=self.staging()
        r=self.f.save_direction(sid,dict(expected_revision=0,staging=stage));self.assertNotEqual(r['id'],sid);self.assertEqual(self.p.get(sid,'shot'),shot)
        payload=dict(expected_revision=r['revision'],expected_image_revision=image['revision'],prompt='Use the staging composition.',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode())
        self.f.compose(sid,payload);after=self.app.images.draft(image['id']);self.assertEqual(after['settings']['model'],image['settings']['model']);self.assertEqual(len(after['settings']['extras']),1)
        with self.assertRaises(APIError):self.f.compose(sid,payload)
        d=self.f.direction(sid);payload.update(expected_revision=d['revision'],expected_image_revision=after['revision']);self.f.compose(sid,payload);after2=self.app.images.draft(image['id']);self.assertEqual(len(after2['settings']['extras']),1)
        v=copy.deepcopy(self.app.agent.record(shot['video_id']));brief=self.f.movement(sid,dict(expected_revision=v['revision'],prompt='A gentle orbit.'))
        self.assertEqual(brief['camera_brief'],'A gentle orbit.');self.assertEqual(self.app.agent.record(v['id']),v)
        job=self.app.prompting.prepare('video',v['id'],dict(expected_revision=v['revision'],approved=True,instruction=brief['camera_brief']),'camera-prompt-fixture')
        deadline=time.monotonic()+2
        while job['status']=='pending' and time.monotonic()<deadline:
            time.sleep(.01);job=self.app.prompting.public(self.p.get(job['id'],'media-prompt-job'))
        self.assertEqual(job['status'],'done',job.get('error'))
        updated=self.app.prompting.apply('video',v['id'],dict(job_id=job['id'],expected_revision=job['revision'],expected_media_revision=v['revision']))['draft']
        self.assertEqual(updated['scene']['duration'],v['scene']['duration'])
        with self.assertRaises(APIError):self.f.movement(sid,dict(expected_revision=v['revision'],prompt='Stale'))
        bad=copy.deepcopy(stage);bad['camera']['distance']=float('nan')
        with self.assertRaises(APIError):self.f.save_direction(sid,dict(expected_revision=d['revision']+1,staging=bad))
        self.assertEqual(self.app.images.db['jobs'],[])
    def test_failed_apply_rolls_back_and_restart_keeps_plan_and_staging(self):
        j=self.plan();before=copy.deepcopy(self.p.all('production'));scenes=copy.deepcopy(self.app.agent.db);images=copy.deepcopy(self.app.images.db);stories=copy.deepcopy(self.app.stories.db)
        with patch.object(self.app.images,'edit',side_effect=ValueError('fixture failure')):
            with self.assertRaises(ValueError):self.f.apply(j,dict(expected_revision=j['revision']))
        self.assertEqual(self.p.all('production'),before);self.assertEqual(self.app.agent.db,scenes);self.assertEqual(self.app.images.db,images);self.assertEqual(self.app.stories.db,stories)
        applied=self.f.apply(self.p.get(j['id'],'world-job'),dict(expected_revision=j['revision']));sid=applied['shot_ids'][0];saved=self.f.save_direction(sid,dict(expected_revision=0,staging=self.staging()))
        self.p.sql.close();self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.f=self.app.filmmaking;self.assertEqual(self.f.direction(sid),saved);self.assertTrue(self.p.get(j['id'],'world-job')['applied'])
    def test_live_gate_no_network_and_workspace_scope(self):
        self.world();self.app.mock=False
        with patch.object(self.app.images,'account_status',return_value={'subscription':{'signed_in':False}}),patch('filmmaking_studio.writing_reply') as writer:
            with self.assertRaises(APIError):self.f.plan(self.pid,dict(expected_revision=1,approved=True),'no-network-key')
            writer.assert_not_called()
        with tempfile.TemporaryDirectory() as root:
            other=Studio(mock=True,storage=root)
            try:
                with self.assertRaises(APIError):other.filmmaking.world(self.pid)
            finally:other.productions.sql.close()

    def test_both_subscription_workers_use_existing_transports_with_no_fallback(self):
        example=self.plan()['result'];self.app.mock=False
        context={'questionnaire':self.f.world(self.pid)['answers']}
        with self.p.sql:j=self.p.new('world-job',production_id=self.pid,provider='codex',mock=False,status='pending',context=context,result=None)
        with patch('filmmaking_studio.writing_reply',return_value=example) as writer:
            self.f.worker(j);writer.assert_called_once();self.assertEqual(self.p.get(j['id'],'world-job')['status'],'done')
        from types import SimpleNamespace
        response=SimpleNamespace(status_code=200,json=lambda:{'choices':[{'message':{'content':__import__('json').dumps(example)}}]})
        with self.p.sql:g=self.p.new('world-job',production_id=self.pid,provider='grok',mock=False,status='pending',context=context,result=None)
        with patch('studio_server.oauth_headers',return_value={'Authorization':'Bearer fixture-only'}),patch('httpx.Client') as client,patch('filmmaking_studio.writing_reply') as fallback:
            client.return_value.__enter__.return_value.post.return_value=response;self.f.worker(g);post=client.return_value.__enter__.return_value.post;post.assert_called_once();self.assertEqual(post.call_args.args[0],'https://api.x.ai/v1/chat/completions');fallback.assert_not_called();self.assertEqual(self.p.get(g['id'],'world-job')['status'],'done')
    def test_adoption_rolls_back_reference_and_drafts_when_linking_fails(self):
        j=self.apply();r=self.p.get(j['asset_ids'][0],'world-asset');a,_=self.image(r,True);references=copy.deepcopy(self.app.references);images=copy.deepcopy(self.app.images.db)
        with patch.object(self.app.images,'edit',side_effect=ValueError('fixture failure')):
            with self.assertRaises(ValueError):self.f.adopt(r['id'],dict(expected_revision=1,asset_id=a['id']))
        self.assertEqual(self.app.references,references);self.assertEqual(self.app.images.db,images);self.assertIsNone(self.p.get(r['id'],'world-asset')['reference_id']);self.assertEqual(self.p.all('asset'),[])
    def test_quick_flow_routes_and_invalid_png_leave_media_untouched(self):
        quick=self.p.dispatch('POST',[],dict(kind='quick',title='Short'))[1];pid=quick['production']['id'];self.f.save_world(pid,dict(expected_revision=0,answers=dict(idea='A sunrise over the city')))
        with patch.object(self.app,'spawn',lambda fn,j:fn(j)):
            _,j=self.app.agent.dispatch('POST','/agent/v1/filmmaking/worlds/'+pid+'/plan',dict(expected_revision=1,approved=True,provider='grok'),'quick-world-key')
        j=self.p.get(j['id'],'world-job');_,j=self.app.agent.dispatch('POST','/agent/v1/filmmaking/jobs/'+j['id']+'/apply',dict(expected_revision=j['revision']),None)
        self.assertIsNone(j['episode_id']);self.assertEqual(len(self.p.outline(pid)['shots']),3)
        sid=j['shot_ids'][0];s=self.p.get(sid,'shot');d=self.f.save_direction(sid,dict(expected_revision=0,staging=self.staging()));image=copy.deepcopy(self.app.images.draft(s['image_id']));assets=copy.deepcopy(self.app.assets)
        with self.assertRaises(APIError):self.f.compose(sid,dict(expected_revision=d['revision'],expected_image_revision=image['revision'],prompt='Composition',data_url='data:image/png;base64,bm90LWEtaW1hZ2U='))
        self.assertEqual(self.app.images.draft(image['id']),image);self.assertEqual(self.app.assets,assets)
        schema=self.app.agent.dispatch('GET','/agent/v1/filmmaking/schema',{},None)[1];self.assertEqual(schema['providers'],['codex','grok'])
        from agent_openapi import specification
        self.assertIn('/filmmaking/shots/{id}/compose',specification()['paths'])

    def test_existing_identity_conditions_planned_views_and_adoption_extends_it(self):
        a=self.app.upload(dict(name='Hero reference',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        ref=self.app.save_reference(dict(title='Story hero',handle='SampleHero',category='Character',description='A silver robot.',images=[{'asset_id':a['id']}]))
        j=self.apply();view=self.p.get(j['asset_ids'][0],'world-asset');draft=self.app.images.draft(view['draft_id']);self.assertEqual(draft['settings']['bindings'][0]['snapshot']['id'],ref['id'])
        self.assertEqual(view['existing_reference_id'],ref['id']);candidate,_=self.image(view,True);adopted=self.f.adopt(view['id'],dict(expected_revision=1,asset_id=candidate['id']))
        self.assertEqual(adopted['reference_id'],ref['id']);self.assertEqual(len(self.app.named_library()),1);self.assertEqual(len(self.app.asset_studio.get(ref['id'])['images']),2)
