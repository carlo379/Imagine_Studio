"""Extra board gates from Claudia's storyboard audit and failure log, run with the board audit.

- no two shots in a row share a camera setup (framing and move) unless one continues the other;
- no two shots share a first frame, unless one is a continuation;
- no shot under 1 s, and no run of four shots of the same length;
- the opening hooks: a first cut by 3.5 s and an opening shot that is not a slow, wide hold;
- a close-up's opening frame is an edit of a wider frame of the same place (made separately, it comes out a different
  room), and a continuing shot opens on the previous take's own last frame.
Each finding is {severity, shot, kind, message}.
"""
SHORT_S = 1.0
SAME_LEN_S = .05
FIRST_CUT_S = 3.5


def check(shots, previz=None, keyframes=None):
    out = []
    def add(sev, shot, kind, msg):
        out.append(dict(severity=sev, shot=shot, kind=kind, message=msg))
    ordered = sorted(shots, key=lambda s: s['start'])
    setups = {s['id']: (s.get('framing'), s.get('move')) for s in (previz or {}).get('shots', [])}
    plan = {s['shot_id']: s for s in (keyframes or {}).get('shots', [])}
    def still(sid, role):
        return next((x for x in plan.get(sid, {}).get('stills', []) if x['role'] == role), None)
    def continues(sid):
        x = still(sid, 'first')
        return bool(x and x.get('continues'))
    for a, b in zip(ordered, ordered[1:]):
        if setups.get(a['id']) and setups.get(a['id']) == setups.get(b['id']) and not continues(b['id']):
            add('warn', b['id'], 'same_setup', f"Same camera setup as {a['id']} ({setups[b['id']][0]}, {setups[b['id']][1]}); change the framing or the move.")
    for s in ordered:
        if s['end'] - s['start'] < SHORT_S:
            add('error', s['id'], 'short_shot', f"{s['end'] - s['start']:.2f}s is under {SHORT_S:.0f} s; it flashes by. Merge it or give it a bar.")
    for k in range(len(ordered) - 3):
        lens = [s['end'] - s['start'] for s in ordered[k:k + 4]]
        if max(lens) - min(lens) <= SAME_LEN_S:
            add('warn', ordered[k]['id'], 'same_length_run', f'Four shots of the same length in a row from {ordered[k]["id"]}; vary the holds with what each shot shows.')
    if ordered:
        cut = next((s['start'] for s in ordered if s['start'] > .05), None)
        if cut is None or cut > FIRST_CUT_S:
            add('warn', ordered[0]['id'], 'slow_hook', f'The first cut comes at {cut or ordered[0]["end"]:.1f}s; open on a hook and cut by {FIRST_CUT_S} s.')
        f, m = setups.get(ordered[0]['id'], (None, None))
        if f == 'wide' and m in ('pull_back', 'drift_high'):
            add('warn', ordered[0]['id'], 'mood_open', 'The film opens on a slow wide hold; open on something that tells part of the story.')
    seen = {}
    for s in ordered:
        x = still(s['id'], 'first')
        a = (x or {}).get('approved', {}) or {}
        if a.get('asset_id'):
            if a['asset_id'] in seen and not x.get('continues'):
                add('error', s['id'], 'shared_first_frame', f"Opens on the same image as {seen[a['asset_id']]}; give each shot its own frame.")
            seen.setdefault(a['asset_id'], s['id'])
        if x and setups.get(s['id'], (None,))[0] == 'close' and not x.get('derived_from') and not x.get('continues'):
            wider = [o for o in ordered if o['id'] != s['id'] and o.get('section') == s.get('section') and setups.get(o['id'], (None,))[0] in ('wide', 'medium')]
            if wider:
                add('warn', s['id'], 'close_not_derived', f"Make this close-up's frame by editing a wider frame of the same place (for example {wider[0]['id']}-first), and set derived_from.")
        if x and x.get('continues'):
            prev = next((o for o in reversed(ordered) if o['start'] < s['start']), None)
            if prev and x.get('continues') != prev['id']:
                add('error', s['id'], 'continuation_gap', f"A continuing shot must follow the shot it continues ({x['continues']}).")
            if not x.get('from_take_last_frame'):
                add('warn', s['id'], 'continuation_frame', 'A continuing shot should open on the previous take\'s own last frame (POST takes/last-frame), or the camera jumps.')
    return out
