"""The single human stop: one approval (approved=true + human_words) right before each take.

That approval covers the plan state, scene edits, take limits, attached frames and the
review pause; the AI review and usage readings never block. Also covers the PATCH
unknown-field refusal and the resumed-poll state fixes.
"""
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import studio_server as studio
from agent_api import APIError
from agent_client import StudioClient
import test_production_plans as plan_fixture  # module import: its TestCase is not rerun here
from test_studio import PNG

WORDS = 'Yes, go ahead with this take.'


class SingleStopTests(unittest.TestCase):
    setUp = plan_fixture.PlanTests.setUp
    tearDown = plan_fixture.PlanTests.tearDown
    call = plan_fixture.PlanTests.call
    scene = plan_fixture.PlanTests.scene
    kit = plan_fixture.PlanTests.kit
    fresh = plan_fixture.PlanTests.fresh
    generate = plan_fixture.PlanTests.generate
    verdict = plan_fixture.PlanTests.verdict
    edit = plan_fixture.PlanTests.edit
    plan = plan_fixture.PlanTests.plan
    approve = plan_fixture.PlanTests.approve

    def wait(self, job_id):
        for _ in range(50):
            job = next(j for j in self.app.records() if j['id'] == job_id)
            if job['status'] != 'pending':return job
            time.sleep(.1)
        self.fail('mock generation did not finish')

    def take(self, scene, key, **extra):
        scene = self.fresh(scene)
        body = {'expected_revision': scene['revision'], 'approved': True, 'human_words': WORDS, **extra}
        return self.wait(self.call('POST', f"scenes/{scene['id']}/generate", body, key)['id'])

    def test_take_approval_covers_plan_changes_and_limits(self):
        a = self.scene('waves.');plan = self.plan(a);self.approve(plan)
        self.edit(a, 'waves, then smiles.')
        # Plan-only generation still refuses a changed shot ...
        with self.assertRaises(APIError) as error:self.generate(a, plan, 'plan-only-changed')
        self.assertEqual(error.exception.code, 'plan_scene_changed')
        # ... but the human's approval of this take is enough, without re-approving the plan.
        job = self.take(a, 'take-approved-1', plan_id=plan['id'])
        self.assertEqual(job['take_approval']['human_words'], WORDS)
        self.assertEqual([w['code'] for w in job['plan']['warnings']], ['plan_scene_changed'])
        self.assertTrue(self.call('GET', 'plans/'+plan['id'])['approved'], 'scene edits never void the plan approval')
        # Takes beyond the plan's limit become warnings, and an unapproved plan is fine too.
        self.verdict(job, 'retry', 'Again.')
        second = self.take(a, 'take-approved-2', plan_id=plan['id'])
        self.verdict(second, 'retry', 'Again.')
        third = self.take(a, 'take-approved-3', plan_id=plan['id'])
        self.assertIn('plan_takes_exhausted', [w['code'] for w in third['plan']['warnings']])
        self.assertEqual(self.call('GET', 'plans/'+plan['id'])['items'][0]['takes_used'], 3)
        b = self.scene('nods.');draft = self.plan(b)
        self.assertIn('plan_not_approved', [w['code'] for w in self.take(b, 'take-draft-plan', plan_id=draft['id'])['plan']['warnings']])
        # Still refused: words without approved=true, a closed plan and a kept shot.
        with self.assertRaises(APIError) as error:
            self.call('POST', f"scenes/{b['id']}/generate", {'expected_revision': self.fresh(b)['revision'], 'plan_id': draft['id'], 'human_words': WORDS}, 'words-alone')
        self.assertEqual(error.exception.code, 'approval_required')
        with self.assertRaises(APIError):
            self.call('POST', f"scenes/{b['id']}/generate", {'expected_revision': self.fresh(b)['revision'], 'approved': True, 'human_words': '  '}, 'blank-words')

    def test_verdict_and_next_approval_in_one_step(self):
        a = self.scene('waves.');b = self.scene('nods.')
        first = self.take(a, 'one-step-1')
        self.assertEqual(first['human_review']['status'], 'pending')
        # approved=true alone still waits for the verdict ...
        with self.assertRaises(APIError) as error:
            self.call('POST', f"scenes/{b['id']}/generate", {'expected_revision': self.fresh(b)['revision'], 'approved': True}, 'one-step-plain')
        self.assertEqual(error.exception.code, 'human_review_required')
        # ... the human's approval of the next take does not, and can carry the verdict.
        second = self.take(b, 'one-step-2', verdict={'job_id': first['id'], 'verdict': 'reject', 'notes': 'Wrong energy.'})
        reviewed = self.call('GET', 'jobs/'+first['id'])['human_review']
        self.assertEqual((reviewed['verdict'], reviewed['human_words'], reviewed['notes']), ('reject', WORDS, 'Wrong energy.'))
        # A rejected, unchanged shot can be rerolled when the human approves that take.
        third = self.take(a, 'one-step-3', verdict={'job_id': second['id'], 'verdict': 'keep', 'human_words': 'Keep the nod.'})
        self.assertEqual(self.call('GET', 'jobs/'+second['id'])['human_review']['human_words'], 'Keep the nod.')
        self.assertEqual(third['status'], 'done')
        # A pending take may also stay unreviewed while the next approved take runs.
        self.take(b, 'one-step-4')
        self.assertEqual(len(self.app.pending_human_review()), 2)
        with self.assertRaises(APIError) as error:
            self.call('POST', f"scenes/{b['id']}/generate", {'expected_revision': self.fresh(b)['revision'], 'approved': True,
                                                             'verdict': {'job_id': third['id'], 'verdict': 'keep'}}, 'verdict-without-words')
        self.assertEqual(error.exception.code, 'approval_required')

    def test_uploaded_frames_approved_by_route_or_by_the_take(self):
        shot = self.app.productions.dispatch('POST', [], dict(kind='quick', title='Any project'))[1]['shots'][0]
        frame = self.app.upload(dict(name='Edited frame', data_url=PNG))
        with self.app.productions.sql:
            self.app.productions.put('shot', {**shot, 'video_mode': 'image_to_video', 'start_frame_asset_id': frame['id']})
        record = self.app.agent.record(shot['video_id'])
        record = self.call('PATCH', 'scenes/'+record['id'], {'expected_revision': record['revision'], 'changes': {'first': {'asset_id': frame['id']}, 'prompt': 'Camera stays locked.'}})
        route = f"scenes/{record['id']}/generate"
        with self.assertRaises(APIError) as error:
            self.call('POST', route, {'expected_revision': record['revision'], 'approved': True}, 'frame-plain')
        self.assertEqual(error.exception.code, 'start_frame_required')
        job = self.wait(self.call('POST', route, {'expected_revision': record['revision'], 'approved': True, 'human_words': WORDS}, 'frame-take')['id'])
        self.assertFalse(job['allow_unapproved_start_frame']);self.assertEqual(job['take_approval']['human_words'], WORDS)
        # The approval route works on any uploaded asset; the agent relays the human's words.
        other = self.app.upload(dict(name='Other frame', data_url=PNG))
        with self.assertRaises(APIError):self.call('POST', f"assets/{other['id']}/approve", {'approved': True})
        with self.assertRaises(APIError) as error:self.call('POST', 'assets/missing/approve', {'human_words': 'ok'})
        self.assertEqual(error.exception.status, 404)
        approved = self.call('POST', f"assets/{other['id']}/approve", {'human_words': 'That frame is great.'})
        self.assertTrue(approved['approved']);self.assertEqual(approved['approval']['human_words'], 'That frame is great.')
        revoked = self.call('POST', f"assets/{other['id']}/approve", {'approved': False, 'human_words': 'Actually no.'})
        self.assertFalse(revoked['approved']);self.assertNotIn('approval', revoked)

    def test_patch_refuses_unknown_fields_without_bumping_the_revision(self):
        a = self.scene('waves.');before = self.fresh(a)
        for body in ({'expected_revision': before['revision'], 'scene': {'prompt': 'x'}}, {'expected_revision': before['revision']}):
            with self.assertRaises(APIError) as error:self.call('PATCH', 'scenes/'+a['id'], body)
            self.assertEqual(error.exception.code, 'invalid_scene');self.assertIn('changes', str(error.exception))
        self.assertEqual(self.fresh(a)['revision'], before['revision'])
        titled = self.call('PATCH', 'scenes/'+a['id'], {'expected_revision': before['revision'], 'title': 'Renamed'})
        self.assertEqual(titled['title'], 'Renamed')


class WorkerErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.app = studio.Studio(mock=True, storage=self.temp.name)
        self.app.update(signed_in=True)

    def tearDown(self):self.temp.cleanup()

    def live_job(self):
        job = {'id': 'job12345', 'created_at': time.time(), 'mock': False, 'settings': {'duration': 5, 'resolution': '480p'},
               'status': 'pending', 'video': None, 'request_id': 'req123', 'agent_key': 'key12345'}
        with self.app.lock:self.app.history.insert(0, job)
        return job

    def test_unexpected_worker_error_keeps_its_cause_and_resume_clears_the_stale_error(self):
        job = self.live_job()
        with patch.object(self.app, 'mock', False), patch('httpx.Client', side_effect=KeyError('video')), \
                patch.object(studio, 'oauth_headers', return_value={'Authorization': 'Bearer secret-token'}):
            self.app.video_worker(None, job)
        self.assertEqual(job['status'], 'error')
        self.assertEqual(job['worker_error']['type'], 'KeyError');self.assertIn("KeyError: 'video'", job['message'])
        self.assertNotIn('secret-token', json.dumps(job))
        self.assertEqual(job['human_review']['status'], 'pending')
        self.app.update(phase='error')
        with patch.object(self.app, 'spawn'):self.app.resume(job['id'])
        self.assertEqual((job['status'], job['resume_count']), ('pending', 1))
        self.assertNotIn('human_review', job, 'the failure pause lifts while the take is polled again')


class ClientResumeTests(unittest.TestCase):
    def test_wait_for_job_ignores_the_error_from_before_a_resume(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        app = studio.Studio(mock=True, storage=temp.name)
        server = ThreadingHTTPServer(('127.0.0.1', 0), studio.StudioHandler);server.tester = app
        threading.Thread(target=server.serve_forever, daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        client = StudioClient(f'http://127.0.0.1:{server.server_port}', app.agent.token_path)
        job = {'id': 'job67890', 'created_at': time.time(), 'mock': False, 'settings': {}, 'status': 'error', 'video': None,
               'request_id': 'req678', 'message': 'old failure'}
        with app.lock:app.history.insert(0, job)
        # An older server leaves the old error in place: the client keeps waiting for the resumed attempt.
        with patch.object(app, 'resume'):client.resume_job(job['id'])
        timer = threading.Timer(.3, lambda: job.update(status='done', resume_count=1));timer.start();self.addCleanup(timer.cancel)
        self.assertEqual(client.wait_for_job(job['id'], timeout=5, interval=.05)['status'], 'done')
        # Without a resume, a finished error returns at once.
        job.update(status='error')
        self.assertEqual(client.wait_for_job(job['id'], timeout=5, interval=.05)['status'], 'error')


class BrowserApprovalTests(unittest.TestCase):
    def test_browser_approves_an_uploaded_asset(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        app = studio.Studio(mock=True, storage=temp.name)
        server = ThreadingHTTPServer(('127.0.0.1', 0), studio.StudioHandler);server.tester = app
        threading.Thread(target=server.serve_forever, daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}';asset = app.upload(dict(name='Frame', data_url=PNG))
        post = lambda body: urlopen(Request(base+f"/api/assets/{asset['id']}/approve", data=json.dumps(body).encode(), method='POST',
                                            headers={'Content-Type': 'application/json', 'X-Tester': 'local', 'Origin': base}))
        with post({'approved': True}) as response:payload = json.load(response)
        self.assertTrue(payload['approved']);self.assertEqual(payload['approval']['source'], 'browser')
        with self.assertRaises(HTTPError) as error:post({'approved': True, 'human_words': 'browser clicks need no words'})
        self.assertEqual(error.exception.code, 400);error.exception.close()


if __name__ == '__main__':
    unittest.main()
