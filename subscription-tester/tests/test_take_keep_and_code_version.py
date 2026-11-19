"""Keeping an earlier take, the server's code-version report, the continuity size test and
the lock-fixed-objects tool. Mock mode and synthetic frames only; no provider calls."""
import tempfile
import time
import unittest
import warnings
from unittest.mock import patch

import code_version
import studio_server as studio
from agent_api import APIError
from agent_client import StudioClient, StaleServerWarning
import test_production_plans as plan_fixture
from test_frame_continuity import scene_image, data_url, BOX

WORDS = 'Yes, go ahead with this take.'


class KeepEarlierTakeTests(unittest.TestCase):
    setUp = plan_fixture.PlanTests.setUp
    tearDown = plan_fixture.PlanTests.tearDown
    call = plan_fixture.PlanTests.call
    scene = plan_fixture.PlanTests.scene
    kit = plan_fixture.PlanTests.kit
    fresh = plan_fixture.PlanTests.fresh
    plan = plan_fixture.PlanTests.plan

    def take(self, scene, key, **extra):
        scene = self.fresh(scene)
        job = self.call('POST', f"scenes/{scene['id']}/generate", {'expected_revision': scene['revision'], 'approved': True, 'human_words': WORDS, **extra}, key)
        for _ in range(50):
            job = self.call('GET', 'jobs/' + job['id'])
            if job['status'] != 'pending':return job
            time.sleep(.1)
        self.fail('mock generation did not finish')

    def test_keep_an_earlier_take_from_the_latest_verdict(self):
        a = self.scene('waves.');plan = self.plan(a)
        first = self.take(a, 'keep-earlier-1', plan_id=plan['id'])
        second = self.take(a, 'keep-earlier-2', plan_id=plan['id'], verdict={'job_id': first['id'], 'verdict': 'retry', 'notes': 'Hat vanishes.'})
        with self.assertRaises(ValueError):
            self.call('POST', f"jobs/{second['id']}/human-review", {'verdict': 'keep', 'keep_job_id': first['id'], 'human_words': "let's keep the first one"})
        self.call('POST', f"jobs/{second['id']}/human-review", {'verdict': 'reject', 'keep_job_id': first['id'], 'human_words': "let's keep the first one"})
        kept = self.call('GET', 'jobs/' + first['id'])['human_review']
        self.assertEqual(kept['verdict'], 'keep')
        self.assertEqual(kept['kept_later']['previous_verdict'], 'retry')
        self.assertEqual(kept['kept_later']['human_words'], "let's keep the first one")
        self.assertEqual(kept['history'][0]['verdict'], 'retry')
        self.assertEqual(self.call('GET', 'jobs/' + second['id'])['human_review']['kept_instead'], first['id'])
        self.assertEqual(self.call('GET', 'plans/' + plan['id'])['items'][0]['state'], 'kept')

    def test_keep_after_the_fact_and_refusals(self):
        a = self.scene('waves.');b = self.scene('nods.')
        first = self.take(a, 'after-fact-1')
        other = self.take(b, 'after-fact-2', verdict={'job_id': first['id'], 'verdict': 'retry', 'notes': 'Again.'})
        with self.assertRaises(ValueError):  # a take of another shot
            self.call('POST', f"jobs/{other['id']}/human-review", {'verdict': 'reject', 'keep_job_id': first['id'], 'human_words': 'keep that'})
        with self.assertRaises(ValueError):  # still waiting for its verdict
            self.call('POST', f"jobs/{other['id']}/keep", {'human_words': 'keep it'})
        with self.assertRaises(ValueError):  # the human's words are required
            self.call('POST', f"jobs/{first['id']}/keep", {})
        job = self.call('POST', f"jobs/{first['id']}/keep", {'human_words': "let's keep the first one"})
        self.assertEqual(job['human_review']['verdict'], 'keep')
        self.assertIsNone(job['human_review']['kept_later']['from_job'])


class CodeVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)

    def tearDown(self):
        self.temp.cleanup()
        code_version._cache.update(at=0.0, value=code_version.STARTED_VERSION)

    def test_root_and_schema_report_stale_code(self):
        root = self.app.agent.dispatch('GET', '/agent/v1/', {}, None)[1]
        self.assertFalse(root['code']['stale'])
        self.assertIn('code', self.app.agent.dispatch('GET', '/agent/v1/schema', {}, None)[1])
        code_version._cache['at'] = 0.0
        with patch.object(code_version, 'digest', return_value='changed-on-disk'):
            stale = self.app.agent.dispatch('GET', '/agent/v1/', {}, None)[1]['code']
        self.assertTrue(stale['stale'])
        self.assertIn('Restart', stale['message'])

    def test_client_warns_once_when_the_server_is_stale(self):
        client = StudioClient.__new__(StudioClient)
        client._code_checked = False
        calls = []
        def request(path='', method='GET', data=None, key=None, **_):
            calls.append((method, path))
            return {'code': {'stale': True, 'message': 'Restart the server.'}} if path == '' else {'id': 'job'}
        client.request = request
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            client.generate({'id': 'scene', 'revision': 1}, approved=True, idempotency_key='k' * 10, human_words=WORDS)
            client.generate({'id': 'scene', 'revision': 1}, approved=True, idempotency_key='j' * 10, human_words=WORDS)
        self.assertEqual([w.category for w in caught], [StaleServerWarning])
        self.assertEqual(calls.count(('GET', '')), 1)


class ContinuitySizeAndLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def upload(self, image):
        return self.app.upload({'name': 'frame.png', 'data_url': data_url(image)})['id']

    def shrunk(self, factor):
        """The start frame with the fixed box redrawn smaller around its centre."""
        from PIL import Image
        first = scene_image()
        box = first.crop((100, 60, 220, 150))
        w, h = round(120 * factor), round(90 * factor)
        last = scene_image()
        background = scene_image(box_at=(-500, -500))
        last.paste(background.crop((90, 50, 230, 160)), (90, 50))
        last.paste(box.resize((w, h), Image.BICUBIC), (160 - w // 2, 105 - h // 2))
        return first, last

    def check(self, first, last, **extra):
        regions = [{'name': 'box', 'box': [90 / 704, 50 / 396, 230 / 704, 160 / 396]}]
        return self.app.agent.dispatch('POST', '/agent/v1/image-studio/continuity',
                                       dict(first={'asset_id': self.upload(first)}, last={'asset_id': self.upload(last)}, regions=regions, **extra), None)[1]

    def test_a_smaller_fixed_object_fails_as_resized(self):
        first, last = self.shrunk(0.91)
        check = self.check(first, last)
        region = check['regions'][0]
        self.assertEqual(check['verdict'], 'fail')
        self.assertEqual(region['status'], 'resized')
        self.assertAlmostEqual(region['scale_percent'], 91, delta=1.5)
        self.assertIn('size', check['reasons'][0])
        same = self.check(scene_image(), scene_image())
        self.assertEqual(same['verdict'], 'pass')
        self.assertAlmostEqual(same['regions'][0]['scale_percent'], 100, delta=0.3)
        with self.assertRaises(APIError):
            self.check(first, last, scale_tolerance_percent=50)

    def test_lock_copies_the_first_frames_pixels(self):
        first, last = self.shrunk(0.91)
        out = self.app.agent.dispatch('POST', '/agent/v1/image-studio/continuity/lock', dict(
            first={'asset_id': self.upload(first)}, last={'asset_id': self.upload(last)},
            regions=[{'name': 'box', 'box': [90 / 704, 50 / 396, 230 / 704, 160 / 396]}], feather_px=0), None)[1]
        from PIL import Image
        _, path = self.app.asset(out['asset']['id'])
        locked = Image.open(path).convert('RGB')
        self.assertEqual(locked.crop((95, 55, 225, 155)).tobytes(), first.crop((95, 55, 225, 155)).tobytes())
        self.assertEqual(locked.getpixel((400, 300)), last.getpixel((400, 300)))
        self.assertEqual(self.check(first, locked)['verdict'], 'pass')
        with self.assertRaises(APIError):
            self.app.agent.dispatch('POST', '/agent/v1/image-studio/continuity/lock', dict(
                first={'asset_id': self.upload(first)}, last={'asset_id': self.upload(last)}, regions=[]), None)


if __name__ == '__main__':
    unittest.main()
