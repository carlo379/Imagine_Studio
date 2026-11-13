"""Lyric sheets for spoken delivery: lint, count, time and fit to the bar grid.

The character speaks every line (Grok Imagine Video lip-syncs speech, not singing), so a line must fit the seconds a
clip can hold and the bars it is placed on. All numbers are estimates until a take is measured (speech.py).
"""
import math
import re

WORD = re.compile(r"[A-Za-z']+")
VOWELS = re.compile(r'[aeiouy]+', re.I)
SPEECH_SYLLABLES_PER_S = 4.2          # measured conversational rate; deadpan delivery runs slower
STUDIO_WORDS_PER_S = 2.5              # Studio's own dialogue_timing rule: words / 2.5 + 1
MAX_CLIP_S = 15.0


def syllables(word):
    w = word.lower().strip("'")
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r'(?:[^laeiouy]es|ed|[^laeiouy]e)$', '', w)
    w = re.sub(r'^y', '', w)
    return max(1, len(VOWELS.findall(w)))


def parse(text):
    """Lines in order. Lines starting with `[` are section tags/notes and carry no words."""
    lines, section = [], None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith('['):
            section = stripped.strip('[]')
            continue
        words = WORD.findall(stripped)
        lines.append(dict(line=len(lines), text=stripped, section=section, words=words,
                          syllables=sum(syllables(w) for w in words)))
    return lines


def lint(text):
    """Problems that break alignment or lip-sync. Each is {line, kind, message}."""
    issues = []
    for line in parse(text):
        t = line['text']
        if re.search(r'\d', t):
            issues.append(dict(line=line['line'], kind='digits', message='Spell numbers out as spoken ("twenty-five").'))
        if re.search(r'[+=%@#$&*_~<>{}\\|]', t):
            issues.append(dict(line=line['line'], kind='symbols', message='Spell symbols out as spoken or remove them.'))
        if not line['words']:
            issues.append(dict(line=line['line'], kind='no_words', message='A lyric line needs letters.'))
        if re.search(r'\b(?:[A-Z]{2,})\b', t):
            issues.append(dict(line=line['line'], kind='acronym', message='Space capitals ("A G I") or write the word as said.'))
        if len(line['words']) > 38:
            issues.append(dict(line=line['line'], kind='too_long', message='Too long for one take; split the line.'))
    return issues


def spoken_seconds(line, pace=1.0, pause_per_comma=.18):
    """Speaking time of a line in seconds, plus the clip length Studio's rule would ask for."""
    commas = len(re.findall(r'[,;:.!?—-]', line['text']))
    speech = line['syllables'] / (SPEECH_SYLLABLES_PER_S * pace) + pause_per_comma * commas
    studio = len(line['words']) / STUDIO_WORDS_PER_S + 1
    return dict(speech_s=round(speech, 2), studio_clip_s=round(studio, 2))


def fit_to_grid(lines, bar_seconds, max_clip=MAX_CLIP_S, pace=1.0, bars_choices=(1, 2, 4)):
    """Give each line the smallest bar slot that holds it, and flag lines that cannot fit one clip.

    Returns per-line dict(bars, slot_s, speech_s, fill, verdict) where fill is speech_s / slot_s."""
    out = []
    for line in lines:
        t = spoken_seconds(line, pace)
        need = t['speech_s']
        bars = next((b for b in bars_choices if b * bar_seconds * .92 >= need), None)
        if bars is None:
            out.append(dict(line=line['line'], bars=None, slot_s=None, speech_s=need, fill=None,
                            verdict='too_long_for_four_bars: split the line or slow the beat'))
            continue
        slot = bars * bar_seconds
        fill = need / slot
        verdict = 'ok'
        if slot > max_clip:
            verdict = 'slot_longer_than_a_take: split the line'
        elif fill < .35:
            verdict = 'sparse: add words, or let the line breathe on purpose'
        elif fill > .9:
            verdict = 'tight: expect to trim; speaking pace matters'
        out.append(dict(line=line['line'], bars=bars, slot_s=round(slot, 3), speech_s=need,
                        fill=round(fill, 2), verdict=verdict))
    return out


def clean_words(text):
    return [w.lower().strip("'") for w in WORD.findall(text)]


def align_words(sheet_text, heard, tolerance=.0):
    """Place each lyric line on the clock from a timed transcript.

    `heard` is [{w, s, e}] (word, start, end seconds). Matching is a sequence alignment on normalised words, so a
    mis-heard word or a split such as "good night" does not shift the following lines. Returns per-line
    {line, start, end, matched, words}; a line with no matched word gets start/end None."""
    import difflib
    lines = parse(sheet_text)
    ref, owner = [], []
    for l in lines:
        for w in l['words']:
            ref.append(w.lower().strip("'"))
            owner.append(l['line'])
    hyp = [re.sub(r"[^a-z']", '', h['w'].lower()).strip("'") for h in heard]
    joined = ref[:]
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    spans = {l['line']: [] for l in lines}
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(a1 - a0):
                spans[owner[a0 + k]].append(b0 + k)
        elif tag == 'replace':
            # unequal blocks of similar size: accept pairwise so a one-word mishearing keeps its timing
            for k in range(min(a1 - a0, b1 - b0)):
                spans[owner[a0 + k]].append(b0 + k)
            if b1 - b0 > a1 - a0:                  # extra heard words (a split word) belong to the last sheet word's line
                spans[owner[a1 - 1]].extend(range(b0 + (a1 - a0), b1))
    out = []
    for l in lines:
        idx = sorted(spans[l['line']])
        n = len(l['words'])
        if not idx:
            out.append(dict(line=l['line'], start=None, end=None, matched=0, words=n))
            continue
        out.append(dict(line=l['line'], start=round(heard[idx[0]]['s'], 3), end=round(heard[idx[-1]]['e'], 3),
                        matched=len(idx), words=n))
    return out
