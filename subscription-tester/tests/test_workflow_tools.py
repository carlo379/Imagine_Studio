import tempfile,unittest,copy
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError
from test_studio import PNG
from workflow_tools import start_frame_gate,check,usage
class WorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=Studio(mock=True,storage=self.tmp.name);self.addCleanup(self.app.productions.sql.close)
  self.shot=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Any project'))[1]['shots'][0]
 def test_start_frame_gate(self):
  a=self.app.upload(dict(name='Frame',data_url=PNG));s=self.shot
  with self.app.productions.sql:self.app.productions.put('shot',{**s,'video_mode':'image_to_video','start_frame_asset_id':a['id']})
  settings=dict(_studio_video_id=s['video_id'])
  self.assertFalse(start_frame_gate(self.app,settings)['allowed'])
  settings['image']=dict(asset_id=a['id']);self.assertIn('Approve',start_frame_gate(self.app,settings)['missing'][0])
  settings['allow_unapproved_start_frame']=True;self.assertTrue(start_frame_gate(self.app,settings)['allowed'])
  settings['image']['asset_id']='missing';self.assertFalse(start_frame_gate(self.app,settings)['allowed'])
  settings['image']['asset_id']=a['id'];a['approved']=True;settings['allow_unapproved_start_frame']=False;self.assertTrue(start_frame_gate(self.app,settings)['allowed'])
 def test_generation_gate_and_override_logged(self):
  a=self.app.upload(dict(name='Frame',data_url=PNG));a['generated']=True;s=self.shot
  with self.app.productions.sql:self.app.productions.put('shot',{**s,'video_mode':'image_to_video','start_frame_asset_id':a['id']})
  record=self.app.agent.record(s['video_id']);record=self.app.agent.patch(record['id'],dict(expected_revision=record['revision'],changes=dict(first=dict(asset_id=a['id']),prompt='Camera stays locked.')))
  self.app.update(signed_in=True);self.app.spawn=lambda *args:None
  path='/agent/v1/scenes/'+record['id']+'/generate';data=dict(expected_revision=record['revision'],approved=True)
  with self.assertRaises(APIError):self.app.agent.dispatch('POST',path,data,'gate-test-once')
  job=self.app.agent.dispatch('POST',path,{**data,'allow_unapproved_start_frame':True},'gate-test-override')[1]
  self.assertTrue(job['allow_unapproved_start_frame']);self.assertNotIn('allow_unapproved_start_frame',self.app.resolve(job['settings']))
 def test_nonblocking_rules_and_unknown_usage(self):
  result=self.app.agent.dispatch('POST','/agent/v1/prompts/check',dict(prompt='Turn screen left. "Hi" "Bye" A card in a pocket.'))[1]
  self.assertFalse(result['blocking']);self.assertTrue({'relative_direction','multiple_lines','prop_contact'}<={w['code'] for w in result['warnings']})
  result=check(self.app,dict(prompt='The camera stays locked.'))
  self.assertEqual(result['warnings'],[])
  status=self.app.agent.dispatch('GET','/agent/v1/usage',{})[1]
  self.assertFalse(status['providers']['grok_video']['readable']);self.assertIn('cannot be read',status['providers']['grok_video']['reason']);self.assertEqual(status['providers']['grok_video']['remaining'],'unknown');self.assertEqual(status['app_generations_today'],{})
 def test_layout_lessons_and_context(self):
  from workflow_tools import layout,lessons,continuity
  key=self.shot['id'];data=dict(expected_revision=0,camera_side='south',characters=[dict(name='Ari',position='left',depth='foreground',facing='right',target='Box')])
  saved=layout(self.app,key,data);self.assertEqual(saved['revision'],1)
  with self.assertRaises(APIError):layout(self.app,key,data)
  with self.assertRaises(APIError):layout(self.app,key,{**data,'expected_revision':1,'characters':[dict(name='Ari',position='bad',depth='foreground',facing='right')]})
  lesson=lessons(self.app,dict(project_id=self.shot['production_id'],failed='Reaching woke the cat',worked='Hands stay at sides',entities=['Ari']),True)
  self.assertEqual(lessons(self.app,dict(query='sides'))[0]['id'],lesson['id'])
  context=continuity(self.app,self.shot,dict(model='grok-imagine-video-1.5',named=[dict(title='Ari')]))
  self.assertEqual(context['relevant_lessons'][0]['id'],lesson['id'])
  self.assertEqual(context['scene_layout']['camera_side'],'south');self.assertEqual(context['shot_end_state']['camera_side'],'south')
 def test_annotation_pose_conflict(self):
  from workflow_tools import annotate
  a=self.app.upload(dict(name='Frame',data_url=PNG));annotate(self.app,a['id'],dict(approved=True,pose={'Ari':'left'}))
  record=self.app.agent.record(self.shot['video_id']);scene={**record['scene'],'first':a,'prompt':'Ari faces right. The camera stays locked.'}
  result=check(self.app,dict(scene=scene,shot_id=self.shot['id']))
  self.assertIn('pose_conflict',[v['code'] for v in result['warnings']])
 def test_duplicate_timeline_migration_and_primary(self):
  e=self.app.editing;t=e.timeline(self.shot['production_id']);old=copy.deepcopy(t)
  # Legacy primary state is supplied on read; stored ID stays intact.
  self.assertTrue(e.timelines()[0]['primary'])
  duplicate=e.dispatch('POST',['timelines',t['id'],'duplicate'],dict(expected_revision=t['revision'],title='Alternative'),None)[1]
  self.assertNotEqual(duplicate['id'],t['id']);self.assertFalse(duplicate['primary']);self.assertEqual(e.p.get(t['id'],'timeline'),old)
  e.dispatch('POST',['timelines',duplicate['id'],'primary'],dict(expected_revision=1),None)
  self.assertEqual(e.timeline(t['production_id'])['id'],duplicate['id'])
  with self.assertRaises(APIError):e.dispatch('POST',['timelines',duplicate['id'],'duplicate'],dict(expected_revision=1),None)
 def test_mirror_image_uses_mocked_ffmpeg_and_preserves_source(self):
  import base64
  from pathlib import Path
  from workflow_tools import mirror
  source=self.app.upload(dict(name='Sign',data_url=PNG));source['known_text']=True
  def ffmpeg(args,**kwargs):
   self.assertIn('hflip',args);Path(args[-1]).write_bytes(base64.b64decode(PNG.split(',')[1]))
  with patch('subprocess.run',side_effect=ffmpeg):result=mirror(self.app,source['id'],{})
  self.assertNotEqual(result['asset']['id'],source['id']);self.assertEqual(result['asset']['mirrored_from'],source['id']);self.assertTrue(result['warnings']);self.assertFalse(result['asset']['approved'])
 def test_mirror_video_copies_audio_and_records_provenance(self):
  from pathlib import Path
  from workflow_tools import mirror
  job=dict(id='video-source',status='done',settings={'model':'external'},mock=True)
  self.app.records=lambda:[job];self.app.download=lambda identity:Path(self.tmp.name)/'source.mp4'
  self.app.editing.upload=lambda data:dict(id='upload-copy',revision=1,video=True)
  def ffmpeg(args,**kwargs):
   self.assertEqual(args[args.index('-c:a')+1],'copy');Path(args[-1]).write_bytes(b'mocked container')
  with patch('subprocess.run',side_effect=ffmpeg):result=mirror(self.app,job['id'],{})
  self.assertEqual(result['take']['mirrored_from'],job['id']);self.assertEqual(result['asset']['mirrored_from'],job['id'])
 def test_speech_ducking_is_bounded_after_normalization(self):
  import array,math,shutil,subprocess,wave
  from pathlib import Path
  from editing_tools import mix_lanes
  if not shutil.which('ffmpeg'):self.skipTest('FFmpeg unavailable')
  speech=Path(__file__).parent/'fixtures/ducking-speech.wav'
  with wave.open(str(speech)) as f:duration=f.getnframes()/f.getframerate()
  music=Path(self.tmp.name)/'music.wav';samples=array.array('h')
  for n in range(round(duration*48000)):samples.extend([0,round(1500*(math.sin(2*math.pi*440*n/48000)+.4*math.sin(2*math.pi*660*n/48000)))])
  with wave.open(str(music),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000);f.writeframes(samples.tobytes())
  def render(amount):
   graph=['[0:a]aresample=48000,pan=stereo|c0=c0|c1=0*c0[voice]']+mix_lanes(dict(dialogue=['[voice]'],music=['[1:a]'],sfx=[]),duration,dict(enabled=True,amount_db=amount,attack_ms=80,release_ms=400),-16)
   self.assertNotIn('loudnorm',';'.join(graph).split('[ducked]')[-1])
   raw=subprocess.run([self.app.editing.ffmpeg,'-v','error','-i',str(speech),'-i',str(music),'-filter_complex',';'.join(graph),'-map','[aout]','-ar','48000','-ac','2','-f','f32le','-'],check=True,capture_output=True).stdout
   out=array.array('f');out.frombytes(raw);return out
  base=render(0)
  def rms(samples,start,channel):
   values=samples[start*2+channel:(start+9600)*2:2];return math.sqrt(sum(v*v for v in values)/len(values))
  # Compare steady speech windows; onset/offset ramps intentionally transition.
  windows=[start for start in range(24000,len(base)//2-24000,9600) if rms(base,start,0)>.04 and rms(base,start-9600,0)>.04]
  self.assertGreater(len(windows),5)
  for amount in (6,10,14,24):
   ducked=render(amount);dips=[20*math.log10(rms(base,start,1)/rms(ducked,start,1)) for start in windows]
   with self.subTest(amount=amount):
    self.assertGreaterEqual(min(dips),amount-2);self.assertLessEqual(max(dips),amount+2)
 def test_all_preflight_warnings_and_clean_bindings(self):
  a=self.app.upload(dict(name='Reference',data_url=PNG))
  for name,category,voice in [('Ari','Character','eve'),('Card','Prop',None)]:self.app.save_reference(dict(title=name,handle=name,category=category,description='',voice=voice,images=[dict(asset_id=a['id'])]))
  record=self.app.agent.create(dict(scene=dict(prompt='Ari says "Hello." Card stays still. The camera stays locked.'),named_references=['Ari','Card']))
  result=check(self.app,dict(scene=record['scene']))
  self.assertEqual(result['warnings'],[])
  scene=copy.deepcopy(record['scene']);scene['prompt']='Ari. Card.'
  self.assertIn('missing_direction',{w['code'] for w in check(self.app,dict(scene=scene))['warnings']})
  scene=copy.deepcopy(record['scene']);scene['prompt']+=' <AUDIO_0>'
  self.assertIn('duplicate_voice',{w['code'] for w in check(self.app,dict(scene=scene))['warnings']})
  scene=copy.deepcopy(record['scene']);scene['voices']=[];scene['named'][0]['voiceId']=None;scene['named'][0]['voice']=None
  self.assertIn('missing_voice',{w['code'] for w in check(self.app,dict(scene=scene))['warnings']})
  clean=check(self.app,dict(prompt='The camera stays locked. A card stays in a pocket. Hands stay off it.'))
  self.assertNotIn('prop_contact',{w['code'] for w in clean['warnings']})
 def test_layout_and_lessons_change_preparation_basis(self):
  from workflow_tools import layout,lessons
  record=self.app.agent.record(self.shot['video_id']);before=self.app.prompting.basis('video',record)
  layout(self.app,self.shot['id'],dict(expected_revision=0,characters=[],camera_side='north'))
  after=self.app.prompting.basis('video',record);self.assertNotEqual(before,after)
  lessons(self.app,dict(project_id=self.shot['production_id'],failed='Camera drifted',worked='Keep camera locked',entities=[]),True)
  self.assertNotEqual(after,self.app.prompting.basis('video',record))
 def test_usage_counts_only_provider_attempts_and_dates_limit_errors(self):
  import time
  self.app.history=[dict(id='real',created_at=time.time(),mock=False,requested_model='grok-imagine-video-1.5',message='HTTP 429 usage limit',limit_error_at=time.time()),dict(id='mock',created_at=time.time(),mock=True,requested_model='grok-imagine-video-1.5')]
  self.app.images.db['jobs']=[dict(id='mirror',created_at=time.time(),mock=False,requested_model='gpt-image-2',mirrored_from='source')]
  value=usage(self.app);self.assertEqual(value['app_generations_today'],{'grok-imagine-video-1.5':1});self.assertEqual(len(value['recent_limit_errors']),1)
 def test_workflow_api_layout_lessons_annotations_and_mirror(self):
  import base64
  from pathlib import Path
  api=self.app.agent
  def call(method,path,data=None):return api.dispatch(method,'/agent/v1/'+path,data or {})[1]
  key=self.shot['id'];self.assertEqual(call('GET','scene-layouts/'+key)['revision'],0)
  self.assertEqual(call('PUT','scene-layouts/'+key,dict(expected_revision=0,characters=[],camera_side='north'))['revision'],1)
  lesson=call('POST','lessons',dict(project_id=self.shot['production_id'],failed='Movement',worked='Hold still',entities=[]))
  self.assertEqual(call('GET','lessons')[0]['id'],lesson['id']);self.assertEqual(call('POST','lessons/search',dict(query='Hold'))[0]['id'],lesson['id'])
  a=self.app.upload(dict(name='Card',data_url=PNG));self.assertTrue(call('POST','assets/'+a['id']+'/annotations',dict(approved=True,known_text=True))['approved'])
  def ffmpeg(args,**kwargs):Path(args[-1]).write_bytes(base64.b64decode(PNG.split(',')[1]))
  with patch('subprocess.run',side_effect=ffmpeg):self.assertTrue(call('POST','assets/'+a['id']+'/mirror')['warnings'])
  t=self.app.editing.timeline(self.shot['production_id']);copy=call('POST','editing/timelines/'+t['id']+'/duplicate',dict(expected_revision=1))
  self.assertEqual(len(call('GET','editing/timelines')),2)
  self.assertTrue(call('POST','editing/timelines/'+copy['id']+'/primary',dict(expected_revision=1))['primary'])
