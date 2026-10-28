import base64
import copy
import io
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch,Mock
import studio_server as studio
from agent_api import APIError
from story_studio import split_script,import_file,writing_reply

class StoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.tmp.name)
  self.series=self.call('POST','series',{'title':'Example Series'})
  self.ep=self.call('POST','episodes',{'series_id':self.series['id'],'title':'Teaser'})
 def tearDown(self):self.tmp.cleanup()
 def call(self,method,path,data=None,key=None):return self.app.agent.dispatch(method,'/agent/v1/stories/'+path,data or {},key)[1]
 def script(self):
  self.ep=self.call('PUT','episodes/'+self.ep['id'],{'expected_revision':self.ep['revision'],'scenes':[{'title':'Opening','text':'SampleHero enters the studio.'},{'title':'Discovery','text':'A signal arrives.'}]});return self.ep
 def wait(self,j):
  for _ in range(50):
   job=self.call('GET','chats/'+j['id'])
   if job['status']!='pending':return job
   time.sleep(.02)
  self.fail('Writing worker did not finish')
 def test_import_preserves_script_divisions_and_docx_text(self):
  parts=split_script('SCENE 1 — Studio\nHello\nSCENE 2 — Discovery\nSignal')
  self.assertEqual([p['text'] for p in parts],['Hello','Signal'])
  self.assertEqual(len(split_script('A script without headings.')),1)
  archive=io.BytesIO()
  with zipfile.ZipFile(archive,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Scene 1</w:t></w:r></w:p><w:p><w:r><w:t>SampleHero speaks.</w:t></w:r></w:p></w:document>')
  parsed=import_file({'name':'teaser.docx','base64':base64.b64encode(archive.getvalue()).decode()})
  self.assertEqual(parsed,'Scene 1\nSampleHero speaks.')
  with self.assertRaises(APIError):import_file({'name':'script.pdf','base64':'eA=='})
 def test_import_preview_does_not_change_episode(self):
  preview=self.call('POST','import-preview',{'text':'Scene 1\nOpening\nScene 2\nEnd'})
  self.assertEqual(len(preview['scenes']),2);self.assertEqual(self.call('GET','episodes/'+self.ep['id'])['revision'],1)
 def test_classified_import_preserves_support_and_scene_identity(self):
  self.script();old=self.ep['scenes'][0]['id']
  preview=self.call('POST','import-preview',{'text':'Opening instructions\nScene 1\nAction'})
  self.assertEqual([s['type'] for s in preview['sections']],['notes','scene'])
  parts=[{'type':'notes','title':'Opening notes','text':'Keep the tone calm.'},{'type':'scene','title':'Opening','text':'New action.'},{'type':'other','title':'Credits','text':'Production team'}]
  result=self.call('POST','episodes/'+self.ep['id']+'/apply-import',{'expected_revision':self.ep['revision'],'sections':parts})
  self.assertEqual(len(result['scenes']),1);self.assertEqual(result['scenes'][0]['id'],old)
  self.assertIn('[Notes] Opening notes',result['notes']);self.assertIn('[Other] Credits',result['notes'])
  self.assertEqual(result['versions'][-1]['notes'],result['notes'])
 def test_notes_only_import_keeps_scenes_and_existing_notes(self):
  self.script()
  self.ep=self.call('PUT','episodes/'+self.ep['id'],{'expected_revision':self.ep['revision'],'notes':'Original notes'})
  result=self.call('POST','episodes/'+self.ep['id']+'/apply-import',{'expected_revision':self.ep['revision'],'sections':[{'type':'notes','title':'Context','text':'New notes'}]})
  self.assertEqual(result['scenes'],self.ep['scenes']);self.assertTrue(result['notes'].startswith('Original notes'))
 def test_invalid_classified_import_is_atomic(self):
  route='episodes/'+self.ep['id']+'/apply-import'
  for parts in ([{'type':'bad','title':'Wrong','text':'Text'}],[{'type':'notes','title':'Too long','text':'x'*10001}],[]):
   with self.assertRaises(APIError):self.call('POST',route,{'expected_revision':1,'sections':parts})
   self.assertEqual(self.call('GET','episodes/'+self.ep['id'])['revision'],1)
  with self.assertRaises(APIError):self.call('POST',route,{'expected_revision':99,'sections':[{'type':'scene','title':'Scene','text':'Action'}]})

 def test_scene_ids_order_revision_restore_restart(self):
  ep=self.script();original=copy.deepcopy(ep)
  renamed=copy.deepcopy(ep['scenes'][0]);renamed['title']='Studio entrance'
  ep=self.call('PUT','episodes/'+ep['id'],{'expected_revision':2,'scenes':[ep['scenes'][1],renamed]})
  self.assertEqual(ep['scenes'][1]['id'],original['scenes'][0]['id'])
  with self.assertRaises(APIError) as err:self.call('PUT','episodes/'+ep['id'],{'expected_revision':2,'title':'Stale'})
  self.assertEqual(err.exception.status,409)
  restored=self.call('POST','episodes/'+ep['id']+'/restore',{'expected_revision':3,'revision':2})
  self.assertEqual(restored['scenes'],original['scenes']);self.assertEqual(restored['revision'],4)
  restarted=studio.Studio(mock=True,storage=self.tmp.name)
  self.assertEqual(restarted.stories.record('episodes',ep['id'])['scenes'],original['scenes'])
 def test_media_context_is_immutable_and_not_a_generation_prompt(self):
  ep=self.script();sid=ep['scenes'][0]['id']
  image=self.call('POST','episodes/'+ep['id']+'/media',{'expected_revision':2,'scene_id':sid,'kind':'image'})
  video=self.call('POST','episodes/'+ep['id']+'/media',{'expected_revision':2,'scene_id':sid,'kind':'video'})
  self.assertEqual(image['settings']['prompt'],'');self.assertEqual(video['scene']['prompt'],'')
  changed=copy.deepcopy(ep['scenes']);changed[0]['text']='Changed scene'
  self.call('PUT','episodes/'+ep['id'],{'expected_revision':2,'scenes':changed})
  self.assertEqual(image['story_context']['scene_text'],'SampleHero enters the studio.')
  self.assertEqual(video['story_context']['script_revision'],2)
  video['scene']['prompt']='Slow camera movement.'
  payload=self.app.agent.compile(video['scene']);payload['_studio_story']=video['story_context']
  self.assertNotIn('_studio_story',self.app.resolve(payload))
  self.assertEqual(len(self.call('GET','links')),2)
 def test_mock_conversation_approval_idempotency_and_apply(self):
  data={'expected_revision':1,'message':'Draft a teaser about a signal.','scope':'episode','approved':True}
  with self.assertRaises(APIError):self.call('POST','episodes/'+self.ep['id']+'/chat',{**data,'approved':False},'writing-test-one')
  with patch('story_studio.writing_reply') as provider:
   j=self.call('POST','episodes/'+self.ep['id']+'/chat',data,'writing-test-one');job=self.wait(j)
   repeated=self.call('POST','episodes/'+self.ep['id']+'/chat',data,'writing-test-one')
   self.assertEqual(j['id'],repeated['id']);provider.assert_not_called()
  self.assertEqual(self.call('GET','episodes/'+self.ep['id'])['scenes'],[])
  updated=self.call('POST','episodes/'+self.ep['id']+'/apply-proposal',{'expected_revision':1,'job_id':job['id']})
  self.assertEqual(len(updated['scenes']),2)
  with self.assertRaises(APIError):self.call('POST','episodes/'+self.ep['id']+'/chat',{**data,'message':'Different'},'writing-test-one')
 def test_proposal_cannot_overwrite_newer_script(self):
  j=self.wait(self.call('POST','episodes/'+self.ep['id']+'/chat',{'expected_revision':1,'message':'Write it.','approved':True},'writing-stale-test'))
  self.call('PUT','episodes/'+self.ep['id'],{'expected_revision':1,'title':'New title'})
  with self.assertRaises(APIError) as err:self.call('POST','episodes/'+self.ep['id']+'/apply-proposal',{'expected_revision':2,'job_id':j['id']})
  self.assertEqual(err.exception.status,409)
 def test_scene_scope_leaves_other_scene_intact(self):
  ep=self.script();j=self.wait(self.call('POST','episodes/'+ep['id']+'/chat',{'expected_revision':2,'scope':'scene','scene_id':ep['scenes'][0]['id'],'message':'Improve pacing.','approved':True},'writing-scene-test'))
  updated=self.call('POST','episodes/'+ep['id']+'/apply-proposal',{'expected_revision':2,'job_id':j['id']})
  self.assertEqual(updated['scenes'][1],ep['scenes'][1])
 def test_previous_context_cross_series_rejected_and_selected_only(self):
  ep=self.script();other=self.call('POST','episodes',{'series_id':self.series['id'],'title':'Episode two'})
  data={'expected_revision':1,'previous_episode_ids':[ep['id']],'message':'Continue the story.','approved':True}
  j=self.wait(self.call('POST','episodes/'+other['id']+'/chat',data,'writing-context-test'))
  self.assertEqual(j['context']['previous_episodes'][0]['episode_id'],ep['id'])
  s=self.call('POST','series',{'title':'Other series'});foreign=self.call('POST','episodes',{'series_id':s['id'],'title':'Other episode'})
  with self.assertRaises(APIError):self.call('POST','episodes/'+other['id']+'/chat',{**data,'previous_episode_ids':[foreign['id']]},'writing-foreign-test')
 def test_limits_duplicate_scene_and_forged_ids_rejected(self):
  ep=self.script()
  for scenes in ([ep['scenes'][0],ep['scenes'][0]],[{'id':'f'*32,'title':'Fake','text':''}],[{'title':'Too long','text':'x'*100001}]):
   with self.assertRaises(APIError):self.call('PUT','episodes/'+ep['id'],{'expected_revision':2,'scenes':scenes})
 def test_workspace_clear_and_revision_safe_context(self):
  ep=self.script();sid=ep['scenes'][0]['id']
  self.call('POST','workspace',{'episode_id':ep['id'],'scene_id':sid})
  self.assertEqual(self.call('GET','workspace')['scene_id'],sid)
  self.call('POST','workspace',{'episode_id':None});self.assertEqual(self.call('GET','workspace'),{})
  snap=self.call('POST','episodes/'+ep['id']+'/context',{'revision':2,'scene_id':sid})
  self.assertEqual(snap['scene_title'],'Opening')
 def test_image_job_reuse_and_refinement_keep_script_snapshot(self):
  ep=self.script();draft=self.call('POST','episodes/'+ep['id']+'/media',{'expected_revision':2,'scene_id':ep['scenes'][0]['id'],'kind':'image'})
  self.app.update(signed_in=True)
  updated=self.app.images.edit(draft['id'],{'expected_revision':1,'settings':{**draft['settings'],'prompt':'SampleHero in the studio.'}})
  _,job=self.app.agent.dispatch('POST','/agent/v1/image-studio/drafts/'+draft['id']+'/generate',{'expected_revision':updated['revision'],'approved':True},'story-image-job')
  for _ in range(100):
   job=self.app.images.job(job['id'])
   if job['status']!='pending':break
   time.sleep(.02)
  self.assertEqual(job['status'],'done');self.assertEqual(job['draft']['story_context'],draft['story_context'])
  for action,data in [('reuse',{}),('refine',{'asset_id':job['outputs'][0]['id']})]:
   _,reused=self.app.agent.dispatch('POST','/agent/v1/image-studio/jobs/'+job['id']+'/'+action,data)
   self.assertEqual(reused['story_context'],draft['story_context'])
  self.assertEqual(len(self.call('GET','links')),3)
 def test_native_writer_is_tool_free_and_no_api_fallback(self):
  def rpc(method,data):
   if method=='config/read':return {'config':{'model':'conflicting-local-model','model_reasoning_effort':'high','mcp_servers':{}}}
   if method=='mcpServerStatus/list':return {'data':[{'name':'code-review'}]}
   if method=='thread/start':
    self.assertEqual(data['model'],'gpt-6.1-sol');self.assertEqual(data['config']['model'],'gpt-6.1-sol');self.assertEqual(data['config']['model_reasoning_effort'],'medium');self.assertFalse(data['config']['features.image_generation']);self.assertFalse(data['config']['features.shell_tool']);self.assertFalse(data['config']['mcp_servers.code-review']['enabled']);self.assertFalse(data['allowProviderModelFallback']);return {'thread':{'id':'t'}}
   if method=='turn/start':
    self.assertIn('outputSchema',data);self.assertEqual(data['model'],'gpt-6.1-sol');self.assertEqual(data['effort'],'medium')
   return {}
  with patch('openai_images.CodexRPC') as cls,patch('openai_images.generate_api') as api:
   c=cls.return_value;c.account.return_value={'signed_in':True};c.rpc.side_effect=rpc;c.receive.side_effect=[{'method':'item/completed','params':{'item':{'type':'agentMessage','text':'{"reply":"Draft ready","scenes":[]}'}}},{'method':'turn/completed','params':{'turn':{'status':'completed'}}}]
   self.assertEqual(writing_reply({'message':'Help'}),{'reply':'Draft ready','scenes':[]});c.close.assert_called_once();api.assert_not_called()

if __name__=='__main__':unittest.main()
