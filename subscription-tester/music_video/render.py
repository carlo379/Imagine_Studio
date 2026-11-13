"""Assemble the cut: shot clips on the song clock, the song ducked under the spoken takes, burned lyrics, loudness.

Spoken clips are slipped and trimmed, never time-stretched. Visual-only clips may be slowed slightly (triage's
best window). Each clip can carry a grade correction; the cut gets one shared grain and optional sound design. `build_command` returns the FFmpeg argv so it can be reviewed
before anything is written; `run` executes it.
"""
import subprocess

from music_video import audio_io

FPS = 24


def build_command(song, placements, out, width=1080, height=1920, ass=None, overlays=None, lufs=-14, song_end=None,
                  mode='spoken_word', vocal_stem=None, instrumental_stem=None, mute_spans=None, sound=None, grain=0, frame='fill'):
    """placements: [{clip, start, duration, in_point=0, speed=1, grade=None, speech=True|False}] sorted by start,
    covering the timeline. sound: the fragments from sound.filters. frame: 'fill' crops to the frame, 'fit' shows the
    whole picture over a blurred fill (for a 16:9 version of a vertical film)."""
    from music_video import grade as grademod
    from music_video import modes
    cfg = modes.check(mode)
    for p in placements:
        if p.get('speech') and p.get('kind', 'spoken') != 'spoken':
            raise ValueError('Only a spoken take may contribute its soundtrack; generated singing audio is never used.')
        if p.get('speed', 1) != 1 and (p.get('speech') or not .5 <= p['speed'] <= 1):
            raise ValueError('Only visual-only clips may be retimed, and only slowed (speed 0.5-1).')
    if mode == 'muted_spans' and not (vocal_stem and instrumental_stem):
        raise ValueError('Muted spans need both stems; use spoken_hooks to duck the whole song instead.')
    ff = audio_io.ffmpeg_path()
    cmd = [ff, '-y', '-nostdin', '-v', 'error', '-i', str(song)]
    parts, v_labels, speech_labels = [], [], []
    for i, p in enumerate(placements):
        cmd += ['-i', str(p['clip'])]
        src = i + 1
        d, ss, speed = p['duration'], p.get('in_point', 0), p.get('speed', 1)
        lut = grademod.lut_filter(p.get('grade'))
        head = f"[{src}:v]trim=start={ss:.3f}:duration={d * speed:.3f},setpts=(PTS-STARTPTS)/{speed},fps={FPS}{lut}"
        if frame == 'fit':
            parts.append(f"{head},split=2[bg{i}][fg{i}]")
            parts.append(f"[bg{i}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},gblur=sigma=24,eq=brightness=-0.08[bgb{i}]")
            parts.append(f"[fg{i}]scale={width}:{height}:force_original_aspect_ratio=decrease[fgs{i}]")
            parts.append(f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,trim=duration={d:.3f}[v{i}]")
        else:
            parts.append(f"{head},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,trim=duration={d:.3f}[v{i}]")
        v_labels.append(f'[v{i}]')
        if p.get('speech'):
            delay = int(round(p['start'] * 1000))
            parts.append(f"[{src}:a]atrim=start={ss:.3f}:duration={d:.3f},asetpts=PTS-STARTPTS,"
                         f"adelay={delay}|{delay},aresample=44100[t{i}]")
            speech_labels.append(f'[t{i}]')
    grain_f = grademod.grain_filter(grain)
    parts.append(''.join(v_labels) + f'concat=n={len(placements)}:v=1:a=0' + (f'[cut0];[cut0]{grain_f[1:]}[cut]' if grain_f else '[cut]'))
    last = '[cut]'
    total = song_end or max(p['start'] + p['duration'] for p in placements)
    base = len(placements) + 1
    for k, o in enumerate(overlays or []):
        cmd += ['-loop', '1', '-framerate', str(FPS), '-t', f'{total:.3f}', '-i', str(o['png'])]
        parts.append(f"{last}[{base + k}:v]overlay=0:{o['y']}:enable='between(t,{o['start']:.3f},{o['end']:.3f})':format=auto[o{k}]")
        last = f'[o{k}]'
    if ass:
        parts.append(f"{last}subtitles={_esc(ass)}[vout]")
        last = '[vout]'
    trim = f',atrim=duration={song_end:.3f}' if song_end else ''
    if mode == 'muted_spans':
        ib = base + len(overlays or [])
        cmd += ['-i', str(instrumental_stem), '-i', str(vocal_stem)]
        gain = modes.gain_expression(mute_spans or [])
        parts.append(f'[{ib}:a]aresample=44100{trim}[inst]')
        parts.append(f"[{ib + 1}:a]aresample=44100{trim},volume='{gain}':eval=frame[voc]")
        parts.append('[inst][voc]amix=inputs=2:normalize=0[song]')
        music = '[song]aresample=44100'
    else:
        music = '[0:a]aresample=44100' + trim
    sound = sound or {}
    music += sound.get('music', '')
    if speech_labels:
        parts.append(''.join(speech_labels) + f'amix=inputs={len(speech_labels)}:normalize=0:dropout_transition=0[speech]')
        parts.append(f"[speech]asplit=2[sp_key][sp_dry]")
        parts.append(f"[sp_dry]anull{sound.get('voice', '')}[sp_mix]")
        parts.append(music + f'[m0]')
        parts.append(f'[m0][sp_key]sidechaincompress=threshold=0.02:ratio={cfg["duck_ratio"]}:attack=15:release=250:makeup=1[mducked]')
        parts.append('[mducked][sp_mix]amix=inputs=2:normalize=0[mix]')
    else:
        parts.append(music + '[mix]')
    if sound.get('hum'):
        parts.append(sound['hum'])
        parts.append('[mix][hum]amix=inputs=2:normalize=0:duration=first[mixh]')
        parts.append(f'[mixh]loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]')
    else:
        parts.append(f'[mix]loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]')
    cmd += ['-filter_complex', ';'.join(parts), '-map', last, '-map', '[aout]', '-map_metadata', '-1', '-map_chapters', '-1', '-c:v', 'libx264', '-preset', 'medium',
            '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(out)]
    return cmd


def _esc(path):
    return str(path).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")


def run(cmd, timeout=3600):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise audio_io.AudioError('Render failed: ' + proc.stderr[-400:])
    return True


def vertical_from_wide(src, out, width=1080, height=1920):
    """Center-crop a landscape master to vertical (a safe default; the director may reframe)."""
    cmd = [audio_io.ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-i', str(src), '-vf',
           f'crop=ih*{width}/{height}:ih,scale={width}:{height}', '-c:a', 'copy', '-c:v', 'libx264', '-crf', '18', str(out)]
    run(cmd)
    return out
