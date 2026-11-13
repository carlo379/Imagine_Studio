"""Measure a generated take's speech and place it on the song clock.

A take's own soundtrack is the vocal (the video model speaks the quoted line), so sync is *within* the take.
What the director controls is where that take sits against the beat: slip it, never stretch it.
"""
import math
import re

from music_video import audio_io, lyrics

HOP = 220
FRAME = HOP / audio_io.RATE


def activity(path):
    """Speech-like activity runs from the take's audio: [(start, end)], plus its envelope."""
    env = audio_io.frame_rms(audio_io.decode(path), HOP)
    if not env:
        return [], env
    peak = sorted(env)[int(.95 * (len(env) - 1))] or 1e-9
    gate = max(peak * .12, 1e-4)
    runs, start, gap = [], None, 0
    for i, v in enumerate(env):
        if v >= gate:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 12:                       # 120 ms of silence closes a run
                runs.append((start * FRAME, (i - gap + 1) * FRAME))
                start, gap = None, 0
    if start is not None:
        runs.append((start * FRAME, (len(env) - gap) * FRAME))
    return [(a, b) for a, b in runs if b - a >= .08], env


def syllable_onsets(env):
    """Local energy peaks in the speech band envelope: a rough syllable-nucleus count and their times."""
    smooth = [sum(env[max(0, i - 2):i + 3]) / len(env[max(0, i - 2):i + 3]) for i in range(len(env))]
    peak = max(smooth) or 1e-9
    out, last = [], -100
    for i in range(2, len(smooth) - 2):
        if smooth[i] > .18 * peak and smooth[i] >= smooth[i - 1] and smooth[i] > smooth[i + 1] \
                and smooth[i] > 1.12 * min(smooth[max(0, i - 8):i + 1]) and i - last >= 8:
            out.append(round(i * FRAME, 3))
            last = i
    return out


def measure(path):
    runs, env = activity(path)
    onsets = syllable_onsets(env)
    if not runs:
        return dict(speech=False, runs=[], note='No speech-like audio found in this take.')
    start, end = runs[0][0], runs[-1][1]
    voiced = sum(b - a for a, b in runs)
    return dict(speech=True, runs=[[round(a, 3), round(b, 3)] for a, b in runs],
                first_speech_s=round(start, 3), last_speech_s=round(end, 3), voiced_s=round(voiced, 3),
                syllable_onsets=onsets, syllables_heard=len(onsets),
                syllables_per_s=round(len(onsets) / max(.1, end - start), 2),
                take_duration_s=round(audio_io.duration(path), 3))


def compare_words(sheet_text, heard_words):
    """Word error rate of a transcript against the sheet (Levenshtein over words). `heard_words` is a list of str."""
    ref = lyrics.clean_words(sheet_text)
    hyp = [h for h in (re.sub(r"[^a-z']", '', w.lower()).strip("'") for w in heard_words) if h]
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    errors = d[len(hyp)]
    missing = [w for w in ref if w not in hyp]
    return dict(wer=round(errors / max(1, len(ref)), 3), errors=errors, words=len(ref),
                missing=missing[:20], verdict='match' if errors / max(1, len(ref)) <= .1 else 'mismatch')


SKIP_S = 2 / 24          # never show a take's first two frames: the first is the sharper input still and pops


def place_on_beat(take, beats, target_start, max_slip=.35, anchor='first_speech', trim_only=False, min_in_point=0.0):
    """Where to start the take on the song so its first spoken syllable lands on a beat.

    `target_start` is the slot start (a bar line, seconds). Returns the timeline start, the slip applied
    (positive = the take would have to start later than the slot) and whether it is usable. Never stretches.

    With `trim_only` the clip is only ever started *earlier* (its first `in_point` seconds are cut, picture and sound
    together, so lip-sync is untouched); a later start would need footage that does not exist. `min_in_point` always
    trims at least that much. The syllable lands within 0.1 s of a beat or the take is not ok; `beat_error_s` says by
    how much (negative = early)."""
    if not take.get('speech'):
        return dict(ok=False, reason='no_speech')
    onset = take['first_speech_s'] if anchor == 'first_speech' else (take['syllable_onsets'] or [take['first_speech_s']])[0]
    near = [b for b in beats if abs(b - (target_start + onset)) < 2]
    if trim_only:
        # The trim i can range from min_in_point to just before the first syllable; the syllable then lands at
        # target_start + onset - i. Choose the beat it can land closest to (exactly, if the trim allows).
        lo, hi = min_in_point, max(min_in_point, onset - .04)
        best = None
        for b in near:
            i = min(hi, max(lo, target_start + onset - b))
            err = (target_start + onset - i) - b
            if best is None or (abs(err), i) < (abs(best[2]), best[1]):
                best = (b, i, err)
        if best is None:
            return dict(ok=False, reason='no_beat_near_slot')
        wanted, in_point, beat_error = best
        ok = abs(beat_error) <= .1
        return dict(ok=ok, timeline_start_s=round(target_start - in_point, 3), slip_s=round(-in_point, 3), in_point_s=round(in_point, 3),
                    lands_on_beat_s=round(wanted, 3), beat_error_s=round(beat_error, 3),
                    reason=None if ok else 'speech_misses_the_beat_retake_or_cover')
    wanted = min(near, key=lambda b: abs(b - (target_start + onset)), default=None)
    if wanted is None:
        return dict(ok=False, reason='no_beat_near_slot')
    start = wanted - onset
    slip = start - target_start
    ok = abs(slip) <= max_slip
    return dict(ok=ok, timeline_start_s=round(start, 3), slip_s=round(slip, 3), in_point_s=round(max(0.0, -slip), 3),
                lands_on_beat_s=round(wanted, 3), beat_error_s=0.0, reason=None if ok else 'slip_too_large_retake_or_cover')


def pace_check(take, expected_speech_s, tolerance=.25):
    """Does the take's speech fill the slot the line was fitted to? Over-long speech cannot be stretched."""
    if not take.get('speech'):
        return dict(ok=False, reason='no_speech')
    actual = take['last_speech_s'] - take['first_speech_s']
    ratio = actual / max(.1, expected_speech_s)
    return dict(ok=abs(ratio - 1) <= tolerance, actual_s=round(actual, 2), expected_s=round(expected_speech_s, 2),
                ratio=round(ratio, 2),
                advice=None if abs(ratio - 1) <= tolerance else
                ('Speech runs long: shorten the line or give it more bars.' if ratio > 1 else
                 'Speech runs short: pad the slot with a gesture or hold, or add a word.'))
