"""Take triage: find the weak seconds of a generated take and pick the best window for its slot.

Every generated take has weak moments: a pop where a face or hand morphs, flicker, a frozen tail, a black frame. This
scans a take locally (FFmpeg and plain Python, no provider) at low resolution and reports them by time. `best_window`
then chooses which part of the take fills the shot's slot. It avoids flagged frames, keeps close to the planned opening
frame, and puts the strongest movement on a beat.

A window never starts on the take's first two frames (SKIP_S): the first frame is the sharper input still, and the
switch to motion pops. Takes are not slowed by default; slowed motion steps visibly (Claudia measured it at 0.53-0.89x).
Slowing a visual-only shot is an explicit choice (allow_retime) and is flagged. Spoken shots are never retimed.
"""
import json
import shutil
import statistics
import subprocess

from music_video import audio_io
from music_video.speech import SKIP_S

SCAN_FPS = 12
SCAN_W = 48
MIN_SPEED = .8
SPEEDS = (1.0, .95, .9, .85, .8)
FROZEN_DIFF = .0015          # mean absolute change per pixel (0-1) below which a frame is "still"
FROZEN_MIN_S = .75
JUMP_MIN = .08               # a frame-to-frame change this large (and well above the take's norm) is a pop
FLICKER_LUMA = .05
BLACK_LUMA = .03


def probe(path):
    exe = shutil.which('ffprobe')
    if not exe:
        raise audio_io.AudioError('ffprobe is required.')
    out = subprocess.run([exe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration',
                          '-of', 'json', str(path)], capture_output=True, text=True, timeout=60)
    try:
        data = json.loads(out.stdout)
        s = data['streams'][0]
        return int(s['width']), int(s['height']), float(data['format']['duration'])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        raise audio_io.AudioError('Could not read the video stream.') from None


def frames(path, fps=SCAN_FPS, width=SCAN_W, pix='gray', start=None, length=None):
    """Low-resolution frames as bytes (gray: 1 byte per pixel; rgb24: 3)."""
    w, h, dur = probe(path)
    height = max(2, round(width * h / w / 2) * 2)
    cmd = [audio_io.ffmpeg_path(), '-nostdin', '-v', 'error']
    if start is not None:
        cmd += ['-ss', f'{start:.3f}']
    if length is not None:
        cmd += ['-t', f'{length:.3f}']
    cmd += ['-i', str(path), '-an', '-vf', f'fps={fps},scale={width}:{height}:flags=area,format={pix}', '-f', 'rawvideo', '-']
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode:
        raise audio_io.AudioError('Video decode failed: ' + proc.stderr.decode('utf-8', 'replace')[:200])
    size = width * height * (3 if pix == 'rgb24' else 1)
    raw = proc.stdout
    return [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)], dict(width=width, height=height, duration=dur, fps=fps)


def scan(path):
    """Per-frame motion and luma, and the flagged moments: [{kind, start, end}]."""
    fr, meta = frames(path)
    n = len(fr)
    if n < 2:
        raise audio_io.AudioError('The take is too short to scan.')
    px = len(fr[0])
    luma = [sum(f) / px / 255 for f in fr]
    diff = [0.0] + [sum(abs(a - b) for a, b in zip(fr[i], fr[i - 1])) / px / 255 for i in range(1, n)]
    norm = statistics.median(diff[1:]) or 1e-4
    dt = 1 / meta['fps']
    bad = [set() for _ in range(n)]
    for i in range(1, n):
        if diff[i] > max(JUMP_MIN, norm * 6):
            bad[i].add('jump')
        if i + 1 < n and abs(luma[i] - luma[i - 1]) > FLICKER_LUMA and (luma[i] - luma[i - 1]) * (luma[i + 1] - luma[i]) < 0 \
                and abs(luma[i + 1] - luma[i]) > FLICKER_LUMA:
            bad[i].add('flicker')
    for i in range(n):
        if luma[i] < BLACK_LUMA:
            bad[i].add('black')
    run = 0
    for i in range(1, n + 1):
        if i < n and diff[i] < FROZEN_DIFF:
            run += 1
            continue
        if run * dt >= FROZEN_MIN_S:
            for k in range(i - run, i):
                bad[k].add('frozen')
        run = 0
    issues = []
    for kind in ('jump', 'flicker', 'black', 'frozen'):
        i = 0
        while i < n:
            if kind in bad[i]:
                j = i
                while j + 1 < n and kind in bad[j + 1]:
                    j += 1
                issues.append(dict(kind=kind, start=round(i * dt, 3), end=round((j + 1) * dt, 3)))
                i = j + 1
            else:
                i += 1
    issues.sort(key=lambda x: x['start'])
    return dict(duration=meta['duration'], fps=meta['fps'], motion=[round(d, 5) for d in diff], luma=[round(v, 4) for v in luma],
                flags=[sorted(b) for b in bad], issues=issues, motion_median=round(norm, 5),
                verdict='clean' if not issues else 'check' if all(x['kind'] == 'frozen' for x in issues) else 'flawed')


def best_window(report, slot, beat_offsets=(), allow_retime=False, keep_open=True):
    """Which part of the take fills a slot of `slot` seconds.

    beat_offsets: beat times relative to the slot start (bar lines first is fine). Returns
    {ok, in_point_s, speed, source_span_s, flagged, accent, score, reason?}. speed < 1 slows the picture."""
    fps, motion, flags = report['fps'], report['motion'], report['flags']
    dur = report['duration']
    speeds = SPEEDS if allow_retime else (1.0,)
    best = None
    for speed in speeds:
        span = slot * speed
        if span + SKIP_S > dur + .02:          # the window must really exist in the take
            continue
        steps = max(0, int((dur - span - SKIP_S) * fps))
        for k in range(steps + 1):
            a = SKIP_S + k / fps
            i0, i1 = int(round(a * fps)), min(len(motion), int(round((a + span) * fps)))
            window = range(i0, i1)
            flagged = sum(1 for i in window if flags[i] and flags[i] != ['frozen'])
            frozen = sum(1 for i in window if 'frozen' in flags[i])
            score = -10 * flagged - 2 * frozen / fps - 2.0 * (1 - speed)
            if keep_open:
                score -= .3 * (a - SKIP_S)                      # the planned opening frame is at the start of the take
            accent = None
            inner = [i for i in window if i > i0]
            if inner and beat_offsets:
                peak = max(inner, key=lambda i: motion[i])
                at = (peak / fps - a) / speed
                near = min(beat_offsets, key=lambda b: abs(b - at))
                accent = dict(peak_s=round(at, 3), nearest_beat_s=round(near, 3), off_s=round(at - near, 3))
                if motion[peak] > report['motion_median'] * 2:
                    score -= 1.5 * min(1.0, abs(at - near) / .25)
            if best is None or score > best['score'] + 1e-9:
                best = dict(ok=True, in_point_s=round(a, 3), speed=speed, source_span_s=round(span, 3), flagged=flagged,
                            frozen_s=round(frozen / fps, 2), accent=accent, score=round(score, 3), retimed=speed < 1)
    if best is None:
        need = slot * (MIN_SPEED if allow_retime else 1) + SKIP_S
        return dict(ok=False, in_point_s=0, speed=1.0, source_span_s=round(dur, 3), flagged=None, accent=None, score=None,
                    reason=f'The take is {dur:.2f}s; the slot needs {need:.2f}s{" even slowed to " + str(MIN_SPEED) + "x" if allow_retime else ""}.')
    best['issues'] = [x for x in report['issues'] if x['end'] > best['in_point_s'] and x['start'] < best['in_point_s'] + best['source_span_s']]
    return best


def spoken_window_issues(report, in_point, slot):
    """Flagged moments inside the part of a spoken take that will be used (no retiming)."""
    return [x for x in report['issues'] if x['end'] > in_point and x['start'] < in_point + slot]


def summary(report):
    return {k: report[k] for k in ('duration', 'fps', 'issues', 'motion_median', 'verdict')}
