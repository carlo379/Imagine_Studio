import base64
import copy
import tempfile
import unittest
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError
from image_studio import mock_png


class SeriesBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.p=self.app.productions;self.f=self.app.filmmaking;self.s=self.f.series
        outline=self.p.dispatch('POST',[],dict(kind='story',title='Example Series'))[1]
        self.pid=outline['production']['id'];self.eid=outline['episodes'][0]['id']
    def tearDown(self):
        self.p.sql.close();self.tmp.cleanup()
    def save(self):
        return self.s.save_bible(self.pid,dict(expected_revision=0,answers=dict(idea='A curious robot explores his world.',genre='Adventure',style='Clean illustrated science fiction.'),guide=dict(cast=[dict(id='hero',name='SampleHero',role='Hero',description='A golden robot.',voice='Warm curious voice.',voice_preset='orion')],places=[dict(id='lab',name='Workshop',description='A sunlit laboratory.')],props=[dict(id='charger',name='Charging station',description='A mint light ring.',purpose='SampleHero recharges here.')])) )
    def test_bible_workshop_before_any_episode_script_and_real_prop_prompts(self):
        bible=self.save();before=copy.deepcopy(self.app.stories.db)
        workshop=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        self.assertEqual([e['category'] for e in workshop['entities']],['Character','Location','Prop'])
        self.assertEqual(self.app.stories.db,before);self.assertFalse(self.app.images.db['jobs'])
        prop=next(v for v in workshop['views'] if v['kind']=='prop')
        self.assertIn('complete object',prop['draft']['settings']['prompt'])
        self.assertNotIn('location scouting',prop['draft']['settings']['prompt'])
        self.assertEqual(self.s.workshop('series-bible',self.pid)['job']['id'],workshop['job']['id'])
        with self.assertRaises(APIError):self.f.workshop.snapshot(self.pid)
        self.assertEqual(self.f.dispatch('GET',['worlds',self.pid,'jobs'],{},None)[1],[])
        specific=self.f.dispatch('GET',['entities',workshop['entities'][0]['id'],'workshop'],{},None)[1]
        self.assertEqual(specific['job']['id'],workshop['job']['id'])

    def test_first_character_sheet_and_existing_portrait_draft_use_exactly_four_views(self):
        bible=self.save();workshop=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        hero=workshop['entities'][0];view=next(v for v in workshop['views'] if v['entity_id']==hero['id']);draft=self.app.images.draft(view['draft_id'])
        self.assertEqual(draft['settings']['ratio'],'3:2')
        for phrase in ('full body front','full body rear','full body side','three-quarter','head close-up'):
            self.assertIn(phrase,draft['settings']['prompt'])
        old={**draft['settings'],'ratio':'2:3','prompt':'Generate a face-only portrait.'}
        self.app.images.edit(draft['id'],dict(expected_revision=draft['revision'],settings=old))
        with patch.object(self.app,'spawn') as spawn:
            result=self.s.dispatch('POST',['series',self.pid,'generate'],dict(job_id=workshop['job']['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=view['id'],expected_revision=view['revision'],character_sheet=True)]),'four-view-sheet-once')[1]
            spawn.assert_called_once()
        saved=self.app.images.draft(view['draft_id'])
        self.assertEqual(saved['settings']['model'],'gpt-image-2');self.assertEqual(saved['settings']['ratio'],'3:2');self.assertIn('exactly four clearly separated views',saved['settings']['prompt'])
        self.assertEqual(len(result['requests']),1);self.assertIsNone(self.p.get(hero['id'],'world-entity')['identity_asset_id'])

    def test_saved_appearance_survives_visual_edit_and_reaches_both_image_models(self):
        bible=self.save();appearance=('Golden metal plating, blue eyes and a distinctive circular chest light. '*8)+'A small notch on his left wrist.'
        guide=copy.deepcopy(bible['guide']);guide['cast'][0]['description']=appearance
        bible=self.s.save_bible(self.pid,dict(expected_revision=bible['revision'],answers=bible['answers'],guide=guide))
        workshop=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        hero=workshop['entities'][0];view=next(v for v in workshop['views'] if v['entity_id']==hero['id'])
        self.assertTrue(hero['description'].startswith('Description: '+appearance),'Visual details take precedence in the display summary')
        self.assertEqual(hero['profile']['description'],appearance)
        draft=self.app.images.draft(view['draft_id'])
        self.assertIn('Appearance & distinguishing details: '+appearance,draft['settings']['prompt'])
        for model in ('gpt-image-2','grok-imagine-image-2.0'):
            record=copy.deepcopy(draft);record['settings'].update(model=model,quality='auto' if model=='gpt-image-2' else 'low',resolution='auto' if model=='gpt-image-2' else '1k')
            _,body,_=self.app.images.compile(record)
            self.assertIn(appearance,body['prompt']);self.assertIn(bible['answers']['style'],body['prompt'])
        changed=appearance+' A narrow scar on his right cheek.'
        updated=self.f.workshop.edit(hero['id'],dict(expected_revision=hero['revision'],profile={**hero['profile'],'description':changed},description=hero['description']))
        self.assertEqual(updated['profile']['description'],changed)
        self.assertIn(changed,self.app.images.draft(view['draft_id'])['settings']['prompt'])
        self.assertEqual(self.s.bible(self.pid)['guide']['cast'][0]['description'],appearance,'Visual refinement preserves the original Bible card')
    def test_confirmed_bible_character_keeps_actual_voice_and_guided_metadata(self):
        bible=self.save();snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        hero=snapshot['entities'][0];asset=self.app.upload(dict(name='SampleHero.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        snapshot=self.f.workshop.upload_identity(hero['id'],dict(expected_revision=hero['revision'],asset_id=asset['id']))
        hero=snapshot['entities'][0];ref=self.app.asset_studio.get(hero['reference_id'])
        self.assertEqual(ref['voice'],'orion');self.assertEqual(hero['profile']['voice'],'Warm curious voice.')
        updated=self.f.workshop.edit(hero['id'],dict(expected_revision=hero['revision'],profile={**hero['profile'],'voice_preset':'carina'}))
        self.assertEqual(updated['profile']['voice_preset'],'carina');self.assertEqual(self.app.asset_studio.get(ref['id'])['voice'],'carina')
        updated=self.f.workshop.edit(hero['id'],dict(expected_revision=updated['revision'],profile={**updated['profile'],'voice_preset':''}))
        self.assertIsNone(self.app.asset_studio.get(ref['id'])['voice'])
    def test_episode_plan_targets_existing_selected_episode_and_replays_once(self):
        self.save();book=self.s.save_book(self.eid,dict(expected_revision=0,answers=dict(title='The Lost Signal',idea='SampleHero finds an old signal.'),expected_episode_revision=1))
        count=len(self.app.stories.db['episodes'])
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            j=self.s.plan(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=book['episode']['revision'],approved=True),'episode-write-once')
        j=self.p.get(j['id'],'world-job')
        self.assertEqual(j['status'],'done',j.get('error'))
        self.assertEqual(j['context']['questionnaire']['genre'],'Adventure')
        applied=self.s.apply(self.eid,dict(job_id=j['id'],expected_revision=j['revision'],expected_episode_revision=book['episode']['revision']))
        self.assertEqual(applied['episode_id'],self.eid);self.assertEqual(len(self.app.stories.db['episodes']),count)
        shots=len(self.p.all('shot'));again=self.s.apply(self.eid,dict(job_id=j['id'],expected_revision=j['revision']))
        self.assertEqual(again['id'],j['id']);self.assertEqual(len(self.p.all('shot')),shots)
    def test_manual_script_and_storyboard_do_not_generate_or_create_episode(self):
        book=self.s.save_book(self.eid,dict(expected_revision=0,guide=dict(script='INT. WORKSHOP - DAY\nSampleHero listens.\nEXT. GARDEN - NIGHT\nA signal glows.')))
        saved=self.s.script(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=book['episode']['revision']))
        self.assertEqual(len(saved['episode']['scenes']),2)
        with self.assertRaises(APIError):self.s.script(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=saved['episode']['revision']))
        j=self.s.storyboard(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=saved['episode']['revision']),'manual-board-once')
        self.assertEqual(len(j['shot_ids']),2);self.assertEqual(len(self.app.stories.db['episodes']),1)
        self.assertFalse(self.app.images.db['jobs']);self.assertFalse(self.app.agent.db.get('jobs',[]))
    def test_episode_asset_promotion_is_explicit_and_revision_checked(self):
        book=self.s.save_book(self.eid,dict(expected_revision=0,guide=dict(props=[dict(id='tool',name='Signal wrench',description='A silver signal scanner.')])) )
        snapshot=self.s.workshop('episode-book',self.eid,dict(expected_revision=book['revision']))
        prop=snapshot['entities'][0];self.assertEqual(self.s.library(self.pid),[])
        with self.assertRaises(APIError):self.s.promote(self.pid,dict(entity_id=prop['id'],expected_revision=0))
        saved=self.s.promote(self.pid,dict(entity_id=prop['id'],expected_revision=prop['revision']))
        self.assertEqual(saved['scope'],'series');self.assertEqual(len(self.s.library(self.pid)),1)
        self.assertEqual(self.p.get(prop['id'],'world-entity')['scope'],'episode-book')
    def test_external_episode_title_is_authoritative_and_restart_keeps_books(self):
        bible=self.save();book=self.s.save_book(self.eid,dict(expected_revision=0,answers=dict(idea='A signal arrives.')))
        ep=self.app.stories.record('episodes',self.eid);self.app.stories.episode_edit(ep,dict(expected_revision=ep['revision'],title='Renamed from Scripts'))
        self.assertEqual(self.s.book(self.eid)['answers']['title'],'Renamed from Scripts')
        before=copy.deepcopy(self.s.book(self.eid));self.p.sql.close()
        self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.s=self.app.filmmaking.series
        self.assertEqual(self.s.book(self.eid),before);self.assertEqual(self.s.bible(self.pid)['answers'],bible['answers'])
    def test_live_provider_gate_prevents_network_and_leaves_book_saved(self):
        book=self.s.save_book(self.eid,dict(expected_revision=0,answers=dict(idea='A signal arrives.')));self.app.mock=False
        with patch.object(self.app.images,'account_status',return_value={'subscription':{'signed_in':False}}),patch('filmmaking_studio.writing_reply') as writer:
            with self.assertRaises(APIError):self.s.plan(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=book['episode']['revision'],approved=True),'blocked-writing-once')
            writer.assert_not_called()
        self.assertEqual(self.s.book(self.eid)['answers']['idea'],'A signal arrives.');self.assertFalse(self.p.all('world-job'))
    def test_visual_refinements_survive_return_to_book_and_workshop_reopen(self):
        bible=self.save();snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        hero=snapshot['entities'][0]
        edited=self.f.workshop.edit(hero['id'],dict(expected_revision=hero['revision'],profile={**hero['profile'],'clothing':'Dark green jacket','voice':'A calm precise delivery.'}))
        reopened=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        self.assertEqual(reopened['entities'][0]['profile'],edited['profile'])
        guide=copy.deepcopy(bible['guide']);guide['cast'][0]['role']='Lead adventurer'
        bible=self.s.save_bible(self.pid,dict(expected_revision=bible['revision'],guide=guide))
        reopened=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        self.assertEqual(reopened['entities'][0]['profile']['clothing'],'Dark green jacket')
        self.assertEqual(reopened['entities'][0]['profile']['role'],'Lead adventurer')
    def test_episode_approved_reference_is_reused_and_explicit_refresh_is_scoped(self):
        book=self.s.save_book(self.eid,dict(expected_revision=0,guide=dict(cast=[dict(id='guest',name='Signal robot',description='A blue robot.')],script='INT. WORKSHOP - DAY\nSignal robot listens.')))
        workshop=self.s.workshop('episode-book',self.eid,dict(expected_revision=book['revision']));hero=workshop['entities'][0]
        asset=self.app.upload(dict(name='Signal robot.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        self.f.workshop.upload_identity(hero['id'],dict(expected_revision=hero['revision'],asset_id=asset['id']))
        script=self.s.script(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=book['episode']['revision']))
        job=self.s.storyboard(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=script['episode']['revision']),'own-reference-board')
        shot=self.p.get(job['shot_ids'][0],'shot');image=self.app.images.draft(shot['image_id'])
        self.assertEqual(image['settings']['bindings'][0]['snapshot']['images'][0]['asset_id'],asset['id'])
        count=len(self.p.all('shot'));repeat=self.s.storyboard(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=script['episode']['revision']),'own-reference-board')
        self.assertEqual(repeat['id'],job['id']);self.assertEqual(len(self.p.all('shot')),count)
        second=self.p.dispatch('POST',[self.pid,'episodes'],dict(title='Another episode'))[1]
        with self.assertRaises(APIError):self.s.refresh_assets(second['id'],dict(expected_revision=0,expected_episode_revision=second['revision'],approved=True,shots=[dict(id=shot['id'],expected_revision=shot['revision'])]))
        refreshed=self.s.refresh_assets(self.eid,dict(expected_revision=book['revision'],expected_episode_revision=script['episode']['revision'],approved=True,shots=[dict(id=shot['id'],expected_revision=shot['revision'])]))
        self.assertEqual(refreshed['shots'][0]['id'],shot['id'])

    def test_pdf_exports_are_read_only_and_keep_series_episode_titles_separate(self):
        self.save()
        self.s.save_book(self.eid,dict(expected_revision=0,expected_episode_revision=1,answers=dict(title='The Lost Signal',idea='An episode premise.'),guide=dict(script='INT. WORKSHOP - DAY\nSampleHero hears a signal.')))
        before=(list(self.p.sql.execute('SELECT * FROM records')),copy.deepcopy(self.app.stories.db))
        for scope,identity,label in [('series-bible',self.pid,'Series Bible'),('episode-book',self.eid,'Episode Storybook')]:
            result,mime=self.s.export_pdf(scope,identity)
            self.assertEqual(mime,'application/pdf');self.assertTrue(result.startswith(b'%PDF'));self.assertIn(b'%%EOF',result)
            with patch('world_bible.render_bible',return_value=b'pdf') as render:
                self.s.export_pdf(scope,identity)
                arguments=render.call_args.args
                self.assertEqual(arguments[4]['book_kind'],label)
                self.assertEqual(arguments[2]['context']['questionnaire']['title'],'Example Series' if scope=='series-bible' else 'The Lost Signal')
        self.assertEqual(before,(list(self.p.sql.execute('SELECT * FROM records')),self.app.stories.db))

    def test_long_descriptive_fields_survive_book_visual_edit_and_identity_upload(self):
        full=('A thoughtful, curious person with a detailed background. '*50)+'END OF DESCRIPTION'
        lighting='Warm diffuse window light. '*38+'FINAL LIGHTING DETAIL'
        lighting=lighting[:980]+'END OF LIGHTING'
        bible=self.s.save_bible(self.pid,dict(expected_revision=0,guide=dict(cast=[dict(id='mark',name='Mark',personality=full,motivation=full,relationships=full,clothing=full,description=full,voice=full)],places=[dict(id='lab',name='Workshop',description=full,grading=full,lighting=lighting)],props=[dict(id='tool',name='Favorite tool',description=full,purpose=full)])))
        self.assertEqual(self.s.bible(self.pid)['guide']['cast'][0]['personality'],full)
        snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']));hero=snapshot['entities'][0]
        edited=self.f.workshop.edit(hero['id'],dict(expected_revision=hero['revision'],description=full,profile=hero['profile']))
        self.assertEqual(edited['description'],full);self.assertEqual(edited['profile']['motivation'],full)
        asset=self.app.upload(dict(name='Mark.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        uploaded=self.f.workshop.upload_identity(hero['id'],dict(expected_revision=edited['revision'],asset_id=asset['id']))
        self.assertEqual(uploaded['entities'][0]['description'],full)
        self.assertEqual(uploaded['entities'][0]['profile']['personality'],full)
        episode=self.s.save_book(self.eid,dict(expected_revision=0,guide=bible['guide']))
        self.assertEqual(self.s.book(self.eid)['guide']['places'][0]['description'],full)
        self.assertEqual(episode['guide']['props'][0]['purpose'],full)
        self.assertEqual(episode['guide']['places'][0]['lighting'],lighting)
        location=next(e for e in snapshot['entities'] if e['category']=='Location')
        self.assertIn(lighting,self.f.workshop.prompt(location,'location','Location reference'))

    def test_episode_pdf_uses_pinned_selected_identity_not_later_series_reference(self):
        bible=self.save();workshop=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
        hero=workshop['entities'][0]
        asset=self.app.upload(dict(name='SampleHero.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        self.f.workshop.upload_identity(hero['id'],dict(expected_revision=hero['revision'],asset_id=asset['id']))
        self.s.save_book(self.eid,dict(expected_revision=0,selected_asset_ids=[hero['id']]))
        pinned=self.s.book(self.eid)['inheritance']['assets'][0]
        with patch('world_bible.render_bible',return_value=b'pdf') as render:
            self.s.export_pdf('episode-book',self.eid)
            snapshot=render.call_args.args[3]
            self.assertEqual([e['name'] for e in snapshot['entities']],['SampleHero'])
            self.assertEqual(snapshot['entities'][0]['reference'],pinned['reference'])
