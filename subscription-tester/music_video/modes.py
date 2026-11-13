"""How speech relates to the song: three delivery modes, chosen per project.

spoken_word   Instrumental track; she speaks every lyric line. The song never has a competing vocal.
spoken_hooks  Full song with its own vocal; she speaks only the chosen key lines. Every other line is carried by
              the song's real vocal over visual-only shots.
muted_spans   Full song, but the song's vocal is muted under each spoken line (needs the vocal and instrumental
              stems) so she never talks over the singer.

Hard rule in every mode: audio Grok generates while *simulating singing* is never used. Only a take that was asked
to speak a line (kind `spoken`) may contribute its soundtrack, and only as speech. Every other shot is visual-only.
"""
import re

MODES = {
    'spoken_word': dict(
        title='Spoken-word song',
        summary='Instrumental track; the character speaks every lyric line.',
        needs=['an instrumental (or beat-only) track'],
        default_spoken='all', duck_ratio=6, song_vocal='absent'),
    'spoken_hooks': dict(
        title='Spoken hooks',
        summary='Full song; she speaks only the key lines, everything else is visual-only over the real vocal.',
        needs=['the full song with its vocal', 'a choice of key lines (hook/chorus sections by default)'],
        default_spoken='hooks', duck_ratio=14, song_vocal='plays'),
    'muted_spans': dict(
        title='Muted spans',
        summary='Full song; the sung vocal is muted under her spoken lines so the two never collide.',
        needs=['the vocal stem and the instrumental stem', 'a choice of spoken lines (hook/chorus by default)'],
        default_spoken='hooks', duck_ratio=3, song_vocal='muted_under_speech'),
}
HOOK_SECTIONS = re.compile(r'hook|chorus|refrain|drop|bridge', re.I)
SINGING_WORDS = re.compile(r'(?<!no )(?<!not )(?<!never )\b(sing|sings|singing|sang|sung|lip[- ]?sync\w*|says|saying|speaks|speaking|talks|talking|mouths|mouthing)\b', re.I)
NON_SPEECH_KINDS = ('sung_cut', 'cutaway', 'dance', 'title')


def check(mode):
    if mode not in MODES:
        raise ValueError('Choose a mode: ' + ', '.join(MODES))
    return MODES[mode]


def delivery(mode, lines, spoken_lines=None):
    """Per lyric line: 'spoken' (she speaks it on camera) or 'song' (the song's own vocal carries it)."""
    cfg = check(mode)
    if spoken_lines is not None:
        chosen = set(spoken_lines)
    elif cfg['default_spoken'] == 'all':
        chosen = {l['line'] for l in lines}
    else:
        chosen = {l['line'] for l in lines if l.get('section') and HOOK_SECTIONS.search(l['section'])}
    if mode == 'spoken_word':
        chosen = {l['line'] for l in lines}     # a spoken-word song has no other voice to carry a line
    return {l['line']: ('spoken' if l['line'] in chosen else 'song') for l in lines}


def requirements(mode, options=None):
    """Findings about what the mode needs. options: song_has_vocals, vocal_stem, instrumental_stem."""
    options = options or {}
    cfg = check(mode)
    out = []
    def add(sev, kind, msg):
        out.append(dict(severity=sev, kind=kind, message=msg))
    if mode == 'spoken_word' and options.get('song_has_vocals'):
        add('error', 'song_has_vocals', 'Spoken-word mode needs an instrumental; this song has a vocal that would collide with her speech. '
            'Use an instrumental, or switch to muted_spans (needs stems) or spoken_hooks.')
    if mode == 'spoken_word' and options.get('song_has_vocals') is None:
        add('warn', 'vocal_unknown', 'Confirm the track is instrumental by ear before spending on takes.')
    if mode == 'muted_spans':
        for key, what in (('vocal_stem', 'vocal'), ('instrumental_stem', 'instrumental')):
            if not options.get(key):
                add('error', f'missing_{what}_stem', f'Muted spans need the {what} stem. Without stems the vocal cannot be muted alone; '
                    'use spoken_hooks (ducks the whole song) instead.')
    if mode == 'spoken_hooks':
        add('info', 'song_ducks', 'The whole song (vocal included) is ducked hard under each spoken hook. Place hooks where the vocal rests when you can.')
    return out


def mute_spans(spans, pad=.1):
    """Windows [a, b] (song seconds) where the sung vocal must be silent: each spoken line's measured speech plus pad."""
    out = []
    for a, b in sorted(spans):
        a, b = max(0.0, a - pad), b + pad
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([round(a, 3), round(b, 3)])
    return out


def speech_spans(shots, placements=None):
    """Where speech lands on the song clock. Measured placements win; otherwise the shot slot's speech estimate."""
    measured = {p['shot']: p for p in (placements or []) if p.get('shot') and p.get('speech_start') is not None}
    spans = []
    for s in shots:
        if s['kind'] != 'spoken':
            continue
        p = measured.get(s.get('id'))
        if p:
            spans.append((p['speech_start'], p['speech_end']))
        else:
            a = s['start'] + s.get('lead_in_s', .3)
            spans.append((a, min(s['end'], a + s['speech_s'])))
    return spans


def gain_expression(spans, fade=.08):
    """FFmpeg `volume` expression: 1 normally, 0 inside each span, with `fade`-second ramps."""
    if not spans:
        return '1'
    terms = [f'(1-clip(min((t-{a - fade:.3f})/{fade},({b + fade:.3f}-t)/{fade}),0,1))' for a, b in spans]
    return '*'.join(terms)
