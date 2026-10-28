"""Cross-tool preservation checks for separate series and episode foundations."""
import base64
import copy
import tempfile
import unittest
from unittest.mock import patch

from agent_api import APIError
from image_studio import mock_png
from story_studio import continuity_context
from studio_server import Studio


class SeriesIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Studio(mock=True, storage=self.tmp.name)
        self.p = self.app.productions
        self.s = self.app.filmmaking.series
        outline = self.p.dispatch('POST', [], {'kind': 'story', 'title': 'Example Series'})[1]
        self.pid = outline['production']['id']
        self.eid = outline['episodes'][0]['id']

    def tearDown(self):
        self.p.sql.close()
        self.tmp.cleanup()

    def state(self):
        return dict(sql=list(self.p.sql.execute('SELECT * FROM records ORDER BY id')),
                    versions=list(self.p.sql.execute('SELECT * FROM versions ORDER BY id,revision')),
                    stories=copy.deepcopy(self.app.stories.db),
                    images=copy.deepcopy(self.app.images.db),
                    videos=copy.deepcopy(self.app.agent.db),
                    references=copy.deepcopy(self.app.references))

    def bible(self, **answers):
        current = self.s.bible(self.pid)
        return self.s.save_bible(self.pid, dict(expected_revision=current['revision'],
            answers={**current['answers'], **answers}, guide=current['guide']))

    def book(self, **changes):
        current = self.s.book(self.eid)
        return self.s.save_book(self.eid, dict(expected_revision=current['revision'],
            expected_episode_revision=current['episode']['revision'], **changes))

    def reference(self, name='SampleHero', category='Character', voice='orion'):
        image = self.app.upload(dict(name=name + '.png',
            data_url='data:image/png;base64,' + base64.b64encode(mock_png()).decode()))
        ref = self.app.save_reference(dict(title=name, handle=name.replace(' ', ''),
            category=category, description='Original identity for ' + name,
            images=[{'asset_id': image['id']}], voice=voice if category == 'Character' else None))
        return self.s.link_reference(self.pid, {'reference_id': ref['id']})

    def episode_with_scene(self, text='SampleHero enters the workshop.'):
        episode = self.app.stories.record('episodes', self.eid)
        return self.app.stories.episode_edit(episode, dict(expected_revision=episode['revision'],
            scenes=[{'title': 'Opening', 'text': text}]))

    def completed_plan(self, assets=None):
        book = self.s.book(self.eid)
        result = dict(reply='A reviewed episode plan.', logline='SampleHero discovers a signal.',
            synopsis='An adventure in the established workshop.', visual_style='Series cinematic style',
            assets=assets or [], scenes=[dict(title='Opening', text='SampleHero finds a signal.',
                shots=[dict(title='The discovery', image_prompt='SampleHero in the workshop.',
                    video_prompt='SampleHero looks toward the signal.', characters=['SampleHero'], location='')])])
        with self.p.sql:
            return self.p.new('world-job', scope='episode-book', purpose='episode-plan',
                production_id=self.pid, episode_id=self.eid, book_revision=book['revision'],
                episode_revision=book['episode']['revision'], world_revision=book['revision'],
                provider='manual', mock=True, status='done',
                context=self.s.planning_context(book), result=result)

    def apply(self, job, **changes):
        return self.s.apply(self.eid, dict(job_id=job['id'], expected_revision=job['revision'],
            expected_episode_revision=self.s.book(self.eid)['episode']['revision'], **changes))

    def trash(self, **changes):
        book=self.s.book(self.eid)
        return self.s.trash_script(self.eid,dict(expected_revision=book['revision'],
            expected_episode_revision=book['episode']['revision'],approved=True,
            expected_job_revisions={j['id']:j['revision'] for j in self.s.jobs(self.eid)},**changes))

    def test_trash_script_preserves_chapters_media_history_and_restore(self):
        bible=self.bible(idea='Series foundation')
        book=self.book(answers={'title':'Keep episode title','idea':'Keep premise','theme':'Keep conflict','style':'Keep look','rules':'Keep rules'},
            guide={'cast':[{'id':'hero','name':'SampleHero'}],'places':[{'id':'home','name':'Home'}],
                'props':[{'id':'tool','name':'Tool'}],'acts':[{'id':'arc','title':'Ending','text':'Keep arc'}],
                'script':'INT. HOME - DAY\nKeep manual draft'})
        episode=self.episode_with_scene()
        shot=self.p.create_shot(self.p.get(self.pid,'production'),dict(title='Keep storyboard shot',episode_id=self.eid,story_scene_id=episode['scenes'][0]['id']))
        plan=self.completed_plan()
        before=self.s.book(self.eid);media=copy.deepcopy((self.app.images.db,self.app.agent.db));saved_shot=copy.deepcopy(self.p.get(shot['id'],'shot'))
        result=self.trash();after=result['book']
        self.assertEqual(after['answers'],before['answers'])
        self.assertEqual({k:v for k,v in after['guide'].items() if k!='script'},{k:v for k,v in before['guide'].items() if k!='script'})
        self.assertEqual(after['inheritance'],before['inheritance'])
        self.assertEqual(after['selected_asset_ids'],before['selected_asset_ids'])
        self.assertEqual(after['guide']['script'],'');self.assertEqual(after['episode']['scenes'],[])
        self.assertEqual(after['episode']['title'],before['episode']['title'])
        self.assertEqual(self.p.get(shot['id'],'shot'),saved_shot)
        self.assertEqual((self.app.images.db,self.app.agent.db),media)
        self.assertEqual(self.s.bible(self.pid),bible)
        self.assertTrue(any(v['scenes']==episode['scenes'] for v in after['episode']['versions']))
        self.assertEqual(after['script_drafts'][0]['script'],before['guide']['script'])
        archived=self.p.get(plan['id'],'world-job');self.assertTrue(archived['script_inactive'])
        restored=self.s.fork(archived,{'expected_revision':archived['revision']})
        self.assertFalse(restored.get('script_inactive',False));self.assertEqual(restored['result'],plan['result'])
        self.assertEqual(self.s.book(self.eid)['answers'],before['answers'])

    def test_trash_script_rejects_stale_jobs_and_pending_writing_without_mutation(self):
        self.book(guide={'script':'Keep this draft'})
        job=self.completed_plan();before=self.state()
        book=self.s.book(self.eid)
        with self.assertRaises(APIError) as stale:
            self.s.trash_script(self.eid,{'expected_revision':book['revision'],'expected_episode_revision':book['episode']['revision'],'approved':True,'expected_job_revisions':{}})
        self.assertEqual(stale.exception.code,'revision_conflict');self.assertEqual(self.state(),before)
        with self.p.sql:
            job.update(status='pending');self.p.put('world-job',job)
        before=self.state()
        with self.assertRaises(APIError) as pending:self.trash()
        self.assertEqual(pending.exception.code,'busy');self.assertEqual(self.state(),before)

    def test_manual_script_save_preserves_all_chapters_and_supersedes_ai_review(self):
        self.book(answers={'idea':'Keep premise','theme':'Keep conflict','style':'Keep look','rules':'Keep rules'},
            guide={'acts':[{'id':'arc','title':'Part one','text':'Keep story beat'}],'script':'INT. HOME - DAY\nManual text'})
        job=self.completed_plan();before=self.s.book(self.eid)
        saved=self.s.script(self.eid,{'expected_revision':before['revision'],'expected_episode_revision':before['episode']['revision']})['book']
        self.assertEqual(saved['answers'],before['answers']);self.assertEqual(saved['guide'],before['guide'])
        self.assertTrue(self.p.get(job['id'],'world-job')['script_inactive'])
        self.assertIn('Manual text',saved['episode']['scenes'][0]['text'])

    def test_reading_new_books_preserves_legacy_world_script_and_every_record(self):
        old_world = self.app.filmmaking.save_world(self.pid, dict(expected_revision=0,
            answers={'title': 'Ambiguous old story', 'idea': 'Original old episode idea.'},
            guide={'cast': [{'id': 'legacy-hero', 'name': 'Old hero'}]}))
        episode = self.episode_with_scene('Keep this original script verbatim.')
        self.p.create_shot(self.p.get(self.pid, 'production'), dict(title='Original shot',
            episode_id=self.eid, story_scene_id=episode['scenes'][0]['id']))
        self.p.sql.commit()
        before = self.state()
        with patch.object(self.app, 'spawn') as spawn:
            bible = self.s.bible(self.pid)
            book = self.s.book(self.eid)
            self.s.library(self.pid, self.eid)
            self.s.workshop('series-bible', self.pid)
            context = continuity_context(self.app, self.pid, self.eid)
            spawn.assert_not_called()
        self.assertEqual(bible['legacy_world'], old_world)
        self.assertEqual(bible['answers']['idea'], '')
        self.assertEqual(book['answers']['title'], episode['title'])
        self.assertIsNone(book['inheritance'])
        self.assertNotIn('legacy_world', context['series_continuity']['snapshot'])
        self.assertEqual(self.state(), before)

    def test_series_and_asset_versions_stay_pinned_until_explicit_refresh(self):
        self.bible(genre='Adventure', tone='Hopeful', rules='SampleHero always wears a blue scarf.')
        hero = self.reference()
        book = self.book(selected_asset_ids=[hero['id']])
        pinned = copy.deepcopy(book['inheritance'])
        self.bible(genre='Mystery', tone='Tense')
        original_ref = hero['reference']
        self.app.asset_studio.dispatch('PUT', [original_ref['id']],
            dict(expected_revision=original_ref['revision'], description='A deliberately revised identity.'), None)
        book = self.book(answers={**book['answers'], 'idea': 'A second paragraph in this episode.'})
        self.assertEqual(book['inheritance'], pinned)
        self.assertEqual(book['inheritance']['assets'][0]['reference']['voice'], 'orion')
        context = self.s.planning_context(book)
        self.assertEqual(context['questionnaire']['genre'], 'Adventure')
        self.assertEqual(context['existing_assets'][0]['description'], original_ref['description'])
        refreshed = self.book(refresh_inheritance=True)
        self.assertEqual(refreshed['inheritance']['answers']['genre'], 'Mystery')
        self.assertEqual(refreshed['inheritance']['assets'][0]['reference']['description'],
                         'A deliberately revised identity.')
        refreshed['inheritance']['assets'][0]['reference']['description'] = 'Mutated client copy'
        self.assertNotEqual(self.s.book(self.eid)['inheritance']['assets'][0]['reference']['description'],
                            'Mutated client copy')

    def test_cross_series_and_foreign_workspace_references_are_rejected(self):
        hero = self.reference()
        other = self.p.dispatch('POST', [], {'kind': 'story', 'title': 'Other series'})[1]
        other_eid = other['episodes'][0]['id']
        before = self.state()
        with self.assertRaises(APIError):
            self.s.save_book(other_eid, {'expected_revision': 0, 'selected_asset_ids': [hero['id']]})
        with self.assertRaises(APIError):
            self.s.library(self.pid, other_eid)
        with self.assertRaises(APIError):
            continuity_context(self.app, self.pid, other_eid)
        self.assertEqual(self.state(), before)
        with tempfile.TemporaryDirectory() as root:
            foreign = Studio(mock=True, storage=root)
            try:
                with self.assertRaises(APIError):
                    foreign.filmmaking.series.bible(self.pid)
                with self.assertRaises(APIError):
                    foreign.filmmaking.series.book(self.eid)
            finally:
                foreign.productions.sql.close()

    def test_stale_bible_and_episode_saves_preserve_newer_work(self):
        bible = self.bible(idea='The shared series premise.')
        book = self.book(answers={**self.s.book(self.eid)['answers'], 'idea': 'This episode premise.'})
        before = self.state()
        with self.assertRaises(APIError):
            self.s.save_bible(self.pid, {'expected_revision': 0, 'answers': {'idea': 'Stale overwrite'}})
        with self.assertRaises(APIError):
            self.s.save_book(self.eid, {'expected_revision': 0, 'answers': {'idea': 'Stale overwrite'}})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.s.bible(self.pid)['revision'], bible['revision'])
        self.assertEqual(self.s.book(self.eid)['revision'], book['revision'])

    def test_apply_targets_selected_episode_and_preserves_existing_scenes_media_and_shots(self):
        hero = self.reference()
        self.book(selected_asset_ids=[hero['id']])
        episode = self.episode_with_scene()
        old = self.p.create_shot(self.p.get(self.pid, 'production'), dict(title='Finished opening',
            episode_id=self.eid, story_scene_id=episode['scenes'][0]['id']))
        image = self.app.images.draft(old['image_id'])
        self.app.images.edit(image['id'], dict(expected_revision=image['revision'],
            settings={**image['settings'], 'prompt': 'Approved original composition'},
            named_references=[hero['handle']]))
        video = self.app.agent.record(old['video_id'])
        self.app.agent.patch(video['id'], dict(expected_revision=video['revision'],
            changes={'prompt': 'Approved original action'}, named_references=[hero['handle']]))
        another = self.p.dispatch('POST', [self.pid, 'episodes'], {'title': 'Unrelated episode'})[1]
        old_shot = self.p.get(old['id'], 'shot')
        old_image = copy.deepcopy(self.app.images.draft(old['image_id']))
        old_video = copy.deepcopy(self.app.agent.record(old['video_id']))
        before_episodes = len(self.p.outline(self.pid)['episodes'])
        job = self.completed_plan()
        applied = self.apply(job, replace_existing=True)
        after = self.app.stories.record('episodes', self.eid)
        self.assertEqual(len(self.p.outline(self.pid)['episodes']), before_episodes)
        self.assertEqual(after['scenes'][0]['id'], episode['scenes'][0]['id'])
        self.assertEqual(self.app.stories.record('episodes', another['id']), another)
        self.assertEqual(self.p.get(old['id'], 'shot'), old_shot)
        self.assertEqual(self.app.images.draft(old['image_id']), old_image)
        self.assertEqual(self.app.agent.record(old['video_id']), old_video)
        self.assertEqual(applied['episode_id'], self.eid)
        new_shot = self.p.get(applied['shot_ids'][0], 'shot')
        self.assertEqual(new_shot['story_scene_id'], episode['scenes'][0]['id'])
        new_video = self.app.agent.record(new_shot['video_id'])
        self.assertEqual(new_video['scene']['voices'][0]['voice'], 'orion')
        self.assertEqual(new_video['scene']['named'][0]['id'], hero['reference']['id'])
        self.assertEqual(self.app.images.draft(new_shot['image_id'])['settings']['bindings'][0]['snapshot'],
                         hero['reference'])
        self.assertEqual(self.app.images.db['jobs'], [])
        self.assertEqual(self.app.records(), [])
        before = self.state()
        self.apply(applied, replace_existing=True)
        self.assertEqual(self.state(), before)

    def test_changed_book_or_script_cannot_apply_an_older_plan(self):
        self.book(answers={**self.s.book(self.eid)['answers'], 'idea': 'Episode idea.'})
        job = self.completed_plan()
        self.book(answers={**self.s.book(self.eid)['answers'], 'idea': 'Newer unsent episode idea.'})
        before = self.state()
        with self.assertRaises(APIError):
            self.apply(job)
        self.assertEqual(self.state(), before)
        job = self.completed_plan()
        self.episode_with_scene('A newer manually edited script.')
        before = self.state()
        with self.assertRaises(APIError):
            self.apply(job, replace_existing=True)
        self.assertEqual(self.state(), before)

    def test_bible_asset_changes_and_episode_promotion_never_rewrite_existing_shots(self):
        hero = self.reference()
        self.book(selected_asset_ids=[hero['id']])
        applied = self.apply(self.completed_plan(assets=[dict(name='Signal Beacon', category='Prop',
            description='A small amber beacon.', views=['Front view'])]))
        old_shots = copy.deepcopy(self.p.all('shot'))
        old_images = copy.deepcopy(self.app.images.db)
        old_videos = copy.deepcopy(self.app.agent.db)
        beacon = next(a for a in self.s.library(self.pid, self.eid) if a['name'] == 'Signal Beacon')
        self.assertNotIn(beacon['id'], [a['id'] for a in self.s.library(self.pid)])
        shared = self.s.promote(self.pid, dict(entity_id=beacon['id'], expected_revision=beacon['revision']))
        self.assertEqual(shared['scope'], 'series')
        self.assertIn(beacon['id'], [a['id'] for a in self.s.library(self.pid)])
        ref = hero['reference']
        self.app.asset_studio.dispatch('PUT', [ref['id']], dict(expected_revision=ref['revision'],
            description='SampleHero has a revised series description.'), None)
        self.bible(style='New style applies to future episodes.')
        self.s.workshop('series-bible', self.pid, {'expected_revision': self.s.bible(self.pid)['revision']})
        self.assertEqual(self.p.all('shot'), old_shots)
        self.assertEqual(self.app.images.db, old_images)
        self.assertEqual(self.app.agent.db, old_videos)
        self.assertEqual(self.p.get(applied['shot_ids'][0], 'shot')['series_context']['assets'][0]['reference'], ref)

    def test_script_and_cross_tool_collaborators_use_pinned_continuity_without_mutating_books(self):
        self.bible(tone='Hopeful', rules='SampleHero always wears a blue scarf.')
        self.book(answers={**self.s.book(self.eid)['answers'], 'idea': 'SampleHero discovers a signal.'})
        self.bible(tone='Tense', rules='A later series change.')
        before = self.state()
        context = self.app.creative.context(dict(production_id=self.pid, episode_id=self.eid,
            scope='episode', stage='script'))
        self.assertEqual(context['series_continuity']['source'], 'episode_inheritance')
        self.assertEqual(context['series_continuity']['snapshot']['answers']['tone'], 'Hopeful')
        self.assertEqual(context['episode_book']['answers']['idea'], 'SampleHero discovers a signal.')
        self.assertEqual(self.state(), before)
        series_context = self.app.creative.context(dict(production_id=self.pid, episode_id=self.eid,
            scope='production', stage='develop'))
        self.assertEqual(series_context['series_continuity']['source'], 'series_bible')
        self.assertEqual(series_context['series_continuity']['snapshot']['answers']['tone'], 'Tense')
        self.assertNotIn('episode_book', series_context)
        self.assertEqual(self.state(), before)
        episode = self.app.stories.record('episodes', self.eid)
        with patch.object(self.app, 'spawn') as spawn:
            reply = self.app.stories.chat(episode, dict(expected_revision=episode['revision'],
                approved=True, message='Keep SampleHero consistent in this scene.'), 'continuity-script-message')
            spawn.assert_called_once()
        self.assertEqual(reply['context']['series_continuity'], context['series_continuity'])
        new_episode = self.p.dispatch('POST', [self.pid, 'episodes'], {'title': 'Future adventure'})[1]
        before = self.state()
        fresh = self.app.creative.context(dict(production_id=self.pid, episode_id=new_episode['id'],
            scope='episode', stage='script'))
        self.assertEqual(fresh['series_continuity']['source'], 'series_bible')
        self.assertEqual(fresh['series_continuity']['snapshot']['answers']['tone'], 'Tense')
        self.assertIsNone(self.s.book(new_episode['id'])['inheritance'])
        self.assertEqual(self.state(), before)

    def test_later_episode_reference_can_update_current_drafts_without_touching_other_episode(self):
        job = self.completed_plan(assets=[dict(name='Signal Beacon', category='Prop',
            description='A small amber beacon.', views=['Front view'])])
        job['result']['scenes'][0]['text'] = 'SampleHero studies the Signal Beacon.'
        job['result']['scenes'][0]['shots'][0]['image_prompt'] = 'SampleHero beside the Signal Beacon.'
        with self.p.sql:
            self.p.put('world-job', job)
        applied = self.apply(job)
        current_shot = self.p.get(applied['shot_ids'][0], 'shot')
        beacon = next(a for a in self.s.library(self.pid, self.eid) if a['name'] == 'Signal Beacon')
        another = self.p.dispatch('POST', [self.pid, 'episodes'], {'title': 'Finished earlier episode'})[1]
        another = self.app.stories.episode_edit(self.app.stories.record('episodes', another['id']),
            dict(expected_revision=another['revision'], scenes=[{'title': 'Earlier scene', 'text': 'SampleHero rests.'}]))
        protected = self.p.create_shot(self.p.get(self.pid, 'production'), dict(title='Earlier shot',
            episode_id=another['id'], story_scene_id=another['scenes'][0]['id']))
        protected_image = copy.deepcopy(self.app.images.draft(protected['image_id']))
        protected_video = copy.deepcopy(self.app.agent.record(protected['video_id']))
        picture = self.app.upload(dict(name='Beacon.png',
            data_url='data:image/png;base64,' + base64.b64encode(mock_png()).decode()))
        self.app.filmmaking.workshop.upload_identity(beacon['id'],
            dict(expected_revision=beacon['revision'], asset_id=picture['id']))
        # Approval saves the reference, without changing any episode draft yet.
        self.assertEqual(self.app.images.draft(current_shot['image_id'])['settings']['bindings'], [])
        book = self.s.book(self.eid)
        request = dict(expected_revision=book['revision'],
            expected_episode_revision=book['episode']['revision'], approved=True,
            shots=[dict(id=current_shot['id'], expected_revision=current_shot['revision'])])
        self.s.refresh_assets(self.eid, request)
        current = self.app.images.draft(current_shot['image_id'])
        self.assertEqual(current['settings']['bindings'][0]['snapshot']['images'][0]['asset_id'], picture['id'])
        self.assertEqual(self.p.get(protected['id'], 'shot'), protected)
        self.assertEqual(self.app.images.draft(protected['image_id']), protected_image)
        self.assertEqual(self.app.agent.record(protected['video_id']), protected_video)
        before = self.state()
        with self.assertRaises(APIError):
            self.s.refresh_assets(self.eid, {**request, 'shots': [
                dict(id=protected['id'], expected_revision=protected['revision'])]})
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
