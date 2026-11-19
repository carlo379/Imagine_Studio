"""Prop models: mesh validation, exact camera placement, renders saved as image assets that
Studio refuses as video inputs. Engines are faked except one real VTK render when installed."""
import base64
import importlib.util
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import studio_server as studio
import prop_models
from agent_api import APIError


def cube_stl(size=100.0):
    """Binary STL of an axis-aligned box from 0 to size on every axis (12 triangles)."""
    s = size
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
             (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    out = bytearray(b'\0' * 80) + struct.pack('<I', len(faces))
    for a, b, c in faces:
        out += struct.pack('<12fH', 0, 0, 0, *v[a], *v[b], *v[c], 0)
    return bytes(out)


def png(width, height, color=(255, 255, 255, 255)):
    from PIL import Image
    data = io.BytesIO()
    Image.new('RGBA', (width, height), color).save(data, 'PNG')
    return data.getvalue()


class PropModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, path, data=None):
        return self.app.agent.dispatch(method, '/agent/v1/' + path, data or {}, None)

    def upload_cube(self, **extra):
        status, model = self.call('POST', 'prop-models', dict(name='Box', format='stl', units='mm',
                                  data_base64=base64.b64encode(cube_stl()).decode(), **extra))
        self.assertEqual(status, 201)
        return model

    def test_upload_reads_true_size_and_lists(self):
        model = self.upload_cube()
        self.assertEqual(model['size_m'], [0.1, 0.1, 0.1])
        self.assertEqual(model['bounds'], [0, 100, 0, 100, 0, 100])
        self.assertEqual(self.call('GET', 'prop-models')[1][0]['id'], model['id'])
        self.assertEqual(self.call('GET', 'prop-models/' + model['id'])[1]['name'], 'Box')

    def test_rejects_unreadable_meshes_and_bad_fields(self):
        for body in (dict(name='X', format='stl', data_base64=base64.b64encode(b'not a mesh').decode()),
                     dict(name='X', format='obj', data_base64=base64.b64encode(b'v 0 0 0\n').decode()),
                     dict(name='X', format='glb', data_base64='AAAA'),
                     dict(name='', format='stl', data_base64='AAAA'),
                     dict(name='X', format='stl', units='feet', data_base64='AAAA')):
            with self.assertRaises(APIError):
                self.call('POST', 'prop-models', body)

    def test_ascii_stl_and_obj_are_read(self):
        ascii_stl = b'solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 3 0\nendloop\nendfacet\nendsolid t\n'
        self.assertEqual(prop_models.bounds(prop_models.mesh_points(ascii_stl, 'stl')), [0, 2, 0, 3, 0, 0])
        obj = b'v 0 0 0\nv 1 0 0\nv 0 1 4\nf 1 2 3\n'
        self.assertEqual(prop_models.bounds(prop_models.mesh_points(obj, 'obj')), [0, 1, 0, 1, 0, 4])

    def test_model_center_lands_where_asked_at_true_size(self):
        model = self.upload_cube()
        matrix, cam, pose, size = prop_models.placement(model, dict(width=2000, height=1000, hfov_deg=60,
                                                                     frame_x=0.8, frame_y=0.3, distance_m=3))
        x, y = prop_models.project(matrix, cam, (50, 50, 50))
        self.assertAlmostEqual(x, 1600, places=3)
        self.assertAlmostEqual(y, 300, places=3)
        self.assertEqual(size, [0.1, 0.1, 0.1])
        # A 0.1 m box seen face-on at 3 m spans focal_px * 0.1 / 3 pixels at its center depth.
        flat, cam, _, _ = prop_models.placement(model, dict(width=2000, height=1000, hfov_deg=60, distance_m=3))
        left, _ = prop_models.project(flat, cam, (0, 50, 50))
        right, _ = prop_models.project(flat, cam, (100, 50, 50))
        self.assertAlmostEqual(right - left, cam['focal_px'] * 0.1 / 3, places=3)

    def test_lens_and_rotations_are_validated(self):
        model = self.upload_cube()
        self.assertAlmostEqual(prop_models.camera(dict(lens_mm=18))['hfov_deg'], 90, places=6)
        for bad in (dict(frame_x='left'), dict(distance_m=0), dict(width=10), dict(yaw_deg=float('nan')), dict(up_axis='x')):
            with self.assertRaises(APIError):
                prop_models.placement(model, bad)

    def test_render_saves_marked_asset_and_composites_over_a_guide(self):
        model = self.upload_cube()
        guide = self.app.upload({'name': 'draft', 'data_url': 'data:image/png;base64,' + base64.b64encode(png(320, 180, (10, 20, 30, 255))).decode()})
        seen = {}
        def fake(engine, job, directory):
            seen.update(engine=engine, job=job)
            return png(job['width'], job['height'], (0, 0, 0, 0))
        with patch('prop_models.run_engine', side_effect=fake):
            status, asset = self.call('POST', f"prop-models/{model['id']}/render",
                                      dict(engine='blender', width=320, height=180, frame_x=0.5, frame_y=0.5,
                                           distance_m=1, background={'asset_id': guide['id']}))
        self.assertEqual(status, 201)
        self.assertEqual(seen['engine'], 'blender')
        self.assertEqual(asset['kind'], 'prop_model_render')
        self.assertEqual(asset['model_id'], model['id'])
        self.assertIn('never send them to the video model', asset['video_policy'])
        _, path = self.app.asset(asset['id'])
        from PIL import Image
        self.assertEqual(Image.open(path).convert('RGBA').getpixel((5, 5)), (10, 20, 30, 255))

    def test_guide_with_another_aspect_is_refused(self):
        model = self.upload_cube()
        guide = self.app.upload({'name': 'square', 'data_url': 'data:image/png;base64,' + base64.b64encode(png(200, 200)).decode()})
        with patch('prop_models.run_engine', side_effect=lambda e, j, d: png(j['width'], j['height'], (0, 0, 0, 0))):
            with self.assertRaises(APIError):
                self.call('POST', f"prop-models/{model['id']}/render", dict(width=320, height=180, background={'asset_id': guide['id']}))

    def test_video_refuses_prop_renders(self):
        model = self.upload_cube()
        with patch('prop_models.run_engine', side_effect=lambda e, j, d: png(j['width'], j['height'])):
            _, asset = self.call('POST', f"prop-models/{model['id']}/render", dict(width=128, height=72))
        with self.assertRaisesRegex(ValueError, 'never send them to the video model'):
            self.app.resolve({'model': 'grok-imagine-video-1.5', 'prompt': 'x', 'image': {'asset_id': asset['id']}})

    def test_missing_engine_is_a_clear_503(self):
        model = self.upload_cube()
        with patch('prop_models.blender_path', return_value=None):
            with self.assertRaises(APIError) as caught:
                self.call('POST', f"prop-models/{model['id']}/render", dict(engine='blender', width=128, height=72))
        self.assertEqual(caught.exception.status, 503)
        self.assertIn('engines', self.call('GET', 'prop-models/schema')[1])

    def test_light_and_ground_shadow_are_validated_and_passed_to_blender(self):
        model = self.upload_cube()
        seen = {}
        def fake(engine, job, directory):
            seen.update(job)
            return png(job['width'], job['height'], (0, 0, 0, 0))
        light = dict(key_color=[1, 0.8, 0.6], ambient_color=[0.5, 0.4, 0.7], key_strength=1.2, exposure=-0.8)
        with patch('prop_models.run_engine', side_effect=fake):
            _, asset = self.call('POST', f"prop-models/{model['id']}/render", dict(engine='blender', width=128, height=72, light=light, ground_shadow=True))
        self.assertEqual(seen['light'], light)
        self.assertTrue(seen['ground_shadow'])
        self.assertEqual(seen['up_vector'], [0, 0, 1])
        self.assertTrue(asset['ground_shadow'])
        for bad in (dict(engine='vtk', ground_shadow=True), dict(engine='blender', light=dict(glow=1)),
                    dict(engine='blender', light=dict(key_color=[2, 0, 0])), dict(engine='blender', ground_shadow='yes')):
            with self.assertRaises(APIError):
                self.call('POST', f"prop-models/{model['id']}/render", dict(width=128, height=72, **bad))

    @unittest.skipUnless(importlib.util.find_spec('vtk'), 'VTK not installed')
    def test_real_vtk_render_draws_the_box_where_placed(self):
        model = self.upload_cube()
        _, asset = self.call('POST', f"prop-models/{model['id']}/render",
                             dict(engine='vtk', width=320, height=180, frame_x=0.25, frame_y=0.5, distance_m=1, yaw_deg=30, pitch_deg=20))
        _, path = self.app.asset(asset['id'])
        from PIL import Image
        image = Image.open(path).convert('RGBA')
        self.assertGreater(image.getpixel((80, 90))[3], 0)
        self.assertEqual(image.getpixel((300, 20))[3], 0)


if __name__ == '__main__':
    unittest.main()
