import copy
import tempfile
import time
import unittest
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError
from provider_usage import observe
from workflow_tools import usage

class WorkshopFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.p=self.app.productions;self.s=self.app.filmmaking.series;self.w=self.app.filmmaking.workshop
        self.production=self.p.dispatch('POST',[],dict(kind='story',title='Annie'))[1]['production'];self.pid=self.production['id']
        self.bible=self.s.save_bible(self.pid,dict(expected_revision=0,guide=dict(cast=[dict(id='annie',name='Annie',hair='Brown',clothing='Blue jacket')]),answers=dict(style='Illustration')))
        self.snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=self.bible['revision']))
        self.e=self.snapshot['entities'][0];self.v=self.snapshot['views'][0];self.job=self.snapshot['job']
    def tearDown(self):self.p.sql.close();self.tmp.cleanup()
    def route(self,path,data=None,key=None,method='POST'):
        return self.app.agent.dispatch(method,'/agent/v1/filmmaking/'+path,data or {},key)[1]
    def payload(self):return dict(job_id=self.job['id'],model='gpt-image-2',approved=True,requests=[dict(view_id=self.v['id'],expected_revision=self.v['revision'],prompt='Draw Annie with exactly four views: front, side, back and head close-up.',reviewed=True,authored_by='agent')])
    def candidate(self):
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            batch=self.route('series/'+self.pid+'/generate',self.payload(),'annie-four-views')
        self.assertEqual(self.p.get(batch['id'],'world-render')['status'],'done')
        view=self.w.snapshot(self.pid,self.job['id'])['views'][0];return view,view['outputs'][0]
    def preview(self,view,image):
        return self.route('assets/'+view['id']+'/bible-change-preview',dict(expected_revision=view['revision'],expected_entity_revision=self.w.entity(self.e['id'])['revision'],asset_id=image['id'],changes=dict(hair='Red')))
    def test_own_prompt_full_workshop_confirm_and_replay(self):
        v,image=self.candidate();self.assertEqual(v['draft']['settings']['prompt'],self.payload()['requests'][0]['prompt'])
        self.assertTrue(v['draft']['prompt_preparation_current']);self.assertEqual(v['draft']['manual_prompt_review']['authored_by'],'agent')
        self.assertEqual(self.app.images.db['jobs'][0]['prompt_review_provenance']['authored_by'],'agent')
        self.assertNotIn('Character sheet',image['name'])
        self.route('assets/'+v['id']+'/confirm',dict(expected_revision=v['revision'],asset_id=image['id'],approved=True,image_layout='character_sheet'))
        self.assertEqual(self.app.asset(image['id'])[0]['name'],'Annie · Character sheet.png')
        self.assertEqual(self.w.entity(self.e['id'])['identity_asset_id'],image['id']);self.assertEqual(self.s.bible(self.pid)['guide'],self.bible['guide'])
        self.route('series/'+self.pid+'/generate',self.payload(),'annie-four-views');self.assertEqual(len(self.app.images.db['jobs']),1)
    def test_live_custom_prompt_needs_review_approval_and_key(self):
        self.app.mock=False;j=self.p.get(self.job['id'],'world-job');j['mock']=False;self.p.put('world-job',j)
        with patch.dict(self.app.agent.config,live_generations_enabled=True),patch.object(self.app.images,'account_status',return_value={'subscription':{'signed_in':True}}),patch.object(self.app,'spawn'):
            missing=self.payload();missing['requests'][0].pop('reviewed')
            with self.assertRaises(APIError) as error:self.route('series/'+self.pid+'/generate',missing,'unreviewed-prompt')
            self.assertEqual(error.exception.code,'prompt_review_required')
            no_approval=self.payload();no_approval['approved']=False
            with self.assertRaises(APIError):self.route('series/'+self.pid+'/generate',no_approval,'no-approval-prompt')
            with self.assertRaises(APIError):self.route('series/'+self.pid+'/generate',self.payload(),None)
            self.route('series/'+self.pid+'/generate',self.payload(),'live-own-prompt')
            draft=self.app.images.draft(self.v['draft_id']);self.assertEqual(draft['manual_review_revision'],draft['revision'])
            job=self.app.images.generate(draft['id'],dict(expected_revision=draft['revision'],approved=True),'live-worker-step')
            self.assertEqual(job['draft']['settings']['prompt'],self.payload()['requests'][0]['prompt'])
        self.assertFalse(self.p.all('media-prompt-job'))
    def test_manual_review_survives_render_settings_but_not_text(self):
        d=self.app.images.draft(self.v['draft_id'])
        d=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings={**d['settings'],'prompt':'Reviewed front view'}))
        self.app.images.dispatch('POST',['drafts',d['id'],'review-prompt'],dict(expected_revision=d['revision'],reviewed=True,authored_by='agent'),None)
        d=self.app.images.draft(d['id']);d=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings={**d['settings'],'model':'grok-imagine-image-2.0','quality':'auto','resolution':'1k','n':2}))
        self.assertEqual(d['manual_review_revision'],d['revision'])
        prepared=self.w.prompt_draft(self.v['id'],dict(expected_revision=self.v['revision'],model='gpt-image-2'))
        self.assertTrue(prepared['current']);self.assertEqual(prepared['draft']['settings']['prompt'],'Reviewed front view')
        d=self.app.images.draft(d['id']);d=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings={**d['settings'],'prompt':'Changed'}));self.assertNotEqual(d['manual_review_revision'],d['revision'])
    def test_bible_preview_no_changes_until_confirm_then_audit(self):
        v,image=self.candidate();before=copy.deepcopy(self.s.bible(self.pid));proposal=self.preview(v,image)
        self.assertEqual(self.s.bible(self.pid),before);self.assertEqual(proposal['diff'][0]['before'],'Brown')
        with self.assertRaises(APIError):self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id']))
        result=self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id'],approved=True,authored_by='agent'))
        self.assertEqual(result['entities'][0]['profile']['hair'],'Red')
        bible=self.s.bible(self.pid);self.assertEqual(bible['guide']['cast'][0]['hair'],'Red');self.assertEqual(bible['image_change_history'][0]['source'],'image');self.assertEqual(bible['image_change_history'][0]['asset_id'],image['id'])
        self.assertEqual(self.w.entity(self.e['id'])['identity_asset_id'],image['id'])
        again=self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id'],approved=True));self.assertEqual(again,result)
        saved=self.s.save_bible(self.pid,dict(expected_revision=bible['revision'],answers={**bible['answers'],'theme':'A new theme'}))
        self.assertEqual(saved['image_change_history'],bible['image_change_history'])
        self.assertEqual(self.p.get(proposal['id'],'image-bible-preview')['confirmation']['source'],'image')
    def test_bible_preview_rejects_stale_bible(self):
        v,image=self.candidate();proposal=self.preview(v,image)
        b=self.s.bible(self.pid);self.s.save_bible(self.pid,dict(expected_revision=b['revision'],answers={**b['answers'],'style':'Changed style'}))
        with self.assertRaises(APIError) as error:self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id'],approved=True))
        self.assertEqual(error.exception.code,'revision_conflict');self.assertIsNone(self.w.entity(self.e['id'])['identity_asset_id'])
    def test_bible_confirm_failure_rolls_back_approval_bible_and_metadata(self):
        v,image=self.candidate();proposal=self.preview(v,image)
        before=self.w.entity(self.e['id']);bible=self.s.bible(self.pid)
        with patch.object(self.app.asset_studio,'dispatch',side_effect=RuntimeError('simulated storage failure')):
            with self.assertRaises(RuntimeError):self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id'],approved=True))
        self.assertEqual(self.w.entity(self.e['id']),before);self.assertEqual(self.s.bible(self.pid),bible)
        self.assertEqual(self.app.references,[]);self.assertFalse(self.app.asset(image['id'])[0]['approved'])
        self.assertFalse(self.app.images.db['jobs'][0]['outputs'][0]['approved'])
        self.assertEqual(self.p.get(proposal['id'],'image-bible-preview')['status'],'preview')
    def test_rejected_candidate_cannot_apply_bible_preview(self):
        v,image=self.candidate();proposal=self.preview(v,image)
        self.route('assets/'+v['id']+'/review',dict(expected_revision=v['revision'],expected_review_revision=image['review_revision'],asset_id=image['id'],action='reject',reason='Wrong hair'))
        with self.assertRaises(APIError):self.route('assets/'+v['id']+'/bible-change-confirm',dict(preview_id=proposal['id'],approved=True))
        self.assertEqual(self.s.bible(self.pid)['guide']['cast'][0]['hair'],'Brown')
    def test_series_and_production_ids_resolve_and_replay_identically(self):
        sid=self.production['series_id']
        for action in ('bible','library','workshop'):
            self.assertEqual(self.route('series/'+sid+'/'+action,method='GET'),self.route('series/'+self.pid+'/'+action,method='GET'))
        with patch.object(self.app,'spawn'):
            first=self.route('series/'+sid+'/generate',self.payload(),'both-series-ids');second=self.route('series/'+self.pid+'/generate',self.payload(),'both-series-ids')
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['production_id'],self.pid)
    def test_four_view_template_and_single_image_name(self):
        prompt=self.v['draft']['settings']['prompt'];self.assertIn('exactly four',prompt);self.assertNotIn('full body three-quarter',prompt)
        v,image=self.candidate();self.route('assets/'+v['id']+'/confirm',dict(expected_revision=v['revision'],asset_id=image['id'],approved=True))
        self.assertEqual(self.app.asset(image['id'])[0]['name'],'Annie · Main image.png')
    def test_usage_is_observed_sanitized_and_not_a_balance(self):
        self.app.mock=False;self.assertEqual(usage(self.app)['providers']['grok_image']['remaining'],'unknown')
        response=type('Response',(),{'headers':{'x-ratelimit-remaining-requests':'12','x-ratelimit-reset-requests':'3s','Authorization':'Bearer secret','set-cookie':'secret'}})()
        observe(self.app,response,'grok_image');info=usage(self.app)['providers']['grok_image']
        self.assertFalse(info['balance_available']);self.assertEqual(info['rate_limit_observation']['rate_limits'],{'x-ratelimit-remaining-requests':'12','x-ratelimit-reset-requests':'3s'})
        self.assertLess(abs(info['rate_limit_observation']['observed_at']-time.time()),2);self.assertNotIn('secret',str(info));self.assertEqual(info['remaining'],'unknown')
        self.app.mock=True;self.assertIsNone(usage(self.app)['providers']['grok_image']['rate_limit_observation'])
