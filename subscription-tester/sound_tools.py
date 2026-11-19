"""Sound tools for ads and short films: voice lines, stems, device sound and music fit.

- Voice lines: a scene set up for a spoken line only. It defaults to Grok Imagine Video 1.5
  Lite at 480p (about a quarter of the cost of full Video 1.5), with a still, neutral
  picture that is thrown away. Lite has no preset voices, so the voice is described in
  words: accent, age and character work; pitch words ("deeper") do not change it.
- Stems: the sound of a finished take (or any local audio file) saved as a 48 kHz WAV, with
  word times from the local transcriber when one is installed.
- Place: build a full-length stem from pieces of other stems, each put at a timeline time,
  optionally stretched, with gain and a device preset (radio, tablet, TV, laptop, phone),
  so one voice can be heard through a different device in each place.
- Music fit: find the song's strong onsets (drum entry, hits) and propose the slide that
  lands one on a picture hit; then write the music stem slid, trimmed to length, with
  volume keyframes (a duck, a rise to full level at a time, a drop under a voice-over).

Local FFmpeg only. Generating a voice line is an ordinary take: it needs the human's
approval like any other generation.
"""
import copy
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from agent_api import APIError

RATE = 48000
AUDIO_EXTENSIONS = ('.wav', '.mp3', '.m4a', '.aac', '.flac', '.aif', '.aiff', '.ogg', '.mp4', '.mov')
MAX_SECONDS = 600
MAX_PIECES = 60
LITE = 'grok-imagine-video-1.5-lite'

DEVICES = {
    'clean': dict(label='Clean, full range', chain=[]),
    'radio': dict(label='Marine or car radio: band-passed 400–3000 Hz with soft clipping',
                  chain=['highpass=f=400', 'lowpass=f=3000', 'acompressor=threshold=0.1:ratio=4:attack=5:release=80', 'asoftclip=type=tanh', 'volume=2dB']),
    'tablet': dict(label='Tablet speaker: thin, high-passed at 600 Hz', chain=['highpass=f=600', 'lowpass=f=9000']),
    'tv': dict(label='TV in a room: small room echo', chain=['highpass=f=120', 'lowpass=f=10000', 'aecho=0.8:0.5:28|45:0.22|0.12']),
    'laptop': dict(label='Laptop speaker: high-passed at 300 Hz, boxy +4 dB at 900 Hz',
                   chain=['highpass=f=300', 'equalizer=f=900:t=q:w=1:g=4', 'lowpass=f=8000']),
    'phone': dict(label='Phone call: 300–3400 Hz', chain=['highpass=f=300', 'lowpass=f=3400', 'acompressor=threshold=0.125:ratio=3']),
}

VOICE_GUIDE = ('Describe the voice in words: accent, age, character and delivery (for example "a deep, warm British male narrator, '
               'normal speed, with quiet emotion"). Pitch words alone ("deeper") do not change a Lite voice; accent and character do. '
               'Ask for normal speed; a slower read tends to sound flat.')


def tools():
    ffmpeg = shutil.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if Path(p).exists()), None)
    if not ffmpeg:
        raise APIError('ffmpeg_unavailable', 'Install FFmpeg to work with sound.', 503)
    return ffmpeg


def duration(path):
    ffprobe = shutil.which('ffprobe') or next((p for p in ('/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe') if Path(p).exists()), None)
    if not ffprobe:
        raise APIError('ffmpeg_unavailable', 'Install FFmpeg to work with sound.', 503)
    try:
        out = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                             capture_output=True, timeout=30, check=True).stdout
        return round(float(json.loads(out)['format']['duration']), 3)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        raise APIError('unreadable_media', 'FFmpeg could not read this file as audio.') from None


def _run(args, what):
    try:
        subprocess.run([tools(), '-hide_banner', '-loglevel', 'error', '-y', *args], capture_output=True, timeout=600, check=True)
    except subprocess.CalledProcessError as error:
        raise APIError('sound_failed', f'FFmpeg could not {what}. ' + (error.stderr or b'').decode('utf-8', 'replace')[-300:]) from None
    except (subprocess.SubprocessError, OSError):
        raise APIError('sound_failed', f'FFmpeg could not {what}.') from None


def _number(value, name, low, high):
    if type(value) not in (int, float) or not low <= value <= high:
        raise APIError('invalid_sound', f'{name} must be a number from {low} to {high}.')
    return float(value)


def _text(value, name, limit, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise APIError('invalid_sound', f'{name} must be text of 1 to {limit} characters.')
    return value.strip()


def gain_expression(keyframes, offset=0.0):
    """A volume expression (linear gain over time t) from [{at_s, db}] keyframes: straight lines in dB
    between keyframes, held before the first and after the last."""
    points = sorted((float(k['at_s']), float(k['db'])) for k in keyframes)
    if not points:
        return '1'
    expr = f'{points[-1][1]}'
    for (t0, d0), (t1, d1) in reversed(list(zip(points, points[1:]))):
        segment = f'{d0}+({d1}-({d0}))*(t-{t0})/{max(t1 - t0, 1e-6)}' if t1 > t0 else f'{d1}'
        expr = f'if(lt(t,{t1}),{segment},{expr})'
    expr = f'if(lt(t,{points[0][0]}),{points[0][1]},{expr})'
    return f'pow(10,({expr})/20)'


def _keyframes(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 50:
        raise APIError('invalid_sound', 'keyframes must be a list of up to 50 {"at_s", "db"} points.')
    out = []
    for k in value:
        if not isinstance(k, dict) or set(k) != {'at_s', 'db'}:
            raise APIError('invalid_sound', 'Each keyframe is {"at_s": seconds on the timeline, "db": gain}.')
        out.append(dict(at_s=_number(k['at_s'], 'keyframe at_s', 0, MAX_SECONDS), db=_number(k['db'], 'keyframe db', -60, 12)))
    return sorted(out, key=lambda k: k['at_s'])


def _local_audio(value):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 4096:
        raise APIError('invalid_path', 'path must be the absolute path of a local audio or video file.')
    path = Path(value)
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise APIError('invalid_path', 'Use an audio file (or a video with sound): ' + ', '.join(AUDIO_EXTENSIONS) + '.')
    if not path.is_file():
        raise APIError('not_found', 'No file at that path.', 404)
    return path


def energy_rises(path, count=4, window_s=1.5):
    """Times where the low band (kick, bass) steps up in level and stays up: [(rise in dB, time)]."""
    import math
    from music_video import beats
    low, _, _ = beats.band_envelopes(path)
    w = max(1, int(window_s / beats.FRAME))
    level = lambda xs: 20 * math.log10(max(sum(xs) / len(xs), 1e-9))
    scores = [(level(low[i:i + w]) - level(low[i - w:i]), i * beats.FRAME) for i in range(w, len(low) - w, 5)]
    picked = []
    for rise, t in sorted(scores, reverse=True):
        if rise < 2:
            break
        if all(abs(t - u) > 2 for _, u in picked):
            picked.append((round(rise, 1), round(t, 3)))
        if len(picked) == count:
            break
    return picked


class SoundTools:
    def __init__(self, app, save_json):
        self.app = app
        self.save_json = save_json
        self.root = Path(app.storage) / 'sound'
        self.path = Path(app.storage) / 'sound-stems.json'
        self.lock = threading.Lock()
        self.transcriber = None          # tests may set a callable(path, prompt) -> [{w, s, e}]
        try:
            self.db = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.db = {'stems': [], 'voice_lines': []}

    # ----- storage -----
    def _save(self):
        self.save_json(self.path, self.db)

    def stem(self, identity):
        with self.lock:
            record = next((s for s in self.db['stems'] if s['id'] == identity), None)
        if not record:
            raise APIError('not_found', 'Sound stem not found.', 404)
        return copy.deepcopy(record)

    def stem_file(self, identity):
        return self.root / f'{self.stem(identity)["id"]}.wav'

    def _new_stem(self, kind, name, made, **extra):
        identity = uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        out = self.root / f'{identity}.wav'
        made(out)
        record = dict(id=identity, kind=kind, name=name[:120], created_at=time.time(), duration_s=duration(out),
                      audio=f'/agent/v1/sound/stems/{identity}/audio.wav', **extra)
        with self.lock:
            self.db['stems'].append(record)
            self._save()
        return copy.deepcopy(record)

    def _source_path(self, item, label):
        """A piece's source: {"stem_id"} or {"path"}."""
        if isinstance(item.get('stem_id'), str):
            path = self.stem_file(item['stem_id'])
            if not path.is_file():
                raise APIError('not_found', f'{label}: the stem file is missing.', 404)
            return path
        if 'path' in item:
            return _local_audio(item['path'])
        raise APIError('invalid_sound', f'{label} needs stem_id or path.')

    # ----- voice lines -----
    def voice_line(self, data):
        """Create a scene for a spoken line only: Lite, 480p, sound on, a still neutral picture."""
        allowed = {'title', 'lines', 'voice', 'picture', 'duration', 'model', 'resolution', 'notes'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise APIError('invalid_voice_line', 'Send title, lines, voice and optional picture, duration, model, resolution and notes.')
        title = _text(data.get('title'), 'title', 120)
        voice = _text(data.get('voice'), 'voice', 600)
        lines = data.get('lines')
        if not isinstance(lines, list) or not 1 <= len(lines) <= 20:
            raise APIError('invalid_voice_line', 'lines must list 1 to 20 {"text", "at_s"?, "delivery"?} lines.')
        cleaned = []
        for line in lines:
            if not isinstance(line, dict) or set(line) - {'text', 'at_s', 'delivery'}:
                raise APIError('invalid_voice_line', 'Each line is {"text", "at_s"?, "delivery"?}.')
            cleaned.append(dict(text=_text(line.get('text'), 'line text', 300),
                                at_s=None if line.get('at_s') is None else _number(line['at_s'], 'at_s', 0, 15),
                                delivery=_text(line.get('delivery'), 'delivery', 200, required=False)))
        length = data.get('duration', 8 if sum(len(l['text']) for l in cleaned) < 120 else 15)
        if type(length) is not int or not 1 <= length <= 15:
            raise APIError('invalid_voice_line', 'duration is whole seconds from 1 to 15.')
        model = data.get('model', LITE)
        if model not in ('grok-imagine-video-1.5', LITE):
            raise APIError('invalid_voice_line', f'model must be {LITE} (default) or grok-imagine-video-1.5.')
        resolution = data.get('resolution', '480p')
        if resolution not in ('480p', '720p'):
            raise APIError('invalid_voice_line', 'resolution is 480p (default) or 720p.')
        picture = _text(data.get('picture'), 'picture', 600, required=False) or \
            'A quiet, dim broadcast booth at night: a desk microphone in the foreground, nobody in frame.'
        notes = _text(data.get('notes'), 'notes', 600, required=False)
        script = []
        for i, line in enumerate(cleaned):
            when = f'At {line["at_s"]:g} seconds' if line['at_s'] is not None else ('Then, after a short pause' if i else 'First')
            how = f', {line["delivery"]}' if line['delivery'] else ''
            script.append(f'{when}, the voice says{how}: "{line["text"]}"')
        prompt = '\n'.join([
            '[Camera & Style]', f'One continuous locked shot, no cuts, nothing moving. {picture}', '',
            '[Voice]', f'An off-screen voice: {voice}', *script, '',
            '[Sound]', 'Only the voice, clear and close. No music. No sound effects.' + (f' {notes}' if notes else ''), '',
            'No subtitles, no on-screen text.'])
        record = self.app.agent.create({'title': title, 'scene': {'model': model, 'resolution': resolution, 'duration': length,
                                                                   'ratio': '16:9', 'audio': True, 'prompt': prompt}})
        line = dict(id=uuid.uuid4().hex, scene_id=record['id'], title=title, voice=voice, lines=cleaned, created_at=time.time())
        with self.lock:
            self.db['voice_lines'].append(line)
            self._save()
        return dict(voice_line=line, scene=record, voice_guide=VOICE_GUIDE,
                    next_steps=['Show the prompt to the human and ask for their approval of this take, then generate it like any scene '
                                '(approved=true with their words).',
                                'When it is done, POST sound/stems with {"job_id"} to save its sound as a stem with word times.'])

    # ----- stems -----
    def transcribe(self, path, prompt=None, model_folder=None):
        if self.transcriber is not None:
            return self.transcriber(str(path), prompt), None
        import importlib.util
        folder = Path(model_folder) if model_folder else Path(self.app.editing.transcription_model())
        if importlib.util.find_spec('faster_whisper') is None or not (folder / 'model.bin').is_file():
            return None, 'No local transcriber or model is installed, so there are no word times. Nothing is downloaded.'
        from faster_whisper import WhisperModel
        model = WhisperModel(str(folder), local_files_only=True, device='cpu', compute_type='int8')
        segments, _ = model.transcribe(str(path), language='en', word_timestamps=True, initial_prompt=prompt,
                                       condition_on_previous_text=False, beam_size=5)
        return [dict(w=w.word.strip(), s=round(w.start, 3), e=round(w.end, 3)) for seg in segments for w in (seg.words or []) if w.word.strip()], None

    def import_stem(self, data):
        if not isinstance(data, dict) or set(data) - {'job_id', 'path', 'name', 'words', 'model_folder'}:
            raise APIError('invalid_sound', 'Send job_id (a finished take) or path (a local audio file), optional name, words (true/false) and model_folder.')
        if ('job_id' in data) == ('path' in data):
            raise APIError('invalid_sound', 'Send exactly one of job_id or path.')
        prompt = None
        if 'job_id' in data:
            try:
                source = self.app.download(data['job_id'])
            except (ValueError, OSError):
                raise APIError('not_found', 'That take has no finished video.', 404) from None
            job = next((j for j in self.app.records() if j['id'] == data['job_id']), {})
            scene_id = (job.get('settings') or {}).get('_studio_video_id')
            with self.lock:
                line = next((v for v in self.db['voice_lines'] if v['scene_id'] == scene_id), None)
            if line:
                prompt = ' '.join(l['text'] for l in line['lines'])
            name = data.get('name') or (line['title'] if line else f"Take {data['job_id'][:8]} sound")
            origin = dict(job_id=data['job_id'], **({'voice_line_id': line['id']} if line else {}))
        else:
            source = _local_audio(data['path'])
            name = data.get('name') or source.stem
            origin = dict(path=str(source))
        name = _text(name, 'name', 120)
        want_words = data.get('words', True)
        if type(want_words) is not bool:
            raise APIError('invalid_sound', 'words must be true or false.')
        model_folder = data.get('model_folder')
        if model_folder is not None and (not isinstance(model_folder, str) or not model_folder.startswith('/')):
            raise APIError('invalid_sound', 'model_folder is an absolute path to a converted Whisper model.')

        def made(out):
            _run(['-i', str(source), '-vn', '-ac', '2', '-ar', str(RATE), '-c:a', 'pcm_s24le', str(out)], 'extract the sound')
        record = self._new_stem('take' if 'job_id' in data else 'import', name, made, origin=origin, words=None)
        if want_words:
            words, note = self.transcribe(self.stem_file(record['id']), prompt, model_folder)
            with self.lock:
                saved = next(s for s in self.db['stems'] if s['id'] == record['id'])
                saved['words'] = words
                if note:
                    saved['words_note'] = note
                self._save()
                record = copy.deepcopy(saved)
        return record

    def place(self, data):
        """A full-length stem from pieces of other stems, each at a timeline time."""
        if not isinstance(data, dict) or set(data) - {'name', 'length_s', 'pieces'}:
            raise APIError('invalid_sound', 'Send name, length_s and pieces.')
        name = _text(data.get('name'), 'name', 120)
        length = _number(data.get('length_s'), 'length_s', 0.5, MAX_SECONDS)
        pieces = data.get('pieces')
        if not isinstance(pieces, list) or not 1 <= len(pieces) <= MAX_PIECES:
            raise APIError('invalid_sound', f'pieces must list 1 to {MAX_PIECES} pieces.')
        inputs, filters, labels = [], [], []
        for i, piece in enumerate(pieces):
            label = f'piece {i + 1}'
            if not isinstance(piece, dict) or set(piece) - {'stem_id', 'path', 'from_s', 'to_s', 'at_s', 'stretch_to_s', 'gain_db', 'device', 'fade_s'}:
                raise APIError('invalid_sound', f'{label}: fields are stem_id or path, from_s, to_s, at_s, stretch_to_s, gain_db, device, fade_s.')
            path = self._source_path(piece, label)
            if str(path) not in inputs:
                inputs.append(str(path))
            index = inputs.index(str(path))
            start = _number(piece.get('from_s', 0), f'{label} from_s', 0, MAX_SECONDS)
            end = _number(piece['to_s'], f'{label} to_s', start + 0.01, MAX_SECONDS) if 'to_s' in piece else None
            at = _number(piece.get('at_s', 0), f'{label} at_s', 0, length)
            gain = _number(piece.get('gain_db', 0), f'{label} gain_db', -60, 24)
            fade = _number(piece.get('fade_s', 0.01), f'{label} fade_s', 0, 2)
            device = piece.get('device', 'clean')
            if device not in DEVICES:
                raise APIError('invalid_sound', f'{label}: device is one of ' + ', '.join(DEVICES) + '.')
            chain = [f'atrim=start={start}' + (f':end={end}' if end is not None else ''), 'asetpts=PTS-STARTPTS', f'aresample={RATE}', 'aformat=channel_layouts=stereo']
            if 'stretch_to_s' in piece:
                if end is None:
                    raise APIError('invalid_sound', f'{label}: stretch_to_s needs to_s.')
                target = _number(piece['stretch_to_s'], f'{label} stretch_to_s', 0.05, MAX_SECONDS)
                factor = (end - start) / target
                if not 0.5 <= factor <= 2.0:
                    raise APIError('invalid_sound', f'{label}: stretch between half and double the length only.')
                chain.append(f'atempo={factor:.6f}')
            chain += DEVICES[device]['chain']
            if gain:
                chain.append(f'volume={gain}dB')
            if fade:
                chain.append(f'afade=t=in:d={fade}')
            ms = round(at * 1000)
            chain.append(f'adelay={ms}|{ms}')
            filters.append(f'[{index}:a]' + ','.join(chain) + f'[p{i}]')
            labels.append(f'[p{i}]')
        base = len(inputs)
        graph = ';'.join(filters + [f'[{base}:a]' + ''.join(labels) + f'amix=inputs={len(labels) + 1}:normalize=0:duration=first,atrim=0:{length}[out]'])

        def made(out):
            args = []
            for path in inputs:
                args += ['-i', path]
            args += ['-f', 'lavfi', '-t', f'{length}', '-i', f'anullsrc=r={RATE}:cl=stereo', '-filter_complex', graph,
                     '-map', '[out]', '-ar', str(RATE), '-c:a', 'pcm_s24le', str(out)]
            _run(args, 'build the placed stem')
        return self._new_stem('placed', name, made, pieces=copy.deepcopy(pieces), length_s=length)

    # ----- music fit -----
    def music_fit(self, data):
        """Propose slides that land a strong onset of the song on the picture's hit."""
        if not isinstance(data, dict) or set(data) - {'stem_id', 'path', 'hit_s', 'length_s', 'song_event_s'}:
            raise APIError('invalid_sound', 'Send stem_id or path, hit_s, length_s and optional song_event_s.')
        path = self._source_path(data, 'song')
        hit = _number(data.get('hit_s'), 'hit_s', 0, MAX_SECONDS)
        length = _number(data.get('length_s'), 'length_s', 0.5, MAX_SECONDS)
        song_length = duration(path)
        events = []
        if data.get('song_event_s') is not None:
            events.append(dict(t=_number(data['song_event_s'], 'song_event_s', 0, song_length), strength=None, kind='chosen'))
        else:
            from music_video import beats, audio_io
            try:
                analysis = beats.analyze(str(path))
            except audio_io.AudioError as error:
                raise APIError('invalid_sound', str(error)) from None
            strong = sorted(analysis['hits'], key=lambda h: -h['strength'])[:8]
            events += [dict(t=h['t'], strength=h['strength'], kind='kick hit' if h['kick'] else 'hit') for h in strong]
            events += [dict(t=t, strength=rise, kind='energy rise (drums or band coming in)') for rise, t in energy_rises(str(path))]
            for section in analysis['sections'][1:]:
                start = section.get('start') if isinstance(section, dict) else None
                if start is not None:
                    events.append(dict(t=start, strength=None, kind='section start'))
            bpm = analysis['bpm']
        options = []
        for event in events:
            offset = round(hit - event['t'], 3)          # where the song's 0 lands on the timeline
            covered_from, covered_to = max(0.0, offset), min(length, offset + song_length)
            options.append(dict(song_event_s=event['t'], kind=event['kind'], strength=event['strength'], offset_s=offset,
                                covers=[round(covered_from, 3), round(covered_to, 3)],
                                silence=dict(head_s=round(max(0.0, offset), 3), tail_s=round(max(0.0, length - (offset + song_length)), 3)),
                                trims_song_start_s=round(max(0.0, -offset), 3)))
        order = {'chosen': 0, 'energy rise (drums or band coming in)': 1, 'kick hit': 2, 'hit': 2, 'section start': 3}
        options.sort(key=lambda o: (order.get(o['kind'], 4), -(o['strength'] or 0)))
        return dict(hit_s=hit, length_s=length, song_length_s=song_length, options=options[:8],
                    **({'bpm': bpm} if data.get('song_event_s') is None else {}),
                    advice='Slide the whole song (never cut it). The events are guesses from energy: listen, find the moment you want on '
                           'the hit (the drum entry, the big hit) and pass it as song_event_s if none of these is it. Then POST sound/music '
                           'with offset_s and volume keyframes.')

    def music(self, data):
        """Write the music stem: the song slid by offset_s, trimmed to length, with volume keyframes."""
        if not isinstance(data, dict) or set(data) - {'stem_id', 'path', 'name', 'offset_s', 'length_s', 'keyframes', 'fade_out_s'}:
            raise APIError('invalid_sound', 'Send stem_id or path, name, offset_s, length_s, keyframes and optional fade_out_s.')
        path = self._source_path(data, 'song')
        name = _text(data.get('name'), 'name', 120)
        offset = _number(data.get('offset_s', 0), 'offset_s', -MAX_SECONDS, MAX_SECONDS)
        length = _number(data.get('length_s'), 'length_s', 0.5, MAX_SECONDS)
        keys = _keyframes(data.get('keyframes'))
        fade_out = _number(data.get('fade_out_s', 0), 'fade_out_s', 0, 10)
        chain = []
        if offset < 0:
            chain += [f'atrim=start={-offset}', 'asetpts=PTS-STARTPTS']
        chain += [f'aresample={RATE}', 'aformat=channel_layouts=stereo']
        if offset > 0:
            ms = round(offset * 1000)
            chain.append(f'adelay={ms}|{ms}')
        chain += ['apad', f'atrim=0:{length}']
        if keys:
            chain.append(f"volume='{gain_expression(keys)}':eval=frame")
        if fade_out:
            chain.append(f'afade=t=out:st={max(0.0, length - fade_out)}:d={fade_out}')

        def made(out):
            _run(['-i', str(path), '-af', ','.join(chain), '-ar', str(RATE), '-c:a', 'pcm_s24le', str(out)], 'write the music stem')
        return self._new_stem('music', name, made, offset_s=offset, length_s=length, keyframes=keys, fade_out_s=fade_out,
                              source=dict(stem_id=data['stem_id']) if 'stem_id' in data else dict(path=str(path)))

    def dispatch(self, method, parts, data, key):
        if parts == ['presets'] and method == 'GET':
            return 200, dict(devices={k: v['label'] for k, v in DEVICES.items()}, voice_line_defaults=dict(model=LITE, resolution='480p'),
                             voice_guide=VOICE_GUIDE, sample_rate=RATE)
        if parts == ['voice-lines']:
            if method == 'GET':
                with self.lock:
                    return 200, copy.deepcopy(list(reversed(self.db['voice_lines'])))
            if method == 'POST':
                return 201, self.voice_line(data)
        if parts == ['stems']:
            if method == 'GET':
                with self.lock:
                    return 200, [{k: s.get(k) for k in ('id', 'kind', 'name', 'duration_s', 'created_at', 'audio')} for s in reversed(self.db['stems'])]
            if method == 'POST':
                return 201, self.import_stem(data)
        if len(parts) == 2 and parts[0] == 'stems' and method == 'GET':
            return 200, self.stem(parts[1])
        if len(parts) == 3 and parts[0] == 'stems' and parts[2] == 'audio.wav' and method == 'GET':
            path = self.stem_file(parts[1])
            if not path.is_file():
                raise APIError('not_found', 'The stem file is missing.', 404)
            return 200, (path.read_bytes(), 'audio/wav')
        if parts == ['place'] and method == 'POST':
            return 201, self.place(data)
        if parts == ['music-fit'] and method == 'POST':
            return 200, self.music_fit(data)
        if parts == ['music'] and method == 'POST':
            return 201, self.music(data)
        raise APIError('not_found', 'Sound route not found.', 404)
