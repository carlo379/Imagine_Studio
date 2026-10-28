"""Editor v3 validation and pure graphs; local smoke fixtures only."""
import copy, json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock
from studio_server import Studio
from agent_api import APIError
from editing_tools import migrate_timeline,build_export,video_filters,output_size
from editing_studio import timeline_duration

class ToolsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.app=Studio(mock=True,storage=self.tmp.name);self.addCleanup(self.app.productions.sql.close)
  self.e=self.app.editing;self.e.source=Mock(return_value=(dict(video=True,audio=True,duration=10,width=160,height=90),Path('/fixture.mp4')))
  self.c=dict(id='a',source=dict(kind='upload',id='fixture'),**{'in':2,'out':4},volume=1,label='A')
  self.t=dict(title='Edit',clips=[self.c,{**self.c,'id':'b'}],audio=[],titles=[],output=dict(ratio='16:9',resolution='720p',fps=24))
 def graph(self,t=None):
  value=self.e.validate(t or self.t);args=build_export(value,[(Path('/fixture.mp4'),self.e.source.return_value[0])]*(len(value['clips'])+len(value['audio'])));return args[args.index('-filter_complex')+1]
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_ducking_reduces_music_under_dialogue(self):
  import array,math
  root=Path(self.tmp.name);ff=shutil.which('ffmpeg');source=root/'voice.mp4';music=root/'music.wav'
  subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=24:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-shortest','-c:v','libx264','-c:a','aac',str(source)],check=True)
  subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','sine=frequency=880:duration=4',str(music)],check=True)
  clips=[{**self.c,'in':0,'out':2},{**self.c,'id':'silent','in':0,'out':2}]
  t=self.e.validate({**self.t,'clips':clips,'audio':[dict(self.c,id='music',start=0,**{'in':0,'out':4},lane='music')],'output':{**self.t['output'],'ducking':dict(enabled=True,amount_db=12)}})
  args=build_export(t,[(source,dict(video=True,audio=True,duration=2)),(source,dict(video=True,audio=False,duration=2)),(music,dict(audio=True,duration=4))])
  subprocess.run([ff,'-v','error','-y','-filter_complex_threads','1',*args],cwd=root,check=True,timeout=45)
  def rms(at):
   raw=subprocess.run([ff,'-v','error','-i',str(root/'export.mp4'),'-ss',str(at),'-t','0.5','-af','bandpass=f=880:width_type=h:w=40','-ac','1','-f','f32le','-'],capture_output=True,check=True).stdout
   samples=array.array('f');samples.frombytes(raw);return math.sqrt(sum(x*x for x in samples)/len(samples))
  self.assertGreater(20*math.log10(rms(3)/rms(1)),6)
 def test_validation_matrix_for_new_schema(self):
  for patch in [dict(captions=[{}]*2001),dict(markers=[{}]*501),dict(clips=[{**self.c,'unknown':1}]),dict(audio=[dict(self.c,id='music',start=0,lane='voice')]),dict(clips=[{**self.c,'source':dict(kind='gap'),'in':0,'out':61}])]:
   with self.subTest(patch=list(patch)),self.assertRaises(APIError):self.e.validate({**self.t,**patch})
  for style in [dict(mode='cloud'),dict(position='left'),dict(size=10),dict(color='red'),dict(max_chars_per_line=3),dict(max_chars_per_line=32.5),dict(unknown=1)]:
   with self.subTest(style=style),self.assertRaises(APIError):self.e.validate({**self.t,'output':{**self.t['output'],'captions':style}})
  for caption in [dict(id='c',start=0,end=1,text='Hi',speaker='x'*81),dict(id='c',start=0,end=1,text='Hi',unknown=1)]:
   with self.assertRaises(APIError):self.e.validate({**self.t,'captions':[caption]})
 def test_drafts_are_not_latest_delivery(self):
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Deliveries'))[1]['production'];timeline=self.e.timeline(p['id'])
  with self.e.p.sql:
   full=self.e.p.new('export',timeline_id=timeline['id'],snapshot=timeline,quality='full',status='done')
   draft=self.e.p.new('export',timeline_id=timeline['id'],snapshot=timeline,quality='draft',status='done')
  jobs=self.e.dispatch('GET',['exports'],{},None)[1]
  self.assertFalse(next(j for j in jobs if j['id']==draft['id'])['latest_delivery']);self.assertTrue(next(j for j in jobs if j['id']==full['id'])['latest_delivery'])
 def test_audio_defaults_and_migration(self):
  v=migrate_timeline(self.t);self.assertEqual(v['output']['cut_audio_crossfade_frames'],0);self.assertEqual(self.t['output'].keys(),{'ratio','resolution','fps'})
  self.assertNotIn('acrossfade',self.graph());self.assertEqual(timeline_duration(self.t['clips']),4)
 def test_audio_validation_and_graph(self):
  t=copy.deepcopy(self.t);t['output'].update(cut_audio_crossfade_frames=2,loudness_target_lufs=-16,ducking=dict(enabled=True))
  t['clips'][0].update(audio_fade_in=.5,audio_fade_out=.5,normalize=True)
  t['audio']=[dict(self.c,id='music',start=0,lane='music')]
  g=self.graph(t);self.assertIn('acrossfade=d=0.083333',g);self.assertIn('afade=t=out:st=1.5:d=0.5',g);self.assertIn('loudnorm=I=-16:TP=-1.5',g);self.assertIn('sidechaincompress=',g)
  for k,v in [('audio_fade_in',1.1),('audio_fade_out',.01),('audio_offset',3),('normalize',1)]:
   with self.subTest(k=k),self.assertRaises(APIError):self.e.validate({**self.t,'clips':[{**self.c,k:v}]})
  for k,v in [('cut_audio_crossfade_frames',13),('cut_audio_crossfade_frames',True),('loudness_target_lufs',-5),('ducking',{'attack_ms':0}),('ducking',{'release_ms':2001}),('ducking',{'amount_db':25}),('ducking',{'enabled':1})]:
   with self.subTest(k=k,v=v),self.assertRaises(APIError):self.e.validate({**self.t,'output':{**self.t['output'],k:v}})
 def test_offset_keeps_dissolve_and_cut_audio_crossfades(self):
  clips=[self.c,{**self.c,'id':'b','transition':dict(type='dissolve',duration=.5)},{**self.c,'id':'c','audio_offset':.25}]
  g=self.graph({**self.t,'clips':clips,'output':{**self.t['output'],'cut_audio_crossfade_frames':2}})
  self.assertEqual(g.count('acrossfade=d=0.5:'),2)
  self.assertEqual(g.count('acrossfade=d=0.083333:'),2)
  self.assertIn('adelay=3750:all=1',g)
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_ffmpeg_errors_survive_export_and_frame_api(self):
  import threading
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Errors'))[1]['production'];t=self.e.timeline(p['id'])
  saved=self.e.save(t['id'],{**self.t,'expected_revision':1,'output':{**self.t['output'],'resolution':'480p'}})
  self.app.spawn=lambda fn,*args:fn(*args)
  job=self.e.export(t['id'],dict(expected_revision=saved['revision']),'missing-input-export');job=self.e.p.get(job['id'],'export')
  self.assertEqual(job['status'],'error');self.assertIn('fixture.mp4',job['ffmpeg_stderr']);self.assertLessEqual(len(job['ffmpeg_stderr'].splitlines()),40)
  self.assertIn(job['ffmpeg_stderr'],job['error'])
  self.e.file=Mock(return_value=Path(self.tmp.name)/'missing-frame.mp4')
  with self.assertRaisesRegex(APIError,'missing-frame.mp4'):self.e.preview_frame(job['id'],dict(timestamp_s=0,expected_revision=saved['revision']))
  self.assertIn('missing-frame.mp4',self.e.p.get(job['id'],'export')['frame_ffmpeg_stderr'])
 def test_handles_and_delay(self):
  for offset in (-.5,.5):
   t={**self.t,'clips':[{**self.c,'audio_offset':offset}]};self.assertIn('adelay=',self.graph(t))
  for c in ({**self.c,'in':0,'audio_offset':-.5},{**self.c,'out':10,'audio_offset':.5}):
   with self.assertRaisesRegex(APIError,'available'):self.e.validate({**self.t,'clips':[c]})
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_v2_read_migration_save_and_export_are_identical(self):
  source=Path(__file__).resolve().parents[1]/'static/mock-video.mp4';m=self.e.probe(source);self.e.source=Mock(return_value=(m,source))
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Legacy'))[1]['production']
  with self.e.p.sql:old=self.e.p.new('timeline',production_id=p['id'],episode_id=None,title='V2 fixture',clips=[{**self.c,'in':0,'out':1}],audio=[],titles=[],output=dict(ratio='16:9',resolution='720p',fps=24))
  loaded=self.e.timeline(p['id']);self.assertEqual(loaded['output']['cut_audio_crossfade_frames'],0);self.assertNotIn('cut_audio_crossfade_frames',self.e.p.get(old['id'],'timeline')['output'])
  self.app.spawn=lambda fn,*args:fn(*args)
  one=self.e.export(old['id'],dict(expected_revision=1),'v2-before-save');one=self.e.p.get(one['id'],'export');self.assertEqual(one['status'],'done',one.get('error'))
  saved=self.e.save(old['id'],dict(expected_revision=1));two=self.e.export(old['id'],dict(expected_revision=2),'v2-after-save');two=self.e.p.get(two['id'],'export');self.assertEqual(two['status'],'done',two.get('error'))
  self.assertEqual(self.e.file(one['id']).read_bytes(),self.e.file(two['id']).read_bytes())
  restored=self.e.restore_revision(old['id'],1,dict(expected_revision=2));self.assertEqual(restored['revision'],3);self.assertEqual(restored['output']['cut_audio_crossfade_frames'],0)
 def test_markers_revisions_and_color(self):
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Workflow'))[1]['production'];timeline=self.e.timeline(p['id'])
  marker=dict(id='mark',time=2.5,label='Reaction',note='Keep Mira still',color='#aef0ca',clip_id='b',clip_time=.5)
  saved=self.e.save(timeline['id'],dict(expected_revision=1,**self.t,markers=[marker]));self.assertEqual(saved['markers'][0]['time'],2.5)
  clips=copy.deepcopy(saved['clips']);clips[0]['out']=5
  moved=self.e.save(saved['id'],dict(expected_revision=2,clips=clips));self.assertEqual(moved['markers'][0]['time'],3.5)
  versions=self.e.revisions(saved['id']);self.assertEqual([v['revision'] for v in versions],[3,2,1])
  restored=self.e.restore_revision(saved['id'],2,dict(expected_revision=3));self.assertEqual(restored['revision'],4);self.assertEqual(restored['clips'],saved['clips'])
  with self.assertRaises(APIError) as err:self.e.restore_revision(saved['id'],1,dict(expected_revision=3))
  self.assertEqual(err.exception.status,409)
  for changes in [dict(note='x'*2001),dict(label='x'*81),dict(color='purple'),dict(clip_id='missing'),dict(clip_time=9)]:
   with self.assertRaises(APIError):self.e.validate({**self.t,'markers':[{**marker,**changes}]})
  self.assertIn('eq=brightness=0.2:contrast=1:saturation=1,colorbalance=rs=0.1:bs=-0.1',self.graph({**self.t,'clips':[{**self.c,'color':dict(brightness=.2,temperature=.5)}]}))
  for field,value in [('brightness',1),('contrast',3),('saturation',-1),('temperature',2)]:
   with self.assertRaises(APIError):self.e.validate({**self.t,'clips':[{**self.c,'color':{field:value}}]})
 def test_take_selection_reuses_production_rules(self):
  outline=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Takes'))[1];shot=outline['shots'][0]
  # Both detailed and compact production reads use this shared history.
  self.app.history.append(dict(id='take-one',status='done',video={'url':'unused'},created_at=1,settings={'_studio_video_id':shot['video_id']}))
  result=self.e.dispatch('POST',['takes','select'],dict(shot_id=shot['id'],take_id='take-one',expected_shot_revision=shot['revision']),None)[1]
  self.assertEqual(result['selected_video'],'take-one')
  sources=self.e.sources(outline['production']['id'],None);self.assertTrue(sources['takes'][0]['selected'])
  with self.assertRaises(APIError) as err:self.e.dispatch('POST',['takes','select'],dict(shot_id=shot['id'],take_id='take-one',expected_shot_revision=shot['revision']),None)
  self.assertEqual(err.exception.status,409)
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_phase4_smoke(self):
  import array
  root=Path(self.tmp.name);source=Path(__file__).resolve().parents[1]/'static/mock-video.mp4';m=self.e.probe(source);self.e.source=Mock(return_value=(m,source))
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Color'))[1]['production'];timeline=self.e.timeline(p['id'])
  settings={**self.t,'clips':[{**self.c,'in':0,'out':1,'color':dict(brightness=.2)}],'markers':[dict(id='m',time=.5,label='Hold',note='Still')],'output':dict(ratio='16:9',resolution='source',fps=24)}
  saved=self.e.save(timeline['id'],dict(expected_revision=1,**settings));self.app.spawn=lambda fn,*args:fn(*args);job=self.e.export(saved['id'],dict(expected_revision=2),'color-smoke');job=self.e.p.get(job['id'],'export');self.assertEqual(job['status'],'done',job.get('error'))
  self.assertEqual(json.loads(self.e.file(job['id'],True).read_text())['markers'][0]['note'],'Still')
  def mean(path):
   raw=subprocess.run([self.e.ffmpeg,'-v','error','-i',str(path),'-ss','0.2','-frames:v','1','-pix_fmt','gray','-f','rawvideo','-'],capture_output=True,check=True).stdout;return sum(raw)/len(raw)
  self.assertGreater(mean(self.e.file(job['id'])),mean(source)+10)
 def test_captions_sizes_and_draft_graphs(self):
  from editing_captions import to_srt,from_srt
  from editing_tools import output_size
  cue=dict(id='caption-1',start=0,end=1,text='Hello world',speaker='Eve')
  self.assertEqual(from_srt(to_srt([cue])),[cue])
  self.assertEqual(output_size({**self.t,'output':{**self.t['output'],'resolution':'480p'}},[]),(848,480))
  for ratio,size in [('16:9',(848,480)),('9:16',(480,848)),('1:1',(480,480))]:self.assertEqual(output_size({**self.t,'output':dict(ratio=ratio,resolution='480p')},[]),size)
  self.assertEqual(output_size({**self.t,'output':dict(ratio='16:9',resolution='source')},[(None,dict(video=True,width=853,height=481))]),(852,480))
  args=build_export(self.e.validate(self.t),[(Path('/fixture'),self.e.source.return_value[0])]*2,quality='draft');self.assertIn('ultrafast',args);self.assertIn('30',args);self.assertIn('scale=640:360',args[args.index('-filter_complex')+1])
  for cue in [dict(id='bad',start=0,end=9,text='Too late'),dict(id='bad',start=1,end=0,text='Backwards'),dict(id='bad',start=0,end=1,text='')]:
   with self.assertRaises(APIError):self.e.validate({**self.t,'captions':[cue]})
 def test_local_transcription_and_missing_engine(self):
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Captions'))[1]['production'];timeline=self.e.timeline(p['id'])
  saved=self.e.save(timeline['id'],dict(expected_revision=1,**self.t));self.e.transcriber_available=lambda:False
  with self.assertRaises(APIError) as error:self.e.transcribe(saved['id'],dict(expected_revision=saved['revision']))
  self.assertEqual(error.exception.status,503);self.assertEqual(error.exception.code,'transcriber_unavailable')
  self.e.transcriber=lambda path:[dict(start=2.2,end=2.8,text='Hello')];self.e.transcriber_available=lambda:True;self.app.spawn=lambda fn,*args:fn(*args)
  job=self.e.transcribe(saved['id'],dict(expected_revision=saved['revision']));self.assertEqual(job['status'],'done',job.get('error'))
  result=self.e.p.get(saved['id'],'timeline');self.assertAlmostEqual(result['captions'][0]['start'],.2)
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_phase3_smoke(self):
  root=Path(self.tmp.name);source=Path(__file__).resolve().parents[1]/'static/mock-video.mp4';m=self.e.probe(source)
  p=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Caption export'))[1]['production'];timeline=self.e.timeline(p['id'])
  self.e.source=Mock(return_value=(m,source));c={**self.c,'in':0,'out':1};settings={**self.t,'clips':[c],'captions':[dict(id='caption',start=0,end=1,text='Hello Eve')],'output':dict(ratio='16:9',resolution='480p',fps=24,captions=dict(mode='both'))}
  saved=self.e.save(timeline['id'],dict(expected_revision=1,**settings));self.app.spawn=lambda fn,*args:fn(*args)
  job=self.e.export(saved['id'],dict(expected_revision=saved['revision']),'caption-smoke');job=self.e.p.get(job['id'],'export');self.assertEqual(job['status'],'done',job.get('error'))
  self.assertEqual((job['media']['width'],job['media']['height']),(848,480));self.assertIn('Hello Eve',self.e.dispatch('GET',['exports',job['id'],'captions.srt'],{},None)[1][0].decode())
  self.assertIn('captions.srt',json.loads(self.e.file(job['id'],True).read_text())['export_files'])
 def test_picture_graph_and_validation(self):
  c={**self.c,'flip_h':True,'flip_v':True,'crop':dict(x=.1,y=.1,w=.5,h=.5),'zoom':dict(scale=2,x=.4,y=.6),'speed':.25,'hold_start':.5,'hold_end':.5}
  g=self.graph({**self.t,'clips':[c]});self.assertIn('hflip,vflip,crop=iw*0.5',g);self.assertIn('setpts=(PTS-STARTPTS)/0.25',g);self.assertIn('atempo=0.5,atempo=0.5',g);self.assertIn('tpad=start_mode=clone:start_duration=0.5',g)
  self.assertEqual(timeline_duration([c]),9)
  for k,v in [('flip_h',1),('crop',dict(x=.9,y=0,w=.5,h=1)),('crop',dict(x=0,y=0,w=.01,h=1)),('zoom',dict(scale=4,x=.5,y=.5)),('speed',0),('speed_audio','fast'),('hold_end',.01),('hold_start',11)]:
   with self.subTest(k=k),self.assertRaises(APIError):self.e.validate({**self.t,'clips':[{**self.c,k:v}]})
  gap={**self.c,'source':{'kind':'gap'},'in':0,'out':.25};self.assertIn('color=c=#000000',str(build_export(self.e.validate({**self.t,'clips':[gap]}),[(None,dict(video=True,audio=False))])))
 def test_picture_normalization_order_at_every_output_size(self):
  clip={**self.c,'zoom':dict(scale=1.3,x=.5,y=.5),'hold_start':.5,'hold_end':.5}
  for resolution in ('480p','720p','1080p','source'):
   for ratio in ('16:9','9:16','1:1'):
    for quality in ('full','draft'):
     with self.subTest(resolution=resolution,ratio=ratio,quality=quality):
      t={**self.t,'output':dict(resolution=resolution,ratio=ratio,fps=24)}
      w,h=output_size(t,[(None,dict(video=True,width=853,height=481))],quality)
      self.assertEqual((w%2,h%2),(0,0))
      filters=video_filters(clip,w,h,24)
      self.assertEqual(filters[-1],'setsar=1')
      self.assertLess(filters.index('fps=24'),next(i for i,f in enumerate(filters) if f.startswith('tpad=')))
      self.assertIn(f'crop={w}:{h}:',','.join(filters))
 @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg/ffprobe missing')
 def test_480p_zoom_segments_have_square_pixels_and_join(self):
  root=Path(self.tmp.name);source=Path(__file__).resolve().parents[1]/'static/mock-video.mp4';m=self.e.probe(source)
  self.e.source=Mock(return_value=(m,source))
  clips=[{**self.c,'in':0,'out':.5,'zoom':dict(scale=1.3,x=.5,y=.5)},{**self.c,'id':'b','in':0,'out':.5}]
  # Probe each segment as well as the joined full export: a join alone can hide
  # accidental output-SAR overrides without correcting the individual inputs.
  for name,segments in [('zoom',clips[:1]),('plain',clips[1:]),('joined',clips)]:
   with self.subTest(segment=name):
    t=self.e.validate({**self.t,'clips':segments,'output':dict(ratio='16:9',resolution='480p',fps=24)})
    args=build_export(t,[(source,m)]*len(segments))
    subprocess.run([self.e.ffmpeg,'-v','error','-y','-filter_complex_threads','1',*args],cwd=root,check=True,timeout=45,capture_output=True)
    stream=json.loads(subprocess.run([self.e.ffprobe,'-v','error','-select_streams','v:0','-count_frames','-show_streams','-of','json',str(root/'export.mp4')],check=True,capture_output=True).stdout)['streams'][0]
    self.assertEqual((stream['width'],stream['height']),(848,480));self.assertEqual(stream['sample_aspect_ratio'],'1:1')
    self.assertEqual(int(stream['nb_read_frames']),12*len(segments))
 @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg/ffprobe missing')
 def test_holds_have_exact_frames_and_match_audio_duration(self):
  root=Path(self.tmp.name);fixture=Path(__file__).resolve().parents[1]/'static/mock-video.mp4';source=root/'with-audio.mp4'
  # Copy existing picture with a local test tone, so A/V sync is checked against
  # an actual source audio track rather than the editor's silent-source fallback.
  subprocess.run([self.e.ffmpeg,'-v','error','-y','-i',str(fixture),'-f','lavfi','-i','sine=frequency=440:duration=3','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-shortest',str(source)],check=True,capture_output=True,timeout=45)
  m=self.e.probe(source)
  self.e.source=Mock(return_value=(m,source))
  # Includes the original phase-2 case (12 moving + 6 + 6 hold frames),
  # start/end separately, slower playback, and a different output frame rate.
  for path,metadata in [(source,m),(fixture,{**m,'audio':False})]:
   for fps,speed,start,end in [(24,2,.25,.25),(24,1,.5,0),(24,1,0,.5),(24,.5,.5,.5),(30,2,.5,0),(30,2,0,.5),(30,2,.5,.5)]:
    with self.subTest(source_audio=metadata['audio'],fps=fps,speed=speed,hold_start=start,hold_end=end):
     clip={**self.c,'in':0,'out':1,'speed':speed,'hold_start':start,'hold_end':end}
     t=self.e.validate({**self.t,'clips':[clip],'output':dict(ratio='1:1',resolution='480p',fps=fps)})
     args=build_export(t,[(path,metadata)])
     if start:self.assertIn(f'adelay={round(start*1000)}:all=1,asetpts=N/SR/TB',args[args.index('-filter_complex')+1])
     subprocess.run([self.e.ffmpeg,'-v','error','-y','-filter_complex_threads','1',*args],cwd=root,check=True,timeout=45,capture_output=True)
     streams=json.loads(subprocess.run([self.e.ffprobe,'-v','error','-count_frames','-show_streams','-of','json',str(root/'export.mp4')],check=True,capture_output=True).stdout)['streams']
     video=next(s for s in streams if s['codec_type']=='video');audio=next(s for s in streams if s['codec_type']=='audio')
     expected=round((1/speed+start+end)*fps)
     self.assertEqual(int(video['nb_read_frames']),expected)
     self.assertAlmostEqual(float(video['duration']),expected/fps,places=5)
     self.assertLessEqual(abs(float(video['duration'])-float(audio['duration'])),1/fps)
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_phase2_smoke(self):
  import io
  from PIL import Image,ImageChops
  root=Path(self.tmp.name);ff=shutil.which('ffmpeg');source=root/'pattern.mp4'
  subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x90:r=24:d=2,drawbox=x=0:y=0:w=80:h=90:color=red:t=fill','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True)
  c={**self.c,'in':0,'out':1,'flip_h':True,'speed':2,'hold_start':.25,'hold_end':.25}
  gap={**self.c,'id':'gap','source':dict(kind='gap'),'in':0,'out':.25}
  last={**self.c,'id':'zoom','in':0,'out':1,'crop':dict(x=.25,y=0,w=.5,h=1),'zoom':dict(scale=1.5,x=.5,y=.5)}
  t=self.e.validate({**self.t,'clips':[c,gap,last]});args=build_export(t,[(source,dict(video=True,audio=False,duration=2)),(None,dict(video=True,audio=False)),(source,dict(video=True,audio=False,duration=2))])
  subprocess.run([ff,'-v','error','-y','-filter_complex_threads','1',*args],cwd=root,check=True,timeout=45)
  self.assertAlmostEqual(self.e.probe(root/'export.mp4')['duration'],2.25,delta=.1)
  video=json.loads(subprocess.run([self.e.ffprobe,'-v','error','-select_streams','v:0','-count_frames','-show_streams','-of','json',str(root/'export.mp4')],capture_output=True,check=True).stdout)['streams'][0]
  self.assertEqual(int(video['nb_read_frames']),54)
  def frame(at):return Image.open(io.BytesIO(subprocess.run([ff,'-v','error','-i',str(root/'export.mp4'),'-ss',str(at),'-frames:v','1','-f','image2pipe','-vcodec','png','-'],capture_output=True,check=True).stdout)).convert('RGB')
  a=frame(.05);self.assertGreater(a.getpixel((100,300))[2],200);self.assertGreater(a.getpixel((1100,300))[0],200)
  self.assertIsNone(ImageChops.difference(a,frame(.2)).getbbox())
  self.assertLess(sum(frame(1.1).getpixel((640,360))),20)
 @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg missing')
 def test_phase1_smoke(self):
  root=Path(self.tmp.name);source=root/'tone.mp4';ff=shutil.which('ffmpeg')
  subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=24:d=5','-f','lavfi','-i','sine=frequency=440:duration=5','-shortest','-c:v','libx264','-c:a','aac',str(source)],check=True)
  t=migrate_timeline(self.t);t['output']['cut_audio_crossfade_frames']=2;t['output']['loudness_target_lufs']=-16;t['clips'][1]['volume']=.25
  args=build_export(t,[(source,self.e.source.return_value[0])]*2)
  subprocess.run([ff,'-v','error','-y','-filter_complex_threads','1',*args],cwd=root,check=True,timeout=45)
  info=self.e.probe(root/'export.mp4');self.assertAlmostEqual(info['duration'],4,delta=.1)
  import array
  raw=subprocess.run([ff,'-v','error','-i',str(root/'export.mp4'),'-ss','1.96','-t','0.15','-ac','1','-ar','48000','-f','f32le','-'],capture_output=True,check=True).stdout
  samples=array.array('f');samples.frombytes(raw);self.assertLess(max(abs(a-b) for a,b in zip(samples,samples[1:])),.05)
  self.assertAlmostEqual(self.e.loudness(root/'export.mp4'),-16,delta=1.5)
  t['clips'][1]['audio_offset']=-.5
  args=build_export(t,[(source,self.e.source.return_value[0])]*2);self.assertIn('adelay=1500:all=1',args[args.index('-filter_complex')+1])
  subprocess.run([ff,'-v','error','-y','-filter_complex_threads','1',*args],cwd=root,check=True,timeout=45)
  self.assertAlmostEqual(self.e.probe(root/'export.mp4')['duration'],4,delta=.1)
