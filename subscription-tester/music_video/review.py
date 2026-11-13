"""Still review: a comparison sheet (planned previz frame beside the generated candidates and the lyric line) and an
independent consistency review of each candidate against the approved references.

The consistency review follows Studio's review rules: a separate reviewer session on the model the human chose gets
only the packet (references, the candidate, the planned composition and the look), never the director's reasoning.
Code, not the reviewer, turns the scores into a suggestion. The human still approves each still in their own words.
"""
import re
import time
from pathlib import Path

ASPECTS = ('person', 'machine', 'room', 'look')
SEVERITIES = ('blocking', 'polish')
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,99}$')

BRIEF = '''You are checking one generated still for a music video against its approved references. You did not make it.
Score each aspect from 0 to 10:
- person: is this the same person as the character reference (face, hair, build, wardrobe)?
- machine: is this the same machine as the machine design (shape, size, materials, its light)?
- room: is this the same room and props as the set reference, and does the room read as the same place as the plan?
- look: does the light and color match the planned look phrase and palette, and the planned composition?
Score an aspect 10 when it has no reference and is not in frame. List each issue with severity "blocking" (the still
cannot be used: wrong face, wrong machine, text in the image, broken anatomy) or "polish", its aspect, the problem and
a concrete fix for the next image prompt. Report how many images you examined. Return only the JSON in submit.schema.'''


class ReviewError(ValueError):
    pass


def suggestion(scores, issues):
    if any(i['severity'] == 'blocking' for i in issues) or min(scores.values()) < 6:
        return 'regenerate'
    if min(scores.values()) < 8:
        return 'usable_with_fixes'
    return 'consistent'


def _name(value, field):
    if not isinstance(value, str) or not NAME.match(value.strip()):
        raise ReviewError(f'{field} must name the model or session (1-100 letters, digits or . _ : / @ + -).')
    return value.strip()


def validate(data, chosen_reviewer=None, director_session=None):
    """A reviewer's submission, checked; returns the stored record with Studio's suggestion."""
    if not isinstance(data, dict) or set(data) - {'reviewer', 'scores', 'issues', 'images_examined', 'summary'}:
        raise ReviewError('Send reviewer, scores, issues, images_examined and summary.')
    r = data.get('reviewer')
    if not isinstance(r, dict) or set(r) - {'model', 'session_id', 'product'}:
        raise ReviewError('reviewer is {"model", "session_id", "product"?}.')
    reviewer = dict(model=_name(r.get('model'), 'reviewer.model'), session_id=_name(r.get('session_id'), 'reviewer.session_id'))
    if chosen_reviewer and reviewer['model'] != chosen_reviewer['model']:
        raise ReviewError(f"The human chose {chosen_reviewer['model']} to review, not {reviewer['model']}.")
    if director_session and director_session == reviewer['session_id']:
        raise ReviewError('The reviewer must run in a new session, separate from the director that made the candidates.')
    scores = data.get('scores')
    if not isinstance(scores, dict) or set(scores) != set(ASPECTS) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 10 for v in scores.values()):
        raise ReviewError('scores needs person, machine, room and look, each 0-10.')
    issues = data.get('issues')
    if not isinstance(issues, list) or len(issues) > 20:
        raise ReviewError('issues is a list of at most 20 items (empty when there are none).')
    clean = []
    for n, i in enumerate(issues):
        if not isinstance(i, dict) or i.get('severity') not in SEVERITIES or i.get('aspect') not in ASPECTS + ('other',) \
                or not isinstance(i.get('problem'), str) or not i['problem'].strip() or not isinstance(i.get('fix', ''), str):
            raise ReviewError(f'Issue {n + 1}: needs severity blocking|polish, an aspect, a problem and a fix.')
        clean.append(dict(severity=i['severity'], aspect=i['aspect'], problem=i['problem'].strip()[:500], fix=i.get('fix', '').strip()[:500]))
    examined = data.get('images_examined')
    if type(examined) is not int or examined < 1:
        raise ReviewError('images_examined must say how many images you looked at.')
    summary = data.get('summary', '')
    if not isinstance(summary, str) or len(summary) > 1000:
        raise ReviewError('summary is at most 1,000 characters.')
    scores = {k: float(scores[k]) for k in ASPECTS}
    return dict(reviewer=reviewer, scores=scores, issues=clean, images_examined=examined, summary=summary.strip(),
                suggestion=suggestion(scores, clean), submitted_at=time.time())


def local_checks(image_path, want_ratio=9 / 16):
    """Free checks before a reviewer looks: it opens, its shape matches the film, it is not tiny."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(image_path) as im:
            w, h = im.size
    except (OSError, UnidentifiedImageError):
        return [dict(severity='blocking', kind='unreadable', message='The image cannot be opened.')]
    out = []
    if abs(w / h - want_ratio) > .03:
        out.append(dict(severity='blocking', kind='wrong_shape', message=f'{w}x{h} is not the film\'s frame shape; it would be cropped.'))
    if min(w, h) < 512:
        out.append(dict(severity='polish', kind='small', message=f'{w}x{h} is small for a first frame.'))
    return out


# --- comparison sheet -------------------------------------------------------------------------------------------------
def _thumb(path, w, h):
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail((w, h))
            canvas = Image.new('RGB', (w, h), '#000000')
            canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
            return canvas
    except (OSError, UnidentifiedImageError, TypeError, AttributeError):
        return None


def sheet(rows, out, tile_w=216, tile_h=384):
    """rows: [{label, line, previz (path|None), candidates: [{label, path, approved, suggestion}]}] -> one PNG."""
    from PIL import Image, ImageDraw, ImageFont
    cols = 1 + max([len(r['candidates']) for r in rows] + [1])
    head = 46
    img = Image.new('RGB', (cols * (tile_w + 8) + 8, len(rows) * (tile_h + head + 10) + 8), '#101218')
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 14)
        small = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 12)
    except OSError:
        font = small = ImageFont.load_default()
    y = 8
    for r in rows:
        dr.text((8, y), r['label'], fill='#ffd84a', font=font)
        dr.text((8, y + 20), (r.get('line') or '')[:120], fill='#c8ccd8', font=small)
        y += head
        tiles = [('PREVIZ', r.get('previz'), None, None)] + [(c['label'], c['path'], c.get('approved'), c.get('suggestion')) for c in r['candidates']]
        for k, (label, path, approved, sug) in enumerate(tiles):
            x = 8 + k * (tile_w + 8)
            t = _thumb(path, tile_w, tile_h) if path else None
            if t:
                img.paste(t, (x, y))
            else:
                dr.rectangle([x, y, x + tile_w, y + tile_h], outline='#3a3f52')
                dr.text((x + 8, y + tile_h // 2), 'missing' if path else 'none yet', fill='#8b91a8', font=small)
            colour = '#4ade80' if approved else '#ffffff'
            if approved:
                dr.rectangle([x - 3, y - 3, x + tile_w + 3, y + tile_h + 3], outline='#4ade80', width=3)
            dr.rectangle([x, y, x + tile_w, y + 20], fill='#000000')
            dr.text((x + 6, y + 3), label + ('  APPROVED' if approved else '') + (f'  {sug}' if sug else ''), fill=colour, font=small)
        y += tile_h + 10
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


# --- review of the finished cut ---------------------------------------------------------------------------------------
CUT_FRAMES = 8
CUT_BRIEF = '''You are a fresh-eyes reviewer of a music-video cut you have not seen before. You get one sheet per shot: eight
frames as cut, in order, with the shot's time, kind and lyric line. For every shot, say ok, polish or blocking:
blocking means it cannot ship (wrong face or machine, broken anatomy, garbled text, a visible pop or freeze, a jump
cut inside one scene, a cut that splits a word); polish means better if fixed. Give the problem and a concrete fix for
the next prompt or first frame (never "patch the frames"). Stills cannot show motion or sync: say so instead of
guessing. Report how many frames you examined. Return only the JSON in submit.schema.'''
CUT_VERDICTS = ('ok', 'polish', 'blocking')


def cut_frames(cut, start, end, out_dir, name, n=CUT_FRAMES, width=320):
    """n frames spread evenly inside [start, end) of the cut, as JPEGs."""
    import subprocess
    from music_video import audio_io
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    files = []
    span = max(.05, end - start)
    for k in range(n):
        t = start + span * (k + .5) / n
        f = Path(out_dir) / f'{name}-{k + 1}.jpg'
        subprocess.run([audio_io.ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-ss', f'{t:.3f}', '-i', str(cut), '-frames:v', '1',
                        '-vf', f'scale={width}:-2', '-q:v', '4', str(f)], capture_output=True, timeout=120)
        files.append((round(t, 2), f))
    return files


def cut_sheet(shot, frames, out, label):
    """One sheet per shot: eight frames as cut in two rows of four, with the time, kind and line."""
    from PIL import Image, ImageDraw, ImageFont
    thumbs = [_thumb(f, 200, 356) for _, f in frames]
    img = Image.new('RGB', (4 * 208 + 8, 2 * (356 + 26) + 52), '#101218')
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 14)
        small = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 12)
    except OSError:
        font = small = ImageFont.load_default()
    dr.text((8, 8), label, fill='#ffd84a', font=font)
    dr.text((8, 28), (shot.get('text') or shot.get('purpose') or '')[:110], fill='#c8ccd8', font=small)
    for k, (t, _) in enumerate(frames):
        x, y = 8 + (k % 4) * 208, 52 + (k // 4) * (356 + 26)
        if thumbs[k]:
            img.paste(thumbs[k], (x, y + 18))
        dr.text((x, y + 2), f'{k + 1}  {t:.2f}s', fill='#ffffff', font=small)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def validate_cut_review(data, shot_ids, chosen_reviewer=None, director_session=None, earlier_sessions=()):
    if not isinstance(data, dict) or set(data) - {'reviewer', 'shots', 'frames_examined', 'summary'}:
        raise ReviewError('Send reviewer, shots, frames_examined and summary.')
    r = data.get('reviewer')
    if not isinstance(r, dict) or set(r) - {'model', 'session_id', 'product'}:
        raise ReviewError('reviewer is {"model", "session_id", "product"?}.')
    reviewer = dict(model=_name(r.get('model'), 'reviewer.model'), session_id=_name(r.get('session_id'), 'reviewer.session_id'))
    if chosen_reviewer and reviewer['model'] != chosen_reviewer['model']:
        raise ReviewError(f"The human chose {chosen_reviewer['model']} to review, not {reviewer['model']}.")
    if director_session and director_session == reviewer['session_id']:
        raise ReviewError('The reviewer must run in a new session, separate from the director.')
    if reviewer['session_id'] in earlier_sessions:
        raise ReviewError('Each fresh-eyes review comes from a new session; this session already reviewed this cut.')
    rows = data.get('shots')
    if not isinstance(rows, list) or {x.get('shot_id') for x in rows if isinstance(x, dict)} != set(shot_ids) or len(rows) != len(shot_ids):
        raise ReviewError('shots needs exactly one entry per shot of the cut: {shot_id, verdict, problem?, fix?}. An empty review is a failed review.')
    clean = []
    for x in rows:
        if x.get('verdict') not in CUT_VERDICTS or set(x) - {'shot_id', 'verdict', 'problem', 'fix'}:
            raise ReviewError(f"{x.get('shot_id')}: verdict is ok, polish or blocking.")
        if x['verdict'] != 'ok' and not (isinstance(x.get('problem'), str) and x['problem'].strip()):
            raise ReviewError(f"{x['shot_id']}: say what is wrong.")
        clean.append(dict(shot_id=x['shot_id'], verdict=x['verdict'], problem=(x.get('problem') or '').strip()[:500], fix=(x.get('fix') or '').strip()[:500]))
    examined = data.get('frames_examined')
    if type(examined) is not int or examined < len(shot_ids):
        raise ReviewError('frames_examined must count the frames you looked at (at least one per shot).')
    summary = data.get('summary', '')
    if not isinstance(summary, str) or len(summary) > 2000:
        raise ReviewError('summary is at most 2,000 characters.')
    blocking = [x['shot_id'] for x in clean if x['verdict'] == 'blocking']
    return dict(reviewer=reviewer, shots=clean, frames_examined=examined, summary=summary.strip(), blocking=blocking,
                suggestion='fix_before_watching' if blocking else 'ready_for_the_human', submitted_at=time.time())
