"""OpenAPI contracts for /music-video, shared with the Agent API reference."""
from music_video import modes


def contracts(paths, operation):
    def obj(properties, required=()):
        return dict(type='object', properties=properties, required=list(required), additionalProperties=False)
    def ref(name):
        return {'$ref': '#/components/schemas/MusicVideo' + name}
    def arr(item):
        return dict(type='array', items=item)
    string, num = {'type': 'string'}, {'type': 'number'}
    revision = {'type': 'integer', 'minimum': 1}
    source = obj({'kind': {'enum': ['upload', 'take']}, 'id': string}, ('kind', 'id'))
    stems = obj({'vocal': source, 'instrumental': source})
    mode = {'enum': list(modes.MODES)}
    free = {'type': 'object'}
    schemas = {
        'MusicVideoSource': source, 'MusicVideoStems': stems,
        'MusicVideoProject': dict(type='object', required=['id', 'revision', 'mode', 'lyrics', 'shots', 'takes'], properties=dict(
            id=string, revision=revision, title=string, production_id=string, mode=mode, lyrics=string, master=free, stems=free,
            song_has_vocals={'type': ['boolean', 'null']}, spoken_lines={'type': ['array', 'null'], 'items': {'type': 'integer'}},
            price_per_second={'type': ['number', 'null']}, phase={'type': ['integer', 'null']}, line_times={'type': ['array', 'null'], 'items': {'type': 'object'}}, analysis={'type': ['object', 'null']},
            shots=arr(ref('Shot')), takes=free, created_at=num, updated_at=num)),
        'MusicVideoShot': dict(type='object', required=['kind', 'start', 'end'], properties=dict(
            id=string, kind={'enum': ['spoken', 'sung_cut', 'cutaway']}, line={'type': 'integer'}, text=string, start=num, end=num,
            bar_start={'type': 'integer'}, bar_end={'type': 'integer'}, speech_s=num, lead_in_s=num, section={'type': ['string', 'null']},
            prompt=string, purpose=string, audio={'enum': ['take', 'none']}, generate={'type': 'boolean'}, hook={'type': 'boolean'}, mode=mode)),
        'MusicVideoShotEdit': obj(dict(id=string, prompt=string, purpose=string, audio={'enum': ['take', 'none']},
                                       generate={'type': 'boolean'}, hook={'type': 'boolean'}), ('id',)),
        'MusicVideoCapabilities': obj(dict(schema_version={'const': 1}, modes=free, rules=arr(string), limits=free,
                                           generation={'const': False}, routes=arr(string)),
                                      ('schema_version', 'modes', 'rules', 'generation')),
        'MusicVideoAudit': dict(type='object', required=['ok', 'findings', 'estimate'], properties=dict(
            ok={'type': 'boolean'}, shots={'type': 'integer'}, shots_per_minute=num, findings=arr(free), estimate=free, takes=free)),
        'MusicVideoRenderPlan': dict(type='object', required=['mode', 'placements', 'mute_spans', 'lyric_gate'], properties=dict(
            mode=mode, placements=arr(free), mute_spans=arr(arr(num)), lyric_gate=free, approximate_lyric_lines={'type': 'integer'},
            notes=arr(string), file=string, bytes={'type': 'integer'}, duration=num)),
    }
    rev = obj({'expected_revision': revision}, ('expected_revision',))

    def add(path, method, summary, request=None, response=None, status='200'):
        op = operation(summary, request)
        op['responses'][status] = {'description': summary, 'content': {'application/json': {'schema': response or free}}}
        paths.setdefault('/music-video/' + path, {})[method] = op

    add('schema', 'get', 'Music-video modes, rules and limits; never generates', response=ref('Capabilities'))
    add('projects', 'get', 'List music-video projects', response=arr(ref('Project')))
    add('projects', 'post', 'Create a music video from a song, lyric sheet and delivery mode',
        obj(dict(title=string, production_id=string, mode=mode, master=source, stems=stems, lyrics=string,
                 song_has_vocals={'type': ['boolean', 'null']}, spoken_lines=arr({'type': 'integer'}),
                 price_per_second={'type': ['number', 'null']}), ('title', 'production_id', 'mode', 'master', 'lyrics')),
        ref('Project'), '201')
    add('projects/{id}', 'get', 'Read the project, analysis summary, board and takes', response=ref('Project'))
    add('projects/{id}', 'patch', 'Revise mode, lyrics, stems, spoken lines, downbeat phase; a changed plan clears the board',
        obj(dict(expected_revision=revision, mode=mode, lyrics=string, stems=stems, song_has_vocals={'type': ['boolean', 'null']},
                 spoken_lines=arr({'type': 'integer'}), price_per_second={'type': ['number', 'null']},
                 phase={'type': ['integer', 'null'], 'minimum': 0, 'maximum': 3}), ('expected_revision',)), ref('Project'))
    add('projects/{id}/analyze', 'post', 'Measure tempo, beats, bars, downbeat guess, sections locally; no generation', rev, ref('Project'))
    add('projects/{id}/align', 'post', 'Place each lyric line on the song clock from a timed transcript of the vocal; clears the board',
        obj(dict(expected_revision=revision, words=arr(obj(dict(w=string, s=num, e=num), ('w', 's', 'e')))), ('expected_revision', 'words')), free)
    add('projects/{id}/lint', 'get', 'Lyric problems, per-line delivery and bar-slot fit', response=free)
    add('projects/{id}/board/draft', 'post', 'Draft shots on bar lines for the chosen mode; clears earlier takes', rev, ref('Project'))
    add('projects/{id}/board', 'patch', 'Edit shot prompts, purposes and flags; kind and timing stay fixed',
        obj(dict(expected_revision=revision, shots=arr(ref('ShotEdit'))), ('expected_revision', 'shots')), ref('Project'))
    add('projects/{id}/audit', 'get', 'Mode-aware gate before any spend: bars, pacing, quotes, audio rules, cost ceiling', response=ref('Audit'))
    add('projects/{id}/takes', 'post', 'Attach a completed take to a shot; triages it, picks the best window for visual shots, measures speech placement for spoken shots',
        obj(dict(expected_revision=revision, shot_id=string, source=source, heard_words=arr(string), allow_retime={'type': 'boolean'},
                 window=obj(dict(in_point_s={'type': 'number', 'minimum': 0}, speed={'type': 'number', 'minimum': .8, 'maximum': 1}), ('in_point_s', 'speed'))),
            ('expected_revision', 'shot_id', 'source')), free, '201')
    spec = dict(type='object', required=['version', 'width', 'height', 'fps', 'duration', 'shots'], properties=dict(
        version={'const': 1}, width={'type': 'integer'}, height={'type': 'integer'}, fps={'type': 'integer'}, duration=num,
        set=free, actors=arr(free), shots=arr(free), tracks=arr(free), lyrics=arr(free)))
    add('projects/{id}/previz', 'get', 'Read the three.js previz spec (camera moves, staged actors, tracks) on the song clock', response=dict(type='object', properties=dict(revision=revision, spec=spec)))
    add('projects/{id}/previz', 'post', 'Generate a default previz spec from the board; never generates media',
        obj(dict(expected_revision=revision, story={'enum': ['generic', 'bedside_machine']}, width={'type': 'integer'},
                 height={'type': 'integer'}, fps={'type': 'integer'}), ('expected_revision',)), dict(type='object', properties=dict(revision=revision, spec=spec)))
    add('projects/{id}/previz', 'put', 'Replace the previz spec after strict validation (actors, shots, camera, tracks)',
        obj(dict(expected_revision=revision, spec=spec), ('expected_revision', 'spec')), dict(type='object', properties=dict(revision=revision, spec=spec)))
    add('projects/{id}/previz/render', 'post', 'Render the previz to MP4 with the song, headlessly and locally; free',
        obj(dict(expected_revision=revision, start=num, end=num), ('expected_revision',)), free)
    add('projects/{id}/previz/stills', 'post', 'Export clean previz stills (no label or lyrics) at the keyframe times; image-model composition reference only',
        obj(dict(expected_revision=revision, stills=arr(obj(dict(name=string, t=num), ('name', 't')))), ('expected_revision',)),
        dict(type='object', required=['revision', 'stills'], properties=dict(revision=revision, stills=arr(free), note=string)))
    refs = obj({role: {'type': ['string', 'null']} for role in ('character', 'machine', 'set', 'style')})
    keyframes = dict(type='object', required=['revision', 'plan', 'check'], properties=dict(
        revision=revision, plan=free, check=free, previz_stale={'type': 'boolean'}, rules=arr(string)))
    add('projects/{id}/keyframes', 'get', 'Read the keyframe plan with its checks and image cost ceiling', response=keyframes)
    add('projects/{id}/keyframes', 'post', 'Draft the keyframe plan from the board and previz: stills per shot, references, prompts, cost; never generates',
        obj(dict(expected_revision=revision, references=refs, candidates={'type': 'integer', 'minimum': 1, 'maximum': 8},
                 price_per_image={'type': ['number', 'null'], 'minimum': 0}, story={'enum': ['generic', 'bedside_machine']}), ('expected_revision',)), keyframes)
    add('projects/{id}/keyframes', 'patch', 'Edit still moments, prompts and times, references, candidates or price',
        obj(dict(expected_revision=revision, references=refs, candidates={'type': 'integer', 'minimum': 1, 'maximum': 8},
                 price_per_image={'type': ['number', 'null'], 'minimum': 0},
                 stills=arr(obj(dict(name=string, moment=string, prompt=string, t=num), ('name',)))), ('expected_revision',)), keyframes)
    approve = {'type': ['object', 'null'], 'additionalProperties': False, 'required': ['asset_id', 'human_words'],
               'properties': dict(asset_id=string, human_words={'type': 'string', 'minLength': 1, 'maxLength': 2000})}
    paths['/music-video/projects/{id}/keyframes']['patch']['requestBody']['content']['application/json']['schema']['properties'].update(
        agent=obj(dict(model=string, session_id=string, product=string), ('model', 'session_id')))
    paths['/music-video/projects/{id}/keyframes']['patch']['requestBody']['content']['application/json']['schema']['properties']['stills']['items']['properties'].update(
        candidates=arr(string), approve=approve, made_from_first={'type': 'boolean'}, derived_from={'type': ['string', 'null']}, continues={'type': ['string', 'null']})
    add('projects/{id}/keyframes/sheet', 'post', 'Comparison sheets: the previz composition beside each generated candidate, with the lyric line',
        obj(dict(shots=arr(string), per_page={'type': 'integer', 'minimum': 1, 'maximum': 12})), free)
    add('projects/{id}/keyframes/packet', 'post', 'Consistency-review packet for one candidate still: references, candidate, planned composition and look',
        obj(dict(still=string, asset_id=string), ('still', 'asset_id')), free)
    review = obj(dict(reviewer=obj(dict(model=string, session_id=string, product=string), ('model', 'session_id')),
                      scores=obj({a: {'type': 'number', 'minimum': 0, 'maximum': 10} for a in ('person', 'machine', 'room', 'look')},
                                 ('person', 'machine', 'room', 'look')),
                      issues=arr(free), images_examined={'type': 'integer', 'minimum': 1}, summary=string),
                 ('reviewer', 'scores', 'issues', 'images_examined'))
    add('projects/{id}/keyframes/reviews', 'post', 'Record an independent reviewer\'s consistency scores; Studio computes the suggestion',
        obj(dict(expected_revision=revision, still=string, asset_id=string, review=review), ('expected_revision', 'still', 'asset_id', 'review')), free, '201')
    add('projects/{id}/keyframes/handoff', 'post', 'Put approved stills into Studio scenes as first/last frames with the previz staging and camera (default: every approved shot with a scene)',
        obj(dict(expected_revision=revision, scenes={'type': 'object', 'additionalProperties': string}), ('expected_revision',)), free)
    add('projects/{id}/triage', 'post', 'Scan a candidate take for pops, flicker, black and frozen frames, and pick its best window; does not attach',
        obj(dict(shot_id=string, source=source, allow_retime={'type': 'boolean'}), ('shot_id', 'source')), free)
    sound = {'type': 'object'}
    add('projects/{id}/sound', 'get', 'Sound design settings: reveal dip, machine hum, voice room', response=free)
    add('projects/{id}/sound', 'patch', 'Change the sound design (reveal, hum, voice); applied at render',
        obj(dict(expected_revision=revision, sound=sound), ('expected_revision', 'sound')), free)
    add('projects/{id}/look', 'get', 'Color script per shot (phrase and palette), the strip image, grain and grade matching', response=free)
    add('projects/{id}/look', 'patch', 'Change section looks, grain and grade matching',
        obj(dict(expected_revision=revision, look={'type': 'object'}), ('expected_revision', 'look')), free)
    add('projects/{id}/release', 'post', 'Render each frame shape, check the hook, pick thumbnails and write captions; local, never generates',
        obj(dict(expected_revision=revision, formats=arr({'enum': ['9:16', '16:9', '1:1', '4:5']}), thumbnails={'type': 'integer', 'minimum': 0, 'maximum': 8},
                 captions={'type': 'boolean'}, lyrics_on_screen={'type': 'boolean'}, max_side={'type': 'integer', 'minimum': 160, 'maximum': 3840}),
            ('expected_revision',)), free)
    add('projects/{id}/line-times/refine', 'post', 'Move each aligned lyric line onto the vocal stem\'s voiced edges (transcripts start words early); clears the board',
        rev, free)
    add('projects/{id}/prompts', 'get', 'Lint every shot prompt for Grok failure modes: mood and posture words, pauses, smiles, text, camera habits, length', response=free)
    add('projects/{id}/prompts/draft', 'post', 'Draft Grok prompts in the short first-frame form for TODO (or named) shots, from keyframe moments and previz moves',
        obj(dict(expected_revision=revision, shots=arr(string), overwrite={'type': 'boolean'}, speaker={'type': 'string', 'maxLength': 80}), ('expected_revision',)), free)
    add('projects/{id}/takes/last-frame', 'post', 'Save a take\'s own last used frame and offer it as the next shot\'s opening frame (a continuation)',
        obj(dict(expected_revision=revision, shot_id=string, to_shot=string), ('expected_revision', 'shot_id', 'to_shot')), free, '201')
    add('projects/{id}/cut/sheets', 'post', 'Fresh-eyes review sheets of a rendered cut (eight frames per shot as cut), a flash check and the reviewer brief',
        obj(dict(file=string), ('file',)), free)
    add('projects/{id}/cut/reviews', 'post', 'Record one fresh-eyes review of a cut (a verdict for every shot); two reviews before the human watches',
        obj(dict(expected_revision=revision, file=string, review=obj(dict(reviewer=obj(dict(model=string, session_id=string, product=string), ('model', 'session_id')),
                 shots=arr(obj(dict(shot_id=string, verdict={'enum': ['ok', 'polish', 'blocking']}, problem=string, fix=string), ('shot_id', 'verdict'))),
                 frames_examined={'type': 'integer', 'minimum': 1}, summary=string), ('reviewer', 'shots', 'frames_examined'))),
            ('expected_revision', 'file', 'review')), free, '201')
    add('projects/{id}/code-shots', 'post', 'Render a visual-only shot from the stage spec, without labels, and attach it as the take; free',
        obj(dict(expected_revision=revision, shot_id=string, width={'type': 'integer'}, height={'type': 'integer'}), ('expected_revision', 'shot_id')), free, '201')
    layer = obj(dict(kind={'enum': ['rect', 'ellipse', 'polygon', 'path']}, fill=string, depth={'type': 'number', 'minimum': 0, 'maximum': 6},
                     x=num, y=num, w=num, h=num, r=num, cx=num, cy=num, rx=num, ry=num, points=arr(arr(num)), d=string), ('kind', 'fill'))
    add('projects/{id}/plates', 'post', 'Paint a cut-paper set plate in code (layers or SVG), save it as an image asset, optionally as the set reference',
        obj(dict(expected_revision=revision, name=string, width={'type': 'integer'}, height={'type': 'integer'}, svg=string, background=string,
                 layers=arr(layer), palette=arr(string), grain={'type': 'number', 'minimum': 0, 'maximum': 1}, shadow={'type': 'number', 'minimum': 0, 'maximum': 1},
                 use_as_set={'type': 'boolean'}), ('expected_revision', 'name')), free, '201')
    add('projects/{id}/transcribe', 'post', 'Start a local word-timed transcription of the vocal stem (or master); poll transcribe-jobs/{id}; no downloads',
        obj(dict(source={'enum': ['vocal', 'master']}, model_folder=string, language={'type': ['string', 'null']})), free, '202')
    add('transcribe-jobs/{id}', 'get', 'Poll a transcription job; when done it holds the words {w, s, e} for align', response=free)
    add('projects/{id}/scenes', 'post', 'Create one Studio scene per board shot (once) and remember the mapping for hand-off, kits and plans',
        obj(dict(expected_revision=revision, shots=arr(string)), ('expected_revision',)), free)
    add('projects/{id}/files', 'get', 'List the files this project wrote (cuts, sheets, stills, plates, thumbnails, captions) with download ids', response=free)
    add('projects/{id}/files/{file_id}', 'get', 'Download one project file', response=dict(type='string', format='binary'))
    paths['/music-video/projects/{id}/files/{file_id}']['get']['responses']['200'] = {'description': 'Binary file', 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}
    add('projects/{id}/render-plan', 'post', 'Preview placements, mute spans and the lyric gate without writing a file',
        obj(dict(expected_revision=revision, width={'type': 'integer'}, height={'type': 'integer'}, lyrics_on_screen={'type': 'boolean'}),
            ('expected_revision',)), ref('RenderPlan'))
    add('projects/{id}/render', 'post', 'Render the cut locally with FFmpeg into the workspace; free, never generates',
        obj(dict(expected_revision=revision, width={'type': 'integer'}, height={'type': 'integer'}, lyrics_on_screen={'type': 'boolean'}),
            ('expected_revision',)), ref('RenderPlan'))
    return schemas
