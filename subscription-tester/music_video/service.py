"""Agent API surface for the music-video toolkit: /agent/v1/music-video/...

Everything here is local and free. It never generates media; takes come from the normal production flow and are
attached here by reference. See MUSIC_VIDEO_GUIDE.md.
"""
import base64
import copy
import hashlib
import json
import re
import time
from pathlib import Path

from agent_api import APIError
from music_video import (audio_io, beats as beatmod, board as boardmod, gates, grade as grademod, grokprompt, keyframes as keymod, lyric_text,
                         lyrics as lyricmod, modes, plates as platemod, previz as previzmod, release as releasemod, render, review as reviewmod,
                         sound as soundmod, speech, stemtimes, triage)

KIND = 'mv-project'
SOURCE_KEYS = ('kind', 'id')
EDITABLE = ('prompt', 'purpose', 'audio', 'generate', 'hook')
ROUTES = ['schema', 'projects', 'projects/{id}', 'projects/{id}/analyze', 'projects/{id}/align', 'projects/{id}/lint', 'projects/{id}/board/draft',
          'projects/{id}/board', 'projects/{id}/audit', 'projects/{id}/takes', 'projects/{id}/render-plan',
          'projects/{id}/previz', 'projects/{id}/previz/render', 'projects/{id}/previz/stills', 'projects/{id}/keyframes',
          'projects/{id}/keyframes/sheet', 'projects/{id}/keyframes/packet', 'projects/{id}/keyframes/reviews', 'projects/{id}/keyframes/handoff',
          'projects/{id}/triage', 'projects/{id}/sound', 'projects/{id}/look', 'projects/{id}/render', 'projects/{id}/release',
          'projects/{id}/line-times/refine', 'projects/{id}/prompts', 'projects/{id}/prompts/draft', 'projects/{id}/takes/last-frame',
          'projects/{id}/cut/sheets', 'projects/{id}/cut/reviews', 'projects/{id}/code-shots', 'projects/{id}/plates',
          'projects/{id}/transcribe', 'transcribe-jobs/{id}', 'projects/{id}/scenes', 'projects/{id}/files', 'projects/{id}/files/{file_id}']
MIME = {'.mp4': 'video/mp4', '.png': 'image/png', '.jpg': 'image/jpeg', '.srt': 'text/plain; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml'}
JOB_KIND = 'mv-transcribe-job'


def fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required) - set(data):
        raise APIError('invalid_music_video_request', 'Use the documented fields: ' + ', '.join(sorted(allowed)))
    if 'expected_revision' in data and (type(data['expected_revision']) is not int or data['expected_revision'] < 1):
        raise APIError('invalid_music_video_revision', 'expected_revision must be a positive integer.')


def number(value, low, high, name):
    if type(value) not in (int, float) or not low <= value <= high or value != value:
        raise APIError('invalid_music_video_request', f'{name} must be a number from {low} to {high}.')
    return value


class MusicVideo:
    def __init__(self, app):
        self.app = app
        self.p = app.productions
        self.e = app.editing

    # --- helpers -----------------------------------------------------------------------------------------------
    def schema(self):
        return dict(schema_version=1, modes={k: {f: v for f, v in m.items()} for k, m in modes.MODES.items()},
                    rules=['Audio generated while simulating singing is never used; only a spoken take contributes sound.',
                           'Visual-only shots generate no audio and their prompts must not ask the model to sing, speak or quote words.',
                           'Takes are slipped by trimming their start (picture and sound together), never stretched.',
                           'Cuts land on bar lines; the downbeat phase is a guess until the director confirms it.'],
                    limits=dict(max_take_seconds=lyricmod.MAX_CLIP_S, shots_per_minute=[boardmod.TAKE_MIN_PER_MIN, boardmod.TAKE_MAX_PER_MIN]),
                    generation=False, routes=list(ROUTES))

    def get(self, identity):
        return self.p.get(identity, KIND)

    def save(self, project, **changes):
        if 'shots' in changes and not changes['shots']:
            changes.setdefault('previz', None)            # a redrafted board invalidates its 3D previz
            changes.setdefault('keyframes', None)         # and its keyframe plan
        project.update(changes, revision=project['revision'] + 1)
        return self.p.put(KIND, project)

    def view(self, project):
        out = copy.deepcopy(project)
        if out.get('analysis'):
            a = out['analysis']
            out['analysis'] = {k: v for k, v in a.items() if k not in ('beats', 'hits')}
            out['analysis']['beat_count'] = len(a['beats'])
            out['analysis']['hit_count'] = len(a.get('hits', []))
        return out

    def media(self, source, audio=False, video=False):
        fields(source, SOURCE_KEYS, SOURCE_KEYS)
        meta, path = self.e.source(source)
        if audio and not meta.get('audio') or video and not meta.get('video'):
            raise APIError('invalid_music_video_source', 'Choose media with the required audio/video stream.')
        if path is None:
            raise APIError('invalid_music_video_source', 'A gap cannot be used here.')
        return meta, Path(path)

    def audio_path(self, source):
        return self.media(source, audio=True)[1]

    def need_analysis(self, project):
        if not project.get('analysis'):
            raise APIError('analysis_required', 'Analyze the song first (POST projects/{id}/analyze).', 409)
        return project['analysis']

    def options(self, project):
        return dict(song_has_vocals=project.get('song_has_vocals'), vocal_stem=project['stems'].get('vocal'),
                    instrumental_stem=project['stems'].get('instrumental'))

    # --- projects ----------------------------------------------------------------------------------------------
    def create(self, data):
        fields(data, ('title', 'production_id', 'mode', 'master', 'stems', 'lyrics', 'song_has_vocals', 'spoken_lines',
                      'price_per_second'), ('title', 'production_id', 'mode', 'master', 'lyrics'))
        self.p.get(data['production_id'], 'production')
        modes.check(data['mode']) if data['mode'] in modes.MODES else self.bad_mode()
        title = data['title'].strip() if isinstance(data['title'], str) else ''
        if not title or len(title) > 120:
            raise APIError('invalid_music_video_request', 'Name the music video (up to 120 characters).')
        meta, path = self.media(data['master'], audio=True)
        stems = data.get('stems', {})
        fields(stems, ('vocal', 'instrumental'))
        for source in stems.values():
            self.media(source, audio=True)
        sheet = self.sheet(data['lyrics'])
        return self.p.new(KIND, title=title, production_id=data['production_id'], mode=data['mode'],
                          lyrics=sheet, master=dict(source=data['master'], duration=audio_io.duration(path)),
                          stems=stems, song_has_vocals=data.get('song_has_vocals'),
                          spoken_lines=self.lines_ok(data.get('spoken_lines'), sheet), price_per_second=self.price(data.get('price_per_second')),
                          phase=None, analysis=None, line_times=None, shots=[], takes={}, previz=None, keyframes=None)

    @staticmethod
    def bad_mode():
        raise APIError('invalid_music_video_mode', 'Choose a mode: ' + ', '.join(modes.MODES))

    @staticmethod
    def sheet(text):
        if not isinstance(text, str) or len(text) > 20000 or not text.strip():
            raise APIError('invalid_music_video_request', 'Provide the lyric sheet (up to 20,000 characters).')
        return text

    @staticmethod
    def price(value):
        return None if value is None else number(value, 0, 1000, 'price_per_second')

    @staticmethod
    def lines_ok(value, sheet):
        if value is None:
            return None
        count = len(lyricmod.parse(sheet))
        if not isinstance(value, list) or any(type(i) is not int or not 0 <= i < count for i in value):
            raise APIError('invalid_music_video_request', f'spoken_lines are line numbers from 0 to {count - 1}.')
        return sorted(set(value))

    def patch(self, identity, data):
        fields(data, ('expected_revision', 'mode', 'lyrics', 'stems', 'song_has_vocals', 'spoken_lines', 'price_per_second', 'phase'),
               ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        changes = {}
        if 'mode' in data:
            if data['mode'] not in modes.MODES:
                self.bad_mode()
            changes['mode'] = data['mode']
        if 'lyrics' in data:
            changes['lyrics'] = self.sheet(data['lyrics'])
        if 'stems' in data:
            fields(data['stems'], ('vocal', 'instrumental'))
            for source in data['stems'].values():
                self.media(source, audio=True)
            changes['stems'] = data['stems']
        for key in ('song_has_vocals',):
            if key in data:
                changes[key] = data[key]
        if 'price_per_second' in data:
            changes['price_per_second'] = self.price(data['price_per_second'])
        if 'phase' in data:
            if data['phase'] is not None and (type(data['phase']) is not int or not 0 <= data['phase'] < 4):
                raise APIError('invalid_music_video_request', 'phase is 0-3 (which beat of the bar is the downbeat), or null.')
            changes['phase'] = data['phase']
            if p.get('analysis') and data['phase'] is not None:
                changes['analysis'] = beatmod.rebar(p['analysis'], data['phase'])
        sheet = changes.get('lyrics', p['lyrics'])
        if 'spoken_lines' in data or 'lyrics' in data:
            changes['spoken_lines'] = self.lines_ok(data.get('spoken_lines', p.get('spoken_lines')), sheet)
        stale = any(k in changes for k in ('mode', 'lyrics', 'spoken_lines', 'phase'))
        if stale and p['shots']:
            changes.update(shots=[], takes={})        # a changed plan invalidates the board and its takes: redraft
        if 'lyrics' in changes:
            changes['line_times'] = None
        return self.view(self.save(p, **changes))

    def analyze(self, identity, data):
        fields(data, ('expected_revision',), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        try:
            analysis = beatmod.analyze(self.audio_path(p['master']['source']), phase=p.get('phase'))
        except audio_io.AudioError as error:
            raise APIError('analysis_failed', str(error)) from None
        return self.view(self.save(p, analysis=analysis, shots=[], takes={}))

    def align(self, identity, data):
        fields(data, ('expected_revision', 'words'), ('expected_revision', 'words'))
        p = self.get(identity)
        self.p.check(p, data)
        words = data['words']
        if not isinstance(words, list) or not words or len(words) > 5000 or any(
                not isinstance(w, dict) or set(w) != {'w', 's', 'e'} or not isinstance(w['w'], str)
                or type(w['s']) not in (int, float) or type(w['e']) not in (int, float) or not 0 <= w['s'] <= w['e'] <= 3600
                for w in words):
            raise APIError('invalid_music_video_request', 'words is a list of {w, s, e}: a word and its start/end seconds.')
        times = lyricmod.align_words(p['lyrics'], words)
        missing = [t['line'] for t in times if t['start'] is None]
        check = speech.compare_words(p['lyrics'], [w['w'] for w in words])
        saved = self.save(p, line_times=times, shots=[], takes={})
        return dict(project=self.view(saved), unmatched_lines=missing, word_check=check)

    def lint(self, identity):
        p = self.get(identity)
        out = dict(issues=lyricmod.lint(p['lyrics']), lines=len(lyricmod.parse(p['lyrics'])),
                   delivery=modes.delivery(p['mode'], lyricmod.parse(p['lyrics']), p.get('spoken_lines')))
        if p.get('analysis'):
            a = p['analysis']
            bar = (a['bars'][-1] - a['bars'][0]) / max(1, len(a['bars']) - 1)
            out['fit'] = lyricmod.fit_to_grid(lyricmod.parse(p['lyrics']), bar)
        return out

    # --- board -------------------------------------------------------------------------------------------------
    def board_draft(self, identity, data):
        fields(data, ('expected_revision',), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        a = self.need_analysis(p)
        issues = [i for i in lyricmod.lint(p['lyrics'])]
        if issues:
            raise APIError('lyrics_need_fixing', 'Fix the lyric sheet first: ' + '; '.join(f"line {i['line'] + 1}: {i['message']}" for i in issues[:4]), 409)
        try:
            shots = boardmod.draft(a, p['lyrics'], mode=p['mode'], spoken_lines=p.get('spoken_lines'), line_times=p.get('line_times'))
        except ValueError as error:
            raise APIError('board_draft_failed', str(error), 409) from None
        return self.view(self.save(p, shots=shots, takes={}, previz=None, keyframes=None))

    def patch_board(self, identity, data):
        fields(data, ('expected_revision', 'shots'), ('expected_revision', 'shots'))
        p = self.get(identity)
        self.p.check(p, data)
        if not isinstance(data['shots'], list):
            raise APIError('invalid_music_video_request', 'shots must be a list of {id, ...fields}.')
        index = {s['id']: s for s in p['shots']}
        shots = copy.deepcopy(p['shots'])
        by_id = {s['id']: s for s in shots}
        for change in data['shots']:
            if not isinstance(change, dict) or change.get('id') not in index:
                raise APIError('unknown_shot', 'Each change needs the id of a shot on this board.', 404)
            extra = set(change) - set(EDITABLE) - {'id'}
            if extra:
                raise APIError('invalid_music_video_request', 'Editable shot fields: ' + ', '.join(EDITABLE) + '.')
            for key in EDITABLE:
                if key in change:
                    by_id[change['id']][key] = change[key]
        for s in shots:                       # the rules that hold whatever the director types
            if s['kind'] != 'spoken':
                s['audio'] = 'none' if s.get('audio') in (None, 'none') else s['audio']
        return self.view(self.save(p, shots=shots))

    def audit(self, identity):
        p = self.get(identity)
        a = self.need_analysis(p)
        if not p['shots']:
            raise APIError('board_required', 'Draft the board first (POST projects/{id}/board/draft).', 409)
        result = boardmod.audit(p['shots'], a, p['lyrics'], p.get('price_per_second'), p['mode'], self.options(p))
        extra = gates.check(p['shots'], p.get('previz'), p.get('keyframes'))
        for s in p['shots']:
            if p['takes'].get(s['id'], {}).get('code'):
                continue
            for f in grokprompt.lint(s.get('prompt'), s['kind'], s.get('text'), s['end'] - s['start']):
                if f['kind'] not in ('quote_mismatch', 'no_quote', 'vocal_in_visual_prompt', 'over_take_limit'):   # the board audit owns these
                    extra.append(dict(f, shot=s['id'], kind='prompt_' + f['kind']))
        result['findings'] += extra
        result['ok'] = not any(f['severity'] == 'error' for f in result['findings'])
        result['takes'] = {sid: dict(placement=t.get('placement'), pace=t.get('pace'), words=t.get('words'))
                           for sid, t in p['takes'].items()}
        return result

    # --- takes -------------------------------------------------------------------------------------------------
    def attach_take(self, identity, data):
        fields(data, ('expected_revision', 'shot_id', 'source', 'heard_words', 'allow_retime', 'window'), ('expected_revision', 'shot_id', 'source'))
        p = self.get(identity)
        self.p.check(p, data)
        a = self.need_analysis(p)
        shot = next((s for s in p['shots'] if s['id'] == data['shot_id']), None)
        if not shot:
            raise APIError('unknown_shot', 'That shot is not on this board.', 404)
        meta, path = self.media(data['source'], video=True)
        slot = shot['end'] - shot['start']
        entry = dict(source=data['source'], clip_duration=meta.get('duration'), audio_used=shot['kind'] == 'spoken')
        report = self.scan(path)
        if shot['kind'] == 'spoken':
            if not meta.get('audio'):
                raise APIError('take_has_no_audio', 'A spoken shot needs a take with its own audio: generate it with audio on.', 409)
            take = speech.measure(path)
            entry['measurement'] = take
            if take['speech']:
                placement = speech.place_on_beat(take, a['beats'], shot['start'], trim_only=True, min_in_point=speech.SKIP_S)
                entry['placement'] = placement
                entry['pace'] = speech.pace_check(take, shot['speech_s'])
                if placement.get('timeline_start_s') is not None:
                    t0 = placement['timeline_start_s'] + 0.0
                    entry['placement'].update(speech_start=round(shot['start'] + take['first_speech_s'] - placement['in_point_s'], 3),
                                              speech_end=round(shot['start'] + take['last_speech_s'] - placement['in_point_s'], 3),
                                              clip_long_enough=(meta.get('duration') or 0) >= placement['in_point_s'] + slot - 1 / 24)
            if data.get('heard_words') is not None:
                if not isinstance(data['heard_words'], list) or not all(isinstance(w, str) for w in data['heard_words']):
                    raise APIError('invalid_music_video_request', 'heard_words is a list of words from a transcript.')
                entry['words'] = speech.compare_words(shot['text'], data['heard_words'])
            if report:
                start = (entry.get('placement') or {}).get('in_point_s') or 0
                entry['triage'] = dict(triage.summary(report), issues_in_use=triage.spoken_window_issues(report, start, slot))
        else:
            if report:
                entry['triage'] = triage.summary(report)
                entry['window'] = self.window_for(shot, report, a, data)
                entry['clip_long_enough'] = entry['window']['ok']
            else:
                entry['clip_long_enough'] = (meta.get('duration') or 0) >= slot - 1 / 24
        takes = dict(p['takes'])
        takes[shot['id']] = entry
        saved = self.save(p, takes=takes)
        return dict(shot_id=shot['id'], take=entry, revision=saved['revision'])

    # --- triage ------------------------------------------------------------------------------------------------
    @staticmethod
    def scan(path):
        try:
            return triage.scan(path)
        except audio_io.AudioError:
            return None

    @staticmethod
    def beat_offsets(shot, analysis):
        return [round(b - shot['start'], 3) for b in analysis['beats'] if shot['start'] - 1e-6 <= b < shot['end']]

    def window_for(self, shot, report, analysis, data):
        slot = shot['end'] - shot['start']
        if data.get('window') is not None:
            w = data['window']
            if not isinstance(w, dict) or set(w) != {'in_point_s', 'speed'} or type(w['speed']) not in (int, float) \
                    or not triage.MIN_SPEED <= w['speed'] <= 1 or type(w['in_point_s']) not in (int, float) or w['in_point_s'] < speech.SKIP_S - 1e-6:
                raise APIError('invalid_music_video_request', f'window is {{in_point_s >= {speech.SKIP_S:.3f} (never the first two frames), speed {triage.MIN_SPEED}-1}}.')
            span = slot * w['speed']
            ok = w['in_point_s'] + span <= report['duration'] + 1 / 24
            return dict(ok=ok, in_point_s=round(float(w['in_point_s']), 3), speed=float(w['speed']), source_span_s=round(span, 3), retimed=w['speed'] < 1,
                        chosen_by='director', issues=[x for x in report['issues'] if x['end'] > w['in_point_s'] and x['start'] < w['in_point_s'] + span],
                        **({} if ok else {'reason': 'The window runs past the end of the take.'}))
        allow = data.get('allow_retime', False)
        if type(allow) is not bool:
            raise APIError('invalid_music_video_request', 'allow_retime is true or false.')
        return dict(triage.best_window(report, slot, self.beat_offsets(shot, analysis), allow_retime=allow), chosen_by='triage')

    def triage_take(self, identity, data):
        """Scan a candidate take for a shot without attaching it, to compare takes."""
        fields(data, ('shot_id', 'source', 'allow_retime'), ('shot_id', 'source'))
        p = self.get(identity)
        a = self.need_analysis(p)
        shot = next((s for s in p['shots'] if s['id'] == data['shot_id']), None)
        if not shot:
            raise APIError('unknown_shot', 'That shot is not on this board.', 404)
        _, path = self.media(data['source'], video=True)
        try:
            report = triage.scan(path)
        except audio_io.AudioError as error:
            raise APIError('triage_failed', str(error)) from None
        out = dict(shot_id=shot['id'], kind=shot['kind'], triage=triage.summary(report))
        if shot['kind'] == 'spoken':
            out['note'] = 'Spoken takes are trimmed, never retimed; attach it to measure the speech placement.'
        else:
            out['window'] = self.window_for(shot, report, a, data)
        return out

    # --- sound and look ------------------------------------------------------------------------------------------
    def sound_view(self, p):
        return dict(revision=p['revision'], sound=soundmod.settings(p.get('sound')), defaults=soundmod.DEFAULT,
                    notes=['The reveal dip, hum and voice room apply at render; render-plan shows the timing.',
                           'Only the spoken take and the song (or its stems) are used; no generated singing.'])

    def sound_patch(self, identity, data):
        fields(data, ('expected_revision', 'sound'), ('expected_revision', 'sound'))
        p = self.get(identity)
        self.p.check(p, data)
        try:
            cfg = soundmod.settings(p.get('sound'), data['sound'])
        except soundmod.SoundError as error:
            raise APIError('invalid_music_video_request', str(error)) from None
        if cfg['reveal'].get('shot_id') and not any(s['id'] == cfg['reveal']['shot_id'] and s['kind'] == 'spoken' for s in p['shots']):
            raise APIError('unknown_shot', 'sound.reveal.shot_id must name a spoken shot on this board.', 404)
        return self.sound_view(self.save(p, sound=cfg))

    def look_view(self, p, draw=True):
        look = grademod.settings(p.get('look'))
        rows = grademod.color_script(p['shots'], look) if p['shots'] else []
        out = dict(revision=p['revision'], look=look, color_script=rows)
        if draw and rows:
            f = self.app.storage / 'music-video' / p['id'] / f"color-script-r{p['revision']}.png"
            grademod.strip(rows, f)
            out['strip'] = str(f.relative_to(self.app.storage))
        return out

    def look_patch(self, identity, data):
        fields(data, ('expected_revision', 'look'), ('expected_revision', 'look'))
        p = self.get(identity)
        self.p.check(p, data)
        try:
            look = grademod.settings(p.get('look'), data['look'])
        except grademod.GradeError as error:
            raise APIError('invalid_music_video_request', str(error)) from None
        return self.look_view(self.save(p, look=look))

    # --- files ------------------------------------------------------------------------------------------------
    def folder(self, p):
        return self.app.storage / 'music-video' / p['id']

    @staticmethod
    def file_id(rel):
        return hashlib.sha256(rel.encode()).hexdigest()[:16]

    def files(self, identity):
        """Everything this project has written (cuts, sheets, stills, plates, thumbnails, captions), with download ids."""
        p = self.get(identity)
        base = self.folder(p)
        rows = []
        if base.is_dir():
            for f in sorted(base.rglob('*')):
                if f.is_file() and f.suffix.lower() in MIME:
                    rel = self.rel(f)
                    rows.append(dict(file=rel, file_id=self.file_id(rel), bytes=f.stat().st_size,
                                     download=f"GET music-video/projects/{p['id']}/files/{self.file_id(rel)}"))
        return dict(project_id=p['id'], files=rows)

    def download(self, identity, file_id):
        p = self.get(identity)
        base = self.folder(p)
        if base.is_dir() and re.fullmatch(r'[0-9a-f]{16}', file_id):
            for f in base.rglob('*'):
                if f.is_file() and f.suffix.lower() in MIME and self.file_id(self.rel(f)) == file_id:
                    return f.read_bytes(), MIME[f.suffix.lower()]
        raise APIError('not_found', 'No such file in this project (list them with GET projects/{id}/files).', 404)

    # --- transcription ----------------------------------------------------------------------------------------
    transcriber = None          # tests replace this with a callable(path) -> [{w, s, e}]

    def transcribe(self, identity, data):
        """Start a local word-timed transcription of the vocal stem (or the master). Poll transcribe-jobs/{id}."""
        fields(data, ('source', 'model_folder', 'language'))
        p = self.get(identity)
        which = data.get('source', 'vocal')
        if which not in ('vocal', 'master'):
            raise APIError('invalid_music_video_request', 'source is vocal (the stem, best) or master.')
        if which == 'vocal' and not p['stems'].get('vocal'):
            raise APIError('vocal_stem_required', 'Add the vocal stem first, or transcribe the master (less accurate under music).', 409)
        folder = data.get('model_folder')
        if folder is not None:
            if not isinstance(folder, str) or not Path(folder).is_absolute() or not (Path(folder) / 'model.bin').is_file():
                raise APIError('invalid_music_video_request', 'model_folder is an absolute path to a converted Whisper model (with model.bin).')
        else:
            folder = str(self.e.transcription_model())
        language = data.get('language', 'en')
        if language is not None and (not isinstance(language, str) or not re.fullmatch(r'[a-z]{2}', language)):
            raise APIError('invalid_music_video_request', 'language is a two-letter code (for example en), or null to detect it.')
        if self.transcriber is None:
            import importlib.util
            if importlib.util.find_spec('faster_whisper') is None or not (Path(folder) / 'model.bin').is_file():
                raise APIError('transcriber_unavailable', 'No local transcriber and model are available (install the transcription extra and a converted '
                               'Whisper model, or set model_folder). Nothing is downloaded. You can still align with word times from elsewhere.', 503)
        path = self.audio_path(p['stems']['vocal'] if which == 'vocal' else p['master']['source'])
        job = self.p.new(JOB_KIND, project_id=p['id'], source=which, status='queued', model_folder=folder, language=language, words=None, error=None)
        self.app.spawn(self.transcribe_worker, job['id'], str(path))
        return self.job_view(job)

    def transcribe_worker(self, job_id, path):
        job = self.p.get(job_id, JOB_KIND)
        job.update(status='running', started_at=time.time())
        self.p.put(JOB_KIND, job)
        try:
            if self.transcriber is not None:
                words = self.transcriber(path)
            else:
                from faster_whisper import WhisperModel
                model = WhisperModel(job['model_folder'], local_files_only=True, device='cpu', compute_type='int8')
                segments, _ = model.transcribe(path, language=job['language'], word_timestamps=True, vad_filter=True,
                                               condition_on_previous_text=False, beam_size=5)
                words = [dict(w=w.word.strip(), s=round(w.start, 3), e=round(w.end, 3)) for seg in segments for w in (seg.words or []) if w.word.strip()]
            job.update(status='done', words=words, finished_at=time.time())
        except Exception as error:                                   # the job reports it; the server keeps running
            job.update(status='error', error=f'Local transcription failed: {str(error)[:300]}', finished_at=time.time())
        self.p.put(JOB_KIND, job)

    def job_view(self, job):
        out = {k: job[k] for k in ('id', 'project_id', 'source', 'status', 'language', 'error') if k in job}
        if job.get('words') is not None:
            out['words'] = job['words']
            out['next'] = f"POST music-video/projects/{job['project_id']}/align with these words, then line-times/refine."
        return out

    # --- Studio scenes for the board ----------------------------------------------------------------------------
    def board_scenes(self, identity, data):
        """Create one Studio scene per board shot (once), so shot kits, plans and takes work per shot."""
        fields(data, ('expected_revision', 'shots'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p['shots']:
            raise APIError('board_required', 'Draft the board first (POST projects/{id}/board/draft).', 409)
        want = data.get('shots')
        if want is not None and (not isinstance(want, list) or not set(want) <= {s['id'] for s in p['shots']}):
            raise APIError('unknown_shot', 'shots lists ids of shots on this board.', 404)
        mapping = dict(p.get('scenes') or {})
        created = []
        for s in sorted(p['shots'], key=lambda x: x['start']):
            if want is not None and s['id'] not in want:
                continue
            if mapping.get(s['id']):
                try:
                    self.agent_call('GET', f"scenes/{mapping[s['id']]}")
                    continue
                except APIError:
                    pass                                   # the scene was deleted; make a new one
            prompt = s.get('prompt') if str(s.get('prompt', '')).strip() not in ('', 'TODO') else (s.get('text') or s.get('purpose') or s['kind'])
            label = s.get('section') or s['kind']
            scene = self.agent_call('POST', 'scenes', {'title': f"{p['title'][:60]} {s['id']} {label}"[:120], 'scene': {'prompt': prompt[:4000]}})
            mapping[s['id']] = scene['id']
            created.append(dict(shot_id=s['id'], scene_id=scene['id']))
        saved = self.save(p, scenes=mapping)
        return dict(revision=saved['revision'], scenes=mapping, created=created,
                    note='Each board shot now has its own Studio scene: build its shot kit, hand off approved stills, then plan and generate as usual.')

    # --- line times from the stem -----------------------------------------------------------------------------
    def refine_lines(self, identity, data):
        fields(data, ('expected_revision',), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p.get('line_times'):
            raise APIError('line_times_required', 'Align the lyrics first (POST projects/{id}/align).', 409)
        if not p['stems'].get('vocal'):
            raise APIError('vocal_stem_required', 'Add the vocal stem (PATCH stems.vocal) to time lines from its level.', 409)
        try:
            times = stemtimes.refine(p['line_times'], self.audio_path(p['stems']['vocal']))
        except audio_io.AudioError as error:
            raise APIError('analysis_failed', str(error)) from None
        changes = dict(line_times=times)
        if p['shots']:
            changes.update(shots=[], takes={})
        saved = self.save(p, **changes)
        moved = [t for t in times if t.get('source') == 'stem' and (abs(t['moved_start_s']) >= .1 or abs(t['moved_end_s']) >= .1)]
        return dict(project=self.view(saved), moved=moved, unchanged=[t['line'] for t in times if t.get('source') != 'stem'],
                    note='Line edges now follow the vocal stem; redraft the board.' if p['shots'] else 'Line edges now follow the vocal stem.')

    # --- Grok prompts --------------------------------------------------------------------------------------------
    def prompts_lint(self, identity):
        p = self.get(identity)
        return dict(revision=p['revision'], shots=[dict(shot_id=s['id'], kind=s['kind'], words=len(grokprompt.words(s.get('prompt'))),
                                                        findings=grokprompt.lint(s.get('prompt'), s['kind'], s.get('text'), s['end'] - s['start']))
                                                   for s in p['shots']])

    def prompts_draft(self, identity, data):
        """Draft Grok prompts for shots still marked TODO (or the named ones), from the keyframe moments and previz."""
        fields(data, ('expected_revision', 'shots', 'overwrite', 'speaker'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p['shots']:
            raise APIError('board_required', 'Draft the board first (POST projects/{id}/board/draft).', 409)
        want = data.get('shots')
        if want is not None and (not isinstance(want, list) or not set(want) <= {s['id'] for s in p['shots']}):
            raise APIError('unknown_shot', 'shots lists ids of shots on this board.', 404)
        speaker = data.get('speaker', 'the speaker')
        if not isinstance(speaker, str) or not 0 < len(speaker) <= 80:
            raise APIError('invalid_music_video_request', 'speaker names who speaks the spoken lines (up to 80 characters).')
        moves = {s['id']: s.get('move') for s in (p.get('previz') or {}).get('shots', [])}
        moments = {s['shot_id']: next((x['moment'] for x in s['stills'] if x['role'] == 'first'), None) for s in (p.get('keyframes') or {}).get('shots', [])}
        shots = copy.deepcopy(p['shots'])
        written = []
        for s in shots:
            if want is not None and s['id'] not in want:
                continue
            if not data.get('overwrite') and str(s.get('prompt', '')).strip() not in ('', 'TODO'):
                continue
            s['prompt'] = grokprompt.write(s, moments.get(s['id']), moves.get(s['id']), speaker)
            written.append(s['id'])
        saved = self.save(p, shots=shots)
        return dict(project=self.view(saved), written=written, lint=self.prompts_lint(identity)['shots'])

    # --- previz ------------------------------------------------------------------------------------------------
    def previz_generate(self, identity, data):
        fields(data, ('expected_revision', 'story', 'width', 'height', 'fps'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        a = self.need_analysis(p)
        if not p['shots']:
            raise APIError('board_required', 'Draft the board first (POST projects/{id}/board/draft).', 409)
        lines = {l['line']: l for l in lyricmod.parse(p['lyrics'])}
        entries = [dict(text=lines[t['line']]['text'], start=t['start'], end=t['end']) for t in (p.get('line_times') or []) if t.get('start') is not None]
        try:
            spec = previzmod.default_spec(p['shots'], a, entries, story=data.get('story', 'generic'),
                                          width=int(number(data.get('width', 540), 160, 2160, 'width')),
                                          height=int(number(data.get('height', 960), 160, 3840, 'height')),
                                          fps=int(number(data.get('fps', 24), 8, 60, 'fps')))
        except previzmod.PrevizError as error:
            raise APIError('invalid_previz', str(error)) from None
        saved = self.save(p, previz=spec)
        return dict(revision=saved['revision'], spec=spec)

    def previz_get(self, identity):
        p = self.get(identity)
        if not p.get('previz'):
            raise APIError('previz_required', 'Generate the previz first (POST projects/{id}/previz).', 404)
        return dict(revision=p['revision'], spec=p['previz'])

    def previz_put(self, identity, data):
        fields(data, ('expected_revision', 'spec'), ('expected_revision', 'spec'))
        p = self.get(identity)
        self.p.check(p, data)
        try:
            spec = previzmod.validate(data['spec'])
        except previzmod.PrevizError as error:
            raise APIError('invalid_previz', str(error)) from None
        saved = self.save(p, previz=spec)
        return dict(revision=saved['revision'], spec=spec)

    def previz_render(self, identity, data):
        fields(data, ('expected_revision', 'start', 'end'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p.get('previz'):
            raise APIError('previz_required', 'Generate the previz first (POST projects/{id}/previz).', 409)
        start = number(data.get('start', 0), 0, 3600, 'start')
        end = number(data.get('end', p['previz']['duration']), 0, 3600, 'end')
        if end <= start:
            raise APIError('invalid_music_video_request', 'end must be after start.')
        out_dir = self.app.storage / 'music-video' / p['id']
        out = out_dir / f"previz-r{p['revision']}.mp4"
        try:
            result = previzmod.render(p['previz'], out, audio=self.audio_path(p['master']['source']), start=start, end=end)
        except previzmod.PrevizError as error:
            raise APIError('previz_render_failed', str(error), 503) from None
        return dict(file=str(out.relative_to(self.app.storage)), bytes=out.stat().st_size, duration=audio_io.duration(out),
                    shots=len(p['previz']['shots']), spec=str(Path(result['spec']).relative_to(self.app.storage)))

    def previz_stills(self, identity, data):
        """Clean previz stills (no label or lyrics) at the keyframe plan's times, or each shot's opening instant."""
        fields(data, ('expected_revision', 'stills'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p.get('previz'):
            raise APIError('previz_required', 'Generate the previz first (POST projects/{id}/previz).', 409)
        plan = p.get('keyframes')
        if 'stills' in data:
            wanted = data['stills']
            if not isinstance(wanted, list):
                raise APIError('invalid_music_video_request', 'stills is a list of {name, t}.')
        elif plan:
            wanted = [dict(name=x['name'], t=x['t']) for s in plan['shots'] for x in s['stills']]
        else:
            wanted = [dict(name=previzmod.still_name(s['id'], 'first'), t=round(s['start'] + keymod.FIRST_OFFSET, 3)) for s in p['previz']['shots']]
        out_dir = self.app.storage / 'music-video' / p['id'] / f"stills-r{p['revision']}"
        try:
            files = previzmod.render_stills(p['previz'], wanted, out_dir)
        except previzmod.PrevizError as error:
            raise APIError('previz_render_failed', str(error), 503) from None
        rel = {n: str(f.relative_to(self.app.storage)) for n, f in files.items()}
        listed = [dict(name=w['name'], t=w['t'], file=rel[w['name']]) for w in wanted]
        revision = p['revision']
        if plan:
            plan = copy.deepcopy(plan)
            times = {w['name']: w['t'] for w in wanted}
            for s in plan['shots']:
                for x in s['stills']:
                    if x['name'] in rel and abs(times[x['name']] - x['t']) < 1e-6:
                        x['previz_still'] = rel[x['name']]
            plan['previz_hash'] = self.previz_hash(p)
            revision = self.save(p, keyframes=plan)['revision']
        return dict(revision=revision, stills=listed,
                    note='Composition reference for stills only. Never attach a previz still to a video request.')

    # --- keyframes ---------------------------------------------------------------------------------------------
    @staticmethod
    def previz_hash(p):
        return hashlib.sha256(json.dumps(p.get('previz'), sort_keys=True).encode()).hexdigest()[:16] if p.get('previz') else None

    @staticmethod
    def story_of(spec):
        ids = {a['id'] for a in (spec or {}).get('actors', [])}
        return 'bedside_machine' if {'carer', 'machine'} <= ids else 'generic'

    def references_ok(self, refs):
        try:
            refs = keymod.clean_refs(refs)
        except keymod.KeyframeError as error:
            raise APIError('invalid_music_video_request', str(error)) from None
        for role, asset_id in refs.items():
            if asset_id is None:
                continue
            try:
                self.app.asset(asset_id)
            except (ValueError, KeyError, TypeError):
                raise APIError('unknown_asset', f'references.{role}: no asset {asset_id} in this workspace.', 404) from None
        return refs

    def keyframe_settings(self, data, current=None):
        current = current or {}
        candidates = int(number(data.get('candidates', current.get('candidates', 2)), 1, 8, 'candidates'))
        price = data.get('price_per_image', current.get('price_per_image'))
        return candidates, None if price is None else number(price, 0, 100, 'price_per_image')

    def keyframes_view(self, p):
        plan = p.get('keyframes')
        if not plan:
            raise APIError('keyframes_required', 'Draft the keyframe plan first (POST projects/{id}/keyframes).', 404)
        result = keymod.check(plan, p['shots'], has_previz=bool(p.get('previz')))
        stale = bool(p.get('previz')) and plan.get('previz_hash') != self.previz_hash(p)
        if stale:
            result['findings'].append(dict(severity='warn', shot=None, still=None, kind='previz_changed',
                                           message='The previz changed after this plan was drafted; redraft it or re-export the stills.'))
        return dict(revision=p['revision'], plan=plan, check=result, previz_stale=stale,
                    rules=['Stills are pictures: no quoted words, no text, nobody singing or speaking.',
                           'Previz stills are composition references for the image model only, never a video-model input.',
                           'Nothing is generated here; generating the batch needs the human\'s approval.'])

    def keyframes_draft(self, identity, data):
        fields(data, ('expected_revision', 'references', 'candidates', 'price_per_image', 'story'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p['shots']:
            raise APIError('board_required', 'Draft the board first (POST projects/{id}/board/draft).', 409)
        story = data.get('story') or self.story_of(p.get('previz'))
        if story not in previzmod.STORIES:
            raise APIError('invalid_music_video_request', 'story is one of ' + ', '.join(previzmod.STORIES))
        candidates, price = self.keyframe_settings(data)
        plan = keymod.draft(p['shots'], p.get('previz'), story=story, references=self.references_ok(data.get('references')),
                            candidates=candidates, price_per_image=price, look=p.get('look'))
        plan['previz_hash'] = self.previz_hash(p)
        return self.keyframes_view(self.save(p, keyframes=plan))

    def keyframes_patch(self, identity, data):
        fields(data, ('expected_revision', 'references', 'candidates', 'price_per_image', 'stills', 'agent'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p.get('keyframes'):
            raise APIError('keyframes_required', 'Draft the keyframe plan first (POST projects/{id}/keyframes).', 404)
        plan = copy.deepcopy(p['keyframes'])
        if 'references' in data:
            old, new = plan['references'], self.references_ok({**plan['references'], **(data['references'] or {})})
            for s in plan['shots']:            # untouched drafted prompts follow the new references
                for x in s['stills']:
                    if x['prompt'] == keymod.prompt_for(x['moment'], old, x.get('light')):
                        x['prompt'] = keymod.prompt_for(x['moment'], new, x.get('light'))
            plan['references'] = new
        plan['candidates'], plan['price_per_image'] = self.keyframe_settings(data, plan)
        if 'stills' in data:
            if not isinstance(data['stills'], list):
                raise APIError('invalid_music_video_request', 'stills is a list of {name, moment?, prompt?, t?}.')
            for c in data['stills']:
                for asset_id in (c.get('candidates') or []) if isinstance(c, dict) and isinstance(c.get('candidates'), list) else []:
                    if not self.asset_file(asset_id):
                        raise APIError('unknown_asset', f'No image asset {asset_id} in this workspace.', 404)
            try:
                keymod.edit(plan, data['stills'])
            except keymod.KeyframeError as error:
                raise APIError('invalid_music_video_request', str(error)) from None
        if data.get('agent') is not None:
            plan['director'] = self.app.director_review.check_director(data['agent'])
        plan['estimate'] = keymod.estimate(plan)
        return self.keyframes_view(self.save(p, keyframes=plan))

    # --- still review, consistency and hand-off ----------------------------------------------------------------
    def asset_file(self, asset_id):
        try:
            return Path(self.app.asset(asset_id)[1])
        except (ValueError, KeyError, TypeError):
            return None

    def rel(self, path):
        try:
            return str(Path(path).relative_to(self.app.storage))
        except ValueError:
            return str(path)

    def plan_still(self, p, name):
        plan = p.get('keyframes')
        if not plan:
            raise APIError('keyframes_required', 'Draft the keyframe plan first (POST projects/{id}/keyframes).', 404)
        for s in plan['shots']:
            for x in s['stills']:
                if x['name'] == name:
                    return plan, s, x
        raise APIError('unknown_still', 'No still with that name in the plan (for example s003-first).', 404)

    def keyframes_sheet(self, identity, data):
        """Comparison sheets: per shot, the previz still beside each generated candidate, with the lyric line."""
        fields(data, ('shots', 'per_page'))
        p = self.get(identity)
        plan = p.get('keyframes')
        if not plan:
            raise APIError('keyframes_required', 'Draft the keyframe plan first (POST projects/{id}/keyframes).', 404)
        want = data.get('shots')
        if want is not None and (not isinstance(want, list) or not all(isinstance(x, str) for x in want)):
            raise APIError('invalid_music_video_request', 'shots is a list of shot ids.')
        per = int(number(data.get('per_page', 5), 1, 12, 'per_page'))
        rows = []
        for s in plan['shots']:
            if want and s['shot_id'] not in want:
                continue
            for x in s['stills']:
                cands = []
                for k, asset_id in enumerate(x.get('candidates', [])):
                    review = (x.get('reviews') or {}).get(asset_id)
                    cands.append(dict(label=chr(65 + k), path=self.asset_file(asset_id), approved=(x.get('approved') or {}).get('asset_id') == asset_id,
                                      suggestion=review['suggestion'] if review else None))
                rows.append(dict(label=f"{x['name']}  {s['start']:.2f}-{s['end']:.2f}s  {s.get('section') or s['kind']}",
                                 line=s.get('text') or x['moment'], previz=self.app.storage / x['previz_still'] if x.get('previz_still') else None,
                                 candidates=cands, name=x['name']))
        if not rows:
            raise APIError('invalid_music_video_request', 'No stills match those shots.')
        out_dir = self.app.storage / 'music-video' / p['id'] / 'review'
        files = []
        for n in range(0, len(rows), per):
            f = out_dir / f"sheet-r{p['revision']}-{n // per + 1}.png"
            reviewmod.sheet(rows[n:n + per], f)
            files.append(dict(file=self.rel(f), stills=[r['name'] for r in rows[n:n + per]]))
        return dict(revision=p['revision'], sheets=files,
                    legend='Columns: the planned previz composition, then candidates A, B, C... An approved candidate is outlined green.')

    def keyframes_packet(self, identity, data):
        """The consistency-review packet for one candidate: the reviewer gets this and nothing else."""
        fields(data, ('still', 'asset_id'), ('still', 'asset_id'))
        p = self.get(identity)
        plan, shot, still = self.plan_still(p, data['still'])
        if data['asset_id'] not in still.get('candidates', []):
            raise APIError('unknown_asset', 'That asset is not a candidate for this still; add it with PATCH keyframes first.', 404)
        cand = self.asset_file(data['asset_id'])
        if not cand:
            raise APIError('unknown_asset', 'The candidate image is missing from the workspace.', 404)
        row = next(r for r in grademod.color_script(p['shots'], p.get('look')) if r['shot_id'] == shot['shot_id'])
        phrase, palette = row['phrase'], row['palette']
        refs = {role: dict(asset_id=a, file=self.rel(self.asset_file(a))) for role, a in plan['references'].items() if a and self.asset_file(a)}
        roles = self.app.director_review.get_roles()
        return dict(still=still['name'], candidate=dict(asset_id=data['asset_id'], file=self.rel(cand)),
                    references=refs, planned_composition=still.get('previz_still'), moment=still['moment'],
                    look=dict(phrase=phrase, palette=palette), local_checks=reviewmod.local_checks(cand),
                    brief=reviewmod.BRIEF, reviewer_model=(roles.get('reviewer') or {}).get('model'),
                    files_root='Files are relative to the Studio workspace folder.',
                    submit=dict(route=f"POST music-video/projects/{p['id']}/keyframes/reviews",
                                schema=dict(reviewer={'model': 'the chosen reviewer model', 'session_id': 'this new session'},
                                            scores={a: '0-10' for a in reviewmod.ASPECTS},
                                            issues=[{'severity': 'blocking|polish', 'aspect': '|'.join(reviewmod.ASPECTS + ('other',)),
                                                     'problem': 'what is wrong', 'fix': 'concrete prompt change'}],
                                            images_examined='how many images you looked at (>0)', summary='one or two sentences')))

    def keyframes_review(self, identity, data):
        fields(data, ('expected_revision', 'still', 'asset_id', 'review'), ('expected_revision', 'still', 'asset_id', 'review'))
        p = self.get(identity)
        self.p.check(p, data)
        plan, shot, still = self.plan_still(p, data['still'])
        if data['asset_id'] not in still.get('candidates', []):
            raise APIError('unknown_asset', 'That asset is not a candidate for this still.', 404)
        try:
            record = reviewmod.validate(data['review'], self.app.director_review.get_roles().get('reviewer'),
                                        (plan.get('director') or {}).get('session_id'))
        except reviewmod.ReviewError as error:
            code = 'wrong_reviewer_model' if 'chose' in str(error) else 'reviewer_not_independent' if 'new session' in str(error) else 'invalid_review'
            raise APIError(code, str(error), 403 if code != 'invalid_review' else 400) from None
        plan = copy.deepcopy(plan)
        target = next(x for s in plan['shots'] for x in s['stills'] if x['name'] == still['name'])
        target.setdefault('reviews', {})[data['asset_id']] = record
        saved = self.save(p, keyframes=plan)
        return dict(revision=saved['revision'], still=still['name'], asset_id=data['asset_id'], review=record,
                    note='A suggestion only. The human approves each still in their own words (PATCH keyframes approve).')

    def keyframes_handoff(self, identity, data):
        """Put approved stills into Studio scenes as first (and last) frames, with the previz still as the staging
        reference and the camera direction, so each shot kit is nearly ready."""
        fields(data, ('expected_revision', 'scenes'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        if not p.get('keyframes'):
            raise APIError('keyframes_required', 'Draft the keyframe plan first (POST projects/{id}/keyframes).', 404)
        if 'scenes' not in data:                   # default: every approved shot that has a scene from POST scenes
            plan_ = p['keyframes']
            ready = {s['shot_id'] for s in plan_.get('shots', []) if all(x.get('approved') for x in s['stills'])}
            data = dict(data, scenes={k: v for k, v in (p.get('scenes') or {}).items() if k in ready})
            if not data['scenes']:
                raise APIError('nothing_to_hand_off', 'No shot has both a Studio scene (POST projects/{id}/scenes) and approved stills.', 409)
        plan = p.get('keyframes')
        if not plan:
            raise APIError('keyframes_required', 'Draft the keyframe plan first (POST projects/{id}/keyframes).', 404)
        scenes = data['scenes']
        by_shot = {s['shot_id']: s for s in plan['shots']}
        if not isinstance(scenes, dict) or not scenes or any(k not in by_shot or not isinstance(v, str) for k, v in scenes.items()):
            raise APIError('invalid_music_video_request', 'scenes maps board shot ids to Studio scene ids.')
        work = []
        for shot_id, scene_id in scenes.items():          # check everything before changing anything
            s = by_shot[shot_id]
            stills = {x['role']: x for x in s['stills']}
            if not (stills.get('first') or {}).get('approved'):
                raise APIError('still_not_approved', f'{shot_id}: approve its opening still first (the human\'s own words).', 409)
            if 'last' in stills and not stills['last'].get('approved'):
                raise APIError('still_not_approved', f'{shot_id}: approve its closing still first.', 409)
            self.agent_call('GET', f'scenes/{scene_id}')
            work.append((shot_id, scene_id, s, stills))
        results = []
        for shot_id, scene_id, s, stills in work:
            changes = {'first': {'asset_id': stills['first']['approved']['asset_id']}}
            if 'last' in stills:
                changes['last'] = {'asset_id': stills['last']['approved']['asset_id']}
            scene = self.agent_call('GET', f'scenes/{scene_id}')
            scene = self.agent_call('PATCH', f'scenes/{scene_id}', {'expected_revision': scene['revision'], 'changes': changes})
            kit = {'expected_revision': scene['revision'], 'camera': self.camera_text(s)}
            if stills['first'].get('previz_still'):
                png = (self.app.storage / stills['first']['previz_still']).read_bytes()
                staging = self.app.upload({'name': f'{shot_id}-previz-staging.png', 'data_url': 'data:image/png;base64,' + base64.b64encode(png).decode()})
                kit['staging_asset_id'] = staging['id']
            if 'last' in stills:
                kit['end_state'] = stills['last']['moment'][:2000]
                kit['last_frame_from_first'] = bool(stills['last'].get('made_from_first'))
            else:
                kit['free_motion'] = True
            view = self.agent_call('PUT', f'scenes/{scene_id}/kit', kit)
            results.append(dict(shot_id=shot_id, scene_id=scene_id, kit_ready=view.get('ready'),
                                kit_missing=[c['id'] for c in view.get('checks', []) if not c.get('ok')]))
        return dict(revision=p['revision'], handed_off=results,
                    notes=['The previz still is saved only as the kit\'s staging reference; Studio keeps it out of the video request.',
                           'Write each scene\'s action and decide complex_action in the kit; nothing was generated.'])

    def last_frame(self, identity, data):
        """Save a take's own last used frame as an image and offer it as the next shot's opening frame (a continuation)."""
        fields(data, ('expected_revision', 'shot_id', 'to_shot'), ('expected_revision', 'shot_id', 'to_shot'))
        p = self.get(identity)
        self.p.check(p, data)
        take = p['takes'].get(data['shot_id'])
        if not take:
            raise APIError('take_required', 'Attach a take to that shot first.', 409)
        plan, shot, still = self.plan_still(p, f"{data['to_shot']}-first")
        board = {s['id']: s for s in p['shots']}
        src = board[data['shot_id']]
        w = take.get('window') or {}
        in_point = (take.get('placement') or {}).get('in_point_s', w.get('in_point_s', speech.SKIP_S))
        t = in_point + (src['end'] - src['start']) * w.get('speed', 1) - 1 / 24
        _, path = self.media(take['source'], video=True)
        out = self.app.storage / 'music-video' / p['id'] / 'frames' / f"{data['shot_id']}-last.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        import subprocess
        proc = subprocess.run([audio_io.ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-ss', f'{max(0, t):.3f}', '-i', str(path), '-frames:v', '1', str(out)],
                              capture_output=True, timeout=120)
        if proc.returncode or not out.is_file():
            raise APIError('frame_failed', 'Could not read the last frame of that take.', 409)
        asset = self.app.upload({'name': out.name, 'data_url': 'data:image/png;base64,' + base64.b64encode(out.read_bytes()).decode()})
        plan = copy.deepcopy(plan)
        target = next(x for s in plan['shots'] for x in s['stills'] if x['name'] == still['name'])
        target['candidates'] = (target.get('candidates') or []) + [asset['id']]
        target.update(continues=data['shot_id'], from_take_last_frame=True)
        saved = self.save(p, keyframes=plan)
        return dict(revision=saved['revision'], asset_id=asset['id'], at_s=round(t, 3), still=still['name'],
                    note='Added as a candidate; the human approves it like any other still.')

    # --- cut review ----------------------------------------------------------------------------------------------
    def cut_file(self, p, rel):
        if not isinstance(rel, str):
            raise APIError('invalid_music_video_request', 'file is the cut path a render returned.')
        base = (self.app.storage / 'music-video' / p['id']).resolve()
        path = (self.app.storage / rel).resolve()
        if base not in path.parents or path.suffix != '.mp4' or not path.is_file():
            raise APIError('unknown_cut', 'file must be a rendered cut of this project.', 404)
        return path

    def cut_sheets(self, identity, data):
        fields(data, ('file',), ('file',))
        p = self.get(identity)
        cut = self.cut_file(p, data['file'])
        out_dir = cut.parent / (cut.stem + '-review')
        sheets = []
        for s in sorted(p['shots'], key=lambda x: x['start']):
            frames = reviewmod.cut_frames(cut, s['start'], s['end'], out_dir / 'frames', s['id'])
            f = reviewmod.cut_sheet(s, frames, out_dir / f"{s['id']}.png", f"{s['id']}  {s['start']:.2f}-{s['end']:.2f}s  {s['kind']}  {s.get('section') or ''}")
            sheets.append(dict(shot_id=s['id'], file=self.rel(f)))
        roles = self.app.director_review.get_roles()
        return dict(file=data['file'], sheets=sheets, flash=releasemod.flash_check(cut), brief=reviewmod.CUT_BRIEF,
                    reviewer_model=(roles.get('reviewer') or {}).get('model'), reviews_so_far=len((p.get('cut_reviews') or {}).get(data['file'], [])),
                    note='Give two fresh reviewers (new sessions, the chosen reviewer model) only these sheets, then the human watches at full speed.',
                    submit=dict(route=f"POST music-video/projects/{p['id']}/cut/reviews",
                                schema=dict(reviewer={'model': '...', 'session_id': 'a new session'},
                                            shots=[{'shot_id': '...', 'verdict': 'ok|polish|blocking', 'problem': '...', 'fix': '...'}],
                                            frames_examined='how many frames you looked at', summary='...')))

    def cut_review(self, identity, data):
        fields(data, ('expected_revision', 'file', 'review'), ('expected_revision', 'file', 'review'))
        p = self.get(identity)
        self.p.check(p, data)
        self.cut_file(p, data['file'])
        earlier = (p.get('cut_reviews') or {}).get(data['file'], [])
        try:
            record = reviewmod.validate_cut_review(data['review'], [s['id'] for s in p['shots']], self.app.director_review.get_roles().get('reviewer'),
                                                   ((p.get('keyframes') or {}).get('director') or {}).get('session_id'),
                                                   [r['reviewer']['session_id'] for r in earlier])
        except reviewmod.ReviewError as error:
            code = 'wrong_reviewer_model' if 'chose' in str(error) else 'reviewer_not_independent' if 'session' in str(error) else 'invalid_review'
            raise APIError(code, str(error), 403 if code != 'invalid_review' else 400) from None
        reviews = copy.deepcopy(p.get('cut_reviews') or {})
        reviews.setdefault(data['file'], []).append(record)
        saved = self.save(p, cut_reviews=reviews)
        done = reviews[data['file']]
        blocking = sorted({sid for r in done for sid in r['blocking']})
        return dict(revision=saved['revision'], reviews=len(done), blocking=blocking,
                    next='Fix the blocking shots by reshooting with a better prompt or first frame, then re-render.' if blocking else
                         ('Ready for the human to watch at full speed.' if len(done) >= 2 else 'Get a second fresh-eyes review.'))

    # --- code-made shots and plates --------------------------------------------------------------------------------
    def code_shot(self, identity, data):
        """Render a visual-only shot from the stage (no label or lyrics) and attach it as the shot's take."""
        fields(data, ('expected_revision', 'shot_id', 'width', 'height'), ('expected_revision', 'shot_id'))
        p = self.get(identity)
        self.p.check(p, data)
        if not p.get('previz'):
            raise APIError('previz_required', 'A code shot renders from the project\'s stage spec; generate or PUT it first.', 409)
        shot = next((s for s in p['shots'] if s['id'] == data['shot_id']), None)
        if not shot:
            raise APIError('unknown_shot', 'That shot is not on this board.', 404)
        if shot['kind'] == 'spoken':
            raise APIError('spoken_needs_a_take', 'A spoken shot needs a real take with its own speech.', 409)
        spec = copy.deepcopy(p['previz'])
        spec['width'] = int(number(data.get('width', spec['width']), 160, 2160, 'width'))
        spec['height'] = int(number(data.get('height', spec['height']), 160, 3840, 'height'))
        start = max(0.0, shot['start'] - speech.SKIP_S)
        end = min(spec['duration'], shot['end'] + .1)
        out = self.app.storage / 'music-video' / p['id'] / 'code-shots' / f"{shot['id']}-r{p['revision']}.mp4"
        try:
            previzmod.render(spec, out, start=start, end=end, clean=True)
        except previzmod.PrevizError as error:
            raise APIError('previz_render_failed', str(error), 503) from None
        media = self.app.editing.upload(dict(name=out.name, base64=base64.b64encode(out.read_bytes()).decode()))
        source = dict(kind='upload', id=media['id'])
        takes = dict(p['takes'])
        takes[shot['id']] = dict(source=source, clip_duration=audio_io.duration(out), audio_used=False, code=True, clip_long_enough=True,
                                 window=dict(ok=True, in_point_s=round(shot['start'] - start, 3), speed=1.0, source_span_s=round(shot['end'] - shot['start'], 3),
                                             chosen_by='code', retimed=False, issues=[]))
        saved = self.save(p, takes=takes)
        return dict(revision=saved['revision'], shot_id=shot['id'], source=source, file=self.rel(out),
                    note='Made in code on the song clock: free, exact and repeatable. Replace it with a generated take any time.')

    def plate(self, identity, data):
        fields(data, ('expected_revision', 'name', 'width', 'height', 'svg', 'background', 'layers', 'palette', 'grain', 'shadow', 'use_as_set'),
               ('expected_revision', 'name'))
        p = self.get(identity)
        self.p.check(p, data)
        name = data['name']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', name):
            raise APIError('invalid_music_video_request', 'name is 1-40 letters, digits, - or _.')
        w = int(number(data.get('width', 1080), 160, 4096, 'width'))
        h = int(number(data.get('height', 1920), 160, 4096, 'height'))
        try:
            if 'svg' in data:
                if any(k in data for k in ('layers', 'background', 'palette')):
                    raise platemod.PlateError('Send svg, or background and layers, not both.')
                svg = platemod.check_svg(data['svg'])
            else:
                svg = platemod.paint(w, h, data.get('background', '#101a3a'), data.get('layers'), data.get('palette'),
                                     data.get('grain', .5), data.get('shadow', .35))
            out = self.app.storage / 'music-video' / p['id'] / 'plates' / f'{name}.png'
            platemod.render(svg, out, w, h)
        except platemod.PlateError as error:
            raise APIError('invalid_plate', str(error)) from None
        asset = self.app.upload({'name': f'{name}.png', 'data_url': 'data:image/png;base64,' + base64.b64encode(out.read_bytes()).decode()})
        plates = [x for x in (p.get('plates') or []) if x['name'] != name] + [dict(name=name, asset_id=asset['id'], file=self.rel(out), width=w, height=h)]
        changes = dict(plates=plates)
        if data.get('use_as_set') and p.get('keyframes'):
            plan = copy.deepcopy(p['keyframes'])
            old, new = plan['references'], dict(plan['references'], set=asset['id'])
            for s in plan['shots']:
                for x in s['stills']:
                    if x['prompt'] == keymod.prompt_for(x['moment'], old, x.get('light')):
                        x['prompt'] = keymod.prompt_for(x['moment'], new, x.get('light'))
            plan['references'] = new
            changes['keyframes'] = plan
        saved = self.save(p, **changes)
        return dict(revision=saved['revision'], name=name, asset_id=asset['id'], file=self.rel(out), used_as_set=bool(changes.get('keyframes')),
                    note='Use it as the set reference: ask the image model to rebuild it as a real, physical set for every still.')

    def agent_call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/' + path, data or {}, None)[1]

    @staticmethod
    def camera_text(s):
        framing = {'wide': 'Wide shot', 'medium': 'Medium shot', 'close': 'Close-up'}.get(s.get('framing'), 'Medium shot')
        move = {'push_in': 'slow push-in', 'pull_back': 'slow pull-back', 'orbit_left': 'slow orbit to the left', 'orbit_right': 'slow orbit to the right',
                'drift_high': 'high angle, gentle drift', 'low_push': 'low angle, slow push-in'}.get(s.get('move'), 'steady')
        return f'{framing}, {move}.'

    # --- render ------------------------------------------------------------------------------------------------
    def assemble(self, p, width, height):
        a = self.need_analysis(p)
        shots = sorted(p['shots'], key=lambda s: s['start'])
        missing = [s['id'] for s in shots if s['id'] not in p['takes']]
        if missing:
            raise APIError('takes_missing', 'Attach a take to every shot first: ' + ', '.join(missing[:8]), 409)
        placements, measured, entries = [], [], []
        for s in shots:
            t = p['takes'][s['id']]
            _, path = self.media(t['source'], video=True)
            place = dict(clip=str(path), start=s['start'], duration=round(s['end'] - s['start'], 3), kind=s['kind'] if s['kind'] == 'spoken' else 'visual',
                         speech=s['kind'] == 'spoken', shot=s['id'], in_point=speech.SKIP_S)
            if s['kind'] == 'spoken':
                pl = t.get('placement') or {}
                if not pl.get('ok'):
                    raise APIError('placement_unusable', f"Shot {s['id']}: the take's speech cannot be placed on a beat ({pl.get('reason', 'no speech')}). Retake or cover it.", 409)
                place.update(in_point=pl['in_point_s'], speech_start=pl['speech_start'], speech_end=pl['speech_end'])
                entries.append(dict(text=s['text'], start=pl['speech_start'], end=pl['speech_end'], approximate=False))
            else:
                w = t.get('window') or {}
                if w.get('ok'):
                    place.update(in_point=w['in_point_s'], speed=w['speed'])
            if s['kind'] == 'sung_cut':
                entries.append(dict(text=s['text'], start=s['start'] + .1, end=min(s['end'], s['start'] + .1 + s['speech_s']), approximate=True))
            placements.append(place)
        spans = modes.mute_spans(modes.speech_spans(shots, placements)) if p['mode'] == 'muted_spans' else []
        return placements, entries, spans

    def grades(self, p, placements):
        """Per-take color correction toward the shot's approved opening still (when the look asks for matching)."""
        look = grademod.settings(p.get('look'))
        plan = p.get('keyframes') or {}
        approved = {s['shot_id']: next((x['approved']['asset_id'] for x in s['stills'] if x['role'] == 'first' and x.get('approved')), None)
                    for s in plan.get('shots', [])}
        out = {}
        if not look['match']:
            return out
        for place in placements:
            ref = self.asset_file(approved.get(place['shot'])) if approved.get(place['shot']) else None
            if not ref or not ref.is_file():
                continue
            try:
                take = grademod.stats(place['clip'], start=place['in_point'], length=place['duration'] * place.get('speed', 1))
                place['grade'] = grademod.match(take, grademod.stats(ref), look['match_strength'])
                out[place['shot']] = place['grade']
            except (audio_io.AudioError, OSError):
                continue
        return out

    def render_plan(self, identity, data, execute=False):
        fields(data, ('expected_revision', 'width', 'height', 'lyrics_on_screen'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        width = int(number(data.get('width', 1080), 160, 3840, 'width'))
        height = int(number(data.get('height', 1920), 160, 3840, 'height'))
        return self.cut(p, width, height, data.get('lyrics_on_screen', True), execute=execute)

    def cut(self, p, width, height, lyrics_on_screen=True, execute=False, frame='fill', suffix=''):
        audit = self.audit(p['id'])
        if not audit['ok']:
            raise APIError('board_not_clean', 'Clear the audit errors before rendering: ' + '; '.join(f['message'] for f in audit['findings'] if f['severity'] == 'error')[:400], 409)
        placements, entries, spans = self.assemble(p, width, height)
        gate = lyric_text.lyric_gate(entries, p['lyrics'])
        look = grademod.settings(p.get('look'))
        sound = soundmod.filters(soundmod.settings(p.get('sound')), placements, p['master']['duration'])
        graded = self.grades(p, placements) if execute else {}
        flagged = {sid: t['window']['issues'] for sid, t in p['takes'].items() if (t.get('window') or {}).get('issues')}
        slowed = sorted(sid for sid, t in p['takes'].items() if (t.get('window') or {}).get('retimed'))
        plan = dict(mode=p['mode'], placements=[{k: v for k, v in x.items() if k != 'clip'} for x in placements],
                    mute_spans=spans, lyric_gate=gate, sound=sound['plan'], grain=look['grain'],
                    flagged_in_use=flagged, slowed_shots=slowed, approximate_lyric_lines=sum(e['approximate'] for e in entries),
                    notes=(['Lyric timing on song-carried lines is estimated from the slot, not aligned to the vocal.'] if any(e['approximate'] for e in entries) else [])
                    + ([f"Slowed below 1x (motion may step visibly): {', '.join(slowed)}. Prefer a cut-away, another take or a reshoot."] if slowed else []))
        if not execute:
            return plan
        plan['graded_shots'] = sorted(graded)
        out_dir = self.app.storage / 'music-video' / p['id']
        out_dir.mkdir(parents=True, exist_ok=True)
        overlays = lyric_text.render_frames(entries, out_dir / f'lyrics-{width}x{height}', width, height) if lyrics_on_screen else None
        out = out_dir / f"cut-r{p['revision']}{suffix}.mp4"
        stems = {k: self.audio_path(v) for k, v in p['stems'].items()}
        try:
            cmd = render.build_command(self.audio_path(p['master']['source']), placements, out, width, height, overlays=overlays,
                                       song_end=p['master']['duration'], mode=p['mode'], vocal_stem=stems.get('vocal'),
                                       instrumental_stem=stems.get('instrumental'), mute_spans=spans, sound=sound, grain=look['grain'], frame=frame)
            render.run(cmd)
        except (ValueError, audio_io.AudioError) as error:
            raise APIError('render_failed', str(error)) from None
        plan.update(file=self.rel(out), bytes=out.stat().st_size, duration=audio_io.duration(out), _path=out, _entries=entries)
        return plan

    def release(self, identity, data):
        """Every frame shape asked for, a hook check, thumbnail picks and a caption file. Local; never generates."""
        fields(data, ('expected_revision', 'formats', 'thumbnails', 'captions', 'lyrics_on_screen', 'max_side'), ('expected_revision',))
        p = self.get(identity)
        self.p.check(p, data)
        formats = data.get('formats', ['9:16'])
        if not isinstance(formats, list) or not formats or len(set(formats)) != len(formats) or any(f not in releasemod.FORMATS for f in formats):
            raise APIError('invalid_music_video_request', 'formats is a list of: ' + ', '.join(releasemod.FORMATS))
        count = int(number(data.get('thumbnails', 3), 0, 8, 'thumbnails'))
        side = int(number(data.get('max_side', 1920), 160, 3840, 'max_side'))
        out = dict(revision=p['revision'], formats={})
        first = None
        for f in formats:
            w, h, frame = releasemod.FORMATS[f]
            k = side / max(w, h)
            w, h = int(round(w * k / 2)) * 2, int(round(h * k / 2)) * 2
            done = self.cut(p, w, h, data.get('lyrics_on_screen', True), execute=True, frame=frame, suffix='-' + f.replace(':', 'x'))
            path, entries = done.pop('_path'), done.pop('_entries')
            out['formats'][f] = dict(file=done['file'], duration=done['duration'], frame=frame)
            first = first or (path, entries)
        path, entries = first
        out['hook'] = releasemod.hook_check(path, p['shots'])
        out['flash'] = releasemod.flash_check(path)
        out['publish_checklist'] = releasemod.PUBLISH_CHECKLIST
        out['metadata'] = 'Stripped from every rendered file (no song IDs or tool tags).'
        kit = self.app.storage / 'music-video' / p['id'] / f"release-r{p['revision']}"
        if count:
            out['thumbnails'] = [dict(t=x['t'], file=self.rel(x['file']), score=x['score']) for x in releasemod.thumbnails(path, kit, p['shots'], count)]
        if data.get('captions', True):
            kit.mkdir(parents=True, exist_ok=True)
            srt = kit / 'lyrics.srt'
            srt.write_text(releasemod.srt(entries), encoding='utf-8')
            out['captions'] = self.rel(srt)
        return out

    @staticmethod
    def public(plan):
        return {k: v for k, v in plan.items() if not k.startswith('_')}

    # --- dispatch ----------------------------------------------------------------------------------------------
    def dispatch(self, method, parts, data, key):
        if parts == ['schema'] and method == 'GET':return 200, self.schema()
        if len(parts) == 2 and parts[0] == 'transcribe-jobs' and method == 'GET':return 200, self.job_view(self.p.get(parts[1], JOB_KIND))
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'transcribe' and method == 'POST':return 202, self.transcribe(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'scenes' and method == 'POST':return 200, self.board_scenes(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'files' and method == 'GET':return 200, self.files(parts[1])
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'files' and method == 'GET':return 200, self.download(parts[1], parts[3])
        if parts == ['projects'] and method == 'GET':return 200, [self.view(p) for p in self.p.all(KIND)]
        if parts == ['projects'] and method == 'POST':return 201, self.view(self.create(data))
        if len(parts) == 2 and parts[0] == 'projects' and method == 'GET':return 200, self.view(self.get(parts[1]))
        if len(parts) == 2 and parts[0] == 'projects' and method == 'PATCH':return 200, self.patch(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'analyze' and method == 'POST':return 200, self.analyze(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'align' and method == 'POST':return 200, self.align(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'lint' and method == 'GET':return 200, self.lint(parts[1])
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'board' and parts[3] == 'draft' and method == 'POST':return 200, self.board_draft(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'board' and method == 'PATCH':return 200, self.patch_board(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'audit' and method == 'GET':return 200, self.audit(parts[1])
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'takes' and method == 'POST':return 201, self.attach_take(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'previz' and method == 'GET':return 200, self.previz_get(parts[1])
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'previz' and method == 'POST':return 200, self.previz_generate(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'previz' and method == 'PUT':return 200, self.previz_put(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'previz' and parts[3] == 'render' and method == 'POST':return 200, self.previz_render(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'previz' and parts[3] == 'stills' and method == 'POST':return 200, self.previz_stills(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'keyframes' and method == 'GET':return 200, self.keyframes_view(self.get(parts[1]))
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'keyframes' and method == 'POST':return 200, self.keyframes_draft(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'keyframes' and method == 'PATCH':return 200, self.keyframes_patch(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'render-plan' and method == 'POST':return 200, self.render_plan(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'render' and method == 'POST':return 200, self.public(self.render_plan(parts[1], data, True))
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'release' and method == 'POST':return 200, self.release(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'line-times' and parts[3] == 'refine' and method == 'POST':return 200, self.refine_lines(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'prompts' and method == 'GET':return 200, self.prompts_lint(parts[1])
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'prompts' and parts[3] == 'draft' and method == 'POST':return 200, self.prompts_draft(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'takes' and parts[3] == 'last-frame' and method == 'POST':return 201, self.last_frame(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'cut' and parts[3] == 'sheets' and method == 'POST':return 200, self.cut_sheets(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'cut' and parts[3] == 'reviews' and method == 'POST':return 201, self.cut_review(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'code-shots' and method == 'POST':return 201, self.code_shot(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'plates' and method == 'POST':return 201, self.plate(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'triage' and method == 'POST':return 200, self.triage_take(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'sound' and method == 'GET':return 200, self.sound_view(self.get(parts[1]))
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'sound' and method == 'PATCH':return 200, self.sound_patch(parts[1], data)
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'look' and method == 'GET':return 200, self.look_view(self.get(parts[1]))
        if len(parts) == 3 and parts[0] == 'projects' and parts[2] == 'look' and method == 'PATCH':return 200, self.look_patch(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'keyframes' and parts[3] == 'sheet' and method == 'POST':return 200, self.keyframes_sheet(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'keyframes' and parts[3] == 'packet' and method == 'POST':return 200, self.keyframes_packet(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'keyframes' and parts[3] == 'reviews' and method == 'POST':return 201, self.keyframes_review(parts[1], data)
        if len(parts) == 4 and parts[0] == 'projects' and parts[2] == 'keyframes' and parts[3] == 'handoff' and method == 'POST':return 200, self.keyframes_handoff(parts[1], data)
        raise APIError('not_found', 'Unknown music-video operation.', 404)
