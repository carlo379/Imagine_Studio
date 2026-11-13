"""Previz: turn the board into a 3D stand-in video (three.js) on the real song clock, and render it headlessly.

The spec is plain JSON (see static/previz.js). The default builder gives every shot a camera move and, for the
`bedside_machine` story, staged actors (a stick-figure carer and a glowing machine), so the pacing, the reveal and the
camera ideas can be judged before any paid generation. Nothing here calls a provider.
"""
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from music_video import audio_io

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
RENDERER = ROOT / 'scripts' / 'previz-render.mjs'
VERSION = 1
STORIES = ('generic', 'bedside_machine')
EASES = ('linear', 'in', 'out', 'inOut')
ACTOR_TYPES = ('stick_human', 'orb_machine', 'lamp', 'box')
POSES = ('stand', 'sit', 'lean_in', 'reach', 'rock', 'tuck', 'lie', 'wave')
PROPS = ('pos', 'rot', 'scale', 'pose', 'glow', 'eyes', 'visible')
PRESETS = ('bedroom', 'street', 'void')


class PrevizError(ValueError):
    pass


def vec(value, name, n=3):
    if not isinstance(value, (list, tuple)) or len(value) != n or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise PrevizError(f'{name} must be {n} finite numbers.')
    return [float(v) for v in value]


def validate(spec):
    """Strict, bounded validation of a previz spec. Returns the cleaned spec or raises PrevizError."""
    if not isinstance(spec, dict):
        raise PrevizError('A previz spec is an object.')
    out = dict(version=VERSION)
    for key, low, high in (('width', 160, 2160), ('height', 160, 3840), ('fps', 8, 60), ('duration', .5, 3600)):
        v = spec.get(key)
        if type(v) not in (int, float) or not low <= v <= high:
            raise PrevizError(f'{key} must be a number from {low} to {high}.')
        out[key] = v
    out['width'], out['height'], out['fps'] = int(out['width']), int(out['height']), int(out['fps'])
    s = spec.get('set') or {}
    if s.get('preset', 'void') not in PRESETS:
        raise PrevizError('set.preset must be one of ' + ', '.join(PRESETS))
    out['set'] = {k: v for k, v in s.items() if k in ('preset', 'background', 'floor', 'ambient', 'key', 'fog')}
    actors = spec.get('actors') or []
    if len(actors) > 24:
        raise PrevizError('At most 24 actors.')
    ids = set()
    out['actors'] = []
    for a in actors:
        if not isinstance(a, dict) or a.get('type') not in ACTOR_TYPES or not isinstance(a.get('id'), str) or a['id'] in ids:
            raise PrevizError('Each actor needs a unique id and a type: ' + ', '.join(ACTOR_TYPES))
        ids.add(a['id'])
        clean = dict(id=a['id'], type=a['type'], color=a.get('color', '#cccccc'))
        for k in ('position', 'rotation', 'scale'):
            if k in a:
                clean[k] = vec(a[k], f"{a['id']}.{k}")
        out['actors'].append(clean)
    shots = spec.get('shots') or []
    if not shots or len(shots) > 200:
        raise PrevizError('Provide 1-200 shots.')
    out['shots'] = []
    for s in shots:
        if not isinstance(s, dict) or type(s.get('start')) not in (int, float) or type(s.get('end')) not in (int, float) or not 0 <= s['start'] < s['end'] <= out['duration'] + 1e-6:
            raise PrevizError('Each shot needs id, start < end within the duration.')
        cam = s.get('camera') or {}
        clean_cam = {}
        for k in ('from', 'to', 'look', 'look_to'):
            if k in cam:
                clean_cam[k] = vec(cam[k], f"{s.get('id')}.camera.{k}")
        for k in ('fov', 'fov_to'):
            if k in cam:
                if type(cam[k]) not in (int, float) or not 10 <= cam[k] <= 120:
                    raise PrevizError('fov is 10-120 degrees.')
                clean_cam[k] = cam[k]
        if cam.get('ease', 'inOut') not in EASES:
            raise PrevizError('ease is one of ' + ', '.join(EASES))
        clean_cam['ease'] = cam.get('ease', 'inOut')
        out['shots'].append(dict(id=str(s.get('id', '')), kind=str(s.get('kind', '')), start=float(s['start']), end=float(s['end']), camera=clean_cam,
                                 move=str(s.get('move', ''))[:20], framing=str(s.get('framing', ''))[:20]))
    tracks = spec.get('tracks') or []
    if len(tracks) > 400:
        raise PrevizError('At most 400 tracks.')
    out['tracks'] = []
    for t in tracks:
        if not isinstance(t, dict) or t.get('actor') not in ids or t.get('prop') not in PROPS or not isinstance(t.get('keys'), list) or not t['keys'] or len(t['keys']) > 600:
            raise PrevizError('Each track needs an actor id, a prop (' + ', '.join(PROPS) + ') and 1-600 keys.')
        keys = []
        for k in t['keys']:
            if not isinstance(k, (list, tuple)) or len(k) != 2 or type(k[0]) not in (int, float) or not math.isfinite(k[0]):
                raise PrevizError('A key is [time, value].')
            v = k[1]
            if t['prop'] == 'pose':
                if v not in POSES:
                    raise PrevizError('pose is one of ' + ', '.join(POSES))
            elif t['prop'] in ('pos', 'rot'):
                v = vec(v, 'key value')
            elif t['prop'] == 'scale':
                v = vec(v, 'key value') if isinstance(v, (list, tuple)) else float(v)
            elif type(v) not in (int, float) or not math.isfinite(v):
                raise PrevizError(f"{t['prop']} keys are numbers.")
            keys.append([float(k[0]), v])
        out['tracks'].append(dict(actor=t['actor'], prop=t['prop'], keys=sorted(keys, key=lambda k: k[0])))
    lyr = spec.get('lyrics') or []
    out['lyrics'] = [dict(text=str(l['text'])[:200], start=float(l['start']), end=float(l['end'])) for l in lyr
                     if isinstance(l, dict) and type(l.get('start')) in (int, float) and type(l.get('end')) in (int, float) and isinstance(l.get('text'), str)][:200]
    return out


# --- default spec from a board ---------------------------------------------------------------------------------------
MOVES = ('push_in', 'orbit_left', 'drift_high', 'pull_back', 'orbit_right', 'low_push')
# Framings give the video variety: wide shows the whole room, medium the carer beside the machine, close the machine.
FRAMING = {
    'wide': dict(focus=(-.2, .9, -1.5), dist=5.6),
    'medium': dict(focus=(-.4, .85, -1.3), dist=3.4),
    'close': dict(focus=(-.9, .7, -1.6), dist=2.5),
}
BEDSIDE_PLAN = ('wide', 'wide', 'medium', 'close', 'wide', 'medium', 'close', 'medium', 'wide', 'close', 'medium', 'wide', 'close')


def camera_for(move, focus, dist):
    fx, fy, fz = focus
    if move == 'push_in':
        return dict(**{'from': [fx + .4, fy + .9, fz + dist * 1.3], 'to': [fx + .1, fy + .5, fz + dist * .6]}, look=[fx, fy, fz], look_to=[fx, fy, fz], fov=38, fov_to=34)
    if move == 'pull_back':
        return dict(**{'from': [fx, fy + .5, fz + dist * .55], 'to': [fx + .6, fy + 1.1, fz + dist * 1.6]}, look=[fx, fy, fz], look_to=[fx, fy + .1, fz], fov=34, fov_to=42)
    if move == 'orbit_left':
        return dict(**{'from': [fx - dist, fy + .8, fz + dist * .9], 'to': [fx - dist * .35, fy + .8, fz + dist * 1.1]}, look=[fx, fy, fz], look_to=[fx, fy, fz], fov=40, fov_to=40)
    if move == 'orbit_right':
        return dict(**{'from': [fx + dist * .35, fy + .8, fz + dist * 1.1], 'to': [fx + dist, fy + .8, fz + dist * .9]}, look=[fx, fy, fz], look_to=[fx, fy, fz], fov=40, fov_to=40)
    if move == 'drift_high':
        return dict(**{'from': [fx - .5, fy + 2.6, fz + dist * .9], 'to': [fx + .5, fy + 2.4, fz + dist * .8]}, look=[fx, fy - .2, fz], look_to=[fx, fy - .2, fz], fov=44, fov_to=44)
    return dict(**{'from': [fx - .3, fy - .1, fz + dist * 1.2], 'to': [fx + .2, fy + .1, fz + dist * .7]}, look=[fx, fy + .2, fz], look_to=[fx, fy + .2, fz], fov=46, fov_to=36)


def bedside_actors():
    return [
        dict(id='machine', type='orb_machine', color='#7fd6ff', position=[-.9, .56, -1.6]),
        dict(id='carer', type='stick_human', color='#e8e2d6', position=[.15, 0, -.7], rotation=[0, -.9, 0]),
        dict(id='lamp', type='lamp', color='#ffb870', position=[.9, .85, -2.6]),
    ]


def default_spec(shots, analysis, lyrics_entries=None, story='generic', width=540, height=960, fps=24, title=''):
    """One camera move per shot (spoken shots get a close, slow push), staged actors for known stories."""
    if story not in STORIES:
        raise PrevizError('story is one of ' + ', '.join(STORIES))
    bedside = story == 'bedside_machine'
    out_shots, i = [], 0
    for s in sorted(shots, key=lambda x: x['start']):
        if s['kind'] == 'spoken':
            move, frame = 'push_in', 'close'
        elif bedside:
            frame = BEDSIDE_PLAN[i % len(BEDSIDE_PLAN)]
            move = MOVES[(i * 5 + (2 if frame == 'wide' else 0)) % len(MOVES)] if frame != 'close' else ('push_in' if i % 2 else 'low_push')
            i += 1
        else:
            move, frame = MOVES[i % len(MOVES)], 'medium'
            i += 1
        f = FRAMING[frame] if bedside else dict(focus=(0, 1.0, 0), dist=4.2)
        cam = camera_for(move, f['focus'], f['dist'])
        cam['ease'] = 'inOut'
        out_shots.append(dict(id=s['id'], kind=s['kind'], start=s['start'], end=s['end'], camera=cam, move=move, framing=frame))
    spec = dict(version=VERSION, width=width, height=height, fps=fps, duration=round(analysis['duration'], 3),
                set=dict(preset='bedroom' if bedside else 'void', background='#0b0d18', fog=[6, 26]),
                actors=bedside_actors() if bedside else [dict(id='subject', type='stick_human', color='#e8e2d6', position=[0, 0, 0])],
                shots=out_shots, tracks=[], lyrics=lyrics_entries or [])
    beat = 60 / analysis['bpm']
    t_end = analysis['duration']
    if bedside:
        spec['tracks'] += bedside_tracks(shots, analysis, beat, t_end)
    else:
        spec['tracks'].append(dict(actor='subject', prop='pose', keys=[[0, 'stand'], [t_end, 'stand']]))
    return validate(spec)


def bedside_tracks(shots, analysis, beat, t_end):
    """Machine breathes (glow on the beat grid), carer sits, tucks, rocks through the hook, and the machine's eyes open
    on the last spoken shot."""
    tracks = []
    glow = []
    t, k = 0.0, 0
    while t < t_end:
        glow.append([round(t, 3), .35 if k % 2 == 0 else .75])
        t += beat * 2
        k += 1
    glow.append([t_end, .5])
    tracks.append(dict(actor='machine', prop='glow', keys=glow))
    poses = [[0, 'stand'], [min(4, t_end), 'sit']]
    for s in sorted(shots, key=lambda x: x['start']):
        sec = (s.get('section') or '').lower()
        if 'hook' in sec:
            poses.append([s['start'] + .1, 'rock'])
        elif 'verse 2' in sec or 'final' in sec:
            poses.append([s['start'] + .1, 'lean_in'])
        elif 'verse' in sec:
            poses.append([s['start'] + .1, 'tuck'])
    poses = sorted({(round(t, 3), p) for t, p in poses})
    # drop consecutive duplicates
    keys = []
    for t, p in poses:
        if not keys or keys[-1][1] != p:
            keys.append([t, p])
    tracks.append(dict(actor='carer', prop='pose', keys=keys))
    spoken = [s for s in shots if s['kind'] == 'spoken']
    if spoken:
        last = spoken[-1]
        tracks.append(dict(actor='machine', prop='eyes', keys=[[0, 0], [last['start'] + .4, 0], [last['start'] + .9, 1], [t_end, 1]]))
        tracks.append(dict(actor='machine', prop='glow', keys=[[last['start'] + .4, .5], [last['start'] + 1.0, 1.0], [t_end, 1.0]]))
    return tracks


# --- sampling (mirrors static/previz.js) -----------------------------------------------------------------------------
def _ease(u):
    return 2 * u * u if u < .5 else 1 - (-2 * u + 2) ** 2 / 2


def sample_track(keys, t, prop):
    """The value of one track at time t, as previz.js computes it. Poses come back as the nearer pose name."""
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    i = 0
    while keys[i + 1][0] < t:
        i += 1
    (t0, v0), (t1, v1) = keys[i], keys[i + 1]
    u = _ease((t - t0) / max(1e-6, t1 - t0))
    if prop == 'pose':
        return v0 if u < .5 else v1
    if isinstance(v0, list):
        return [a + (b - a) * u for a, b in zip(v0, v1)]
    return v0 + (v1 - v0) * u


def state_at(spec, t):
    """What the stage shows at time t: the shot, and each actor's sampled props. A track takes effect from its first
    key, so a later track on the same prop only overrides from where it starts."""
    shots = sorted(spec['shots'], key=lambda s: s['start'])
    shot = next((s for s in reversed(shots) if t >= s['start']), shots[0])
    actors = {a['id']: dict(type=a['type']) for a in spec['actors']}
    for tr in spec['tracks']:
        if t < tr['keys'][0][0]:
            continue
        actors[tr['actor']][tr['prop']] = sample_track(tr['keys'], t, tr['prop'])
    return dict(shot=shot, actors=actors)


def still_name(shot_id, role):
    return f'{shot_id}-{role}'


# --- rendering -------------------------------------------------------------------------------------------------------
def find_browser():
    """A browser to drive headlessly. Order: explicit env var, Studio's pinned test browser, Playwright's, Chrome."""
    explicit = os.environ.get('IMAGINE_PREVIZ_BROWSER') or os.environ.get('IMAGINE_CAMERA_REFERENCE_BROWSER')
    candidates = [explicit] if explicit else []
    candidates += sorted(str(p) for p in (ROOT / '.validation' / 'parity-browser').glob('*/chrome-headless-shell'))
    cache = Path.home() / 'Library' / 'Caches' / 'ms-playwright'
    candidates += sorted(str(p) for p in cache.glob('chromium_headless_shell-*/*/chrome-headless-shell'))[::-1]
    candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', shutil.which('google-chrome') or '',
                   shutil.which('chromium') or '', shutil.which('chromium-browser') or '']
    return next((c for c in candidates if c and Path(c).is_file()), None)


def _tools(browser):
    node = shutil.which('node')
    if not node:
        raise PrevizError('Node.js is required to render previz.')
    browser = browser or find_browser()
    if not browser:
        raise PrevizError('No headless browser found. Set IMAGINE_PREVIZ_BROWSER to a Chrome/Chromium executable.')
    return node, browser


def _run(cmd, timeout):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        raise PrevizError('Previz render timed out.') from None
    if proc.returncode:
        raise PrevizError('Previz render failed: ' + (proc.stderr or proc.stdout)[-500:])
    return proc


def render(spec, out, audio=None, start=0, end=None, browser=None, timeout=1800, clean=False):
    """Render the spec to an MP4 with the song laid under it. Raises PrevizError with a clear message. `clean` drops the
    PREVIZ label, timecode and lyrics, for a code-made shot in the final cut."""
    spec = validate(spec)
    node, browser = _tools(browser)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    spec_path = out.with_suffix('.spec.json')
    spec_path.write_text(json.dumps(spec))
    cmd = [node, str(RENDERER), '--spec', str(spec_path), '--out', str(out), '--browser', browser, '--ffmpeg', audio_io.ffmpeg_path(),
           '--start', str(start), '--end', str(end if end is not None else spec['duration'])]
    if audio:
        cmd += ['--audio', str(audio)]
    if clean:
        cmd += ['--clean', '1']
    proc = _run(cmd, timeout)
    return dict(file=str(out), spec=str(spec_path), log=proc.stdout[-300:])


STILL_NAME = re.compile(r'^[A-Za-z0-9_-]{1,40}$')


def render_stills(spec, stills, out_dir, browser=None, timeout=600):
    """Clean PNG stills of the stage (no label, timecode or lyrics) at the requested times: [{name, t}].
    Returns {name: path}. Composition reference for image generation; never a video-model input."""
    spec = validate(spec)
    if not stills or len(stills) > 200:
        raise PrevizError('Request 1-200 stills.')
    for s in stills:
        if not isinstance(s, dict) or not STILL_NAME.match(str(s.get('name', ''))) or type(s.get('t')) not in (int, float) \
                or not 0 <= s['t'] <= spec['duration']:
            raise PrevizError('Each still is {name, t} with a simple name and a time inside the previz.')
    node, browser = _tools(browser)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path, list_path = out_dir / 'spec.json', out_dir / 'stills.json'
    spec_path.write_text(json.dumps(spec))
    list_path.write_text(json.dumps([dict(name=s['name'], t=s['t']) for s in stills]))
    _run([node, str(RENDERER), '--spec', str(spec_path), '--stills', str(list_path), '--out-dir', str(out_dir), '--browser', browser], timeout)
    files = {s['name']: out_dir / f"{s['name']}.png" for s in stills}
    missing = [n for n, f in files.items() if not f.is_file()]
    if missing:
        raise PrevizError('The renderer did not write: ' + ', '.join(missing[:6]))
    return files


def render_svg(svg_text, out, width, height, browser=None, timeout=300):
    """Rasterise an SVG plate to PNG in the headless browser (as an image: no scripts, no external loads)."""
    node, browser = _tools(browser)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    svg_path, spec_path = out.with_suffix('.svg'), out.with_suffix('.size.json')
    svg_path.write_text(svg_text, encoding='utf-8')
    spec_path.write_text(json.dumps(dict(width=width, height=height, fps=1, duration=1)))
    _run([node, str(RENDERER), '--spec', str(spec_path), '--svg', str(svg_path), '--out', str(out), '--browser', browser], timeout)
    if not out.is_file():
        raise PrevizError('The plate was not written.')
    return out
