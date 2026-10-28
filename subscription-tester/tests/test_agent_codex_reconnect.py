"""Phase 2: mock-only reconnect requests, human boundary and safe polling."""
import json
import shutil
import threading
import unittest
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor,Request,build_opener,urlopen

from agent_api import APIError
from agent_client import AgentError,StudioClient
from studio_server import Studio,StudioHandler
from workspace_accounts import WorkspaceAccounts

STATE=Path('/tmp/imagine-agent-fix')
SAFE={'id','status','step','human_action_required','error','requested_at','updated_at'}

class ReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if STATE.exists():raise RuntimeError('Refusing to reuse or delete existing /tmp/imagine-agent-fix.')
        STATE.mkdir(mode=0o700);cls.addClassCleanup(shutil.rmtree,STATE)
        cls.app=Studio(mock=True,storage=STATE)
        cls.manager=WorkspaceAccounts(cls.app,mock_identity=True)
        cls.addClassCleanup(cls.manager.sql.close)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler)
        cls.addClassCleanup(cls.server.server_close)
        if cls.server.server_port==8766:raise RuntimeError('Refusing the live Studio port.')
        cls.server.tester=cls.app;cls.server.accounts=cls.manager
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.addClassCleanup(cls.thread.join,5);cls.addClassCleanup(cls.server.shutdown)
        cls.client=StudioClient(cls.base,STATE/'agent-token')
        cls.browser=build_opener(HTTPCookieProcessor(CookieJar()))
        with cls.browser.open(cls.base+'/') as response:response.read()

    def setUp(self):
        with self.manager.lock,self.manager.sql:
            self.manager.sql.execute('DELETE FROM codex_reconnect');self.manager.jobs.clear()

    def browser_request(self,path,data=None,headers=None):
        request=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,
                        headers={'Content-Type':'application/json','Origin':self.base,'X-Tester':'local',**(headers or {})})
        with self.browser.open(request) as response:return json.load(response)

    def test_request_waits_for_human_coalesces_and_does_not_call_provider(self):
        self.assertEqual(self.client.codex_reconnect_status()['status'],'idle')
        with patch.object(self.manager,'codex_login') as login,patch('workspace_accounts.subprocess.Popen') as provider:
            request=self.client.request_codex_reconnect()
            self.assertEqual(set(request),SAFE);self.assertEqual(request['status'],'pending')
            self.assertEqual(request['step'],'human_start');self.assertTrue(request['human_action_required'])
            self.assertEqual(self.client.request_codex_reconnect()['id'],request['id'])
            self.assertEqual(self.client.studio_account()['codex_reconnect'],request)
            login.assert_not_called();provider.assert_not_called()

    def test_human_starts_mock_flow_and_agent_observes_completion(self):
        request=self.client.request_codex_reconnect()
        with patch('workspace_accounts.subprocess.Popen') as provider:
            result=self.browser_request('/api/studio-account/codex',{'request_id':request['id']})
            self.assertEqual(result['status'],'connected');provider.assert_not_called()
        state=self.client.codex_reconnect_status()
        self.assertEqual(state['id'],request['id']);self.assertEqual(state['status'],'connected')
        self.assertEqual(state['step'],'complete');self.assertFalse(state['human_action_required'])
        self.assertNotEqual(self.client.request_codex_reconnect()['id'],request['id'])

    def test_poll_redacts_device_secrets_and_reports_safe_errors(self):
        request=self.client.request_codex_reconnect()
        def login(handler):
            job=dict(id='synthetic-native-job',source=handler.workspace_id,target=handler.workspace_id,
                     kind='codex',status='waiting',url='https://auth.openai.com/synthetic-device',code='TEST-ABCDE')
            self.manager.jobs[job['id']]=job
            return {k:v for k,v in job.items() if k not in ('source','target')}
        with patch.object(self.manager,'codex_login',side_effect=login):
            self.browser_request('/api/studio-account/codex',{'request_id':request['id']})
        state=self.client.codex_reconnect_status()
        self.assertEqual(state['status'],'pending');self.assertEqual(state['step'],'device_verification')
        native=self.browser_request('/api/studio-account')['auth'];self.assertEqual(native['code'],'TEST-ABCDE')
        for value in (state,self.client.studio_account()):
            serialized=json.dumps(value)
            for secret in ('TEST-ABCDE','synthetic-device','"target"','"url"','"code"'):self.assertNotIn(secret,serialized)
        self.manager.jobs['synthetic-native-job'].update(status='error',error='unsafe synthetic error TEST-ABCDE')
        failure=self.client.codex_reconnect_status();self.assertEqual(failure['status'],'error')
        self.assertNotIn('TEST-ABCDE',json.dumps(failure));self.assertNotIn('TEST-ABCDE',json.dumps(self.client.studio_account()))

    def test_agent_cannot_choose_workspace_identity_or_complete_verification(self):
        for data in ({'workspace_id':'other'},{'account_id':'other'},{'code':'TEST-ABCDE'},{'request_id':'foreign'},{'approved':True}):
            with self.assertRaises(AgentError) as error:self.client.request('studio-account/codex','POST',data)
            self.assertEqual(error.exception.code,'invalid_request')
        for action in ('signin','logout','guest','restore-guest','cancel'):
            with self.assertRaises(AgentError) as error:self.client.request('studio-account/'+action,'POST',{})
            self.assertEqual(error.exception.status,403)
        with self.assertRaises(AgentError) as error:self.client.request('studio-account/codex/finish','POST',{})
        self.assertEqual(error.exception.status,404)

    def test_bearer_cannot_start_flow_by_spoofing_browser_headers(self):
        with patch.object(self.manager,'codex_login') as login:
            request=Request(self.base+'/api/studio-account/codex',data=b'{}',headers={
                'Authorization':'Bearer '+self.client.token,'Origin':self.base,'X-Tester':'local','Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(error.exception.code,403);error.exception.close();login.assert_not_called()

    def test_stale_browser_request_and_workspace_are_rejected(self):
        self.client.request_codex_reconnect()
        for data,headers in (({'request_id':'foreign'},{}),({}, {'X-Workspace-ID':'other'})):
            with self.assertRaises(HTTPError) as error:self.browser_request('/api/studio-account/codex',data,headers)
            self.assertEqual(error.exception.code,409);error.exception.close()

    def test_persistence_restart_and_foreign_workspace_isolation(self):
        request=self.client.request_codex_reconnect()
        other=self.manager.new_guest()
        other_client=StudioClient(self.base,self.manager.app(other).storage/'agent-token')
        self.assertEqual(other_client.codex_reconnect_status()['status'],'idle')
        self.assertEqual(other_client.studio_account()['workspace_id'],other)
        self.assertEqual(self.client.studio_account()['accounts'],[])
        handler=SimpleNamespace(workspace_id=other,session_hash='synthetic-human-session')
        with self.assertRaises(APIError) as error:self.manager.start_codex_reconnect(handler,{'request_id':request['id']})
        self.assertEqual(error.exception.status,409)
        restarted=WorkspaceAccounts(self.app,mock_identity=True)
        try:
            self.assertEqual(restarted.codex_reconnect_status('local-owner'),request)
            with restarted.lock,restarted.sql:
                restarted.sql.execute("UPDATE codex_reconnect SET step='device_verification',job_id='lost-on-restart' WHERE workspace='local-owner'")
            self.assertEqual(restarted.codex_reconnect_status('local-owner')['status'],'error')
            self.assertEqual(restarted.codex_reconnect_status(other)['status'],'idle')
        finally:restarted.sql.close()

if __name__=='__main__':unittest.main()
