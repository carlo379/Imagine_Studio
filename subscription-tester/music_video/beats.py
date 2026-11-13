"""Song clock: tempo, beats, bars, downbeat phase, sections and hits.

Pure standard library. Beat times come from measured onsets; the bar grid is derived from them and the downbeat
phase is a scored guess that the director can override with `phase=`.
"""
import math
import statistics

from music_video import audio_io

HOP = 220                      # 10 ms at 22,050 Hz
FRAME = HOP / audio_io.RATE
VERSION = 'mv-beats-v1'


def band_envelopes(path):
    """Per-frame energy for the kick band, the body and the top end."""
    low = audio_io.frame_rms(audio_io.decode(path, filter_chain='lowpass=f=160,lowpass=f=160'), HOP)
    mid = audio_io.frame_rms(audio_io.decode(path, filter_chain='highpass=f=200,lowpass=f=2500'), HOP)
    high = audio_io.frame_rms(audio_io.decode(path, filter_chain='highpass=f=3000'), HOP)
    n = min(len(low), len(mid), len(high))
    return low[:n], mid[:n], high[:n]


def flux(env):
    """Positive change of log-compressed energy: an onset strength curve."""
    peak = max(env) if env else 0
    if peak <= 0:
        return [0.0] * len(env)
    comp = [math.log1p(1000 * v / peak) for v in env]
    out = [0.0]
    for i in range(1, len(comp)):
        out.append(max(0.0, comp[i] - comp[i - 1]))
    # Local mean removal keeps sustained loud passages from swamping quiet ones.
    smooth = []
    for i in range(len(out)):
        window = out[max(0, i - 30):i + 31]
        smooth.append(max(0.0, out[i] - sum(window) / len(window)))
    return smooth


def onset_curve(low, mid, high):
    a, b, c = flux(low), flux(mid), flux(high)
    return [1.0 * x + .7 * y + .4 * z for x, y, z in zip(a, b, c)], a


def estimate_period(onset, lo_bpm=70, hi_bpm=180):
    """Autocorrelation tempo with harmonic support and a gentle prior near 120 BPM.

    Returns (period_in_frames, strength)."""
    n = len(onset)
    mean = sum(onset) / n
    x = [v - mean for v in onset]
    denom = sum(v * v for v in x) or 1.0
    lo = int(60 / hi_bpm / FRAME / 2)
    hi = int(60 / lo_bpm / FRAME * 2) + 2
    scores = {}
    for lag in range(max(2, lo), min(hi, n - 2) + 1):
        scores[lag] = sum(x[i] * x[i + lag] for i in range(n - lag)) / denom
    get = lambda lag: scores.get(int(round(lag)), 0.0)
    best = None
    for lag in range(int(60 / hi_bpm / FRAME), int(60 / lo_bpm / FRAME) + 1):
        if lag not in scores:
            continue
        bpm = 60 / (lag * FRAME)
        prior = math.exp(-.5 * (math.log2(bpm / 120) / 1.0) ** 2)
        support = (scores[lag] + .5 * get(lag / 2) + .5 * get(lag * 2) + .25 * get(lag * 4)) * (.6 + .4 * prior)
        if best is None or support > best[0]:
            best = (support, lag)
    lag = best[1]
    a, b, c = scores.get(lag - 1, scores[lag]), scores[lag], scores.get(lag + 1, scores[lag])
    shift = .5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0
    return lag + max(-.5, min(.5, shift)), scores[lag]


def track(onset, period, tightness=400.0):
    """Dynamic-programming beat tracker (Ellis style)."""
    n = len(onset)
    score = [0.0] * n
    back = [-1] * n
    lo, hi = max(1, int(period * .5)), int(period * 2)
    for t in range(n):
        best, arg = 0.0, -1
        for p in range(max(0, t - hi), t - lo + 1):
            gap = (t - p) / period
            s = score[p] - tightness * math.log(gap) ** 2
            if arg < 0 or s > best:
                best, arg = s, p
        score[t] = onset[t] + (best if arg >= 0 else 0.0)
        back[t] = arg
    tail = range(max(0, n - int(period * 1.2)), n)
    t = max(tail, key=lambda i: score[i])
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    beats.reverse()
    return beats


def settle_offbeat(frames, kick, period, segment=8):
    """Hats and claps can pull the tracker half a beat off the kick, even part-way through a song.

    Each run of `segment` beats moves to the kick when the kick is clearly stronger half a beat away."""
    half = int(round(period / 2))
    n = len(kick)
    def strength(pts):
        pts = [min(n - 1, max(0, p)) for p in pts]
        return sum(max(kick[max(0, p - 2):p + 3]) for p in pts) / len(pts)
    out = []
    for i in range(0, len(frames), segment):
        chunk = frames[i:i + segment]
        base, up, down = strength(chunk), strength([f + half for f in chunk]), strength([f - half for f in chunk])
        if up > 1.25 * base and up >= down:
            chunk = [f + half for f in chunk]
        elif down > 1.25 * base:
            chunk = [f - half for f in chunk]
        out += [f for f in chunk if 0 <= f < n]
    return sorted(set(out))


def trim_weak_edges(frames, onset, floor=.25):
    """Drop leading/trailing beats the tracker invented in silence or fades."""
    if len(frames) < 4:
        return frames
    strengths = [max(onset[max(0, f - 2):f + 3]) for f in frames]
    typical = sorted(strengths)[len(strengths) // 2]
    lo, hi = 0, len(frames)
    while lo < hi and strengths[lo] < floor * typical:
        lo += 1
    while hi > lo and strengths[hi - 1] < floor * typical:
        hi -= 1
    return frames[lo:hi]


def trim_weak_edges_t(times, onset):
    frames = trim_weak_edges([int(round(t / FRAME)) for t in times], onset)
    keep = {int(round(t / FRAME)): t for t in times}
    return [keep[f] for f in frames]


def snap_to_peaks(beats, onset, radius=3):
    out = []
    for b in beats:
        window = range(max(0, b - radius), min(len(onset), b + radius + 1))
        out.append(max(window, key=lambda i: onset[i]))
    return out


def linear_fit(times):
    """Least squares t = offset + i * period. Returns (offset, period, max_abs_residual)."""
    n = len(times)
    xs = list(range(n))
    mx, my = (n - 1) / 2, sum(times) / n
    sxx = sum((x - mx) ** 2 for x in xs) or 1
    period = sum((x - mx) * (y - my) for x, y in zip(xs, times)) / sxx
    offset = my - period * mx
    resid = max(abs(offset + period * x - y) for x, y in zip(xs, times))
    return offset, period, resid


def regularize(times, tolerance=.035):
    """If most beats sit on one straight line, return that line's beats (filling gaps); else None.

    Handles a steady-tempo song whose tracker wobbled at a section change."""
    if len(times) < 8:
        return None
    gaps = sorted(b - a for a, b in zip(times, times[1:]))
    period = gaps[len(gaps) // 2]
    index = [0]
    for a, b in zip(times, times[1:]):          # cumulative: no drift from a slightly wrong period
        index.append(index[-1] + max(1, round((b - a) / period)))
    pts = list(zip(index, times))
    for _ in range(6):
        offset, per, _r = linear_fit_points(pts)
        keep = [(i, t) for i, t in pts if abs(offset + per * i - t) <= tolerance]
        if len(keep) == len(pts) or len(keep) < 8:
            break
        pts = keep
    if len(pts) < .85 * len(times):
        return None
    offset, per, resid = linear_fit_points(pts)
    if resid > tolerance:
        return None
    first, last = pts[0][0], pts[-1][0]
    return [round(offset + per * i, 3) for i in range(first, last + 1)]


def linear_fit_points(pts):
    n = len(pts)
    mx = sum(i for i, _ in pts) / n
    my = sum(t for _, t in pts) / n
    sxx = sum((i - mx) ** 2 for i, _ in pts) or 1
    per = sum((i - mx) * (t - my) for i, t in pts) / sxx
    offset = my - per * mx
    return offset, per, max(abs(offset + per * i - t) for i, t in pts)


def comb_grid(onset, period, spread=.02):
    """Best straight beat grid for a steady-tempo song: scan tempo and phase, score the onsets under every tick.

    Returns (beat_times, fraction_of_ticks_with_an_onset)."""
    n = len(onset)
    local = [max(onset[max(0, i - 1):i + 2]) for i in range(n)]
    typical = sorted(v for v in local if v > 0)[len(local) // 2 or 0] if any(local) else 1
    best = (-1, None, None)
    p = period * (1 - spread)
    while p <= period * (1 + spread):
        ph = 0.0
        while ph < p:
            total, k, t = 0.0, 0, ph
            while t < n - 1:
                total += local[int(round(t))]
                k += 1
                t += p
            score = total / max(1, k)
            if score > best[0]:
                best = (score, p, ph)
            ph += 1
        p += period * spread / 12
    _s, p, ph = best
    ticks, t = [], ph
    while t < n - 1:
        ticks.append(t)
        t += p
    hits = sum(1 for t in ticks if max(onset[max(0, int(round(t)) - 2):int(round(t)) + 3]) >= .8 * typical)
    return [round(t * FRAME, 3) for t in ticks], hits / max(1, len(ticks))


def downbeat_phase(beat_frames, low, meter=4):
    """Score each phase by how hard the kick band rises at its beats (raw energy, so loud bar-ones win)."""
    n = len(low)
    rise = []
    for f in beat_frames:
        after = max(low[f:min(n, f + 5)] or [0])
        before = min(low[max(0, f - 8):f + 1] or [0])
        rise.append(max(0.0, after - before))
    totals = [0.0] * meter
    counts = [0] * meter
    for i, r in enumerate(rise):
        totals[i % meter] += r
        counts[i % meter] += 1
    means = [totals[k] / counts[k] if counts[k] else 0 for k in range(meter)]
    order = sorted(range(meter), key=lambda k: means[k], reverse=True)
    top, second = means[order[0]], means[order[1]]
    confidence = (top - second) / top if top > 0 else 0
    return order[0], round(confidence, 3), [round(m, 4) for m in means]


def bars_from_beats(beats, phase, meter=4):
    """Bar start times: every `meter`-th beat starting at `phase`. Bars count from 0."""
    return [beats[i] for i in range(phase, len(beats), meter)]


def sections(bars, low, mid, high, total_duration, min_bars=4):
    """Guess sections from bar-level energy novelty. Boundaries fall on bar lines."""
    if len(bars) < 2 * min_bars:
        return [dict(name='A', start=0.0, end=round(total_duration, 3), bars=len(bars), guessed=True)]
    def feature(a, b):
        i, j = int(a / FRAME), max(int(a / FRAME) + 1, int(b / FRAME))
        return [sum(env[i:j]) / max(1, len(env[i:j])) for env in (low, mid, high)]
    edges = bars + [total_duration]
    feats = [feature(edges[k], edges[k + 1]) for k in range(len(bars))]
    scale = [max(f[d] for f in feats) or 1 for d in range(3)]
    feats = [[f[d] / scale[d] for d in range(3)] for f in feats]
    novelty = []
    for k in range(min_bars, len(bars) - min_bars + 1):
        before = [sum(feats[j][d] for j in range(k - min_bars, k)) / min_bars for d in range(3)]
        after = [sum(feats[j][d] for j in range(k, k + min_bars)) / min_bars for d in range(3)]
        novelty.append((sum(abs(a - b) for a, b in zip(before, after)), k))
    cuts = []
    for score, k in sorted(novelty, reverse=True):
        if score < .25:
            break
        if all(abs(k - c) >= min_bars for c in cuts):
            cuts.append(k)
    cuts = sorted(cuts)
    bounds = [0] + cuts + [len(bars)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        start = 0.0 if a == 0 else bars[a]
        end = total_duration if b == len(bars) else bars[b]
        energy = sum(sum(f) for f in feats[a:b]) / max(1, b - a)
        out.append(dict(start=round(start, 3), end=round(end, 3), bars=b - a, energy=round(energy, 3), guessed=True))
    ranked = sorted(set(round(s['energy'], 3) for s in out), reverse=True)
    for i, s in enumerate(out):
        s['name'] = 'intro' if i == 0 and s['energy'] < ranked[0] else (
            'outro' if i == len(out) - 1 and len(out) > 2 and s['energy'] < ranked[0] else (
                'drop' if s['energy'] == ranked[0] else 'verse'))
    return out


def hits(kick_flux, onset, bars_s, threshold=3.0):
    """Strong onsets that are not on the plain beat grid: impacts to cut or punch on."""
    if not onset:
        return []
    typical = statistics.median([v for v in onset if v > 0] or [1])
    out = []
    for i in range(2, len(onset) - 2):
        if onset[i] >= threshold * typical * 2 and onset[i] >= onset[i - 1] and onset[i] > onset[i + 1]:
            out.append(dict(t=round(i * FRAME, 3), strength=round(onset[i] / typical, 2),
                            kick=kick_flux[i] > .5 * onset[i]))
    return out[:400]


def analyze(path, phase=None, meter=4):
    total = audio_io.duration(path)
    low, mid, high = band_envelopes(path)
    onset, kick = onset_curve(low, mid, high)
    if sum(onset) <= 0:
        raise audio_io.AudioError('The audio is silent; nothing to analyze.')
    period, strength = estimate_period(onset)
    frames = snap_to_peaks(track(onset, period), onset)
    frames = settle_offbeat(frames, kick, period)
    frames = trim_weak_edges(frames, onset)
    beats = [round(f * FRAME, 3) for f in frames]
    grid, grid_hits = comb_grid(onset, period)
    straight = grid if grid_hits >= .9 else None
    if straight:
        beats = trim_weak_edges_t(straight, onset)
        frames = [min(len(kick) - 1, max(0, int(round(t / FRAME)))) for t in beats]
    if len(beats) < meter * 2:
        raise audio_io.AudioError('Too few beats found. Give the tempo with --bpm or check the audio.')
    offset, mean_period, resid = linear_fit(beats)
    steady = resid < .035
    bpm = 60 / mean_period
    guess, confidence, means = downbeat_phase(frames, low, meter)
    chosen = guess if phase is None else phase % meter
    bars = bars_from_beats(beats, chosen, meter)
    return dict(
        version=VERSION, duration=round(total, 3), bpm=round(bpm, 2), meter=meter,
        tempo_steady=steady, tempo_strength=round(strength, 3), grid_max_residual_s=round(resid, 4),
        beats=beats, bars=bars, downbeat_phase=chosen, downbeat_phase_guess=guess,
        downbeat_confidence=confidence, downbeat_phase_means=means,
        phase_source='director' if phase is not None else 'guess',
        sections=sections(bars, low, mid, high, total),
        hits=hits(kick, onset, bars),
        notes=['The downbeat phase is a guess scored on kick strength; confirm it by ear and override with phase.',
               'Section names are guesses from energy; confirm them before planning shots.'])


def rebar(result, phase):
    """Re-derive bars after the director sets the downbeat phase; no re-analysis needed."""
    meter = result['meter']
    result = dict(result)
    result['downbeat_phase'] = phase % meter
    result['phase_source'] = 'director'
    result['bars'] = bars_from_beats(result['beats'], result['downbeat_phase'], meter)
    return result


def snap(t, points, tolerance=None):
    """Nearest point on a grid, or t itself when none is within tolerance."""
    if not points:
        return t
    near = min(points, key=lambda p: abs(p - t))
    return near if tolerance is None or abs(near - t) <= tolerance else t
