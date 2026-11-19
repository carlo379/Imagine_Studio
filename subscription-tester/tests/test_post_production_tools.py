"""Delivery check, sound tools, Resolve export, prop placement and the resize-aware image
prompt. Mock mode and files made locally with FFmpeg; no provider calls."""
import base64
import io
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import xml.dom.minidom
from pathlib import Path

import studio_server as studio
from agent_api import APIError

FFMPEG = shutil.which('ffmpeg') or ('/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').exists() else None)


def make(path, args):
    subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', *args, str(path)], check=True, capture_output=True)
    return path


def rms(path, start, length):
    raw = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-ss', str(start), '-t', str(length), '-i', str(path),
                          '-ac', '1', '-f', 's16le', '-'], capture_output=True, check=True).stdout
    samples = struct.unpack(f'<{len(raw) // 2}h', raw[:len(raw) // 2 * 2])
    return (sum(s * s for s in samples) / max(1, len(samples))) ** 0.5


@unittest.skipUnless(FFMPEG, 'FFmpeg is required')
class PostProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.app = studio.Studio(mock=True, storage=str(self.dir / 'state'))

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, path, data=None, key=None):
        return self.app.agent.dispatch(method, '/agent/v1/' + path, data or {}, key)[1]

    def video(self, name='ad.mp4', seconds=2, audio_seconds=2.07, rate=48000, bitrate='320k', volume=0.9):
        """A 1920×1080 24 fps clip whose sound runs a little long, like a Resolve AAC render."""
        return make(self.dir / name, ['-f', 'lavfi', '-i', f'testsrc2=size=1920x1080:rate=24:duration={seconds}',
                                      '-f', 'lavfi', '-i', f'anoisesrc=color=pink:sample_rate={rate}:duration={audio_seconds}:amplitude={volume}',
                                      '-ac', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', bitrate])

    def tone(self, name, seconds, frequency=440):
        return make(self.dir / name, ['-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=48000:duration={seconds}', '-ac', '2'])

    # ----- delivery check -----
    def test_delivery_check_finds_length_and_format_problems_and_fixes_only_the_sound(self):
        source = self.video()
        spec = dict(video_codec='h264', width=1920, height=1080, audio_codec='aac', sample_rate=44100, audio_bitrate_kbps=[180, 200],
                    duration_s=2.0, lufs_target=-14.0, lufs_tolerance=1.0, true_peak_max_db=-1.0)
        check = self.call('POST', 'delivery/checks', {'path': str(source), 'spec': spec})
        self.assertEqual(check['verdict'], 'fix')
        failed = {r['rule'] for r in check['checks'] if not r['ok']}
        self.assertTrue({'sound length', 'sample rate', 'audio bit rate'} <= failed, failed)
        self.assertEqual(check['info']['video']['frames'], 48)
        self.assertTrue(check['contact_sheet'])
        self.assertEqual(self.app.agent.dispatch('GET', f"/agent/v1/delivery/checks/{check['id']}/contact-sheet.jpg", {}, None)[1][1], 'image/jpeg')
        fixed = self.call('POST', f"delivery/checks/{check['id']}/fix", {})
        self.assertEqual(fixed['verdict'], 'ready', fixed['reasons'])
        self.assertEqual(fixed['fixed_from'], check['id'])
        self.assertTrue(fixed['fix']['output_path'].endswith('ad_DELIVERY.mp4'))
        self.assertEqual(fixed['info']['audio']['duration_s'], 2.0)
        self.assertEqual(fixed['info']['audio']['sample_rate'], 44100)
        # The picture is the original stream, copied.
        hashes = [subprocess.run([FFMPEG, '-loglevel', 'error', '-i', str(p), '-map', '0:v', '-c', 'copy', '-f', 'md5', '-'],
                                 capture_output=True, check=True).stdout for p in (source, Path(fixed['fix']['output_path']))]
        self.assertEqual(hashes[0], hashes[1])
        with self.assertRaises(APIError) as error:   # never overwrites
            self.call('POST', f"delivery/checks/{check['id']}/fix", {'output_path': str(source)})
        self.assertEqual(error.exception.code, 'file_exists')
        presets = self.call('GET', 'delivery/presets')
        self.assertEqual(presets['contest_30s_1080p']['duration_s'], 30.0)
        with self.assertRaises(APIError):
            self.call('POST', 'delivery/checks', {'path': 'relative.mp4', 'preset': 'x'})

    # ----- sound tools -----
    def test_voice_line_scene_defaults_to_lite_480p_with_the_lines_quoted(self):
        out = self.call('POST', 'sound/voice-lines', {'title': 'End VO', 'voice': 'a deep, warm British male narrator, normal speed, with emotion',
                                                       'lines': [{'text': 'Same moment.', 'at_s': 1}, {'text': 'Everywhere.'}, {'text': 'Your brand.'}]})
        scene = out['scene']['scene']
        self.assertEqual((scene['model'], scene['resolution'], scene['audio']), ('grok-imagine-video-1.5-lite', '480p', True))
        self.assertIn('"Same moment."', scene['prompt'])
        self.assertIn('No music', scene['prompt'])
        self.assertIn('Pitch words', out['voice_guide'])
        self.assertEqual(self.call('GET', 'sound/voice-lines')[0]['scene_id'], out['scene']['id'])

    def test_stems_place_through_devices_and_music_fits_the_hit(self):
        self.app.sound.transcriber = lambda path, prompt: [dict(w='hello', s=0.1, e=0.5)]
        voice = self.call('POST', 'sound/stems', {'path': str(self.tone('voice.wav', 6)), 'name': 'Announcer'})
        self.assertEqual(voice['words'][0]['w'], 'hello')
        self.assertAlmostEqual(voice['duration_s'], 6, delta=0.05)
        placed = self.call('POST', 'sound/place', {'name': 'Broadcast', 'length_s': 10, 'pieces': [
            {'stem_id': voice['id'], 'from_s': 0, 'to_s': 2, 'at_s': 1, 'device': 'radio'},
            {'stem_id': voice['id'], 'from_s': 2, 'to_s': 3, 'at_s': 5, 'stretch_to_s': 1.5, 'device': 'tv', 'gain_db': -6}]})
        self.assertAlmostEqual(placed['duration_s'], 10, delta=0.02)
        path = self.app.sound.stem_file(placed['id'])
        self.assertLess(rms(path, 0, 0.9), 5)            # silence before the first piece
        self.assertGreater(rms(path, 1.2, 1.5), 500)      # the radio piece
        self.assertLess(rms(path, 3.2, 1.5), 5)           # the gap
        self.assertGreater(rms(path, 5.1, 1.2), 100)      # the stretched TV piece
        with self.assertRaises(APIError):
            self.call('POST', 'sound/place', {'name': 'x', 'length_s': 5, 'pieces': [{'stem_id': voice['id'], 'device': 'megaphone'}]})
        song = self.call('POST', 'sound/stems', {'path': str(self.tone('song.wav', 20, 220)), 'name': 'Song', 'words': False})
        fit = self.call('POST', 'sound/music-fit', {'stem_id': song['id'], 'hit_s': 15.5, 'length_s': 30, 'song_event_s': 16.93})
        self.assertEqual(fit['options'][0]['offset_s'], -1.43)
        music = self.call('POST', 'sound/music', {'stem_id': song['id'], 'name': 'Music', 'offset_s': -1.43, 'length_s': 18,
                                                   'keyframes': [{'at_s': 0, 'db': -20}, {'at_s': 13, 'db': -20}, {'at_s': 15.5, 'db': 0}]})
        self.assertAlmostEqual(music['duration_s'], 18, delta=0.02)
        mpath = self.app.sound.stem_file(music['id'])
        quiet, loud = rms(mpath, 2, 2), rms(mpath, 16, 1)
        self.assertAlmostEqual(20 * __import__('math').log10(loud / quiet), 20, delta=1.0)
        self.assertEqual(self.app.agent.dispatch('GET', f"/agent/v1/sound/stems/{music['id']}/audio.wav", {}, None)[1][1], 'audio/wav')

    # ----- Resolve export -----
    def test_fcpxml_puts_clips_in_order_and_stems_on_named_lanes(self):
        a, b = self.video('a.mp4', 2, 2), self.video('b.mp4', 3, 3)
        stem = self.call('POST', 'sound/stems', {'path': str(self.tone('music.wav', 5)), 'name': 'Music', 'words': False})
        out = self.call('POST', 'resolve/exports', {'title': 'Test cut', 'video': [{'path': str(a)}, {'path': str(b), 'in_s': 1, 'duration_s': 2}],
                                                     'audio': [{'stem_id': stem['id'], 'track': 'Music'},
                                                               {'path': str(self.tone('vo.wav', 1)), 'track': 'End VO', 'at_s': 3.5}]})
        self.assertEqual((out['frames'], out['clips'], out['stems']), (120, 2, 2))
        self.assertEqual([t['track'] for t in out['tracks']], ['Music', 'End VO'])
        doc = xml.dom.minidom.parse(out['fcpxml'])
        clips = doc.getElementsByTagName('asset-clip')
        spine = [c for c in clips if not c.getAttribute('lane')]
        self.assertEqual([(c.getAttribute('offset'), c.getAttribute('start'), c.getAttribute('duration')) for c in spine],
                         [('0s', '0s', '48/24s'), ('48/24s', '24/24s', '48/24s')])
        vo = next(c for c in clips if c.getAttribute('lane') == '-2')
        self.assertEqual(vo.parentNode.getAttribute('offset'), '48/24s')   # connected to the clip under 3.5 s
        self.assertEqual(vo.getAttribute('offset'), '60/24s')             # parent start 24 + (84 - 48)
        lua = Path(out['lua']).read_text()
        self.assertIn('"End VO"', lua)
        self.assertIn('DuplicateTimeline', lua)
        self.assertIn(b'fcpxml', self.app.agent.dispatch('GET', f"/agent/v1/resolve/exports/{out['id']}/timeline.fcpxml", {}, None)[1][0])

    # ----- prop placement and resize-aware prompts -----
    def png(self, color):
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGB', (64, 36), color).save(data, 'PNG')
        return self.app.upload({'name': 'still.png', 'data_url': 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()})['id']

    def test_prop_placement_runs_the_two_image_steps(self):
        body = {'title': 'Shot 3 dish', 'base': {'asset_id': self.png((90, 60, 40))}, 'reference': {'asset_id': self.png((200, 200, 200))},
                'target': 'the wrong dish on the barn roof', 'product': 'satellite dish'}
        with self.assertRaises(APIError) as error:
            self.call('POST', 'image-studio/prop-placement', body)
        self.assertEqual(error.exception.code, 'approval_required')
        self.app.begin('login')
        for _ in range(50):
            if self.app.state.get('signed_in'):break
            time.sleep(.05)
        run = self.call('POST', 'image-studio/prop-placement', {**body, 'approved': True})
        self.assertIn('second image', run['steps'][0]['prompt'])
        for _ in range(100):
            run = self.call('POST', f"image-studio/prop-placement/{run['id']}/advance")
            if run['status'] == 'done' or run['status'].endswith('failed'):break
            time.sleep(.1)
        self.assertEqual(run['status'], 'done', run)
        self.assertEqual([s['kind'] for s in run['steps']], ['gpt_placement', 'grok_reproduce'])
        self.assertIn('Change nothing', run['steps'][1]['prompt'])
        self.assertEqual(run['result']['asset_id'], run['steps'][1]['output'])

    def test_a_resize_request_drops_the_preserve_proportions_line(self):
        images = self.app.images
        def prompt(text):
            draft = images.dispatch('POST', ['drafts'], {'title': 'x', 'settings': {'model': 'grok-imagine-image-2.0', 'prompt': text,
                                                         'ratio': '16:9', 'extras': [{'asset_id': self.png((1, 2, 3))}]}, 'named_references': []}, None)[1]
            return images.expanded_prompt(draft['settings'])[0]
        self.assertIn('proportions', prompt('Keep the dish where it is.'))
        resized = prompt('Make the dish 20% smaller.')
        self.assertNotIn('proportions', resized)
        self.assertIn('change their size only as the scene instructions ask', resized)


if __name__ == '__main__':
    unittest.main()
