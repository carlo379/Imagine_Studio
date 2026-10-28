"""Offline contracts: no live writer or video generation requests."""
import base64, copy, io, subprocess, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from studio_server import Studio
from agent_api import APIError
import prompt_guides
MODEL='grok-imagine-video-1.5'
class VideoReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.app=Studio(mock=True,storage=self.tmp.name)
  raw=io.BytesIO(); Image.new('RGB',(8,8),'black').save(raw,format='PNG')
  self.asset=self.app.upload(dict(name='Sheet.png',data_url='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()))
  self.app.save_reference(dict(title='SampleHero',handle='SampleHero2',category='Character',images=[{'asset_id':self.asset['id']}]))
  prod=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Review fixture'))[1]
  self.video=self.app.agent.record(prod['shots'][0]['video_id'])
  scene=self.app.agent.attach(copy.deepcopy(self.video['scene']),['SampleHero2'])
  scene.update(first=self.asset,prompt='@SampleHero2 turns. Mark says "You wore it!"',audio=True,duration=5,model=MODEL)
  self.video=self.app.agent.edit(self.video['id'],dict(expected_revision=self.video['revision'],scene=scene))
  self.app.mock=False; self.app.spawn=Mock(); self.app.filmmaking.series.writing_access=Mock()
  self.app.filmmaking.request_plan=Mock(side_effect=AssertionError('Unexpected writer request'))
  settings=self.app.agent.compile(scene); settings.update(_studio_scene=copy.deepcopy(scene),_studio_video_id=self.video['id'])
  self.job=dict(id=uuid.uuid4().hex,status='done',video='https://fixture.invalid/video',mock=False,settings=settings,returned_model=MODEL,model_identity='confirmed')
  self.service=self.app.video_review
  self.job['request_snapshot']=self.service.capture_submission(self.job,self.app.resolve(settings),settings)
  self.app.records=Mock(return_value=[self.job])
  self.evidence=dict(duration=5,audio_present=True,frames=[dict(id='frame-0',time_seconds=0),dict(id='frame-1',time_seconds=4)],references=[dict(id='input-1',attached=True,exact_pixels=True)])
 def tearDown(self):
  self.app.productions.sql.close(); self.tmp.cleanup()
 def start(self,key='review-fixture-01',**kwargs):
  return self.service.start(dict(video_job_id=self.job['id'],scene_id=self.video['id'],provider='codex',approved=True,**kwargs),key)
 def report(self):
  return dict(summary='Match in inspected frame.',overall='met',requirements=[dict(id='identity',requirement='Reference design at reveal',category='identity',status='met',observation='Visible silhouette matches sheet.',evidence_ids=['frame-1','input-1'],timestamps=[4],confidence='high')],hypotheses=[],revised_prompt=self.video['scene']['prompt'],changes=[],comparison=dict(summary='',improved_ids=[],regressed_ids=[],uncertain_ids=[]),lesson_candidates=[dict(finding_ids=['identity'],guidance='Bind the revealed character to its attached reference.',rationale='A visible match at reveal.')])
 def done(self):
  item=self.start(); review=self.service.get(item['id']); snapshot=self.service._read_snapshot(self.job,item['id'])
  context=prompt_guides.capture({},[dict(model=MODEL,fields=['revised_prompt'],operation='review')],app=self.app)
  review.update(status='done',snapshot=snapshot,evidence=copy.deepcopy(self.evidence),result=self.report(),provenance=prompt_guides.provenance(context)); return review
 def apply(self,review,**kwargs):
  record=self.app.agent.record(self.video['id'])
  return self.service.apply(review['id'],dict(approved=True,expected_scene_revision=record['revision'],expected_review_revision=review['revision'],**kwargs))
 def test_snapshot_private_and_tamper_checked(self):
  snapshot=self.service._read_snapshot(self.job,uuid.uuid4().hex)
  self.assertTrue(all(i['exact_pixels'] for i in snapshot['images']))
  public=self.service.public(dict(snapshot=snapshot))['snapshot']; self.assertNotIn('scene',public)
  self.assertTrue(all('path' not in i and 'url' not in i for i in public['images']))
  (Path(self.tmp.name)/self.job['request_snapshot']['path']).write_text('{}')
  with self.assertRaisesRegex(APIError,'missing or changed'): self.service._read_snapshot(self.job,uuid.uuid4().hex)
 def test_explicit_approval_idempotency_cache(self):
  with self.assertRaisesRegex(APIError,'explicitly'): self.service.start(dict(video_job_id=self.job['id'],scene_id=self.video['id']),'review-no-approval')
  first=self.start(); self.assertEqual(self.start()['id'],first['id']); self.assertEqual(self.start(key='review-another-key')['id'],first['id'])
  with self.assertRaisesRegex(APIError,'different inputs'): self.start(notes='changed')
  self.assertEqual(self.app.spawn.call_count,1); self.app.filmmaking.request_plan.assert_not_called()
 def test_explicit_standalone_overrides_origin(self):
  review=self.done(); self.app.agent.record(self.video['id'])['video_review_origin']=dict(review_id=review['id'])
  second=copy.deepcopy(self.job); second['id']=uuid.uuid4().hex
  second['request_snapshot']=self.service.capture_submission(second,self.app.resolve(second['settings']),second['settings']); self.app.records.return_value.append(second)
  result=self.service.start(dict(video_job_id=second['id'],scene_id=self.video['id'],approved=True,previous_review_id=None),'review-standalone')
  self.assertIsNone(result['previous_review_id'])
 def test_evidence_and_timestamps_are_grounded(self):
  review=self.done()
  for ids,times in [(['invented'],[4]),(['frame-1'],[2]),(['frame-1'],[float('nan')])]:
   result=self.report(); result['requirements'][0].update(evidence_ids=ids,timestamps=times)
   with self.assertRaises(APIError): self.service.validate_result(result,review,review['snapshot'],self.evidence)
 def test_uncertain_temporal_audio_and_legacy_claims(self):
  review=self.done()
  for category,requirement in [('action','Maintain contact throughout the step'),('dialogue','Exact spoken line'),('camera','Slow push')]:
   result=self.report(); result['requirements'][0].update(category=category,requirement=requirement)
   self.assertEqual(self.service.validate_result(result,review,review['snapshot'],self.evidence)['overall'],'uncertain')
  snapshot=copy.deepcopy(review['snapshot']); snapshot['source']='reconstructed'
  self.assertEqual(self.service.validate_result(self.report(),review,snapshot,self.evidence)['overall'],'uncertain')
 def test_missing_requested_audio(self):
  review=self.done(); result=self.report(); result['requirements'][0].update(category='audio',status='failed'); evidence=dict(self.evidence,audio_present=False)
  self.assertEqual(self.service.validate_result(result,review,review['snapshot'],evidence)['overall'],'failed')
  review['snapshot']['request']['generate_audio']=False
  self.assertEqual(self.service.validate_result(result,review,review['snapshot'],evidence)['overall'],'uncertain')
 def test_unexplained_and_changed_dialogue_revisions(self):
  review=self.done(); result=self.report(); result['revised_prompt']='@SampleHero2 waves.'
  with self.assertRaisesRegex(APIError,'without explaining'): self.service.validate_result(result,review,review['snapshot'],self.evidence)
  result['changes']=[dict(finding_ids=['identity'],before='turns',after='waves',reason='Fix staging')]
  self.assertIn('quoted dialogue',self.service.validate_result(result,review,review['snapshot'],self.evidence)['revision_error'])
 def test_apply_preserves_inputs_and_recovery(self):
  review=self.done(); original=self.video['scene']['prompt']; prompt=original+' He faces Mark.'; old=copy.deepcopy(self.video['scene'])
  applied=self.apply(review,prompt=prompt); self.assertEqual(applied['scene']['scene']['prompt'],prompt)
  self.assertEqual(applied['review']['previous_draft']['prompt'],original)
  for key in ('first','named','audio','duration','model'): self.assertEqual(applied['scene']['scene'][key],old[key])
  self.app.filmmaking.request_plan.assert_not_called()
 def test_apply_rejects_stale_inputs_dialogue(self):
  review=self.done()
  with self.assertRaisesRegex(APIError,'draft changed'): self.service.apply(review['id'],dict(approved=True,expected_scene_revision=0))
  with self.assertRaisesRegex(APIError,'quoted dialogue'): self.apply(review,prompt='@SampleHero2 waves.')
  self.app.agent.record(self.video['id'])['scene']['audio']=False
  with self.assertRaisesRegex(APIError,'references changed'): self.apply(review)
 def test_learning_explicit_reversible_scoped(self):
  review=self.done(); learning=self.app.video_learning; before=prompt_guides.load(MODEL,app=self.app)['sha256']
  outcome=self.service.outcome(review['id'],dict(approved=True,successful=True,expected_revision=review['revision'])); lesson=outcome['lesson_proposal']
  self.assertEqual(lesson['status'],'proposed'); self.assertEqual(prompt_guides.load(MODEL,app=self.app)['sha256'],before)
  active=learning.approve(lesson['id'],dict(approved=True,expected_revision=lesson['revision'],expected_guide_version=0))['lesson']
  self.assertNotEqual(prompt_guides.load(MODEL,app=self.app)['sha256'],before); self.assertEqual(learning.supplement(MODEL+'-lite'),'')
  self.assertFalse(prompt_guides.current_versions(review['provenance'],app=self.app))
  inactive=learning.deactivate(active['id'],dict(expected_revision=active['revision']))['lesson']; self.assertEqual(learning.supplement(MODEL),'')
  learning.approve(inactive['id'],dict(approved=True,expected_revision=inactive['revision'],expected_guide_version=2)); self.assertIn('Bind the revealed',learning.supplement(MODEL))
 def test_unknown_model_uncertain_findings_cannot_teach(self):
  review=self.done(); review['snapshot']['returned_model']=None
  outcome=self.service.outcome(review['id'],dict(approved=True,successful=True,expected_revision=review['revision']))
  self.assertIsNone(outcome['lesson_proposal']); self.assertIn('unconfirmed',outcome['lesson_reason'])
  review['snapshot']['returned_model']=MODEL; review['result']['requirements'][0]['status']='uncertain'
  self.assertIsNone(self.app.video_learning.propose(review,dict(approved=True,successful=True)))
 def test_lessons_merge_distinct_attempts(self):
  review=self.done(); learning=self.app.video_learning
  for index in range(3):
   candidate=copy.deepcopy(review); candidate.update(id=uuid.uuid4().hex,video_job_id=uuid.uuid4().hex)
   lesson=learning.propose(candidate,dict(approved=True,successful=True)); learning.approve(lesson['id'],dict(approved=True,expected_revision=lesson['revision'],expected_guide_version=index))
  history=learning.history(MODEL)['lessons']; active=next(r for r in history if r['status']=='active')
  self.assertEqual(active['confidence'],'supported'); self.assertEqual(len(active['evidence']),3); self.assertEqual(len(history),3)
 def test_review_and_lesson_mode_isolation(self):
  review=self.done(); lesson=self.app.video_learning.propose(review,dict(approved=True,successful=True))
  self.app.mock=True
  with self.assertRaisesRegex(APIError,'not found'): self.service.get(review['id'])
  with self.assertRaisesRegex(APIError,'not found'): self.app.video_learning.lesson(lesson['id'])
  self.assertEqual(self.app.video_learning.history(MODEL)['lessons'],[])
  self.assertEqual(self.service.dispatch('GET',[],{})[1]['reviews'],[])
 def test_mock_worker_never_calls_writer(self):
  self.app.mock=True; self.job['mock']=True; self.app.spawn=lambda fn,*args:fn(*args)
  result=self.start(); self.assertEqual(result['status'],'done'); self.assertEqual(result['result']['overall'],'uncertain')
  self.assertEqual(result['evidence']['visual_analysis'],'none'); self.app.filmmaking.request_plan.assert_not_called()
 def test_worker_uses_submitted_request_and_frozen_pixels_not_current_draft(self):
  item=self.start(); evidence=copy.deepcopy(self.evidence)
  self.service.sample=Mock(return_value=(evidence,[dict(url='data:image/png;base64,fixture')]))
  self.app.filmmaking.request_plan.side_effect=None; self.app.filmmaking.request_plan.return_value=self.report()
  self.app.agent.record(self.video['id'])['scene']['prompt']='Newer user draft.'
  self.service.worker(item['id'],self.job)
  review=self.service.get(item['id']); self.assertEqual(review['status'],'done',review['error'])
  context=self.app.filmmaking.request_plan.call_args.args[1]
  self.assertEqual(context['draft_prompt'],'@SampleHero2 turns. Mark says "You wore it!"')
  self.assertEqual(context['source_provenance'],'exact'); self.assertEqual(len(context['_writing_images']),1)
  self.assertEqual(self.app.agent.record(self.video['id'])['scene']['prompt'],'Newer user draft.')
 def test_writer_failure_preserves_draft_and_does_not_retry(self):
  item=self.start(); self.service.sample=Mock(return_value=(self.evidence,[]))
  before=copy.deepcopy(self.app.agent.record(self.video['id']))
  self.app.filmmaking.request_plan.side_effect=ValueError('Fixture writing failure')
  self.service.worker(item['id'],self.job)
  review=self.service.get(item['id']); self.assertEqual(review['status'],'error')
  self.assertIn('No automatic retry',review['error']); self.assertEqual(self.app.filmmaking.request_plan.call_count,1)
  self.assertEqual(self.app.agent.record(self.video['id']),before)
 def test_local_sampling_and_corruption_guard(self):
  if not self.app.editing.ffmpeg: self.skipTest('FFmpeg unavailable')
  path=Path(self.tmp.name)/'fixture.mp4'
  subprocess.run([self.app.editing.ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=64x64:r=8:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True)
  self.app.download=Mock(return_value=path); review=self.done(); evidence,images=self.service.sample(review['id'],self.job,review['snapshot'])
  self.assertGreaterEqual(len(evidence['frames']),2); self.assertEqual(evidence['frames'][-1]['time_seconds'],.875); self.assertFalse(evidence['audio_present']); self.assertTrue(all(r['attached'] for r in evidence['references']))
  self.assertEqual(len(images),len(evidence['frames'])+len(evidence['references'])); review['evidence']=evidence
  self.service.evidence_file(review['id'],'frame-0').write_bytes(b'corrupted')
  with self.assertRaisesRegex(APIError,'changed'): self.service.evidence_file(review['id'],'frame-0')
 def test_partial_learning_only_confirmed_met_findings(self):
  review=self.done(); review['result']['overall']='partial'
  review['result']['requirements'].append(dict(id='eyeline',status='failed'))
  original=copy.deepcopy(review)
  for ids in ([], ['eyeline'], ['identity','identity'], ['unknown']):
   with self.assertRaises(APIError):
    self.service.outcome(review['id'],dict(approved=True,assessment='improved',expected_revision=review['revision'],confirmed_finding_ids=ids))
   self.assertEqual(review,original)
  value=self.service.outcome(review['id'],dict(approved=True,assessment='improved',expected_revision=review['revision'],confirmed_finding_ids=['identity']))
  self.assertFalse(value['outcome']['successful']); self.assertEqual(value['outcome']['assessment'],'improved')
  self.assertEqual(value['lesson_proposal']['evidence'][0]['assessment'],'improved')
  self.assertEqual(value['lesson_proposal']['evidence'][0]['confirmed_finding_ids'],['identity'])
  self.assertEqual(self.app.video_learning.supplement(MODEL),'')
 def test_assessment_only_and_history_do_not_teach(self):
  review=self.done()
  for assessment in ('improved','successful','needs_work'):
   value=self.service.outcome(review['id'],dict(approved=True,assessment=assessment,expected_revision=review['revision'],confirmed_finding_ids=['identity'],candidate_index=None))
   self.assertIsNone(value['lesson_proposal'])
  self.assertEqual(len(review['outcome_history']),2); self.assertEqual(self.app.video_learning.history(MODEL)['lessons'],[])
 def test_lesson_approval_does_not_require_another_review_to_apply(self):
  review=self.done()
  value=self.service.outcome(review['id'],dict(approved=True,assessment='improved',expected_revision=review['revision'],confirmed_finding_ids=['identity']))
  lesson=value['lesson_proposal']; self.app.video_learning.approve(lesson['id'],dict(approved=True,expected_revision=lesson['revision'],expected_guide_version=0))
  self.assertEqual(self.apply(review)['scene']['scene']['prompt'],review['result']['revised_prompt'])
  self.app.filmmaking.request_plan.assert_not_called()
 def test_origin_is_frozen_at_generation_and_standalone_is_explicit(self):
  parent=self.done(); self.app.agent.record(self.video['id'])['video_review_origin']=dict(review_id=parent['id'])
  second=copy.deepcopy(self.job); second['id']=uuid.uuid4().hex
  second['request_snapshot']=self.service.capture_submission(second,self.app.resolve(second['settings']),second['settings'])
  self.app.records.return_value.append(second)
  self.app.agent.record(self.video['id'])['video_review_origin']=None
  self.assertEqual(self.service.suggested_previous(second,self.video['id']),parent['id'])
  value=self.service.start(dict(video_job_id=second['id'],scene_id=self.video['id'],approved=True),'origin-frozen-01')
  self.assertEqual(value['previous_review_id'],parent['id'])
 def refinement_fixture(self):
  parent=self.done(); evidence,images=self.service.sample(parent['id'],self.job,parent['snapshot'])
  parent['evidence']=evidence; parent['result']['requirements'][0]['timestamps']=[evidence['frames'][-1]['time_seconds']]
  parent['result']['requirements'][0]['evidence_ids']=[evidence['frames'][-1]['id'],evidence['references'][0]['id']]
  return parent
 def test_refinement_reuses_verified_pixels_without_render_or_extraction(self):
  if not self.app.editing.ffmpeg: self.skipTest('FFmpeg unavailable')
  path=Path(self.tmp.name)/'refine.mp4'
  subprocess.run([self.app.editing.ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=blue:s=64x64:r=8:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(path)],check=True)
  self.app.download=Mock(return_value=path); parent=self.refinement_fixture()
  self.app.download.reset_mock(); self.service.sample=Mock(side_effect=AssertionError('No new extraction'))
  before=copy.deepcopy(self.app.agent.record(self.video['id'])); original=copy.deepcopy(parent)
  data=dict(approved=True,expected_revision=parent['revision'],notes='Fix the final glance.',preserve_finding_ids=['identity'])
  child=self.service.refine(parent['id'],data,'refinement-test-01')
  self.assertEqual(self.service.refine(parent['id'],data,'refinement-test-01')['id'],child['id'])
  self.assertEqual(self.service.refine(parent['id'],data,'refinement-cache-01')['id'],child['id'])
  result=copy.deepcopy(parent['result']); result['revised_prompt']+=' Keep partner eyelines.'
  result['requirements'].append(dict(id='glance',requirement='Final glance',category='other',status='uncertain',observation='Not verified.',evidence_ids=[],timestamps=[],confidence='low'))
  result['changes']=[dict(finding_ids=['glance'],before='',after='Keep partner eyelines.',reason='Human reported final glance.')]
  self.app.filmmaking.request_plan.side_effect=None; self.app.filmmaking.request_plan.return_value=result
  self.service.refinement_worker(child['id']); saved=self.service.get(child['id'])
  self.assertEqual(saved['status'],'done',saved['error']); self.assertEqual(saved['parent_review_id'],parent['id'])
  context=self.app.filmmaking.request_plan.call_args.args[1]
  self.assertEqual(context['remaining_issues'],data['notes']); self.assertEqual(context['preserved_findings'][0]['id'],'identity')
  self.assertGreater(len(context['_writing_images']),1); self.assertEqual(parent,original)
  self.assertEqual(self.app.agent.record(self.video['id']),before); self.service.sample.assert_not_called(); self.app.download.assert_not_called()
  saved['evidence']['frames'][0]['sha256']='invalid'
  with self.assertRaises(APIError): self.service.evidence_file(saved['id'],saved['evidence']['frames'][0]['id'])
 def test_refinement_guards_and_failure_preserve_prior_draft(self):
  parent=self.done(); data=dict(approved=True,expected_revision=parent['revision'],notes='Fix eyeline.',preserve_finding_ids=['identity'])
  for update in ({'approved':False},{'expected_revision':0},{'notes':''},{'preserve_finding_ids':['unknown']}):
   with self.assertRaises(APIError): self.service.refine(parent['id'],dict(data,**update),'refinement-invalid')
  child=self.service.refine(parent['id'],data,'refinement-failure'); before=copy.deepcopy(self.app.agent.record(self.video['id']))
  self.service.saved_evidence=Mock(return_value=(self.evidence,[]))
  self.app.filmmaking.request_plan.side_effect=ValueError('Fixture writing failure')
  self.service.refinement_worker(child['id']); saved=self.service.get(child['id'])
  self.assertEqual(saved['status'],'error'); self.assertIn('No automatic retry',saved['error'])
  self.assertEqual(self.app.filmmaking.request_plan.call_count,1); self.assertEqual(self.app.agent.record(self.video['id']),before)
  self.assertEqual(parent['status'],'done')
 def test_refinement_rejects_changes_to_preserved_findings(self):
  parent=self.done(); child=self.service.refine(parent['id'],dict(approved=True,expected_revision=parent['revision'],notes='Fix glance.',preserve_finding_ids=['identity']),'refinement-preserve')
  self.service.saved_evidence=Mock(return_value=(self.evidence,[])); result=self.report()
  result['requirements'][0]['status']='failed'
  self.app.filmmaking.request_plan.side_effect=None; self.app.filmmaking.request_plan.return_value=result
  self.service.refinement_worker(child['id'])
  self.assertEqual(self.service.get(child['id'])['status'],'error'); self.assertEqual(parent['result']['requirements'][0]['status'],'met')
if __name__=='__main__': unittest.main()
