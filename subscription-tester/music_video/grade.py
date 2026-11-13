"""Color script and grade matching: make every shot look like one film.

The color script gives each section a lighting phrase and a palette. The phrase feeds the keyframe prompts and the
palette is drawn as a strip, so the light changes across the video by design: color is made in the pictures. Grade
matching (each take pulled toward its approved still, one constant correction per clip so it cannot flicker) and grain
are off until the human asks for them.
"""
import copy
import re
from pathlib import Path

from music_video import audio_io, triage

# Default color arc for a night-time story: cold verses, warmer hook, the machine's cyan taking over at the reveal.
ARC = (
    ('intro', 'deep blue night, a single small warm lamp, most of the room in shadow', ['#0b1026', '#1d2a55', '#ffb870']),
    ('verse', 'cold blue moonlight with a small pool of amber lamp light on the bed', ['#101a3a', '#3a5a8c', '#e8a060']),
    ('pre', 'the amber lamp light creeping wider across the bed', ['#1a1e3a', '#6a5a7a', '#f0b070']),
    ('hook', 'warm amber lamp light filling the bedside, blue only at the edges', ['#2a1e2a', '#c07a40', '#ffd8a0']),
    ('chorus', 'warm amber lamp light filling the bedside, blue only at the edges', ['#2a1e2a', '#c07a40', '#ffd8a0']),
    ('bridge', "hard cyan glow from the machine competing with the lamp", ['#081a2a', '#2ab0d0', '#ffb870']),
    ('final', "the machine's cyan light blooming over everything, the lamp dim", ['#05121c', '#40d0ff', '#e0f8ff']),
    ('outro', "the machine's cyan light blooming over everything, the lamp dim", ['#05121c', '#40d0ff', '#e0f8ff']),
)
FALLBACK = ('night', 'soft warm lamp light against blue night shadows', ['#101a3a', '#3a5a8c', '#ffb870'])
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
DEFAULT = dict(sections={}, grain=0.0, match=False, match_strength=.7)   # no grade or texture until the human asks


class GradeError(ValueError):
    pass


def section_key(section):
    s = (section or '').lower()
    return next((key for key, _, _ in ARC if key in s), None)


def look_for(section, look):
    """The phrase and palette for a section: the director's override, else the default arc."""
    own = (look or {}).get('sections', {}).get(section or '')
    if own:
        return own['phrase'], own['palette']
    key = section_key(section)
    hit = next((x for x in ARC if x[0] == key), FALLBACK)
    return hit[1], hit[2]


def settings(current=None, changes=None):
    out = copy.deepcopy(DEFAULT)
    for src in (current or {}, changes or {}):
        if not isinstance(src, dict) or set(src) - set(DEFAULT):
            raise GradeError('look has sections, grain, match and match_strength.')
        if 'sections' in src:
            if not isinstance(src['sections'], dict) or len(src['sections']) > 40:
                raise GradeError('look.sections maps a section name to {phrase, palette}.')
            for name, v in src['sections'].items():
                if v is None:
                    out['sections'].pop(name, None)
                    continue
                if not isinstance(v, dict) or set(v) != {'phrase', 'palette'} or not isinstance(v['phrase'], str) \
                        or not 0 < len(v['phrase']) <= 300 or not isinstance(v['palette'], list) or not 1 <= len(v['palette']) <= 6 \
                        or not all(isinstance(c, str) and HEX.match(c) for c in v['palette']):
                    raise GradeError(f'look.sections.{name} is {{phrase (1-300 chars), palette (1-6 #rrggbb colors)}}.')
                out['sections'][name] = dict(phrase=v['phrase'], palette=v['palette'])
        for key, low, high in (('grain', 0, 1), ('match_strength', 0, 1)):
            if key in src:
                if type(src[key]) not in (int, float) or not low <= src[key] <= high:
                    raise GradeError(f'look.{key} is from {low} to {high}.')
                out[key] = float(src[key])
        if 'match' in src:
            if type(src['match']) is not bool:
                raise GradeError('look.match is true or false.')
            out['match'] = src['match']
    return out


def color_script(shots, look=None):
    """Cutaways carry no section: before the first line they take the intro look, later the section they sit in."""
    rows, current = [], 'Intro'
    for s in sorted(shots, key=lambda x: x['start']):
        current = s.get('section') or current
        phrase, palette = look_for(current, look)
        rows.append(dict(shot_id=s['id'], start=s['start'], end=s['end'], section=current, phrase=phrase, palette=palette))
    return rows



def strip(rows, out, width=1600, height=180):
    """Draw the color script as a strip: each shot's width follows its length, its palette as bands."""
    from PIL import Image, ImageDraw, ImageFont
    total = max(r['end'] for r in rows) or 1
    img = Image.new('RGB', (width, height), '#000000')
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 13)
    except OSError:
        font = ImageFont.load_default()
    band_h = height - 24
    for r in rows:
        x0, x1 = int(r['start'] / total * width), max(int(r['start'] / total * width) + 1, int(r['end'] / total * width))
        n = len(r['palette'])
        for k, c in enumerate(r['palette']):
            dr.rectangle([x0, int(k * band_h / n), x1, int((k + 1) * band_h / n)], fill=c)
        dr.line([x0, 0, x0, height], fill='#000000', width=2)
        dr.text((x0 + 4, band_h + 5), r['shot_id'], fill='#e8e8e8', font=font)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


# --- measuring and matching -----------------------------------------------------------------------------------------
def stats(path, start=None, length=None, samples=8):
    """Per-channel mean and standard deviation (0-255) of a video window or an image."""
    if Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
        from PIL import Image
        with Image.open(path) as im:
            raw = im.convert('RGB').resize((48, 85)).tobytes()
        chans = [raw[0::3], raw[1::3], raw[2::3]]
    else:
        fps = max(.5, samples / max(.5, length or 4))
        frames, _ = triage.frames(path, fps=fps, width=48, pix='rgb24', start=start, length=length)
        if not frames:
            raise audio_io.AudioError('No frames to measure.')
        raw = b''.join(frames)
        chans = [raw[0::3], raw[1::3], raw[2::3]]
    out = {}
    for name, ch in zip('rgb', chans):
        n = len(ch)
        mean = sum(ch) / n
        out[name] = [round(mean, 2), round((sum((v - mean) ** 2 for v in ch) / n) ** .5, 2)]
    return out


def match(take_stats, ref_stats, strength=.7):
    """Gain and offset per channel moving the take's color toward the reference, limited so a bad take is not
    pushed into ugliness."""
    out = {}
    for c in 'rgb':
        (tm, ts), (rm, rs) = take_stats[c], ref_stats[c]
        gain = min(1.4, max(.7, rs / ts if ts > 1 else 1.0))
        offset = rm - gain * tm
        gain = 1 + (gain - 1) * strength
        offset = max(-60.0, min(60.0, offset * strength))
        out[c] = [round(gain, 4), round(offset, 2)]
    return out


def lut_filter(correction):
    if not correction:
        return ''
    parts = [f"{c}='clip(val*{g}+{o},0,255)'" for c, (g, o) in correction.items()]
    return ',lutrgb=' + ':'.join(parts)


def grain_filter(grain):
    return f',noise=alls={int(round(grain * 24))}:allf=t' if grain and grain > 0 else ''
