"""Storyboard on the song clock: draft shots from the bar grid and lyric slots, then audit them.

Nothing here generates media. A shot is plain data the director edits; `audit` is the gate before any spend.
"""
import math
import re

from music_video import lyrics, modes

FPS = 24
TAKE_MIN_PER_MIN, TAKE_MAX_PER_MIN = 7, 14        # take-based films run about 7-12 shots a minute


def bar_index(bars, t, tolerance=1 / FPS):
    for i, b in enumerate(bars):
        if abs(b - t) <= tolerance:
            return i
    return None


def draft(analysis, sheet_text, mode='spoken_word', spoken_lines=None, start_bar=0, pace=1.0, max_clip=lyrics.MAX_CLIP_S, lead_in=.3,
          line_times=None):
    """One shot per lyric line on consecutive bar slots, then cutaways for the gaps.

    The delivery mode decides each line: `spoken` lines get a spoken shot (she speaks it, her take audio is the vocal);
    lines the song's own vocal carries get a visual-only `sung_cut` shot (no generated audio, ever)."""
    deliver = modes.delivery(mode, lyrics.parse(sheet_text), spoken_lines)
    if line_times:
        return draft_timed(analysis, sheet_text, deliver, line_times, mode, lead_in)
    bars = analysis['bars'] + [analysis['duration']]
    bar_s = (analysis['bars'][-1] - analysis['bars'][0]) / max(1, len(analysis['bars']) - 1)
    lines = lyrics.parse(sheet_text)
    fit = lyrics.fit_to_grid(lines, bar_s, max_clip, pace)
    shots, cursor = [], start_bar
    for line, f in zip(lines, fit):
        if f['bars'] is None:
            raise ValueError(f"Line {line['line'] + 1} cannot fit four bars; split it first.")
        end = min(cursor + f['bars'], len(bars) - 1)
        spoken = deliver[line['line']] == 'spoken'
        shots.append(dict(kind='spoken' if spoken else 'sung_cut', line=line['line'], text=line['text'], bar_start=cursor,
                          bar_end=end, start=round(bars[cursor], 3), end=round(bars[end], 3), speech_s=f['speech_s'],
                          lead_in_s=lead_in, section=line['section'], prompt='TODO', purpose='TODO',
                          verdict=f['verdict'], audio='take' if spoken else 'none', mode=mode))
        cursor = end
    out, last = [], 0
    for s in sorted(shots, key=lambda s: s['bar_start']):
        if s['bar_start'] > last:
            out += cutaways(bars, last, s['bar_start'])
        out.append(s)
        last = s['bar_end']
    if last < len(bars) - 1:
        out += cutaways(bars, last, len(bars) - 1)
    for i, s in enumerate(out):
        s['id'] = f's{i + 1:03d}'
    if out:
        out[0]['start'] = 0.0          # the picture covers the song from its first frame (the first bar may come later)
    return out


def nearest_bar(bars, t):
    return min(range(len(bars)), key=lambda i: abs(bars[i] - t))


def draft_timed(analysis, sheet_text, deliver, line_times, mode, lead_in=.3):
    """Shots follow the song's real line times: each line starts on the bar nearest its first word and runs to the
    bar at or after its last word; cutaways fill whatever is left (intros, gaps, tails)."""
    bars = analysis['bars'] + [analysis['duration']]
    lines = lyrics.parse(sheet_text)
    timed = {t['line']: t for t in line_times if t.get('start') is not None}
    shots, floor = [], 0
    for line in lines:
        t = timed.get(line['line'])
        if not t:
            raise ValueError(f"Line {line['line'] + 1} has no time; align the lyrics or add its time.")
        a = max(floor, nearest_bar(bars[:-1], t['start']))
        b = next((i for i in range(a + 1, len(bars)) if bars[i] >= t['end'] - .25), len(bars) - 1)
        spoken = deliver[line['line']] == 'spoken'
        shots.append(dict(kind='spoken' if spoken else 'sung_cut', line=line['line'], text=line['text'], bar_start=a, bar_end=b,
                          start=round(bars[a], 3), end=round(bars[b], 3),
                          speech_s=round(t['end'] - t['start'], 2) if not spoken else lyrics.spoken_seconds(line)['speech_s'],
                          song_start=t['start'], song_end=t['end'], lead_in_s=lead_in, section=line['section'],
                          prompt='TODO', purpose='TODO', verdict='ok', audio='take' if spoken else 'none', mode=mode))
        floor = b
    out, last = [], 0
    for s in sorted(shots, key=lambda s: s['bar_start']):
        if s['bar_start'] > last:
            out += cutaways(bars, last, s['bar_start'])
        out.append(s)
        last = s['bar_end']
    if last < len(bars) - 1:
        out += cutaways(bars, last, len(bars) - 1)
    for i, s in enumerate(out):
        s['id'] = f's{i + 1:03d}'
    if out:
        out[0]['start'] = 0.0          # the picture covers the song from its first frame (the first bar may come later)
    return out


def cutaways(bars, a, b, per=2):
    """Cutaway shots across bars [a, b), two bars each, the last absorbing an odd bar."""
    out, i = [], a
    while i < b:
        j = b if b - i <= per + 1 and b - i != per * 2 else min(b, i + per)
        if b - i == 3:
            j = b
        out.append(dict(kind='cutaway', bar_start=i, bar_end=j, start=round(bars[i], 3), end=round(bars[j], 3),
                        prompt='TODO', purpose='TODO'))
        i = j
    return out


def audit(shots, analysis, sheet_text, price_per_second=None, mode=None, options=None):
    """Findings the director must clear before the board is approved. Each is {severity, shot, kind, message}."""
    found = []
    def add(sev, shot, kind, msg):
        found.append(dict(severity=sev, shot=shot, kind=kind, message=msg))
    bars, dur = analysis['bars'], analysis['duration']
    ordered = sorted(shots, key=lambda s: s['start'])
    lines = lyrics.parse(sheet_text)
    said = {}
    mode = mode or next((s.get('mode') for s in ordered if s.get('mode')), None)
    if mode:
        for r in modes.requirements(mode, options):
            add(r['severity'], None, r['kind'], r['message'])
    for s in ordered:
        sid = s.get('id', '?')
        if bar_index(bars, s['start']) is None and s['start'] > .05:
            add('error', sid, 'off_bar', 'Start is not on a bar line; cuts must land on bars.')
        if s['end'] <= s['start']:
            add('error', sid, 'empty', 'Shot has no length.')
        if any(str(s.get(k, '')).strip() in ('', 'TODO') for k in ('prompt', 'purpose')):
            add('error', sid, 'todo', 'Fill in the prompt and the purpose (why this shot exists).')
        if s['kind'] in modes.NON_SPEECH_KINDS or s['kind'] == 'sung_cut':
            if s.get('audio', 'none') != 'none':
                add('error', sid, 'grok_audio_in_visual_shot', 'Generated audio from a visual-only shot must never be used. Set audio to none; the song carries the sound.')
            if s.get('prompt') not in ('', 'TODO'):
                if re.search(r'[“"][^”"]+[”"]', s['prompt']) or modes.SINGING_WORDS.search(s['prompt']):
                    add('error', sid, 'vocal_in_visual_prompt', 'A visual-only shot must not ask the model to sing, speak or quote words; its audio would be discarded and the face would mime wrongly.')
        if s['kind'] == 'sung_cut':
            said.setdefault(s['line'], []).append(sid)
        if s['kind'] == 'spoken':
            if s.get('audio') != 'take':
                add('error', sid, 'spoken_audio_off', 'A spoken shot must generate audio: its take is the vocal.')
            if mode == 'spoken_hooks' and not s.get('hook', True):
                add('warn', sid, 'not_a_hook', 'In spoken-hooks mode only the key lines are spoken.')
            said.setdefault(s['line'], []).append(sid)
            clip = s['end'] - s['start']
            need = s['speech_s'] + s.get('lead_in_s', .3)
            if clip < need:
                add('error', sid, 'too_short', f'Slot {clip:.1f}s is shorter than the line needs ({need:.1f}s).')
            if clip > lyrics.MAX_CLIP_S:
                add('error', sid, 'over_take_limit', 'Slot is longer than one 15 s take; split the line.')
            quoted = re.findall(r'[“"]([^”"]+)[”"]', s.get('prompt', ''))
            if s.get('prompt') not in ('', 'TODO') and not any(lyrics.clean_words(q) == lyrics.clean_words(s['text']) for q in quoted):
                add('error', sid, 'quote_mismatch', 'The prompt must quote the lyric line exactly, in quotation marks.')
            if len(re.findall(r'\w+', s.get('prompt', ''))) > 140:
                add('warn', sid, 'long_prompt', 'Long prompts drift; keep the action simple and the quoted line clear.')
    for line in lines:
        n = len(said.get(line['line'], []))
        if n == 0:
            add('error', None, 'line_uncovered', f"Lyric line {line['line'] + 1} has no spoken shot.")
        elif n > 1:
            add('warn', None, 'line_repeated', f"Lyric line {line['line'] + 1} has {n} spoken shots.")
    for a, b in zip(ordered, ordered[1:]):
        if b['start'] - a['end'] > 1 / FPS:
            add('error', a.get('id'), 'gap', f"Gap of {b['start'] - a['end']:.2f}s before the next shot.")
        if a['end'] - b['start'] > 1 / FPS:
            add('error', a.get('id'), 'overlap', 'Shots overlap.')
    per_min = len(shots) / max(.1, dur) * 60
    if not TAKE_MIN_PER_MIN <= per_min <= TAKE_MAX_PER_MIN:
        add('warn', None, 'pacing', f'{per_min:.1f} shots a minute; take-based films run about {TAKE_MIN_PER_MIN}-{TAKE_MAX_PER_MIN}.')
    if ordered and ordered[0]['start'] > 1 / FPS:
        add('error', ordered[0].get('id'), 'late_start', 'The first shot must start at 0: shots are laid end to end from the first frame, so a late start shifts the whole picture against the song.')
    if ordered and dur - ordered[-1]['end'] > 1.0:
        add('warn', None, 'early_end', 'Shots end well before the song does.')
    return dict(ok=not any(f['severity'] == 'error' for f in found), shots=len(shots),
                shots_per_minute=round(per_min, 1), findings=found,
                estimate=estimate(shots, price_per_second))


def estimate(shots, price_per_second=None, takes_per_shot=2):
    """Planned seconds and, when the human's calibrated price is known, a cost ceiling (seconds x price x takes)."""
    seconds = sum(math.ceil(s['end'] - s['start']) for s in shots if s.get('generate', True))
    out = dict(planned_seconds=seconds, takes_per_shot=takes_per_shot, generated_seconds=seconds * takes_per_shot)
    if price_per_second is not None:
        out['cost_ceiling'] = round(seconds * takes_per_shot * price_per_second, 2)
    return out
