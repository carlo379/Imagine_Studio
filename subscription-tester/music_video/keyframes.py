"""Keyframe plan: which still image each shot needs before any video is generated, drafted from the board and previz.

For every shot it records the opening instant to picture, the references to attach (character, machine, set,
style), a draft image prompt and the previz time to compare against. Most shots need one still, the opening frame,
which later becomes the take's first frame. A shot with a clear end state (the spoken reveal) also gets a closing
frame. The plan carries a cost ceiling for the whole batch. Nothing here generates an image.

Stills are pictures, not performances: their prompts never quote lyrics, never ask for text on screen and never ask
anyone to sing or speak. Previz stills may be used as a composition reference for the image model (as Studio's
shot-kit staging is); they are never sent to the video model.
"""
import re

from music_video import grade as grademod, lyrics as lyricmod, modes, previz as previzmod

ROLES = ('character', 'machine', 'set', 'style')
STILL_ROLES = ('first', 'last')
FIRST_OFFSET = .04          # the first visible instant of the shot
LAST_OFFSET = .05
MAX_PROMPT_WORDS = 160
TEXT_WORDS = re.compile(r'\b(text|caption|subtitle|lyrics?|letters|words|title card|logo|sign that says)\b', re.I)

FRAMING_TEXT = {
    'wide': 'Wide shot of the whole room',
    'medium': 'Medium shot of the carer beside the machine',
    'close': 'Close-up of the machine',
}
MOVE_TEXT = {
    'push_in': 'camera slightly back, ready to push in',
    'pull_back': 'camera close, ready to pull back',
    'orbit_left': 'camera off to the left side',
    'orbit_right': 'camera off to the right side',
    'drift_high': 'high angle looking down',
    'low_push': 'low angle near the floor',
}
POSE_TEXT = {
    'stand': 'standing beside the bed',
    'sit': 'sitting at the bedside',
    'lean_in': 'leaning in close to the machine',
    'reach': 'reaching out toward the machine',
    'rock': 'rocking gently, one hand resting on the machine',
    'tuck': 'tucking a blanket around the machine',
    'lie': 'lying down',
    'wave': 'raising one hand',
}
PURPOSE = {
    'cutaway': 'Hold the mood between lines: the room, the light, the machine at rest.',
    'sung_cut': 'Picture the line the song sings, without anyone miming it.',
    'spoken': 'The machine speaks its line on camera; this is the reveal.',
}
STYLE = 'Cinematic still, {light}, shallow depth of field, film grain.'
ENDING = 'Vertical 9:16 frame. No text, no captions, no logos.'


class KeyframeError(ValueError):
    pass


def eyes_text(value):
    if value is None:
        return 'its eyes closed'
    return 'its eyes open, glowing softly' if value >= .5 else 'its eyes closed'


def glow_text(value):
    if value is None:
        return 'a faint glow'
    return 'a bright, steady glow' if value >= .8 else 'a low, breathing glow' if value >= .45 else 'a faint glow'


def moment(story, state, framing, move, kind):
    """One plain sentence for what the frame shows, from the previz state at that instant."""
    actors = state['actors'] if state else {}
    if story == 'bedside_machine':
        carer = actors.get('carer', {})
        machine = actors.get('machine', {})
        pose = POSE_TEXT.get(carer.get('pose'), 'sitting at the bedside')
        m = f"the small machine resting on the bed with {glow_text(machine.get('glow'))} and {eyes_text(machine.get('eyes'))}"
        head = FRAMING_TEXT.get(framing, 'Medium shot')
        if framing == 'close':
            return f"{head}: {m}; the carer's hand just in frame. {MOVE_TEXT.get(move, '').capitalize()}.".replace(' .', '.')
        return f"{head} at night: the carer {pose}, {m}. {MOVE_TEXT.get(move, '').capitalize()}.".replace(' .', '.')
    subject = actors.get('subject', {})
    pose = subject.get('pose', 'stand')
    return f"{(framing or 'medium').capitalize()} shot of the subject, {pose.replace('_', ' ')}. {MOVE_TEXT.get(move, '').capitalize()}.".replace(' .', '.')


def prompt_for(text_moment, refs, light=None):
    lines = [text_moment]
    attach = [f'[{role} reference]' for role in ROLES if refs.get(role)]
    if attach:
        lines.append('Match ' + ', '.join(attach) + ' exactly.')
    lines += [STYLE.format(light=light or grademod.FALLBACK[1]), ENDING]
    return ' '.join(lines)


def still_times(shot):
    first = round(shot['start'] + FIRST_OFFSET, 3)
    out = [('first', first)]
    if shot['kind'] == 'spoken':                # the spoken reveal ends in a clear end state
        out.append(('last', round(max(first, shot['end'] - LAST_OFFSET), 3)))
    return out


def draft(shots, spec=None, story='generic', references=None, candidates=2, price_per_image=None, look=None):
    """A keyframe plan from the board (and the previz, when it exists). The light in each prompt follows the color
    script for the shot's section."""
    refs = clean_refs(references)
    by_id = {s['id']: s for s in (spec or {}).get('shots', [])}
    script = {r['shot_id']: r for r in grademod.color_script(shots, look)}
    out = []
    for shot in sorted(shots, key=lambda s: s['start']):
        p = by_id.get(shot['id'], {})
        framing, move = p.get('framing') or 'medium', p.get('move') or ''
        stills = []
        light = script[shot['id']]['phrase']
        for role, t in still_times(shot):
            state = previzmod.state_at(spec, t) if spec else None
            m = moment(story, state, framing, move, shot['kind'])
            stills.append(dict(name=previzmod.still_name(shot['id'], role), role=role, t=t, moment=m, light=light,
                               prompt=prompt_for(m, refs, light), previz_still=None, candidates=[], approved=None,
                               made_from_first=False if role == 'last' else None, reviews={}))
        out.append(dict(shot_id=shot['id'], kind=shot['kind'], start=shot['start'], end=shot['end'], section=shot.get('section'),
                        line=shot.get('line'), text=shot.get('text'), framing=framing, move=move,
                        purpose=PURPOSE.get(shot['kind'], ''), stills=stills))
    plan = dict(story=story, references=refs, candidates=candidates, price_per_image=price_per_image, shots=out,
                previz_used=bool(spec))
    plan['estimate'] = estimate(plan)
    return plan


def clean_refs(references):
    refs = references or {}
    if not isinstance(refs, dict) or set(refs) - set(ROLES):
        raise KeyframeError('references maps a role (' + ', '.join(ROLES) + ') to an asset id.')
    for k, v in refs.items():
        if v is not None and (not isinstance(v, str) or not 0 < len(v) <= 120):
            raise KeyframeError(f'references.{k} must be an asset id or null.')
    return {k: refs.get(k) for k in ROLES}


def estimate(plan):
    stills = sum(len(s['stills']) for s in plan['shots'])
    out = dict(stills=stills, candidates_per_still=plan['candidates'], images=stills * plan['candidates'])
    if plan.get('price_per_image') is not None:
        out['cost_ceiling'] = round(out['images'] * plan['price_per_image'], 2)
    return out


def check(plan, board_shots, has_previz=True):
    """Findings to clear before the batch is approved: {severity, shot, still, kind, message}."""
    found = []
    def add(sev, shot, still, kind, msg):
        found.append(dict(severity=sev, shot=shot, still=still, kind=kind, message=msg))
    refs = plan['references']
    story = plan['story']
    if not refs.get('character'):
        add('error', None, None, 'no_character_reference', 'Attach the approved character sheet so every still shows the same person.')
    if story == 'bedside_machine' and not refs.get('machine'):
        add('error', None, None, 'no_machine_reference', 'Attach the approved machine design so it looks the same in every still.')
    if not refs.get('set'):
        add('warn', None, None, 'no_set_reference', 'A set reference keeps the room consistent across stills.')
    if not has_previz:
        add('warn', None, None, 'no_previz', 'Without a previz the framing is a default; generate the previz for varied framing and comparison stills.')
    board = {s['id']: s for s in board_shots}
    planned = {s['shot_id'] for s in plan['shots']}
    for sid in board:
        if sid not in planned:
            add('error', sid, None, 'shot_missing', 'This board shot has no keyframe; redraft the plan.')
    lyric_words = {s['id']: lyricmod.clean_words(s.get('text') or '') for s in board_shots}
    for s in plan['shots']:
        if s['shot_id'] not in board:
            add('error', s['shot_id'], None, 'stale_shot', 'This shot is no longer on the board; redraft the plan.')
            continue
        b = board[s['shot_id']]
        if abs(b['start'] - s['start']) > 1e-3 or abs(b['end'] - s['end']) > 1e-3:
            add('error', s['shot_id'], None, 'stale_timing', 'The board timing changed; redraft the plan.')
        roles = [x['role'] for x in s['stills']]
        if 'first' not in roles:
            add('error', s['shot_id'], None, 'no_first_frame', 'Every shot needs an opening frame.')
        if b['kind'] == 'spoken' and 'last' not in roles:
            add('warn', s['shot_id'], None, 'no_last_frame', 'The spoken reveal has a clear end state; plan its closing frame.')
        for x in s['stills']:
            prompt = x.get('prompt') or ''
            if not prompt.strip() or prompt.strip() == 'TODO':
                add('error', s['shot_id'], x['name'], 'todo', 'Write the image prompt.')
                continue
            if not b['start'] <= x['t'] <= b['end']:
                add('error', s['shot_id'], x['name'], 'outside_shot', 'The still time is outside its shot.')
            if re.search(r'[“"][^”"]+[”"]', prompt):
                add('error', s['shot_id'], x['name'], 'quoted_words', 'A still prompt must not quote words; image models paint them as text.')
            if modes.SINGING_WORDS.search(prompt):
                add('error', s['shot_id'], x['name'], 'performance_in_still', 'A still is a picture: do not ask anyone to sing or speak.')
            stripped = re.sub(r'\bno (text|captions?|logos?|subtitles?)\b', '', prompt, flags=re.I)
            stripped = re.sub(r'\bno [a-z]+, no [a-z]+, no [a-z]+\b', '', stripped, flags=re.I)
            if TEXT_WORDS.search(stripped):
                add('warn', s['shot_id'], x['name'], 'text_on_screen', 'The prompt mentions text; stills should carry no words.')
            line = lyric_words.get(s['shot_id']) or []
            if len(line) >= 4 and ' '.join(line) in ' '.join(lyricmod.clean_words(prompt)):
                add('error', s['shot_id'], x['name'], 'lyric_in_still', 'The prompt contains the lyric line; describe the picture instead.')
            if len(re.findall(r'\w+', prompt)) > MAX_PROMPT_WORDS:
                add('warn', s['shot_id'], x['name'], 'long_prompt', 'Long image prompts drift; keep one clear moment.')
            for role in ROLES:
                if f'[{role} reference]' in prompt and not refs.get(role):
                    add('error', s['shot_id'], x['name'], 'reference_not_attached', f'The prompt names the {role} reference but none is attached.')
    all_stills = [x for s in plan['shots'] for x in s['stills']]
    progress = dict(stills=len(all_stills), with_candidates=sum(1 for x in all_stills if x.get('candidates')),
                    approved=sum(1 for x in all_stills if x.get('approved')))
    return dict(ok=not any(f['severity'] == 'error' for f in found), findings=found, estimate=estimate(plan), progress=progress)


EDITABLE = ('moment', 'prompt', 't', 'candidates', 'approve', 'made_from_first', 'derived_from', 'continues')
MAX_CANDIDATES = 8


def edit(plan, changes):
    """Apply edits to stills: [{name, moment?, prompt?, t?, candidates?, approve?, made_from_first?}].

    candidates lists generated image asset ids; approve is {asset_id, human_words} (the human's own words, verbatim)
    or null to withdraw. Asset existence is checked by the caller."""
    by_name = {x['name']: (s, x) for s in plan['shots'] for x in s['stills']}
    for c in changes:
        if not isinstance(c, dict) or c.get('name') not in by_name:
            raise KeyframeError('Each change needs the name of a still in this plan (for example s003-first).')
        extra = set(c) - set(EDITABLE) - {'name'}
        if extra:
            raise KeyframeError('Editable still fields: ' + ', '.join(EDITABLE) + '.')
        shot, still = by_name[c['name']]
        for key in ('moment', 'prompt'):
            if key in c:
                if not isinstance(c[key], str) or len(c[key]) > 4000:
                    raise KeyframeError(f'{key} is text up to 4,000 characters.')
                still[key] = c[key]
        if 't' in c:
            if type(c['t']) not in (int, float) or not shot['start'] <= c['t'] <= shot['end']:
                raise KeyframeError(f"t must be inside the shot ({shot['start']}-{shot['end']} s).")
            still['t'] = round(float(c['t']), 3)
            still['previz_still'] = None
        if 'candidates' in c:
            v = c['candidates']
            if not isinstance(v, list) or len(v) > MAX_CANDIDATES or not all(isinstance(a, str) and 0 < len(a) <= 120 for a in v) or len(set(v)) != len(v):
                raise KeyframeError(f'candidates is a list of up to {MAX_CANDIDATES} distinct image asset ids.')
            still['candidates'] = v
            still['reviews'] = {a: r for a, r in still.get('reviews', {}).items() if a in v}
            if still.get('approved') and still['approved']['asset_id'] not in v:
                still['approved'] = None
        if 'approve' in c:
            v = c['approve']
            if v is None:
                still['approved'] = None
            else:
                if not isinstance(v, dict) or set(v) != {'asset_id', 'human_words'} or v['asset_id'] not in still.get('candidates', []):
                    raise KeyframeError('approve is {asset_id, human_words}, and the asset must be one of the still\'s candidates.')
                if not isinstance(v['human_words'], str) or not v['human_words'].strip() or len(v['human_words']) > 2000:
                    raise KeyframeError("human_words must quote the human's own approval, verbatim (1-2,000 characters).")
                still['approved'] = dict(asset_id=v['asset_id'], human_words=v['human_words'].strip())
        if 'derived_from' in c:
            v = c['derived_from']
            if v is not None and (v not in by_name or v == still['name']):
                raise KeyframeError('derived_from names another still in this plan (the wider frame this one was edited from), or null.')
            still['derived_from'] = v
        if 'continues' in c:
            v = c['continues']
            shot_ids = [s['shot_id'] for s in plan['shots']]
            if still['role'] != 'first' or (v is not None and (v not in shot_ids or v == shot['shot_id'])):
                raise KeyframeError('continues is set on an opening still: the id of the shot this one continues, or null.')
            still['continues'] = v
        if 'made_from_first' in c:
            if still['role'] != 'last' or type(c['made_from_first']) is not bool:
                raise KeyframeError('made_from_first is true or false, on a closing (last) still only.')
            still['made_from_first'] = c['made_from_first']
    return plan
