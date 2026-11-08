"""Saved directing work shared by the storyboard and Agent API."""
from agent_api import APIError
from story_studio import text


def active_shot(p, identity, production_id=None, episode_id=None):
    shot = p.get(identity, 'shot')
    production = p.get(shot['production_id'], 'production')
    if production.get('archived') or shot.get('archived'):
        raise APIError('archived', 'Restore this shot and production before using directing tools.', 409)
    if production_id is not None and (shot['production_id'], shot.get('episode_id')) != (production_id, episode_id):
        raise APIError('invalid_scope', 'Choose a shot from this production and episode.')
    return shot


def check_revision(p, record, expected_revision):
    if type(expected_revision) is not int:
        raise APIError('invalid_revision', 'Supply the saved integer revision.')
    p.check(record, {'expected_revision': expected_revision})


def shot_frames(p, shot, snapshot=False):
    view = p.view_shot(shot) if snapshot else shot
    frames = []
    def add(role, source, timestamp=None):
        if source and source.get('id'):
            frames.append(dict(role=role, asset_id=source['id'], src='/api/assets/'+source['id'],
                               name=source.get('name', role), timestamp_s=timestamp))
    add('Selected image', view['approved_image'])
    for take in view['image_takes']:
        for asset in take.get('outputs', []):
            if asset['id'] != (view['approved_image'] or {}).get('id'):
                add('Image candidate', asset)
    video = view['video']
    if video and not snapshot:
        video = p.app.agent.record(video['id'])
    scene = video['scene'] if video else {}
    add('First frame', scene.get('first'), 0)
    for key in scene.get('keys', []):
        add('Keyframe', key['source'], key['slot']/3)
    add('Last frame', scene.get('last'), scene.get('duration'))
    for ref in scene.get('refs', []):
        add('Reference image', ref['source'])
    result = dict(shot_id=shot['id'], title=shot['title'], frames=frames)
    if snapshot:
        state = {key: view[key] for key in ('revision', 'story_direction', 'notes', 'image', 'video', 'script_changed')}
        state['shot'] = shot
        direction = p.app.filmmaking.direction(shot['id'])
        if direction.get('staging'):
            state['camera_staging'] = direction
        link = next((r for r in p.all('blocking-link') if r['shot_id'] == shot['id'] and r.get('layout_id')), None)
        if link:
            from scene_blocking import KIND, view_stage
            layout = p.get(link['layout_id'], KIND)
            state['shared_blocking'] = {**link, 'layout_revision': layout['revision'], 'stage': view_stage(layout, link['view_id'])}
        result['state'] = state
    return result


def scoped_record(p, kind, identity, pid, eid):
    record = p.get(identity, kind)
    if (record['production_id'], record.get('episode_id')) != (pid, eid):
        raise APIError('not_found', 'This record is outside the selected episode.', 404)
    return record


def review_route(p, method, parts, data):
    if len(parts) >= 3 and parts[0] == 'continuity':
        pid, scope = parts[1:3]
        production = p.get(pid, 'production')
        if production.get('archived'):
            raise APIError('archived', 'Restore this production first.', 409)
        eid = None if scope == 'quick' else scope
        if production['kind'] == 'story':
            p.episode(production, eid)
        elif eid is not None:
            raise APIError('invalid_scope', 'Use quick for a Quick Video.')
        if parts[3:] == ['frames'] and method == 'GET':
            return 200, [shot_frames(p, s) for s in p.summary(pid)['shots'] if s.get('episode_id') == eid]
        kind = 'continuity-review'
        if len(parts) == 3 and method == 'GET':
            return 200, [{**{k: r[k] for k in ('id', 'revision', 'title')},
                          'frames': [{k: f[k] for k in ('shot_id', 'title', 'asset_id')} for f in r['frames']]}
                         for r in p.all(kind) if (r['production_id'], r.get('episode_id')) == (pid, eid)]
        if len(parts) == 3 and method == 'POST':
            choices = data.get('frames')
            if not isinstance(choices, list) or len(choices) != 2:
                raise APIError('invalid_frames', 'Select exactly two frames.')
            frames = []
            for choice in choices:
                if not isinstance(choice, dict):
                    raise APIError('invalid_frames', 'Select a shot and an image for each side.')
                shot_id = choice.get('shot_id')
                if not isinstance(shot_id, str):
                    raise APIError('invalid_frames', 'Choose a shot for each frame.')
                catalog = shot_frames(p, active_shot(p, shot_id, pid, eid), snapshot=True)
                frame = next((f for f in catalog['frames'] if f['asset_id'] == choice.get('asset_id')
                              and f['role'] == choice.get('role') and f['timestamp_s'] == choice.get('timestamp_s')), None)
                if not frame:
                    raise APIError('invalid_frames', 'A selected frame changed. Reload the frame list.')
                _, path = p.app.asset(frame['asset_id'])
                if not path.is_file():
                    raise APIError('missing_image', 'A selected frame file is missing.')
                frames.append({**frame, 'shot_id': catalog['shot_id'], 'title': catalog['title'], 'state': catalog['state']})
            if frames[0] == frames[1]:
                raise APIError('invalid_frames', 'Choose two different frame positions.')
            fields = review_fields(data)
            with p.sql:
                return 201, p.new(kind, production_id=pid, episode_id=eid, frames=frames, **fields)
        if len(parts) >= 4:
            record = scoped_record(p, kind, parts[3], pid, eid)
            if len(parts) == 4 and method == 'GET':
                return 200, record
            if len(parts) == 4 and method == 'PUT':
                check_revision(p, record, data.get('expected_revision'))
                with p.sql:
                    return 200, p.put(kind, {**record, **review_fields(data, record), 'revision': record['revision']+1})
            if parts[4:] == ['attach'] and method == 'POST':
                from frame_tools import place
                from candidate_review import available
                check_revision(p, record, data.get('expected_revision'))
                side = data.get('side')
                if type(side) is not int or side not in (0, 1) or not record['findings'].strip():
                    raise APIError('review_required', 'Save your image findings and choose the reviewed side to attach.')
                identity = data.get('target_shot_id')
                if not isinstance(identity, str):
                    raise APIError('invalid_target', 'Choose the destination shot.')
                shot = active_shot(p, identity, pid, eid)
                frame = record['frames'][side]
                if frame['shot_id'] == shot['id']:
                    raise APIError('invalid_target', 'Choose a different shot for the reviewed reference.')
                asset, path = p.app.asset(frame['asset_id'])
                available(asset)
                if not path.is_file():
                    raise APIError('missing_image', 'The reviewed image file is missing.')
                with p.mutation():
                    existing = p.app.agent.record(shot['video_id']) if shot.get('video_id') else None
                    check_revision(p, existing or {'revision': 0}, data.get('expected_video_revision'))
                    video = existing or p.media(shot, 'video')
                    if any(r['source'].get('id') == frame['asset_id'] for r in video['scene']['refs']):
                        return 200, video
                    return 200, place(p.app.agent, frame['asset_id'], dict(
                        scene_id=video['id'], expected_revision=video['revision'], target='reference'))
    return None


def review_fields(data, record=None):
    record = record or {}
    return {field: text(data.get(field, record.get(field, default)), limit, label, field == 'title')
            for field, default, limit, label in (
                ('title', 'Continuity review', 120, 'Review title'),
                ('consistent', '', 6000, 'Continuity expectations'),
                ('changes', '', 6000, 'Intentional changes'),
                ('findings', '', 12000, 'Image findings'))}


def generation_preview(p, identity):
    """Compile the saved video draft and identify each input without submitting."""
    from candidate_review import available
    from workflow_tools import start_frame_gate

    shot = active_shot(p, identity)
    video = p.app.agent.record(shot['video_id']) if shot.get('video_id') else None
    if not video:
        raise APIError('missing_video', 'Open the shot in Video to create its draft.', 404)
    scene = video['scene']
    issues, images, voices = [], [], []

    def issue(code, field, message, severity='error'):
        issues.append(dict(code=code, field=field, severity=severity, message=message))

    def image(role, field, source, timestamp=None, tag=None, identity=None):
        if not source:
            return
        asset_id = source.get('id')
        item = dict(role=role, field=field, asset_id=asset_id, timestamp_s=timestamp, tag=tag,
                    name=source.get('name') or role, src=source.get('src'))
        named = next((n['title'] for n in scene['named'] if identity and identity in n['refIds']), None)
        item['identity'] = named
        if asset_id:
            try:
                asset, path = p.app.asset(asset_id)
                available(asset)
                if not path.is_file():
                    raise ValueError()
                item['src'] = asset['src']
                if asset.get('generated') and not asset.get('approved'):
                    issue('approval_required', field, 'Review and approve '+item['name']+' before rendering.')
            except APIError as error:
                issue(error.code, field, str(error))
            except ValueError:
                item['src'] = None
                issue('missing_image', field, 'Replace the missing image '+item['name']+' ('+asset_id+').')
        images.append(item)

    image('First frame', 'image', scene['first'], 0, '<IMAGE_0>')
    for index, ref in enumerate(scene['refs']):
        image('Reference image', f'reference_images[{index}]', ref['source'],
              tag=f'<IMAGE_{index+bool(scene["first"])}>', identity=ref['id'])
    for index, key in enumerate(scene['keys']):
        image('Keyframe', f'keyframes[{index}]', key['source'], key['slot']/3)
    image('Last frame', 'last_frame', scene['last'], scene['duration'])

    for index, voice in enumerate(scene['voices']):
        speakers = [n['title'] for n in scene['named'] if n.get('voiceId') == voice['id']]
        speaker = ', '.join(speakers) or voice.get('speaker') or voice.get('name') or voice.get('label')
        voices.append(dict(speaker=speaker, voice_id=voice['voice'], included=scene['audio'], tag=f'<AUDIO_{index}>'))
        if not speaker and scene['audio']:
            issue('unlabeled_voice', f'reference_audios[{index}]',
                  'This voice slot has no named speaker. Check the audio tag in the compiled prompt.', 'warning')
    if scene['voices'] and not scene['audio']:
        issue('audio_disabled', 'generate_audio', 'Audio is off. The saved preset voices are omitted.', 'warning')
    current = {n['id']: n for n in p.app.named_library()}
    for named in scene['named']:
        latest = current.get(named['id'])
        if not latest or latest.get('archived'):
            issue('stale_identity', 'named', named['title']+' uses a snapshot of a missing or archived identity.', 'warning')
            continue
        if latest.get('voice') != named.get('voice'):
            issue('stale_voice', 'reference_audios', named['title']+' has a different voice in the current library. Review the shot assignment.', 'warning')
        bound_voice = next((v['voice'] for v in scene['voices'] if v['id'] == named.get('voiceId')), None)
        if named.get('voice') and bound_voice != named['voice']:
            issue('voice_binding_changed', 'reference_audios', named['title']+' has a missing or different voice binding in this shot.', 'warning')
        if [i.get('id') or i.get('src') for i in latest['images']] != [i.get('id') or i.get('src') for i in named['images']]:
            issue('stale_images', 'reference_images', named['title']+' uses an earlier set of library images. Review the saved shot snapshot.', 'warning')
    if video.get('archived'):
        issue('archived_video', 'video', 'Restore this video draft before rendering.')
    context = video.get('story_context') or {}
    if shot.get('episode_id') and context.get('script_revision') != p.app.stories.record('episodes', shot['episode_id'])['revision']:
        issue('stale_script', 'story_context', 'The script changed. Review the shot against the latest script context.', 'warning')

    request = None
    try:
        compiled = p.app.agent.compile(scene, validate=False)
        compiled['_studio_video_id'] = video['id']
        for message in start_frame_gate(p.app, compiled)['missing']:
            issue('start_frame_required', 'image', message)
        resolved = p.app.resolve(compiled)
        status = p.app.prompting.request_status(resolved, video['id'], scene)
        for item in status['prompt_issues']:
            issues.append({**item, 'field': 'prompt'})
        # Keep exact request fields, replacing inline media bytes with source/role
        # descriptors. The provider transport for recordings is created at render time.
        request = {k: v for k, v in resolved.items() if k not in
                   ('image', 'last_frame', 'keyframes', 'reference_images', 'reference_audios')}
        def source_descriptor(item):
            if item['asset_id']:
                return {'asset_id': item['asset_id']}
            if (item['src'] or '').startswith('data:'):
                return {'inline_image': True}
            return {'url': item['src']}

        for item in images:
            field = item['field'].split('[')[0]
            source = source_descriptor(item)
            if field == 'keyframes':
                request.setdefault(field, []).append({'image': source, 'timestamp_s': item['timestamp_s']})
            elif field == 'reference_images':
                request.setdefault(field, []).append(source)
            else:
                request[field] = source
        if resolved.get('reference_audios'):
            request['reference_audios'] = [
                {'voice_id': v['voice_id']} if 'voice_id' in v else {'recording_excerpt_id': scene['recording']['excerpt_id']}
                for v in resolved['reference_audios']]
    except (ValueError, OSError) as error:
        issue(getattr(error, 'code', 'invalid_request'), 'video', str(error) if isinstance(error, ValueError)
              else 'A saved media file could not be read. Check the attached images and audio.')
    intended = shot.get('intended_edit_duration')
    if intended is not None and intended > scene['duration']:
        issue('edit_longer_than_render', 'intended_edit_duration', 'The planned edit duration exceeds the render. Check for a hold or adjust the timing.', 'warning')
    return dict(shot_id=identity, shot_revision=shot['revision'], video_revision=video['revision'],
                model=scene['model'], resolution=scene['resolution'], aspect_ratio=scene['ratio'],
                render_duration=scene['duration'], intended_edit_duration=intended, images=images, voices=voices,
                recording=scene.get('recording'), request=request, issues=issues,
                valid=request is not None and not any(i['severity']=='error' for i in issues))
