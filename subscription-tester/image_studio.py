"""Persistent image drafts, identity snapshots and locally cached image candidates."""
import base64
import copy
import hashlib
import json
import re
import struct
import threading
import time
import uuid
import zlib
from agent_api import APIError
from video_rules import RATIOS
import openai_images

IMAGE_MODEL = 'grok-imagine-image-2.0'
IMAGE_RATIOS = tuple(dict.fromkeys((*RATIOS, '2:1', '1:2', '19.5:9', '9:19.5', '20:9', '9:20', 'auto')))
DEFAULTS = dict(model=IMAGE_MODEL, prompt='', ratio='16:9', resolution='1k', quality='auto', n=1, bindings=[], extras=[], base=None, edit_region=None)
OPENAI_RATIOS = ('auto','1:1','3:2','2:3','16:9','9:16')
IMAGE_MODELS = {
    IMAGE_MODEL: dict(label='Grok Imagine Image 2.0', provider='grok', billing='Grok subscription', ratios=IMAGE_RATIOS, resolutions=['1k','1.5k','2k'], counts=[1,2,4], deferred=True, qualities=['low','medium','auto']),
    'gpt-image-2': dict(label='OpenAI Image 2 · subscription', provider='codex', billing='Codex subscription allowance', ratios=OPENAI_RATIOS, resolutions=['auto'], qualities=['auto'], counts=[1]),
    **{m: dict(label='OpenAI Image 2.5 '+('Flare' if m.endswith('flare') else 'Sunburst')+' · API', provider='openai', billing='OpenAI API billing', ratios=OPENAI_RATIOS, resolutions=list(openai_images.SIZES), qualities=list(openai_images.QUALITIES), counts=[1,2,4]) for m in openai_images.API_MODELS}}


def source_limit(model):
    # The installed native Codex tool validates referenced_image_paths at five.
    # Its subscription transport does not inherit the HTTP API's 16-image cap.
    return 16 if model in openai_images.API_MODELS else 5



def mock_png(ratio='16:9'):
    """Local geometric storyboard, deliberately not a simulated model output."""
    a, b = (16, 9) if ratio == 'auto' else map(float, ratio.split(':'))
    w, h = (640, max(64, round(640*b/a))) if a >= b else (max(64, round(640*a/b)), 640)
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            color = (20+int(y/h*18), 35+int(y/h*12), 43+int(y/h*15))
            if w*.08 < x < w*.92 and h*.08 < y < h*.62: color=(54,83,89)
            if (x-w*.73)**2+(y-h*.29)**2 < (min(w,h)*.10)**2: color=(236,186,117)
            if w*.16 < x < w*.84 and h*.76 < y < h*.83: color=(153,110,74)
            if (x-w*.5)**2+(y-h*.37)**2 < (min(w,h)*.11)**2: color=(145,204,180)
            if w*.43 < x < w*.57 and h*.5 < y < h*.75: color=(106,151,136)
            rows.extend(color)
    def chunk(kind, value):
        return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


class ImageStudio:
    def __init__(self, app, config, save):
        self.app, self.config, self.save = app, config, save
        self.path = app.storage/'image-studio.json'
        self.lock = threading.RLock()
        self.openai_account = None
        self.openai_checked_at = 0
        self.account_lock = threading.Lock()
        self.db = json.loads(self.path.read_text()) if self.path.exists() else {'current_id':None,'drafts':[],'jobs':[]}
        # Apply the new Grok default to editable drafts; historical requests stay immutable.
        if not self.db.get('grok_auto_quality_migrated'):
            for draft in self.db['drafts']:
                if draft['settings'].get('model', IMAGE_MODEL)==IMAGE_MODEL and draft['settings'].get('quality')=='low':
                    draft['settings']['quality']='auto'
                    draft['revision']+=1
            self.db['grok_auto_quality_migrated']=True
        # A synchronous upstream POST cannot safely be replayed after process loss.
        for job in self.db['jobs']:
            if job['status']=='pending':
                job.update(status='error', recoverable=bool(job.get('provider')=='grok' and job.get('request_id') and job.get('deferred')), message='Server restarted. Resume the existing Grok image job.' if job.get('provider')=='grok' and job.get('request_id') and job.get('deferred') else 'Server restarted during image generation. No automatic retry was made. Check usage before submitting again.')
        self.persist()

    def persist(self): self.save(self.path,self.db)

    def prompt_limit(self, model):
        # OpenAI's documented GPT Image limit; native subscription uses the
        # same local cap, with upstream transport validation still authoritative.
        if model=='gpt-image-2' or model in openai_images.API_MODELS:return 32000
        return self.config['prompt_limit_chars']

    def schema(self):
        return {'model':IMAGE_MODEL,'models':{model:{**copy.deepcopy(profile),'max_sources':source_limit(model),'source_limit_basis':'OpenAI API 16-image limit' if profile['provider']=='openai' else 'Installed Codex native tool five-image limit' if profile['provider']=='codex' else 'Grok five-image edit limit','prompt_limit_chars':self.prompt_limit(model),'prompt_limit_basis':'OpenAI documented API limit; native transport may impose additional restrictions' if profile['provider'] in ('codex','openai') else 'Local configurable limit; provider character limit unconfirmed'} for model,profile in IMAGE_MODELS.items()},'defaults':copy.deepcopy(DEFAULTS),'ratios':IMAGE_RATIOS,
                'resolutions':['1k','1.5k','2k'],'qualities':['low','medium','auto'],'max_sources':5,
                'prompt_limit_chars':self.config['prompt_limit_chars'],'output_limit_mb':self.config.get('image_output_limit_mb',20),
                'reference_export':{'suggest':'POST jobs/{id}/reference-suggestion','save':'POST jobs/{id}/reference','requires':'Approved output asset_id; editable prompt-derived metadata; default Location; no generation calls'},'documentation':'IMAGE_STUDIO_GUIDE.md','consistency_guaranteed':False}

    def draft(self, identity):
        record=next((r for r in self.db['drafts'] if r['id']==identity),None)
        if not record: raise APIError('not_found','Image draft not found.',404)
        return record

    def job(self, identity):
        record=next((r for r in self.db['jobs'] if r['id']==identity and r['mock']==self.app.mock),None)
        if not record: raise APIError('not_found','Image generation not found in this mode.',404)
        return record

    def normalized(self, value):
        if not isinstance(value,dict) or set(value)-set(DEFAULTS): raise APIError('invalid_image_draft','Use the documented image settings.')
        s={**copy.deepcopy(DEFAULTS),**copy.deepcopy(value)}
        if not isinstance(s['prompt'],str) or len(s['prompt'])>50000: raise APIError('invalid_prompt','Use text up to 50,000 draft characters.')
        if s['model'] not in IMAGE_MODELS: raise APIError('invalid_model','Choose a supported image model. Image 2.5 subscription access is unconfirmed.')
        profile=IMAGE_MODELS[s['model']]
        if type(s['n']) is not int or s['n'] not in profile['counts']:raise APIError('invalid_count','Choose a supported candidate count for this connection.')
        for field in ('resolution','quality'):
            if field not in value and s[field] not in profile[field+'s' if field=='resolution' else 'qualities']:
                s[field]='auto'
        for field, allowed in [('ratio',profile['ratios']),('resolution',profile['resolutions']),('quality',profile['qualities'])]:
            if s[field] not in allowed: raise APIError('invalid_settings','Choose a documented image '+field+'.')
        if not isinstance(s['bindings'],list) or len(s['bindings'])>20: raise APIError('invalid_bindings','Use a list of at most 20 saved assets.')
        seen=set()
        for binding in s['bindings']:
            if not isinstance(binding,dict): raise APIError('invalid_bindings','Asset snapshots must be objects.')
            snap=binding.get('snapshot')
            if not isinstance(snap,dict) or not isinstance(snap.get('id'),str) or not isinstance(snap.get('handle'),str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',snap['handle']): raise APIError('invalid_bindings','Invalid asset snapshot.')
            if snap['handle'].lower() in seen: raise APIError('invalid_bindings','Attach each asset once.')
            seen.add(snap['handle'].lower())
            if not isinstance(snap.get('title'),str) or len(snap['title'])>self.config['reference_title_limit'] or not isinstance(snap.get('description',''),str) or len(snap.get('description',''))>self.config['reference_description_limit'] or snap.get('category') not in ('Character','Location','Prop'): raise APIError('invalid_bindings','Invalid asset description or category.')
            images=snap.get('images')
            selected=binding.get('selected')
            if not isinstance(images,list) or not 1<=len(images)<=7 or not isinstance(selected,list) or any(type(i) is not int or not 0<=i<len(images) for i in selected) or len(selected)!=len(set(selected)): raise APIError('invalid_bindings','Choose valid image views for the saved asset.')
            for image in images:
                if self.app.agent.source(image) is None: raise APIError('invalid_source','Asset views require images.')
        if not isinstance(s['extras'],list) or len(s['extras'])>16: raise APIError('invalid_source','Extra references must be a list.')
        for image in s['extras']:
            if self.app.agent.source(image) is None: raise APIError('invalid_source','Extra references require images.')
        if s['base'] is not None:
            source=self.app.agent.source(s['base'])
            if source is None: raise APIError('invalid_source','Refinement needs a base image.')
        from precision_studio import region
        s['edit_region']=region(s['edit_region'])
        if s['edit_region'] and (not s['base'] or not s['base'].get('asset_id')):raise APIError('invalid_region','Region editing requires a locally uploaded base image.')
        return s

    def attach(self, settings, handles):
        if not isinstance(handles,list) or any(not isinstance(h,str) for h in handles): raise APIError('invalid_bindings','named_references must be a list of handles.')
        for handle in handles:
            if any(b['snapshot']['handle'].lower()==handle.lstrip('@').lower() for b in settings['bindings']): continue
            record=next((r for r in self.app.named_library() if not r['archived'] and r['handle'].lower()==handle.lstrip('@').lower()),None)
            if not record or not record['images']: raise APIError('unknown_reference','Choose an asset with images: '+handle)
            settings['bindings'].append({'snapshot':copy.deepcopy(record),'selected':[0]})
        return self.normalized(settings)

    def sync_mentions(self, settings):
        # Keep existing snapshots and manually selected views; attach only missing exact handles.
        # Refinements use the base image by default. Mentions must never silently
        # add pixels to this request; additional references are an explicit choice.
        if settings.get('base'): return settings
        count=bool(settings['base'])+len(settings['extras'])+sum(len(b['selected']) for b in settings['bindings'])
        library={r['handle'].lower():r for r in self.app.named_library() if not r['archived']}
        attached={b['snapshot']['handle'].lower() for b in settings['bindings']}
        for handle in re.findall(r'(?:^|[^A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]*)',settings['prompt']):
            key=handle.lower();record=library.get(key)
            if key in attached or not record or not record['images'] or count>=source_limit(settings['model']) or len(settings['bindings'])>=20:continue
            settings['bindings'].append({'snapshot':copy.deepcopy(record),'selected':[0]})
            attached.add(key);count+=1
        return settings

    def create(self, data):
        title=data.get('title','Untitled image')
        if not isinstance(title,str) or not 1<=len(title.strip())<=120: raise APIError('invalid_title','Enter an image title up to 120 characters.')
        settings=self.sync_mentions(self.attach(self.normalized(data.get('settings',{})),data.get('named_references',[])))
        record=dict(id=uuid.uuid4().hex,title=title.strip(),revision=1,settings=settings,created_at=time.time(),updated_at=time.time())
        if data.get('parent_draft_id'):
            parent=self.draft(data['parent_draft_id'])
            record['parent_draft_id']=parent['id']
            record['version_root_id']=parent.get('version_root_id',parent['id'])
            if parent.get('story_context'):record['story_context']=copy.deepcopy(parent['story_context'])
        if data.get('story_context'):record['story_context']=self.app.stories.context(data['story_context']['episode_id'],data['story_context'].get('scene_id'),data['story_context'].get('script_revision'))
        self.db['drafts'].insert(0,record); self.persist()
        return copy.deepcopy(record)

    def versions(self, identity):
        record=self.draft(identity)
        root=record.get('version_root_id',record['id'])
        return [copy.deepcopy(d) for d in self.db['drafts'] if d.get('version_root_id',d['id'])==root]

    def edit(self, identity, data):
        record=self.draft(identity)
        if data.get('expected_revision')!=record['revision']: raise APIError('revision_conflict','Image draft changed. Reload it or save a copy.',409)
        title=data.get('title',record['title'])
        if not isinstance(title,str) or not 1<=len(title.strip())<=120: raise APIError('invalid_title','Enter an image title up to 120 characters.')
        settings=self.sync_mentions(self.attach(self.normalized(data.get('settings',record['settings'])),data.get('named_references',[])))
        if 'title' not in data and settings['prompt']!=record['settings']['prompt']:
            title=title.replace('Character sheet','Main image')
        previous_title=record['title']
        reviewed=self.manual_review_current(record)
        before=self.app.prompting.authoring_basis('image',record) if reviewed else None
        record.update(title=title.strip(),settings=settings,revision=record['revision']+1,updated_at=time.time())
        if reviewed and before==self.app.prompting.authoring_basis('image',record):
            record['manual_review_revision']=record['revision']
            record.setdefault('manual_prompt_review',dict(authored_by='human'))['revision']=record['revision']
        self.persist()
        if previous_title!=record['title'] and hasattr(self.app,'productions'):self.app.productions.media_renamed('image',identity,record['title'])
        return copy.deepcopy(record)

    def expanded_prompt(self, settings):
        """Validate and expand text/references without reading image bytes."""
        s=self.normalized(settings);prompt=s['prompt'].strip();sources=[];context=[]
        if not prompt: raise APIError('invalid_prompt','Describe the image you want to create.')
        if s['base']:
            sources.append(s['base']);context.append('Input image 1 is the scene to refine. Apply the requested changes while preserving other scene details.')
        if s['edit_region']:
            r=s['edit_region']
            prompt+='\nEdit only the region from '+str(round(r['x']*100,1))+'% to '+str(round((r['x']+r['width'])*100,1))+'% across and '+str(round(r['y']*100,1))+'% to '+str(round((r['y']+r['height'])*100,1))+'% down. Preserve the rest of the image.'
        for handle in re.findall(r'(?:^|[^A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]*)',prompt):
            if not any(b['snapshot']['handle'].lower()==handle.lower() for b in s['bindings']):
                saved=next((r for r in self.app.named_library() if r['handle'].lower()==handle.lower()),None)
                if s['base'] and saved and not saved['archived']:
                    prompt=re.sub(r'(^|[^A-Za-z0-9_])@'+re.escape(handle)+r'(?![A-Za-z0-9_])',lambda m:m[1]+saved['title'],prompt,flags=re.I)
                    continue
                if saved and not saved['archived'] and saved['images']:raise APIError('source_limit','Could not attach @'+handle+': all '+('five' if source_limit(s['model'])==5 else '16')+' source image slots are in use. Remove or deselect a source image, then save the prompt again.')
                if saved and not saved['archived']:raise APIError('missing_view','@'+handle+' needs an image in the asset library before it can be attached.')
                raise APIError('unknown_reference','Unknown or archived asset @'+handle+'. Choose a saved asset or correct the mention.')
        for binding in s['bindings']:
            snap=binding['snapshot']
            if not binding['selected']:
                # A deselected asset stays available in the draft, but is not
                # a generation source. Explicit mentions still require pixels.
                if s['base']:
                    prompt=re.sub(r'(^|[^A-Za-z0-9_])@'+re.escape(snap['handle'])+r'(?![A-Za-z0-9_])',lambda m:m[1]+snap['title'],prompt,flags=re.I)
                elif re.search(r'(^|[^A-Za-z0-9_])@'+re.escape(snap['handle'])+r'(?![A-Za-z0-9_])',prompt,flags=re.I):
                    raise APIError('missing_view','@'+snap['handle']+' is mentioned in the prompt but has no selected image. Select a view or remove that mention.')
                continue
            indices=[]
            for index in binding['selected']:
                sources.append(snap['images'][index]);indices.append(str(len(sources)))
            context.append(snap['category']+': '+snap['title']+' — input image(s) '+', '.join(indices)+'. '+snap.get('description',''))
            prompt=re.sub(r'(^|[^A-Za-z0-9_])@'+re.escape(snap['handle'])+r'(?![A-Za-z0-9_])',lambda m:m[1]+snap['title'],prompt,flags=re.I)
        for source in s['extras']:
            sources.append(source);context.append('Input image '+str(len(sources))+' is an additional scene reference.')
        if len(sources)>source_limit(s['model']): raise APIError('source_limit','Use at most '+('five' if source_limit(s['model'])==5 else '16')+' source images total, including the image being refined. Deselect extra views.')
        if context: prompt+='\n\nVisual references:\n'+'\n'.join(context)+'\nPreserve the supplied asset identities, proportions, materials and defining details. Follow the scene instructions without redesigning these assets.'
        if s['model'] != IMAGE_MODEL and s['ratio']!='auto': prompt+='\nRequested output canvas: '+s['ratio']+'. Preserve the described framing and subject scale; do not zoom or crop merely to achieve the canvas shape.'
        limit=self.prompt_limit(s['model'])
        if len(prompt)>limit: raise APIError('prompt_limit',f"Expanded image prompt has {len(prompt):,} characters including asset descriptions and composition guidance; {s['model']} allows {limit:,} in this app. Your draft is preserved. Shorten the scene or reference descriptions.")
        return prompt,sources

    def compile(self, record):
        s=self.normalized(record['settings']);prompt,sources=self.expanded_prompt(s)
        body={'model':s['model'],'prompt':prompt,'aspect_ratio':s['ratio'],'resolution':s['resolution'],'quality':s['quality'],'response_format':'b64_json'}
        if s['model']==IMAGE_MODEL and s['quality']=='auto':
            body.pop('quality')  # Let Grok choose its default for generation versus editing.
        def image(source):
            resolved=self.app.agent.source(source)
            if resolved.get('id'):
                asset,path=self.app.asset(resolved['id']);url='data:'+asset['mime']+';base64,'+base64.b64encode(path.read_bytes()).decode()
            else: url=resolved['src']
            return {'type':'image_url','url':url}
        if s['model'] != IMAGE_MODEL:
            body={'model':s['model'],'prompt':prompt}
            if sources: body['images']=[image(source) for source in sources]
            if s['model']=='gpt-image-2':
                return 'codex://native-image-generation',body,len(sources)
            body.update(n=s['n'],quality=s['quality'],size=s['resolution'],output_format='png')
            if s['edit_region']:
                from precision_studio import mask_for
                _,path=self.app.asset(s['base']['asset_id']);base,mask=mask_for(path,s['edit_region'])
                body['images'][0]={'type':'image_url','url':'data:image/png;base64,'+base64.b64encode(base).decode()}
                body['mask']={'url':'data:image/png;base64,'+base64.b64encode(mask).decode()}
            return ('https://api.openai.com/v1/images/edits' if sources else 'https://api.openai.com/v1/images/generations'),body,len(sources)
        if len(sources)==1: body['image']=image(sources[0])
        elif sources: body['images']=[image(source) for source in sources]
        body.update(n=s['n'],deferred=True,response_format='url')
        return ('https://api.x.ai/v1/images/edits' if sources else 'https://api.x.ai/v1/images/generations'),body,len(sources)

    def manual_review_current(self,record):
        if record.get('manual_review_revision')!=record['revision']:return False
        fingerprint=record.get('manual_prompt_review',{}).get('authoring_fingerprint')
        if not fingerprint:return True  # Existing clients' saved reviews remain supported.
        from prompt_guides import digest
        return fingerprint==digest(self.app.prompting.authoring_basis('image',record))

    def review_provenance(self, record):
        revision = record.get('manual_review_revision')
        if revision is None:
            return None
        review = record.get('manual_prompt_review') or dict(revision=revision, authored_by='human')
        return {**copy.deepcopy(review), 'current': self.manual_review_current(record)}

    def validate(self, record):
        try:
            endpoint,body,count=self.compile(record)
            warnings=['Visual consistency requires review; identical appearance is not guaranteed.']
            if record['settings'].get('edit_region'):warnings.append('Selected region uses a mask on Image 2.5 API; subscriptions use prompt guidance. Review the entire result because preservation is not guaranteed.')
            if body['model']=='gpt-image-2': warnings.append('Codex chooses automatic size/quality. Aspect ratio is prompt guidance. Model identity is the documented native default, not confirmed response metadata.')
            if body['model'] in openai_images.API_MODELS and body['size']!='auto':
                width,height=map(int,body['size'].split('x'))
                requested=record['settings']['ratio']
                if requested!='auto':
                    a,b=map(float,requested.split(':'))
                    if abs(width/height-a/b)>.01: warnings.append('Selected pixel dimensions control the output shape; aspect-ratio guidance differs from that size.')
            return dict(valid=True,errors=[],endpoint=endpoint,request=body,source_count=count,billing=IMAGE_MODELS[body['model']]['billing'],transport='Codex app-server (compiled scene; native tool call occurs during generation)' if body['model']=='gpt-image-2' else 'multipart/form-data' if body.get('images') and body['model'] in openai_images.API_MODELS else 'JSON',expanded_prompt_chars=len(body['prompt']),warnings=warnings,
                prompt_preparation_current=self.app.prompting.current('image',record) or self.manual_review_current(record),prompt_provenance=copy.deepcopy(record.get('prompt_preparation')),
                prompt_review_provenance=self.review_provenance(record))
        except ValueError as e: return dict(valid=False,errors=[str(e)])

    def generate(self, identity, data, key):
        record=self.draft(identity)
        if data.get('approved') is not True: raise APIError('approval_required','Explicit approval is required before image generation.',403)
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key): raise APIError('idempotency_required','Supply an 8–100 character Idempotency-Key.')
        fingerprint=hashlib.sha256(json.dumps({'id':identity,'revision':data.get('expected_revision'),'mock':self.app.mock},sort_keys=True).encode()).hexdigest()
        previous=next((j for j in self.db['jobs'] if j.get('key')==key),None)
        if previous:
            if previous['fingerprint']!=fingerprint: raise APIError('idempotency_conflict','This key belongs to different image settings.',409)
            return copy.deepcopy(previous)
        if data.get('expected_revision')!=record['revision']: raise APIError('revision_conflict','Review the current image draft before generation.',409)
        if not self.app.mock and not self.config['live_generations_enabled']: raise APIError('live_locked','Live image generation is locked.',403)
        if any(j.get('draft',{}).get('id')==identity and j.get('mock')==self.app.mock and j.get('recoverable') for j in self.db['jobs']):raise APIError('resume_required','Resume or discard the existing image request before starting another generation.',409)
        if not self.manual_review_current(record):self.app.prompting.require('image',record)
        endpoint,body,count=self.compile(record)
        provider=IMAGE_MODELS[body['model']]['provider']
        if not self.app.mock:
            if provider=='openai' and not openai_images.api_key(): raise APIError('api_key_required','Configure OPENAI_API_KEY on the server for Image 2.5.',403)
            if provider=='codex' and not self.account_status()['subscription']['signed_in']: raise APIError('sign_in_required','Sign in with ChatGPT in Codex, then refresh OpenAI connection.',403)
        with self.app.lock:
            if self.app.state['phase'] in ('connecting','waiting','generating','pending'): raise APIError('busy','Wait for the current image or video operation.',409)
            if provider=='grok' and not self.app.state['signed_in']: raise APIError('sign_in_required','Sign in with Grok before generating.',403)
            job=dict(id=uuid.uuid4().hex,created_at=time.time(),mock=self.app.mock,draft=copy.deepcopy(record),endpoint=endpoint,
                     expanded_prompt=body['prompt'],prompt_review_provenance=self.review_provenance(record),source_count=count,provider=provider,model=body['model'],requested_model=body['model'],returned_model=None,model_identity='unconfirmed',deferred=provider=='grok',request_id=None,recoverable=False,billing=IMAGE_MODELS[body['model']]['billing'],status='pending',message='Creating image…',outputs=[],key=key,fingerprint=fingerprint)
            self.db['jobs'].insert(0,job);self.persist()
            self.app.state.update(phase='generating',message='Generating a mock image…' if self.app.mock else 'Generating image. No automatic retry will be made.')
        self.app.spawn(self.worker,job,endpoint,body)
        return copy.deepcopy(job)

    def cache(self, raw, job):
        if len(raw)>self.config.get('image_output_limit_mb',20)*1024*1024: raise ValueError('Image output exceeds the local cache limit.')
        if raw.startswith(b'\x89PNG\r\n\x1a\n'): ext,mime='png','image/png'
        elif raw.startswith(b'\xff\xd8'): ext,mime='jpg','image/jpeg'
        elif raw.startswith(b'RIFF') and raw[8:12]==b'WEBP': ext,mime='webp','image/webp'
        else: raise ValueError('Unsupported image output format.')
        identity=uuid.uuid4().hex;path=self.app.storage/'assets'/f'{identity}.{ext}'
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(raw);path.chmod(0o600)
        asset=dict(id=identity,name=('Mock · ' if job['mock'] else '')+job['draft']['title'].replace('Character sheet','Main image')+'.'+ext,ext=ext,mime=mime,bytes=len(raw),src='/api/assets/'+identity,
                   generated=True,image_job_id=job['id'],approved=False,mock=job['mock'])
        if ext=='png' and len(raw)>=24:
            asset['width'],asset['height']=struct.unpack('>II',raw[16:24])
        elif ext in ('jpg','webp'):
            import io
            from PIL import Image
            try:
                with Image.open(io.BytesIO(raw), formats=['JPEG','WEBP']) as image:
                    asset['width'],asset['height']=image.size
            except (ValueError,OSError):pass
        requested=job['draft']['settings'].get('ratio','auto')
        asset['requested_ratio']=requested
        width,height=asset.get('width'),asset.get('height')
        if width and height and requested!='auto':
            a,b=map(float,requested.split(':'))
            deviation=abs((width/height)/(a/b)-1)*100
            asset.update(ratio_matches_request=width*b==height*a,ratio_deviation_percent=round(deviation,4))
            if not asset['ratio_matches_request']:
                detail='Minor pixel rounding' if deviation<.5 else 'Review the framing'
                asset['framing_warning']=f'Actual output {width}×{height} differs from requested {requested} by {deviation:.3f}%. {detail}; the original pixels are preserved.'
        with self.app.lock:
            self.app.assets.append(asset);self.save(self.app.assets_path,self.app.assets)
        return asset

    def resume(self, job):
        if not job.get('recoverable') or job.get('provider')!='grok' or not job.get('deferred') or not job.get('request_id'):
            raise APIError('not_resumable','This image job has no recoverable provider request.',409)
        with self.app.lock:
            if self.app.state['phase'] in ('connecting','waiting','generating','pending'):raise APIError('busy','Wait for the current operation.',409)
            job.update(status='pending',message='Resuming the existing image request. No new generation submitted.')
            self.persist();self.app.state.update(phase='pending',message=job['message'])
        self.app.spawn(self.worker,job,job['endpoint'],None)
        return copy.deepcopy(job)

    def discard(self,job,data):
        with self.lock,self.app.lock:return self._discard_locked(job,data)

    def _discard_locked(self,job,data):
        if data.get('confirmed') is not True:raise APIError('confirmation_required','Confirm discarding recovery for this image job.',403)
        if not job.get('request_id') or data.get('request_id')!=job['request_id']:raise APIError('request_conflict','Review the current provider request before discarding recovery.',409)
        if job.get('status')=='discarded':return copy.deepcopy(job)
        if job.get('status')!='error' or not job.get('recoverable'):raise APIError('not_discardable','Only a failed recoverable image job can be discarded. Wait for active work to stop.',409)
        from story_studio import text
        reason=text(data.get('reason',''),500,'Discard reason')
        before=copy.deepcopy(job)
        try:
            with self.app.productions.sql:
                audit=self.app.productions.new('image-job-audit',action='discard-recovery',job_id=job['id'],draft_id=job['draft']['id'],request_id=job['request_id'],provider=job.get('provider'),model=job.get('model'),confirmed=True,reason=reason,previous_status=job['status'])
                job.update(status='discarded',recoverable=False,discarded_at=time.time(),discard_audit_id=audit['id'],discard_reason=reason,message='Recovery discarded by confirmation. Cached outputs and request history are kept. This does not cancel provider work or refund usage.')
                self.persist()
        except Exception:
            job.clear();job.update(before);self.persist();raise
        return copy.deepcopy(job)

    def poll_grok(self, client, job):
        from studio_server import oauth_headers
        deadline=time.monotonic()+self.config.get('poll_timeout_seconds',600)
        while time.monotonic()<deadline:
            result=client.get('https://api.x.ai/v1/images/'+job['request_id'],headers=oauth_headers())
            from provider_usage import observe
            observe(self.app,result,'grok_image')
            if result.status_code==404:
                job['recoverable']=False;self.persist()
                raise ValueError('The saved Grok image request is no longer available. Deferred results expire after 24 hours.')
            if result.status_code not in (200,202):raise ValueError(f'Image polling stopped (HTTP {result.status_code}). Resume the saved request; do not resubmit.')
            payload=result.json() if result.content else {}
            status=payload.get('status') or ('pending' if result.status_code==202 else None)
            if status=='done':return payload
            if status in ('failed','expired'):
                job['recoverable']=False;self.persist()
                raise ValueError('Grok image request expired.' if status=='expired' else 'Grok image generation failed: '+openai_images.safe_error((payload.get('error') or {}).get('message','Unknown provider failure.')))
            if status!='pending':raise ValueError('Unknown image polling status. Resume the saved request.')
            time.sleep(self.config.get('poll_interval_seconds',5))
        raise ValueError('Image polling timed out. Resume the existing request; no automatic resubmission.')

    def cache_grok(self, payload, job):
        data=payload.get('data');count=job['draft']['settings'].get('n',1)
        if not isinstance(data,list) or len(data)!=count or any(not isinstance(item,dict) for item in data):raise ValueError('Unexpected image output count. Resume the saved request; do not resubmit.')
        if any(item.get('respect_moderation') is False for item in data):
            job['recoverable']=False;self.persist();raise ValueError('The image batch was filtered by moderation.')
        # Save each index as it is cached, so a download interruption does not duplicate candidates.
        outputs=list(job.get('outputs',[]))
        for index,item in enumerate(data):
            if any(o.get('candidate_index')==index for o in outputs):continue
            limit=self.config.get('image_output_limit_mb',20)*1024*1024
            if isinstance(item.get('b64_json'),str):raw=openai_images.decode_output(item['b64_json'],limit)
            elif isinstance(item.get('url'),str):raw,_=openai_images.grok_result_bytes(item['url'],limit)
            else:raise ValueError('Image result has no downloadable output. Resume the saved request.')
            output=self.cache(raw,job);output['candidate_index']=index;outputs.append(output)
            with self.lock:job['outputs']=outputs;self.persist()
        with self.lock:
            job['returned_model']=payload.get('model') if isinstance(payload.get('model'),str) else None
            job['model_identity']='confirmed' if job['returned_model'] else 'unconfirmed'
            job['revised_prompt']=data[0].get('revised_prompt') if isinstance(data[0].get('revised_prompt'),str) else None
            job['usage']={k:v for k,v in (payload.get('usage') or {}).items() if type(v) in (int,float,bool)}
        return sorted(outputs,key=lambda o:o['candidate_index'])

    def worker(self, job, endpoint, body):
        try:
            if self.app.mock:
                time.sleep(.3);outputs=[{**self.cache(mock_png(job['draft']['settings']['ratio']),job),'candidate_index':i} for i in range(job['draft']['settings'].get('n',1))]
            elif job.get('provider') in ('openai','codex'):
                generate=openai_images.generate_api if job['provider']=='openai' else openai_images.generate_subscription
                raw,metadata=generate(endpoint,body,self.config) if job['provider']=='openai' else generate(body,self.config)
                outputs=[{**self.cache(item,job),'candidate_index':i} for i,item in enumerate(raw if isinstance(raw,list) else [raw])]
                with self.lock:job.update(metadata)
            else:
                import httpx
                from studio_server import oauth_headers,upstream_error
                from grok_debug_trace import begin,post,utc
                with httpx.Client(timeout=self.config.get('image_timeout_seconds',180),follow_redirects=False) as client:
                    if body is not None:
                        credential_load_start=time.monotonic();headers=oauth_headers()
                        trace=begin(self.app,job['id'],headers['Authorization'],utc(),round(time.monotonic()-credential_load_start,6))
                        response=post(client,endpoint,headers,body,trace)
                        from provider_usage import observe
                        observe(self.app,response,'grok_image')
                        if response.status_code not in (200,202):
                            detail=upstream_error(response,(headers['Authorization'],headers['Authorization'][7:]))
                            with self.lock: job.update(http_status=response.status_code)
                            if response.status_code==401:
                                with self.lock:job.update(error_kind='authentication_expired')
                                self.app.update(signed_in=False,auth_status='error',auth_error='Grok sign-in expired. Reconnect before generating again.')
                                raise ValueError('Grok reported an expired authentication context '
                                    f'(HTTP {response.status_code}). Reconnect Grok in Workspace & account before trying again. '
                                    'This is not an outfit or content rejection.')
                            if 'auth context expired' in detail.lower():
                                with self.lock:job.update(error_kind='upstream_auth_context')
                                raise ValueError(f'Grok image service failed (HTTP {response.status_code}): '+detail+
                                    ' This does not establish that your sign-in expired. Your connection was kept.')
                            raise ValueError(f'xAI rejected the image request (HTTP {response.status_code}). '+detail)
                        payload=response.json()
                        identity=payload.get('request_id')
                        if identity is not None:
                            if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',identity):raise ValueError('Invalid image request identifier.')
                            with self.lock:job.update(request_id=identity,recoverable=True);self.persist()
                            payload=self.poll_grok(client,job)
                        elif not payload.get('data'):raise ValueError('No image request ID returned. Check usage before generating again.')
                    else:payload=self.poll_grok(client,job)
                    outputs=self.cache_grok(payload,job)
            # Publish completion and release the workspace generation gate together.
            # A client seeing done must be able to submit its next approved job.
            with self.lock,self.app.lock:
                job.update(status='done',recoverable=False,outputs=outputs,message='Mock candidates ready. No account usage consumed.' if self.app.mock else 'Candidates saved locally. Review each before approving.');self.persist()
                self.app.state.update(phase=job['status'],message=job['message'])
        except Exception as e:
            message=openai_images.safe_error(e) if isinstance(e,ValueError) else 'Network, account authentication or response validation failed.'
            if job.get('provider')=='grok' and not job.get('request_id') and not self.app.mock:message+=' No request ID was saved; check usage before starting another generation.'
            with self.lock,self.app.lock:
                job.update(status='error',message=message+' No automatic retry was made.')
                if re.search(r'quota|rate.?limit|usage.?limit|429',message,re.I):job['limit_error_at']=time.time()
                self.app.state.update(phase=job['status'],message=job['message'])
                self.persist()

    def output(self, job, identity):
        output=next((o for o in job['outputs'] if o['id']==identity),None)
        if not output: raise APIError('not_found','Image candidate not found.',404)
        return output

    def account_status(self, refresh=False):
        if self.app.mock:
            return {'api_configured':True,'subscription':{'signed_in':True,'plan':'mock','message':'Mock mode; no provider requests.'}}
        with self.account_lock:
            if refresh or self.openai_account is None or time.time()-self.openai_checked_at>60:
                self.openai_account=openai_images.subscription_status();self.openai_checked_at=time.time()
        return {'api_configured':bool(openai_images.api_key()),'subscription':copy.deepcopy(self.openai_account)}

    def dispatch(self, method, parts, data, key):
        with self.lock:
            if len(parts)==3 and parts[0]=='drafts' and parts[2]=='jobs' and method=='GET':
                draft=self.draft(parts[1]);root=draft.get('version_root_id') or draft['id']
                identities={d['id'] for d in self.db['drafts'] if d['id']==root or d.get('version_root_id')==root}|{draft['id']}
                p=getattr(self.app,'productions',None)
                if p:
                    for image_id,versions in p.sql.execute("SELECT json_extract(body,'$.image_id'),json_extract(body,'$.image_version_ids') FROM records WHERE kind='shot' AND owner='local-user'"):
                        linked={image_id,*(json.loads(versions) if versions else [])}
                        if draft['id'] in linked:identities.update(linked)
                return 200,copy.deepcopy([j for j in self.db['jobs'] if j['mock']==self.app.mock and (j['draft']['id'] in identities or j['draft'].get('version_root_id')==root)])
            if parts==['schema'] and method=='GET': return 200,self.schema()
            if parts==['openai-account'] and method=='GET': return 200,self.account_status()
            if parts==['openai-account','refresh'] and method=='POST': return 200,self.account_status(True)
            if parts==['drafts']:
                if method=='GET':return 200,copy.deepcopy(self.db['drafts'])
                if method=='POST':return 201,self.create(data)
            if parts==['workspace']:
                if method=='GET':return 200,copy.deepcopy(self.draft(self.db['current_id'])) if self.db['current_id'] else None
                if method=='POST':
                    record=self.draft(data['draft_id']) if 'draft_id' in data else self.create(data)
                    self.db['current_id']=record['id'];self.persist();return 200,copy.deepcopy(record)
            if len(parts)>=2 and parts[0]=='drafts':
                record=self.draft(parts[1])
                if len(parts)==2 and method=='GET':return 200,copy.deepcopy(record)
                if len(parts)==3 and parts[2]=='versions' and method=='GET':return 200,self.versions(record['id'])
                if len(parts)==3 and parts[2]=='review-prompt' and method=='POST':
                    if data.get('expected_revision')!=record['revision']:raise APIError('revision_conflict','The image inputs changed. Review the current prompt.',409)
                    if data.get('reviewed') is not True:raise APIError('review_required','Explicitly review the image prompt first.',403)
                    authored_by=data.get('authored_by','human')
                    if authored_by not in ('agent','human'):raise APIError('invalid_author','authored_by must be agent or human.')
                    self.compile(record)
                    record['manual_review_revision']=record['revision']
                    from prompt_guides import digest
                    record['manual_prompt_review']=dict(revision=record['revision'],authored_by=authored_by,reviewed_at=time.time(),authoring_fingerprint=digest(self.app.prompting.authoring_basis('image',record)))
                    self.persist()
                    return 200,copy.deepcopy(record)
                if len(parts)==2 and method=='PUT':return 200,self.edit(parts[1],data)
                if len(parts)==3 and parts[2]=='refresh-reference' and method=='POST':
                    if data.get('expected_revision')!=record['revision']:
                        raise APIError('revision_conflict','Image draft changed. Fetch its current revision before updating the asset.',409)
                    settings=copy.deepcopy(record['settings'])
                    binding=next((b for b in settings['bindings'] if b['snapshot']['id']==data.get('reference_id')),None)
                    if not binding:raise APIError('not_found','This asset is not attached to the image draft.',404)
                    latest=next((r for r in self.app.named_library() if r['id']==data['reference_id']),None)
                    if not latest:raise APIError('not_found','Asset no longer exists; the draft snapshot was preserved.',404)
                    old=binding['snapshot']
                    source_key=lambda source:json.dumps(source,sort_keys=True)
                    selected={source_key(old['images'][i]) for i in binding['selected']}
                    binding['selected']=[i for i,source in enumerate(latest['images']) if source_key(source) in selected]
                    binding['snapshot']=copy.deepcopy(latest)
                    if old['handle']!=latest['handle']:
                        pattern=r'(?<![A-Za-z0-9_])@'+re.escape(old['handle'])+r'(?![A-Za-z0-9_])'
                        settings['prompt']=re.sub(pattern,lambda m:'@'+latest['handle'],settings['prompt'],flags=re.I)
                    return 200,self.edit(record['id'],{'expected_revision':data['expected_revision'],'settings':settings})
                if len(parts)==3 and parts[2]=='validate' and method=='POST':return 200,self.validate(record)
                if len(parts)==3 and parts[2]=='generate' and method=='POST':return 202,self.generate(parts[1],data,key)
            if parts==['jobs'] and method=='GET':return 200,copy.deepcopy([j for j in self.db['jobs'] if j['mock']==self.app.mock])
            if len(parts)>=2 and parts[0]=='jobs':
                job=self.job(parts[1])
                if len(parts)==2 and method=='GET':return 200,copy.deepcopy(job)
                if len(parts)==3 and parts[2]=='resume' and method=='POST':return 202,self.resume(job)
                if len(parts)==3 and parts[2]=='discard' and method=='POST':return 200,self.discard(job,data)
                if len(parts)==4 and parts[2]=='outputs' and method=='GET':
                    output=self.output(job,parts[3]);asset,path=self.app.asset(output['id']);return 200,(path.read_bytes(),asset['mime'])
                if len(parts)==3 and parts[2] in ('reference-suggestion','reference') and method=='POST':
                    output=self.output(job,data.get('asset_id'))
                    asset,_=self.app.asset(output['id'])
                    if not output['approved'] or not asset.get('approved'):
                        raise APIError('review_required','Approve this image after reviewing it before saving a reference.',403)
                    category=data.get('category','Location')
                    if category not in ('Location','Character','Prop'):
                        raise APIError('invalid_category','Choose Location, Character or Prop.')
                    from reference_suggestions import suggest
                    suggestion=suggest(job,output,self.app.named_library(),self.config,category)
                    if parts[2]=='reference-suggestion':return 200,suggestion
                    details={**suggestion,**{k:data[k] for k in ('title','handle','description','category','voice','images') if k in data}}
                    if not isinstance(details['images'],list) or {'asset_id':output['id']} not in details['images']:
                        raise APIError('missing_source','Keep the approved generated image attached to this reference.')
                    return 201,self.app.save_reference(details)
                if len(parts)==3 and parts[2]=='reuse' and method=='POST':return 201,self.create({'title':data.get('title',job['draft']['title']),'settings':job['draft']['settings'],'story_context':job['draft'].get('story_context'),'parent_draft_id':job['draft']['id']})
                if len(parts)==3 and parts[2]=='refine' and method=='POST':
                    output=self.output(job,data.get('asset_id'));settings=copy.deepcopy(job['draft']['settings']);settings['base']={'asset_id':output['id']};settings['edit_region']=None;settings['prompt']=data.get('prompt','')
                    for binding in settings['bindings']: binding['selected']=[]
                    settings['extras']=[]
                    return 201,self.create({'title':data.get('title',job['draft']['title']),'settings':settings,'story_context':job['draft'].get('story_context'),'parent_draft_id':job['draft']['id']})
                if len(parts)==3 and parts[2]=='approve' and method=='POST':
                    if type(data.get('approved')) is not bool:raise APIError('invalid_approval','Use an approved boolean.')
                    output=self.output(job,data.get('asset_id'))
                    from candidate_review import available
                    available(self.app.asset(output['id'])[0])
                    if not data['approved']:
                        from candidate_review import dependencies
                        if dependencies(self.app,output['id']):raise APIError('reference_in_use','This image is still used by saved work. Replace those uses before removing approval.',409)
                    with self.app.lock:
                        asset=next(a for a in self.app.assets if a['id']==output['id'])
                        asset.update(approved=data['approved'],review_state='approved' if data['approved'] else 'candidate',review_revision=asset.get('review_revision',0)+1)
                        self.save(self.app.assets_path,self.app.assets)
                    output.update(approved=data['approved'],review_state=asset['review_state'],review_revision=asset['review_revision']);self.persist();return 200,copy.deepcopy(output)
                if len(parts)==3 and parts[2]=='download' and method=='GET':
                    output=self.output(job,job['outputs'][0]['id'] if job['outputs'] else None);asset,path=self.app.asset(output['id']);return 200,(path.read_bytes(),asset['mime'])
                if len(parts)==3 and parts[2]=='transfer' and method=='POST':
                    output=self.output(job,data.get('asset_id'))
                    if not output['approved']:raise APIError('review_required','Approve this image after reviewing it before video use.',403)
                    if data.get('new_scene') is True:
                        from frame_tools import place
                        return 201,place(self.app.agent,output['id'],data)
                    record=self.app.agent.record(data.get('scene_id'));scene=copy.deepcopy(record['scene']);target=data.get('target')
                    if target=='reference':
                        from frame_tools import place
                        return 200,place(self.app.agent,output['id'],{**data,'target':'reference'})
                    if target not in ('first','last','keyframe'):raise APIError('invalid_target','Choose first, last or keyframe.')
                    if target=='last' and scene['model']!='grok-imagine-video-1.5':raise APIError('model_limit','Last frames require Video 1.5.')
                    if scene['model'] not in ('grok-imagine-video-1.5','grok-imagine-video-1.5-lite'):raise APIError('invalid_model','Choose Video 1.5 or Lite before placing a frame.')
                    source=self.app.agent.source({'asset_id':output['id']})
                    if target=='keyframe':
                        slot=data.get('slot')
                        if scene['model']!='grok-imagine-video-1.5':raise APIError('model_limit','Keyframes require Video 1.5.')
                        if type(slot) is not int or not 0<slot<scene['duration']*3 or len(scene['keys'])>=4 or any(k['slot']==slot for k in scene['keys']):raise APIError('invalid_slot','Choose an unused interior ⅓-second slot; use at most four keyframes.')
                        scene['keys'].append({'id':uuid.uuid4().hex,'source':source,'slot':slot})
                    else:
                        if scene[target] and data.get('replace') is not True:raise APIError('replace_required','This frame is occupied. Explicitly confirm replacing it.',409)
                        before=copy.deepcopy(scene);scene[target]=source;self.app.agent.retag(before,scene)
                    return 200,self.app.agent.edit(record['id'],{'expected_revision':data.get('expected_revision'),'scene':scene})
            raise APIError('not_found','Image Studio route not found.',404)
