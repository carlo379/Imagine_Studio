import copy
import tempfile
import time
import unittest
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError


class CandidateReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.p=self.app.productions;self.s=self.app.filmmaking.series;self.w=self.app.filmmaking.workshop
        self.pid=self.p.dispatch('POST',[],dict(kind='story',title='Review series'))[1]['production']['id']
        bible=self.s.save_bible(self.pid,dict(expected_revision=0,answers=dict(style='Stylized 3D'),guide=dict(cast=[dict(id='hero',name='Hero',description='A gold robot.')],places=[dict(id='lab',name='Lab',description='A green workshop.')],props=[dict(id='tool',name='Tool',description='A bronze wrench.')])) )
        self.snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=bible['revision']))
    def tearDown(self):
        self.p.sql.close();self.tmp.cleanup()
    def candidate(self,category):
        e=next(e for e in self.snapshot['entities'] if e['category']==category)
        v=next(v for v in self.snapshot['views'] if v['entity_id']==e['id'])
        draft=self.app.images.draft(v['draft_id'])
        with patch('httpx.Client') as http:
            job=self.app.images.generate(draft['id'],dict(expected_revision=draft['revision'],approved=True),'candidate-'+category)
            deadline=time.monotonic()+3
            while job['status']=='pending' and time.monotonic()<deadline:
                time.sleep(.02);job=self.app.images.job(job['id'])
            http.assert_not_called()
        self.assertEqual(job['status'],'done')
        return v,job['outputs'][0],job
    def review(self,v,o,action,reason=''):
        view=self.p.get(v['id'],'world-asset');asset,_=self.app.asset(o['id'])
        return self.app.agent.dispatch('POST','/agent/v1/filmmaking/assets/'+v['id']+'/review',dict(expected_revision=view['revision'],expected_review_revision=asset.get('review_revision',0),asset_id=o['id'],action=action,reason=reason),None)[1]
    def test_all_categories_reject_trash_restore_and_approve_without_paid_calls(self):
        for category in ('Character','Location','Prop'):
            with self.subTest(category=category):
                v,o,job=self.candidate(category);_,path=self.app.asset(o['id']);raw=path.read_bytes()
                with patch.object(self.app,'spawn') as spawn:
                    self.review(v,o,'reject','Wrong style: too realistic')
                    self.assertNotIn(o['id'],[a['id'] for a in self.app.library()])
                    self.assertEqual(self.app.asset(o['id'])[0]['review_state'],'rejected')
                    with self.assertRaises(APIError):self.app.agent.source({'asset_id':o['id']})
                    with self.assertRaises(APIError):self.w.confirm(v['id'],dict(expected_revision=self.p.get(v['id'],'world-asset')['revision'],asset_id=o['id'],approved=True))
                    with self.assertRaises(APIError):self.app.images.dispatch('POST',['jobs',job['id'],'approve'],dict(asset_id=o['id'],approved=True),None)
                    self.review(v,o,'trash')
                    with self.assertRaises(APIError):self.review(v,o,'trash')
                    self.review(v,o,'restore')
                    self.assertEqual(self.app.asset(o['id'])[0]['review_state'],'rejected','Restore from Trash preserves rejection')
                    self.review(v,o,'restore')
                    self.assertEqual(self.app.asset(o['id'])[0]['review_state'],'candidate')
                    self.assertFalse(self.app.asset(o['id'])[0]['approved'])
                    self.assertIn(o['id'],[a['id'] for a in self.app.library()])
                    self.w.confirm(v['id'],dict(expected_revision=self.p.get(v['id'],'world-asset')['revision'],asset_id=o['id'],approved=True))
                    self.assertEqual(self.app.asset(o['id'])[0]['review_state'],'approved')
                    spawn.assert_not_called()
                self.assertEqual(path.read_bytes(),raw)
    def test_selected_reference_cannot_be_removed_or_unapproved(self):
        v,o,job=self.candidate('Character')
        self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=o['id'],approved=True))
        before=copy.deepcopy(self.app.assets)
        for action in ('reject','trash'):
            result=self.review(v,o,action)
            self.assertGreater(result['review_blocked']['count'],0)
            self.assertTrue(any(d['kind']=='Reference' for d in result['review_blocked']['dependencies']))
            self.assertEqual(self.app.assets,before)
        with self.assertRaises(APIError):self.app.images.dispatch('POST',['jobs',job['id'],'approve'],dict(asset_id=o['id'],approved=False),None)
    def test_draft_and_episode_snapshots_are_protected(self):
        v,o,_=self.candidate('Location')
        self.app.images.create(dict(title='Saved scene',settings=dict(prompt='A scene.',base={'asset_id':o['id']})))
        result=self.review(v,o,'trash');self.assertTrue(any(d['kind']=='Image draft' for d in result['review_blocked']['dependencies']))
        v,o,_=self.candidate('Prop')
        with self.p.sql:self.p.new('episode-book',title='Episode foundation',inheritance=dict(assets=[dict(identity_asset_id=o['id'])]))
        result=self.review(v,o,'reject');self.assertNotIn('review_blocked',result);self.assertTrue(any(d['kind']=='Episode Book' for d in result['review_preserved']['dependencies']))
    def test_clear_then_reject_preserves_references_and_request_history(self):
        for category in ('Character','Location','Prop'):
            with self.subTest(category=category):
                v,o,job=self.candidate(category)
                self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=o['id'],approved=True))
                entity=self.w.entity(v['entity_id']);ref_id=entity['reference_id']
                reference_before=copy.deepcopy(next(r for r in self.app.references if r['id']==ref_id))
                snapshot=copy.deepcopy(job);snapshot.update(id='old-'+category)
                snapshot['draft']['settings']['extras']=[{'asset_id':o['id']}]
                self.app.images.db['jobs'].append(snapshot)
                historical_settings=copy.deepcopy(snapshot['draft']['settings'])
                self.w.clear_approval(entity['id'],dict(expected_revision=entity['revision']))
                asset,path=self.app.asset(o['id']);raw=path.read_bytes()
                self.assertFalse(asset['approved']);self.assertEqual(asset['review_state'],'candidate')
                self.assertFalse(self.app.images.job(job['id'])['outputs'][0]['approved'])
                self.assertTrue(self.app.asset_studio.get(ref_id)['needs_replacement'])
                with patch.object(self.app,'spawn') as spawn:
                    result=self.review(v,o,'reject','Wrong style');spawn.assert_not_called()
                self.assertNotIn('review_blocked',result)
                self.assertTrue(any(d['kind']=='Image request snapshot' for d in result['review_preserved']['dependencies']))
                self.assertEqual(self.app.asset(o['id'])[0]['review_state'],'rejected')
                self.assertEqual(snapshot['draft']['settings'],historical_settings)
                self.assertEqual(next(r for r in self.app.references if r['id']==ref_id),reference_before)
                self.assertEqual(path.read_bytes(),raw)
                with self.assertRaises(APIError):self.app.agent.source({'asset_id':o['id']})
                self.assertIn('review_blocked',self.review(v,o,'trash'))
                self.review(v,o,'restore')
                self.assertEqual(self.app.asset(o['id'])[0]['review_state'],'candidate')

    def test_restore_survives_restart_and_files_are_never_deleted(self):
        v,o,_=self.candidate('Character');self.review(v,o,'reject','Wrong appearance');self.review(v,o,'trash')
        self.p.sql.close();self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.w=self.app.filmmaking.workshop
        self.assertEqual(self.w.view(self.p.get(v['id'],'world-asset'))['outputs'][0]['review_state'],'trashed')
        self.review(v,o,'restore');asset,path=self.app.asset(o['id'])
        self.assertEqual(asset['review_state'],'rejected');self.assertEqual(asset['review_reason'],'Wrong appearance');self.assertTrue(path.exists())
        self.review(v,o,'restore');self.assertIn(o['id'],[a['id'] for a in self.app.library()])
    def test_stale_and_foreign_review_actions_are_rejected(self):
        v,o,_=self.candidate('Character');_,other,_=self.candidate('Location')
        for data in (dict(asset_id=o['id'],expected_revision=0,expected_review_revision=0),dict(asset_id=o['id'],expected_revision=v['revision'],expected_review_revision=99),dict(asset_id=other['id'],expected_revision=v['revision'],expected_review_revision=0)):
            with self.assertRaises(APIError):self.app.agent.dispatch('POST','/agent/v1/filmmaking/assets/'+v['id']+'/review',{**data,'action':'trash'},None)
        self.assertNotIn('review_state',self.app.asset(o['id'])[0])
