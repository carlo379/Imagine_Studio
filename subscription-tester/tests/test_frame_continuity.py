"""Fixed-object continuity checks: held, moved and changed regions, verdicts, acceptance,
the shot kit's consistency check and the video refusal. Synthetic frames, no provider calls."""
import base64
import io
import random
import tempfile
import unittest

import studio_server as studio
import frame_continuity
from agent_api import APIError


def scene_image(box_at=(100, 60), person_at=(400, 200), lantern_at=(560, 40), size=(704, 396), seed=7):
    """A textured backdrop with a fixed 'box', a 'person' and a 'lantern' drawn at given positions."""
    from PIL import Image, ImageDraw
    rnd = random.Random(seed)
    image = Image.new('RGB', size, (40, 44, 52))
    draw = ImageDraw.Draw(image)
    for _ in range(900):  # stable texture so tiles can be matched
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        draw.rectangle((x, y, x + 6, y + 6), fill=(rnd.randrange(60, 200),) * 3)
    def textured(x, y, w, h, color, s):
        r = random.Random(s)
        draw.rectangle((x, y, x + w, y + h), fill=color)
        for _ in range(60):
            px, py = x + r.randrange(w - 6), y + r.randrange(h - 6)
            draw.rectangle((px, py, px + 5, py + 5), fill=tuple(min(255, c + 60) for c in color))
    textured(*box_at, 120, 90, (180, 60, 60), 1)
    textured(*person_at, 80, 150, (60, 160, 70), seed * 3)
    textured(*lantern_at, 50, 70, (200, 170, 50), 2)
    return image


def data_url(image):
    data = io.BytesIO()
    image.save(data, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()


BOX = [100 / 704, 60 / 396, 220 / 704, 150 / 396]
LANTERN = [560 / 704, 40 / 396, 610 / 704, 110 / 396]


class FrameContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/' + path, data or {}, None)

    def upload(self, image):
        return self.app.upload({'name': 'frame.png', 'data_url': data_url(image)})['id']

    def check(self, first, last, regions=None, **extra):
        body = dict(first={'asset_id': self.upload(first)}, last={'asset_id': self.upload(last)}, **extra)
        if regions is not None:
            body['regions'] = regions
        status, result = self.call('POST', 'image-studio/continuity', body)
        self.assertEqual(status, 201)
        return result

    def test_fixed_objects_held_while_a_person_changes_passes(self):
        result = self.check(scene_image(), scene_image(person_at=(300, 150), seed=7),
                            regions=[dict(name='box', box=BOX), dict(name='lantern', box=LANTERN)])
        self.assertEqual(result['verdict'], 'pass')
        self.assertEqual([r['status'] for r in result['regions']], ['held', 'held'])
        self.assertEqual(set(result['images']), {'map', 'overlay', 'difference'})

    def test_a_fixed_object_that_moved_fails_with_its_shift(self):
        result = self.check(scene_image(), scene_image(lantern_at=(580, 52)),
                            regions=[dict(name='box', box=BOX), dict(name='lantern', box=LANTERN)])
        self.assertEqual(result['verdict'], 'fail')
        lantern = result['regions'][1]
        self.assertIn(lantern['status'], ('moved', 'changed'))
        self.assertGreater(lantern['shift_px'], result['tolerance_px'])
        self.assertIn('lantern', ' '.join(result['reasons']))

    def test_whole_frame_shift_is_reported_as_moved_tiles(self):
        first = scene_image()
        from PIL import Image
        last = first.transform(first.size, Image.AFFINE, (1, 0, 12, 0, 1, 0))  # everything shifts 12 px: the camera moved
        result = self.check(first, last)
        self.assertEqual(result['verdict'], 'fail')
        self.assertGreater(result['counts']['moved'], 50)

    def test_regions_and_frames_are_validated(self):
        first = self.upload(scene_image())
        for body in (dict(first={'asset_id': first}),
                     dict(first={'asset_id': first}, last={'asset_id': first}, regions=[dict(name='x', box=[0.5, 0.5, 0.2, 0.9])]),
                     dict(first={'asset_id': first}, last={'asset_id': first}, regions=[dict(box=[0, 0, 1, 1])]),
                     dict(first={'asset_id': first}, last={'asset_id': first}, tolerance_percent=50)):
            with self.assertRaises(APIError):
                self.call('POST', 'image-studio/continuity', body)

    def test_accept_needs_the_humans_words_and_is_recorded(self):
        result = self.check(scene_image(), scene_image(lantern_at=(580, 52)), regions=[dict(name='lantern', box=LANTERN)])
        with self.assertRaises(APIError):
            self.call('POST', f"image-studio/continuity/{result['id']}/accept", {})
        _, accepted = self.call('POST', f"image-studio/continuity/{result['id']}/accept", {'human_words': 'Fine, the lantern swing is ok'})
        self.assertEqual(accepted['accepted']['human_words'], 'Fine, the lantern swing is ok')
        listed = self.call('GET', 'image-studio/continuity')[1]
        self.assertEqual(listed[0]['id'], result['id'])

    def test_kit_counts_a_passed_or_accepted_check_of_the_same_frames(self):
        first, last = self.upload(scene_image()), self.upload(scene_image(person_at=(300, 150)))
        _, check = self.call('POST', 'image-studio/continuity', dict(first={'asset_id': first}, last={'asset_id': last}, regions=[dict(name='box', box=BOX)]))
        scene = self.app.agent.create({'title': 'Shot', 'scene': {'prompt': 'A shot.', 'first': {'asset_id': first}, 'last': {'asset_id': last}}})
        kit = dict(expected_revision=scene['revision'], camera='Locked.', action='She jumps.', end_state='She lands.', complex_action=False)
        view = self.call('PUT', f"scenes/{scene['id']}/kit", kit)[1]
        self.assertFalse(next(c for c in view['checks'] if c['id'] == 'last_from_first')['ok'])
        view = self.call('PUT', f"scenes/{scene['id']}/kit", dict(expected_revision=view['revision'], continuity_check_id=check['id']))[1]
        self.assertTrue(next(c for c in view['checks'] if c['id'] == 'last_from_first')['ok'])
        # A check of other frames does not count.
        other = self.check(scene_image(), scene_image(), regions=[dict(name='box', box=BOX)])
        view = self.call('PUT', f"scenes/{scene['id']}/kit", dict(expected_revision=view['revision'], continuity_check_id=other['id']))[1]
        self.assertFalse(next(c for c in view['checks'] if c['id'] == 'last_from_first')['ok'])

    def test_check_images_are_refused_as_video_inputs(self):
        result = self.check(scene_image(), scene_image())
        with self.assertRaisesRegex(ValueError, 'never send them to the video model'):
            self.app.resolve({'model': 'grok-imagine-video-1.5', 'prompt': 'x', 'image': {'asset_id': result['images']['map']}})


if __name__ == '__main__':
    unittest.main()
