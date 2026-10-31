"""Regression coverage for the nine end-to-end Agent API issues."""
import base64
import copy
import unittest
from unittest.mock import patch
import test_workshop_fixes as fixtures
from agent_api import APIError
from image_studio import mock_png


class DawnWorkflowTests(unittest.TestCase):
    setUp=fixtures.WorkshopFixTests.setUp
    tearDown=fixtures.WorkshopFixTests.tearDown
    route=fixtures.WorkshopFixTests.route
    payload=fixtures.WorkshopFixTests.payload
    candidate=fixtures.WorkshopFixTests.candidate
    def upload(self):return self.app.upload(dict(name='Local.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))['id']
    def add_places(self,ratio='9:16'):
        bible=self.s.bible(self.pid);guide=copy.deepcopy(bible['guide'])
        guide.update(places=[dict(id='room',name='Room',description='Stone hall.',lighting='Soft light.',time='Morning.')],props=[dict(id='key',name='Key',description='Silver key.',purpose='Opens the gate.')])
        bible=self.s.save_bible(self.pid,dict(expected_revision=bible['revision'],guide=guide,answers={**bible['answers'],'style':'Ink illustration. Vertical 9:16.','aspect_ratio':ratio}))
        return self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
    def episode(self):return self.p.outline(self.pid)['episodes'][0]['id']
    def link(self):
        eid=self.episode();return eid,self.s.save_book(eid,dict(expected_revision=0,selected_asset_ids=[self.e['id']]))
    def test_unique_place_and_prop_lines_and_trimmed_style(self):
        snapshot=self.add_places()
        for view in snapshot['views']:
            if view['category']=='Character':continue
            lines=view['draft']['settings']['prompt'].splitlines()
            self.assertEqual(len(lines),len(set(lines)))
            for label in ('Description','Lighting','Time','Purpose'):
                self.assertLessEqual(sum(line.startswith(label+':') for line in lines),1)
            self.assertNotIn('..',next(line for line in lines if line.startswith('Look:')))
    def test_aspect_default_override_preview_and_submission_match(self):
        snapshot=self.add_places();view=next(v for v in snapshot['views'] if v['kind']=='location')
        self.assertEqual(view['draft']['settings']['ratio'],'9:16');self.assertIn('Aspect ratio: 9:16',view['draft']['settings']['prompt'])
        snapshot=self.route('assets/'+view['id'],dict(expected_revision=view['revision'],ratio='16:9'),method='PUT')
        view=next(v for v in snapshot['views'] if v['id']==view['id']);self.assertIn('Aspect ratio: 16:9',view['draft']['settings']['prompt']);self.assertNotIn('9:16',view['draft']['settings']['prompt'])
        payload=dict(job_id=self.job['id'],model='grok-imagine-image-2.0',requests=[dict(view_id=view['id'],expected_revision=view['revision'])])
        preview=self.route('series/'+self.pid+'/generation-preview',payload)
        self.assertEqual(preview['requests'][0]['request']['aspect_ratio'],'16:9')
        with patch.object(self.app,'spawn'):
            batch=self.route('series/'+self.pid+'/generate',{**payload,'approved':True},'matching-place-aspect')
        d=self.app.images.draft(batch['requests'][0]['draft_id']);self.assertEqual(self.app.images.compile(d)[1],preview['requests'][0]['request'])
    def test_style_only_vertical_default_for_existing_series(self):
        snapshot=self.add_places(ratio='')
        self.assertTrue(all(v['draft']['settings']['ratio']=='9:16' for v in snapshot['views'] if v['category']!='Character'))
    def test_links_stay_frozen_until_explicit_refresh_and_scripts_stay_fixed(self):
        eid,book=self.link();self.assertFalse(book['linked_entities'][0]['source_changed']);frozen=copy.deepcopy(book['inheritance'])
        v,image=self.candidate();self.route('assets/'+v['id']+'/confirm',dict(expected_revision=v['revision'],asset_id=image['id'],approved=True))
        bible=self.s.bible(self.pid);guide=copy.deepcopy(bible['guide']);guide['cast'][0]['hair']='Red'
        self.s.save_bible(self.pid,dict(expected_revision=bible['revision'],guide=guide))
        stale=self.s.book(eid);self.assertEqual(stale['inheritance'],frozen);self.assertTrue(stale['linked_entities'][0]['source_changed'])
        before=copy.deepcopy(self.app.stories.db)
        refreshed=self.route('episodes/'+eid+'/storybook/refresh-links',dict(expected_revision=stale['revision']))
        source=refreshed['inheritance']['assets'][0];self.assertEqual(source['identity_asset_id'],image['id']);self.assertEqual(source['profile']['hair'],'Red')
        self.assertFalse(refreshed['linked_entities'][0]['source_changed']);self.assertEqual(self.app.stories.db,before)
        self.assertEqual(refreshed['guide']['script'],book['guide']['script'])
        with self.assertRaises(APIError):self.route('episodes/'+eid+'/storybook/refresh-links',dict(expected_revision=stale['revision']))
    def test_readiness_exposes_missing_and_confirmed_main_images_without_mutating(self):
        eid,book=self.link();before=copy.deepcopy(book)
        initial=self.route('episodes/'+eid+'/storybook/readiness',method='GET');self.assertEqual(initial['needs_images'],1);self.assertIsNone(initial['entities'][0]['confirmed_main_image'])
        self.assertEqual(self.s.book(eid),before)
        v,image=self.candidate();self.route('assets/'+v['id']+'/confirm',dict(expected_revision=v['revision'],asset_id=image['id'],approved=True))
        stale=self.route('episodes/'+eid+'/storybook/readiness',method='GET');self.assertTrue(stale['entities'][0]['source_changed']);self.assertEqual(stale['needs_images'],1)
        self.route('episodes/'+eid+'/storybook/refresh-links',dict(expected_revision=book['revision']))
        ready=self.route('episodes/'+eid+'/storybook/readiness',method='GET');self.assertTrue(ready['ready']);self.assertEqual(ready['entities'][0]['confirmed_main_image']['asset_id'],image['id'])
    def test_generation_layout_names_candidate_and_rename_repairs_legacy_name(self):
        data=self.payload();data['requests'][0]['character_sheet']=True
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            self.route('series/'+self.pid+'/generate',data,'layout-sheet-name')
        view=self.w.snapshot(self.pid,self.job['id'])['views'][0];image=view['outputs'][0]
        self.assertIn('Character sheet',image['name']);self.assertEqual(image['image_layout'],'character_sheet')
        renamed=self.route('assets/'+view['id']+'/rename-candidate',dict(expected_revision=view['revision'],expected_review_revision=image['review_revision'],asset_id=image['id'],title='SampleHero · Front view'))
        candidate=renamed['views'][0]['outputs'][0];self.assertEqual(candidate['name'],'SampleHero · Front view.png');self.assertFalse(candidate['approved'])
        self.assertEqual(self.app.images.db['jobs'][0]['outputs'][0]['name'],candidate['name'])
        self.assertEqual(self.app.images.db['jobs'][0]['draft']['title'],'Annie · Character sheet')
        with self.assertRaises(APIError):self.route('assets/'+view['id']+'/rename-candidate',dict(expected_revision=view['revision'],expected_review_revision=image['review_revision'],asset_id=image['id'],title='Stale'))
    def test_generate_accepts_series_id_on_world_route_and_identifies_view_revision(self):
        data=self.payload();d=self.app.images.draft(self.v['draft_id']);self.app.images.edit(d['id'],dict(expected_revision=d['revision'],title='New draft title'))
        wrong=copy.deepcopy(data);wrong['requests'][0]['expected_revision']=d['revision']
        with self.assertRaises(APIError) as error:self.route('worlds/'+self.production['series_id']+'/generate',wrong,'wrong-view-revision')
        self.assertIn('VIEW revision',str(error.exception));self.assertIn('current is 1',str(error.exception))
        with patch.object(self.app,'spawn'):
            result=self.route('worlds/'+self.production['series_id']+'/generate',data,'series-id-world-route')
        self.assertEqual(result['production_id'],self.pid)
    def test_entity_save_does_not_touch_unselected_drafts_or_reviewed_prompts(self):
        d=self.app.images.draft(self.v['draft_id']);d=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings={**d['settings'],'prompt':'Reviewed exact front view'}))
        self.app.images.dispatch('POST',['drafts',d['id'],'review-prompt'],dict(expected_revision=d['revision'],reviewed=True,authored_by='agent'),None)
        before=copy.deepcopy(self.app.images.draft(d['id']))
        entity=self.w.edit(self.e['id'],dict(expected_revision=self.e['revision'],profile={**self.e['profile'],'hair':'Red'},refresh_view_ids=[self.v['id']]))
        self.assertEqual(self.app.images.draft(d['id']),before)
        bible=self.s.bible(self.pid);self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        self.assertEqual(self.app.images.draft(d['id']),before)
        self.assertFalse(self.app.images.manual_review_current(self.app.images.draft(d['id'])),'Saved review remains recorded but changed creative inputs require review again')
    def test_unreviewed_prompt_refresh_is_only_explicit_and_targeted(self):
        before=copy.deepcopy(self.app.images.draft(self.v['draft_id']))
        entity=self.w.edit(self.e['id'],dict(expected_revision=self.e['revision'],profile={**self.e['profile'],'hair':'Red'}))
        self.assertEqual(self.app.images.draft(before['id']),before)
        self.w.edit(entity['id'],dict(expected_revision=entity['revision'],refresh_view_ids=[self.v['id']]))
        self.assertIn('Hair: Red',self.app.images.draft(before['id'])['settings']['prompt'])
    def test_bible_reference_patch_preview_confirm_and_validation(self):
        v,image=self.candidate()
        payload=dict(expected_revision=v['revision'],expected_entity_revision=self.e['revision'],asset_id=image['id'],changes=dict(reference_ids=[image['id']]))
        proposal=self.route('assets/'+v['id']+'/bible-change-preview',payload)
        self.assertEqual(self.s.bible(self.pid)['guide']['cast'][0]['reference_ids'],[])
        self.assertEqual(proposal['diff'][0]['after'],[image['id']])
        self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id'],approved=True))
        self.assertEqual(self.s.bible(self.pid)['guide']['cast'][0]['reference_ids'],[image['id']])
        latest=self.w.snapshot(self.pid,self.job['id'])['views'][0];entity=self.w.entity(self.e['id'])
        for bad in ('not-a-list',['missing-asset'],[image['id']]*6):
            with self.assertRaises((APIError,ValueError)):self.route('assets/'+v['id']+'/bible-change-preview',dict(expected_revision=latest['revision'],expected_entity_revision=entity['revision'],asset_id=image['id'],changes=dict(reference_ids=bad)))
    def test_guide_card_links_capture_once_and_refresh_without_touching_local_cards(self):
        eid=self.episode();book=self.s.save_book(eid,dict(expected_revision=0,guide=dict(cast=[dict(id='linked',name='Annie',hair='Brown',series_asset_id=self.e['id']),dict(id='local',name='Local person',hair='Black')])))
        self.assertEqual(book['inheritance']['assets'][0]['id'],self.e['id'])
        entity=self.w.edit(self.e['id'],dict(expected_revision=self.e['revision'],profile={**self.e['profile'],'hair':'Red'}))
        saved=self.s.save_book(eid,dict(expected_revision=book['revision'],answers={**book['answers'],'idea':'A changed premise'}))
        self.assertEqual(saved['inheritance']['assets'][0]['profile']['hair'],'Brown')
        refreshed=self.route('episodes/'+eid+'/storybook/refresh-links',dict(expected_revision=saved['revision']))
        self.assertEqual(refreshed['guide']['cast'][0]['hair'],'Red');self.assertEqual(refreshed['guide']['cast'][0]['id'],'linked')
        self.assertEqual(refreshed['guide']['cast'][1],book['guide']['cast'][1])
    def test_paid_preview_shows_returned_rate_limit_separately_from_unknown_balance(self):
        from provider_usage import observe
        self.app.mock=False;job=self.p.get(self.job['id'],'world-job');job['mock']=False;self.p.put('world-job',job)
        observe(self.app,type('Response',(),{'headers':{'x-ratelimit-remaining-requests':'12'}})(),'grok_image')
        with patch.object(self.app,'spawn') as submit:
            preview=self.route('series/'+self.pid+'/generation-preview',self.payload());submit.assert_not_called()
        quota=preview['usage']['providers']['grok_image'];self.assertFalse(quota['balance_available']);self.assertEqual(quota['remaining'],'unknown')
        self.assertEqual(quota['rate_limit_observation']['rate_limits']['x-ratelimit-remaining-requests'],'12')
    def test_aspect_normalization_preserves_clock_times(self):
        self.assertEqual(self.w.aspect_text('Night at 12:30. Vertical 9:16.','16:9'),'Night at 12:30. 16:9.')
    def test_paid_previews_show_allowance_status_without_approval_or_submission(self):
        before=copy.deepcopy(self.app.images.db);payload=self.payload();payload.pop('approved')
        with patch.object(self.app,'spawn') as submit:
            preview=self.route('series/'+self.production['series_id']+'/generation-preview',payload)
            submit.assert_not_called()
        self.assertEqual(self.app.images.db,before);self.assertTrue(preview['approval_required'])
        quota=preview['usage']['providers']['grok_image'];self.assertEqual(quota['remaining'],'unknown');self.assertFalse(quota['balance_available']);self.assertIn('cannot be read',quota['reason'])
        validation=self.app.images.validate(self.app.images.draft(self.v['draft_id']));self.assertEqual(validation['usage'],preview['usage'])
        scene=self.app.agent.create(dict(title='Video preview'));self.assertIn('usage',self.app.agent.validation(scene))
