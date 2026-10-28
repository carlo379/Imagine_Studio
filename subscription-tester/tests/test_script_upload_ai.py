"""Invalid AI matches cannot block valid upload comparisons or write saved data."""
import copy
import tempfile
import unittest
from studio_server import Studio
from agent_api import APIError

class UploadAIReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.addCleanup(self.p.sql.close)
        self.s=self.app.filmmaking.series
        outline=self.p.dispatch('POST',[],dict(kind='story',title='Upload test'))[1]
        self.pid=outline['production']['id'];self.eid=outline['episodes'][0]['id']
        guide=dict(places=[dict(id='room',name='Room',time='Morning',lighting='Natural window light.')])
        self.s.save_bible(self.pid,dict(expected_revision=0,guide=guide))
        self.book=self.s.save_book(self.eid,dict(expected_revision=0,guide=guide))
        self.app.mock=False;self.s.writing_access=lambda provider:None;self.app.spawn=lambda fn,*args:fn(*args)
        self.ai=self.s.upload_review.ai;self.source='Lighting: Soft warm sunlight.\n\nTime of day: Late afternoon.'

    def response(self,context,all_invalid=False):
        unit=next(u for u in context['upload_units'] if 'Soft warm sunlight.' in u['text'])
        lighting=next(t for t in context['saved_details'] if t['kind']=='card' and t['field']=='lighting')
        time=next(t for t in context['saved_details'] if t['kind']=='card' and t['field']=='time')
        good=dict(unit_id=unit['id'],excerpt='Soft warm sunlight.',target_ids=lighting['ids'],relationship='conflict',confidence='high',reason='Lighting differs from the saved description.')
        mixed={**good,'target_ids':[lighting['ids'][0],time['ids'][0]]}
        invalid={**good,'excerpt':'This is not in the uploaded script.'}
        return dict(matches=[mixed,invalid] if all_invalid else [mixed,invalid,good],summary='Compared the lighting.')

    def review(self,all_invalid=False):
        self.app.filmmaking.request_plan=lambda provider,context,*args:self.response(context,all_invalid)
        return self.ai.start(self.eid,dict(text=self.source,expected_revision=self.book['revision'],approved=True),'upload-review-test')

    def test_mixed_fields_and_bad_excerpt_are_skipped_valid_match_survives(self):
        before=copy.deepcopy(self.s.bible(self.pid));result=self.review()
        self.assertEqual(result['status'],'done');review=result['result']
        self.assertEqual(review['source'],self.source);self.assertEqual(len(review['warnings']),2)
        self.assertIn('mixed unrelated',review['warnings'][0]['message'])
        self.assertEqual(len(review['comparisons']),1)
        match=review['comparisons'][0];self.assertEqual(match['field'],'lighting')
        self.assertTrue(all(t['field']=='lighting' for t in match['targets']))
        self.assertEqual(self.s.bible(self.pid),before)
        self.assertEqual(self.s.book(self.eid)['guide']['script'],'')
        with self.assertRaises(APIError):self.s.upload_review.apply(self.eid,dict(source=self.source,review_job_id=result['id'],review_token=review['review_token'],expected_revision=self.book['revision'],expected_episode_revision=self.book['episode']['revision'],choices={}))
        applied=self.s.upload_review.apply(self.eid,dict(source=self.source,review_job_id=result['id'],review_token=review['review_token'],expected_revision=self.book['revision'],expected_episode_revision=self.book['episode']['revision'],choices={match['id']:'both'}))
        self.assertEqual(applied['guide']['script'],self.source);self.assertEqual(self.s.bible(self.pid),before)

    def test_all_invalid_matches_allow_full_script_import_with_warning(self):
        result=self.review(True);self.assertEqual(result['status'],'done');review=result['result']
        self.assertEqual(review['comparisons'],[]);self.assertEqual(len(review['warnings']),2)
        applied=self.s.upload_review.apply(self.eid,dict(source=self.source,review_job_id=result['id'],review_token=review['review_token'],expected_revision=self.book['revision'],expected_episode_revision=self.book['episode']['revision'],choices={}))
        self.assertEqual(applied['guide']['script'],self.source)

    def test_partial_review_retains_narrative_protection_and_rejects_invalid_envelope(self):
        result=self.review();job=copy.deepcopy(self.ai.read(self.eid,result['id']))
        for unit in job['source_units']:unit['protected']=True
        review=self.ai.normalize(job,self.response(job['context']))
        self.assertTrue(review['comparisons'][0]['advisory_only'])
        self.assertEqual(len(review['warnings']),2)
        with self.assertRaises(ValueError):self.ai.normalize(job,{'matches':'invalid','summary':'No reliable review'})

if __name__=='__main__':unittest.main()
