"""Offline, bounded-memory musical measurements. Never downloads models or calls providers."""
import array
import hashlib
import math
import subprocess
from pathlib import Path

VERSION = 'envelope-onsets-v1'
RATE = 8000
HOP = 160


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def envelope(ffmpeg, path, cancelled):
    # Pipe decoding avoids a whole-song PCM buffer. Every 20ms bin has a rational clock.
    process = subprocess.Popen([ffmpeg, '-nostdin', '-v', 'error', '-i', str(path),
        '-vn', '-ac', '1', '-ar', str(RATE), '-f', 's16le', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    values = []
    try:
        while True:
            if cancelled():
                raise InterruptedError()
            block = process.stdout.read(HOP * 2)
            if not block:
                break
            pcm = array.array('h', block)
            values.append(math.sqrt(sum(v*v for v in pcm) / max(1, len(pcm))) / 32768)
        if process.wait(timeout=10):
            raise ValueError('Audio decode failed.')
        return values
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def activity(values, duration):
    if not values:
        return []
    threshold = max(.003, max(values)*.08)
    runs = []
    start = None
    for i, v in enumerate([*values, 0]):
        if v >= threshold and start is None:
            start = i
        if v < threshold and start is not None:
            if i-start >= 3:
                a, b = start * HOP/RATE, min(duration, i*HOP/RATE)
                if runs and a-runs[-1][1] < .16:
                    runs[-1][1] = b
                else:
                    runs.append([a,b])
            start = None
    return runs


def alignment(master, stem):
    # Envelope correlation is diagnostic evidence, never proof of the same performance.
    # Downsample to 100ms, limit lag to +/-2s and inspect three disjoint ranges.
    a = [sum(master[i:i+5])/len(master[i:i+5]) for i in range(0,len(master),5)]
    b = [sum(stem[i:i+5])/len(stem[i:i+5]) for i in range(0,len(stem),5)]
    n = min(len(a),len(b)); findings = []
    for lo in sorted(set([0, max(0,n//2-50), max(0,n-100)])):
        hi = min(n,lo+100); scores = []
        for lag in range(-20,21):
            pairs = [(a[i],b[i+lag]) for i in range(lo,hi) if 0<=i+lag<len(b)]
            if len(pairs)<8:
                continue
            x = sum(p[0] for p in pairs)/len(pairs); y = sum(p[1] for p in pairs)/len(pairs)
            dot = sum((p[0]-x)*(p[1]-y) for p in pairs)
            norm = math.sqrt(sum((p[0]-x)**2 for p in pairs)*sum((p[1]-y)**2 for p in pairs))
            scores.append((dot/norm if norm>1e-12 else 0,lag))
        score, lag = max(scores,default=(0,0))
        findings.append(dict(start=lo/10,end=hi/10,offset_s=lag/10,correlation=round(score,4)))
    return dict(method='100ms-envelope-correlation',status='needs_review',confidence=None,
        measured_offset_s=findings[0]['offset_s'] if findings else None,
        convention='stem_time = master_time + measured_offset_s',inspected_ranges=findings,
        note='Matching duration and correlation do not establish the same take. Confirm by listening.',human_correction_s=None)


def measure(ffmpeg, master_path, stem_paths, duration, cancelled, alignment_findings=None):
    master = envelope(ffmpeg,master_path,cancelled)
    stems = {role:envelope(ffmpeg,path,cancelled) for role,path in stem_paths.items()}
    cues = []
    def cue(kind,a,b,method,text='',confidence=None):
        if b>a:
            cues.append(dict(id=hashlib.sha256(f'{kind}:{a}:{b}:{text}'.encode()).hexdigest()[:24],
                kind=kind,start=a,end=b,text=text,method=method,source='local_analysis',
                confidence=confidence,review_state='suggested',uncertainty_s=.04))
    for a,b in activity(master,duration):
        cue('music_activity',a,b,'rms-threshold')
    finding=(alignment_findings or {}).get('lead_vocal',{})
    vocal = stems.get('lead_vocal') if finding.get('status')=='verified' else None
    if vocal is not None:
        offset=finding.get('human_correction_s',0) or 0
        runs = [[max(0,a-offset),min(duration,b-offset)] for a,b in activity(vocal,len(vocal)*HOP/RATE) if b-offset>0 and a-offset<duration]
        at = 0
        for a,b in runs:
            cue('vocal_activity',a,b,'stem-rms-threshold')
            cue('phrase',a,b,'stem-activity-phrase')
            if a-at>=.25:
                cue('instrumental_gap',at,a,'stem-rms-threshold')
            at = b
        if duration-at>=.25:
            cue('instrumental_gap',at,duration,'stem-rms-threshold')
    # Local energy onsets are actual measured positions; deliberately no invented bar grid.
    previous = -100
    for i in range(2,len(master)-2):
        baseline = sum(master[max(0,i-10):i])/min(i,10)
        if master[i] > max(.008,baseline*1.8) and master[i]>=master[i-1] and master[i]>master[i+1] and i-previous>=12:
            at = i*HOP/RATE
            cue('beat',at,min(duration,at+.02),'energy-onset-candidate',confidence=.35)
            previous = i
    stride = max(1,math.ceil(len(master)/3000))
    return dict(tool_version=VERSION,waveform=dict(hop_samples=HOP*stride,sample_rate=RATE,
        values=[round(max(master[i:i+stride]),5) for i in range(0,len(master),stride)]),cues=cues[:10000],
        stem_alignment={role:alignment(master,values) for role,values in stems.items()},
        notes=['Beat candidates need review; no downbeats are inferred.',
            'Vocal activity needs an aligned, human-verified vocal stem.' if vocal is not None else 'No verified aligned vocal stem: music energy is not labeled vocal activity. Manual phrase/word timing remains available.'])
