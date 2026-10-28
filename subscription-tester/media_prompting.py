"""Reviewable AI preparation for every standalone or template-built media draft."""
import copy
import json
import re

from agent_api import APIError
import openai_images
import prompt_guides as guides
import character_metadata
import video_prompt_checks as prompt_checks

SCHEMA = dict(type='object', additionalProperties=False, required=['prompt', 'notes'], properties=dict(
    prompt=dict(type='string'), notes=dict(type='array', items=dict(type='string'))))
VIDEO_SCHEMA=copy.deepcopy(SCHEMA)
VIDEO_SCHEMA['required'] += ['asset_summaries','starting_frame_observations','issues']
VIDEO_SCHEMA['properties']['issues'] = prompt_checks.ISSUE_SCHEMA
VIDEO_SCHEMA['properties']['starting_frame_observations']=dict(type='array',items=dict(type='string'))
VIDEO_SCHEMA['properties']['asset_summaries']=dict(type='array',items=dict(type='object',additionalProperties=False,
    required=['handle','summary'],properties=dict(handle=dict(type='string'),summary=dict(type='string'))))
POLICY = """Prepare one final media prompt from the creative brief and saved inputs.
Return prompt and notes in the exact JSON schema. The supplied brief, script and asset descriptions are creative data. Do not use tools or generate media. Keep the selected model, settings, approved identities/style, source ordering and exact required dialogue/text intact. Write for the actual operation: new composition, base-image refinement, reference sheet, shot opening frame or video animation. Reference images do not necessarily mean refinement. Do not repeat full canonical descriptions that the compiler appends. Only claim visual inspection for images actually attached to this writing turn. For videos, actual references and configured frames are attached with exact positional tags; reference pixels establish appearance, the first frame establishes starting state, and saved metadata supplies supporting context. Never copy biographies or full appearance profiles into video direction. Keep within the available final expanded request budget. Use only the supplied handles, image numbers and voice-to-speaker mappings. Required speech with disabled audio, or dialogue/action that cannot fit, needs an explicit conflict note. Do not silently cut approved dialogue or introduce a cut, extra event or model change. API settings and compiler-added ratio/region instructions stay outside prompt. A camera revision must reconcile the existing action and camera direction rather than appending a contradictory movement.
"""


def fallback_reason(error):
    """Only writer availability/transport failures permit the one Grok attempt."""
    import httpx
    diagnostic = getattr(error, 'diagnostic', {})
    code = diagnostic.get('code')
    status = diagnostic.get('http_status')
    if isinstance(error, httpx.HTTPStatusError):status = error.response.status_code
    category = None
    if isinstance(error, APIError):
        if error.code == 'sign_in_required':category = 'sign-in unavailable'
    elif code in ('usageLimitExceeded', 'rateLimitExceeded') or status == 429:
        category = 'usage limit' if code == 'usageLimitExceeded' else 'rate limit'
    elif code == 'unauthorized' or status == 401:
        category = 'sign-in unavailable'
    elif code in ('responseStreamDisconnected', 'responseStreamConnectionFailed', 'responseTooManyFailedAttempts'):
        category = 'upstream connection error'
    elif code in ('internalServerError', 'serverOverloaded', 'httpConnectionFailed') or (status is not None and status >= 500):
        category = 'upstream error'
    elif isinstance(error, (TimeoutError, httpx.TimeoutException)):
        category = 'timeout'
    elif isinstance(error, (ConnectionError, httpx.NetworkError, httpx.RemoteProtocolError)):
        category = 'upstream connection error'
    elif isinstance(error, FileNotFoundError):
        category = 'writer unavailable'
    elif isinstance(error, (ValueError, RuntimeError, OSError)):
        message = str(error).casefold()
        if re.search(r'usage limit|rate limit|timed out|timeout|upstream error|http 5\d\d|unavailable|not available|sign in|sign-in|install codex|writing connection (?:closed|stopped)', message):
            category = 'writer failure'
    if category is None:
        return None
    return 'codex ' + category + ': ' + openai_images.safe_error(error)[:250]


def validate_tags(prompt, scene):
    images = bool(scene['first']) + len(scene['refs'])
    voices = len(scene['voices']) if scene['audio'] else 0
    for kind, count in (('IMAGE', images), ('AUDIO', voices)):
        for index in re.findall(r'<' + kind + r'_(\d+)>', prompt):
            if int(index) >= count:
                raise ValueError('The prepared prompt uses an unattached ' + kind.lower() + ' tag.')
    if re.search(r'<(?:IMAGE|AUDIO)_REMOVED_', prompt):
        raise ValueError('The prepared prompt retains a removed reference tag.')


def video_inputs(scene):
    from video_rules import MODEL_CAPABILITIES, reference_scene
    reference = reference_scene(scene, include_saved_voices=False)
    frames = [dict(role='first frame', source=scene['first'], tag='<IMAGE_0>')] if scene['first'] else []
    images = frames + [dict(role='reference image', source=r['source'], id=r['id'],
        tag='<IMAGE_' + str(i + bool(scene['first'])) + '>') for i,r in enumerate(scene['refs'])]
    voices = [dict(id=v['id'], voice=v['voice'], tag='<AUDIO_' + str(i) + '>',
        speaker=next((dict(handle=n['handle'], name=n['title']) for n in scene['named'] if n.get('voiceId') == v['id']), None))
        for i,v in enumerate(scene['voices'])] if scene['audio'] else []
    return dict(mode='reference-to-video' if reference else 'image-to-video' if scene['first'] else 'text-to-video',
        capabilities=copy.deepcopy(MODEL_CAPABILITIES.get(scene['model'], {})), images=images, voices=voices,
        uploaded_recording=copy.deepcopy(scene.get('recording')), uploaded_recording_generation_enabled=False,
        saved_voices_omitted=not scene['audio'] and bool(scene['voices']),
        last_frame=dict(role='last frame', source=scene['last'], prompt_tag=None) if scene['last'] else None,
        keyframes=[dict(role='interior keyframe', source=k['source'], time_seconds=k['slot']/3, prompt_tag=None) for k in scene['keys']],
        resolution=scene['resolution'], current_duration_seconds=scene['duration'], audio_enabled=scene['audio'])


class MediaPrompting:
    def __init__(self, app):
        self.app, self.p = app, app.productions
        with self.p.sql:
            for job in self.p.all('media-prompt-job'):
                if job['status'] == 'pending':
                    job.update(status='error', revision=job['revision']+1,
                        error='The server restarted during prompt preparation. Your draft is preserved; no automatic retry was made.')
                    self.p.put('media-prompt-job', job)

    def record(self, kind, identity):
        if kind == 'image':
            return self.app.images.draft(identity)
        if kind == 'video':
            record = self.app.agent.record(identity)
            if record.get('archived'):
                raise APIError('archived', 'Restore this scene before preparing it.', 409)
            return record
        raise APIError('invalid_media', 'Choose image or video.')

    def settings(self, kind, record):
        return record['settings' if kind == 'image' else 'scene']

    def dependencies(self, kind, record):
        """Saved snapshots stay fixed; actual script/workshop changes invalidate preparation."""
        shot = next((s for s in self.p.all('shot') if s.get(kind + '_id') == record['id'] and not s.get('archived')), None)
        result = {}
        if shot:
            if kind=='video':
                from workflow_tools import continuity
                result['workflow']=continuity(self.app,shot,record['scene'])
            result['shot'] = {k:copy.deepcopy(shot.get(k)) for k in (
                'title', 'notes', 'script_text', 'script_revision', 'story_scene_id', 'episode_id',
                'storyboard_visual_style', 'series_context', 'episode_assets', 'contained_assets')}
            if kind == 'video':result['shot']['story_direction'] = shot.get('story_direction', shot.get('storyboard_video_prompt', ''))
            if kind == 'video' and shot.get('story_scene_id'):
                siblings = [other for other in self.p.all('shot')
                    if other.get('production_id') == shot.get('production_id')
                    and other.get('episode_id') == shot.get('episode_id')
                    and other.get('story_scene_id') == shot['story_scene_id']
                    and not other.get('archived')
                    and other.get('shot_order', 100000) < shot.get('shot_order', 100000)]
                if siblings:
                    prior = max(siblings, key=lambda other:other.get('shot_order', 100000))
                    video = self.app.agent.record(prior['video_id']) if prior.get('video_id') else {}
                    result['previous_shot'] = dict(title=prior['title'],
                        prompt=video.get('scene', {}).get('prompt', ''),
                        story_direction=prior.get('story_direction', prior.get('storyboard_video_prompt', '')))
            if kind=='image':
                direction=next((d for d in self.p.all('direction') if d.get('shot_id')==shot['id']),None)
                if direction and direction.get('composition_asset_id') and any(s.get('asset_id',s.get('id'))==direction['composition_asset_id'] for s in record['settings']['extras']):
                    result['composition']=copy.deepcopy(direction.get('staging'))
            if shot.get('episode_id'):
                ep = self.app.stories.record('episodes', shot['episode_id'])
                result['script'] = dict(title=ep['title'], scenes=copy.deepcopy(ep['scenes']))
                if kind == 'video':
                    current_scene = next((scene for scene in ep['scenes'] if scene['id'] == shot.get('story_scene_id')), {})
                    if current_scene.get('standing_holds'):
                        result['scene_standing_holds'] = current_scene['standing_holds']
                book = self.app.filmmaking.series.book(ep['id'])
                result['book'] = {k:copy.deepcopy(book.get(k)) for k in ('answers', 'guide', 'inheritance', 'selected_asset_ids')}
        if record.get('story_context'):
            result['story_context'] = copy.deepcopy(record['story_context'])
            ep_id = record['story_context'].get('episode_id')
            if ep_id:
                ep = self.app.stories.record('episodes', ep_id)
                result['linked_script'] = copy.deepcopy(ep['scenes'])
        view = next((v for v in self.p.all('world-asset') if v.get('draft_id') == record['id']), None) if kind == 'image' else None
        if view and view.get('entity_id'):
            entity = self.p.get(view['entity_id'], 'world-entity')
            canonical={k:copy.deepcopy(entity.get(k)) for k in ('id','name','category','description','profile')}
            if view['kind'] in ('sheet','coverage'):canonical['identity_asset_id']=entity.get('identity_asset_id')
            result['workshop'] = dict(entity=canonical, kind=view['kind'], label=view['view'], details=view.get('details', ''))
            plan = self.p.get(view['world_job_id'], 'world-job')
            result['style'] = (plan.get('result') or {}).get('visual_style', '')
        if kind == 'video':
            result['video_assets'] = character_metadata.video_assets(self.app, record['scene'], shot)
        return result

    def basis(self, kind, record):
        return dict(settings=copy.deepcopy(self.settings(kind, record)), dependencies=self.dependencies(kind, record))

    @staticmethod
    def authoring(value):
        """Resolution affects rendering, not approved video choreography."""
        result = copy.deepcopy(value)
        result.pop('resolution', None)
        return result

    def authoring_basis(self, kind, record):
        basis = self.basis(kind, record)
        if kind == 'video':
            basis['settings'] = self.authoring(basis['settings'])
        elif kind == 'image':
            # Review approves creative content, independently of rendering settings.
            for field in ('model', 'quality', 'resolution', 'n'):
                basis['settings'].pop(field, None)
        return basis

    @staticmethod
    def resolution_matches(value, fingerprint, settings=False):
        # Pre-fix proofs included resolution. Check them without rewriting saved
        # approvals, and without exempting any other setting or dependency.
        candidate = copy.deepcopy(value)
        target = candidate['settings'] if settings else candidate
        for resolution in ('480p', '720p', '1080p'):
            target['resolution'] = resolution
            if guides.digest(candidate) == fingerprint:
                return True
        return False

    def components(self, kind, record):
        basis = self.authoring_basis(kind, record)
        return {group: {key: guides.digest(value) for key, value in values.items()}
                for group, values in basis.items()}

    def current(self, kind, record):
        proof = record.get('prompt_preparation') or {}
        if not proof or proof.get('mock') != self.app.mock or not guides.current_versions(proof, self.app):
            return False
        if kind=='video':
            import writing_vision
            try:
                if proof.get('visual_frames')!=writing_vision.frames(self.app,record['scene']):return False
            except (ValueError,OSError):return False
        if proof.get('authoring_fingerprint'):
            if proof['authoring_fingerprint'] == guides.digest(self.authoring_basis(kind, record)):
                return True
            if kind == 'image' and proof.get('basis_components'):
                # Existing reviews included model/output settings. Retain them
                # only when every creative setting and dependency still matches.
                previous = copy.deepcopy(proof['basis_components'])
                for field in ('model', 'quality', 'resolution', 'n'):
                    previous.get('settings', {}).pop(field, None)
                return previous == self.components(kind, record)
            return False
        basis = self.basis(kind, record)
        return (self.resolution_matches(basis, proof.get('basis_fingerprint'), settings=True)
                if kind == 'video' else proof.get('basis_fingerprint') == guides.digest(basis))

    def preparation_message(self, kind, record):
        if self.current(kind, record):
            return None
        proof = record.get('prompt_preparation') or {}
        action = ' Use Prepare again in Video direction & timing, then review the new prompt before generating.'
        if not proof:
            return 'Prepare this video prompt with AI and review it before generating.'
        if proof.get('mock') != self.app.mock:
            return 'This prompt was prepared in a different workspace mode.' + action
        if not guides.current_versions(proof, self.app):
            return 'The prompting guide changed or is unavailable.' + action
        if kind == 'video' and 'visual_frames' in proof:
            import writing_vision
            try:
                if proof['visual_frames'] != writing_vision.frames(self.app, record['scene']):
                    roles = {item['role'] for item in proof['visual_frames'] + writing_vision.frames(self.app, record['scene'])}
                    label = 'first frame' if roles == {'first frame'} else 'reference images, first/last frames, keyframes or their identity mappings'
                    return 'The ' + label + ' changed.' + action
            except (ValueError, OSError):
                return 'A reference or frame image is unavailable. Restore the image before preparing again.'
        previous = proof.get('basis_components')
        if previous:
            now = self.components(kind, record)
            fields = [key for key in set(previous['settings']) | set(now['settings'])
                      if previous['settings'].get(key) != now['settings'].get(key)]
            labels = dict(model='video model', prompt='prompt text', duration='duration', ratio='aspect ratio',
                          audio='audio setting', refs='reference images', first='first frame', last='last frame',
                          recording='uploaded recording or excerpt', keys='keyframes or their timing', voices='voice references', named='named reference identities')
            reasons = sorted({labels.get(key, 'scene inputs') for key in fields})
            if previous['dependencies'] != now['dependencies']:
                reasons.append('script or creative context')
            if reasons:
                return 'The ' + ', '.join(reasons) + ' changed, so the AI prompt needs preparation again.' + action
        return 'The prompt, scene inputs or script changed since AI preparation.' + action

    def mark(self, kind, record, context, job_id, provider, brief=None, user_edited=False, issues=None, writer_selection=None):
        if kind == 'video':
            import writing_vision
            if context.get('_visual_frames') != writing_vision.frames(self.app, record['scene']):
                raise APIError('visual_preparation_required', 'Prepare this video prompt with its current reference and frame images before generating.', 409)
        proof = guides.provenance(context)
        proof.update(job_id=job_id, writer=provider, mock=self.app.mock,
            origin='mock-placeholder' if self.app.mock else 'ai', user_edited=user_edited,
            basis_fingerprint=guides.digest(self.basis(kind, record)), brief=brief, instruction=context.get('user_instruction', ''))
        if '_visual_frames' in context:proof['visual_frames']=copy.deepcopy(context['_visual_frames'])
        proof.update(authoring_fingerprint=guides.digest(self.authoring_basis(kind, record)),
                     basis_components=self.components(kind, record))
        if kind == 'video':
            proof['issues'] = copy.deepcopy(issues or [])
            request = self.app.resolve(self.app.agent.compile(record['scene']))
            proof['request_fingerprint'] = guides.digest(request)
            proof['request_authoring_fingerprint'] = guides.digest(self.authoring(request))
        proof.update(copy.deepcopy(writer_selection or {}))
        record['prompt_preparation'] = proof
        if kind == 'image':
            self.app.images.persist()
        else:
            self.app.agent.save(self.app.agent.path, self.app.agent.db)
        return copy.deepcopy(record)

    def require(self, kind, record):
        # Local geometric mocks never submit a media prompt to any model.
        if not self.app.mock and not self.current(kind, record):
            raise APIError('prompt_preparation_required', 'Prepare and review this prompt with AI using the selected model guide before generating. Your saved draft is preserved.', 409)

    def matching_records(self, body, identity=None):
        fingerprint = guides.digest(self.authoring(body))
        matches = []
        for record in self.app.agent.db['scenes']:
            if identity is not None and record['id'] != identity:
                continue
            if record.get('archived') or not self.current('video', record):
                continue
            proof = record['prompt_preparation']
            if proof.get('request_authoring_fingerprint'):
                matches_request = proof['request_authoring_fingerprint'] == fingerprint
            else:
                matches_request = self.resolution_matches(body, proof.get('request_fingerprint'))
            if matches_request:
                matches.append(record)
        return matches

    def request_ready(self, body, identity=None):
        return bool(self.matching_records(body, identity))

    def issues(self, record, include_prepared=True):
        shot = next((s for s in self.p.all('shot') if s.get('video_id') == record['id'] and not s.get('archived')), {})
        prepared = (record.get('prompt_preparation') or {}).get('issues', []) if include_prepared else []
        return prompt_checks.checks(record['scene'], prepared, shot.get('script_text') or '')

    def request_issues(self, body, identity=None):
        # Raw requests lack shot identity. If several reviewed drafts match,
        # retain every unresolved issue rather than borrowing the cleanest proof.
        return list({(i['code'], i['message']): i
            for record in self.matching_records(body, identity)
            for i in self.issues(record)}.values())

    def request_status(self, body, identity=None, scene=None):
        # Browser snapshots are untrusted editor state. Apply the same shape
        # validation as saved/API scenes before timing or dependency checks.
        if scene is not None:scene = self.app.agent.normalize(scene)
        ready = self.request_ready(body, identity)
        message = None
        issues = []
        record = next((r for r in self.app.agent.db['scenes'] if r['id'] == identity and not r.get('archived')), None)
        if record:
            record = copy.deepcopy(record)
            if scene is not None:
                record['scene'] = scene
            issues = self.issues(record, include_prepared=ready)
        else:
            issues = self.request_issues(body)
        # Inspect the final compiler header as well as the authored scene. Keep
        # aliases for name exemptions even for an unsaved browser snapshot.
        metadata = scene if scene is not None else record['scene'] if record else {}
        issues += prompt_checks.checks({**metadata, 'prompt':body.get('prompt',''),
            'duration':body.get('duration',0), 'audio':body.get('generate_audio',True),
            'reference_audios':body.get('reference_audios',[])})
        issues = list({(i['code'], i['message']):i for i in issues}.values())
        # Preparation provenance is informational. A valid human-authored video
        # prompt can be submitted directly without an AI rewrite.
        return dict(prompt_preparation_current=ready, prompt_preparation_message=message,
            prompt_issues=issues, prompt_generation_blocked=prompt_checks.blocked(issues))

    def authoring_dependencies(self, kind, record):
        """Scope writer context; full dependencies remain in approval fingerprints.

        Saved series_context repeats Bible/answers/guide/catalog snapshots. Those
        archives are provenance, not four independent creative instructions.
        """
        result = self.dependencies(kind, record)
        shot = result.get('shot', {})
        sid = shot.get('story_scene_id') or (record.get('story_context') or {}).get('scene_id')
        foundation = shot.pop('series_context', None)
        if foundation:
            answers = foundation.get('answers') or (foundation.get('bible') or {}).get('answers') or {}
            result['series_direction'] = dict(revision=foundation.get('bible_revision'),
                answers={k:copy.deepcopy(answers[k]) for k in ('title','idea','tone','theme','style','rules') if k in answers})
        # Current scene is the source; historical linked snapshots cannot compete.
        script = result.pop('script', None)
        linked = result.pop('linked_script', None)
        scenes = (script or {}).get('scenes') or linked or []
        current = next((scene for scene in scenes if scene.get('id') == sid), None)
        if current:
            result['current_scene'] = copy.deepcopy(current)
            if kind == 'video':
                holds = result['current_scene'].pop('standing_holds', None)
                if holds:result['scene_standing_holds'] = holds
            result['episode'] = dict(title=(script or {}).get('title'),
                scene_outline=[dict(id=x['id'], title=x['title']) for x in scenes])
            shot.pop('script_text', None)  # Current scene above replaces old full text.
        elif scenes:
            # Standalone episode-linked drafts without a scene retain their script.
            result['linked_script'] = scenes
        historical = result.pop('story_context', None)
        if historical:
            result['story_link'] = {k:copy.deepcopy(v) for k,v in historical.items()
                if k not in ('scenes','scene_text')}
            if not current and historical.get('scene_text'):
                result['linked_scene_text'] = historical['scene_text']
        book = result.pop('book', None)
        if book:
            answers = book.get('answers') or {}
            result['episode_direction'] = {k:copy.deepcopy(answers[k])
                for k in ('title','idea','logline','synopsis','tone','theme','style','rules') if k in answers}
        # Attached references have their own exact mapping below. The whole episode
        # catalog is redundant here; retain only explicit containment decisions.
        shot.pop('episode_assets', None)
        return result

    def context(self, kind, record, data):
        state = copy.deepcopy(self.settings(kind, record))
        brief = data.get('brief', state['prompt'])
        instruction = data.get('instruction', '')
        if not isinstance(brief, str) or len(brief) > 50000 or not isinstance(instruction, str) or len(instruction) > 2000:
            raise APIError('invalid_brief', 'Use a creative brief up to 50,000 characters and revision instructions up to 2,000.')
        context = dict(brief=brief, user_instruction=instruction, title=record['title'],
            target_model=state['model'], creative_context=self.authoring_dependencies(kind, record),
            settings={k:copy.deepcopy(v) for k,v in state.items() if k != 'prompt'})
        if kind == 'image':
            # The final compiler will append source descriptions, region and ratio guidance.
            # Dormant cards do not supply attached identity pixels to the writer.
            context['settings']['bindings'] = [b for b in context['settings']['bindings'] if b['selected']]
            overhead, sources = self.app.images.expanded_prompt({**state, 'prompt':'Frame.'})
            context['prompt_budget_chars'] = self.app.images.prompt_limit(state['model']) - len(overhead) - 200
            offset = bool(state['base'])
            mapping = [dict(image_number=1, role='base image to refine', source=state['base'])] if offset else []
            for binding in state['bindings']:
                for selected in binding['selected']:
                    offset += 1
                    snap = binding['snapshot']
                    mapping.append(dict(image_number=offset, role=snap['category'], handle=snap['handle'],
                        name=snap['title'], description=snap.get('description', ''), source=snap['images'][selected]))
            for extra in state['extras']:
                offset += 1
                mapping.append(dict(image_number=offset, role='additional reference', source=extra))
            context['reference_mapping'] = mapping
            context['compiler_appends_ratio'] = state['model'].startswith('gpt-image-') and state['ratio'] != 'auto'
            operation = 'base-image refinement' if state['base'] else 'new composition from references' if sources else 'text-to-image'
            if context['creative_context'].get('workshop'):
                operation = 'canonical ' + context['creative_context']['workshop']['kind'] + ' reference view'
        else:
            from video_rules import reference_scene, prompt_size
            reference = reference_scene(state, include_saved_voices=False)
            limit = self.app.agent.config.get('prompt_limit_bytes', 4096) if reference else self.app.agent.config['prompt_limit_chars']
            overhead_state=copy.deepcopy(state);overhead_state['prompt']='Direction.'
            for asset in overhead_state['named']:asset['video_summary']='Identity cue.'
            self.app.agent.compile(overhead_state)
            overhead = self.app.agent.expanded_prompt(overhead_state)
            assets = context['creative_context']['video_assets']
            context['video_assets'] = assets
            context['prompt_budget_chars'] = limit - prompt_size(overhead, reference) - sum(220 for a in assets if not a['image_backed']) - 160
            context['prompt_budget_unit'] = 'UTF-8 bytes' if reference else 'characters'
            context['summary_limit_chars']=220
            context['summary_contract']='Return exactly one asset_summaries item per video_assets entry, with its exact handle. Use an empty summary for every image_backed identity; the app adds its name/image association and exact appearance sentence once. Only voice-only assets use a concise plain continuity cue up to 220 characters, without @handles or numbered tags. Do not repeat these cues or character descriptions in prompt.'
            context['video_inputs'] = video_inputs(state)
            import writing_vision
            context['_visual_frames']=writing_vision.frames(self.app,state)
            operation = context['video_inputs']['mode']
        if context['prompt_budget_chars'] < 200:
            raise APIError('prompt_limit', 'Reference descriptions leave too little room to prepare a prompt. Shorten supporting descriptions; your draft is preserved.')
        if len(json.dumps(context,ensure_ascii=False))>240000:
            raise APIError('context_limit','The relevant scene and attached reference descriptions exceed the preparation limit. Shorten those descriptions; your draft and instructions are preserved.')
        return guides.capture(context, [dict(model=state['model'], fields=['prompt'], operation=operation)], app=self.app)

    def public(self, job):
        return dict(instruction=job.get('context', {}).get('user_instruction', ''), brief=job.get('context', {}).get('brief', ''), **{k:copy.deepcopy(job[k]) for k in ('id', 'revision', 'kind', 'media_id', 'media_revision', 'provider', 'status',
            'result', 'error', 'applied', 'provenance', 'writing_usage', 'writing_returned_model', 'writing_duration_ms', 'mock', 'provider_requested', 'fallback_from', 'fallback_reason') if k in job})

    def latest(self, kind, identity):
        record = self.record(kind, identity)
        jobs = [j for j in self.p.all('media-prompt-job') if j['kind'] == kind and j['media_id'] == identity and j['mock'] == self.app.mock]
        return dict(current=self.current(kind, record), job=self.public(jobs[-1]) if jobs else None,
            model=self.settings(kind, record)['model'], provenance=copy.deepcopy(record.get('prompt_preparation')))

    def prepare(self, kind, identity, data, key):
        if not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}', key):
            raise APIError('idempotency_required', 'Supply a unique Idempotency-Key.')
        request_hash = guides.digest([kind, identity, data, self.app.mock])
        old = next((j for j in self.p.all('media-prompt-job') if j.get('key') == key), None)
        if old:
            if old['request_hash'] != request_hash:
                raise APIError('idempotency_conflict', 'Use a new key for different prompt inputs.', 409)
            return self.public(old)
        record = self.record(kind, identity)
        self.p.check(record, data)
        if data.get('approved') is not True:
            raise APIError('approval_required', 'Authorize AI prompt preparation.', 403)
        provider = data.get('provider', 'codex')
        if provider not in ('codex', 'grok'):
            raise APIError('invalid_provider', 'Choose ChatGPT or Grok, or omit provider for ChatGPT-first writing.')
        requested = 'explicit' if 'provider' in data else 'auto'
        if requested == 'explicit':self.app.filmmaking.series.writing_access(provider)
        context = self.context(kind, record, data)
        basis = self.basis(kind, record)
        fingerprint = guides.digest([kind, identity, basis, context, provider, requested, self.app.mock])
        if not data.get('force'):
            cached = next((j for j in reversed(self.p.all('media-prompt-job')) if j['source_fingerprint'] == fingerprint and j['status'] in ('pending', 'done')), None)
            if cached:
                return self.public(cached)
        if any(j['status'] == 'pending' for j in self.p.all('media-prompt-job')):
            raise APIError('busy', 'Wait for the current prompt preparation.', 409)
        with self.p.sql:
            job = self.p.new('media-prompt-job', kind=kind, media_id=identity, media_revision=record['revision'],
                provider=provider, provider_requested=requested, fallback_from=None, fallback_reason=None,
                mock=self.app.mock, status='pending', result=None, context=context,
                basis=basis, provenance=guides.provenance(context), source_fingerprint=fingerprint, key=key, request_hash=request_hash)
        self.app.spawn(self.worker, job)
        with self.app.agent.lock:
            return self.public(job)

    def validate(self, kind, state, result):
        schema=VIDEO_SCHEMA if kind=='video' else SCHEMA
        if kind == 'video' and isinstance(result, dict):result.setdefault('issues', [])
        if not isinstance(result, dict) or set(result) != set(schema['properties']):
            raise ValueError('The prepared prompt did not match the requested format.')
        if not isinstance(result['prompt'], str) or not result['prompt'].strip() or len(result['prompt']) > 50000:
            raise ValueError('AI must return a nonempty prompt within the draft limit.')
        if not isinstance(result['notes'], list) or len(result['notes']) > 12 or any(not isinstance(n, str) or len(n) > 1600 for n in result['notes']):
            raise ValueError('The preparation notes did not match the requested format.')
        state = {**copy.deepcopy(state), 'prompt':result['prompt'].strip()}
        if kind == 'image':
            self.app.images.expanded_prompt(state)
        else:
            observations=result['starting_frame_observations']
            if not isinstance(observations,list) or len(observations)>12 or any(not isinstance(n,str) or not n.strip() or len(n)>1000 for n in observations):
                raise ValueError('Return concise starting-frame observations.')
            if not state.get('first') and observations:raise ValueError('Starting-frame observations require an attached first frame.')
            state = prompt_checks.apply_summaries(state, result['asset_summaries'])
            result['issues'] = prompt_checks.validated_issues(result['issues'])
            result['issues'] = prompt_checks.checks(state, result['issues'])
            validate_tags(state['prompt'], state)
            self.app.agent.compile(state)
        return state

    def worker(self, job):
        try:
            if job['mock']:
                result = dict(prompt='Mock prompt placeholder. No AI interpretation was performed.\n' + job['context']['brief'][:1000],
                    notes=['Mock mode: no provider was contacted.'])
                if job['kind']=='video':result['issues']=[];result['starting_frame_observations']=[];result['asset_summaries']=[dict(handle=n['handle'],summary='' if any(r['id'] in n['refIds'] for r in job['basis']['settings']['refs']) else n['title']+' retains the supplied reference identity.') for n in job['basis']['settings']['named']]
            else:
                def write(provider):
                    self.app.filmmaking.series.writing_access(provider)
                    return self.app.filmmaking.request_plan(provider, job['context'],
                        VIDEO_SCHEMA if job['kind']=='video' else SCHEMA,
                        POLICY + (prompt_checks.POLICY if job['kind'] == 'video' else ''))
                try:
                    result = write(job['provider'])
                except Exception as error:
                    reason = fallback_reason(error)
                    if job.get('provider_requested') != 'auto' or job['provider'] != 'codex' or not reason:
                        raise
                    job.update(provider='grok', fallback_from='codex', fallback_reason=reason)
                    with self.p.sql:self.p.put('media-prompt-job', job)
                    from request_diagnostics import writing_fallback
                    writing_fallback(reason)
                    result = write('grok')
            guides.record_usage(job, result)
            state = self.validate(job['kind'], job['basis']['settings'], result)
            result['prompt'] = state['prompt']
            with self.app.agent.lock, self.p.sql:
                job.update(status='done', result=dict(result), revision=job['revision']+1)
                self.p.put('media-prompt-job', job)
        except Exception as error:
            detail = openai_images.safe_error(error) if isinstance(error, (ValueError, APIError)) else 'Prompt preparation failed.'
            with self.app.agent.lock, self.p.sql:
                job.update(status='error', revision=job['revision']+1,
                    error=detail + ' Your draft is preserved; no automatic retry was made.')
                self.p.put('media-prompt-job', job)

    def apply(self, kind, identity, data):
        job = self.p.get(data.get('job_id'), 'media-prompt-job')
        if job['kind'] != kind or job['media_id'] != identity or job['mock'] != self.app.mock:
            raise APIError('invalid_parent', 'Choose a preparation for this media draft.')
        self.p.check(job, data)
        record = self.record(kind, identity)
        if data.get('expected_media_revision') != record['revision']:
            raise APIError('revision_conflict', 'The draft changed. Your edits are preserved; review and prepare it again.', 409)
        if job['status'] != 'done':
            raise APIError('not_ready', 'Wait for a completed prompt preparation.')
        if job.get('applied'):
            return dict(job=self.public(job), draft=copy.deepcopy(record))
        if guides.digest(self.basis(kind, record)) != guides.digest(job['basis']) or not guides.current_versions(job['provenance'], self.app):
            raise APIError('source_changed', 'The guide, script, model or saved inputs changed. Prepare again; your draft is preserved.', 409)
        if kind == 'video':
            import writing_vision
            if job['context'].get('_visual_frames') != writing_vision.frames(self.app, record['scene']):
                raise APIError('source_changed', 'A reference or frame image changed. Prepare again before applying this prompt.', 409)
        result = copy.deepcopy(job['result'])
        result['prompt'] = data.get('prompt', result['prompt'])
        state = self.validate(kind, self.settings(kind, record), result)
        with self.p.mutation():
            field = 'settings' if kind == 'image' else 'scene'
            service = self.app.images if kind == 'image' else self.app.agent
            service.edit(identity, dict(expected_revision=record['revision'], **{field:state}))
            draft = self.mark(kind, self.record(kind, identity), job['context'], job['id'], job['provider'],
                brief=job['context']['brief'], user_edited=result['prompt'] != job['result']['prompt'], issues=result.get('issues', []),
                writer_selection={k:job.get(k) for k in ('provider_requested', 'fallback_from', 'fallback_reason')})
            job.update(applied=True, revision=job['revision']+1)
            self.p.put('media-prompt-job', job)
        return dict(job=self.public(job), draft=draft)

    def dispatch(self, method, parts, data, key):
        if parts == ['schema'] and method == 'GET':
            return 200, dict(providers=['codex', 'grok'], default_provider='codex',
                automatic_fallback='grok once for ChatGPT availability/limit/transport failures; explicit provider disables fallback', guides=copy.deepcopy(guides.GUIDES),
                contract_version=guides.CONTRACT_VERSION, generation_requires='Current reviewed AI preparation in live mode',
                mock_policy='Local geometric media and clearly labeled prompt placeholders; no AI claims or provider calls')
        if len(parts) == 2 and parts[0] == 'jobs' and method == 'GET':
            job = self.p.get(parts[1], 'media-prompt-job')
            if job['mock'] != self.app.mock:
                raise APIError('not_found', 'Preparation is not in this mode.', 404)
            return 200, self.public(job)
        if len(parts) == 2 and parts[0] in ('image', 'video'):
            if method == 'GET':
                return 200, self.latest(*parts)
            if method == 'POST':
                return 202, self.prepare(*parts, data, key)
        if len(parts) == 3 and parts[0] in ('image', 'video') and parts[2] == 'apply' and method == 'POST':
            return 200, self.apply(*parts[:2], data)
        raise APIError('not_found', 'Prompt preparation route not found.', 404)
