"""Line times from the vocal stem's level, not from the transcript.

Speech recognisers place a word up to about 2 s early after a pause, which clips first words. A transcript is good for
*which* line is sung; the isolated vocal's loudness is better for *when* it starts and ends. `refine` keeps each line's
order and rough place from the aligned transcript and moves its start and end onto the stem's voiced edges.
"""
from music_video import audio_io

HOP_S = .01
RATE = 16000
BRIDGE_S = .12          # quieter dips shorter than this inside a phrase do not end it
SEARCH_EARLY_S = 2.6    # a recogniser's start can be this much too early
SEARCH_LATE_S = .6


def envelope(path):
    samples = audio_io.decode(path, rate=RATE)
    return audio_io.frame_rms(samples, int(RATE * HOP_S))


def voiced_mask(env):
    """Frames louder than a threshold set from the stem's own noise floor and peak, with short dips bridged."""
    if not env:
        return []
    ordered = sorted(env)
    floor = ordered[int(len(ordered) * .2)]
    peak = ordered[int(len(ordered) * .98)]
    thr = max(floor * 4, peak * .08, 1e-4)
    mask = [v >= thr for v in env]
    gap = int(BRIDGE_S / HOP_S)
    i = 0
    while i < len(mask):
        if not mask[i]:
            j = i
            while j < len(mask) and not mask[j]:
                j += 1
            if 0 < i and j < len(mask) and j - i <= gap:
                for k in range(i, j):
                    mask[k] = True
            i = j
        else:
            i += 1
    return mask


def refine(line_times, vocal_path=None, env=None):
    """Return line times moved onto the stem's voiced edges: [{line, start, end, source, moved_start_s, moved_end_s}]."""
    env = env if env is not None else envelope(vocal_path)
    mask = voiced_mask(env)
    n = len(mask)
    to_i = lambda t: max(0, min(n - 1, int(round(t / HOP_S))))
    ordered = sorted([t for t in line_times if t.get('start') is not None], key=lambda t: t['start'])
    out, prev_end = [], 0.0
    for k, t in enumerate(ordered):
        nxt = ordered[k + 1]['start'] if k + 1 < len(ordered) else n * HOP_S
        lo, hi = to_i(max(prev_end, t['start'] - .4)), to_i(min(t['end'], t['start'] + SEARCH_EARLY_S))
        # start: the first voiced frame at or after the transcript start (it is often early), unless the transcript
        # start is already inside a phrase, then that phrase's onset (bounded by the previous line).
        i = to_i(t['start'])
        if mask[i]:
            while i > lo and mask[i - 1]:
                i -= 1
            start_i = i
        else:
            start_i = next((j for j in range(i, max(i, hi) + 1) if mask[j]), None)
        if start_i is None:
            out.append(dict(t, source='transcript', moved_start_s=0.0, moved_end_s=0.0, note='No voice found near this line on the stem.'))
            prev_end = t['end']
            continue
        # end: extend through the voiced phrase that holds the transcript end, but never into the next line.
        e = to_i(t['end'])
        limit = to_i(min(nxt - .05, t['end'] + SEARCH_LATE_S))
        if mask[e]:
            while e < limit and mask[e + 1]:
                e += 1
        else:
            while e > start_i and not mask[e]:
                e -= 1
        start, end = start_i * HOP_S, (e + 1) * HOP_S
        if end <= start:
            end = t['end']
        out.append(dict(line=t['line'], start=round(start, 3), end=round(end, 3), source='stem',
                        moved_start_s=round(start - t['start'], 3), moved_end_s=round(end - t['end'], 3)))
        prev_end = end
    keep = {t['line'] for t in ordered}
    out += [dict(t, source='none') for t in line_times if t['line'] not in keep]
    return sorted(out, key=lambda t: t['line'])
