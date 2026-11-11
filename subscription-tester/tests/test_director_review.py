import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import Request,urlopen
import studio_server as studio
from agent_api import APIError
from test_studio import PNG,request

DIRECTOR={'model':'claude-opus-5-5','session_id':'director-session-1','product':'Claude Code'}
GOOD={'reviewer':{'model':'gpt-review-1','session_id':'reviewer-session-1','product':'Codex'},
      'scores':{'story':8,'identity':9,'craft':7,'performance':7},'issues':[],'frames_examined':12,'summary':'Plays the beat.'}

class DirectorReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name);self.api=self.app.agent
        asset=self.app.upload({'name':'view.png','data_url':PNG})
        self.call('POST','references',{'title':'SampleHero','handle':'SampleHero','category':'Character','description':'A robot.','images':[{'asset_id':asset['id']}]})
        self.app.update(signed_in=True);self.network=patch('httpx.Client');self.network.start()
    def tearDown(self):self.network.stop();self.temp.cleanup()
    def call(self,method,path,data=None,key=None):return self.api.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def roles(self):
        return self.call('PUT','roles',{'director':{'model':'claude-opus-5-5','product':'Claude Code'},'reviewer':{'model':'gpt-review-1','product':'Codex'},
                                        'human_words':'Use Opus to direct and GPT to review.'})
    def take(self,key,agent=DIRECTOR,text='waves.'):
        scene=self.call('POST','scenes',{'title':'Shot','scene':{'prompt':'@SampleHero '+text},'named_references':['SampleHero']})
        body={'expected_revision':scene['revision'],'approved':True,**({'agent':agent} if agent else {})}
        job=self.call('POST',f"scenes/{scene['id']}/generate",body,key)
        for _ in range(50):
            done=next(j for j in self.app.records() if j['id']==job['id'])
            if done['status']!='pending':return done
            time.sleep(.1)
        self.fail('mock generation did not finish')

    def test_human_chooses_the_director_model(self):
        with self.assertRaises(APIError):self.call('PUT','roles',{'director':{'model':'claude-opus-5-5'}})  # no human words
        roles=self.roles()
        self.assertEqual(roles['director']['model'],'claude-opus-5-5');self.assertEqual(roles['source'],'agent_relay')
        with self.assertRaises(APIError) as error:self.take('no-identity-1',agent=None)
        self.assertEqual(error.exception.code,'director_identity_required')
        with self.assertRaises(APIError) as error:self.take('wrong-model-1',agent={'model':'gpt-5','session_id':'s1'})
        self.assertEqual(error.exception.code,'wrong_director_model')
        job=self.take('right-model-1')
        self.assertEqual(job['agent_identity'],DIRECTOR)

    def test_packet_has_frames_story_and_taste_but_no_director_reasoning(self):
        self.roles();job=self.take('packet-1')
        packet=self.call('GET',f"jobs/{job['id']}/review-packet")
        self.assertEqual(set(packet),{'job_id','job_status','error','brief','story','references','frames','contact_sheet_url',
                                      'human_taste','past_disagreements','required_reviewer','director','submit'})
        self.assertIn('STORY BEAT',packet['brief']);self.assertEqual(packet['required_reviewer']['model'],'gpt-review-1')
        self.assertEqual(len(packet['frames']),12);self.assertTrue(packet['contact_sheet_url'].startswith('/agent/v1/jobs/'))
        sheet=self.call('GET',packet['contact_sheet_url'].removeprefix('/agent/v1/'))
        self.assertEqual(sheet[1],'image/jpeg');self.assertTrue(sheet[0].startswith(b'\xff\xd8'))
        with self.assertRaises(APIError):self.call('GET',f"jobs/{job['id']}/review-frames/../../agent-token")

    def test_review_rules_and_code_computed_suggestion(self):
        self.roles();job=self.take('review-1');route=f"jobs/{job['id']}/ai-review"
        for bad,code in (({**GOOD,'reviewer':{'model':'other-model','session_id':'x1'}},'wrong_reviewer_model'),
                         ({**GOOD,'reviewer':{'model':'gpt-review-1','session_id':'director-session-1'}},'reviewer_not_independent'),
                         ({**GOOD,'scores':{'story':8}},'invalid_review'),({**GOOD,'frames_examined':0},'invalid_review'),
                         ({**GOOD,'issues':[{'severity':'meh','category':'craft','problem':'x'}]},'invalid_review'),
                         ({**GOOD,'verdict':'keep'},'invalid_review')):
            with self.assertRaises(APIError,msg=code) as error:self.call('POST',route,bad)
            self.assertEqual(error.exception.code,code)
        reviewed=self.call('POST',route,{**GOOD,'issues':[{'severity':'blocking','category':'anatomy','time_s':2.1,'problem':'Hand merges with the cup.','fix':'Keep the cup in her left hand, fingers visible.'}]})
        self.assertEqual(reviewed['ai_review']['suggestion'],'retry')
        with self.assertRaises(APIError) as error:self.call('POST',route,GOOD)
        self.assertEqual(error.exception.code,'review_exists')
        self.assertEqual(self.app.director_review.suggestion({'story':4,'identity':9,'craft':9,'performance':9},[]),'reject')
        self.assertEqual(self.app.director_review.suggestion({'story':8,'identity':9,'craft':5,'performance':9},[]),'retry')
        self.assertEqual(self.app.director_review.suggestion({'story':8,'identity':9,'craft':7,'performance':6},[{'severity':'polish'}]),'keep')

    def test_relayed_verdict_waits_for_the_review_and_agreement_is_tracked(self):
        self.roles()
        first=self.take('agreement-1')
        with self.assertRaises(APIError) as error:self.call('POST',f"jobs/{first['id']}/human-review",{'verdict':'keep','human_words':'Keep.'})
        self.assertEqual(error.exception.code,'ai_review_required')
        self.call('POST',f"jobs/{first['id']}/ai-review",GOOD)
        self.call('POST',f"jobs/{first['id']}/human-review",{'verdict':'keep','human_words':'Keep.'})
        second=self.take('agreement-2',text='nods.')
        self.call('POST',f"jobs/{second['id']}/ai-review",{'unavailable':True,'reason':'Codex usage limit reached.'})
        self.call('POST',f"jobs/{second['id']}/human-review",{'verdict':'retry','human_words':'Slower.'})
        third=self.take('agreement-3',text='turns.')
        self.call('POST',f"jobs/{third['id']}/ai-review",{**GOOD,'reviewer':{'model':'gpt-review-1','session_id':'reviewer-session-3'}})
        self.call('POST',f"jobs/{third['id']}/human-review",{'verdict':'reject','human_words':'Too stiff, rethink it.'})
        agreement=self.call('GET','reviewer/agreement')
        self.assertEqual((agreement['compared'],agreement['agreed'],agreement['ai_looser']),(2,1,1))
        self.assertEqual(agreement['by_reviewer_model'],{'gpt-review-1':{'compared':2,'agreed':1}})
        self.assertEqual(agreement['recent_disagreements'][0]['human_words'],'Too stiff, rethink it.')
        # The next review packet carries that disagreement so the reviewer learns this human's taste.
        fourth=self.take('agreement-4',text='sits.')
        packet=self.call('GET',f"jobs/{fourth['id']}/review-packet")
        self.assertEqual(packet['past_disagreements'][0]['human_words'],'Too stiff, rethink it.')
        self.assertIn('Too stiff, rethink it.',[t['human_words'] for t in packet['human_taste']])

    def test_without_chosen_roles_nothing_changes(self):
        job=self.take('no-roles-1',agent=None)
        self.assertIsNone(job['agent_identity'])
        self.call('POST',f"jobs/{job['id']}/human-review",{'verdict':'keep','human_words':'Good.'})

class DirectorReviewBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),studio.StudioHandler);self.server.tester=self.app
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def browser(self,path,data=None,raw=False):
        request=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
            headers={'Origin':self.base,'X-Tester':'local','Content-Type':'application/json'},method='GET' if data is None else 'POST')
        with urlopen(request) as response:body=response.read();return body if raw else json.loads(body)
    def test_roles_packet_frames_and_agreement_in_the_browser(self):
        roles=self.browser('/api/roles',{'director':{'model':'gpt-5-codex','product':'Codex'},'reviewer':{'model':'claude-opus-5-5','product':'Claude Code'}})
        self.assertEqual(roles['source'],'browser');self.assertEqual(self.browser('/api/roles'),self.app.director_review.get_roles())
        self.app.update(signed_in=True)
        with patch('httpx.Client'):
            identity=self.app.start_video(request(),True)
            for _ in range(50):
                if next(j for j in self.app.records() if j['id']==identity)['status']!='pending':break
                time.sleep(.1)
        packet=self.browser(f'/api/jobs/{identity}/review-packet')
        self.assertTrue(packet['contact_sheet_url'].startswith('/api/jobs/'))
        self.assertTrue(self.browser(packet['contact_sheet_url'],raw=True).startswith(b'\xff\xd8'))
        self.assertEqual(self.browser('/api/reviewer-agreement'),self.app.director_review.agreement())

if __name__=='__main__':unittest.main()
