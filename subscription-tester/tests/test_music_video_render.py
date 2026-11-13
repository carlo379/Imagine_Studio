import subprocess
import tempfile
import unittest
from pathlib import Path

import mv_fixtures as fx
from music_video import audio_io, lyric_text, render


class RenderTests(unittest.TestCase):
    def test_end_to_end_small_cut(self):
        ff = audio_io.ffmpeg_path()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            samples, _ = fx.song(seconds=6)
            fx.write_wav(d / 'song.wav', samples)
            for name, color in (('a', 'red'), ('b', 'blue')):
                subprocess.run([ff, '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={color}:s=320x240:d=4:r=24',
                                '-f', 'lavfi', '-i', 'sine=f=300:d=4', '-shortest', '-pix_fmt', 'yuv420p', str(d / f'{name}.mp4')], check=True)
            overlays = lyric_text.render_frames([dict(text='hello there friend', start=.5, end=2)], d / 'frames', 360, 640, size=36)
            self.assertEqual(len(overlays), 3)
            cmd = render.build_command(d / 'song.wav', [
                dict(clip=d / 'a.mp4', start=0, duration=3, speech=True),
                dict(clip=d / 'b.mp4', start=3, duration=3, speech=False)], d / 'out.mp4', 360, 640, overlays=overlays, song_end=6)
            render.run(cmd)
            self.assertAlmostEqual(audio_io.duration(d / 'out.mp4'), 6, delta=.3)

    def test_no_speech_cut_builds_without_ducking(self):
        cmd = render.build_command('s.wav', [dict(clip='a.mp4', start=0, duration=2)], 'o.mp4')
        self.assertNotIn('sidechaincompress', ' '.join(cmd))


if __name__ == '__main__':
    unittest.main()
