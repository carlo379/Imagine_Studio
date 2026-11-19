"""A just-accepted Grok request can answer 404 before xAI registers it: keep polling during the
grace window, fail on 404 after it, and never resubmit."""
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import studio_server as studio
from image_studio import ProviderResponseError


def response(code, payload=None):
    r = Mock(status_code=code, headers={}, content=b'{}' if payload is not None else b'')
    r.json.return_value = payload or {}
    return r


class ImagePollGraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)
        self.images = self.app.images

    def tearDown(self):
        self.temp.cleanup()

    def poll(self, replies, created_at):
        client = Mock()
        client.get.side_effect = replies
        job = {'request_id': 'req-1', 'created_at': created_at}
        with patch('studio_server.oauth_headers', return_value={'Authorization': 'Bearer test-only'}), \
                patch('image_studio.time.sleep'):
            return self.images.poll_grok(client, job), job, client

    def test_early_404s_are_treated_as_still_starting(self):
        done = {'status': 'done', 'data': [{'url': 'https://example.invalid/a.png'}]}
        payload, job, client = self.poll([response(404), response(404), response(202, {'status': 'pending'}),
                                          response(200, done)], time.time())
        self.assertEqual(payload['data'], done['data'])
        self.assertEqual(job['not_found_polls'], 2)
        self.assertEqual(client.get.call_count, 4)
        client.post.assert_not_called()

    def test_404_after_the_grace_window_is_final_and_not_recoverable(self):
        client = Mock()
        client.get.side_effect = [response(404)]
        job = {'request_id': 'req-2', 'created_at': time.time() - 3600, 'recoverable': True}
        with patch('studio_server.oauth_headers', return_value={'Authorization': 'Bearer test-only'}), \
                patch('image_studio.time.sleep'):
            with self.assertRaises(ProviderResponseError):
                self.images.poll_grok(client, job)
        self.assertFalse(job['recoverable'])
        self.assertEqual(client.get.call_count, 1)
        client.post.assert_not_called()

    def test_grace_window_is_configurable(self):
        self.images.config = dict(self.images.config, poll_not_found_grace_seconds=0)
        client = Mock()
        client.get.side_effect = [response(404)]
        job = {'request_id': 'req-3', 'created_at': time.time()}
        with patch('studio_server.oauth_headers', return_value={'Authorization': 'Bearer test-only'}), \
                patch('image_studio.time.sleep'):
            with self.assertRaises(ProviderResponseError):
                self.images.poll_grok(client, job)


class VideoPollGraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_worker(self, replies, created_at):
        client = Mock()
        client.get.side_effect = replies
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        job = {'id': 'video-job', 'request_id': 'vid-1', 'created_at': created_at, 'settings': {}}
        finished = {}
        def finish(j, status, message, *args, **kwargs):
            finished.update(status=status, message=message)
        self.app.mock = False  # exercise the provider polling path; every network call is faked
        try:
            with patch('studio_server.oauth_headers', return_value={'Authorization': 'Bearer test-only'}), \
                    patch('httpx.Client', return_value=client), patch('studio_server.time.sleep'), \
                    patch.object(self.app, 'finish', side_effect=finish), patch.object(self.app, 'update'):
                self.app.video_worker(None, job)
        finally:
            self.app.mock = True
        return finished, job, client

    def test_early_404s_keep_polling_until_the_video_is_ready(self):
        done = {'status': 'done', 'video': {'url': 'https://example.invalid/v.mp4', 'duration': 6}}
        finished, job, client = self.run_worker([response(404), response(202, {'status': 'pending'}),
                                                 response(200, done)], time.time())
        self.assertEqual(finished['status'], 'done')
        self.assertEqual(job['not_found_polls'], 1)
        client.post.assert_not_called()

    def test_finished_video_keeps_the_humans_usage_readings(self):
        done = {'status': 'done', 'video': {'url': 'https://example.invalid/v.mp4', 'duration': 8},
                'usage': {'cost_in_usd_ticks': 11400000000}}
        client = Mock()
        client.get.side_effect = [response(200, done)]
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        job = {'id': 'video-job', 'request_id': 'vid-2', 'created_at': time.time(), 'settings': {},
               'usage': {'before': 15.0, 'after': None, 'unavailable': False}}
        self.app.mock = False
        try:
            with patch('studio_server.oauth_headers', return_value={'Authorization': 'Bearer test-only'}), \
                    patch('httpx.Client', return_value=client), patch('studio_server.time.sleep'), \
                    patch.object(self.app, 'finish'), patch.object(self.app, 'update'):
                self.app.video_worker(None, job)
        finally:
            self.app.mock = True
        self.assertEqual(job['usage']['before'], 15.0)
        self.assertEqual(job['provider_usage'], {'cost_in_usd_ticks': 11400000000})

    def test_404_after_the_grace_window_stops_with_resume_hint(self):
        finished, job, client = self.run_worker([response(404)], time.time() - 3600)
        self.assertEqual(finished['status'], 'error')
        self.assertIn('Video polling stopped', finished['message'])
        client.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
