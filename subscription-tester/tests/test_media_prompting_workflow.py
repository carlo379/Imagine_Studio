"""Offline writer selection and compact continuity; no provider or media calls."""
import copy
import unittest
import httpx
from unittest.mock import Mock, patch

from agent_api import APIError
import prompt_guides as guides
from story_studio import WritingError
import test_prompt_guides as fixtures


class MediaFixture:
    setUp = fixtures.PreparationTests.setUp
    tearDown = fixtures.PreparationTests.tearDown
    reply = fixtures.PreparationTests.reply
    image = fixtures.PreparationTests.image
    prepare = fixtures.PreparationTests.prepare
    apply = fixtures.PreparationTests.apply


class WriterOrderTests(MediaFixture, unittest.TestCase):
    def video(self):
        return self.app.agent.create(dict(scene=dict(prompt='Eve waits.')))

    def test_unset_provider_uses_chatgpt_for_grok_video_and_image(self):
        for kind, record in [('video', self.video()), ('image', self.image())]:
            self.writer.reset_mock()
            job = self.prepare(kind, record)
            self.assertEqual(job['status'], 'done', job.get('error'))
            self.assertEqual([call.args[0] for call in self.writer.call_args_list], ['codex'])
            self.assertEqual(job['provider'], 'codex')
            self.assertEqual(job['provider_requested'], 'auto')
            self.assertIsNone(job['fallback_reason'])

    def test_codex_failures_use_one_grok_fallback_and_record_reason_and_provenance(self):
        errors = [WritingError(dict(message='Weekly limit', codexErrorInfo='usageLimitExceeded')),
                  WritingError(dict(message='Slow down', codexErrorInfo='rateLimitExceeded')),
                  WritingError(dict(message='Server down', codexErrorInfo={'unknown':{'httpStatusCode':503}})),
                  TimeoutError('ChatGPT timed out'), ValueError('Codex unavailable'),
                  RuntimeError('ChatGPT upstream error'),
                  httpx.HTTPStatusError('HTTP 503', request=httpx.Request('POST','https://writer.invalid'),
                      response=httpx.Response(503))]
        for error in errors:
            with self.subTest(error=str(error)):
                self.writer.reset_mock()
                def write(provider, *args):
                    if provider == 'codex':raise error
                    value = self.reply(provider, *args)
                    value.returned_model = 'fixture-grok'
                    return value
                self.writer.side_effect = write
                record = self.video()
                with patch('request_diagnostics.writing_fallback') as log:
                    job = self.prepare('video', record)
                self.assertEqual(job['status'], 'done', job.get('error'))
                self.assertEqual([call.args[0] for call in self.writer.call_args_list], ['codex','grok'])
                self.assertEqual(job['provider'], 'grok')
                self.assertEqual(job['provider_requested'], 'auto')
                self.assertEqual(job['fallback_from'], 'codex')
                self.assertIn('codex ', job['fallback_reason'])
                self.assertEqual(job['writing_returned_model'], 'fixture-grok')
                log.assert_called_once_with(job['fallback_reason'])
                public = self.app.prompting.dispatch('GET', ['jobs',job['id']], {}, None)[1]
                self.assertEqual(public['fallback_reason'], job['fallback_reason'])
                draft = self.apply('video', record, job)
                self.assertEqual(draft['prompt_preparation']['writer'], 'grok')
                self.assertEqual(draft['prompt_preparation']['fallback_reason'], job['fallback_reason'])

    def test_sign_in_failure_falls_back_but_live_lock_does_not(self):
        def access(provider):
            if provider == 'codex':raise APIError('sign_in_required','Connect ChatGPT.')
        self.app.filmmaking.series.writing_access = Mock(side_effect=access)
        with patch('request_diagnostics.writing_fallback'):
            job = self.prepare('image', self.image())
        self.assertEqual(job['status'], 'done')
        self.assertEqual([call.args[0] for call in self.writer.call_args_list], ['grok'])
        self.assertIn('sign-in', job['fallback_reason'])
        self.writer.reset_mock()
        self.app.filmmaking.series.writing_access.side_effect = APIError('live_locked','Live requests are locked.')
        job = self.prepare('image', self.image())
        self.assertEqual(job['status'], 'error')
        self.assertIsNone(job['fallback_reason'])
        self.writer.assert_not_called()

    def test_explicit_provider_never_falls_back(self):
        record = self.video()
        job = self.prepare('video', record, provider='grok')
        self.assertEqual(job['status'], 'done')
        self.assertEqual(job['provider_requested'], 'explicit')
        self.assertEqual([call.args[0] for call in self.writer.call_args_list], ['grok'])
        self.writer.reset_mock()
        self.writer.side_effect = TimeoutError('ChatGPT timed out')
        job = self.prepare('video', self.video(), provider='codex')
        self.assertEqual(job['status'], 'error')
        self.assertEqual([call.args[0] for call in self.writer.call_args_list], ['codex'])
        self.assertIsNone(job['fallback_reason'])

    def test_no_same_provider_retry_or_fallback_on_invalid_output(self):
        self.writer.side_effect = [TimeoutError('ChatGPT timed out'), ValueError('Grok upstream error')]
        with patch('request_diagnostics.writing_fallback'):
            job = self.prepare('video', self.video())
        self.assertEqual(job['status'], 'error')
        self.assertEqual([call.args[0] for call in self.writer.call_args_list], ['codex','grok'])
        self.writer.reset_mock()
        self.writer.side_effect = None
        self.writer.return_value = dict(prompt='Malformed shape')
        job = self.prepare('video', self.video())
        self.assertEqual(job['status'], 'error')
        self.writer.assert_called_once()
        self.assertIsNone(job['fallback_reason'])

    def test_auto_cache_cannot_override_explicit_writer_choice(self):
        record = self.video()
        def write(provider, *args):
            if provider == 'codex':raise TimeoutError('ChatGPT timed out')
            return self.reply(provider,*args)
        self.writer.side_effect = write
        with patch('request_diagnostics.writing_fallback'):
            automatic = self.prepare('video',record)
        explicit = self.app.prompting.prepare('video',record['id'],
            dict(expected_revision=record['revision'],approved=True,provider='codex'),'explicit-separate-cache')
        self.assertNotEqual(automatic['id'], explicit['id'])
        self.assertEqual(explicit['status'], 'error')
        self.assertEqual(explicit['provider'], 'codex')


class ContinuityTests(MediaFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        p = self.app.productions
        self.production = p.dispatch('POST',[],dict(kind='story',title='Sample Adventure'))[1]['production']
        ep = self.app.stories.dispatch('POST',['episodes'],dict(series_id=self.production['series_id'],title='Episode 1'),None)[1]
        self.ep = self.app.stories.episode_edit(self.app.stories.record('episodes',ep['id']),
            dict(expected_revision=ep['revision'],scenes=[dict(title='Scene 2',text='Eve watches Mira.',
                standing_holds='Locked camera. GREENHOUSE sign stays behind Eve.'),dict(title='Other scene',text='Elsewhere.')]))
        sid = self.ep['scenes'][0]['id']
        def shot(title, order, **extra):
            with p.sql:
                value = p.create_shot(self.production,dict(episode_id=self.ep['id'],story_scene_id=sid,title=title))
                value.update(shot_order=order,story_direction=title+' direction',**extra)
                p.put('shot',value)
            video = self.app.agent.record(value['video_id'])
            self.app.agent.edit(video['id'],dict(expected_revision=video['revision'],scene={**video['scene'],'prompt':title+' saved prompt'}))
            return value
        self.early = shot('Early',1)
        self.previous = shot('Previous',2)
        self.archived = shot('Archived',3,archived=True)
        self.current = shot('Current',4)
        self.next = shot('Next',5)
        self.record = self.app.agent.record(self.current['video_id'])

    def test_previous_shot_and_standing_holds_are_compact_and_frozen(self):
        job = self.prepare('video',self.record)
        self.assertEqual(job['status'],'done',job.get('error'))
        context = self.writer.call_args.args[1]['creative_context']
        self.assertEqual(context['previous_shot'],dict(title='Previous',prompt='Previous saved prompt',story_direction='Previous direction'))
        self.assertEqual(context['scene_standing_holds'],self.ep['scenes'][0]['standing_holds'])
        self.assertNotIn('standing_holds',context['current_scene'])
        self.assertEqual(set(context['previous_shot']),{'title','prompt','story_direction'})
        frozen = self.app.productions.get(job['id'],'media-prompt-job')['context']['creative_context']
        prior = self.app.agent.record(self.previous['video_id'])
        self.app.agent.edit(prior['id'],dict(expected_revision=prior['revision'],scene={**prior['scene'],'prompt':'Changed ending'}))
        self.assertEqual(frozen['previous_shot']['prompt'],'Previous saved prompt')
        with self.assertRaisesRegex(APIError,'changed'):
            self.apply('video',self.record,job)

    def test_prior_end_state_direction_and_holds_invalidate_preparation(self):
        job = self.prepare('video',self.record)
        applied = self.apply('video',self.record,job)
        self.assertTrue(self.app.prompting.current('video',applied))
        with self.app.productions.sql:
            self.previous['story_direction']='Mira ends behind the box.'
            self.app.productions.put('shot',self.previous)
        self.assertFalse(self.app.prompting.current('video',applied))
        record = self.app.agent.record(applied['id'])
        job = self.app.prompting.prepare('video',record['id'],dict(expected_revision=record['revision'],approved=True),'fresh-continuity')
        applied = self.apply('video',record,job)
        self.assertTrue(self.app.prompting.current('video',applied))
        episode = self.app.stories.record('episodes',self.ep['id'])
        scenes = copy.deepcopy(episode['scenes']);scenes[0]['standing_holds']='Camera locked. Sparrow eyes closed.'
        self.app.stories.dispatch('PUT',['episodes',episode['id']],dict(expected_revision=episode['revision'],scenes=scenes),None)
        self.assertFalse(self.app.prompting.current('video',applied))

    def test_previous_selection_ignores_other_scene_and_reorders_and_archives(self):
        p = self.app.productions
        with p.sql:
            other = {**self.early,'id':'other-shot','video_id':self.app.agent.create(dict(scene=dict(prompt='Other scene.')))['id'],
                'story_scene_id':self.ep['scenes'][1]['id'],'shot_order':3}
            p.put('shot',other)
        self.assertEqual(self.app.prompting.dependencies('video',self.record)['previous_shot']['title'],'Previous')
        with p.sql:
            self.previous['archived']=True;p.put('shot',self.previous)
        self.assertEqual(self.app.prompting.dependencies('video',self.record)['previous_shot']['title'],'Early')
        first = self.app.agent.record(self.early['video_id'])
        self.assertNotIn('previous_shot',self.app.prompting.dependencies('video',first))

    def test_standing_holds_route_preserves_omitted_fields_and_validates_text(self):
        original = self.ep['scenes'][0]['standing_holds']
        episode = self.app.stories.record('episodes',self.ep['id'])
        scenes = [{k:v for k,v in scene.items() if k!='standing_holds'} for scene in episode['scenes']]
        saved = self.app.stories.dispatch('PUT',['episodes',episode['id']],dict(expected_revision=episode['revision'],scenes=scenes),None)[1]
        self.assertEqual(saved['scenes'][0]['standing_holds'],original)
        for value in (None,123,'x'*10001):
            invalid=copy.deepcopy(saved['scenes']);invalid[0]['standing_holds']=value
            with self.assertRaises(APIError):
                self.app.stories.dispatch('PUT',['episodes',saved['id']],dict(expected_revision=saved['revision'],scenes=invalid),None)
        cleared=copy.deepcopy(saved['scenes']);cleared[0]['standing_holds']=''
        self.app.stories.dispatch('PUT',['episodes',saved['id']],dict(expected_revision=saved['revision'],scenes=cleared),None)
        self.assertNotIn('scene_standing_holds',self.app.prompting.dependencies('video',self.record))
