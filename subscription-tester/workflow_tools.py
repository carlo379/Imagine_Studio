"""Local workflow checks. No provider calls or visual inference."""
import copy,json,re,time
from collections import Counter
from datetime import datetime
from pathlib import Path
from agent_api import APIError

RULES=Path(__file__).with_name('prompt_check_rules.json')
def shot_for(app,identity):
 return next((s for s in app.productions.all('shot') if s.get('video_id')==identity and not s.get('archived')),None)

def start_frame_gate(app,settings):
 shot=shot_for(app,settings.get('_studio_video_id'))
 image=settings.get('image') or {};asset_id=image.get('asset_id') if isinstance(image,dict) else None
 saved_first=(app.agent.record(shot['video_id'])['scene'].get('first') or {}) if shot else {}
 required=bool(shot and (shot.get('video_mode')=='image_to_video' or image or saved_first))
 missing=[];asset=None
 if required:
  if not asset_id:missing.append('Name the attached start frame with image.asset_id.')
  else:
   try:asset,_=app.asset(asset_id)
   except ValueError:missing.append('The named start-frame asset is missing.')
   attached=shot.get('start_frame_asset_id') or shot.get('selected_image') or saved_first.get('id')
   if not attached or attached!=asset_id:missing.append('Attach this start-frame asset to this shot first.')
   if asset and asset.get('approved') is not True:missing.append('Approve the attached start-frame asset first.')
 override=settings.get('allow_unapproved_start_frame',False)
 if type(override) is not bool:raise APIError('invalid_override','allow_unapproved_start_frame must be boolean.')
 # Override bypasses approval only, never attachment or an unnamed request.
 if override:missing=[m for m in missing if not m.startswith('Approve ')]
 return dict(required=required,allowed=not missing,missing=missing,asset=copy.deepcopy(asset),override=override)

def check(app,data):
 if set(data)-{'scene_id','scene','prompt','shot_id'}:raise APIError('invalid_check','Use scene_id, scene, prompt or shot_id.')
 if data.get('scene') is not None and not isinstance(data['scene'],dict):raise APIError('invalid_check','scene must be an object.')
 scene=copy.deepcopy(data.get('scene') or (app.agent.record(data['scene_id'])['scene'] if data.get('scene_id') else {}))
 prompt=data.get('prompt',scene.get('prompt',''))
 if not isinstance(prompt,str) or len(prompt)>50000:raise APIError('invalid_prompt','Use prompt text up to 50000 characters.')
 shot=app.productions.get(data['shot_id'],'shot') if data.get('shot_id') else shot_for(app,data.get('scene_id'))
 if not scene and shot:
  scene=copy.deepcopy(app.agent.record(shot['video_id'])['scene'])
  if 'prompt' not in data:prompt=scene.get('prompt','')
 if scene.get('model'):scene=app.agent.normalize(scene)
 rules=json.loads(RULES.read_text());warnings=[]
 def warn(code,**values):warnings.append(dict(code=code,severity='warning',message=rules[code].format(**values)))
 body=prompt.partition('\n\n')[2] if prompt.startswith('Reference identities:\n') else prompt
 clauses=re.split(r'[.!?;\n]',body)
 for asset in scene.get('named',[]):
  name=asset.get('title') or asset.get('handle','');aliases=[name,asset.get('handle',''),name.split()[0] if name else '']
  mentions=[c for c in clauses if any(re.search(r'(?<!\w)'+re.escape(n)+r'(?!\w)',c,re.I) for n in aliases if n)]
  if asset.get('category') in ('Character','Prop') and asset.get('images') and not any(re.search(rules['action_words'],c,re.I) for c in mentions):warn('missing_direction',name=name)
  if any(re.search(re.escape(n)+r'.{0,30}(?:says|asks|whispers|shouts|speaks|:\s*[“"])',body,re.I) for n in aliases if n):
   if scene.get('audio') is False or not asset.get('voiceId') or not any(v.get('id')==asset.get('voiceId') for v in scene.get('voices',[])):warn('missing_voice',name=name)
 if not re.search(r'\bcamera\b.{0,70}'+rules['action_words'],body,re.I):warn('missing_direction',name='The camera')
 for rule in rules['text_rules']:
  if len(re.findall(rule['pattern'],body,re.I))>=rule.get('min_matches',1) and not (rule.get('unless') and re.search(rule['unless'],body,re.I)):warnings.append(dict(code=rule['code'],severity='warning',message=rule['message']))
 # Compile authored snapshots to check actual header bindings, never demand tags in the body.
 final=app.agent.expanded_prompt({**scene,'prompt':prompt}) if scene.get('model') else prompt
 for tag,count in Counter(re.findall(r'<AUDIO_\d+>',final)).items():
  if count>1:warn('duplicate_voice',tag=tag)
 context=continuity(app,shot,scene)
 for c in context.get('scene_layout',{}).get('characters',[]):
  if c['name'] not in [a.get('title') for a in scene.get('named',[])]:
   mentions=[v for v in clauses if re.search(r'(?<!\w)'+re.escape(c['name'])+r'(?!\w)',v,re.I)]
   if not any(re.search(rules['action_words'],v,re.I) for v in mentions):warn('missing_direction',name=c['name'])
 for lesson in context.get('relevant_lessons',[]):warnings.append(dict(code='lesson',severity='warning',message=lesson['worked'],lesson_id=lesson['id']))
 if shot:
  frame=scene.get('first') or {};asset=next((a for a in app.assets if a['id']==frame.get('id')),{});pose=asset.get('pose',{})
  for name,facing in pose.items():
   matches=re.findall(re.escape(name)+r'.{0,30}faces? (left|right|front|back)',body,re.I)
   if matches and any(f.casefold()!=facing for f in matches):warn('pose_conflict')
 return dict(usage=usage(app),context=context,warnings=warnings,blocking=False,guide='docs/prompting-guides/Grok_Imagine_Prompting_Guide.md')

def usage(app):
 today=datetime.now().astimezone().date();counts={};limits=[]
 jobs=app.records()+app.images.db.get('jobs',[])
 for job in jobs:
  timestamp=job.get('created_at',0)
  if not isinstance(timestamp,(int,float)):continue
  model=job.get('requested_model') or job.get('model') or job.get('settings',{}).get('model') or job.get('draft',{}).get('settings',{}).get('model','unknown')
  if datetime.fromtimestamp(timestamp).astimezone().date()==today and not job.get('mock') and not job.get('imported_media_id') and not job.get('mirrored_from'):counts[model]=counts.get(model,0)+1
  message=str(job.get('error') or job.get('message') or '')
  if job.get('limit_error_at') or re.search(r'quota|rate.?limit|usage.?limit|HTTP 429',message,re.I):limits.append(dict(model=model,timestamp=job.get('limit_error_at',timestamp),message='Provider recently returned a limit/quota error.'))
 return dict(date=str(today),timezone=str(datetime.now().astimezone().tzinfo),providers={p:dict(remaining='unknown',used_today='unknown',readable=False,reason='Remaining subscription allowance cannot be read by Studio: the subscription bridge does not expose a numeric media allowance.') for p in ('grok_video','grok_image','chatgpt_image')},app_generations_today=counts,recent_limit_errors=[v for v in limits if time.time()-v['timestamp']<86400])

def layout(app,identity,data=None):
 p=app.productions
 known={s['id'] for s in p.all('shot')}|{s.get('story_scene_id') for s in p.all('shot')}
 for episode in app.stories.db.get('episodes',[]):known.update(s['id'] for s in episode.get('scenes',[]))
 if identity not in known:raise APIError('not_found','Scene or shot not found.',404)
 old=next((r for r in p.all('scene-layout') if r['scene_id']==identity),None)
 if data is None:return old or dict(scene_id=identity,revision=0,characters=[],camera_side='unspecified')
 if set(data)-{'expected_revision','characters','camera_side'} or type(data.get('expected_revision')) is not int or data['expected_revision']!=(old or {}).get('revision',0):raise APIError('revision_conflict','Reload layout before saving.',409)
 characters=data.get('characters',[]);side=data.get('camera_side','unspecified')
 if not isinstance(side,str) or len(side)>120 or not isinstance(characters,list) or len(characters)>50:raise APIError('invalid_layout','Use at most 50 positions and a camera side up to 120 characters.')
 names=set()
 for c in characters:
  if not isinstance(c,dict) or set(c)-{'name','position','depth','facing','target'}:raise APIError('invalid_layout','Use name, position, depth, facing and target.')
  if not isinstance(c.get('name'),str) or not 1<=len(c['name'])<=120 or c['name'].casefold() in names:raise APIError('invalid_layout','Names must be distinct, 1–120 characters.')
  names.add(c['name'].casefold())
  if c.get('position') not in ('left','center','right') or c.get('depth') not in ('foreground','background') or c.get('facing') not in ('left','right','front','back') or not isinstance(c.get('target',''),str) or len(c.get('target',''))>120:raise APIError('invalid_layout','Choose left/center/right, foreground/background and own left/right/front/back.')
 with p.sql:
  return p.put('scene-layout',{**old,'revision':old['revision']+1,'characters':characters,'camera_side':side}) if old else p.new('scene-layout',scene_id=identity,characters=characters,camera_side=side)

def lessons(app,data=None,create=False):
 p=app.productions;data=data or {}
 if create:
  if set(data)-{'project_id','failed','worked','entities','shot_type','model','source_take','date'}:raise APIError('invalid_lesson','Use documented lesson fields.')
  if data.get('project_id'):p.get(data['project_id'],'production')
  for key in ('failed','worked'):
   if not isinstance(data.get(key),str) or not 1<=len(data[key].strip())<=4000:raise APIError('invalid_lesson','Record what failed and what worked (1–4000 characters each).')
  entities=data.get('entities',[])
  if not isinstance(entities,list) or len(entities)>30 or any(not isinstance(e,str) or not 1<=len(e)<=120 for e in entities):raise APIError('invalid_lesson','Use up to 30 entity names.')
  for key in ('model','shot_type','source_take'):
   if data.get(key) is not None and (not isinstance(data[key],str) or len(data[key])>120):raise APIError('invalid_lesson',key+' must be text up to 120 characters.')
  if data.get('source_take') and not any(j['id']==data['source_take'] for j in app.records()):raise APIError('invalid_lesson','Source take not found.')
  date=data.get('date',datetime.now().astimezone().date().isoformat())
  try:datetime.strptime(date,'%Y-%m-%d')
  except (ValueError,TypeError):raise APIError('invalid_lesson','Use an ISO calendar date.') from None
  with p.sql:return p.new('workflow-lesson',**{**data,'entities':entities,'date':date,'project_id':data.get('project_id')})
 if set(data)-{'project_id','query','model','entities','shot_type'}:raise APIError('invalid_lesson','Search with project_id, query, model or entities.')
 result=p.all('workflow-lesson')
 if data.get('project_id'):result=[r for r in result if r.get('project_id') in (None,data['project_id'])]
 if data.get('model'):result=[r for r in result if not r.get('model') or r['model']==data['model']]
 if 'shot_type' in data:result=[r for r in result if not r.get('shot_type') or r['shot_type']==data['shot_type']]
 if data.get('entities'):
  names={n.casefold() for n in data['entities']};result=[r for r in result if not r['entities'] or names.intersection(n.casefold() for n in r['entities'])]
 if data.get('query'):
  if not isinstance(data['query'],str):raise APIError('invalid_lesson','Query must be text.')
  result=[r for r in result if data['query'].casefold() in json.dumps(r,ensure_ascii=False).casefold()]
 return result[-200:]

def continuity(app,shot,scene):
 if not shot:return {}
 p=app.productions;sid=shot.get('story_scene_id') or shot['id']
 base=layout(app,sid)
 previous=sorted((s for s in p.all('shot') if s.get('story_scene_id')==shot.get('story_scene_id') and s['production_id']==shot['production_id'] and not s.get('archived') and s.get('shot_order',0)<shot.get('shot_order',0)),key=lambda s:s.get('shot_order',0))
 end=layout(app,previous[-1]['id']) if previous else None
 return dict(scene_layout=base,shot_end_state=layout(app,shot['id']),previous_shot_end_state=end,relevant_lessons=lessons(app,dict(project_id=shot['production_id'],model=scene.get('model'),shot_type=shot.get('shot_type'),entities=[v for n in scene.get('named',[]) for v in (n.get('title',''),n.get('handle','')) if v])))

def annotate(app,identity,data):
 if set(data)-{'approved','known_text','pose'}:raise APIError('invalid_annotation','Use approved, known_text and pose.')
 try:asset,_=app.asset(identity)
 except ValueError:
  if set(data)!={'known_text'} or type(data['known_text']) is not bool:raise APIError('invalid_annotation','Video annotations accept known_text boolean only.')
  original=next((j for j in app.history if j['id']==identity),None)
  if original is not None:
   original['known_text']=data['known_text'];app.agent.save(app.history_path,app.history);return copy.deepcopy(original)
  original=app.productions.get(identity,'imported-video');original['known_text']=data['known_text']
  with app.productions.sql:return app.productions.put('imported-video',original)
 if 'approved' in data and type(data['approved']) is not bool:raise APIError('invalid_annotation','Approved must be boolean.')
 if 'known_text' in data and type(data['known_text']) is not bool:raise APIError('invalid_annotation','known_text must be boolean.')
 pose=data.get('pose',{})
 if not isinstance(pose,dict) or len(pose)>50 or any(not isinstance(k,str) or not isinstance(v,str) or len(k)>120 or v not in ('left','right','front','back') for k,v in pose.items()):raise APIError('invalid_annotation','Pose maps names to left/right/front/back.')
 with app.lock:
  asset.update(copy.deepcopy(data));app.agent.save(app.assets_path,app.assets)
 return copy.deepcopy(asset)

def mirror(app,identity,data):
 import base64,subprocess,tempfile
 if set(data)-{'expected_shot_revision'}:raise APIError('invalid_mirror','Only expected_shot_revision is accepted for a take.')
 job=next((j for j in app.records() if j['id']==identity and j['status']=='done'),None)
 shot=shot_for(app,job.get('settings',{}).get('_studio_video_id')) if job else None
 if job:
  if shot:app.productions.check(shot,dict(expected_revision=data.get('expected_shot_revision')))
  source=job;path=app.download(identity)
 else:source,path=app.asset(identity)
 if not app.editing.ffmpeg:raise APIError('mirror_unavailable','Install FFmpeg to mirror local media.',503)
 with tempfile.TemporaryDirectory(prefix='studio-mirror-') as temp:
  target=Path(temp)/('mirror.mp4' if job else 'mirror.png')
  args=[app.editing.ffmpeg,'-v','error','-nostdin','-y','-i',str(path),'-vf','hflip']
  args+=['-map','0:v:0','-map','0:a?','-c:v','libx264','-crf','20','-c:a','copy'] if job else ['-frames:v','1']
  try:subprocess.run([*args,str(target)],capture_output=True,check=True,timeout=180)
  except (OSError,subprocess.SubprocessError):raise APIError('mirror_failed','Local mirror failed; source media is intact.',503) from None
  raw=target.read_bytes()
  if job:
   asset=app.editing.upload(dict(name='Mirrored video.mp4',base64=base64.b64encode(raw).decode()))
   with app.productions.sql:
    asset.update(mirrored_from=identity,known_text=source.get('known_text',False));app.productions.put('edit-media',asset)
   if shot:
    result=app.productions.dispatch('POST',['shots',shot['id'],'import-video'],dict(expected_revision=shot['revision'],media_id=asset['id'],source_label='Mirrored from '+identity,select=False))[1]
    take=result['take'];take['mirrored_from']=identity
    with app.productions.sql:app.productions.put('imported-video',take)
   else:
    with app.productions.sql:take=app.productions.new('imported-video',status='done',mock=app.mock,imported_media_id=asset['id'],mirrored_from=identity,settings=copy.deepcopy(job['settings']),video='/api/video-media/local',requested_model='local-mirror')
    take['video']='/api/video-media/'+take['id']
    with app.productions.sql:app.productions.put('imported-video',take)
   return dict(asset=asset,take=take,warnings=['Known on-screen text will be reversed.'] if source.get('known_text') else [])
  asset=app.upload(dict(name='Mirrored '+source.get('name','image'),data_url='data:image/png;base64,'+base64.b64encode(raw).decode()))
  asset.update(mirrored_from=identity,approved=False,generated=source.get('generated',False),known_text=source.get('known_text',False),source_shot_id=source.get('source_shot_id'),source_video_job_id=source.get('source_video_job_id'))
  for shot_record in app.productions.all('shot'):
   if shot_record.get('selected_image')==identity or shot_record.get('start_frame_asset_id')==identity:asset['source_shot_id']=shot_record['id']
  original_job=next((j for j in app.images.db.get('jobs',[]) if j['id']==source.get('image_job_id')),None)
  if original_job:
   import uuid
   derived={**copy.deepcopy(original_job),'id':uuid.uuid4().hex,'created_at':time.time(),'outputs':[asset],'status':'done','mirrored_from':identity,'key':None,'message':'Local mirror; no provider usage.'}
   asset['image_job_id']=derived['id'];app.images.db['jobs'].append(derived);app.images.persist()
  app.agent.save(app.assets_path,app.assets)
  return dict(asset=asset,warnings=['Known on-screen text will be reversed.'] if source.get('known_text') else [])
