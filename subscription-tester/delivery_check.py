"""Delivery check: is a finished video file ready to post or submit?

Measures any local video file, including renders made outside Studio (Resolve, Premiere):
codecs, size, frame rate, frame count and exact stream lengths; integrated loudness (LUFS),
true peak and the loudest moments; black and frozen stretches; and a contact sheet. It
compares them with a spec preset (a contest, X, YouTube) or a custom spec, and lists what
fails.

One fix is offered, without touching the picture: copy the video stream untouched and
re-encode only the audio, trimmed or padded to the exact length, at the spec's sample rate
and bit rate, optionally normalized to the spec's loudness and true peak. This repairs
encoder padding (Resolve's AAC adds about 0.07 s) and loudness without a new render.

Local FFmpeg only; no provider call.
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

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.m4v', '.mkv', '.webm')
MAX_BYTES = 4 * 1024 ** 3
MAX_SECONDS = 15 * 60

PRESETS = {
    'contest_30s_1080p': dict(
        label='30 s contest ad: H.264 1920×1080, AAC 192k 44.1 kHz, exactly 30.0 s',
        video_codec='h264', width=1920, height=1080, audio_codec='aac', sample_rate=44100,
        audio_bitrate_kbps=[180, 200], duration_s=30.0, lufs_target=-14.0, lufs_tolerance=1.0, true_peak_max_db=-1.0),
    'x': dict(
        label='X (Twitter) video post: H.264 + AAC, up to 1920×1200, 2 min 20 s',
        video_codec='h264', max_width=1920, max_height=1200, audio_codec='aac', max_duration_s=140.0,
        lufs_target=-14.0, lufs_tolerance=2.0, true_peak_max_db=-1.0),
    'youtube': dict(
        label='YouTube upload: H.264 + AAC, −14 LUFS, true peak −1 dBTP',
        video_codec='h264', audio_codec='aac', lufs_target=-14.0, lufs_tolerance=1.0, true_peak_max_db=-1.0),
}
SPEC_FIELDS = {
    'label': str, 'video_codec': str, 'audio_codec': str, 'width': int, 'height': int, 'max_width': int, 'max_height': int,
    'fps': (int, float), 'sample_rate': int, 'audio_bitrate_kbps': list, 'duration_s': (int, float), 'max_duration_s': (int, float),
    'lufs_target': (int, float), 'lufs_tolerance': (int, float), 'true_peak_max_db': (int, float),
}


def tools():
    ffmpeg = shutil.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if Path(p).exists()), None)
    ffprobe = shutil.which('ffprobe') or next((p for p in ('/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe') if Path(p).exists()), None)
    if not ffmpeg or not ffprobe:
        raise APIError('ffmpeg_unavailable', 'Install FFmpeg to check delivery files.', 503)
    return ffmpeg, ffprobe


def _rate(value):
    try:
        num, den = str(value).split('/')
        return round(int(num) / int(den), 3) if int(den) else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path):
    _, ffprobe = tools()
    try:
        out = subprocess.run([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                             capture_output=True, timeout=60, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        raise APIError('unreadable_media', 'FFprobe could not read this file as video.') from None
    data = json.loads(out or b'{}')
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    audio = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)
    if not video:
        raise APIError('unreadable_media', 'This file has no video stream.')
    fps = _rate(video.get('avg_frame_rate')) or _rate(video.get('r_frame_rate'))
    v_duration = float(video.get('duration') or data.get('format', {}).get('duration') or 0)
    frames = int(video['nb_frames']) if str(video.get('nb_frames', '')).isdigit() else (round(v_duration * fps) if fps else None)
    result = dict(
        container=data.get('format', {}).get('format_name'), bytes=int(data.get('format', {}).get('size') or 0),
        duration_s=round(float(data.get('format', {}).get('duration') or 0), 3),
        video=dict(codec=video.get('codec_name'), profile=video.get('profile'), width=video.get('width'), height=video.get('height'),
                   fps=fps, frames=frames, duration_s=round(v_duration, 3), pixel_format=video.get('pix_fmt'),
                   bitrate_kbps=round(int(video['bit_rate']) / 1000) if str(video.get('bit_rate', '')).isdigit() else None),
        audio=None)
    if audio:
        result['audio'] = dict(codec=audio.get('codec_name'), sample_rate=int(audio.get('sample_rate') or 0), channels=audio.get('channels'),
                               duration_s=round(float(audio.get('duration') or 0), 3),
                               bitrate_kbps=round(int(audio['bit_rate']) / 1000) if str(audio.get('bit_rate', '')).isdigit() else None)
    return result


def measure(path, has_audio):
    """One FFmpeg pass: loudness (EBU R128 with true peak), loudest moments, black and frozen stretches."""
    ffmpeg, _ = tools()
    graph = '[0:v]blackdetect=d=0.2:pix_th=0.05,freezedetect=n=-60dB:d=1.0[v]'
    maps = ['-map', '[v]']
    if has_audio:
        graph += ';[0:a]ebur128=peak=true:framelog=verbose[a]'
        maps += ['-map', '[a]']
    try:
        err = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-loglevel', 'verbose', '-i', str(path), '-filter_complex', graph, *maps, '-f', 'null', '-'],
                             capture_output=True, timeout=600).stderr.decode('utf-8', 'replace')
    except (subprocess.SubprocessError, OSError):
        raise APIError('measure_failed', 'FFmpeg could not measure this file.') from None
    black = [dict(start_s=float(a), end_s=float(b)) for a, b in re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', err)]
    starts = [float(v) for v in re.findall(r'freeze_start: ([\d.]+)', err)]
    ends = [float(v) for v in re.findall(r'freeze_end: ([\d.]+)', err)]
    frozen = [dict(start_s=s, end_s=ends[i] if i < len(ends) else None) for i, s in enumerate(starts)]
    loudness = None
    if has_audio:
        summary = err[err.rfind('Summary:'):] if 'Summary:' in err else ''
        def grab(pattern, text=summary):
            m = re.search(pattern, text)
            return float(m.group(1)) if m else None
        short = [(float(t), float(s)) for t, s in re.findall(r't:\s*([\d.]+)\s+TARGET:[^\n]*?S:\s*(-?[\d.]+)', err)]
        loudest, taken = [], []
        for t, s in sorted(short, key=lambda x: -x[1]):
            if all(abs(t - u) >= 2.0 for u in taken):
                taken.append(t)
                loudest.append(dict(time_s=round(max(0.0, t - 3.0), 2), short_term_lufs=s))
            if len(loudest) == 5:
                break
        loudest.sort(key=lambda x: x['time_s'])
        loudness = dict(integrated_lufs=grab(r'I:\s*(-?[\d.]+) LUFS'), range_lu=grab(r'LRA:\s*(-?[\d.]+) LU'),
                        true_peak_db=grab(r'Peak:\s*(-?[\d.]+|-inf) dBFS'), loudest_moments=loudest,
                        note='loudest_moments are 3 s short-term windows; time_s is where each window starts.')
    return dict(loudness=loudness, black=black, frozen=frozen)


def contact_sheet(path, out, duration):
    ffmpeg, _ = tools()
    step = max(0.5, (duration or 1) / 12)
    try:
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path), '-vf',
                        f'fps=1/{step:.3f},scale=480:-2,tile=4x3:padding=4:color=black', '-frames:v', '1', '-q:v', '4', str(out)],
                       capture_output=True, timeout=120, check=True)
    except (subprocess.SubprocessError, OSError):
        return False
    return out.exists()


def compare(info, measured, spec):
    """Each spec rule as {rule, expected, found, ok}."""
    rows = []
    def add(rule, expected, found, ok):
        rows.append(dict(rule=rule, expected=expected, found=found, ok=bool(ok)))
    v, a, loud = info['video'], info['audio'], measured.get('loudness')
    if 'video_codec' in spec:add('video codec', spec['video_codec'], v['codec'], v['codec'] == spec['video_codec'])
    if 'width' in spec:add('frame size', f"{spec['width']}×{spec['height']}", f"{v['width']}×{v['height']}", (v['width'], v['height']) == (spec['width'], spec['height']))
    if 'max_width' in spec:add('frame size limit', f"≤ {spec['max_width']}×{spec['max_height']}", f"{v['width']}×{v['height']}",
                               v['width'] <= spec['max_width'] and v['height'] <= spec['max_height'])
    if 'fps' in spec:add('frame rate', spec['fps'], v['fps'], v['fps'] is not None and abs(v['fps'] - spec['fps']) < 0.01)
    if 'duration_s' in spec:
        fps = v['fps'] or 24
        expected_frames = round(spec['duration_s'] * fps)
        add('picture length', f"{spec['duration_s']:.3f} s ({expected_frames} frames)", f"{v['duration_s']:.3f} s ({v['frames']} frames)",
            v['frames'] == expected_frames if v['frames'] is not None else abs(v['duration_s'] - spec['duration_s']) < 0.5 / fps)
        if a:add('sound length', f"{spec['duration_s']:.3f} s", f"{a['duration_s']:.3f} s", abs(a['duration_s'] - spec['duration_s']) <= 0.005)
        add('file length', f"{spec['duration_s']:.3f} s", f"{info['duration_s']:.3f} s", abs(info['duration_s'] - spec['duration_s']) <= 0.005)
    if 'max_duration_s' in spec:add('length limit', f"≤ {spec['max_duration_s']} s", f"{info['duration_s']} s", info['duration_s'] <= spec['max_duration_s'])
    if 'audio_codec' in spec:add('audio codec', spec['audio_codec'], a['codec'] if a else 'no audio', bool(a) and a['codec'] == spec['audio_codec'])
    if 'sample_rate' in spec:add('sample rate', spec['sample_rate'], a['sample_rate'] if a else None, bool(a) and a['sample_rate'] == spec['sample_rate'])
    if 'audio_bitrate_kbps' in spec:
        low, high = spec['audio_bitrate_kbps']
        found = a['bitrate_kbps'] if a else None
        add('audio bit rate', f'{low}–{high} kbps', found, found is not None and low <= found <= high)
    if 'lufs_target' in spec:
        found = loud and loud['integrated_lufs']
        add('loudness', f"{spec['lufs_target']} LUFS ± {spec.get('lufs_tolerance', 1.0)}", found,
            found is not None and abs(found - spec['lufs_target']) <= spec.get('lufs_tolerance', 1.0))
    if 'true_peak_max_db' in spec:
        found = loud and loud['true_peak_db']
        add('true peak', f"≤ {spec['true_peak_max_db']} dBTP", found, found is not None and found <= spec['true_peak_max_db'])
    if loud and loud['true_peak_db'] is not None and loud['true_peak_db'] > 0:
        add('clipping', 'no sample above 0 dBFS', f"{loud['true_peak_db']} dBTP", False)
    if measured['black']:add('black frames', 'none longer than 0.2 s', f"{len(measured['black'])} stretch(es)", False)
    if measured['frozen']:add('frozen picture', 'none longer than 1 s', f"{len(measured['frozen'])} stretch(es)", False)
    return rows


def _spec(data):
    preset = data.get('preset')
    if preset is not None and preset not in PRESETS:
        raise APIError('invalid_spec', 'preset must be one of: ' + ', '.join(PRESETS) + '.')
    spec = copy.deepcopy(PRESETS.get(preset, {}))
    custom = data.get('spec') or {}
    if not isinstance(custom, dict) or set(custom) - set(SPEC_FIELDS):
        raise APIError('invalid_spec', 'spec fields are: ' + ', '.join(SPEC_FIELDS) + '.')
    for key, value in custom.items():
        if not isinstance(value, SPEC_FIELDS[key]) or isinstance(value, bool):
            raise APIError('invalid_spec', f'spec.{key} has the wrong type.')
    if 'audio_bitrate_kbps' in custom and (len(custom['audio_bitrate_kbps']) != 2 or not all(isinstance(v, (int, float)) for v in custom['audio_bitrate_kbps'])):
        raise APIError('invalid_spec', 'spec.audio_bitrate_kbps is [lowest, highest].')
    spec.update(custom)
    if not spec:
        raise APIError('invalid_spec', 'Choose a preset or send a spec.')
    return preset, spec


def _source(value):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 4096:
        raise APIError('invalid_path', 'path must be the absolute path of a local video file.')
    path = Path(value).expanduser()
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise APIError('invalid_path', 'Use a video file: ' + ', '.join(VIDEO_EXTENSIONS) + '.')
    if not path.is_file():
        raise APIError('not_found', 'No file at that path.', 404)
    if path.stat().st_size > MAX_BYTES:
        raise APIError('invalid_path', 'The file is larger than 4 GB.')
    return path


class DeliveryCheck:
    def __init__(self, app, save_json):
        self.app = app
        self.save_json = save_json
        self.root = Path(app.storage) / 'delivery'
        self.path = Path(app.storage) / 'delivery-checks.json'
        self.lock = threading.Lock()
        try:
            self.checks = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.checks = []

    def _store(self, check):
        with self.lock:
            self.checks = [c for c in self.checks if c['id'] != check['id']] + [check]
            self.save_json(self.path, self.checks[-200:])

    def get(self, identity):
        with self.lock:
            check = next((c for c in self.checks if c['id'] == identity), None)
        if not check:
            raise APIError('not_found', 'Delivery check not found.', 404)
        return copy.deepcopy(check)

    def run(self, path, preset, spec, title=None, fixed_from=None):
        info = probe(path)
        if info['duration_s'] > MAX_SECONDS:
            raise APIError('invalid_path', 'Delivery checks cover files up to 15 minutes.')
        measured = measure(path, info['audio'] is not None)
        identity = uuid.uuid4().hex
        folder = self.root / identity
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        sheet = contact_sheet(path, folder / 'contact-sheet.jpg', info['duration_s'])
        rows = compare(info, measured, spec)
        failed = [r for r in rows if not r['ok']]
        fixable = [r['rule'] for r in failed if r['rule'] in ('sound length', 'file length', 'sample rate', 'audio bit rate', 'loudness', 'true peak', 'clipping', 'audio codec')]
        check = dict(id=identity, title=(title or Path(path).name)[:120], path=str(path), created_at=time.time(), preset=preset, spec=spec,
                     info=info, **measured, checks=rows, verdict='ready' if not failed else 'fix',
                     reasons=[f"{r['rule']}: expected {r['expected']}, found {r['found']}" for r in failed] or ['Every rule passes.'],
                     fixable=fixable, contact_sheet=f'/agent/v1/delivery/checks/{identity}/contact-sheet.jpg' if sheet else None,
                     fixed_from=fixed_from)
        self._store(check)
        return check

    def create(self, data):
        if not isinstance(data, dict) or set(data) - {'path', 'preset', 'spec', 'title'}:
            raise APIError('invalid_check', 'Send path, and preset and/or spec, and an optional title.')
        preset, spec = _spec(data)
        title = data.get('title')
        if title is not None and (not isinstance(title, str) or len(title) > 120):
            raise APIError('invalid_check', 'title must be text up to 120 characters.')
        return self.run(_source(data.get('path')), preset, spec, title)

    def fix(self, identity, data):
        """Copy the picture untouched; re-encode only the sound to the spec's length, format and loudness."""
        check = self.get(identity)
        if not isinstance(data, dict) or set(data) - {'output_path', 'loudness', 'duration_s'}:
            raise APIError('invalid_fix', 'Send optional output_path, loudness (true/false) and duration_s.')
        source = Path(check['path'])
        if not source.is_file():
            raise APIError('not_found', 'The checked file is no longer at its path.', 404)
        if not check['info']['audio']:
            raise APIError('invalid_fix', 'This file has no sound to fix.')
        spec = check['spec']
        duration = data.get('duration_s', spec.get('duration_s') or check['info']['video']['duration_s'])
        if type(duration) not in (int, float) or not 0.5 <= duration <= MAX_SECONDS:
            raise APIError('invalid_fix', 'duration_s must be a length in seconds.')
        loudness = data.get('loudness', 'lufs_target' in spec)
        if type(loudness) is not bool:
            raise APIError('invalid_fix', 'loudness must be true or false.')
        output = data.get('output_path')
        if output is not None:
            if not isinstance(output, str) or not output.startswith('/') or not output.lower().endswith(('.mp4', '.mov', '.m4v')):
                raise APIError('invalid_path', 'output_path must be an absolute .mp4, .mov or .m4v path.')
            output = Path(output)
            if output.exists():
                raise APIError('file_exists', 'A file already exists at output_path; choose a new name.', 409)
            if not output.parent.is_dir():
                raise APIError('invalid_path', 'The folder for output_path does not exist.')
        else:
            # Next to the original, never over it: My_Ad.mp4 -> My_Ad_DELIVERY.mp4 (then _DELIVERY_2 ...).
            output = source.with_name(source.stem + '_DELIVERY' + source.suffix.lower())
            n = 2
            while output.exists():
                output = source.with_name(f'{source.stem}_DELIVERY_{n}{source.suffix.lower()}')
                n += 1
        ffmpeg, _ = tools()
        rate = spec.get('sample_rate') or check['info']['audio']['sample_rate'] or 48000
        low, high = spec.get('audio_bitrate_kbps') or [192, 192]
        bitrate = 192 if low <= 192 <= high else round((low + high) / 2)
        chain = [f'aresample={rate}', 'apad', f'atrim=0:{duration:.6f}', 'asetpts=PTS-STARTPTS']
        if loudness:
            target = spec.get('lufs_target', -14.0)
            peak = min(spec.get('true_peak_max_db', -1.0), -1.0)
            first = subprocess.run([ffmpeg, '-hide_banner', '-nostats', '-i', str(source), '-vn', '-af',
                                    ','.join(chain + [f'loudnorm=I={target}:TP={peak - 0.2}:LRA=11:print_format=json']), '-f', 'null', '-'],
                                   capture_output=True, timeout=600).stderr.decode('utf-8', 'replace')
            stats = re.search(r'\{[^{}]*"input_i"[^{}]*\}', first)
            if not stats:
                raise APIError('measure_failed', 'FFmpeg could not measure the loudness.')
            m = json.loads(stats.group(0))
            chain.append(f"loudnorm=I={target}:TP={peak - 0.2}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                         f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
            chain += [f'aresample={rate}', 'apad', f'atrim=0:{duration:.6f}']
        try:
            subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-i', str(source), '-map', '0:v:0', '-map', '0:a:0',
                            '-c:v', 'copy', '-af', ','.join(chain), '-c:a', 'aac', '-b:a', f'{bitrate}k', '-ar', str(rate),
                            '-t', f'{duration:.6f}', '-movflags', '+faststart', str(output)],
                           capture_output=True, timeout=900, check=True)
        except (subprocess.SubprocessError, OSError) as error:
            detail = getattr(error, 'stderr', b'') or b''
            raise APIError('fix_failed', 'FFmpeg could not write the fixed file. ' + detail.decode('utf-8', 'replace')[-300:]) from None
        result = self.run(output, check['preset'], spec, f"{check['title']} (fixed)", fixed_from=identity)
        result['fix'] = dict(picture='copied untouched', sound=f'AAC {bitrate}k {rate} Hz, {duration:.3f} s' + (', loudness normalized' if loudness else ''),
                             output_path=str(output))
        self._store(result)
        return result

    def sheet(self, identity):
        self.get(identity)
        path = self.root / identity / 'contact-sheet.jpg'
        if not path.is_file():
            raise APIError('not_found', 'No contact sheet for this check.', 404)
        return path.read_bytes()

    def dispatch(self, method, parts, data, key):
        if parts == ['presets'] and method == 'GET':
            return 200, copy.deepcopy(PRESETS)
        if parts == ['checks']:
            if method == 'GET':
                with self.lock:
                    return 200, [{k: c.get(k) for k in ('id', 'title', 'path', 'preset', 'verdict', 'created_at', 'fixed_from')} for c in reversed(self.checks)]
            if method == 'POST':
                return 201, self.create(data)
        if len(parts) == 2 and parts[0] == 'checks' and method == 'GET':
            return 200, self.get(parts[1])
        if len(parts) == 3 and parts[0] == 'checks' and parts[2] == 'fix' and method == 'POST':
            return 201, self.fix(parts[1], data)
        if len(parts) == 3 and parts[0] == 'checks' and parts[2] == 'contact-sheet.jpg' and method == 'GET':
            return 200, (self.sheet(parts[1]), 'image/jpeg')
        raise APIError('not_found', 'Delivery route not found.', 404)
