"""Synthetic songs and speech-like audio for the music-video tests (standard library only)."""
import math
import random
import struct
import wave

RATE = 22050


def write_wav(path, samples, rate=RATE):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b''.join(struct.pack('<h', max(-32767, min(32767, int(v * 32767)))) for v in samples))


def song(seconds=32, bpm=124, first=0.5, drop_bar=4, seed=3):
    """Kick on every beat (louder on the downbeat), hats on the offbeats, a bass pad after the drop."""
    rng = random.Random(seed)
    n = int(seconds * RATE)
    out = [0.0] * n
    period = 60 / bpm
    beat = 0
    t = first
    truth = []
    while t < seconds - .3:
        truth.append(t)
        down = beat % 4 == 0
        start = int(t * RATE)
        for i in range(int(.18 * RATE)):
            if start + i < n:
                out[start + i] += (.9 if down else .55) * math.sin(2 * math.pi * (110 - 400 * i / RATE if False else 55 + 45 * math.exp(-i / 900)) * i / RATE) * math.exp(-i / 1800)
        h = int((t + period / 2) * RATE)
        for i in range(int(.04 * RATE)):
            if h + i < n:
                out[h + i] += .25 * (rng.random() * 2 - 1) * math.exp(-i / 200)
        if beat >= drop_bar * 4:
            for i in range(int(period * RATE)):
                if start + i < n:
                    out[start + i] += .18 * math.sin(2 * math.pi * 82 * (start + i) / RATE)
        beat += 1
        t += period
    return out, truth
