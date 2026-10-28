import base64
import copy
import tempfile
import time
import unittest
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError
from image_studio import mock_png

class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name);self.f=self.app.filmmaking;self.w=self.f.workshop;self.p=self.app.productions
        self.pid=self.p.dispatch('POST',[],dict(kind='story',title='Signal'))[1]['production']['id']
        self.guide=dict(cast=[dict(id='hero',name='SampleHero',role='Hero',clothing='Silver shell')],places=[dict(id='place',name='Workshop',description='A warm workshop',time='Night')],acts=[dict(id='act',title='Discovery',text='SampleHero finds a signal.')],script='')
        world=self.f.save_world(self.pid,dict(expected_revision=0,answers=dict(idea='SampleHero finds a signal.'),guide=self.guide))
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            self.j=self.f.plan(self.pid,dict(expected_revision=world['revision'],approved=True),'workshop-story-once')
        self.j=self.p.get(self.j['id'],'world-job')
    def tearDown(self):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with self.app.agent.lock:pending=any(b['status']=='pending' for b in self.p.all('world-render'))
            if not pending:break
            time.sleep(.05)
        self.p.sql.close();self.tmp.cleanup()
    def start(self):return self.w.start(self.pid,dict(job_id=self.j['id'],expected_revision=self.j['revision']))
    def request(self,v,n=1,key='workshop-render-once'):
        return self.app.agent.dispatch('POST','/agent/v1/filmmaking/worlds/'+self.pid+'/generate',dict(job_id=self.j['id'],approved=True,model='gpt-image-2',requests=[dict(view_id=v['id'],expected_revision=v['revision'])]*n),key)[1]
    def wait(self,b):
        for _ in range(100):
            with self.app.agent.lock:batch=self.p.get(b['id'],'world-render')
            if batch['status']!='pending':return batch
            time.sleep(.05)
        self.fail('Batch did not finish')
    def confirm_main(self,s,category='Character',key='main-render-once'):
        e=next(e for e in s['entities'] if e['category']==category);v=next(v for v in s['views'] if v['entity_id']==e['id'])
        b=self.wait(self.request(v,key=key));self.assertEqual(b['status'],'done',b.get('error'));fresh=self.w.snapshot(self.pid);view=next(r for r in fresh['views'] if r['id']==v['id']);o=view['outputs'][0]
        return self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=o['id'],approved=True))
    def test_model_switch_preserves_reviewed_prompt_through_preflight_and_render(self):
        snapshot=self.start();self.app.spawn=lambda *args:None
        for view in snapshot['views']:
            draft=self.app.images.draft(view['draft_id'])
            reviewed='Exact reviewed prompt for '+view['kind']+'.'
            draft=self.app.images.edit(draft['id'],dict(expected_revision=draft['revision'],settings={**draft['settings'],'prompt':reviewed}))
            context=self.app.prompting.context('image',draft,{})
            self.app.prompting.mark('image',self.app.images.draft(draft['id']),context,'saved-review','codex',brief='Original brief')
            for number,model in enumerate(('grok-imagine-image-2.0','gpt-image-2')):
                prepared=self.w.prompt_draft(view['id'],dict(expected_revision=view['revision'],model=model))
                self.assertTrue(prepared['current'])
                self.assertEqual(prepared['draft']['settings']['prompt'],reviewed)
                self.assertEqual(prepared['draft']['settings']['model'],model)
                batch=self.w.generate(self.pid,dict(job_id=self.j['id'],approved=True,model=model,requests=[dict(view_id=view['id'],expected_revision=view['revision'])]),'preserve-'+view['id']+'-'+str(number))
                rendered=self.app.images.draft(batch['requests'][0]['draft_id'])
                self.assertEqual(rendered['settings']['prompt'],reviewed)
                self.assertEqual(rendered['settings']['model'],model)
                self.assertTrue(self.app.prompting.current('image',rendered))
                batch['status']='cancelled';self.p.put('world-render',batch)
            self.assertEqual(self.p.all('media-prompt-job'),[],'Switching models never requests AI writing')

    def test_guided_story_and_workshop_are_additive_and_restart_safe(self):
        before=copy.deepcopy(self.p.outline(self.pid));s=self.start();self.assertEqual([e['name'] for e in s['entities']],['SampleHero','Workshop'])
        self.assertEqual(self.p.outline(self.pid),before);self.assertEqual(self.app.images.db['jobs'],[])
        again=self.w.start(self.pid,dict(job_id=s['job']['id'],expected_revision=s['job']['revision']));self.assertEqual(len(again['views']),2)
        self.p.sql.close();self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.w=self.app.filmmaking.workshop
        self.assertEqual(self.w.snapshot(self.pid)['entities'],s['entities'])
    def test_scout_batch_reuses_one_view_and_never_replays(self):
        s=self.start();v=s['views'][1];b=self.request(v,3);done=self.wait(b);self.assertEqual(done['status'],'done',done.get('error'));self.assertEqual(done['completed'],3)
        self.assertEqual(len(self.w.snapshot(self.pid)['views'][1]['outputs']),3)
        same=self.request(v,3);self.assertEqual(same['id'],b['id']);self.assertEqual(len(self.app.images.db['jobs']),3)
    def test_confirmed_identity_conditions_sheets_and_connects_storyboard(self):
        s=self.confirm_main(self.start());hero=s['entities'][0];v=self.w.add_views(hero['id'],dict(expected_revision=hero['revision'],views=[dict(label='Dress uniform',details='A dark coat')]))[0]
        d=self.app.images.draft(v['draft_id']);self.assertEqual(d['settings']['extras'],[{'asset_id':hero['identity_asset_id']}]);self.assertIn('full body rear',d['settings']['prompt'])
        s=self.confirm_main(s,'Location','location-render-once');j=self.p.get(self.j['id'],'world-job');applied=self.f.apply(j,dict(expected_revision=j['revision']));self.assertEqual(len(applied['asset_ids']),3)
        for sid in applied['shot_ids']:
            shot=self.p.get(sid,'shot');self.assertEqual(len(self.app.images.draft(shot['image_id'])['settings']['bindings']),2);self.assertEqual(len(self.app.agent.record(shot['video_id'])['scene']['named']),2)
        self.assertEqual(len(self.p.all('production')),1)

    def test_outfit_prompt_retains_complete_direction_and_approved_identity(self):
        s=self.confirm_main(self.start());hero=s['entities'][0]
        profile={**hero['profile'], 'personality':'BIOGRAPHY '*1000,
                 'motivation':'MOTIVATION '*800,'clothing':'ORIGINAL OUTFIT '*600,
                 'age':'Middle-aged','hair':'Short brown hair','build':'Average build',
                 'description':'Distinctive cheek scar and a narrow silver eyebrow.'}
        hero=self.w.edit(hero['id'],dict(expected_revision=hero['revision'],profile=profile))
        details='Dark jeans and a blue jacket. '+('outfit detail '*50)+' Red sneakers.'
        view=self.w.add_views(hero['id'],dict(expected_revision=hero['revision'],views=[dict(label='Weekend',details=details)]))[0]
        draft=self.app.images.draft(view['draft_id']);prompt=draft['settings']['prompt']
        self.assertLess(len(prompt),2700)
        for text in ('full body front','full body rear','full body side','three-quarter','head close-up',details,'No captions','Short brown hair','Change only clothing',profile['description']):
            self.assertIn(text,prompt)
        self.assertNotIn('BIOGRAPHY',prompt);self.assertNotIn('MOTIVATION',prompt);self.assertNotIn('ORIGINAL OUTFIT',prompt)
        self.assertEqual(draft['settings']['extras'],[{'asset_id':hero['identity_asset_id']}])
        for model in ('gpt-image-2','grok-imagine-image-2.0'):
            request=copy.deepcopy(draft);request['settings']['model']=model
            request['settings'].update(quality='auto' if model=='gpt-image-2' else 'low',resolution='auto' if model=='gpt-image-2' else '1k')
            endpoint,body,count=self.app.images.compile(request)
            self.assertEqual(count,1)
            ref=(body.get('images') or [body.get('image')])[0]
            asset,path=self.app.asset(hero['identity_asset_id'])
            self.assertEqual(base64.b64decode(ref['url'].split(',')[1]),path.read_bytes())
            self.assertIn('3:2',body['prompt'] if model=='gpt-image-2' else body['aspect_ratio'])
        # Updating the displayed recommendation does not rewrite saved history.
        self.assertEqual(self.w.view(view)['recommended_prompt'],prompt)
        self.assertEqual(self.app.images.draft(view['draft_id']),draft)
    def test_coverage_requires_confirmed_reference_and_supports_eight_views(self):
        s=self.start();location=s['entities'][1]
        with self.assertRaises(APIError):self.w.add_views(location['id'],dict(expected_revision=location['revision'],views=[dict(label='Wide')]))
        s=self.confirm_main(s,'Location');e=s['entities'][1]
        views=self.w.add_views(e['id'],dict(expected_revision=e['revision'],views=[dict(label=l) for l in ('Wide','Medium','Close-up','Aerial','Low angle','Reverse','Interior','Detail')]))
        for v in views:self.assertEqual(self.app.images.draft(v['draft_id'])['settings']['extras'][0]['asset_id'],e['identity_asset_id'])
    def test_location_multiple_inputs_keep_identity_and_reach_both_models(self):
        snapshot=self.start();e=next(e for e in snapshot['entities'] if e['category']=='Location')
        ids=[self.w.reference(self.pid,dict(name='Input.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))['asset']['id'] for _ in range(5)]
        self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=ids[0]))
        e=self.w.entity(e['id']);original=e['identity_asset_id']
        e=self.w.edit(e['id'],dict(expected_revision=e['revision'],profile={**e['profile'],'reference_ids':ids}))
        self.assertEqual(e['identity_asset_id'],original)
        self.assertEqual(self.f.series.guide(dict(places=[dict(id='room',name='Room',reference_ids=ids)]))['places'][0]['reference_ids'],ids)
        with self.assertRaises(APIError):self.w.edit(e['id'],dict(expected_revision=e['revision'],profile={**e['profile'],'reference_ids':ids+[ids[0]]}))
        v=next(v for v in self.w.snapshot(self.pid)['views'] if v['entity_id']==e['id'])
        for model in ('gpt-image-2','grok-imagine-image-2.0'):
            with patch.object(self.app,'spawn') as spawn:
                batch=self.w.generate(self.pid,dict(job_id=self.j['id'],approved=True,model=model,requests=[dict(view_id=v['id'],expected_revision=v['revision'])]),'location-multi-'+model.replace('.','-'))
            d=self.app.images.draft(v['draft_id']);compiled=self.app.images.compile(d)
            self.assertEqual([x['asset_id'] for x in d['settings']['extras']],ids)
            self.assertEqual(len(compiled[1]['images']),5)
            self.assertEqual(self.w.entity(e['id'])['identity_asset_id'],original)
            batch.update(status='done');self.p.put('world-render',batch)
        e=self.w.entity(e['id']);self.w.edit(e['id'],dict(expected_revision=e['revision'],profile={**e['profile'],'reference_ids':ids[:2]}))
        with patch.object(self.app,'spawn'):
            self.w.generate(self.pid,dict(job_id=self.j['id'],approved=True,model='gpt-image-2',requests=[dict(view_id=v['id'],expected_revision=v['revision'])]),'location-removed-input')
        self.assertEqual(len(self.app.images.draft(v['draft_id'])['settings']['extras']),2)
        for b in self.p.all('world-render'):b.update(status='done');self.p.put('world-render',b)

    def test_reference_upload_palette_and_identity_adoption(self):
        s=self.start();r=self.w.reference(self.pid,dict(name='Reference.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()));self.assertEqual(len(r['palette']),5)
        e=s['entities'][0];s=self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=r['asset']['id']));self.assertEqual(s['entities'][0]['identity_asset_id'],r['asset']['id']);self.assertEqual(len(self.app.named_library()),1)
    def test_foreign_candidates_stale_profiles_and_api_models_rejected(self):
        s=self.start();e=s['entities'][0]
        with self.assertRaises(APIError):self.w.edit(e['id'],dict(expected_revision=0,description='Stale'))
        with self.assertRaises(APIError):self.w.confirm(s['views'][0]['id'],dict(expected_revision=1,approved=True,asset_id='foreign'))
        with self.assertRaises(APIError):self.w.generate(self.pid,dict(job_id=self.j['id'],approved=True,model='gpt-image-2.5-flare',requests=[dict(view_id=s['views'][0]['id'],expected_revision=1)]),'invalid-api-model')
        self.assertEqual(self.app.images.db['jobs'],[])
    def test_cancellation_preserves_finished_image_and_stops_remaining(self):
        s=self.start();b=self.request(s['views'][1],6)
        self.app.agent.dispatch('POST','/agent/v1/filmmaking/renders/'+b['id']+'/cancel',{},None)
        done=self.wait(b);self.assertEqual(done['status'],'cancelled');self.assertLess(done['completed'],6);self.assertLessEqual(len(self.app.images.db['jobs']),1)
    def test_pdf_includes_story_and_confirmed_local_images(self):
        s=self.confirm_main(self.start());raw,mime=self.w.bible(self.pid);self.assertEqual(mime,'application/pdf');self.assertTrue(raw.startswith(b'%PDF'));self.assertIn(b'/Subtype /Image',raw)
    def test_routes_and_imported_script_context(self):
        response=self.app.agent.dispatch('GET','/agent/v1/filmmaking/worlds/'+self.pid+'/workshop',{},None)[1];self.assertEqual(response['job']['id'],self.j['id'])
        w=self.f.world(self.pid);g=copy.deepcopy(w['guide']);g['script']='INT. WORKSHOP - NIGHT\nSampleHero discovers the signal.'
        w=self.f.save_world(self.pid,dict(expected_revision=w['revision'],answers=w['answers'],guide=g))
        with patch.object(self.app,'spawn',lambda fn,*args:None):j=self.f.plan(self.pid,dict(expected_revision=w['revision'],approved=True),'imported-script-plan')
        self.assertIn('INT. WORKSHOP',j['context']['guide']['script'])
    def test_live_gate_fails_before_any_render_submission(self):
        s=self.start();self.app.mock=False
        j=self.p.get(self.j['id'],'world-job');j['mock']=False
        with self.p.sql:self.p.put('world-job',j)
        with patch.object(self.app.images,'account_status',return_value={'subscription':{'signed_in':False}}),patch.object(self.app.images,'generate') as generate:
            with self.assertRaises(APIError):self.request(s['views'][0])
            generate.assert_not_called()
    def test_changing_identity_keeps_candidates_but_requires_new_sheets(self):
        s=self.confirm_main(self.start());hero=s['entities'][0]
        sheet=self.w.add_views(hero['id'],dict(expected_revision=hero['revision'],views=[dict(label='Main outfit')]))[0]
        self.wait(self.request(sheet,key='first-sheet-render'))
        v=next(v for v in self.w.snapshot(self.pid)['views'] if v['id']==sheet['id']);out=v['outputs'][0]
        s=self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=out['id'],approved=True))
        main=next(v for v in s['views'] if v['kind']=='portrait');self.wait(self.request(main,key='new-identity-render'))
        main=next(v for v in self.w.snapshot(self.pid)['views'] if v['kind']=='portrait')
        s=self.w.confirm(main['id'],dict(expected_revision=main['revision'],asset_id=main['outputs'][-1]['id'],approved=True))
        previous=next(v for v in s['views'] if v['id']==sheet['id']);self.assertIsNone(previous['selected']);self.assertFalse(previous['outputs'][0]['compatible']);self.assertEqual(len(previous['outputs']),1)
        with self.assertRaises(APIError):self.w.confirm(previous['id'],dict(expected_revision=previous['revision'],asset_id=out['id'],approved=True))
    def test_interrupted_batch_is_not_resubmitted_after_restart(self):
        s=self.start()
        with patch.object(self.app,'spawn') as spawn:b=self.request(s['views'][0]);spawn.assert_called_once()
        self.p.sql.close();self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.w=self.app.filmmaking.workshop
        self.assertEqual(self.p.get(b['id'],'world-render')['status'],'error');self.assertEqual(self.app.images.db['jobs'],[])
    def test_profile_edit_updates_matching_description_fields(self):
        hero=self.start()['entities'][0]
        profile=copy.deepcopy(hero['profile']);profile['clothing']='Dark green utility vest'
        updated=self.w.edit(hero['id'],dict(expected_revision=hero['revision'],profile=profile,description=hero['description']))
        self.assertIn('Clothing: Dark green utility vest',updated['description'])
        self.assertNotIn('Clothing: Silver shell',updated['description'])
