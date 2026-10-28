"""Parity regressions exercised through isolated HTTP; no provider access."""
import copy
import base64
import io
import json
import re
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import Mock
from PIL import Image
from studio_server import Studio,StudioHandler
from workspace_accounts import WorkspaceAccounts
from agent_client import StudioClient,AgentError
from agent_openapi import specification

class CompletionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='imagine-parity-completion-');self.addCleanup(self.temp.cleanup)
        self.app=Studio(mock=True,storage=self.temp.name);self.addCleanup(self.app.productions.sql.close)
        self.app.filmmaking.request_plan=Mock(side_effect=AssertionError('No writer call allowed'))
        self.manager=WorkspaceAccounts(self.app,mock_identity=True);self.addCleanup(self.manager.sql.close)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);self.server.tester=self.app;self.server.accounts=self.manager
        self.addCleanup(self.server.server_close);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.server.shutdown)
        self.origin='http://127.0.0.1:'+str(self.server.server_port);self.client=StudioClient(self.origin,self.app.agent.token_path)
        with urlopen(self.origin) as response:self.cookie=response.headers['Set-Cookie'].split(';')[0]
        self.tab_id='parity-completion-browser-tab'

    def browser(self,path,data=None,extra=None):
        headers={'Cookie':self.cookie,'X-Browser-Tab':self.tab_id,'Origin':self.origin,'X-Tester':'local',**(extra or {})}
        raw=json.dumps(data).encode() if data is not None else None
        with urlopen(Request(self.origin+path,data=raw,headers=headers)) as response:
            cookie=response.headers.get('Set-Cookie')
            if cookie:self.cookie=cookie.split(';')[0]
            return json.load(response) if response.headers.get_content_type()=='application/json' else response.read()

    def share(self):
        self.browser('/api/browser-handoff/drafts/consent',{'enabled':True})
        state={'route':{'page':'home'},'view':{},'editors':{'precision':dict(id='asset',revision=1,dirty=True,data={'operations':[{'kind':'rotate','degrees':90}]},actions=['save','discard'])}}
        return self.browser('/api/browser-handoff/tabs',state)['tab'],state

    def test_query_parameters_filter_and_reach_target_context_over_http(self):
        self.app.video_review.db['reviews']=[dict(id='a',mock=True,scene_id='first',video_job_id='take-a'),dict(id='b',mock=True,scene_id='second',video_job_id='take-b')]
        result=self.client.request('video-review',params={'scene_id':'first'})
        self.assertEqual([r['id'] for r in result['reviews']],['a'])
        self.assertEqual(result,self.browser('/api/video-review?scene_id=first'))
        self.app.video_review.generation=Mock(return_value={'settings':{}})
        self.app.video_review.suggested_previous=Mock(return_value='origin-review')
        target=self.client.request('video-review',params={'scene_id':'first','target_video_job_id':'take-c'})
        self.assertEqual(target['suggested_previous_review_id'],'origin-review')
        self.app.video_review.suggested_previous.assert_called_once()
        for query in ('?scene_id=a&scene_id=b','?unknown=a','?scene_id='):
            with self.assertRaises(HTTPError) as error:urlopen(Request(self.origin+'/agent/v1/video-review'+query,headers={'Authorization':'Bearer '+self.client.token}))
            self.assertEqual(error.exception.code,400);error.exception.close()
        with self.assertRaises(ValueError):self.client.request('video-review',method='POST',params={'scene_id':'a'})

    def test_tab_requests_revisions_consent_acknowledgement_and_isolation(self):
        self.assertEqual(self.client.browser_tabs(),[])
        tab,state=self.share();self.assertEqual(self.client.browser_tabs(),[tab])
        self.assertEqual(self.browser('/api/browser-handoff/tabs',state)['tab']['revision'],tab['revision'])
        request=self.client.request_browser(tab,'resolve',{'editor':'precision','action':'save'})
        self.assertEqual(request['status'],'pending');self.assertNotIn('owner',request)
        self.assertFalse(self.browser('/api/browser-handoff/tabs',state)['controls_enabled'])
        self.assertTrue(self.browser('/api/browser-handoff/controls/consent',{'enabled':True})['controls_enabled'])
        with self.assertRaises(AgentError) as forbidden:self.client.request('handoff/tabs','POST',state)
        self.assertEqual(forbidden.exception.status,404)
        old_tab=self.tab_id;self.tab_id='another-completion-browser-tab'
        with self.assertRaises(HTTPError) as foreign:self.browser('/api/browser-handoff/requests/'+request['id']+'/ack',{'expected_revision':1,'status':'completed'})
        self.assertEqual(foreign.exception.code,404);foreign.exception.close();self.tab_id=old_tab
        self.browser('/api/browser-handoff/requests/'+request['id']+'/ack',{'expected_revision':1,'status':'completed'})
        self.assertEqual(self.client.browser_request(request['id'])['status'],'completed')
        changed=copy.deepcopy(state);changed['editors']['precision']['data']['operations']=[]
        self.browser('/api/browser-handoff/tabs',changed)
        with self.assertRaises(AgentError) as stale:self.client.request_browser(tab,'navigate',{'route':{'page':'projects'}})
        self.assertEqual(stale.exception.status,409)
        guest=self.manager.new_guest();foreign_client=StudioClient(self.origin,self.manager.app(guest).agent.token_path)
        self.addCleanup(self.manager.app(guest).productions.sql.close)
        self.assertEqual(foreign_client.browser_tabs(),[])
        with self.assertRaises(AgentError):foreign_client.browser_request(request['id'])
        self.browser('/api/browser-handoff/drafts/consent',{'enabled':False})
        self.assertEqual(self.client.browser_tabs(),[])
        with self.assertRaises(AgentError):self.client.request_browser(tab,'identity',{'action':'guest'})

    def test_identity_guest_request_completes_in_original_workspace(self):
        tab,state=self.share();request=self.client.request_browser(tab,'identity',{'action':'guest'})
        with self.assertRaises(AgentError) as direct:self.client.request('studio-account/guest','POST',{})
        self.assertEqual(direct.exception.code,'browser_session_required')
        self.browser('/api/browser-handoff/requests/'+request['id']+'/ack',{'expected_revision':1,'status':'awaiting_human'})
        self.browser('/api/studio-account/guest',{},extra={'X-Handoff-Request':request['id']})
        self.assertEqual(self.client.browser_request(request['id'])['status'],'completed')
        # No foreign workspace ID or new token is returned to the original agent.
        self.assertNotIn('workspace_id',self.client.browser_request(request['id']))
        for identity,app in self.manager.apps.items():
            if identity!='local-owner':app.productions.sql.close()

    def test_browser_publication_rejects_credentials_embedded_media_and_bad_destinations(self):
        tab,state=self.share()
        for data in ({'api_key':'never-share-this'},{'image':'data:image/png;base64,AAAA'}):
            unsafe=copy.deepcopy(state);unsafe['editors']['precision']['data']=data
            with self.assertRaises(HTTPError) as error:self.browser('/api/browser-handoff/tabs',unsafe)
            self.assertEqual(error.exception.code,400);error.exception.close()
        self.assertEqual(self.client.request('handoff/tabs/'+tab['id'])['state'],state)
        for route in ({'page':'home','url':'https://example.invalid'},{'page':'tool','tool':'terminal'},{'page':'project','workspace':{'production_id':'outside-workspace','stage':'edit'}}):
            with self.assertRaises(AgentError):self.client.request_browser(tab,'navigate',{'route':route})

    def test_identity_signin_safe_status_follows_human_completion(self):
        tab,state=self.share();request=self.client.request_browser(tab,'identity',{'action':'signin'})
        self.browser('/api/browser-handoff/requests/'+request['id']+'/ack',{'expected_revision':1,'status':'awaiting_human'})
        login=self.browser('/api/studio-account/signin',{},extra={'X-Handoff-Request':request['id']})
        status=self.client.browser_request(request['id']);self.assertEqual(status['status'],'awaiting_human')
        self.assertFalse(any(k in status for k in ('url','code','auth_job_id','owner')))
        self.browser(login['url'].replace(self.origin,''))
        self.assertEqual(self.client.browser_request(request['id'])['status'],'completed')

    def test_export_shared_formatter_preserves_book_script_and_originals(self):
        outline=self.client.create_production('Export story',kind='story');pid=outline['production']['id'];eid=outline['episodes'][0]['id']
        bible=self.client.request('filmmaking/series/'+pid+'/bible')
        bible=self.client.request('filmmaking/series/'+pid+'/bible','PUT',dict(expected_revision=0,answers={'idea':'A <robot> & a friend.'},guide={'cast':[{'id':'hero','name':'Hero','description':'Red coat'}]}))
        before=copy.deepcopy(self.app.productions.all('series-bible'))
        exported=self.client.export_book(pid);rendered=self.client.request('documents/render','POST',dict(document=bible,title='Export story',family='series'))
        self.assertEqual(exported,rendered);self.assertIn('A <robot> & a friend.',exported['text']);self.assertIn('### Hero',exported['text'])
        raw=json.loads(self.client.export_book(pid,format='json')['text']);self.assertEqual(raw['guide'],bible['guide'])
        self.assertEqual(self.client.export_book(eid,kind='episode')['mime'],'text/markdown')
        self.assertEqual(before,self.app.productions.all('series-bible'));self.app.filmmaking.request_plan.assert_not_called()

    def test_demo_shared_recipe_replay_and_live_refusal(self):
        fixtures=self.client.request('demo');self.assertEqual(fixtures['version'],1)
        first=self.client.request('demo/load','POST',{},'parity-demo-once');second=self.client.request('demo/load','POST',{},'parity-demo-once')
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.app.library()),3)
        self.assertEqual(len(first['scene']['keys']),2)
        self.app.mock=False
        for path,method in (('demo','GET'),('demo/load','POST')):
            with self.assertRaises(AgentError) as error:self.client.request(path,method,{} if method=='POST' else None,'live-demo-refusal')
            self.assertEqual(error.exception.status,403)

    def test_composite_preview_includes_sequence_transition_title_and_revision(self):
        if not self.app.editing.ffmpeg:self.skipTest('Local FFmpeg is required for composite previews.')
        outline=self.client.create_production('Composite preview');timeline=self.client.open_edit(outline['production']['id'])
        clips=[]
        for i,color in enumerate(('red','blue')):
            raw=io.BytesIO();Image.new('RGB',(32,18),color).save(raw,format='PNG')
            asset=self.client.request('assets','POST',dict(name=color+'.png',data_url='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()))
            clips.append(dict(id='clip-'+str(i),source=dict(kind='image',id=asset['id']),**{'in':0,'out':1},volume=0,label=color,transition=dict(type='cut' if i==0 else 'dissolve',duration=0 if i==0 else .25)))
        timeline=self.client.request('editing/timelines/'+timeline['id'],'PUT',dict(expected_revision=timeline['revision'],title='Composite preview',clips=clips,audio=[],titles=[dict(id='caption',text='Shared preview',start=0,end=.5,position='bottom',size=36,color='#ffffff')],output=dict(ratio='16:9',resolution='720p',fps=24)))
        job=self.client.preview_edit(timeline);self.assertEqual(job['id'],self.client.preview_edit(timeline)['id'])
        deadline=time.monotonic()+40
        while job['status'] in ('queued','rendering'):
            if time.monotonic()>deadline:self.fail('Composite preview timed out.')
            time.sleep(.05);job=self.client.request('editing/exports/'+job['id'])
        self.assertEqual(job['status'],'done',job.get('error'))
        first=Image.open(io.BytesIO(self.client.preview_frame(job,.25))).convert('RGB')
        last=Image.open(io.BytesIO(self.client.preview_frame(job,1.5))).convert('RGB')
        middle=Image.open(io.BytesIO(self.client.preview_frame(job,.9))).convert('RGB')
        self.assertEqual(first.size,(1280,720));self.assertGreater(first.getpixel((640,240))[0],220);self.assertGreater(last.getpixel((640,240))[2],220)
        pixel=middle.getpixel((640,240));self.assertGreater(pixel[0],20);self.assertGreater(pixel[2],20)
        whites=lambda im:sum(1 for rgb in im.crop((400,550,900,700)).get_flattened_data() if min(rgb)>180)
        self.assertGreater(whites(first),100);self.assertEqual(whites(last),0)
        latest=self.client.request('editing/timelines/'+timeline['id'],'PUT',dict(expected_revision=timeline['revision'],title='Changed after preview'))
        with self.assertRaises(AgentError) as stale:self.client.preview_edit(timeline)
        self.assertEqual(stale.exception.status,409);self.assertGreater(latest['revision'],timeline['revision'])
        self.assertEqual(len(self.app.productions.all('export')),1);self.app.filmmaking.request_plan.assert_not_called()

class CompletionContractTests(unittest.TestCase):
    def test_every_template_parameter_and_mutation_body_is_described(self):
        spec=specification()
        for path,ops in spec['paths'].items():
            for method,op in ops.items():
                names={p['name'] for p in op.get('parameters',[]) if p['in']=='path'}
                self.assertEqual(set(re.findall(r'\{([^}]+)\}',path)),names,path)
                schema=op.get('requestBody',{}).get('content',{}).get('application/json',{}).get('schema')
                if schema is not None:self.assertNotEqual(schema,{'type':'object'},(method,path))
        self.assertIn('story_direction',spec['paths']['/productions/shots/{id}']['put']['requestBody']['content']['application/json']['schema']['properties'])

if __name__=='__main__':unittest.main()
