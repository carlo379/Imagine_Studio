"""Local editor scale and scene render regressions; no provider calls."""
import copy,json,shutil,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from studio_server import Studio
from editing_tools import build_export
from editing_batches import bounded_export,BATCH_INPUTS

class ScaleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.app=Studio(mock=True,storage=self.tmp.name);self.e=self.app.editing;self.addCleanup(self.e.p.sql.close)
  self.source=Path(__file__).resolve().parents[1]/'static/mock-video.mp4'
  self.app.spawn=lambda fn,*args:fn(*args)
  self.p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Scale'))[1]['production']
 def fixture(self,n=12):
  m=self.e.probe(self.source);self.e.source=Mock(return_value=(m,self.source))
  timeline=self.e.timeline(self.p['id'])
  return self.e.save(timeline['id'],dict(expected_revision=timeline['revision'],clips=[dict(id=f'c{i}',source=dict(kind='upload',id='fixture'),**{'in':0,'out':.25},volume=1) for i in range(n)],output=dict(ratio='16:9',resolution='480p',fps=24,cut_audio_crossfade_frames=0)))
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_many_clips_bounded_inputs_cleanup_and_frames(self):
  t=self.fixture(20);calls=[];run=self.e.run
  def track(identity,args,*rest):calls.append(args.count('-i'));return run(identity,args,*rest)
  self.e.run=track
  j=self.e.export(t['id'],dict(expected_revision=t['revision']),'scale-many-clips');j=self.e.p.get(j['id'],'export')
  self.assertEqual(j['status'],'done',j.get('error'));self.assertLessEqual(max(calls),BATCH_INPUTS)
  self.assertEqual(j['batch_peak_inputs'],BATCH_INPUTS)
  self.assertFalse(list((self.app.storage/'exports'/j['id']).glob('batch-*')))
  self.assertEqual(self.frame_count(self.e.file(j['id'])),120)
 def frame_count(self,path):
  raw=subprocess.check_output([self.e.ffprobe,'-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','json',str(path)])
  return int(json.loads(raw)['streams'][0]['nb_read_frames'])
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_batched_matches_single_graph_frames_and_audio(self):
  t=self.fixture(4);t['clips'][1]['transition']=dict(type='dissolve',duration=1/12);t['clips'][2]['hold_end']=1/12;t['clips'][3]['zoom']=dict(scale=1.3,x=.5,y=.5)
  sources=[(self.source,self.e.probe(self.source))]*4
  root=Path(self.tmp.name);single=root/'single';single.mkdir();batch=root/'batch';batch.mkdir()
  with self.e.p.sql:j=self.e.p.new('export',status='rendering',snapshot=t)
  import threading
  self.e.cancellations[j['id']]=threading.Event()
  reference=build_export(t,sources);reference[-1:-1]=['-threads','2']
  self.e.run(j['id'],reference,single,0,1,1)
  bounded_export(self.e,j['id'],build_export(t,sources,balanced=True),batch,1,24)
  a=single/'export.mp4';b=batch/'export.mp4';self.assertEqual(self.frame_count(a),self.frame_count(b));self.assertEqual(self.frame_count(b),24)
  def decoded(path):return subprocess.check_output([self.e.ffmpeg,'-v','error','-i',str(path),'-map','0:v','-pix_fmt','yuv420p','-f','rawvideo','-'])
  aa=decoded(a);bb=decoded(b);self.assertEqual(len(aa),len(bb));self.assertLess(sum(abs(x-y) for x,y in zip(aa,bb))/len(aa),.1)
  self.assertLess(abs(self.e.probe(a)['duration']-self.e.probe(b)['duration']),1/24)
 def story(self):
  o=self.app.productions.dispatch('POST',[],dict(kind='story',title='Story',episode_title='Episode'))[1];ep=o['episodes'][0]
  ep=self.app.productions.dispatch('POST',[o['production']['id'],'scenes'],dict(episode_id=ep['id'],expected_revision=ep['revision'],title='Workshop'))[1]
  return o['production']['id'],ep['id'],ep['scenes'][0]['id']
 def call(self,method,path,data=None,key=None):return self.app.agent.dispatch(method,'/agent/v1/editing/'+path,data or {},key)[1]
 def test_scene_scope_migration_and_primary_isolation(self):
  pid,ep,sid=self.story()
  with self.e.p.sql:legacy=self.e.p.new('timeline',production_id=pid,episode_id=ep,title='Legacy',clips=[],audio=[],titles=[],output=dict(ratio='16:9',resolution='720p',fps=24))
  parent=self.call('POST','timelines/open',dict(production_id=pid,episode_id=ep))
  self.assertEqual(parent['id'],legacy['id']);self.assertIsNone(parent['story_scene_id']);self.assertNotIn('story_scene_id',self.e.p.get(legacy['id'],'timeline'))
  child=self.call('POST','timelines/open',dict(production_id=pid,episode_id=ep,story_scene_id=sid))
  self.assertNotEqual(child['id'],parent['id']);self.assertEqual(child['title'],'Workshop')
  duplicate=self.call('POST','timelines/'+child['id']+'/duplicate',dict(expected_revision=1))
  self.call('POST','timelines/'+duplicate['id']+'/primary',dict(expected_revision=1))
  self.assertEqual(self.call('POST','timelines/open',dict(production_id=pid,episode_id=ep,story_scene_id=sid))['id'],duplicate['id'])
  self.assertEqual(self.e.p.get(parent['id'],'timeline')['revision'],parent['revision'])
  from agent_api import APIError
  with self.assertRaises(APIError):self.call('POST','timelines/open',dict(production_id=pid,episode_id=ep,story_scene_id='foreign'))
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_scene_render_replace_links_and_revision_guard(self):
  from agent_api import APIError
  pid,ep,sid=self.story();parent=self.e.timeline(pid,ep);child=self.e.timeline(pid,ep,sid)
  child=self.e.save(child['id'],dict(expected_revision=child['revision'],clips=[dict(id='gap',source=dict(kind='gap'),**{'in':0,'out':.5})],output=dict(ratio='16:9',resolution='480p',fps=24)))
  body=dict(expected_revision=child['revision'],parent_timeline_id=parent['id'],expected_parent_revision=parent['revision'])
  job=self.call('POST','timelines/'+child['id']+'/render',body,'scene-render-one');job=self.e.p.get(job['id'],'export');self.assertEqual(job['status'],'done',job.get('error'));self.assertEqual(job.get('render_status'),'inserted',job.get('render_error'))
  parent=self.e.p.get(parent['id'],'timeline');self.assertEqual(len(parent['clips']),1);clip=parent['clips'][0];self.assertEqual(clip['render_link']['revision'],child['revision']);self.assertEqual(clip['render_link']['timeline_id'],child['id'])
  self.assertEqual(self.call('POST','timelines/'+child['id']+'/render',body,'scene-render-one')['id'],job['id'])
  # A new request re-renders and replaces the linked clip.
  again=self.call('POST','timelines/'+child['id']+'/render',{**body,'expected_parent_revision':parent['revision']},'scene-render-two');again=self.e.p.get(again['id'],'export');self.assertEqual(again.get('render_status'),'inserted',again.get('render_error'))
  newer=self.e.p.get(parent['id'],'timeline');self.assertEqual(len(newer['clips']),1);self.assertEqual(newer['clips'][0]['id'],clip['id'])
  with self.assertRaises(APIError) as err:self.call('POST','timelines/'+child['id']+'/render',body,'scene-stale-render')
  self.assertEqual(err.exception.status,409)
  # An edit after queuing is protected, and its render remains downloadable.
  self.app.spawn=lambda *args:None
  pending=self.call('POST','timelines/'+child['id']+'/render',{**body,'expected_parent_revision':newer['revision']},'scene-racing-edit')
  self.e.save(newer['id'],dict(expected_revision=newer['revision'],title='Changed while rendering'))
  self.e.worker(pending['id']);pending=self.e.p.get(pending['id'],'export')
  self.assertEqual(pending['status'],'done',pending.get('error'));self.assertEqual(pending['render_status'],'error');self.assertIn('changed',pending['render_error'].lower());self.assertTrue(self.e.file(pending['id']).is_file())

 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_batch_cancel_cleans_intermediates(self):
  t=self.fixture(12);run=self.e.run;calls=[]
  def cancel(identity,*args):
   result=run(identity,*args);calls.append(identity)
   if len(calls)==2:self.e.cancellations[identity].set()
   return result
  self.e.run=cancel;j=self.e.export(t['id'],dict(expected_revision=t['revision']),'scale-cancel-batch');j=self.e.p.get(j['id'],'export')
  self.assertEqual(j['status'],'cancelled');self.assertFalse(list((self.app.storage/'exports'/j['id']).glob('batch-*')))
 def test_audio_capacity_boundary_through_agent_api(self):
  from agent_api import APIError
  from agent_openapi import specification
  t=self.fixture(1);m=self.e.source.return_value[0];self.e.source.return_value=({**m,'audio':True},self.source);audio=[dict(id=f'a{i}',source=dict(kind='upload',id='fixture'),**{'in':0,'out':.25},start=0,volume=1) for i in range(200)]
  saved=self.call('PUT','timelines/'+t['id'],dict(expected_revision=t['revision'],audio=audio));self.assertEqual(len(saved['audio']),200)
  with self.assertRaisesRegex(APIError,'200 audio items'):self.call('PUT','timelines/'+t['id'],dict(expected_revision=saved['revision'],audio=audio+[dict(audio[0],id='overflow')]))
  self.assertEqual(self.e.p.get(t['id'],'timeline')['revision'],saved['revision']);self.assertEqual(self.call('GET','schema')['limits']['audio'],200)
  body=specification()['paths']['/editing/timelines/{id}']['put']['requestBody']['content']['application/json']['schema'];self.assertEqual(body['properties']['audio']['maxItems'],200)
 def test_offline_transcription_configuration_and_mocked_engine(self):
  import sys,types
  from unittest.mock import patch
  from agent_api import APIError
  root=(Path(self.tmp.name)/'offline-model').resolve();root.mkdir()
  with patch('editing_studio.importlib.util.find_spec',return_value=None):
   original=self.call('GET','transcription');self.assertFalse(original['available']);self.assertIn('SRT',original['message'])
   changed=self.call('PUT','transcription',dict(expected_revision=0,local_transcription_model=str(root)));self.assertFalse(changed['model_present'])
   t=self.fixture(1)
   with self.assertRaisesRegex(APIError,'Import an SRT'):self.call('POST','timelines/'+t['id']+'/captions/transcribe',dict(expected_revision=t['revision']))
  for name in ('model.bin','config.json','tokenizer.json'):(root/name).write_bytes(b'local mock fixture')
  with patch('editing_studio.importlib.util.find_spec',return_value=object()):
   state=self.call('GET','transcription');self.assertTrue(state['available']);self.assertEqual(state['local_transcription_model'],str(root))
  with self.assertRaises(APIError):self.call('PUT','transcription',dict(expected_revision=0,local_transcription_model=None))
  with self.assertRaises(APIError):self.call('PUT','transcription',dict(expected_revision=changed['revision'],local_transcription_model='remote-model-name'))
  model=Mock();model.transcribe.return_value=([types.SimpleNamespace(start=0,end=.2,text='Local words')],None);factory=Mock(return_value=model)
  m=self.e.probe(self.source);self.e.source=Mock(return_value=({**m,'audio':True},self.source))
  with patch.dict(sys.modules,{'faster_whisper':types.SimpleNamespace(WhisperModel=factory)}),patch('editing_studio.importlib.util.find_spec',return_value=object()),patch('httpx.Client') as network:
   job=self.call('POST','timelines/'+t['id']+'/captions/transcribe',dict(expected_revision=t['revision']));network.assert_not_called()
  self.assertEqual(job['status'],'done',job.get('error'));self.assertEqual(self.e.p.get(t['id'],'timeline')['captions'][0]['text'],'Local words')
  factory.assert_called_once_with(str(root),local_files_only=True,device='cpu',compute_type='int8')
  restarted=Studio(mock=True,storage=self.tmp.name);self.addCleanup(restarted.productions.sql.close)
  self.assertEqual(restarted.editing.transcription_settings()['local_transcription_model'],str(root))
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_many_audio_stems_ducking_and_offsets_match_reference(self):
  import array,threading,math
  speech=Path(__file__).parent/'fixtures/ducking-speech.wav';t=self.fixture(5);t['clips'][1]['transition']=dict(type='dissolve',duration=1/12);t['clips'][-1]['audio_offset']=1/12
  meta=self.e.probe(speech);audio=[dict(id=f'a{i}',source=dict(kind='upload',id='speech'),**{'in':0,'out':.5},start=i/24,volume=.05,lane=('dialogue','music','sfx')[i%3]) for i in range(12)]
  t['audio']=audio;t['output'].update(loudness_target_lufs=-16,ducking=dict(enabled=True,amount_db=10,attack_ms=80,release_ms=400))
  sources=[(self.source,self.e.probe(self.source))]*5+[(speech,meta)]*12
  root=Path(self.tmp.name);single=root/'reference';single.mkdir();batch=root/'staged';batch.mkdir()
  with self.e.p.sql:j=self.e.p.new('export',status='rendering',snapshot=t)
  self.e.cancellations[j['id']]=threading.Event()
  def lossless_audio(args):
   args[args.index('-c:a')+1]='pcm_f32le';idx=args.index('-movflags');del args[idx:idx+2];args[-1]='export.nut';return args
  args=lossless_audio(build_export(t,sources));args[-1:-1]=['-threads','2'];self.e.run(j['id'],args,single,0,1,2)
  bounded_export(self.e,j['id'],lossless_audio(build_export(t,sources,balanced=True)),batch,2,24)
  def samples(path):
   raw=subprocess.check_output([self.e.ffmpeg,'-v','error','-i',str(path),'-map','0:a','-f','f32le','-']);out=array.array('f');out.frombytes(raw);return out
  a=samples(single/'export.nut');b=samples(batch/'export.nut');self.assertEqual(len(a),len(b));self.assertLess(math.sqrt(sum((x-y)**2 for x,y in zip(a,b))/len(a)),.0001)
  self.assertEqual(self.frame_count(single/'export.nut'),self.frame_count(batch/'export.nut'))

 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_normalized_stems_keep_the_full_silent_tail(self):
  import array
  from editing_tools import mix_lanes
  speech=Path(__file__).parent/'fixtures/ducking-speech.wav'
  graph=['[0:a]atrim=duration=0.5,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=3[d][m][s]']
  for node in mix_lanes(dict(dialogue=['[d]'],music=['[m]'],sfx=['[s]']),2,dict(enabled=True,amount_db=10,attack_ms=80,release_ms=400),-16):
   graph.append(node)
   if node.endswith('[sfx]'):break
  args=[self.e.ffmpeg,'-v','error','-y','-filter_complex_threads','1','-i',str(speech),'-filter_complex',';'.join(graph)]
  paths=[]
  for lane in ('dialogue','music','sfx'):
   path=Path(self.tmp.name)/(lane+'.f32');paths.append(path)
   args+=['-map','['+lane+']','-ar','48000','-ac','2','-f','f32le',str(path)]
  subprocess.run(args,check=True,capture_output=True,timeout=20)
  for path in paths:
   with self.subTest(lane=path.stem):
    values=array.array('f');values.frombytes(path.read_bytes())
    self.assertEqual(len(values),2*48000*2)
    self.assertEqual(max(abs(v) for v in values[-9600:]),0)

 def test_audio_handle_api_identifies_clip_direction_and_silent_sources(self):
  from agent_api import APIError
  t=self.fixture(1);c={**t['clips'][0],'label':'Opening wide'};meta=self.e.source.return_value[0]
  self.e.source.return_value=({**meta,'audio':True},self.source)
  for offset,end,side in [(-.042,c['out'],'before the trim start'),(.042,meta['duration'],'after the trim end')]:
   with self.assertRaises(APIError) as error:self.call('PUT','timelines/'+t['id'],dict(expected_revision=t['revision'],clips=[{**c,'out':end,'audio_offset':offset}]))
   self.assertEqual(error.exception.code,'invalid_audio_handle');self.assertIn('Opening wide',str(error.exception));self.assertIn(c['id'],str(error.exception));self.assertIn(side,str(error.exception));self.assertIn('0.000s available',str(error.exception))
  self.e.source.return_value=({**meta,'audio':False},self.source)
  with self.assertRaisesRegex(APIError,'no audio track'):self.call('PUT','timelines/'+t['id'],dict(expected_revision=t['revision'],clips=[{**c,'audio_offset':.042}]))
  self.assertEqual(self.e.p.get(t['id'],'timeline')['revision'],t['revision'])
