"""Mock-only Phase 1 contracts; live credential and provider functions are mocked."""
import json
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from agent_api import APIError
from agent_client import StudioClient,AgentError
from studio_server import Studio

ROOT=Path(__file__).resolve().parents[1]
STATE=Path('/tmp/imagine-agent-fix')

class ModelAccessTests(unittest.TestCase):
    def test_same_fresh_check_never_uses_cached_status_or_generates(self):
        with tempfile.TemporaryDirectory(prefix='imagine-model-access-') as directory:
            app=Studio(mock=True,storage=directory)
            app.mock=False;app.update(signed_in=True)
            response=Mock(status_code=401)
            with patch('studio_server.oauth_headers',return_value={'Authorization':'Bearer fake-test-credential'}) as credentials,patch('httpx.Client') as factory,patch.object(app,'generate') as generate:
                client=factory.return_value.__enter__.return_value;client.get.return_value=response
                first=app.agent.dispatch('POST','/agent/v1/account/grok-check',{})[1]
                self.assertFalse(first['signed_in']);self.assertFalse(first['image_access_verified'])
                response.status_code=200
                second=app.check_grok_connection()
                self.assertTrue(second['signed_in']);self.assertFalse(second['image_access_verified'])
                self.assertEqual(credentials.call_count,2);self.assertEqual(client.get.call_count,2)
                self.assertEqual(client.get.call_args.args,('https://api.x.ai/v1/models',))
                client.post.assert_not_called();generate.assert_not_called()

    def test_upstream_failure_is_not_cached_success(self):
        with tempfile.TemporaryDirectory(prefix='imagine-model-access-') as directory:
            app=Studio(mock=True,storage=directory);app.mock=False;app.update(signed_in=True)
            with patch('studio_server.oauth_headers',return_value={}),patch('httpx.Client') as factory:
                factory.return_value.__enter__.return_value.get.return_value.status_code=500
                with self.assertRaisesRegex(ValueError,'HTTP 500'):app.check_grok_connection()

class Phase1MockHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Refuse to delete anyone else's temporary work. Own only this server PID.
        if STATE.exists():raise RuntimeError('/tmp/imagine-agent-fix already exists; inspect and remove it before this suite.')
        STATE.mkdir(mode=0o700)
        cls.process=None
        cls.addClassCleanup(cls.cleanup)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        if port==8766:raise RuntimeError('Refusing the live Studio port.')
        cls.base=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'studio_server.py'),'--port',str(port),'--state-dir',str(STATE)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if cls.process.poll() is not None:raise RuntimeError('Isolated mock server exited during startup.')
            if (STATE/'agent-token').exists():
                try:
                    cls.client=StudioClient(cls.base,STATE/'agent-token')
                    cls.client.request('schema');return
                except (OSError,AgentError):pass
            time.sleep(.05)
        raise RuntimeError('Isolated mock server did not start.')

    @classmethod
    def cleanup(cls):
        if cls.process is not None:
            cls.process.terminate()
            try:cls.process.wait(timeout=5)
            except subprocess.TimeoutExpired:cls.process.kill();cls.process.wait()
        shutil.rmtree(STATE)

    def test_model_access_contract(self):
        result=self.client.check_grok_model_access()
        self.assertTrue(result['mock']);self.assertFalse(result['image_access_verified'])

    def test_url_remove_conflicts_restore_and_no_resurrection(self):
        rows=self.client.request('urls','POST',{'url':'https://example.invalid/parity.png','name':'Parity'})
        record=next(r for r in rows if r['name']=='Parity')
        archived=self.client.archive_url(record)
        self.assertTrue(archived['archived']);self.assertEqual(archived['revision'],record['revision']+1)
        self.assertFalse(any(r['url_id']==record['url_id'] for r in self.client.remembered_urls()))
        self.client.request('urls','POST',{'url':record['src'],'name':'Stale browser cache'})
        self.assertFalse(any(r['url_id']==record['url_id'] for r in self.client.remembered_urls()))
        with self.assertRaises(AgentError) as conflict:self.client.archive_url(record,False)
        self.assertEqual(conflict.exception.status,409)
        restored=self.client.archive_url(archived,False)
        self.assertEqual(restored['url_id'],record['url_id'])
        self.assertIn(restored,self.client.remembered_urls(True))
        # A new client reads server truth, rather than its own local cache.
        self.assertIn(restored,StudioClient(self.base,STATE/'agent-token').remembered_urls())

    def test_diagnostic_approval_key_replay_conflict_and_status(self):
        with self.assertRaises(AgentError) as denied:self.client.image_test('apple',idempotency_key='parity-denied')
        self.assertEqual(denied.exception.status,403)
        with self.assertRaises(AgentError) as missing:self.client.request('image-test','POST',{'prompt':'apple','approved':True})
        self.assertEqual(missing.exception.code,'idempotency_required')
        self.client.request('account/login','POST',{})
        deadline=time.monotonic()+5
        while not self.client.request('account')['signed_in']:
            if time.monotonic()>deadline:self.fail('Mock login did not finish')
            time.sleep(.05)
        original=self.client.image_test('apple',approved=True,idempotency_key='phase1-mock-diagnostic')
        repeat=self.client.image_test('apple',approved=True,idempotency_key='phase1-mock-diagnostic')
        self.assertEqual(original['id'],repeat['id'])
        with self.assertRaises(AgentError) as conflict:self.client.image_test('pear',approved=True,idempotency_key='phase1-mock-diagnostic')
        self.assertEqual(conflict.exception.status,409)
        deadline=time.monotonic()+5
        while True:
            result=self.client.image_test_status(original['id'])
            if result['status']!='pending':break
            if time.monotonic()>deadline:self.fail('Mock image diagnostic did not finish')
            time.sleep(.05)
        self.assertEqual(result['status'],'done');self.assertEqual(result['http_status'],200)
        self.assertTrue(result['image'].startswith('data:image/'))
        self.assertNotIn('key',result);self.assertNotIn('fingerprint',result)

    def test_projects_only_and_classification_discovery(self):
        quick=self.client.create_production('Parity quick',kind='quick')['production']
        story=self.client.create_production('Parity series',kind='story')['production']
        self.client.create_image('Standalone image',{'prompt':'Saved draft only'})
        page=self.client.recent_productions(projects_only=True,limit=100)
        self.assertTrue(all(r['is_project'] for r in page['items']))
        self.assertEqual(next(r for r in page['items'] if r['id']==quick['id'])['project_label'],'Quick Video')
        self.assertIsNone(next(r for r in page['items'] if r['id']==story['id'])['project_label'])
        schema=self.client.request('productions/schema')
        self.assertIn('projects_only',schema['pagination']['filters'])
        self.assertIn('classification',schema['pagination'])
        self.assertGreaterEqual(self.client.recent_productions(limit=100)['production_total'],page['production_total'])

class DiagnosticPersistenceTests(unittest.TestCase):
    def test_completed_and_interrupted_requests_are_never_replayed_after_restart(self):
        with tempfile.TemporaryDirectory(prefix='imagine-diagnostic-') as directory:
            app=Studio(mock=True,storage=directory)
            with patch.object(app,'begin') as begin:
                status,record=app.diagnostics.start({'prompt':'apple','approved':True},'persist-once-key',1000)
                self.assertEqual(status,202)
                callback=begin.call_args.kwargs['on_complete']
                callback({'phase':'done','message':'Mock completed','http_status':200,'image':'data:image/png;base64,mock'})
                app.diagnostics.start({'prompt':'apple','approved':True},'persist-once-key',1000)
                begin.assert_called_once()
                app.diagnostics.start({'prompt':'pear','approved':True},'interrupted-key',1000)
            restarted=Studio(mock=True,storage=directory)
            with patch.object(restarted,'begin') as begin:
                replay=restarted.diagnostics.start({'prompt':'apple','approved':True},'persist-once-key',1000)[1]
                self.assertEqual(replay['id'],record['id']);self.assertEqual(replay['status'],'done')
                interrupted=restarted.diagnostics.start({'prompt':'pear','approved':True},'interrupted-key',1000)[1]
                self.assertEqual(interrupted['status'],'error');begin.assert_not_called()

if __name__=='__main__':unittest.main()
