"""Release kit: the checks and files that decide whether people watch. Hook check on the opening seconds, thumbnail
picks, an SRT caption file and other frame shapes of the same cut. Local only.
"""
import subprocess
from pathlib import Path

from music_video import audio_io, triage

FORMATS = {'9:16': (1080, 1920, 'fill'), '16:9': (1920, 1080, 'fit'), '1:1': (1080, 1080, 'fill'), '4:5': (1080, 1350, 'fill')}
HOOK_S = 2.0


def _ts(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def srt(entries):
    """Lyric caption file from the cut's lyric entries [{text, start, end}]."""
    rows = []
    for n, e in enumerate(sorted(entries, key=lambda x: x['start']), 1):
        rows.append(f"{n}\n{_ts(e['start'])} --> {_ts(max(e['end'], e['start'] + .5))}\n{e['text'].strip()}\n")
    return '\n'.join(rows)


def hook_check(cut, shots):
    """The first seconds of the cut: is something visible, moving and changing? [{severity, kind, message}] + numbers."""
    report = triage.scan(cut)
    n = int(HOOK_S * report['fps'])
    luma = report['luma'][:n]
    motion = report['motion'][1:n]
    first_cut = next((s['start'] for s in sorted(shots, key=lambda s: s['start']) if s['start'] > .05), None)
    out = []
    mean_luma = sum(luma) / max(1, len(luma))
    mean_motion = sum(motion) / max(1, len(motion))
    if luma and min(luma[:3]) < triage.BLACK_LUMA:
        out.append(dict(severity='warn', kind='black_open', message='The cut opens on black; a scroller sees nothing in the first frames.'))
    if mean_luma < .08:
        out.append(dict(severity='warn', kind='dark_open', message='The first two seconds are very dark; brighten the opening shot or open on the lamp.'))
    if mean_motion < .004:
        out.append(dict(severity='warn', kind='static_open', message='Almost nothing moves in the first two seconds; open on movement or a closer, livelier shot.'))
    if first_cut is None or first_cut > 3.5:
        out.append(dict(severity='warn', kind='slow_first_cut', message=f"The first cut comes at {first_cut or 0:.1f}s; a cut before 3.5 s holds attention better."))
    return dict(findings=out, mean_luma=round(mean_luma, 3), mean_motion=round(mean_motion, 4),
                first_cut_s=first_cut, ok=not out)


def thumbnails(cut, out_dir, shots, count=3, spacing=2.0):
    """Pick bright, sharp, colorful frames away from cuts; write full-size JPEGs. Returns [{t, file, score}]."""
    frames, meta = triage.frames(cut, fps=2, width=96, pix='rgb24')
    w, h = meta['width'], meta['height']
    cuts = [s['start'] for s in shots]
    scored = []
    for i, f in enumerate(frames):
        t = i / meta['fps']
        if any(abs(t - c) < .35 for c in cuts):
            continue
        r, g, b = f[0::3], f[1::3], f[2::3]
        lum = [(.299 * a + .587 * bb + .114 * c) for a, bb, c in zip(r, g, b)]
        mean = sum(lum) / len(lum)
        sharp = sum(abs(lum[k] - lum[k + 1]) for k in range(len(lum) - 1) if (k + 1) % w) / len(lum)
        color = sum(max(a, bb, c) - min(a, bb, c) for a, bb, c in zip(r, g, b)) / len(lum)
        bright = 1 - abs(mean - 110) / 110
        scored.append((sharp * (.4 + bright) * (.5 + color / 128), t))
    scored.sort(reverse=True)
    picked = []
    for score, t in scored:
        if all(abs(t - p[1]) >= spacing for p in picked):
            picked.append((score, t))
        if len(picked) == count:
            break
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for k, (score, t) in enumerate(picked, 1):
        f = out_dir / f'thumb-{k}.jpg'
        proc = subprocess.run([audio_io.ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-ss', f'{t:.3f}', '-i', str(cut),
                               '-frames:v', '1', '-q:v', '2', str(f)], capture_output=True, timeout=120)
        if proc.returncode == 0 and f.is_file():
            out.append(dict(t=round(t, 2), file=f, score=round(score, 3)))
    return out


# --- flash check ------------------------------------------------------------------------------------------------------
FLASH_DELTA = .10        # a luminance swing of 10% of full range
FLASHES_PER_S = 3        # more than three flashes in any one second fails (the usual photosensitivity guideline)


def flash_check(path, fps=24):
    """Count opposing luminance swings; more than three flashes in any 1 s window is a failure. Flashes at cuts count:
    a flash is only acceptable as a single cut, never as a strobe."""
    frames, meta = triage.frames(path, fps=fps, width=32, pix='gray')
    luma = [sum(f) / len(f) / 255 for f in frames]
    swings = []
    for i in range(1, len(luma)):
        d = luma[i] - luma[i - 1]
        if abs(d) >= FLASH_DELTA:
            swings.append((i / fps, 1 if d > 0 else -1))
    flashes = [swings[k][0] for k in range(1, len(swings)) if swings[k][1] != swings[k - 1][1] and swings[k][0] - swings[k - 1][0] <= .5]
    bad, j = [], 0
    for i, t in enumerate(flashes):
        while flashes[j] < t - 1:
            j += 1
        if i - j + 1 > FLASHES_PER_S:
            bad.append(round(t, 2))
    windows = []
    for t in bad:
        if not windows or t - windows[-1][1] > 1:
            windows.append([round(max(0, t - 1), 2), t])
        else:
            windows[-1][1] = t
    return dict(ok=not windows, flashes=len(flashes), failing_windows=windows,
                message=None if not windows else 'More than three flashes in a second: remove the strobe or slow it; flashes only as cuts.')


def strip_metadata(src, out):
    """Copy a file without its global metadata and chapters (song IDs, tool tags). Streams are copied, not re-encoded."""
    proc = subprocess.run([audio_io.ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-i', str(src), '-map', '0', '-map_metadata', '-1',
                           '-map_chapters', '-1', '-c', 'copy', '-movflags', '+faststart', str(out)], capture_output=True, timeout=600)
    if proc.returncode:
        raise audio_io.AudioError('Metadata strip failed: ' + proc.stderr.decode('utf-8', 'replace')[-200:])
    return out


PUBLISH_CHECKLIST = [
    "Set the platform's AI-generated content label when you upload.",
    'Check the making-of notes and captions for personal or identifying details before posting.',
    'No generated likeness of a real person; no taboo words in titles, captions or file names.',
    'Song credits and permissions: confirm the song is yours to publish on that platform.',
]
