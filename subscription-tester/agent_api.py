"""Versioned local agent interface and shared scene storage. No provider credentials exposed."""
import base64
import copy
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from video_rules import MODELS, RATIOS, VOICES, image_input, MODEL_CAPABILITIES, reference_scene, prompt_size

class APIError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message); self.code=code; self.status=status


def blank():
    return dict(model=MODELS[0],duration=5,ratio='16:9',resolution='480p',prompt='',audio=True,
                refs=[],first=None,last=None,voices=[],keys=[],named=[],recording=None)

class AgentAPI:
    def __init__(self, app, config, save):
        self.app,self.config,self.save=app,config,save
        self.lock=threading.RLock()
        self.path=app.storage/'scenes.json'
        self.db=json.loads(self.path.read_text()) if self.path.exists() else {'current_id':None,'scenes':[]}
        self.db.setdefault('urls',[])
        migrated=False
        for source in self.db['urls']:
            if 'url_id' not in source:
                source.update(url_id=uuid.uuid4().hex,revision=1,archived=False);migrated=True
        if migrated:self.save(self.path,self.db)
        self.token_path=app.storage/'agent-token'
        self.token_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            with self.token_path.open('x') as f:
                self.token_path.chmod(0o600);f.write(secrets.token_urlsafe(32))
        except FileExistsError: pass
        self.token_path.chmod(0o600)
        self.token=self.token_path.read_text().strip()

    def authorized(self, header):
        return hmac.compare_digest(header or '', 'Bearer '+self.token)

    def source(self, value):
        if value is None:return None
        if not isinstance(value,dict):raise APIError('invalid_source','An image needs asset_id or url.')
        identity=value.get('asset_id') or value.get('id')
        if identity:
            asset,path=self.app.asset(identity)
            from candidate_review import available
            available(asset)
            if not path.exists():raise APIError('missing_asset','The image file is missing.')
            return copy.deepcopy(asset)
        url=value.get('url') or value.get('src')
        image_input({'url':url})
        return {'src':url,'name':str(value.get('name','Image URL'))[:120]}

    def normalize(self, scene):
        if not isinstance(scene,dict) or set(scene)-set(blank()):
            raise APIError('invalid_scene','Use the documented scene fields.')
        result={**blank(),**copy.deepcopy(scene)}
        if not isinstance(result['prompt'],str) or len(result['prompt'])>50000:
            raise APIError('invalid_scene','Prompt must be text, at most 50,000 draft characters.')
        if type(result['audio']) is not bool:raise APIError('invalid_scene','Audio must be boolean.')
        for field in ('model','ratio','resolution'):
            if not isinstance(result[field],str):raise APIError('invalid_scene',field+' must be text.')
        if type(result['duration']) is not int:raise APIError('invalid_scene','Duration must be an integer.')
        for field in ('refs','voices','keys','named'):
            if not isinstance(result[field],list) or len(result[field])>30:
                raise APIError('invalid_scene',field+' must be a list with at most 30 entries.')
        for field in ('first','last'):result[field]=self.source(result[field])
        for field in ('refs','voices','keys'):
            identities=set()
            for entry in result[field]:
                if not isinstance(entry,dict):raise APIError('invalid_scene','Inputs must be objects.')
                entry.setdefault('id',uuid.uuid4().hex)
                if not isinstance(entry['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',entry['id']) or entry['id'] in identities:
                    raise APIError('invalid_scene','Input IDs must be unique within each input list.')
                identities.add(entry['id'])
                if field in ('refs','keys'):
                    entry['source']=self.source(entry.get('source'))
                    if entry['source'] is None:raise APIError('invalid_source','Reference images and keyframes require a source.')
                if field=='voices' and isinstance(entry.get('voice'),str):entry['voice']=entry['voice'].lower()
                if field=='voices' and entry.get('voice') not in VOICES:raise APIError('invalid_voice','Choose a documented preset voice.')
                if field=='keys' and type(entry.get('slot')) is not int:raise APIError('invalid_keyframe','Use an integer slot (seconds × 3).')
        handles=set()
        for n in result['named']:
            if not isinstance(n,dict) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',n.get('handle','')):
                raise APIError('invalid_reference','Invalid reference snapshot.')
            if n['handle'].casefold() in handles:raise APIError('invalid_reference','Duplicate scene reference name.')
            handles.add(n['handle'].casefold())
            if not isinstance(n.get('id'),str) or len(n['id'])>100 or len(n.get('title',''))>self.config['reference_title_limit'] or len(n.get('description',''))>self.config['reference_description_limit']:
                raise APIError('invalid_reference','Snapshot metadata exceeds the configured limits.')
            if not isinstance(n.get('title'),str) or not isinstance(n.get('description',''),str) or n.get('category') not in ('Character','Location','Prop'):
                raise APIError('invalid_reference','Invalid snapshot metadata.')
            if 'video_summary' in n and (not isinstance(n['video_summary'],str) or not 1<=len(n['video_summary'].strip())<=220 or '\n' in n['video_summary'] or '\r' in n['video_summary']):
                raise APIError('invalid_reference','Video asset summaries must be one line of 1–220 characters.')
            if not isinstance(n.get('refIds'),list) or not isinstance(n.get('images'),list) or len(n['refIds'])!=len(n['images']):
                raise APIError('invalid_reference','Snapshot images and bindings must match.')
            if len(n['images'])>7 or any(not isinstance(i,str) for i in n['refIds']) or len(set(n['refIds']))!=len(n['refIds']):raise APIError('invalid_reference','Snapshot needs at most seven unique image bindings.')
            for image in n['images']:self.source(image)
            if n.get('voice') and n['voice'] not in VOICES:raise APIError('invalid_reference','Invalid snapshot voice.')
        from audio_references import AudioReferences
        result['recording']=AudioReferences(self.app).attachment(result['recording'])
        return result

    def attach(self, scene, handles):
        if not isinstance(handles,list):raise APIError('invalid_reference','named_references must be a list of handles.')
        for handle in handles:
            if not isinstance(handle,str):raise APIError('invalid_reference','Reference handle must be text.')
            record=next((r for r in self.app.named_library() if not r['archived'] and r['handle'].casefold()==handle.lstrip('@').casefold()),None)
            if not record:raise APIError('unknown_reference','Saved reference not found: '+handle)
            if any(n['id']==record['id'] for n in scene['named']):continue
            if len(scene['refs'])+len(record['images'])>14 or len(scene['voices'])+bool(record['voice'])>3:
                raise APIError('reference_limit','This reference exceeds the scene image or voice limit.')
            refs=[{'id':uuid.uuid4().hex,'source':self.source(i),'namedId':record['id']} for i in record['images']]
            voice={'id':uuid.uuid4().hex,'voice':record['voice'],'namedId':record['id']} if record['voice'] else None
            scene['refs'].extend(refs)
            if voice:scene['voices'].append(voice)
            scene['named'].append({**record,'refIds':[r['id'] for r in refs],'voiceId':voice['id'] if voice else None})
        return scene

    def expanded_prompt(self, scene):
        s=self.normalize(scene)
        first=s['first']
        voices=s['voices'] if s['audio'] else []
        errors=[];contexts=[];prompt=s['prompt']
        # Older preparations appended prose summaries despite attached pixels.
        # Remove only recognized generated rows; retain unrelated user direction.
        paragraphs=[]
        for paragraph in prompt.split('\n\n'):
            lines=paragraph.splitlines()
            if lines and lines[0] in ('Asset cues:','Reference context:','Reference identities:'):
                header=lines[0];kept=[]
                for line in lines[1:]:
                    generated=False
                    for n in s['named']:
                        image_backed=any(r['id'] in n['refIds'] for r in s['refs'])
                        if header=='Asset cues:':
                            prefixes=('@'+n['handle']+':',n['title']+':') if image_backed else ()
                        else:
                            prefixes=(n['category']+': '+n['title']+' (',
                                      "Preserve "+n['title']+"'s exact appearance as shown in ",
                                      'Voice for '+n['title']+': ')
                        if any(line.casefold().startswith(p.casefold()) for p in prefixes):generated=True;break
                    if not generated:kept.append(line)
                if kept:paragraphs.append('\n'.join([header,*kept]))
            else:paragraphs.append(paragraph)
        prompt='\n\n'.join(paragraphs).strip()
        for handle in re.findall(r'(?:^|[^A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]*)',prompt):
            if not any(n['handle'].casefold()==handle.casefold() for n in s['named']):errors.append('@'+handle+' is not attached.')
        for n in s['named']:
            tags=[]
            for identity in n['refIds']:
                index=next((i for i,r in enumerate(s['refs']) if r['id']==identity),None)
                if index is None:errors.append(n['title']+' is missing an attached image.')
                else:tags.append(f'<IMAGE_{index+bool(first)}>')
            index=next((i for i,v in enumerate(voices) if v['id']==n.get('voiceId')),None)
            if not tags and index is None:errors.append(n['title']+' has no active image or voice for this model.')
            prompt=re.sub(r'(^|[^A-Za-z0-9_])@'+re.escape(n['handle'])+r'(?![A-Za-z0-9_])',lambda m:m[1]+n['title'],prompt,flags=re.I)
            if tags:
                if n['category']=='Character':
                    contexts.append("Preserve "+n['title']+"'s exact appearance as shown in "+' and '.join(tags)+' throughout the shot.')
                else:contexts.append(n['category']+': '+n['title']+' ('+', '.join(tags)+').')
            if index is not None:
                description='' if tags else n.get('video_summary',n.get('description',''))
                if n.get('video_summary') and n['video_summary'] in prompt:description=''
                contexts.append('Voice for '+n['title']+f': <AUDIO_{index}>.'+(' '+description if description else ''))
        if s.get('recording'):
            character=next((n['title'] for n in self.app.named_library() if n['id']==s['recording'].get('character_id')),None)
            contexts.append(('Recorded performance for '+character if character else 'Uploaded audio performance')+': <AUDIO_0>. Follow the supplied recording for the sung words and timing.')
        if contexts:prompt='Reference identities:\n'+'\n'.join(contexts)+('\n\n'+prompt if prompt else '')
        if errors:raise APIError('validation_failed',' '.join(dict.fromkeys(errors)))
        return prompt

    def compile(self, scene, allow_unapproved_start_frame=False, validate=True):
        s=self.normalize(scene)
        first=s['first']
        if s.get('recording'):
            if s['voices']:raise APIError('conflicting_audio','Remove preset voice assignments explicitly before using an uploaded recording.')
            if not s['audio']:raise APIError('conflicting_audio','Enable audio before using an uploaded recording.')
            if s['model']!=MODELS[0] or s['resolution']=='1080p':raise APIError('unsupported_inputs','Recordings require full Video 1.5 at 480p or 720p.')
        voices=s['voices'] if s['audio'] else []
        prompt=self.expanded_prompt(s)
        body={'model':s['model'],'duration':s['duration'],'aspect_ratio':s['ratio'],'resolution':s['resolution']}
        if prompt.strip():body['prompt']=prompt
        def src(source):return {'asset_id':source['id']} if source.get('id') else {'url':source['src']}
        if s['refs']:body['reference_images']=[src(r['source']) for r in s['refs']]
        # xAI reserves <IMAGE_0> for this pinned frame; references start at 1.
        # Tags are provider prompt syntax, not JSON field names.
        if first:body['image']=src(first)
        if s['model']==MODELS[1] and reference_scene(s):raise APIError('unsupported_inputs','Lite requires removing references, saved voices, last frames and keyframes or choosing Video 1.5.')
        body['generate_audio']=s['audio']
        if s['last']:body['last_frame']=src(s['last'])
        if s['keys']:body['keyframes']=[{'image':src(k['source']),'timestamp_s':k['slot']/3} for k in s['keys']]
        if voices:body['reference_audios']=[{'voice_id':v['voice']} for v in voices]
        if s.get('recording'):body['_studio_audio_reference']=s['recording']
        body['_studio_scene']=s
        if allow_unapproved_start_frame:body['allow_unapproved_start_frame']=True
        if validate:self.app.resolve(body)
        return body

    def validation(self, record):
        from workflow_tools import usage
        scene=record['scene'];warnings=[v['message'] for v in usage(self.app)['recent_limit_errors']]
        if not scene['audio'] and scene['voices']:warnings.append('Audio is off; saved voices are omitted.')
        from audio_references import AudioReferences
        effective_audio=AudioReferences(self.app).inspection(scene.get('recording'),scene['duration'])
        if effective_audio and effective_audio['duration_mismatch']:warnings.append('Recording excerpt duration differs from the shot. Neither timing has been changed.')
        if effective_audio:
            latest=next((j for j in self.app.history if (j.get('settings') or {}).get('_studio_video_id')==record['id']),None)
            if latest and (latest.get('audio_reference_access')=='denied' or (latest.get('http_status')==403 and 'reference_audios' in latest.get('upstream_error','') and 'not enabled' in latest.get('upstream_error',''))):
                warnings.append('xAI denied custom recording access on the last attempt for this draft. Ask xAI to enable caller-supplied audio-reference URLs for this team before retrying.')
            else:warnings.append('Custom recording access is unverified for this account. xAI may reject custom-audio access.')
            warnings.append('Generation temporarily serves only the excerpt through Cloudflare HTTPS; the link closes after processing. Exact singing sync is unverified.')
        try:
            settings=self.compile(record['scene']);request=self.app.resolve(settings)
            status = self.app.prompting.request_status(request, record['id'], scene)
            manual=copy.deepcopy(record.get('manual_prompt_review'))
            if manual:manual['current']=manual['revision']==record['revision']
            if manual and manual['current']:status['prompt_preparation_current']=True
            warnings.extend(i['message'] for i in status['prompt_issues'] if i['severity'] == 'warning')
            return {'valid':True,'errors':[],'warnings':warnings,'expanded_prompt_chars':len(request.get('prompt','')),'expanded_prompt_bytes':len(request.get('prompt','').encode('utf-8')),'request':request,
                'prompt_preparation_current':self.app.prompting.current('video',record),
                'prompt_preparation_message':self.app.prompting.preparation_message('video',record),
                'prompt_provenance':manual or copy.deepcopy(record.get('prompt_preparation')),
                'prompt_review_provenance':manual,
                'effective_audio_reference':effective_audio,
                **status}
        except ValueError as e:return {'valid':False,'errors':[str(e)],'warnings':warnings,'error_code':getattr(e,'code','validation_failed'),'effective_audio_reference':effective_audio}

    def record(self, identity):
        record=next((r for r in self.db['scenes'] if r['id']==identity),None)
        if not record:raise APIError('not_found','Scene not found.',404)
        return record

    def create(self, data):
        scene=self.attach(self.normalize(data.get('scene',{})),data.get('named_references',[]))
        title=data.get('title','Untitled scene')
        if not isinstance(title,str) or not title.strip() or len(title)>120:raise APIError('invalid_title','Scene title must contain 1–120 characters.')
        record={'id':uuid.uuid4().hex,'title':title.strip(),'revision':1,'scene':scene,'archived':False,'updated_at':time.time()}
        if data.get('story_context'):record['story_context']=self.app.stories.context(data['story_context']['episode_id'],data['story_context'].get('scene_id'),data['story_context'].get('script_revision'))
        self.db['scenes'].insert(0,record);self.save(self.path,self.db)
        return copy.deepcopy(record)

    def edit(self, identity, data):
        record=self.record(identity)
        if data.get('expected_revision')!=record['revision']:raise APIError('revision_conflict','Scene changed. Fetch it again before saving.',409)
        title=data.get('title',record['title'])
        if not isinstance(title,str) or not title.strip() or len(title)>120:raise APIError('invalid_title','Scene title must contain 1–120 characters.')
        scene=self.normalize(data.get('scene',record['scene']))
        previous_title=record['title']
        record.update(title=title.strip(),scene=scene,revision=record['revision']+1,updated_at=time.time())
        self.save(self.path,self.db)
        if previous_title!=record['title'] and hasattr(self.app,'productions'):self.app.productions.media_renamed('video',identity,record['title'])
        return copy.deepcopy(record)

    @staticmethod
    def retag(before,after):
        def ids(s,kind):
            if kind=='AUDIO':return [v['id'] for v in s['voices']] if s['audio'] and s['model']==MODELS[0] else []
            first=s['first']
            return (['first'] if first else [])+[r['id'] for r in s['refs']]
        for kind in ('IMAGE','AUDIO'):
            old,new=ids(before,kind),ids(after,kind)
            def replace(m):
                index=int(m[1])
                if index>=len(old):return m[0]
                return f'<{kind}_{new.index(old[index])}>' if old[index] in new else f'<{kind}_REMOVED_{index}>'
            after['prompt']=re.sub('<'+kind+r'_(\d+)>',replace,after['prompt'])

    def patch(self, identity, data):
        record=self.record(identity);before=record['scene'];changes=data.get('changes',{})
        if not isinstance(changes,dict):raise APIError('invalid_scene','changes must be an object.')
        scene=self.normalize({**before,**changes})
        if 'prompt' not in changes:self.retag(before,scene)
        self.attach(scene,data.get('named_references',[]))
        for field in ('remove_named_references','restore_named_references'):
            if not isinstance(data.get(field,[]),list) or any(not isinstance(x,str) for x in data.get(field,[])):
                raise APIError('invalid_reference',field+' must be a list of handles.')
        for handle in data.get('restore_named_references',[]):
            binding=next((n for n in scene['named'] if n['handle'].casefold()==handle.lstrip('@').casefold()),None)
            if not binding:raise APIError('unknown_reference','No scene snapshot for '+handle)
            for i,image_id in enumerate(binding['refIds']):
                if not any(r['id']==image_id for r in scene['refs']):scene['refs'].append({'id':image_id,'source':self.source(binding['images'][i]),'namedId':binding['id']})
            if binding.get('voiceId') and not any(v['id']==binding['voiceId'] for v in scene['voices']):scene['voices'].append({'id':binding['voiceId'],'voice':binding['voice'],'namedId':binding['id']})
        for handle in data.get('remove_named_references',[]):
            binding=next((n for n in scene['named'] if n['handle'].casefold()==handle.lstrip('@').casefold()),None)
            if binding:
                old=copy.deepcopy(scene)
                scene['refs']=[r for r in scene['refs'] if r['id'] not in binding['refIds']]
                scene['voices']=[v for v in scene['voices'] if v['id']!=binding.get('voiceId')]
                scene['named'].remove(binding)
                scene['prompt']=re.sub('@'+re.escape(binding['handle'])+r'(?![A-Za-z0-9_])',binding['title'],scene['prompt'],flags=re.I)
                self.retag(old,scene)
        return self.edit(identity,{**data,'scene':scene})

    def workspace(self):
        identity=self.db['current_id']
        return copy.deepcopy(self.record(identity)) if identity else None

    def dispatch(self, method, path, data, key=None):
        if not isinstance(data,dict):raise APIError('invalid_json','JSON body must be an object.')
        parsed=urlsplit(path)
        if parsed.query:
            if method!='GET':raise APIError('invalid_query','Query parameters are supported only on reads.')
            allowed={'scene_id','video_job_id','target_video_job_id'} if parsed.path in ('/agent/v1/video-review','/api/agent/video-review') else {'model'} if parsed.path=='/agent/v1/video-review/lessons' else set()
            values=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=20)
            if set(values)-allowed or any(len(v)!=1 or not v[0] or len(v[0])>128 for v in values.values()):raise APIError('invalid_query','Use the documented query parameters once each.')
            data={**data,**{k:v[0] for k,v in values.items()}}
        # These operations own their short snapshot/cache locks. Subprocesses
        # must not keep every unrelated workspace API request waiting.
        if parsed.path=='/agent/v1/workspace/status' and method=='GET':
            from studio_performance import workspace_status
            return 200,workspace_status(self.app)
        if parsed.path=='/agent/v1/editing/inspect' and method=='POST':return 200,self.app.editing.inspect(data)
        if parsed.path=='/agent/v1/image-studio/openai-account' and method=='GET':return 200,self.app.images.account_status()
        if parsed.path=='/agent/v1/image-studio/openai-account/refresh' and method=='POST':return 200,self.app.images.account_status(True)
        started=time.monotonic()
        with self.lock:
            acquired=time.monotonic()
            result=self._dispatch(method,parsed.path,data,key)
        elapsed=time.monotonic()-started
        if elapsed>.25:
            logging.getLogger(__name__).info('Studio API %s: lock_wait_ms=%.1f work_ms=%.1f',method,(acquired-started)*1000,(time.monotonic()-acquired)*1000)
        return result

    def _dispatch(self, method, path, data, key):
        parts=path.strip('/').split('/')
        if parts[:2]!=['agent','v1']:raise APIError('not_found','Unknown API version.',404)
        parts=parts[2:]
        if len(parts)==3 and parts[0]=='productions' and parts[2]=='export' and method=='POST':
            if data != {}: raise APIError('invalid_request','Project export accepts an empty JSON object.')
            self.app.productions.get(parts[1], 'production')
            return 202,self.app.archives.start('export',parts[1])
        if len(parts)==2 and parts[0]=='project-archives' and method=='GET':
            return 200,self.app.archives.status(parts[1])
        if parts==['library','page'] and method=='POST':
            from studio_library import page
            return 200,page(self.app,data)
        if parts==['workspace','status'] and method=='GET':
            from studio_performance import workspace_status
            return 200,workspace_status(self.app)
        if len(parts)==3 and parts[0]=='scenes' and parts[2]=='jobs' and method=='GET':
            record=self.record(parts[1]);unique=sum(r['scene']==record['scene'] for r in self.db['scenes'])==1
            return 200,[j for j in self.app.records() if j['settings'].get('_studio_video_id')==record['id'] or (unique and not j['settings'].get('_studio_video_id') and j['settings'].get('_studio_scene')==record['scene'])]
        if not isinstance(data,dict):raise APIError('invalid_json','JSON body must be an object.')
        if len(parts)==2 and parts[0]=='scene-layouts' and method in ('GET','PUT'):
            from workflow_tools import layout
            return 200,layout(self.app,parts[1],data if method=='PUT' else None)
        if parts==['lessons'] and method in ('GET','POST'):
            from workflow_tools import lessons
            if method=='POST':return 201,lessons(self.app,data,True)
            return 200,lessons(self.app,data)
        if parts==['lessons','search'] and method=='POST':
            from workflow_tools import lessons
            return 200,lessons(self.app,data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='annotations' and method=='POST':
            from workflow_tools import annotate
            return 200,annotate(self.app,parts[1],data)
        if parts==['prompts','check'] and method=='POST':
            from workflow_tools import check
            return 200,check(self.app,data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='mirror' and method=='POST':
            from workflow_tools import mirror
            return 201,mirror(self.app,parts[1],data)
        if parts==['usage'] and method=='GET':
            from workflow_tools import usage
            return 200,usage(self.app)
        if parts and parts[0]=='handoff':return self.app.handoff.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='documents':return self.app.documents.dispatch(method,parts[1:],data,key)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='place' and method=='POST':
            from frame_tools import place
            return 200,place(self,parts[1],data)
        if parts and parts[0]=='productions':return self.app.productions.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='editing':return self.app.editing.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='song-performance':return self.app.song_performance.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='filmmaking':return self.app.filmmaking.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='creative':return self.app.creative.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='asset-studio':return self.app.asset_studio.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='precision':return self.app.precision.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='stories':return self.app.stories.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='image-studio':return self.app.images.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='prompting':return self.app.prompting.dispatch(method,parts[1:],data,key)
        if parts and parts[0]=='video-review':return self.app.video_review.dispatch(method,parts[1:],data,key)
        if parts==['demo'] and method=='GET':
            if not self.app.mock:raise APIError('mock_only','Demo fixtures are available only in mock mode.',403)
            from demo_fixtures import fixtures
            return 200,fixtures()
        if parts==['demo','load'] and method=='POST':
            if not self.app.mock:raise APIError('mock_only','Demo fixtures are available only in mock mode.',403)
            if data:raise APIError('invalid_demo','The demo uses fixed inputs.')
            if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):raise APIError('idempotency_required','Supply an Idempotency-Key for loading a demo.')
            prior=self.db.setdefault('demo_keys',{}).get(key)
            if prior:return 200,copy.deepcopy(self.record(prior))
            from demo_fixtures import fixtures
            fixture=fixtures();images=[self.app.upload(i) for i in fixture['images']]
            scene={**blank(),**fixture['scene'],'first':images[0],'last':images[2],'refs':[{'id':'demo-reference','source':images[1]}],'keys':[{'id':'demo-key-1','source':images[1],'slot':5},{'id':'demo-key-2','source':images[2],'slot':10}]}
            record=self.create({'title':'Mock storyboard','scene':scene});self.db['demo_keys'][key]=record['id'];self.save(self.path,self.db)
            self.app.begin('login')
            return 201,record
        if method=='GET' and not parts:return 200,{'version':'1','name':'Imagine Studio','schema':'/agent/v1/schema','approval_required':True}
        if method=='GET' and parts==['schema']:
            from agent_openapi import specification
            contract=specification()
            return 200,{'version':'1','scene_defaults':blank(),'models':MODELS,'model_capabilities':MODEL_CAPABILITIES,'uploaded_audio':__import__('audio_references').capabilities(),'song_performance':self.app.song_performance.schema(),'ratios':RATIOS,'voices':VOICES,'config':self.config,
                'image_source':{'asset_id':'uploaded-id','alternative':{'url':'https://public.example/image.png'}},
                'keyframe':'{id, source, slot}; slot is integer seconds × 3',
                'routes':[path.lstrip('/') or '/' for path in contract['paths']],
                'route_methods':{path.lstrip('/') or '/':list(methods) for path,methods in contract['paths'].items()},
                'frame_tools':{'capture':'POST jobs/{id}/capture-frame with timestamp_s; optional data_url for browser capture','place':'POST assets/{id}/place with target, scene_id and expected_revision OR new_scene=true; keyframes require integer slot'},
                'documentation':'AGENT_API.md; edits require expected_revision; renders require approved=true and Idempotency-Key'}
        if parts==['openapi.json'] and method=='GET':
            from agent_openapi import specification
            return 200,specification()
        if parts==['account'] and method=='GET':return 200,self.app.snapshot()
        if parts==['account','login'] and method=='POST':self.app.begin('login');return 202,self.app.snapshot()
        if parts==['account','grok-check'] and method=='POST':return 200,self.app.check_grok_connection()
        from audio_references import AudioReferences, capabilities as audio_capabilities
        recordings=AudioReferences(self.app)
        if parts==['audio-references','schema'] and method=='GET':return 200,audio_capabilities()
        if parts==['audio-references']:
            if method=='GET':return 200,self.app.productions.all('audio-reference')
            if method=='POST':return 201,recordings.upload(data,key)
        if len(parts)==2 and parts[0]=='audio-references' and method=='GET':return 200,recordings.get(parts[1])
        if len(parts)==3 and parts[0]=='audio-references' and parts[2]=='excerpts' and method=='POST':return 201,recordings.excerpt(parts[1],data)
        if len(parts)==3 and parts[0]=='audio-references' and parts[2]=='download' and method=='GET':
            r,p=recordings.file(parts[1]);return 200,(p.read_bytes(),'audio/wav' if r['format']=='wav' else 'audio/mpeg')
        if len(parts)==2 and parts[0]=='audio-excerpts' and method=='GET':return 200,recordings.get(parts[1],'audio-excerpt')
        if len(parts)==3 and parts[0]=='audio-excerpts' and parts[2]=='download' and method=='GET':
            r,p=recordings.file(parts[1],'audio-excerpt');return 200,(p.read_bytes(),'audio/mpeg' if p.suffix=='.mp3' else 'audio/wav')
        if parts==['assets']:
            if method=='GET':return 200,self.app.library()
            if method=='POST':return 201,self.app.upload(data)
        if len(parts)==2 and parts[0]=='assets' and method=='GET':
            asset,path=self.app.asset(parts[1]);return 200,(path.read_bytes(),asset['mime'])
        if parts==['urls']:
            if method=='GET':return 200,copy.deepcopy([s for s in self.db['urls'] if not s['archived']])
            if method=='POST':
                source=self.source(data)
                if not source or source.get('id') or not source['src'].startswith('https://'):raise APIError('invalid_url','Use a public HTTPS image URL.')
                if not any(s['src']==source['src'] for s in self.db['urls']):
                    self.db['urls'].append({**source,'url_id':uuid.uuid4().hex,'revision':1,'archived':False});self.save(self.path,self.db)
                # Existing archived URLs stay archived, including stale localStorage imports.
                return 200,copy.deepcopy([s for s in self.db['urls'] if not s['archived']])
        if parts==['urls','all'] and method=='GET':return 200,copy.deepcopy(self.db['urls'])
        if len(parts)>=2 and parts[0]=='urls':
            source=next((s for s in self.db['urls'] if s['url_id']==parts[1]),None)
            if not source:raise APIError('not_found','Remembered URL not found.',404)
            if len(parts)==2 and method=='GET':return 200,copy.deepcopy(source)
            if len(parts)==3 and parts[2]=='archive' and method=='POST':
                if type(data.get('expected_revision')) is not int or data['expected_revision']!=source['revision']:
                    raise APIError('revision_conflict','This URL changed. Reload before removing or restoring it.',409)
                archived=data.get('archived',True)
                if type(archived) is not bool:raise APIError('invalid_url','archived must be boolean.')
                source.update(archived=archived,revision=source['revision']+1);self.save(self.path,self.db)
                return 200,copy.deepcopy(source)
        if parts==['references']:
            if method=='GET':return 200,self.app.named_library()
            if method=='POST':return 201,self.app.save_reference(data)
        if len(parts)>=2 and parts[0]=='references':
            identity=parts[1]
            if len(parts)==2 and method=='GET':
                record=next((r for r in self.app.named_library() if r['id']==identity),None)
                if not record:raise APIError('not_found','Reference not found.',404)
                return 200,record
            if len(parts)==2 and method=='PUT':return 200,self.app.save_reference({**data,'id':identity})
            if len(parts)==3 and parts[2]=='archive' and method=='POST':return 200,self.app.archive_reference(identity,data.get('archived',True))
        if parts==['scenes']:
            if method=='GET':return 200,copy.deepcopy(self.db['scenes'])
            if method=='POST':return 201,self.create(data)
        if parts==['workspace']:
            if method=='GET':return 200,self.workspace()
            if method=='POST':
                if 'scene_id' in data:
                    record=self.record(data['scene_id'])
                    if record['archived']:raise APIError('archived','Restore this scene before selecting it.')
                elif not self.db['current_id']:
                    record=self.create(data)
                else:return 200,self.workspace()
                self.db['current_id']=record['id'];self.save(self.path,self.db);return 200,copy.deepcopy(record)
        if len(parts)>=2 and parts[0]=='scenes':
            identity=parts[1];record=self.record(identity)
            if len(parts)==2:
                if method=='GET':return 200,copy.deepcopy(record)
                if method=='PUT':return 200,self.edit(identity,data)
                if method=='PATCH':return 200,self.patch(identity,data)
            if len(parts)==3:
                action=parts[2]
                if action=='validate' and method=='POST':return 200,self.validation(record)
                if action=='review-prompt' and method=='POST':
                    if data.get('expected_revision')!=record['revision']:raise APIError('revision_conflict','Scene changed. Review the current revision.',409)
                    if data.get('reviewed') is not True:raise APIError('review_required','Explicitly review the video prompt first.',403)
                    author=data.get('authored_by','human')
                    if author not in ('agent','human'):raise APIError('invalid_author','authored_by must be agent or human.')
                    validation=self.validation(record)
                    if not validation['valid'] or validation.get('prompt_generation_blocked'):raise APIError('validation_failed',' '.join(validation['errors']) or 'Resolve the prompt conflicts before recording review.')
                    from prompt_guides import digest
                    record['manual_prompt_review']=dict(revision=record['revision'],authored_by=author,reviewed_at=time.time(),request_fingerprint=digest(validation['request']))
                    self.save(self.path,self.db)
                    return 200,copy.deepcopy(record)
                if action=='archive' and method=='POST':
                    if data.get('expected_revision')!=record['revision']:raise APIError('revision_conflict','Fetch scene before archiving.',409)
                    record.update(archived=data.get('archived',True),revision=record['revision']+1)
                    if record['archived'] and self.db['current_id']==identity:self.db['current_id']=None
                    self.save(self.path,self.db);return 200,copy.deepcopy(record)
                if action=='generate' and method=='POST':
                    if data.get('approved') is not True:raise APIError('approval_required','Explicit human authorization and approved=true are required.',403)
                    if not key or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):raise APIError('idempotency_required','Supply an 8–100 character Idempotency-Key.')
                    fingerprint=hashlib.sha256(json.dumps({'scene_id':identity,'revision':data.get('expected_revision'),'allow_unapproved_start_frame':data.get('allow_unapproved_start_frame',False)},sort_keys=True).encode()).hexdigest()
                    previous=next((j for j in self.app.records() if j.get('agent_key')==key),None)
                    if previous:
                        if previous.get('agent_fingerprint')!=fingerprint:raise APIError('idempotency_conflict','This key belongs to a different scene/revision.',409)
                        return 200,previous
                    if data.get('expected_revision')!=record['revision']:raise APIError('revision_conflict','Scene changed; review it before generation.',409)
                    if record['archived']:raise APIError('archived','Restore scene before generating.')
                    if type(data.get('allow_unapproved_start_frame',False)) is not bool:raise APIError('invalid_override','allow_unapproved_start_frame must be boolean.')
                    settings=self.compile(record['scene'],data.get('allow_unapproved_start_frame',False),validate=False)
                    settings['_studio_video_id']=record['id']
                    if record.get('story_context'):settings['_studio_story']=copy.deepcopy(record['story_context'])
                    identity=self.app.start_video(settings,True,agent_key=key,agent_fingerprint=fingerprint)
                    return 202,next(j for j in self.app.records() if j['id']==identity)
        if parts==['jobs'] and method=='GET':return 200,self.app.records()
        if len(parts)>=2 and parts[0]=='jobs':
            job=next((j for j in self.app.records() if j['id']==parts[1]),None)
            if not job:raise APIError('not_found','Job not found.',404)
            if len(parts)==2 and method=='GET':
                state=self.app.snapshot()
                if state.get('job_id')==job['id']:job['progress']=state.get('progress')
                return 200,job
            if len(parts)==3:
                if parts[2]=='capture-frame' and method=='POST':
                    from frame_tools import capture
                    return 201,capture(self.app,job,data)
                if parts[2]=='resume' and method=='POST':self.app.resume(job['id']);return 202,{'id':job['id']}
                if parts[2]=='download' and method=='GET':return 200,(self.app.download(job['id']).read_bytes(),{'mov':'video/quicktime','webm':'video/webm'}.get(self.app.download(job['id']).suffix.lstrip('.'),'video/mp4'))
                if parts[2]=='reuse' and method=='POST':
                    settings=job['settings'];scene=settings.get('_studio_scene')
                    if not scene:
                        scene={**blank(),'model':settings['model'],'duration':settings['duration'],'ratio':settings['aspect_ratio'],'resolution':settings['resolution'],'prompt':settings.get('prompt',''),'audio':settings.get('generate_audio',True),
                            'refs':[{'source':i} for i in settings.get('reference_images',[])], 'first':settings.get('image'),'last':settings.get('last_frame'),
                            'voices':[{'voice':v['voice_id']} for v in settings.get('reference_audios',[])],
                            'keys':[{'source':k['image'],'slot':round(k['timestamp_s']*3)} for k in settings.get('keyframes',[])]}
                    return 201,self.create({'title':data.get('title','Reused scene'),'scene':scene,'story_context':settings.get('_studio_story')})
        if parts==['image-test'] and method=='POST':
            return self.app.diagnostics.start(data,key,self.config['prompt_limit_chars'])
        if len(parts)==2 and parts[0]=='image-test' and method=='GET':return 200,self.app.diagnostics.get(parts[1])
        raise APIError('not_found','Endpoint or HTTP method not found.',404)

    def serve(self, handler, method, browser=False):
        if not handler.allowed_host():return handler.send(403,{'error':{'code':'local_only','message':'Local access only.'}})
        origin=handler.headers.get('Origin')
        allowed=(f'http://127.0.0.1:{handler.server.server_port}',f'http://localhost:{handler.server.server_port}')
        if browser:
            if handler.path.startswith(('/api/agent/audio-references','/api/agent/audio-excerpts')) and ((origin and origin not in allowed) or handler.headers.get('Sec-Fetch-Site')=='cross-site'):
                return handler.send(403,{'error':{'code':'origin_required','message':'Recordings require local browser access.'}})
            if method!='GET' and (origin not in allowed or handler.headers.get('X-Tester')!='local'):
                return handler.send(403,{'error':{'code':'origin_required','message':'Local browser origin required.'}})
        elif not self.authorized(handler.headers.get('Authorization')) or (origin and origin not in allowed):
            return handler.send(403,{'error':{'code':'agent_auth_required','message':'Local agent bearer token required.'}})
        try:
            data={}
            if method not in ('GET',):
                length=int(handler.headers.get('Content-Length','0'))
                limit=(64*1024*1024*4//3+8192) if handler.path.endswith(('/editing/media','/audio-references')) else self.config['upload_limit_mb']*1024*1024*4//3+8192
                if not 0<length<=limit:raise APIError('body_limit','JSON body exceeds the local limit.',413)
                data=json.loads(handler.rfile.read(length))
            path=handler.path.replace('/api/agent','/agent/v1',1) if browser else handler.path
            status,result=self.dispatch(method,path,data,handler.headers.get('Idempotency-Key'))
            if isinstance(result,tuple):return handler.send(status,result[0],result[1])
            return handler.send(status,result)
        except APIError as e:return handler.send(e.status,{'error':{'code':e.code,'message':str(e)}})
        except ValueError as e:
            return handler.send(400,{'error':{'code':'validation_failed','message':str(e)}})
        except (TypeError,KeyError,AttributeError,IndexError) as exc:
            from request_diagnostics import structure_failure
            operation='load this workspace' if method=='GET' else 'save this change'
            if handler.path.endswith('/select-take'):operation='update this shot’s selected take'
            return handler.send(400,{'error':{'code':'invalid_request','message':structure_failure(exc,operation)}})
        except OSError:return handler.send(500,{'error':{'code':'storage_error','message':'Local storage unavailable.'}})
