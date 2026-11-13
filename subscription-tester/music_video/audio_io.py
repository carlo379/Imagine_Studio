"""Decode audio with FFmpeg into plain Python sample arrays (no numpy)."""
import array
import json
import shutil
import subprocess

RATE = 22050


class AudioError(ValueError):
    pass


def ffmpeg_path():
    path = shutil.which('ffmpeg')
    if not path:
        raise AudioError('FFmpeg is required. Install it and retry.')
    return path


def duration(path):
    probe = shutil.which('ffprobe')
    if not probe:
        raise AudioError('ffprobe is required.')
    out = subprocess.run([probe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                         capture_output=True, text=True, timeout=60)
    try:
        return float(json.loads(out.stdout)['format']['duration'])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise AudioError('Could not read the audio duration.')


def decode(path, rate=RATE, filter_chain=None, start=None, length=None):
    """Mono signed 16-bit samples scaled to floats in [-1, 1]."""
    cmd = [ffmpeg_path(), '-nostdin', '-v', 'error']
    if start is not None:
        cmd += ['-ss', f'{start:.3f}']
    if length is not None:
        cmd += ['-t', f'{length:.3f}']
    cmd += ['-i', str(path), '-vn', '-ac', '1', '-ar', str(rate)]
    if filter_chain:
        cmd += ['-af', filter_chain]
    cmd += ['-f', 's16le', '-']
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode:
        raise AudioError('Audio decode failed: ' + proc.stderr.decode('utf-8', 'replace')[:200])
    pcm = array.array('h')
    pcm.frombytes(proc.stdout[:len(proc.stdout) // 2 * 2])
    return [v / 32768 for v in pcm]


def frame_rms(samples, hop):
    """RMS per non-overlapping hop."""
    out = []
    for i in range(0, len(samples) - hop + 1, hop):
        block = samples[i:i + hop]
        out.append((sum(v * v for v in block) / hop) ** .5)
    return out
