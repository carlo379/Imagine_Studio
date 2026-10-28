"""Guide routing, writer caching and preparation/render boundaries. No live calls."""
import copy
import base64
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

from agent_api import APIError
from studio_server import Studio, StudioHandler
import prompt_guides as guides
import story_studio
from media_prompting import SCHEMA, VIDEO_SCHEMA, POLICY, video_inputs


class GuideTests(unittest.TestCase):
    def test_chronological_video_policy_all_writer_paths(self):
        for model in ('grok-imagine-video-1.5','grok-imagine-video-1.5-lite'):
            context=guides.capture({},[dict(model=model,fields=['prompt'])])
            for task in ('preparation','review','refinement','storyboard planning'):
                _,policy=guides.instructions(context,task)
                self.assertIn('Never write timestamp ranges or timed action blocks',policy)
                self.assertIn('List every action and event in the order it must happen',policy)
                self.assertIn('Evidence timestamps in review findings',policy)
        _,image_policy=guides.instructions(guides.capture({},[dict(model='gpt-image-2',fields=['prompt'])]),'still')
        self.assertNotIn(guides.VIDEO_AUTHORING_POLICY,image_policy)

    def test_complete_applicable_guide_independent_of_writer(self):
        for model,filename in guides.GUIDES.items():
            for writer in ('codex','grok'):
                context=guides.capture(dict(scene='A discovery.',writer=writer),[dict(model=model,fields=['prompt'])])
                payload,policy=guides.instructions(context,'Return the exact schema.')
                self.assertNotIn('_prompt_guides',payload)
                self.assertEqual(payload['media_authoring_targets'][0]['model'],model)
                source=(guides.GUIDE_DIR/filename).read_text()
                self.assertEqual(policy.count(source),1)
                self.assertEqual(len(guides.provenance(context)['guides']),1)
                self.assertNotIn('text',guides.provenance(context)['guides'][0])
        with self.assertRaises(ValueError):guides.load('grok-imagine-video')

    def test_video_rules_reach_full_and_lite_writers(self):
        rules = (
            'Agents that write prompts directly, without the built-in writer, follow this same guide.',
            'The app runs the same checks on their prompts.',
            "Hold everything you don't mention.",
            'Describe the body, not the idea.',
            'One clear action per moment.',
            'Anything within reach gets touched, and a touched character reacts.',
            'Name the exact visible state.',
            "Carry forward the previous shot's end state and the scene's standing holds unless the direction changes them.",
            "Add nothing that wasn't asked for.",
            'The camera stays locked unless the direction asks for a move.',
            'When a beat fails twice, change the shot, not the words.',
            'Write like a director giving a quick shot note to an animator.',
            'Describe each action in order: who does it, to what, and how it ends.',
            'Mention hand contact only when it matters to the story.',
            'Put any remaining must-avoid items in one short closing line.',
            'In the body, refer to the speaker by name only.',
            'Never repeat `<AUDIO_n>` tags or preset voice names such as Ursa or Eve in the body.',
            'An off-screen performer stays unseen.',
            "Keep the listener's mouth, lips, jaw and visor still.",
            'A mouthless robot stays mouthless.',
            'There is no beat-count limit or prompt length target.',
            'Report an overloaded shot rather than removing events or splitting it.',
            'State each fact or constraint once, where it applies.',
            'Before returning, delete any sentence that repeats an earlier one.',
        )
        for model in ('grok-imagine-video-1.5', 'grok-imagine-video-1.5-lite'):
            context = guides.capture({}, [dict(model=model, fields=['prompt'])])
            _, policy = guides.instructions(context, 'Return the exact schema.')
            source = context['_prompt_guides']['guides'][0]['text']
            for rule in rules:
                self.assertIn(rule, guides.VIDEO_AUTHORING_POLICY)
                self.assertIn(rule, policy)

    def test_replacement_guide_is_loaded_verbatim_for_both_video_models(self):
        filename = 'Grok_Imagine_Prompting_Guide.md'
        original = (guides.GUIDE_DIR / filename).read_text()
        for model in ('grok-imagine-video-1.5', 'grok-imagine-video-1.5-lite'):
            loaded = guides.load(model)
            self.assertEqual(loaded['file'], filename)
            self.assertEqual(loaded['text'], original)
            context = guides.capture({}, [dict(model=model, fields=['prompt'])])
            _, policy = guides.instructions(context, 'Return the exact schema.')
            self.assertEqual(policy.count(original), 1)
        self.assertNotIn('/workspace/', original)
        self.assertNotIn('my own practical extensions', original)
        self.assertIn('https://x.com/imagine/article/2115214583983935517', original)
        self.assertIn('Items marked (inferred) are practical extensions', original)
        self.assertIn('Always write video prompts in the 7-block format', original)
        self.assertIn('main source of truth', original)
        self.assertIn('## Standing rules (always apply)', original)
        self.assertIn('## The 7-block video prompt', original)
        for header in ('[Camera & Style]', '[Subject Motion / Action]',
                       '[Environment & Atmosphere]', '[Physics & Details]',
                       '[Audio]', '[SFX]', '[Restrictions]'):
            self.assertIn(header, original)
        self.assertEqual(guides.VIDEO_AUTHORING_POLICY.count("Hold everything you don't mention."), 1)

    def test_loader_uses_exact_filenames_despite_resource_forks(self):
        filename = guides.GUIDES['grok-imagine-video-1.5']
        source = (guides.GUIDE_DIR / filename).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / filename).write_text(source)
            (root / ('._' + filename)).write_text('Resource fork, never authoring instructions.')
            (root / 'unused-guide.md').write_text('Obsolete instructions.')
            with patch.object(guides, 'GUIDE_DIR', root):
                for model in ('grok-imagine-video-1.5', 'grok-imagine-video-1.5-lite'):
                    loaded = guides.load(model)
                    self.assertEqual(loaded['file'], filename)
                    self.assertEqual(loaded['text'], source)
                (root / filename).unlink()
                with self.assertRaisesRegex(ValueError, 'required prompting guide is unavailable'):
                    guides.load('grok-imagine-video-1.5')

    def test_prefix_and_cache_group_stable_across_shots_and_change_with_guide(self):
        a=guides.capture({'scene':'One'},[dict(model='gpt-image-2',fields=['prompt'])])
        b=guides.capture({'scene':'Two'},[dict(model='gpt-image-2',fields=['prompt'])])
        _,first=guides.instructions(a,POLICY);_,second=guides.instructions(b,POLICY)
        self.assertEqual(first,second)
        key=guides.cache_group('/workspace-a','grok-4.7',first,SCHEMA)
        self.assertEqual(key,guides.cache_group('/workspace-a','grok-4.7',second,SCHEMA))
        self.assertNotEqual(key,guides.cache_group('/workspace-b','grok-4.7',second,SCHEMA))
        b['_prompt_guides']['guides'][0]['text']+='\nNew guidance.'
        _,changed=guides.instructions(b,POLICY)
        self.assertNotEqual(key,guides.cache_group('/workspace-a','grok-4.7',changed,SCHEMA))

    def test_absent_usage_is_unknown_and_zero_is_preserved(self):
        self.assertIsNone(guides.usage_counts(None)['cached_input_tokens'])
        self.assertEqual(guides.usage_counts({'prompt_tokens_details':{'cached_tokens':0}})['cached_input_tokens'],0)
        self.assertIsNone(guides.usage_counts({'prompt_tokens_details':{'cached_tokens':True}})['cached_input_tokens'])

    def test_codex_guides_sent_once_and_native_cache_usage_parsed(self):
        calls=[]
        class RPC:
            def __init__(self,**kwargs):
                self.events=iter([dict(method='thread/tokenUsage/updated',params=dict(tokenUsage=dict(last=dict(inputTokens=100,cachedInputTokens=60,cacheWriteInputTokens=20,outputTokens=8)))),
                    dict(method='item/completed',params=dict(item=dict(type='agentMessage',text=json.dumps(dict(prompt='A still frame.',notes=[]))))),
                    dict(method='turn/completed',params=dict(turn=dict(status='completed')))])
            def account(self):return {'signed_in':True}
            def rpc(self,method,data):
                calls.append((method,data));return {'thread':{'id':'test-thread'}} if method=='thread/start' else {}
            def receive(self):return next(self.events)
            def close(self):pass
        context=guides.capture({'brief':'A still'},[dict(model='gpt-image-2',fields=['prompt'])])
        with patch.object(story_studio.openai_images,'CodexRPC',RPC):
            result=story_studio.writing_reply(context,SCHEMA,POLICY)
        thread=next(v for m,v in calls if m=='thread/start');turn=next(v for m,v in calls if m=='turn/start')
        source=guides.load('gpt-image-2')['text']
        self.assertEqual(thread['developerInstructions'].count(source),1)
        self.assertNotIn(source,thread['baseInstructions'])
        self.assertNotIn('_prompt_guides',json.loads(turn['input'][0]['text']))
        self.assertNotIn('prompt_cache_key',turn)
        self.assertEqual(result.usage['cached_input_tokens'],60)
        self.assertEqual(result.usage['cache_write_input_tokens'],20)
        self.assertEqual(set(result),{'prompt','notes'})

    def test_grok_reuses_stable_header_and_prefix_and_records_real_response_fields(self):
        with tempfile.TemporaryDirectory() as root:
            app=Studio(mock=True,storage=root)
            try:
                body=dict(model='grok-returned-model',choices=[dict(message=dict(content=json.dumps(dict(prompt='Prepared.',notes=[]))))],
                    usage=dict(prompt_tokens=100,completion_tokens=12,prompt_tokens_details=dict(cached_tokens=75)))
                response=Mock(status_code=200);response.json.return_value=body
                with patch('studio_server.oauth_headers',return_value={'Authorization':'Bearer fixture-only'}),patch('httpx.Client') as client:
                    post=client.return_value.__enter__.return_value.post;post.return_value=response
                    for brief in ('First shot','Second shot'):
                        context=guides.capture(dict(brief=brief),[dict(model='gpt-image-2.5-flare',fields=['prompt'])])
                        result=app.filmmaking.request_plan('grok',context,SCHEMA,POLICY)
                        self.assertEqual(result.usage['cached_input_tokens'],75)
                        self.assertEqual(result.returned_model,'grok-returned-model')
                    first,second=[c.kwargs for c in post.call_args_list]
                    self.assertEqual(first['headers']['x-grok-conv-id'],second['headers']['x-grok-conv-id'])
                    self.assertEqual(first['json']['messages'][0],second['json']['messages'][0])
                    self.assertNotEqual(first['json']['messages'][1],second['json']['messages'][1])
                    source=guides.load('gpt-image-2.5-flare')['text']
                    self.assertEqual(first['json']['messages'][0]['content'].count(source),1)
                    self.assertEqual(first['json']['response_format']['json_schema']['schema'],SCHEMA)
                    self.assertNotIn('prompt_cache_key',first['json'])
            finally:app.productions.sql.close()


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        pixels=io.BytesIO();Image.new('RGB',(24,16),'red').save(pixels,format='PNG')
        self.pixel=self.app.upload(dict(name='Offline reference.png',
            data_url='data:image/png;base64,'+base64.b64encode(pixels.getvalue()).decode()))
        self.app.spawn=lambda fn,*args:fn(*args)
        self.app.mock=False;self.app.state['signed_in']=True
        self.app.images.account_status=Mock(return_value={'subscription':{'signed_in':True}})
        self.writer=Mock(side_effect=self.reply)
        self.app.filmmaking.request_plan=self.writer
    def tearDown(self):
        self.app.productions.sql.close();self.tmp.cleanup()
    def reply(self,provider,context,schema,policy,**kwargs):
        result=dict(prompt='AI-authored direction. '+context.get('brief','A still.'),notes=[])
        if 'starting_frame_observations' in schema['properties']:result['starting_frame_observations']=[]
        if 'asset_summaries' in schema['properties']:
            result['asset_summaries']=[dict(handle=n['handle'],summary=n['title']+' keeps its canonical appearance.') for n in context['settings']['named']]
        return guides.WritingResult(result,dict(prompt_tokens=100,prompt_tokens_details={'cached_tokens':50}),12,'fixture-writer')
    def image(self,model='grok-imagine-image-2.0',**settings):
        return self.app.images.create(dict(title='A frame',settings=dict(model=model,prompt='An illustrated frame.',**settings)))
    def prepare(self,kind,record,**data):
        return self.app.prompting.prepare(kind,record['id'],dict(expected_revision=record['revision'],approved=True,**data),'prepare-'+record['id'])
    def apply(self,kind,record,job,**data):
        return self.app.prompting.apply(kind,record['id'],dict(job_id=job['id'],expected_revision=job['revision'],expected_media_revision=record['revision'],**data))['draft']

    def test_all_image_models_both_writers_and_reviewed_user_edit(self):
        for model in [m for m in guides.GUIDES if 'image' in m]:
            for provider in ('codex','grok'):
                draft=self.image(model);before=copy.deepcopy(draft['settings'])
                job=self.prepare('image',draft,provider=provider,instruction='Keep the lighting warm.')
                self.assertEqual(job['status'],'done')
                self.assertEqual(self.app.images.draft(draft['id'])['settings'],before)
                final=self.apply('image',draft,job,prompt=job['result']['prompt']+' Preserve the held red cup.')
                self.assertTrue(self.app.prompting.current('image',final))
                self.assertTrue(final['prompt_preparation']['user_edited'])
                self.assertEqual(final['prompt_preparation']['writer'],provider)
                self.assertEqual(final['prompt_preparation']['instruction'],'Keep the lighting warm.')
                self.assertEqual(final['prompt_preparation']['guides'][0]['file'],guides.GUIDES[model])
                self.assertEqual(job['writing_usage']['cached_input_tokens'],50)
                self.assertEqual({k:v for k,v in final['settings'].items() if k!='prompt'},{k:v for k,v in before.items() if k!='prompt'})

    def test_image_model_switch_keeps_existing_review_and_creative_inputs(self):
        draft=self.image();job=self.prepare('image',draft)
        final=self.apply('image',draft,job,prompt='My exact reviewed prompt. Keep the red cup.')
        # Emulate a saved review from before rendering settings were excluded.
        stored=self.app.images.draft(final['id'])
        stored['prompt_preparation']['authoring_fingerprint']=guides.digest(self.app.prompting.basis('image',stored))
        stored['prompt_preparation']['basis_components']={group:{key:guides.digest(value) for key,value in values.items()} for group,values in self.app.prompting.basis('image',stored).items()}
        original=copy.deepcopy(stored['prompt_preparation'])
        for model,resolution in [('grok-imagine-image-2.0','1k'),('gpt-image-2','auto')]:
            changed=self.app.images.edit(stored['id'],dict(expected_revision=stored['revision'],settings={**stored['settings'], 'model':model,'resolution':resolution,'quality':'auto'}))
            self.assertTrue(self.app.prompting.current('image',changed))
            self.assertEqual(changed['settings']['prompt'],final['settings']['prompt'])
            self.assertEqual(changed['prompt_preparation'],original)
            stored=self.app.images.draft(stored['id'])
        changed=copy.deepcopy(stored);changed['settings']['prompt']+=' Changed.'
        self.assertFalse(self.app.prompting.current('image',changed))
        changed=copy.deepcopy(stored);changed['settings']['extras'].append({'asset_id':self.pixel['id']})
        self.assertFalse(self.app.prompting.current('image',changed))
        self.writer.assert_called_once()

    def test_generation_requires_preparation_and_sends_reviewed_prompt_exactly(self):
        draft=self.image(resolution='1.5k');self.app.spawn=Mock()
        with self.assertRaisesRegex(APIError,'Prepare and review'):
            self.app.images.generate(draft['id'],dict(expected_revision=draft['revision'],approved=True),'render-unprepared')
        self.app.spawn.assert_not_called();self.assertEqual(self.app.images.db['jobs'],[])
        self.app.spawn=lambda fn,*args:fn(*args)
        job=self.prepare('image',draft);final=self.apply('image',draft,job)
        self.app.spawn=Mock()
        rendered=self.app.images.generate(final['id'],dict(expected_revision=final['revision'],approved=True),'render-prepared')
        self.assertEqual(rendered['expanded_prompt'],self.app.images.expanded_prompt(final['settings'])[0])
        self.assertEqual(rendered['draft']['settings']['resolution'],'1.5k')
        self.assertEqual(rendered['draft']['prompt_preparation']['job_id'],job['id'])
        self.app.spawn.assert_called_once()

    def test_setting_or_prompt_changes_invalidate_preparation_but_titles_do_not(self):
        draft=self.image();job=self.prepare('image',draft);final=self.apply('image',draft,job)
        renamed=self.app.images.edit(final['id'],dict(expected_revision=final['revision'],title='Renamed'))
        self.assertTrue(self.app.prompting.current('image',renamed))
        changed=self.app.images.edit(final['id'],dict(expected_revision=renamed['revision'],settings={**renamed['settings'],'ratio':'1:1','prompt':renamed['settings']['prompt']+' Changed.'}))
        self.assertFalse(self.app.prompting.current('image',changed))
        self.assertFalse(self.app.images.validate(changed)['prompt_preparation_current'])

    def test_edits_during_writing_and_failures_preserve_draft(self):
        draft=self.image();job=self.prepare('image',draft)
        changed=self.app.images.edit(draft['id'],dict(expected_revision=draft['revision'],settings={**draft['settings'],'prompt':'My newer direction.'}))
        with self.assertRaises(APIError):self.apply('image',changed,job)
        self.assertEqual(self.app.images.draft(draft['id'])['settings']['prompt'],'My newer direction.')
        self.writer.side_effect=ValueError('Fixture writing failure')
        failed=self.app.prompting.prepare('image',changed['id'],dict(expected_revision=changed['revision'],approved=True),'failure-'+changed['id'])
        self.assertEqual(failed['status'],'error');self.assertIn('no automatic retry',failed['error'])
        self.assertEqual(self.app.images.draft(draft['id'])['settings']['prompt'],'My newer direction.')

    def test_guide_snapshot_frozen_but_changed_guide_cannot_be_applied_or_rendered(self):
        draft=self.image();job=self.prepare('image',draft)
        stored=self.app.productions.get(job['id'],'media-prompt-job');original=stored['context']['_prompt_guides']['guides'][0]['text']
        with tempfile.TemporaryDirectory() as folder:
            filename=guides.GUIDES[draft['settings']['model']];Path(folder,filename).write_text(original+'\nA correction.')
            with patch.object(guides,'GUIDE_DIR',Path(folder)):
                self.assertEqual(stored['context']['_prompt_guides']['guides'][0]['text'],original)
                with self.assertRaisesRegex(APIError,'guide'):self.apply('image',draft,job)
        final=self.apply('image',draft,job)
        with patch.object(guides,'GUIDE_DIR',Path(self.tmp.name)/'missing'):
            self.assertFalse(self.app.prompting.current('image',final))
            with self.assertRaisesRegex(APIError,'Prepare and review'):self.app.prompting.require('image',final)

    def test_idempotency_returns_same_job_without_another_writing_call(self):
        draft=self.image();first=self.prepare('image',draft);second=self.prepare('image',draft)
        self.assertEqual(first['id'],second['id']);self.writer.assert_called_once()
        with self.assertRaises(APIError):self.prepare('image',draft,instruction='A different request')

    def test_identical_drafts_have_separate_review_jobs(self):
        first=self.image();second=self.image()
        a=self.prepare('image',first);b=self.prepare('image',second)
        self.assertNotEqual(a['id'],b['id']);self.assertEqual(b['media_id'],second['id'])
        self.assertTrue(self.app.prompting.current('image',self.apply('image',second,b)))

    def test_shot_authoring_paths_route_full_guides_for_the_actual_targets(self):
        out=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Scene'))[1]
        shot=out['shots'][0];pid=out['production']['id']
        image=self.app.images.draft(shot['image_id']);video=self.app.agent.record(shot['video_id'])
        image=self.app.images.edit(image['id'],dict(expected_revision=image['revision'],settings={**image['settings'],'model':'gpt-image-2.5-sunburst','quality':'low','resolution':'auto','prompt':'Opening brief.'}))
        video=self.app.agent.edit(video['id'],dict(expected_revision=video['revision'],scene={**video['scene'],'model':'grok-imagine-video-1.5-lite','prompt':'Video brief.'}))
        opening,*_=self.app.filmmaking.opening_frames.source(shot,image,video)
        direction,*_=self.app.filmmaking.video_directions.source(shot,video)
        creative=self.app.creative.context(dict(production_id=pid,scope='shot',stage='generate',shot_id=shot['id']))
        self.assertEqual(guides.provenance(opening)['targets'][0]['model'],'gpt-image-2.5-sunburst')
        self.assertEqual(guides.provenance(direction)['targets'][0]['model'],'grok-imagine-video-1.5-lite')
        self.assertEqual({t['model'] for t in guides.provenance(creative)['targets']},{'gpt-image-2.5-sunburst','grok-imagine-video-1.5-lite'})
        for context in (opening,direction,creative):
            _,policy=guides.instructions(context,'Return the caller schema.')
            for guide in context['_prompt_guides']['guides']:self.assertEqual(policy.count(guide['text']),1)
        planning=guides.planning(dict(production=out['production'],episode=dict(title='Episode'),series_bible=dict(answers={},guide={}),
            questionnaire={},guide={},source_script='INT. WORKSHOP - DAY',source_scenes=[dict(title='Workshop')],allow_dialogue_polish=False,dialogue_units=[],asset_catalog=[]))
        projected=self.app.filmmaking.series.completion.provider_context(planning)
        self.assertEqual(guides.provenance(projected),guides.provenance(planning))

    def test_actual_source_order_and_archived_bound_snapshot_preserved(self):
        ref=self.app.save_reference(dict(title='Hero',handle='Hero',description='Red coat.',category='Character',voice=None,images=[{'url':'https://example.com/hero.png'}]))
        draft=self.app.images.create(dict(title='Refinement',settings=dict(prompt='Change the sky; preserve @Hero.',base={'url':'https://example.com/base.png'},extras=[{'url':'https://example.com/style.png'}]),named_references=['Hero']))
        job=self.prepare('image',draft);context=self.writer.call_args.args[1]
        self.assertEqual([r['image_number'] for r in context['reference_mapping']],[1,2,3])
        self.assertEqual(context['reference_mapping'][0]['role'],'base image to refine')
        self.assertEqual(context['reference_mapping'][1]['handle'],'Hero')
        final=self.apply('image',draft,job);self.app.archive_reference(ref['id'],True)
        self.assertTrue(self.app.prompting.current('image',final))
        self.assertEqual(final['settings']['bindings'][0]['snapshot']['description'],'Red coat.')

    def test_both_video_models_allow_manual_submission_and_optional_preparation(self):
        for model in ('grok-imagine-video-1.5','grok-imagine-video-1.5-lite'):
            scene=self.app.agent.create(dict(scene=dict(model=model,prompt='Lena says: "Keep the red cup."')))
            self.app.spawn=Mock()
            self.app.start_video(self.app.agent.compile(scene['scene']),True)
            self.app.spawn.assert_called_once()
            self.app.state['phase']='ready'
            self.app.spawn=lambda fn,*args:fn(*args)
            job=self.prepare('video',scene,provider='codex');final=self.apply('video',scene,job)
            self.assertIn('"Keep the red cup."',final['scene']['prompt'])
            self.assertTrue(self.app.prompting.current('video',final))
            self.assertTrue(self.app.prompting.request_ready(self.app.resolve(self.app.agent.compile(final['scene']))))
            edited=self.app.agent.edit(final['id'],dict(expected_revision=final['revision'],scene={**final['scene'],'duration':6}))
            self.assertFalse(self.app.prompting.current('video',edited))

    def test_voice_and_pin_roles_are_actual_order_and_invalid_tags_rejected(self):
        names=[]
        for name,voice in [('Lena','luna'),('Milo','orion'),('Ada','iris')]:
            self.app.save_reference(dict(title=name,handle=name,description='Canonical '+name,category='Character',voice=voice,images=[{'asset_id':self.pixel['id']}]));names.append(name)
        scene=self.app.agent.create(dict(scene=dict(prompt='Lena speaks first.',resolution='720p',first=self.pixel,last=self.pixel,keys=[dict(id='anchor',source=self.pixel,slot=3)]),named_references=names))
        inputs=video_inputs(scene['scene'])
        self.assertEqual([v['speaker']['handle'] for v in inputs['voices']],names)
        self.assertEqual([v['tag'] for v in inputs['voices']],['<AUDIO_0>','<AUDIO_1>','<AUDIO_2>'])
        self.assertEqual(inputs['images'][1]['tag'],'<IMAGE_1>')
        self.assertIsNone(inputs['last_frame']['prompt_tag']);self.assertEqual(inputs['keyframes'][0]['time_seconds'],1)
        job=self.prepare('video',scene);self.assertEqual(job['status'],'done')
        final=self.apply('video',scene,job);expanded=self.app.agent.expanded_prompt(final['scene'])
        self.assertEqual(expanded.count('Lena keeps its canonical appearance.'),0)
        bad=dict(prompt='Use <AUDIO_3>.',notes=[],asset_summaries=job['result']['asset_summaries'],starting_frame_observations=[])
        with self.assertRaisesRegex(ValueError,'unattached'):self.app.prompting.validate('video',scene['scene'],bad)

    def test_resolution_only_changes_preserve_new_and_existing_video_approval(self):
        for model in ('grok-imagine-video-1.5','grok-imagine-video-1.5-lite'):
            for legacy in (False, True):
                scene=self.app.agent.create(dict(scene=dict(model=model,prompt='Walk slowly.',resolution='480p')))
                final=self.apply('video',scene,self.prepare('video',scene))
                if legacy:
                    proof=self.app.agent.record(final['id'])['prompt_preparation']
                    for key in ('authoring_fingerprint','basis_components','request_authoring_fingerprint'):
                        proof.pop(key)
                prepared_prompt=final['scene']['prompt'];calls=self.writer.call_count
                for resolution in ('720p','1080p','480p'):
                    final=self.app.agent.edit(final['id'],dict(expected_revision=final['revision'],scene={**final['scene'],'resolution':resolution}))
                    validation=self.app.agent.validation(final)
                    self.assertTrue(validation['valid'])
                    self.assertTrue(validation['prompt_preparation_current'])
                    self.assertIsNone(validation['prompt_preparation_message'])
                    self.assertTrue(self.app.prompting.request_ready(validation['request']))
                    self.assertIsNone(self.app.prompting.request_status(validation['request'],final['id'])['prompt_preparation_message'])
                    forged={**validation['request'],'prompt':'Unreviewed replacement.'}
                    self.assertFalse(self.app.prompting.request_ready(forged))
                    self.assertEqual(final['scene']['prompt'],prepared_prompt)
                self.assertEqual(self.writer.call_count,calls)

    def test_creative_changes_track_optional_preparation_without_blocking_manual_requests(self):
        scene=self.app.agent.create(dict(scene=dict(prompt='Walk slowly.')))
        final=self.apply('video',scene,self.prepare('video',scene))
        for field,value,label in (
                ('duration',6,'duration'),('prompt','Run quickly.','prompt text'),
                ('model','grok-imagine-video-1.5-lite','video model'),('ratio','9:16','aspect ratio'),
                ('audio',False,'audio setting'),('first',self.pixel,'first frame'),
                ('last',self.pixel,'last frame'),
                ('refs',[{'id':'ref','source':self.pixel}],'reference images'),
                ('keys',[{'id':'key','source':self.pixel,'slot':3}],'keyframes'),
                ('voices',[{'id':'voice','voice':'luna'}],'voice references')):
            changed=copy.deepcopy(final);changed['scene'][field]=value
            self.assertFalse(self.app.prompting.current('video',changed))
            self.assertIn(label,self.app.prompting.preparation_message('video',changed))
        changed=self.app.agent.edit(final['id'],dict(expected_revision=final['revision'],scene={**final['scene'],'duration':6,'resolution':'720p'}))
        validation=self.app.agent.validation(changed)
        self.assertTrue(validation['valid']);self.assertFalse(validation['prompt_preparation_current'])
        self.assertIsNone(validation['prompt_preparation_message'])
        self.assertFalse(self.app.prompting.request_ready(validation['request']))
        self.assertIsNone(self.app.prompting.request_status(validation['request'],changed['id'])['prompt_preparation_message'])
        self.app.spawn=Mock()
        self.app.start_video(self.app.agent.compile(changed['scene']),True)
        self.app.spawn.assert_called_once()
        with patch.object(self.app.prompting,'dependencies',return_value={'script':'Changed script'}):
            self.assertIn('script or creative context',self.app.prompting.preparation_message('video',final))
        with patch.object(guides,'current_versions',return_value=False):
            self.assertIn('guide changed',self.app.prompting.preparation_message('video',final))

    def test_resolution_exemption_cannot_bypass_reference_workflow_limits(self):
        scene=self.app.agent.create(dict(scene=dict(prompt='Walk slowly.',refs=[{'id':'ref','source':self.pixel}])))
        final=self.apply('video',scene,self.prepare('video',scene))
        valid=self.app.agent.edit(final['id'],dict(expected_revision=final['revision'],scene={**final['scene'],'resolution':'720p'}))
        self.assertTrue(self.app.agent.validation(valid)['valid'])
        body=self.app.resolve(self.app.agent.compile(valid['scene']));body['resolution']='1080p'
        self.app.spawn=Mock()
        with self.assertRaisesRegex(ValueError,'720p'):
            self.app.start_video(body,True)
        self.app.spawn.assert_not_called()

    def test_image_identity_summary_is_not_appended_and_reviewed_action_stays_editable(self):
        self.app.save_reference(dict(title='Hero',handle='Hero',description='Red coat.',category='Character',images=[{'asset_id':self.pixel['id']}]))
        scene=self.app.agent.create(dict(scene=dict(prompt='@Hero holds the red cup.'),named_references=['Hero']))
        job=self.prepare('video',scene)
        self.assertNotIn('Asset cues:',job['result']['prompt'])
        final=self.apply('video',scene,job,prompt=job['result']['prompt'].replace('red cup','blue cup'))
        expanded=self.app.agent.expanded_prompt(final['scene'])
        self.assertIn('blue cup',expanded)
        self.assertEqual(expanded.count('exact appearance as shown in <IMAGE_0>'),1)
        self.assertNotIn('canonical appearance',expanded)

    def test_mock_is_labeled_and_never_calls_writer(self):
        self.app.mock=True;draft=self.image();job=self.prepare('image',draft)
        self.writer.assert_not_called();self.assertIn('No AI interpretation',job['result']['prompt'])
        self.assertIsNone(job['writing_usage']['cached_input_tokens'])


class PromptHTTPTests(unittest.TestCase):
    def test_served_module_and_revision_checked_prepare_review_apply_workflow(self):
        from agent_client import AgentError, StudioClient
        from urllib.request import Request, urlopen
        from workspace_accounts import WorkspaceAccounts
        with tempfile.TemporaryDirectory(prefix='imagine-prompt-test-') as root:
            app=Studio(mock=True,storage=root);app.mock=False;app.spawn=lambda fn,*args:fn(*args)
            app.images.account_status=Mock(return_value={'subscription':{'signed_in':True}})
            app.filmmaking.request_plan=Mock(return_value=dict(prompt='AI fixture with the reviewed red cup.',notes=[]))
            accounts=WorkspaceAccounts(app,mock_identity=True)
            server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);server.tester=app;server.accounts=accounts
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                origin='http://127.0.0.1:'+str(server.server_port);client=StudioClient(origin,app.storage/'agent-token')
                for path,mime in (('/static/media-prompting.js','text/javascript'),('/static/media-prompting.css','text/css')):
                    with urlopen(Request(origin+path,headers={'Authorization':'Bearer '+client.token})) as response:
                        self.assertEqual(response.status,200);self.assertEqual(response.headers.get_content_type(),mime)
                        self.assertTrue(response.read())
                record=client.request('image-studio/drafts','POST',dict(title='A frame',settings=dict(prompt='A cup.')))
                with self.assertRaises(AgentError) as rejected:
                    client.request('image-studio/drafts/'+record['id']+'/generate','POST',dict(expected_revision=record['revision'],approved=True),'http-render-unprepared')
                self.assertEqual(rejected.exception.code,'prompt_preparation_required')
                with self.assertRaises(AgentError) as diagnostic:
                    client.request('image-test','POST',dict(prompt='A manual cup.',approved=True),'http-diagnostic-bypass')
                self.assertEqual(diagnostic.exception.code,'prompt_preparation_required');self.assertEqual(app.diagnostics.records,[])
                route='prompting/image/'+record['id']
                job=client.request(route,'POST',dict(expected_revision=record['revision'],approved=True,provider='codex'),'http-prompt-fixture')
                self.assertEqual(job['status'],'done');self.assertFalse(client.request(route)['current'])
                self.assertEqual(client.request('prompting/jobs/'+job['id'])['provenance'],job['provenance'])
                result=client.request(route+'/apply','POST',dict(job_id=job['id'],expected_revision=job['revision'],expected_media_revision=record['revision']))
                self.assertTrue(client.request(route)['current']);self.assertEqual(result['draft']['settings']['prompt'],job['result']['prompt'])
                self.assertEqual(app.images.db['jobs'],[]);app.filmmaking.request_plan.assert_called_once()
                spec=client.request('openapi.json');self.assertIn('PromptPreparationJob',spec['components']['schemas'])
            finally:
                server.shutdown();thread.join(5);server.server_close();accounts.sql.close();app.productions.sql.close()


if __name__=='__main__':unittest.main()
