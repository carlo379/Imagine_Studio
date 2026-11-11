import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import studio_server as studio
from agent_api import APIError
from test_studio import PNG

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name);self.api=self.app.agent
        asset=self.app.upload({'name':'view.png','data_url':PNG})
        self.call('POST','references',{'title':'SampleHero','handle':'SampleHero','category':'Character','description':'A robot.','images':[{'asset_id':asset['id']}]})
        self.app.update(signed_in=True)
        self.network=patch('httpx.Client');self.network.start()
    def tearDown(self):self.network.stop();self.temp.cleanup()
    def call(self,method,path,data=None,key=None):return self.api.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def scene(self,text,end_state=None):
        scene=self.call('POST','scenes',{'title':text,'scene':{'prompt':'@SampleHero '+text},'named_references':['SampleHero']})
        return self.kit(scene,end_state)
    def kit(self,scene,end_state=None):
        upload=lambda name:self.app.upload({'name':name,'data_url':PNG})['id']
        staging,first=upload('staging.png'),upload('first.png')
        changes={'first':{'asset_id':first}}
        if end_state:changes['last']={'asset_id':upload('last.png')}
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':changes})
        self.call('PUT',f"scenes/{scene['id']}/kit",{'expected_revision':scene['revision'],'camera':'Medium shot, locked camera.',
            'action':'She acts.','complex_action':False,'staging_asset_id':staging,**({'end_state':end_state,'last_frame_from_first':True} if end_state else {'free_motion':True})})
        return self.fresh(scene)
    def fresh(self,scene):return self.call('GET','scenes/'+scene['id'])
    def generate(self,scene,plan,key):
        scene=self.fresh(scene)
        job=self.call('POST',f"scenes/{scene['id']}/generate",{'expected_revision':scene['revision'],'plan_id':plan['id']},key)
        for _ in range(50):
            done=next(j for j in self.app.records() if j['id']==job['id'])
            if done['status']!='pending':return done
            time.sleep(.1)
        self.fail('mock generation did not finish')
    def verdict(self,job,verdict,words):
        return self.call('POST',f"jobs/{job['id']}/human-review",{'verdict':verdict,'human_words':words,'notes':words})
    def edit(self,scene,text):
        scene=self.fresh(scene);return self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':{'prompt':'@SampleHero '+text}})
    def plan(self,*scenes,**budget):
        return self.call('POST','plans',{'title':'Episode 1','items':[{'scene_id':s['id']} for s in scenes],**({'budget':budget} if budget else {})})
    def approve(self,plan,words='Looks good, go ahead.'):
        return self.call('POST',f"plans/{plan['id']}/approve",{'expected_revision':self.call('GET','plans/'+plan['id'])['revision'],'human_words':words})

    def test_plan_must_be_approved_then_replaces_per_take_approval(self):
        a=self.scene('waves.');plan=self.plan(a)
        self.assertEqual(plan['status'],'draft');self.assertFalse(plan['approved'])
        with self.assertRaises(APIError) as error:self.generate(a,plan,'plan-not-approved')
        self.assertEqual(error.exception.code,'plan_not_approved')
        with self.assertRaises(APIError):self.call('POST',f"plans/{plan['id']}/approve",{'expected_revision':plan['revision']})  # no human words
        approved=self.approve(plan)
        self.assertTrue(approved['approved']);self.assertEqual(approved['approval']['human_words'],'Looks good, go ahead.')
        job=self.generate(a,plan,'plan-take-one')
        self.assertEqual(job['plan'],{'id':plan['id'],'item':a['id']})
        # The review pause still applies under a plan.
        with self.assertRaises(APIError) as error:self.generate(a,plan,'plan-take-two')
        self.assertEqual(error.exception.code,'human_review_required')
        self.verdict(job,'keep','Perfect.')
        with self.assertRaises(APIError) as error:self.generate(a,plan,'plan-take-three')
        self.assertEqual(error.exception.code,'plan_item_done')
        view=self.call('GET','plans/'+plan['id'])
        self.assertEqual(view['items'][0]['state'],'kept');self.assertEqual(view['totals']['shots_kept'],1)

    def test_retry_allows_a_changed_take_but_reject_needs_approval_again(self):
        a=self.scene('waves.');plan=self.plan(a);self.approve(plan)
        first=self.generate(a,plan,'retry-take-one');self.verdict(first,'retry','She smiles too early.')
        self.edit(a,'waves, then smiles after the line.')
        second=self.generate(a,plan,'retry-take-two');self.verdict(second,'reject','The whole idea is wrong.')
        self.edit(a,'walks through the door instead.')
        with self.assertRaises(APIError) as error:self.generate(a,plan,'reject-take-three')
        self.assertEqual(error.exception.code,'plan_scene_changed')
        self.approve(plan,'Yes, the door idea is better.')
        third=self.generate(a,plan,'reject-take-three')
        self.assertEqual(self.call('GET','plans/'+plan['id'])['items'][0]['takes_used'],3)
        self.assertEqual(third['plan']['item'],a['id'])

    def test_changing_a_shot_without_a_retry_verdict_is_refused(self):
        a=self.scene('waves.');plan=self.plan(a);self.approve(plan)
        self.edit(a,'jumps.')
        with self.assertRaises(APIError) as error:self.generate(a,plan,'silent-change')
        self.assertEqual(error.exception.code,'plan_scene_changed')

    def test_scope_limits_edits_and_close(self):
        a=self.scene('waves.');b=self.scene('nods.');c=self.scene('runs.')
        plan=self.plan(a,b,max_takes=2);plan=self.approve(plan)
        with self.assertRaises(APIError) as error:self.generate(c,plan,'not-in-plan')
        self.assertEqual(error.exception.code,'not_in_plan')
        # Per-shot limit (default 2).
        one=self.generate(a,plan,'limit-a-one');self.verdict(one,'retry','Again.')
        two=self.generate(a,plan,'limit-a-two');self.verdict(two,'retry','Again.')
        with self.assertRaises(APIError) as error:self.generate(a,plan,'limit-a-three')
        self.assertIn(error.exception.code,('plan_takes_exhausted','plan_budget_exceeded'))
        # Plan-wide limit of 2 takes is used up too.
        with self.assertRaises(APIError) as error:self.generate(b,plan,'limit-b-one')
        self.assertEqual(error.exception.code,'plan_budget_exceeded')
        # Any change to the plan clears its approval.
        view=self.call('GET','plans/'+plan['id'])
        edited=self.call('PUT','plans/'+plan['id'],{'expected_revision':view['revision'],'budget':{'max_takes':5}})
        self.assertEqual(edited['status'],'draft');self.assertIsNone(edited['approval'])
        with self.assertRaises(APIError) as error:self.generate(b,plan,'limit-b-two')
        self.assertEqual(error.exception.code,'plan_not_approved')
        renamed=self.call('PUT','plans/'+plan['id'],{'expected_revision':edited['revision'],'title':'Renamed'})
        self.assertEqual(renamed['status'],'draft')
        approved=self.approve(plan)
        retitled=self.call('PUT','plans/'+plan['id'],{'expected_revision':approved['revision'],'title':'Episode 1, final'})
        self.assertTrue(retitled['approved'],'a title-only edit keeps the approval')
        closed=self.call('POST',f"plans/{plan['id']}/close",{'expected_revision':retitled['revision']})
        self.assertEqual(closed['status'],'closed')
        with self.assertRaises(APIError) as error:self.generate(b,plan,'after-close')
        self.assertEqual(error.exception.code,'plan_closed')

    def test_invalid_plans_are_refused(self):
        a=self.scene('waves.')
        for bad in ({'title':'x','items':[]},{'title':'','items':[{'scene_id':a['id']}]},
                    {'title':'x','items':[{'scene_id':'missing'}]},{'title':'x','items':[{'scene_id':a['id']},{'scene_id':a['id']}]},
                    {'title':'x','items':[{'scene_id':a['id'],'max_takes':9}]},{'title':'x','items':[{'scene_id':a['id']}],'budget':{'usage_percent':0}},
                    {'title':'x','items':[{'scene_id':a['id']}],'budget':{'dollars':5}}):
            with self.assertRaises(APIError,msg=bad):self.call('POST','plans',bad)

    def test_usage_cap_uses_learned_costs_and_readings(self):
        a=self.scene('waves.');b=self.scene('nods.')
        plan=self.approve(self.plan(a,b,usage_percent=3))
        rates={'resolutions':{'480p':{'established':True,'percent_per_second':0.4},'720p':{'established':False,'percent_per_second':None},
                              '1080p':{'established':False,'percent_per_second':None}},'samples':[]}
        duration=self.fresh(a)['scene']['duration']
        view=None
        with patch.object(self.app,'usage_calibration',return_value=rates):
            view=self.call('GET','plans/'+plan['id'])
            self.assertAlmostEqual(view['totals']['estimate_percent_expected'],round(0.4*duration*2,2))
            # A live take whose readings show it used 2.5% leaves too little for the next one.
            self.app.history.insert(0,{'id':'live1','created_at':time.time(),'mock':False,'status':'done','plan':{'id':plan['id'],'item':a['id']},
                'settings':{'resolution':'480p','duration':duration},'usage':{'before':10,'after':12.5},'human_review':{'status':'reviewed','verdict':'keep'}})
            with patch.object(self.app,'mock',False):
                with self.assertRaises(APIError) as error:self.app.plans.authorize(plan['id'],self.fresh(b))
            self.assertEqual(error.exception.code,'plan_budget_exceeded');self.assertIn('3%',str(error.exception))
            self.assertEqual(self.call('GET','plans/'+plan['id'])['totals']['usage_percent_spent'],2.5)

class PlanBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),studio.StudioHandler);self.server.tester=self.app
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def browser(self,path,data=None):
        request=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
            headers={'Origin':self.base,'X-Tester':'local','Content-Type':'application/json'},method='GET' if data is None else 'POST')
        with urlopen(request) as response:return json.loads(response.read())
    def test_human_approves_and_closes_in_the_browser(self):
        agent=lambda method,path,data:self.app.agent.dispatch(method,'/agent/v1/'+path,data,None)[1]
        scene=agent('POST','scenes',{'title':'Shot','scene':{'prompt':'A slow orbit.'}})
        upload=lambda:self.app.upload({'name':'f.png','data_url':PNG})['id']
        scene=agent('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':{'first':{'asset_id':upload()}}})
        with self.assertRaises(HTTPError) as error:
            self.browser(f"/api/scenes/{scene['id']}/kit",{'expected_revision':scene['revision'],'end_state':'Ends still.','free_motion':True})
        self.assertEqual(error.exception.code,400);error.exception.close()
        kit=self.browser(f"/api/scenes/{scene['id']}/kit",{'expected_revision':scene['revision'],'camera':'Slow orbit, wide.','action':'The camera circles the tower.','complex_action':False,
                                                           'free_motion':True,'staging_asset_id':upload()})
        self.assertTrue(kit['ready'],kit['missing']);self.assertEqual(self.browser(f"/api/scenes/{scene['id']}/kit"),kit)
        plan=self.app.agent.dispatch('POST','/agent/v1/plans',{'title':'Episode','items':[{'scene_id':scene['id']}]},None)[1]
        self.assertEqual(self.browser('/api/plans')[0]['id'],plan['id'])
        with self.assertRaises(HTTPError) as error:self.browser(f"/api/plans/{plan['id']}/approve",{'expected_revision':plan['revision'],'human_words':'x'})
        self.assertEqual(error.exception.code,400);error.exception.close()
        with self.assertRaises(HTTPError) as error:self.browser(f"/api/plans/{plan['id']}/approve",{'expected_revision':99})
        self.assertEqual(error.exception.code,409);error.exception.close()
        approved=self.browser(f"/api/plans/{plan['id']}/approve",{'expected_revision':plan['revision']})
        self.assertTrue(approved['approved']);self.assertEqual(approved['approval']['source'],'browser')
        self.assertEqual(self.browser('/api/plans/'+plan['id']),self.app.agent.dispatch('GET','/agent/v1/plans/'+plan['id'],{},None)[1])
        closed=self.browser(f"/api/plans/{plan['id']}/close",{'expected_revision':approved['revision']})
        self.assertEqual(closed['status'],'closed')

if __name__=='__main__':unittest.main()
