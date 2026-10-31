"""Review selection is reversible; saved production snapshots remain immutable."""
import base64
import copy
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_api import APIError
from image_studio import mock_png
from studio_server import Studio


class WorkshopControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.p=self.app.productions;self.f=self.app.filmmaking;self.s=self.f.series;self.w=self.f.workshop
        outline=self.p.dispatch('POST',[],dict(kind='story',title='Control series'))[1]
        self.pid=outline['production']['id'];self.eid=outline['episodes'][0]['id']
        self.bible=self.s.save_bible(self.pid,dict(expected_revision=0,answers=dict(style='Cinematic stylized 3D animation'),guide=dict(
            cast=[dict(id='hero',name='Hero',description='A gold robot.',clothing='Blue jacket')],
            places=[dict(id='lab',name='Lab',description='A green workshop.')],
            props=[dict(id='tool',name='Tool',description='A bronze wrench.')])) )
        self.snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=self.bible['revision']))
        self.raw=mock_png()

    def refine_candidate(self,image,key):
        job=next(j for j in self.app.images.db['jobs'] if any(o['id']==image['id'] for o in j['outputs']))
        draft=self.app.images.dispatch('POST',['jobs',job['id'],'refine'],dict(asset_id=image['id'],prompt='Make the lighting warmer.'),None)[1]
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            edited=self.app.images.generate(draft['id'],dict(expected_revision=draft['revision'],approved=True),key)
        return edited,self.app.images.job(edited['id'])['outputs'][0]

    def test_develop_refine_return_reject_reopen_generate_bible_and_episode_all_categories(self):
        from candidate_review import review
        book=self.s.save_book(self.eid,dict(expected_revision=0,guide=copy.deepcopy(self.bible['guide'])))
        contexts=[('series-bible',self.pid,self.bible),('episode-book',self.eid,book)]
        for scope,identity,document in contexts:
            for category in ('Character','Location','Prop'):
                with self.subTest(scope=scope,category=category):
                    snapshot=self.s.workshop(scope,identity,dict(expected_revision=document['revision']))
                    entity=next(e for e in snapshot['entities'] if e['category']==category)
                    view=next(v for v in snapshot['views'] if v['entity_id']==entity['id'] and v['kind'] in ('portrait','location','prop'))
                    sources=[self.upload(category+' inspiration '+str(i)+'.png')['id'] for i in range(2)]
                    self.w.edit(entity['id'],dict(expected_revision=entity['revision'],profile={**entity['profile'],'reference_ids':sources}))
                    original=self.generate_candidate(view,'cycle-original-'+scope+'-'+category)
                    main=self.app.images.draft(view['draft_id'])
                    # Legacy drafts must be repaired as well as newly forked refinements.
                    self.app.images.edit(main['id'],dict(expected_revision=main['revision'],settings={**main['settings'],'base':{'asset_id':original['id']},'edit_region':dict(x=0,y=0,width=1,height=1)}))
                    source_before=copy.deepcopy(main)
                    refined=self.app.precision.dispatch('POST',['refine'],dict(asset_id=original['id'],draft_id=main['id'],expected_revision=main['revision'],region=dict(x=.1,y=.1,width=.3,height=.3),settings={**main['settings'],'prompt':'Refine this design.'}),None)[1]
                    self.assertNotEqual(refined['id'],main['id']);self.assertEqual(main,source_before)
                    edited=self.generate_candidate({'draft_id':refined['id']},'cycle-refined-'+scope+'-'+category)
                    job=next(j for j in self.app.images.db['jobs'] if any(o['id']==edited['id'] for o in j['outputs']))
                    self.app.images.dispatch('POST',['jobs',job['id'],'approve'],dict(asset_id=edited['id'],approved=True),None)
                    view=self.p.get(view['id'],'world-asset')
                    self.w.return_image(view['id'],dict(expected_revision=view['revision'],job_id=job['id'],asset_id=edited['id']))
                    entity=self.w.entity(entity['id']);self.w.clear_approval(entity['id'],dict(expected_revision=entity['revision']))
                    for image in (original,edited):
                        view=self.p.get(view['id'],'world-asset')
                        review(self.w,view['id'],dict(expected_revision=view['revision'],asset_id=image['id'],expected_review_revision=self.app.asset(image['id'])[0].get('review_revision',0),action='reject',reason='Unwanted design'))
                    history=copy.deepcopy(self.app.images.db['jobs']);assets=copy.deepcopy(self.app.assets)
                    versions=list(self.p.sql.execute('SELECT id,revision,body FROM versions ORDER BY id,revision'))
                    with patch.object(self.app,'spawn') as spawn:
                        reopened=self.s.workshop(scope,identity,dict(expected_revision=document['revision']));spawn.assert_not_called()
                    view=next(v for v in reopened['views'] if v['id']==view['id'])
                    self.assertEqual(view['draft']['settings']['base'],{'asset_id':original['id']},'Opening the workshop preserves unselected drafts')
                    prepared=self.w.prompt_draft(view['id'],dict(expected_revision=view['revision'],model='gpt-image-2'))
                    view=self.w.view(self.p.get(view['id'],'world-asset'))
                    self.assertIsNone(prepared['draft']['settings']['base']);self.assertIsNone(prepared['draft']['settings']['edit_region'])
                    self.assertEqual([x['asset_id'] for x in view['draft']['settings']['extras']],sources)
                    self.assertEqual(self.app.images.db['jobs'],history);self.assertEqual(self.app.assets,assets)
                    self.assertTrue(set(versions).issubset(set(self.p.sql.execute('SELECT id,revision,body FROM versions'))))
                    self.assertEqual(self.app.images.draft(refined['id'])['settings']['base'],{'asset_id':original['id']},'Historical refinement remains untouched')
                    direction='New '+category+' candidate in cinematic stylized 3D animation.'
                    with patch.object(self.app,'spawn'):
                        batch=self.w.generate(self.pid,dict(job_id=reopened['job']['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=view['id'],expected_revision=view['revision'],prompt=direction)]),'cycle-new-'+scope+'-'+category)
                    _,body,count=self.app.images.compile(self.app.images.draft(main['id']))
                    self.assertEqual(count,2);self.assertIn(direction,body['prompt'])
                    self.assertEqual(self.app.images.db['jobs'],history);self.assertEqual(self.app.assets,assets)
                    batch.update(status='done');self.p.put('world-render',batch)

    def test_preparation_drops_missing_base_preserves_valid_base_until_fresh_generation(self):
        entity,view=self.item('Prop');asset=self.upload('Valid base.png');draft=self.app.images.draft(view['draft_id'])
        region=dict(x=.1,y=.1,width=.3,height=.3)
        for missing in ('unknown-id',asset['id']):
            if missing==asset['id']:self.app.asset(asset['id'])[1].unlink()
            legacy=copy.deepcopy(draft);legacy['settings'].update(base={'asset_id':missing},edit_region=region)
            prepared=self.w.prepare_settings(entity,view,legacy)
            self.assertIsNone(prepared['base']);self.assertIsNone(prepared['edit_region'])
            self.assertIsNotNone(legacy['settings']['base'],'Preparation does not mutate its input')
        valid=self.upload('Second valid base.png');legacy=copy.deepcopy(draft);legacy['settings'].update(base={'asset_id':valid['id']},edit_region=region)
        prepared=self.w.prepare_settings(entity,view,legacy)
        self.assertEqual(prepared['base'],legacy['settings']['base']);self.assertEqual(prepared['edit_region'],region)
        fresh=self.w.prepare_settings(entity,view,legacy,fresh=True)
        self.assertIsNone(fresh['base']);self.assertIsNone(fresh['edit_region'])

    def test_rejected_refinement_cannot_block_fresh_generation_all_categories(self):
        region=dict(x=.1,y=.1,width=.3,height=.3)
        inspiration=[self.upload('Fresh source '+str(i)+'.png')['id'] for i in range(2)]
        for category in ('Character','Location','Prop'):
            e,v=self.item(category);original=self.generate_candidate(v,'fresh-reject-'+category)
            d=self.app.images.draft(v['draft_id'])
            # Reproduce legacy precision editing of the main workflow draft.
            d['settings'].update(base={'asset_id':original['id']},edit_region=region)
            asset=self.app.asset(original['id'])[0];asset.update(review_state='rejected',approved=False)
            history=copy.deepcopy(self.app.images.db['jobs'])
            self.w.edit(e['id'],dict(expected_revision=e['revision'],profile={**e['profile'],'reference_ids':inspiration}))
            self.assertEqual(d['settings']['base'],{'asset_id':original['id']},'An entity save never repairs an unrelated draft implicitly')
            self.assertEqual(d['settings']['edit_region'],region)
            # Generation must repair legacy settings even without editing details first.
            d['settings'].update(base={'asset_id':original['id']},edit_region=region)
            with patch.object(self.app,'spawn'):
                batch=self.w.generate(self.pid,dict(job_id=self.snapshot['job']['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=v['id'],expected_revision=v['revision'],prompt='A fresh candidate in cinematic stylized 3D animation.')]),'clean-rejected-'+category)
            self.assertIsNone(d['settings']['base']);self.assertIsNone(d['settings']['edit_region'])
            _,body,count=self.app.images.compile(d)
            self.assertEqual(count,2);self.assertEqual([x['asset_id'] for x in d['settings']['extras']],inspiration)
            self.assertIn('A fresh candidate',body['prompt'])
            self.assertEqual(self.app.images.db['jobs'],history)
            self.assertEqual(asset['review_state'],'rejected')
            batch.update(status='done');self.p.put('world-render',batch)

    def test_image_studio_roundtrip_preserves_original_and_adopts_approved_edits_all_categories(self):
        for category in ('Character','Location','Prop'):
            with self.subTest(category=category):
                entity,view=self.item(category);original=self.generate_candidate(view,'roundtrip-original-'+category)
                self.w.confirm(view['id'],dict(expected_revision=view['revision'],asset_id=original['id'],approved=True))
                entity,view=self.item(category)
                # Existing episode foundations remain pinned to the original.
                book=self.s.book(self.eid);book=self.s.save_book(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=book['episode']['revision'],answers=book['answers'],guide=book['guide'],selected_asset_ids=[entity['id']],refresh_inheritance=True))
                frozen=copy.deepcopy(book)
                job,edited=self.refine_candidate(original,'roundtrip-edit-'+category)
                self.assertEqual({o['id'] for o in self.w.view(view)['outputs']},{original['id'],edited['id']})
                body=dict(expected_revision=view['revision'],job_id=job['id'],asset_id=edited['id'])
                with patch.object(self.app,'spawn') as spawn:
                    result=self.w.return_image(view['id'],body);spawn.assert_not_called()
                self.assertEqual(next(v for v in result['views'] if v['id']==view['id'])['selected'],original['id'],'Unreviewed edits never replace selection')
                self.app.images.dispatch('POST',['jobs',job['id'],'approve'],dict(asset_id=edited['id'],approved=True),None)
                with patch.object(self.app,'spawn') as spawn:
                    result=self.app.agent.dispatch('POST','/agent/v1/filmmaking/assets/'+view['id']+'/return-image',body,None)[1];spawn.assert_not_called()
                current=next(e for e in result['entities'] if e['id']==entity['id'])
                self.assertEqual(current['identity_asset_id'],edited['id'])
                self.assertEqual({o['id'] for o in next(v for v in result['views'] if v['id']==view['id'])['outputs']},{original['id'],edited['id']})
                current_book=self.s.book(self.eid)
                self.assertEqual({k:v for k,v in current_book.items() if k!='linked_entities'},{k:v for k,v in frozen.items() if k!='linked_entities'})
                self.assertTrue(current_book['linked_entities'][0]['source_changed'])
                self.assertEqual(self.w.return_image(view['id'],body),result,'Retrying a return is idempotent')
                self.assertTrue(self.app.asset(original['id'])[1].exists())

    def test_image_studio_return_rejects_foreign_images_and_stale_selection(self):
        entity,view=self.item('Location');original=self.generate_candidate(view,'roundtrip-location')
        other,other_view=self.item('Prop');foreign=self.generate_candidate(other_view,'roundtrip-foreign')
        foreign_job=next(j for j in self.app.images.db['jobs'] if any(o['id']==foreign['id'] for o in j['outputs']))
        with self.assertRaises(APIError) as error:self.w.return_image(view['id'],dict(expected_revision=view['revision'],job_id=foreign_job['id'],asset_id=foreign['id']))
        self.assertEqual(error.exception.code,'invalid_candidate')
        job,edited=self.refine_candidate(original,'roundtrip-stale')
        self.app.images.dispatch('POST',['jobs',job['id'],'approve'],dict(asset_id=edited['id'],approved=True),None)
        with self.assertRaises(APIError) as error:self.w.return_image(view['id'],dict(expected_revision=999,job_id=job['id'],asset_id=edited['id']))
        self.assertEqual(error.exception.code,'revision_conflict');self.assertIsNone(self.w.entity(entity['id'])['identity_asset_id'])
        # A scene merely using the image as loose inspiration is unrelated.
        draft=self.app.images.create(dict(title='Unrelated',settings=dict(prompt='Different scene.',extras=[{'asset_id':original['id']}],model='gpt-image-2')))
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            unrelated=self.app.images.generate(draft['id'],dict(expected_revision=draft['revision'],approved=True),'roundtrip-unrelated')
        self.assertNotIn(unrelated['outputs'][0]['id'],{o['id'] for o in self.w.view(view)['outputs']})

    def test_refinement_chain_and_optional_angle_keep_their_original_view_and_identity_check(self):
        entity,main=self.item('Location');identity=self.upload('Approved place.png')
        self.w.upload_identity(entity['id'],dict(expected_revision=entity['revision'],asset_id=identity['id']))
        entity,main=self.item('Location');self.w.add_views(entity['id'],dict(expected_revision=entity['revision'],model='gpt-image-2',views=[dict(label='Reverse',details='Opposite side')]))
        view=next(v for v in self.p.all('world-asset') if v['entity_id']==entity['id'] and v['kind']=='coverage')
        original=self.generate_candidate(view,'roundtrip-angle');job,edit=self.refine_candidate(original,'roundtrip-angle-edit');next_job,next_edit=self.refine_candidate(edit,'roundtrip-angle-edit-again')
        self.assertTrue(all(o['compatible'] for o in self.w.view(view)['outputs']))
        self.assertNotIn(next_edit['id'],{o['id'] for o in self.w.view(main)['outputs']})
        self.app.images.dispatch('POST',['jobs',next_job['id'],'approve'],dict(asset_id=next_edit['id'],approved=True),None)
        result=self.w.return_image(view['id'],dict(expected_revision=view['revision'],job_id=next_job['id'],asset_id=next_edit['id']))
        self.assertEqual(next(e for e in result['entities'] if e['id']==entity['id'])['identity_asset_id'],identity['id'])
        # Changing the main identity invalidates descendants of the prior angle.
        child_job,child_edit=self.refine_candidate(next_edit,'roundtrip-angle-after-approval')
        changed=self.w.entity(entity['id']);changed['identity_asset_id']='new-identity';self.p.put('world-entity',changed)
        self.assertTrue(all(not o['compatible'] for o in self.w.view(view)['outputs']))

    def test_failed_attempt_dismissal_is_durable_scoped_and_never_retries(self):
        for category in ('Character','Location','Prop'):
            entity,main=self.item(category)
            identity=self.upload()
            self.w.upload_identity(entity['id'],dict(expected_revision=entity['revision'],asset_id=identity['id']))
            entity=self.w.entity(entity['id'])
            self.w.add_views(entity['id'],dict(expected_revision=entity['revision'],model='gpt-image-2',views=[dict(label='Reverse',details='Opposite side')]))
            view=next(v for v in self.p.all('world-asset') if v['entity_id']==entity['id'] and v['id']!=main['id'])
            image=self.generate_candidate(view,'history-'+category)
            job=next(j for j in self.app.images.db['jobs'] if any(o['id']==image['id'] for o in j['outputs']))
            job.update(status='error',message='Test provider failure');self.app.images.persist()
            original=copy.deepcopy(job);snapshot=self.w.view(view)
            self.assertEqual(snapshot['attempts'][0]['id'],job['id'])
            with patch.object(self.app.images,'generate',side_effect=AssertionError('No retry')):
                result=self.w.review_attempt(view['id'],dict(expected_revision=view['revision'],attempt_ids=[job['id']],action='dismiss'))
                self.assertTrue(result['attempts'][0]['dismissed'])
                self.assertEqual(result['outputs'][0]['id'],image['id'])
                reloaded=Studio(mock=True,storage=self.tmp.name)
                try:self.assertTrue(reloaded.filmmaking.workshop.view(reloaded.productions.get(view['id'],'world-asset'))['attempts'][0]['dismissed'])
                finally:reloaded.productions.sql.close()
                with self.assertRaises(APIError):self.w.review_attempt(view['id'],dict(expected_revision=result['revision'],attempt_ids=['foreign-job'],action='dismiss'))
                with self.assertRaises(APIError):self.w.review_attempt(view['id'],dict(expected_revision=0,attempt_ids=[job['id']],action='restore'))
                restored=self.w.review_attempt(view['id'],dict(expected_revision=result['revision'],attempt_ids=[job['id']],action='restore'))
                self.assertFalse(restored['attempts'][0]['dismissed'])
            self.assertEqual(self.app.images.job(job['id']),original)

    def tearDown(self):
        self.p.sql.close();self.tmp.cleanup()

    def item(self,category):
        entity=next(e for e in self.p.all('world-entity') if e['category']==category and e.get('scope')=='series-bible')
        view=next(v for v in self.p.all('world-asset') if v['entity_id']==entity['id'] and v['kind'] in ('portrait','location','prop'))
        return entity,view

    def upload(self,name='Inspiration.png'):
        return self.w.reference(self.pid,dict(name=name,data_url='data:image/png;base64,'+base64.b64encode(self.raw).decode()))['asset']

    def generate_candidate(self,view,key):
        draft=self.app.images.draft(view['draft_id'])
        with patch('httpx.Client') as http:
            job=self.app.images.generate(draft['id'],dict(expected_revision=draft['revision'],approved=True),key)
            deadline=time.monotonic()+5
            while job['status']=='pending' and time.monotonic()<deadline:
                time.sleep(.02);job=self.app.images.job(job['id'])
            http.assert_not_called()
        self.assertEqual(job['status'],'done')
        return job['outputs'][0]

    def clear(self,e):
        return self.app.agent.dispatch('POST','/agent/v1/filmmaking/entities/'+e['id']+'/clear-approval',dict(expected_revision=e['revision']),None)[1]

    @staticmethod
    def without_approval(value):
        # Approval metadata may change; media, inputs, references and snapshots must not.
        if isinstance(value,dict):
            return {k:WorkshopControlTests.without_approval(v) for k,v in value.items()
                    if not ('mime' in value and k in ('approved','review_state','review_revision'))}
        if isinstance(value,(list,tuple)):return [WorkshopControlTests.without_approval(v) for v in value]
        return value

    def test_uploaded_approval_can_be_cleared_and_same_image_reapproved_for_every_category(self):
        for category in ('Character','Location','Prop'):
            with self.subTest(category=category):
                e,v=self.item(category);asset=self.upload(category+'.png')
                self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=asset['id']))
                e,v=self.item(category);ref=self.app.asset_studio.get(e['reference_id'])
                before=copy.deepcopy((self.app.images.db,self.app.references,self.app.stories.db,self.app.assets))
                with patch.object(self.app,'spawn') as spawn:
                    cleared=self.clear(e);spawn.assert_not_called()
                entity=next(x for x in cleared['entities'] if x['id']==e['id']);view=next(x for x in cleared['views'] if x['id']==v['id'])
                self.assertIsNone(entity['identity_asset_id']);self.assertIsNone(entity['reference_id']);self.assertIsNone(view['selected'])
                self.assertEqual(view['outputs'][0]['id'],asset['id']);self.assertTrue(view['outputs'][0]['uploaded'])
                self.assertEqual((self.app.images.db,self.app.references,self.app.stories.db,self.app.assets),before)
                self.assertEqual(self.app.asset(asset['id'])[1].read_bytes(),self.raw)
                self.assertEqual(next(a for a in self.s.library(self.pid) if a['id']==e['id'])['status'],'described')
                approved=self.w.confirm(v['id'],dict(expected_revision=view['revision'],approved=True,asset_id=asset['id']))
                current=next(x for x in approved['entities'] if x['id']==e['id'])
                self.assertEqual(current['reference_id'],ref['id']);self.assertEqual(current['identity_asset_id'],asset['id'])

    def test_clearing_selected_generated_identity_invalidates_variations_without_deleting_outputs(self):
        for category in ('Character','Location','Prop'):
            with self.subTest(category=category):
                e,v=self.item(category);candidate=self.generate_candidate(v,'main-'+category)
                self.w.confirm(v['id'],dict(expected_revision=v['revision'],approved=True,asset_id=candidate['id']))
                e,v=self.item(category);variation=self.w.add_views(e['id'],dict(expected_revision=e['revision'],views=[dict(label='Alternate')]))[0]
                output=self.generate_candidate(variation,'alternate-'+category)
                self.w.confirm(variation['id'],dict(expected_revision=variation['revision'],approved=True,asset_id=output['id']))
                e,v=self.item(category);before=copy.deepcopy((self.app.images.db,self.app.references,self.app.assets))
                cleared=self.clear(e)
                current=next(x for x in cleared['views'] if x['id']==variation['id'])
                self.assertIsNone(current['selected']);self.assertIsNone(current['reference_id']);self.assertFalse(current['outputs'][0]['compatible'])
                self.assertEqual(self.without_approval((self.app.images.db,self.app.references,self.app.assets)),self.without_approval(before))
                with self.assertRaises(APIError) as error:
                    self.w.generate(self.pid,dict(job_id=cleared['job']['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=variation['id'],expected_revision=current['revision'])]),'blocked-alternate-'+category)
                self.assertEqual(error.exception.code,'identity_required')
                main=next(x for x in cleared['views'] if x['id']==v['id'])
                self.w.confirm(v['id'],dict(expected_revision=main['revision'],approved=True,asset_id=candidate['id']))
                self.assertEqual(self.item(category)[0]['identity_asset_id'],candidate['id'])
                self.assertIsNone(self.p.get(variation['id'],'world-asset')['selected_asset_id'])

    def test_clear_preserves_real_episode_foundation_storyboard_and_job_snapshots(self):
        entities=[]
        for category in ('Character','Location','Prop'):
            e,_=self.item(category);asset=self.upload(category+'.png')
            self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=asset['id']));entities.append(self.item(category)[0])
        book=self.s.save_book(self.eid,dict(expected_revision=0,selected_asset_ids=[e['id'] for e in entities],guide=dict(script='INT. LAB - DAY\nHero repairs the Tool in Lab.')))
        scripted=self.s.script(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=book['episode']['revision']))
        self.s.storyboard(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=scripted['episode']['revision']),'preserved-board-once')
        records={r[0]:r[3] for r in self.p.sql.execute('SELECT * FROM records') if r[1] not in ('world-entity','world-asset')}
        before=copy.deepcopy((self.app.images.db,self.app.agent.db,self.app.stories.db,self.app.references,self.app.assets,self.app.history))
        for e in entities:self.clear(e)
        after={r[0]:r[3] for r in self.p.sql.execute('SELECT * FROM records') if r[1] not in ('world-entity','world-asset')}
        self.assertEqual(records,after)
        self.assertEqual((self.app.images.db,self.app.agent.db,self.app.stories.db,self.app.references,self.app.assets,self.app.history),before)
        self.assertEqual(self.s.book(self.eid)['inheritance']['assets'][0]['identity_asset_id'],entities[0]['identity_asset_id'])

    def test_cleared_image_can_be_replaced_without_modifying_detached_canonical_reference(self):
        e,v=self.item('Location');asset=self.upload('Finished location.png')
        self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=asset['id']))
        e,v=self.item('Location');prior=self.app.asset_studio.get(e['reference_id']);self.clear(e)
        candidate=self.generate_candidate(v,'replacement-location')
        v=self.p.get(v['id'],'world-asset');snapshot=self.w.confirm(v['id'],dict(expected_revision=v['revision'],approved=True,asset_id=candidate['id']))
        current=next(x for x in snapshot['entities'] if x['id']==e['id'])
        self.assertNotEqual(current['reference_id'],prior['id']);self.assertEqual(self.app.asset_studio.get(prior['id']),prior)
        self.assertEqual({o['id'] for o in next(x for x in snapshot['views'] if x['id']==v['id'])['outputs']},{asset['id'],candidate['id']})

    def test_clear_requires_current_revision_and_idle_generation_and_survives_restart(self):
        e,v=self.item('Character');asset=self.upload();self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=asset['id']))
        with self.assertRaises(APIError) as error:self.clear(e)
        self.assertEqual(error.exception.code,'revision_conflict');e,v=self.item('Character')
        self.app.state['phase']='generating'
        with self.assertRaises(APIError) as error:self.clear(e)
        self.assertEqual(error.exception.code,'busy');self.app.state['phase']='idle'
        with patch.object(self.app,'spawn'):
            batch=self.w.generate(self.pid,dict(job_id=self.snapshot['job']['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=v['id'],expected_revision=v['revision'])]),'pending-clear-check')
        with self.assertRaises(APIError) as error:self.clear(e)
        self.assertEqual(error.exception.code,'busy');batch.update(status='done');self.p.put('world-render',batch);self.clear(e)
        self.p.sql.close();self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.w=self.app.filmmaking.workshop;self.s=self.app.filmmaking.series
        e,v=self.item('Character');self.assertIsNone(e['identity_asset_id']);self.assertEqual(self.w.view(v)['outputs'][0]['id'],asset['id'])
        self.w.confirm(v['id'],dict(expected_revision=v['revision'],approved=True,asset_id=asset['id']))
        self.assertEqual(self.item('Character')[0]['identity_asset_id'],asset['id'])

    def test_five_inspiration_images_and_fresh_main_details_reach_both_transports_after_approval(self):
        assets=[self.upload('Inspiration '+str(i)+'.png')['id'] for i in range(5)]
        for category in ('Character','Location','Prop'):
            e,v=self.item(category);self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=assets[0]))
            e,v=self.item(category);profile={**e['profile'],'description':'Fresh visual details for '+category,'reference_ids':assets}
            e=self.w.edit(e['id'],dict(expected_revision=e['revision'],profile=profile))
            # Updating copied sheet metadata advances its revision, just as a
            # rename does. Refresh before submitting a generation request.
            e,v=self.item(category)
            for model in ('gpt-image-2','grok-imagine-image-2.0'):
                with patch.object(self.app,'spawn'):
                    batch=self.w.generate(self.pid,dict(job_id=self.snapshot['job']['id'],model=model,approved=True,requests=[dict(view_id=v['id'],expected_revision=v['revision'])]),'fresh-'+category+'-'+model.replace('.','-'))
                draft=self.app.images.draft(v['draft_id']);_,body,count=self.app.images.compile(draft)
                self.assertEqual(count,5);self.assertEqual(len(body['images']),5)
                self.assertEqual([r['asset_id'] for r in draft['settings']['extras']],assets)
                self.assertIn(profile['description'],body['prompt']);self.assertIn(self.bible['answers']['style'],body['prompt'])
                self.assertEqual(self.item(category)[0]['identity_asset_id'],assets[0])
                batch.update(status='done');self.p.put('world-render',batch)
            with self.assertRaises(APIError):self.w.edit(e['id'],dict(expected_revision=e['revision'],profile={**profile,'reference_ids':assets+[assets[0]]}))
        self.assertEqual(len(self.w.normalize_guide(dict(cast=[dict(id='legacy',name='Hero',reference_ids=assets)]))['cast'][0]['reference_ids']),5)

    def test_linked_identity_without_selected_view_stays_reviewable_and_custom_prompt_is_explicit(self):
        e,v=self.item('Prop');asset=self.upload('Tool.png')
        self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=asset['id']))
        e,v=self.item('Prop');v.pop('uploaded_candidate_ids',None);v.update(selected_asset_id=None,reference_id=None,revision=v['revision']+1)
        with self.p.sql:self.p.put('world-asset',v)
        snapshot=self.clear(e);view=next(x for x in snapshot['views'] if x['id']==v['id'])
        self.assertEqual([o['id'] for o in view['outputs']],[asset['id']])
        self.w.confirm(v['id'],dict(expected_revision=view['revision'],approved=True,asset_id=asset['id']))
        view=self.p.get(v['id'],'world-asset');custom='A deliberately custom prop direction.'
        with patch.object(self.app,'spawn'):
            batch=self.w.generate(self.pid,dict(job_id=snapshot['job']['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=view['id'],expected_revision=view['revision'],prompt=custom)]),'custom-prop-direction')
        self.assertEqual(self.app.images.draft(view['draft_id'])['settings']['prompt'],custom)
        batch.update(status='done');self.p.put('world-render',batch)

    def test_episode_visual_style_uses_pinned_foundation_then_explicit_override(self):
        book=self.s.save_book(self.eid,dict(expected_revision=0,guide=dict(props=[dict(id='guest',name='Guest tool',description='A cyan wrench.')])) )
        workshop=self.s.workshop('episode-book',self.eid,dict(expected_revision=book['revision']))
        self.assertEqual(workshop['job']['result']['visual_style'],self.bible['answers']['style'])
        self.assertIn(self.bible['answers']['style'],workshop['views'][0]['recommended_prompt'])
        self.s.save_bible(self.pid,dict(expected_revision=self.bible['revision'],answers={**self.bible['answers'],'style':'Watercolor illustration'}))
        workshop=self.s.workshop('episode-book',self.eid,dict(expected_revision=book['revision']))
        self.assertEqual(workshop['job']['result']['visual_style'],self.bible['answers']['style'])
        book=self.s.save_book(self.eid,dict(expected_revision=book['revision'],answers={**book['answers'],'style':'Flat comic art'}))
        workshop=self.s.workshop('episode-book',self.eid,dict(expected_revision=book['revision']))
        self.assertEqual(workshop['job']['result']['visual_style'],'Flat comic art')
        self.assertIn('Flat comic art',workshop['views'][0]['recommended_prompt'])
        # A deliberately blank pinned style must not fall through to a newer Bible.
        saved=self.p.get(book['id'],'episode-book');saved['answers']['style']='';saved['inheritance']['answers']['style']='';saved['revision']+=1
        with self.p.sql:self.p.put('episode-book',saved)
        workshop=self.s.workshop('episode-book',self.eid,dict(expected_revision=saved['revision']))
        self.assertEqual(workshop['job']['result']['visual_style'],'')


if __name__=='__main__':unittest.main()
