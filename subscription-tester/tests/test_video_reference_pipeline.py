"""Offline end-to-end reference preparation, proof and generation preflight."""
import base64
import copy
import io
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image
from agent_api import APIError
from studio_server import Studio
import video_prompt_checks as checks


class VideoReferencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Studio(mock=True, storage=self.tmp.name)
        image = io.BytesIO()
        Image.new('RGB', (8, 8), 'black').save(image, format='PNG')
        self.png = base64.b64encode(image.getvalue()).decode()
        self.asset = self.app.upload(dict(name='Character sheet.png', data_url='data:image/png;base64,' + self.png))
        self.app.save_reference(dict(title='SampleHero', handle='SampleHero2', category='Character',
            description='Biography that must not reach the video engine.', images=[{'asset_id':self.asset['id']}]))
        production = self.app.productions.dispatch('POST', [], dict(kind='quick', title='Reference shot'))[1]
        self.shot = production['shots'][0]
        video = self.app.agent.record(self.shot['video_id'])
        scene = self.app.agent.attach(copy.deepcopy(video['scene']), ['SampleHero2'])
        scene.update(first=self.asset, prompt='@SampleHero2 turns toward Mark.', audio=True, duration=5)
        self.video = self.app.agent.edit(video['id'], dict(expected_revision=video['revision'], scene=scene))
        self.app.mock = False
        self.app.state['signed_in'] = True
        self.app.spawn = lambda fn, *args: fn(*args)
        self.app.filmmaking.series.writing_access = Mock()
        self.reply = dict(direction='0-5 s: @SampleHero2 turns toward Mark, holding his partner eyeline.',
            asset_summaries=[dict(handle='SampleHero2', summary='')], duration_seconds=5,
            duration_reason='One restrained reaction.', notes=[], starting_frame_observations=[], issues=[])
        self.app.filmmaking.request_plan = Mock(side_effect=lambda *args: copy.deepcopy(self.reply))

    def tearDown(self):
        self.app.productions.sql.close()
        self.tmp.cleanup()

    def prepare(self, key='reference-preparation', **data):
        shot = self.app.productions.get(self.shot['id'], 'shot')
        video = self.app.agent.record(shot['video_id'])
        return self.app.filmmaking.video_directions.prepare(shot['id'], dict(expected_revision=shot['revision'],
            expected_video_revision=video['revision'], approved=True, provider='codex', **data), key)

    def apply(self, job):
        video = self.app.agent.record(self.shot['video_id'])
        return self.app.filmmaking.video_directions.apply(self.shot['id'], dict(job_id=job['id'],
            expected_revision=job['revision'], expected_video_revision=video['revision'], replace_settings=True))['draft']

    def test_writer_sees_reference_mapping_and_provider_has_one_preservation_without_biography(self):
        job = self.prepare()
        self.assertEqual(job['status'], 'done', job.get('error'))
        context = self.app.filmmaking.request_plan.call_args.args[1]
        self.assertEqual(context['video_assets'][0]['image_tags'], ['<IMAGE_1>'])
        self.assertEqual([i['role'] for i in context['_visual_frames']], ['first frame', 'reference image'])
        draft = self.apply(job)
        request = self.app.resolve(self.app.agent.compile(draft['scene']))
        self.assertIn("Preserve SampleHero's exact appearance as shown in <IMAGE_1> throughout the shot.", request['prompt'])
        self.assertEqual(request['prompt'].count('exact appearance'), 1)
        self.assertNotIn('SampleHero2', request['prompt'])
        self.assertNotIn('Biography', request['prompt'])
        self.assertNotIn('Asset cues:', draft['scene']['prompt'])
        self.assertNotIn('video_summary', draft['scene']['named'][0])
        status = self.app.prompting.request_status(request, draft['id'], draft['scene'])
        self.assertTrue(status['prompt_preparation_current'])
        self.assertFalse(status['prompt_generation_blocked'])
        self.assertEqual(status['prompt_issues'], [])
        self.assertIsNone(status['prompt_preparation_message'])

    def test_unresolved_visual_conflict_is_reviewable_but_blocks_provider_submission(self):
        self.reply['issues'] = [dict(code='visual_conflict', severity='error',
            message='The requested open door conflicts with the pinned closed ending state. Correct the door instruction and use Prepare again.')]
        job = self.prepare()
        self.assertFalse(job['auto_apply'])
        draft = self.apply(job)
        body = self.app.resolve(self.app.agent.compile(draft['scene']))
        status = self.app.prompting.request_status(body, draft['id'], draft['scene'])
        self.assertTrue(status['prompt_preparation_current'])
        self.assertTrue(status['prompt_generation_blocked'])
        self.app.spawn = Mock()
        with self.assertRaisesRegex(APIError, 'door'):
            self.app.start_video(body, True)
        self.app.spawn.assert_not_called()

    def test_writing_failure_preserves_settings_and_records_reason_once(self):
        from story_studio import WritingError
        before=copy.deepcopy(self.app.agent.record(self.video['id']))
        self.app.filmmaking.request_plan.side_effect=WritingError(dict(message='Connection closed',
            codexErrorInfo={'responseStreamDisconnected':{'httpStatusCode':None}}),turn_id='failed-turn')
        job=self.prepare()
        self.assertEqual(job['status'],'error')
        self.assertIn('writing connection closed',job['error'])
        self.assertEqual(job['error'].count('preserved'),1)
        self.assertEqual(job['writing_error']['code'],'responseStreamDisconnected')
        self.assertEqual(job['writing_error']['turn_id'],'failed-turn')
        self.assertEqual(self.app.agent.record(self.video['id']),before)
        self.app.filmmaking.request_plan.assert_called_once()

    def test_legacy_failure_display_removes_duplicate_suffix_without_mutating_job(self):
        original=dict(id='old',status='error',error='Codex returned a writing error. No automatic retry was made. Your prompt is preserved; no automatic retry was made.')
        before=copy.deepcopy(original)
        public=self.app.filmmaking.video_directions.public(original)
        self.assertEqual(public['error'].lower().count('no automatic retry'),1)
        self.assertEqual(original,before)

    def test_browser_snapshot_is_validated_before_runtime_checks(self):
        draft=self.apply(self.prepare())
        body=self.app.resolve(self.app.agent.compile(draft['scene']))
        invalid={**draft['scene'],'duration':'12'}
        with self.assertRaisesRegex(APIError,'Duration must be an integer'):
            self.app.prompting.request_status(body,draft['id'],invalid)
        self.assertTrue(self.app.prompting.request_status(body,draft['id'],draft['scene'])['prompt_preparation_current'])

    def test_manual_prompt_submits_without_ai_and_keeps_exact_direction(self):
        draft=self.app.agent.record(self.video['id'])
        manual='0-5 s: @SampleHero2 turns toward Mark. Hold the reaction.'
        draft=self.app.agent.edit(draft['id'],dict(expected_revision=draft['revision'],scene={**draft['scene'],'prompt':manual}))
        settings=self.app.agent.compile(draft['scene'])
        self.app.spawn=Mock()
        self.app.start_video(settings,True)
        self.app.spawn.assert_called_once()
        self.app.filmmaking.request_plan.assert_not_called()
        self.assertEqual(self.app.agent.record(draft['id'])['scene']['prompt'],manual)

    def test_manual_prompt_still_rejects_action_beyond_duration(self):
        draft=self.app.agent.record(self.video['id'])
        settings=self.app.agent.compile({**draft['scene'],'prompt':'0-9 s: @SampleHero2 walks.'})
        self.app.spawn=Mock()
        with self.assertRaisesRegex(APIError,'outside the selected duration'):
            self.app.start_video(settings,True)
        self.app.spawn.assert_not_called()

    def test_reference_pixels_change_requires_new_preparation_even_if_ids_unchanged(self):
        draft = self.apply(self.prepare())
        _, path = self.app.asset(self.asset['id'])
        Image.new('RGB', (8, 8), 'gold').save(path, format='PNG')
        self.assertFalse(self.app.prompting.current('video', draft))
        self.assertIn('reference images', self.app.prompting.preparation_message('video', draft))

    def test_new_reference_inputs_keep_previous_human_corrections_as_history(self):
        first = self.prepare(instruction='Keep the left door closed and eyelines toward partners.')
        draft = self.apply(first)
        changed = copy.deepcopy(draft['scene'])
        changed['ratio'] = '4:3'
        self.app.agent.edit(draft['id'], dict(expected_revision=draft['revision'], scene=changed))
        second = self.prepare('reference-preparation-next', instruction='Use restrained acting.')
        self.assertEqual(second['status'], 'done', second.get('error'))
        previous = self.app.filmmaking.request_plan.call_args.args[1]['previous_preparation']
        self.assertIn('left door closed', previous['instruction'])
        self.assertTrue(previous['current_inputs_take_priority'])

    def test_last_frame_endpoint_allows_accepted_duration_recommendation(self):
        changed = copy.deepcopy(self.video['scene'])
        changed['last'] = self.asset
        self.video = self.app.agent.edit(self.video['id'], dict(expected_revision=self.video['revision'], scene=changed))
        self.reply.update(duration_seconds=12, direction='0-12 s: @SampleHero2 turns slowly toward Mark.')
        job = self.prepare()
        self.assertEqual(job['status'], 'done', job.get('error'))
        draft = self.apply(job)
        self.assertEqual(draft['scene']['duration'], 12)
        self.assertTrue(self.app.prompting.current('video', draft))

    def test_missing_binding_stops_preparation_before_writer(self):
        changed = copy.deepcopy(self.video['scene'])
        changed['refs'] = []
        self.app.agent.edit(self.video['id'], dict(expected_revision=self.video['revision'], scene=changed))
        with self.assertRaisesRegex(APIError, 'missing an attached image'):
            self.prepare()
        self.app.filmmaking.request_plan.assert_not_called()

    def test_identical_provider_request_cannot_borrow_another_shots_preparation(self):
        draft = self.apply(self.prepare())
        twin = self.app.agent.create(dict(scene=copy.deepcopy(draft['scene'])))
        context = self.app.prompting.context('video', twin, {})
        self.app.prompting.mark('video', self.app.agent.record(twin['id']), context, 'twin-preparation', 'fixture')
        draft = self.app.agent.record(draft['id'])
        draft['story_context'] = {'changed_script': 'A different required action.'}
        body = self.app.resolve(self.app.agent.compile(draft['scene']))
        status = self.app.prompting.request_status(body, draft['id'])
        self.assertFalse(status['prompt_preparation_current'])
        self.assertTrue(self.app.prompting.request_ready(body, twin['id']))
        self.assertFalse(self.app.prompting.request_ready(body, draft['id']))

    def test_visual_proof_is_required_and_unseen_collaborator_context_cannot_mark_ready(self):
        with self.assertRaisesRegex(APIError, 'current reference'):
            self.app.prompting.mark('video', self.app.agent.record(self.video['id']), {}, 'unseen', 'fixture')
        draft = self.apply(self.prepare())
        draft['prompt_preparation'].pop('visual_frames')
        self.assertFalse(self.app.prompting.current('video', draft))


class VideoPreflightTests(unittest.TestCase):
    def test_timing_and_audio_messages_are_conditional_and_do_not_guess_visual_facts(self):
        scene = dict(prompt='0-5 s: Mark opens the right door.\n5-8 s: Mark (delighted): "You wore it!"', duration=8, audio=True)
        self.assertEqual(checks.checks(scene), [])
        scene['audio'] = False
        issues = checks.checks(scene)
        self.assertEqual(issues[0]['code'], 'audio_disabled')
        self.assertFalse(checks.blocked(issues), 'An explicitly silent video remains possible.')
        scene['duration'] = 6
        self.assertTrue(checks.blocked(checks.checks(scene)))
        scene.update(prompt='Preserve the closed left door. No camera-facing dialogue.', duration=8)
        self.assertEqual(checks.checks(scene), [], 'No guessed door contradiction or generic audio warning.')

    def test_voice_tag_warning_for_authored_body_and_compiled_duplicates(self):
        header = 'Reference identities:\nVoice for Mira: <AUDIO_0>.'
        for prompt in ('Mira says hello using <AUDIO_0>.',
                       header + '\n\nMira says hello using <AUDIO_0>.',
                       header + '\nVoice for Ada: <AUDIO_0>.\n\nMira and Ada wait.'):
            issues = checks.checks(dict(prompt=prompt))
            self.assertEqual([i['code'] for i in issues], ['voice_tag_repeated'])
            self.assertFalse(checks.blocked(issues))
        for prompt in ('Mira says hello.', header + '\n\nMira says hello.'):
            self.assertEqual(checks.checks(dict(prompt=prompt)), [])

    def test_preset_name_warning_uses_attached_voices_and_exempts_asset_names(self):
        scene = dict(prompt='Mira speaks with URSA.', voices=[dict(voice='ursa')])
        self.assertEqual(checks.checks(scene)[0]['code'], 'voice_name_in_body')
        for prompt in ('Mira speaks.', 'Mira meets Ursaline.', 'Mira meets Eve.',
                       'Reference identities:\nVoice for Mira: <AUDIO_0>. Ursa\n\nMira speaks.'):
            self.assertEqual(checks.checks({**scene, 'prompt': prompt}), [])
        for title, handle, voice in [('Eve', 'Eve', 'eve'), ('Eve Foster', 'EveFoster', 'eve'),
                                     ('Ada', 'EveBot', 'eve')]:
            scene = dict(prompt=title+' waits beside EveBot.', refs=[dict(id='portrait')],
                voices=[dict(voice=voice)], named=[dict(title=title, handle=handle,
                category='Character', refIds=['portrait'])])
            self.assertEqual(checks.checks(scene), [], 'Character names must not be treated as voice instructions.')
        self.assertEqual(checks.checks(dict(prompt='Eve walks.', voices=[])), [])

    def test_character_direction_warning_accepts_any_name_or_handle_mention(self):
        scene = dict(prompt='The camera pans.', refs=[dict(id='portrait')], named=[
            dict(title='Mira', handle='MiraBot', category='Character', refIds=['portrait']),
            dict(title='Narrator', handle='Narrator', category='Character', refIds=[]),
            dict(title='Crate', handle='Crate', category='Prop', refIds=['portrait'])])
        issues = checks.checks(scene)
        self.assertEqual([i['code'] for i in issues], ['character_without_direction'])
        self.assertIn('Mira', issues[0]['message'])
        self.assertFalse(checks.blocked(issues))
        for prompt in ('Mira waits.', '@MiraBot holds still.', 'mira watches.'):
            self.assertEqual(checks.checks({**scene, 'prompt': prompt}), [])
        self.assertEqual(checks.checks({**scene, 'prompt':'Supernova glows.'})[0]['code'], 'character_without_direction')
        for line in ("Preserve Mira's exact appearance as shown in <IMAGE_0> throughout the shot.",
                     'Character: Mira (<IMAGE_0>).'):
            header = 'Reference identities:\n'+line+'\nVoice for Narrator: <AUDIO_0>.'
            self.assertEqual(checks.checks(dict(prompt=header+'\n\nThe camera pans.'))[0]['code'], 'character_without_direction')
            self.assertEqual(checks.checks(dict(prompt=header+'\n\nMira waits.')), [])

    def test_character_direction_accepts_unique_first_names_and_camelcase_handles(self):
        for title, handle in [('Eve Foster', 'EveFoster'), ('EveFoster', 'EveFoster')]:
            scene = dict(refs=[dict(id='portrait')], named=[dict(title=title,
                handle=handle, category='Character', refIds=['portrait'])])
            for prompt in ('Eve waits.', title+' watches Mira.', 'eve stays behind the box.'):
                self.assertEqual(checks.checks({**scene, 'prompt':prompt}), [], (title, prompt))
            self.assertEqual(checks.checks({**scene, 'prompt':'Evelina waits.'})[0]['code'],
                'character_without_direction', 'Partial-name matches still need whole words.')
        # Raw compiled prompts have display names in the header, without bindings.
        header = "Reference identities:\nPreserve EveFoster's exact appearance as shown in <IMAGE_0>.\n\n"
        self.assertEqual(checks.checks(dict(prompt=header+'Eve waits.')), [])
        scene = dict(refs=[dict(id='portrait')], named=[dict(title='The Al Robot Carter',
            handle='TheAlRobotCarter', category='Character', refIds=['portrait'])])
        for prompt in ('The robot waits behind the box.', 'Al waits.'):
            self.assertEqual(checks.checks({**scene, 'prompt':prompt})[0]['code'],
                'character_without_direction', 'Common words and words shorter than three letters are ignored.')
        self.assertEqual(checks.checks({**scene, 'prompt':'Carter waits.'})[0]['code'], 'character_without_direction')

    def test_shared_first_name_requires_full_names_or_handles(self):
        scene = dict(refs=[dict(id='carter'), dict(id='fox')], named=[
            dict(title='Eve Foster',handle='EveFoster',category='Character',refIds=['carter']),
            dict(title='Eve Fox',handle='LeoFox',category='Character',refIds=['fox'])])
        self.assertEqual(len(checks.checks({**scene, 'prompt':'Eve waits.'})), 2)
        issues = checks.checks({**scene, 'prompt':'Eve Foster waits.'})
        self.assertEqual(len(issues), 1)
        self.assertIn('Eve Fox', issues[0]['message'])
        self.assertEqual(checks.checks({**scene, 'prompt':'@EveFoster waits. Eve Fox watches.'}), [])
        self.assertEqual(len(checks.checks({**scene, 'prompt':'Nobody moves.'})), 2)
        # The preset exemption still applies even when a first name is ambiguous.
        self.assertEqual(checks.checks({**scene, 'voices':[dict(voice='eve')],
            'prompt':'Eve Foster and Eve Fox wait.'}), [])
        voice_only = copy.deepcopy(scene)
        voice_only['named'][1]['refIds'] = []
        issues = checks.checks({**voice_only, 'prompt':'Eve waits.'})
        self.assertEqual(len(issues), 1)
        self.assertIn('Eve Foster', issues[0]['message'])
        header = "Reference identities:\nPreserve Eve Foster's exact appearance as shown in <IMAGE_0>.\nPreserve Eve Fox's exact appearance as shown in <IMAGE_1>.\n\n"
        self.assertEqual(len(checks.checks(dict(prompt=header+'Eve waits.'))), 2)
        self.assertEqual(checks.checks(dict(prompt=header+'Eve Foster and Eve Fox wait.')), [])

    def test_runtime_warnings_are_recomputed_when_completed_proposals_are_applied(self):
        warning = checks.checks(dict(prompt='Use <AUDIO_0>.'))[0]
        self.assertEqual(checks.validated_issues([warning]), [])
        self.assertEqual(checks.checks(dict(prompt='Mira waits.'), checks.validated_issues([warning])), [])
        self.assertEqual(checks.checks(dict(prompt='Use <AUDIO_0>.'), checks.validated_issues([warning])), [warning])
        with self.assertRaisesRegex(ValueError, 'remain warnings'):
            checks.validated_issues([{**warning, 'severity':'error'}])
        # The twelve-item limit still covers writer conflicts, not recomputed warnings.
        self.assertEqual(checks.validated_issues([warning] * 13), [])

    def test_summary_compatibility_never_appends_an_old_image_description(self):
        scene = dict(named=[dict(handle='SampleHero2', refIds=['ref'], video_summary='Gold boots.')], refs=[dict(id='ref')])
        state = checks.apply_summaries(scene, [dict(handle='SampleHero2', summary='Legacy incorrect gold boots.')])
        self.assertNotIn('video_summary', state['named'][0])
        self.assertEqual(scene['named'][0]['video_summary'], 'Gold boots.')


if __name__ == '__main__':
    unittest.main()
