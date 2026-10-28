"""Phase 3 metadata only: no provider calls, saved-data writes or media generation."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from agent_api import APIError
from browser_handoff import BrowserHandoff
from studio_server import Studio,save_json

class BrowserHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='imagine-agent-fix-',dir='/tmp');self.addCleanup(self.temp.cleanup)
        self.app=Studio(mock=True,storage=self.temp.name);self.p=self.app.productions;self.addCleanup(self.p.sql.close);self.h=self.app.handoff
        outline=self.p.dispatch('POST',[],{'kind':'story','title':'Return flow series'})[1]
        self.pid=outline['production']['id'];self.ep=outline['episodes'][0]['id'];self.tab='synthetic-origin-tab';self.session='synthetic-browser-session'
        self.bible=self.app.filmmaking.series.save_bible(self.pid,{'expected_revision':0,'guide':{
            'cast':[{'id':'character','name':'Hero','description':'A robot.'}],
            'places':[{'id':'location','name':'Home','description':'A warm room.'}],
            'props':[{'id':'prop','name':'Tool','description':'A small wrench.'}]}})
        self.book=self.app.filmmaking.series.save_book(self.ep,{'expected_revision':0,'guide':copy.deepcopy(self.bible['guide'])})

    def context(self,category='Prop',episode=False):
        scope,identity,document=('episode-book',self.ep,self.book) if episode else ('series-bible',self.pid,self.bible)
        snapshot=self.app.filmmaking.series.workshop(scope,identity,{'expected_revision':document['revision']})
        entity=next(e for e in snapshot['entities'] if e['category']==category)
        view=next(v for v in snapshot['views'] if v['entity_id']==entity['id'])
        return {'route':{'page':'project','workspace':{'production_id':self.pid,'episode_id':self.ep,'stage':'develop','board_view':'board'}},'title':'Back to the book','draft_id':view['draft_id'],
                'context':{'scope':('episodes/'+self.ep) if episode else ('series/'+self.pid),'entity_id':entity['id'],'view_id':view['id'],'expected_revision':view['revision'],'page':3,'visual':{'activeStep':3,'expanded':[False,True,False,True],'heroChoice':'','scrollTop':380}}}

    def browser(self,method,parts,data=None,tab=None,session=None):return self.h.browser_dispatch(session or self.session,tab or self.tab,method,parts,data or {})
    def call(self,method,path,data=None):return self.app.agent.dispatch(method,'/agent/v1/handoff/'+path,data or {})[1]

    def test_bible_episode_all_categories_read_request_ack_finish_persists_exact_context(self):
        for episode in (False,True):
            for category in ('Character','Location','Prop'):
                with self.subTest(episode=episode,category=category):
                    value=self.context(category,episode);flow=self.browser('POST',['flows'],value)
                    persisted=BrowserHandoff(self.app,save_json).dispatch('GET',['flows',flow['id']],{})[1]
                    self.assertEqual(persisted['value'],value);self.assertNotIn('owner',persisted)
                    requested=self.call('POST','flows/'+flow['id']+'/request',{'expected_revision':flow['revision']})
                    self.assertEqual(requested['status'],'return_requested')
                    self.assertEqual(self.call('POST','flows/'+flow['id']+'/request',{'expected_revision':requested['revision']}),requested)
                    with self.assertRaises(APIError) as error:self.call('POST','flows/'+flow['id']+'/finish',{'expected_revision':requested['revision']})
                    self.assertEqual(error.exception.code,'return_not_applied')
                    acknowledged=self.browser('POST',['flows',flow['id'],'returned'],{'expected_revision':requested['revision']})
                    finished=self.call('POST','flows/'+flow['id']+'/finish',{'expected_revision':acknowledged['revision']})
                    self.assertEqual(finished['status'],'finished');self.assertEqual(finished['value'],value)

    def test_five_step_handoffs_preserve_every_section_and_return_context(self):
        for episode in (False,True):
            for category in ('Character','Location','Prop'):
                value=self.context(category,episode)
                before=copy.deepcopy(self.app.images.db)
                for step in range(5):
                    with self.subTest(category=category,episode=episode,step=step):
                        value['context']['visual'].update(activeStep=step,expanded=[i==step for i in range(5)])
                        flow=self.browser('POST',['flows'],value)
                        self.assertEqual(flow['value'],value)
                        requested=self.call('POST','flows/'+flow['id']+'/request',{'expected_revision':flow['revision']})
                        returned=self.browser('POST',['flows',flow['id'],'returned'],{'expected_revision':requested['revision']})
                        finished=self.call('POST','flows/'+flow['id']+'/finish',{'expected_revision':returned['revision']})
                        self.assertEqual(finished['value']['context']['visual'],value['context']['visual'])
                self.assertEqual(self.app.images.db,before,'Opening a return flow does not modify or generate images')

    def test_invalid_section_states_are_rejected(self):
        value=self.context()
        for step,expanded in ((4,[False]*4),(5,[False]*5),(-1,[False]*5),(True,[False]*5),(0,[False]*6),(0,[False]*4+[1])):
            bad=copy.deepcopy(value);bad['context']['visual'].update(activeStep=step,expanded=expanded)
            with self.subTest(step=step,expanded=expanded),self.assertRaises(APIError):
                self.browser('POST',['flows'],bad)

    def test_foreign_tab_workspace_and_stale_revision_do_not_apply(self):
        flow=self.browser('POST',['flows'],self.context());before=copy.deepcopy(self.app.images.db)
        with self.assertRaises(APIError) as error:self.browser('POST',['flows',flow['id'],'returned'],{'expected_revision':1},tab='another-browser-tab')
        self.assertEqual(error.exception.status,404)
        self.assertEqual(self.browser('GET',[],tab='another-browser-tab')['flows'],[])
        with tempfile.TemporaryDirectory(prefix='imagine-agent-fix-',dir='/tmp') as directory:
            other=Studio(mock=True,storage=directory);self.addCleanup(other.productions.sql.close)
            with self.assertRaises(APIError) as error:other.handoff.dispatch('GET',['flows',flow['id']],{})
            self.assertEqual(error.exception.status,404)
        self.call('POST','flows/'+flow['id']+'/request',{'expected_revision':1})
        with self.assertRaises(APIError) as error:self.call('POST','flows/'+flow['id']+'/request',{'expected_revision':1})
        self.assertEqual(error.exception.status,409);self.assertEqual(self.app.images.db,before)

    def test_new_return_supersedes_old_and_expiration_is_discoverable(self):
        value=self.context();old=self.browser('POST',['flows'],value);new=self.browser('POST',['flows'],value)
        self.assertEqual(self.call('GET','flows/'+old['id'])['status'],'superseded')
        self.assertEqual([f['id'] for f in self.browser('GET',[])['flows']],[new['id']])
        with self.assertRaises(APIError):self.call('POST','flows/'+old['id']+'/request',{'expected_revision':2})
        with patch('browser_handoff.time.time',return_value=new['expires_at']+1):
            self.assertEqual(self.call('GET','flows'),[])
            with self.assertRaises(APIError) as error:self.call('GET','flows/'+new['id'])
            self.assertEqual(error.exception.status,404)

    def test_context_cannot_redirect_or_reuse_foreign_entity_view_draft(self):
        value=self.context();other=self.context('Location');before=copy.deepcopy(self.app.images.db)
        for change in ({'route':{'page':'tool','tool':'image'}},
                {'draft_id':'missing-draft'},
                {'context':{**value['context'],'scope':'series/foreign'}},
                {'context':{**value['context'],'visual':{**value['context']['visual'],'heroChoice':'foreign-image'}}},
                {'context':{**value['context'],'visual':{**value['context']['visual'],'scrollTop':-1}}},
                {'context':{**value['context'],'visual':{**value['context']['visual'],'expanded':[True]}}}):
            with self.assertRaises(APIError):self.browser('POST',['flows'],{**value,**change})
        with self.assertRaises(APIError):self.browser('POST',['flows'],{**value,'context':{**value['context'],'view_id':other['context']['view_id']}})
        with self.assertRaises(APIError):self.browser('POST',['flows'],{**value,'draft_id':other['draft_id']})
        self.assertEqual(self.call('GET','flows'),[]);self.assertEqual(self.app.images.db,before)

    def test_opt_in_snapshots_never_modify_saved_data_and_agent_has_no_write_route(self):
        data={k:{'id':'pending-'+k,'revision':2,'dirty':True,'data':{'title':'Unsaved '+k}} for k in ('book','image','video','timeline')}
        before=(copy.deepcopy(self.app.images.db),copy.deepcopy(self.app.agent.db),list(self.p.sql.execute('SELECT * FROM records ORDER BY id')))
        with self.assertRaises(APIError) as error:self.browser('POST',['drafts'],data)
        self.assertEqual(error.exception.code,'consent_required');self.assertEqual(self.call('GET','drafts'),[])
        self.browser('POST',['drafts','consent'],{'enabled':True});snapshot=self.browser('POST',['drafts'],data)
        self.assertEqual(snapshot['drafts'],data);self.assertTrue(snapshot['read_only'])
        self.assertEqual(self.call('GET','drafts/'+snapshot['id']),snapshot)
        for path in ('drafts','drafts/'+snapshot['id'],'drafts/consent','drafts/'+snapshot['id']+'/apply','flows'):
            with self.assertRaises(APIError) as error:self.call('POST',path,data)
            self.assertEqual(error.exception.status,404)
        self.assertEqual(before,(self.app.images.db,self.app.agent.db,list(self.p.sql.execute('SELECT * FROM records ORDER BY id'))))
        with self.assertRaises(APIError):self.h.browser_dispatch(None,self.tab,'POST',['drafts','consent'],{'enabled':True})

    def test_revocation_expiry_limits_and_secret_rejection(self):
        self.browser('POST',['drafts','consent'],{'enabled':True})
        data={'book':{'id':'pending','revision':0,'dirty':True,'data':{'guide':{'name':'Pending prop'}}}}
        snapshot=self.browser('POST',['drafts'],data)
        for payload in ({'api_key':'synthetic-secret'},{'accessToken':'synthetic-secret'},{'token':'synthetic-secret'},{'text':'x'*270000},{'image':'data:image/png;base64,AA'}):
            with self.assertRaises(APIError):self.browser('POST',['drafts'],{**data,'book':{**data['book'],'data':payload}})
        with patch('browser_handoff.time.time',return_value=snapshot['expires_at']+1):self.assertEqual(self.call('GET','drafts'),[])
        snapshot=self.browser('POST',['drafts'],data)
        self.browser('POST',['drafts','consent'],{'enabled':False});self.assertEqual(self.call('GET','drafts'),[])
        with self.assertRaises(APIError) as error:self.call('GET','drafts/'+snapshot['id'])
        self.assertEqual(error.exception.status,404)

class BrowserHandoffHTTPTests(unittest.TestCase):
    """Only an isolated mock listener; cookie publishing and native client reads."""
    @classmethod
    def setUpClass(cls):
        import threading
        from http.cookiejar import CookieJar
        from http.server import ThreadingHTTPServer
        from urllib.request import build_opener,HTTPCookieProcessor
        from agent_client import StudioClient
        from studio_server import StudioHandler
        from workspace_accounts import WorkspaceAccounts
        cls.temp=tempfile.TemporaryDirectory(prefix='imagine-agent-fix-',dir='/tmp');cls.addClassCleanup(cls.temp.cleanup)
        cls.app=Studio(mock=True,storage=cls.temp.name);cls.addClassCleanup(cls.app.productions.sql.close)
        cls.manager=WorkspaceAccounts(cls.app,mock_identity=True);cls.addClassCleanup(cls.manager.sql.close)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);cls.addClassCleanup(cls.server.server_close)
        if cls.server.server_port==8766:raise RuntimeError('Refusing the live Studio port.')
        cls.server.tester=cls.app;cls.server.accounts=cls.manager;cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.addClassCleanup(cls.thread.join,5);cls.addClassCleanup(cls.server.shutdown)
        cls.client=StudioClient(cls.base,cls.app.storage/'agent-token')
        cls.browser=build_opener(HTTPCookieProcessor(CookieJar()))
        with cls.browser.open(cls.base+'/') as response:response.read()

    def browser_request(self,path,data=None,headers=None):
        import json
        from urllib.request import Request
        request=Request(self.base+'/api/browser-handoff'+path,data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type':'application/json','Origin':self.base,'X-Tester':'local','X-Browser-Tab':'synthetic-http-tab',**(headers or {})})
        with self.browser.open(request) as response:return json.load(response)

    def test_cookie_opt_in_client_discovery_and_revoke(self):
        self.browser_request('/drafts/consent',{'enabled':True})
        snapshot=self.browser_request('/drafts',{'image':{'id':'synthetic-draft','revision':1,'dirty':True,'data':{'prompt':'Pending local text'}}})
        self.assertEqual(self.client.browser_draft(snapshot['id']),snapshot)
        self.assertIn(snapshot,self.client.browser_drafts())
        self.browser_request('/drafts/consent',{'enabled':False});self.assertEqual(self.client.browser_drafts(),[])
        self.assertEqual(self.client.return_flows(),[])
        self.assertTrue(self.client.request('handoff')['human_consent_required'])

    def test_bearer_cannot_publish_and_browser_cannot_pick_workspace_or_foreign_origin(self):
        from urllib.error import HTTPError
        from urllib.request import Request,urlopen
        from agent_client import AgentError,StudioClient
        for path in ('/drafts/consent','/drafts','/flows'):
            request=Request(self.base+'/api/browser-handoff'+path,data=b'{}',headers={
                'Authorization':'Bearer '+self.client.token,'Origin':self.base,'X-Tester':'local','X-Browser-Tab':'synthetic-http-tab','Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as error:urlopen(request)
            self.assertEqual(error.exception.code,403);error.exception.close()
        for headers in ({'X-Workspace-ID':'foreign-workspace'},{'Origin':'https://foreign.invalid'}):
            with self.assertRaises(HTTPError) as error:self.browser_request('/drafts/consent',{'enabled':True},headers)
            self.assertEqual(error.exception.code,409 if 'X-Workspace-ID' in headers else 403);error.exception.close()
        other=self.manager.new_guest();foreign=StudioClient(self.base,self.manager.app(other).storage/'agent-token')
        self.browser_request('/drafts/consent',{'enabled':True})
        snapshot=self.browser_request('/drafts',{'book':{'id':'synthetic-book','revision':0,'dirty':True,'data':{'title':'Private pending book'}}})
        self.assertEqual(foreign.browser_drafts(),[])
        with self.assertRaises(AgentError) as error:foreign.browser_draft(snapshot['id'])
        self.assertEqual(error.exception.status,404)
        self.browser_request('/drafts/consent',{'enabled':False})

if __name__=='__main__':unittest.main()

