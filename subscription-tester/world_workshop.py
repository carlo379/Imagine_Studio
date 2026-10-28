"""Visual world development. Existing subscription transports render the images.

Queue state is durable, generation is explicit, and interrupted batches never replay.
"""
import copy
import hashlib
import io
import json
import re
import time
import uuid
from agent_api import APIError
from story_studio import text
from image_studio import DEFAULTS
from character_metadata import profile_description, library_description

MODELS=('gpt-image-2','grok-imagine-image-2.0')
CAST={'name':80,'role':120,'age':80,'gender':80,'personality':10000,'motivation':10000,'relationships':10000,'description':10000,'hair':160,'eyes':160,'skin':160,'height':80,'build':160,'ethnicity':160,'clothing':10000}
PLACE={'name':80,'description':10000,'time':80,'lighting':1000,'grading':10000}
COVERAGE={'Wide':'Wide establishing shot showing the full environment.','Medium':'Medium shot of the main activity area.','Close-up':'Close-up of a defining architectural or environmental feature.','Aerial':'Elevated aerial view of the location.','Low angle':'Low camera angle looking up through the environment.','Reverse':'Reverse angle revealing the opposite side of the same place.','Interior':'Interior view consistent with the established architecture.','Detail':'Extreme detail of the defining textures and materials.'}

class WorldWorkshop:
    def __init__(self,film):
        self.f=film;self.app=film.app;self.p=film.p
        with self.p.sql:
            for batch in self.p.all('world-render'):
                if batch['status']=='pending':
                    batch.update(status='error',error='Generation was interrupted. Completed images are saved; remaining requests were not sent.',revision=batch['revision']+1)
                    self.p.put('world-render',batch)

    def normalize_guide(self,g):
        if not isinstance(g,dict) or set(g)-{'cast','places','acts','script'}:raise APIError('invalid_guide','Check the story cards.')
        out={'script':text(g.get('script',''),60000,'Imported script')}
        for key,limits,max_count in [('cast',CAST,8),('places',PLACE,4),('acts',{'title':120,'text':6000},8)]:
            entries=g.get(key,[])
            if not isinstance(entries,list) or len(entries)>max_count:raise APIError('guide_limit',f'Use at most {max_count} {key} cards.')
            out[key]=[]
            for entry in entries:
                if not isinstance(entry,dict) or set(entry)-set(limits)-{'id','reference_ids','palette'}:raise APIError('invalid_guide','Check the '+key+' fields.')
                item={k:text(entry.get(k,''),v,k.title()) for k,v in limits.items()}
                item['id']=text(entry.get('id',''),80,'Card id',True)
                refs=entry.get('reference_ids',[])
                if not isinstance(refs,list) or len(refs)>5:raise APIError('guide_limit','Use up to five inspiration images per card.')
                for identity in refs:self.safe_asset(identity)
                item['reference_ids']=refs
                palette=entry.get('palette',[])
                if not isinstance(palette,list) or len(palette)>6 or any(not isinstance(c,str) or not re.fullmatch('#[0-9a-fA-F]{6}',c) for c in palette):raise APIError('invalid_palette','Use up to six hex colors.')
                item['palette']=palette
                out[key].append(item)
        return out

    def safe_asset(self,identity):
        if not isinstance(identity,str):raise APIError('invalid_reference','Choose a local reference image.')
        asset,path=self.app.asset(identity)
        from candidate_review import available
        available(asset)
        if asset.get('generated') and not asset.get('approved'):raise APIError('review_required','Review the generated reference first.',403)
        from PIL import Image
        try:
            with Image.open(path) as im:
                if im.width*im.height>40000000:raise ValueError()
                im.verify()
        except Exception:raise APIError('invalid_reference','Use a valid PNG, JPEG or WebP image.') from None
        return asset,path

    def reference(self,pid,data):
        self.f.production(pid)
        # Validate the upload before putting it in the shared library.
        import base64
        from PIL import Image
        raw=data.get('data_url','')
        try:
            if not isinstance(raw,str) or not re.match(r'^data:image/(png|jpeg|webp);base64,',raw):raise ValueError()
            decoded=base64.b64decode(raw.split(',',1)[1],validate=True)
            if len(decoded)>10*1024*1024:raise ValueError()
            with Image.open(io.BytesIO(decoded)) as im:
                if im.width*im.height>40000000:raise ValueError()
                im.verify()
            with Image.open(io.BytesIO(decoded)) as im:
                im=im.convert('RGB');im.thumbnail((128,128))
                colors=im.quantize(colors=5).convert('RGB').getcolors(16384)
                palette=['#%02x%02x%02x'%color for _,color in sorted(colors,reverse=True)[:5]]
        except Exception:raise APIError('invalid_reference','Upload a PNG, JPEG or WebP image under 10 MB.') from None
        asset=self.app.upload(data)
        return dict(asset=asset,palette=palette)

    def description(self,profile):
        # The profile remains the complete source of truth. Display summaries
        # prioritize appearance and omit whole oversized fields explicitly.
        return profile_description(profile)

    def job(self,pid,identity=None):
        self.f.production(pid)
        jobs=[j for j in self.p.all('world-job') if j['production_id']==pid and j['mock']==self.app.mock and j['status']=='done']
        if not identity:jobs=[j for j in jobs if not j.get('scope')]
        j=next((j for j in jobs if j['id']==identity),None) if identity else (jobs[-1] if jobs else None)
        if not j:raise APIError('not_ready','Build and review your story first.',409)
        return j

    def entity(self,identity):
        e=self.p.get(identity,'world-entity');self.job(e['production_id'],e['world_job_id']);return e

    def sync_view_metadata(self,entity):
        # A view's name is its linked entity's label; its independently editable
        # view/outfit title and all saved image settings remain unchanged.
        for view in self.p.all('world-asset'):
            if view.get('entity_id')==entity['id'] and (view['name']!=entity['name'] or view['description']!=entity['description']):
                view.update(name=entity['name'],description=entity['description'],revision=view['revision']+1)
                self.p.put('world-asset',view)

    def model(self,value):
        if value not in MODELS:raise APIError('invalid_model','Choose ChatGPT or Grok subscription images.')
        return value

    def settings(self,model,prompt,ratio='16:9',refs=None):
        return {**copy.deepcopy(DEFAULTS),'model':self.model(model),'prompt':prompt,'ratio':ratio,'quality':'auto' if model in ('gpt-image-2','grok-imagine-image-2.0') else 'low','resolution':'auto' if model=='gpt-image-2' else '1k','extras':[{'asset_id':r} for r in refs or []]}

    def prompt(self,e,kind,label,details=''):
        j=self.job(e['production_id'],e['world_job_id'])
        if e['category']=='Character' and kind in ('portrait','sheet'):
            # Reserve space for every view and outfit instruction. Narrative
            # biographies are retained in the Bible, not duplicated in edits.
            profile=e.get('profile',{})
            parts=['Create one polished character reference sheet with five clearly separated views: full body front, full body rear (back), full body side, full body three-quarter (3/4), and a head close-up. Same face, proportions and outfit in every view. Neutral standing poses, full figures uncropped, generous spacing on a simple neutral background.',
                   'Character: '+e['name'][:80]+'.']
            if kind=='sheet':
                parts += ['Use input image 1 as the approved character identity. Preserve his or her face, hair, body, age and rendering style. Change only clothing and accessories; the reference outfit must not override the requested outfit.',
                          'Requested outfit ('+label[:80]+'): '+(details[:800] or label[:80])+'.']
            else:parts.append('Establish a distinctive, reusable identity from these visual details.')
            for field,limit in [('gender',40),('age',80),('ethnicity',100),('height',60),('build',80),('hair',80),('eyes',60),('skin',60)]:
                if profile.get(field):parts.append(field.title()+': '+profile[field][:limit]+'.')
            if profile.get('description'):
                parts.append('Appearance & distinguishing details: '+profile['description'][:1000]+'.')
            if kind=='portrait':
                if profile.get('clothing'):parts.append('Main outfit: '+profile['clothing'][:500]+'.')
                # Freeform appearance still matters when no structured visuals
                # were provided. Summaries synthesized from profile fields are
                # already represented above and need not be repeated.
                if not profile.get('description') and e.get('description') and not any(e['description'].startswith(k.title()+':') for k in profile):
                    parts.append('Appearance: '+e['description'][:400]+'.')
            parts.append('Series visual style: '+j['result']['visual_style'][:200]+'.')
            palette=profile.get('palette',[])[:5]
            if palette:parts.append('Identity color palette: '+', '.join(palette)+'.')
            parts.append('No captions, labels or watermarks.')
            return '\n'.join(parts)
        fields=e.get('profile',{})
        lighting='Lighting: '+fields['lighting'][:1000]+'\n' if e['category']=='Location' and fields.get('lighting') else ''
        profile=self.description({k:v for k,v in fields.items() if not (lighting and k=='lighting')})
        base=f"{e['category']} reference: {e['name']}.\n{lighting}{e['description'][:1000]}\n{profile[:1000]}\nLook: {j['result']['visual_style'][:400]}.\n"
        if kind in ('portrait','sheet'):
            layout='Create one polished character reference sheet with five clearly separated views: full body front, full body rear (back), full body side, full body three-quarter (3/4), and a head close-up. Same character, face, proportions, clothing and colors in every view. Neutral standing poses, full figures uncropped, generous spacing on a simple neutral background. '
            if kind=='sheet':layout+='Preserve the identity in the supplied reference. Outfit: '+details+'\n'
            else:layout+='Establish a distinctive, reusable identity from these character details.\n'
            base=layout+base
        elif kind=='location':base+='Cinematic location scouting image in the series visual style. Establish coherent geography, architecture, scale and atmosphere. '+details
        elif kind=='prop':base+='Clean reusable prop reference. Show the complete object, silhouette, construction, materials and defining details. Neutral uncluttered background. '+details
        elif e['category']=='Prop':base+='Consistent alternate view of the same object. Preserve shape, construction, materials, scale and defining features. '+details
        else:base+=COVERAGE.get(label,details)+' Preserve geography, architecture, colors and materials from the supplied location reference.'
        palette=e.get('profile',{}).get('palette',[])
        if palette:base+=' Color palette: '+', '.join(palette)+'.'
        return (base+' No captions, labels or watermarks.')[:4096 if e['category']=='Location' else 2700]

    def new_view(self,e,kind,label,model,details=''):
        if kind=='portrait':label='Character sheet'
        refs=e.get('profile',{}).get('reference_ids',[])[:5]
        if kind in ('sheet','coverage'):
            if not e.get('identity_asset_id'):raise APIError('identity_required','Confirm the main reference before creating variations.',409)
            refs=[e['identity_asset_id']]
        draft=self.app.images.create(dict(title=(e['name']+' · '+label)[:120],settings=self.settings(model,self.prompt(e,kind,label,details),'3:2' if kind in ('portrait','sheet') else '16:9',refs)))
        return self.p.new('world-asset',world_job_id=e['world_job_id'],production_id=e['production_id'],entity_id=e['id'],media_production_id=None,shot_id=None,draft_id=draft['id'],name=e['name'],category=e['category'],description=e['description'],view=label,kind=kind,details=details,reference_id=None,existing_reference_id=None,selected_asset_id=None)

    def start(self,pid,data):
        j=self.job(pid,data.get('job_id'));self.p.check(j,data)
        if j.get('workshop_started'):return self.snapshot(pid,j['id'])
        world=self.f.world(pid);model=self.model(data.get('model','gpt-image-2'))
        if not j.get('applied') and world['revision']!=j['world_revision']:raise APIError('revision_conflict','Your story inputs changed. Build a fresh story first.',409)
        guide=world.get('guide',{})
        with self.p.mutation():
            if not j.get('applied'):
                populated=copy.deepcopy(guide)
                for key,category,limits,maximum in [('cast','Character',CAST,8),('places','Location',PLACE,4)]:
                    entries=populated.get(key,[])
                    for asset in j['result']['assets']:
                        if asset['category']!=category:continue
                        blank=next((c for c in entries if c['name'].casefold()==asset['name'].casefold()),None) or next((c for c in entries if not c.get('name')),None)
                        if blank is None:
                            if len(entries)>=maximum:continue
                            blank=dict(id=str(uuid.uuid4()),name='');entries.append(blank)
                        blank['name']=asset['name']
                        for field,value in asset.get('profile',{}).items():
                            if field in limits and not blank.get(field):blank[field]=value
                        if key=='places' and not blank.get('description'):blank['description']=asset['description'][:1200]
                        if key=='cast' and not blank.get('personality'):blank['personality']=asset['description'][:500]
                    populated[key]=entries
                if not any(a.get('text') for a in populated.get('acts',[])):
                    populated['acts']=[dict(id=str(uuid.uuid4()),title=scene['title'],text=scene['text'][:6000]) for scene in j['result']['scenes']]
                if populated!=guide:
                    world=self.f.save_world(pid,dict(expected_revision=world['revision'],answers=world['answers'],guide=populated))
                    guide=world['guide'];j['world_revision']=world['revision']
            for asset in j.get('applied_plan',j['result'])['assets']:
                profiles=guide.get('cast' if asset['category']=='Character' else 'places',[])
                limits=CAST if asset['category']=='Character' else PLACE
                profile={k:v for k,v in asset.get('profile',{}).items() if k in limits}
                profile.update({k:v for k,v in next((copy.deepcopy(c) for c in profiles if c['name'].casefold()==asset['name'].casefold()),{}).items() if v not in ('',[],None)})
                name=asset['name'].lstrip('@').casefold()
                canonical=next((r for r in self.app.named_library() if not r.get('archived') and not r.get('needs_replacement') and r['category']==asset['category'] and name in (r['title'].casefold(),r['handle'].casefold()) and r['images']),None)
                identity=canonical['images'][0].get('asset_id') if canonical else None
                e=self.p.new('world-entity',production_id=pid,world_job_id=j['id'],name=asset['name'],category=asset['category'],description=asset['description'],profile=profile,identity_asset_id=identity,reference_id=canonical['id'] if canonical else None,suggested_views=asset['views'])
                legacy=[r for r in self.p.all('world-asset') if r['world_job_id']==j['id'] and r['name']==e['name']]
                if legacy:
                    for i,r in enumerate(legacy):
                        r.update(entity_id=e['id'],kind=('portrait' if e['category']=='Character' else 'location') if i==0 else ('sheet' if e['category']=='Character' else 'coverage'),selected_asset_id=None,revision=r['revision']+1);self.p.put('world-asset',r)
                        old=self.f.asset_view(r)
                        if i==0 and old['approved'] and old.get('reference_id'):
                            e.update(identity_asset_id=old['candidate']['id'],reference_id=old['reference_id'],revision=e['revision']+1);self.p.put('world-entity',e)
                else:self.new_view(e,'portrait' if e['category']=='Character' else 'location','Identity portrait' if e['category']=='Character' else 'Location reference',model)
            j.update(workshop_started=True,revision=j['revision']+1);self.p.put('world-job',j)
            if j.get('applied'):self.connect_shots(j)
        return self.snapshot(pid,j['id'])

    def image_jobs(self,r):
        # Refinements create new drafts. Follow only the edited base/parent image,
        # never loose inspiration inputs, so edits belong to the original view.
        all_jobs=[j for j in self.app.images.db['jobs'] if j['mock']==self.app.mock]
        roots={j['id']:j for j in all_jobs if j['draft']['id']==r['draft_id']}
        sources={o['id']:j for j in roots.values() for o in j.get('outputs',[])}
        generated={o['id'] for j in all_jobs for o in j.get('outputs',[])}
        for identity in r.get('uploaded_candidate_ids',[])+([r['selected_asset_id']] if r.get('selected_asset_id') else []):
            if identity not in generated or (identity in r.get('uploaded_candidate_ids',[]) and r['kind'] not in ('sheet','coverage')):
                sources.setdefault(identity,None)
        while True:
            added=False
            for job in all_jobs:
                if job['id'] in roots:continue
                parent=job.get('parent_asset_id') or (job['draft']['settings'].get('base') or {}).get('asset_id')
                if parent not in sources:continue
                root=sources[parent];roots[job['id']]=root
                for output in job.get('outputs',[]):sources[output['id']]=root
                added=True
            if not added:break
        return [j for j in all_jobs if j['id'] in roots],roots

    def view(self,r):
        jobs,roots=self.image_jobs(r)
        entity=self.entity(r['entity_id']) if r.get('entity_id') else None
        def compatible(job):
            if r.get('kind') not in ('sheet','coverage'):return True
            original=roots[job['id']]
            if original is None:return bool(entity.get('identity_asset_id'))
            settings=original['draft']['settings'];sources=[a.get('asset_id') for a in settings['extras']]+[b['snapshot']['images'][i].get('asset_id') for b in settings['bindings'] for i in b['selected']]
            return bool(entity.get('identity_asset_id')) and entity['identity_asset_id'] in sources
        from candidate_review import state
        outputs=[]
        for j in reversed(jobs):
            for o in j.get('outputs',[]):
                asset,_=self.app.asset(o['id'])
                outputs.append({**o,'job_id':j['id'],'draft_id':j['draft']['id'],'compatible':compatible(j),'review_state':state(asset),'review_reason':asset.get('review_reason',''),'review_revision':asset.get('review_revision',0)})
        selected=r.get('selected_asset_id')
        # Uploaded finished images have no generation job. Keep them reviewable
        # after clearing an accidental approval instead of losing their gallery.
        uploaded=list(r.get('uploaded_candidate_ids',[]))
        if selected and selected not in uploaded:uploaded.append(selected)
        for identity in uploaded:
            if any(o['id']==identity for o in outputs):continue
            a,_=self.app.asset(identity)
            outputs.append({**a,'uploaded':True,'approved':bool(a.get('approved') or selected==identity),
                            'review_state':state(a),'review_reason':a.get('review_reason',''),
                            'review_revision':a.get('review_revision',0),'compatible':r.get('kind') not in ('sheet','coverage') or bool(entity.get('identity_asset_id'))})
        for output in outputs:
            output.update(r.get('candidate_reviews',{}).get(output['id'],{}))
        draft=copy.deepcopy(self.app.images.draft(r['draft_id']))
        draft['prompt_preparation_current']=self.app.prompting.current('image',draft)
        batches=[b for b in self.p.all('world-render') if b['mock']==self.app.mock and b['status']=='pending' and r['id'] in b['view_ids']]
        recommended=self.prompt(entity,r['kind'],r['view'],r.get('details','')) if entity and r['kind'] in ('portrait','sheet','location','prop') else draft['settings']['prompt']
        if draft['prompt_preparation_current']:recommended=draft['settings']['prompt']
        attempts=[dict(id=j['id'],error=j.get('message') or 'Image generation failed.',model=j.get('model'),error_kind=j.get('error_kind'),dismissed=j['id'] in r.get('dismissed_attempt_ids',[])) for j in jobs if j['status']=='error']
        # Interrupted/cancelled batches can fail before an image job exists.
        for batch in self.p.all('world-render'):
            if batch['mock']==self.app.mock and r['id'] in batch['view_ids'] and batch['status'] in ('error','cancelled') and not any(j['id'] in batch.get('image_job_ids',[]) and j['status']=='error' for j in jobs):
                attempts.append(dict(id=batch['id'],error=batch.get('error') or 'Generation was cancelled before completion.',model=None,error_kind=None,dismissed=batch['id'] in r.get('dismissed_attempt_ids',[])))
        latest=jobs[0] if jobs else None
        failed=latest if latest and latest['status']=='error' else None
        return {**r,'attempts':attempts,'outputs':outputs,'selected':selected,'draft':draft,'recommended_prompt':recommended,'pending':bool(batches),'render_state':'generating' if any(j['status']=='pending' for j in jobs) else 'queued' if batches else 'idle','error':failed.get('message') if failed else None,'error_model':failed.get('model') if failed else None,'error_kind':failed.get('error_kind') if failed else None}

    def review_attempt(self,identity,data):
        view=self.p.get(identity,'world-asset');self.job(view['production_id'],view['world_job_id'])
        with self.p.mutation():
            self.p.check(view,data)
            ids=data.get('attempt_ids');action=data.get('action')
            if action not in ('dismiss','restore') or not isinstance(ids,list) or not ids or len(ids)>1000 or any(not isinstance(i,str) for i in ids):
                raise APIError('invalid_review','Choose failed attempts to dismiss or restore.')
            known={a['id'] for a in self.view(view)['attempts']}
            if not set(ids)<=known:raise APIError('invalid_review','This failed attempt does not belong to this view.')
            dismissed=set(view.get('dismissed_attempt_ids',[]))
            dismissed=dismissed|set(ids) if action=='dismiss' else dismissed-set(ids)
            view.update(dismissed_attempt_ids=sorted(dismissed),revision=view['revision']+1)
            self.p.put('world-asset',view)
        return self.view(view)

    def snapshot(self,pid,job_id=None):
        j=self.job(pid,job_id)
        return dict(job=j,entities=[e for e in self.p.all('world-entity') if e['world_job_id']==j['id']],views=[self.view(r) for r in self.p.all('world-asset') if r['world_job_id']==j['id']],batches=[b for b in self.p.all('world-render') if b['world_job_id']==j['id'] and b['mock']==self.app.mock])

    def render_settings(self,settings,model):
        """Switch image connections without changing reviewed creative content."""
        result=copy.deepcopy(settings)
        if result['model']!=model:
            result.update(model=model,quality='auto',resolution='auto' if model=='gpt-image-2' else '1k',n=1)
        return result

    def prepare_settings(self,e,r,d,*,fresh=False,model=None,prompt=None,refresh_prompt=True,character_sheet=False):
        """Prepare a workflow draft, never historical jobs or refinement drafts.

        Opening/saving retains usable refinement inputs, but repairs rejected,
        trashed or missing legacy bases. Fresh generation always starts from the
        visible inspiration/approved identity, without a hidden refinement region.
        """
        s=copy.deepcopy(d['settings'])
        discard_base=fresh
        if s.get('base') and not discard_base:
            try:
                discard_base=self.app.agent.source(s['base']) is None
            except ValueError:
                discard_base=True
        if discard_base:s['base']=None
        if not s.get('base'):s['edit_region']=None
        if refresh_prompt:s['prompt']=self.prompt(e,r['kind'],r['view'],r.get('details',''))
        if model:
            s.update(model=model,quality='auto' if model in MODELS else 'low',resolution='auto' if model=='gpt-image-2' else '1k')
        if character_sheet:
            if e['category']!='Character' or r['kind'] not in ('portrait','sheet'):
                raise APIError('invalid_view','Choose a character reference view.')
            s.update(prompt=self.prompt(e,r['kind'],r['view'],r.get('details','')),ratio='3:2')
        if prompt is not None:s['prompt']=text(prompt,self.app.images.prompt_limit(s['model']),'Image direction',True)
        if r['kind'] in ('portrait','location','prop'):
            s['extras']=[{'asset_id':a} for a in e.get('profile',{}).get('reference_ids',[])]
            s['bindings']=[]
        elif r['kind'] in ('sheet','coverage'):
            # An unapproved entity can still open its old views. Generation
            # separately requires an approved identity before submitting them.
            s['extras']=[{'asset_id':e['identity_asset_id']}] if e.get('identity_asset_id') else []
            s['bindings']=[]
        return s

    def edit(self,identity,data):
        e=self.entity(identity);self.p.check(e,data)
        profile=data.get('profile',e['profile'])
        key={'Character':'cast','Location':'places','Prop':'props'}[e['category']]
        if self.job(e['production_id'],e['world_job_id']).get('scope'):
            guide=self.f.series.guide({key:[{**profile,'id':identity}]})
        else:
            guide=self.normalize_guide({'cast':[dict(id=identity,**{k:v for k,v in profile.items() if k!='id'})]} if e['category']=='Character' else {'places':[dict(id=identity,**{k:v for k,v in profile.items() if k!='id'})]})
        description=text(data.get('description',e['description']),10000,'Description',True)
        updated_profile=guide[key][0]
        if description==e['description']:
            lines=description.splitlines()
            for field,old in e['profile'].items():
                if not isinstance(old,str) or not old:continue
                label=field.replace('_',' ').title()+': '
                lines=[label+updated_profile.get(field,'') if line==label+old else line for line in lines]
            description='\n'.join(lines)
        prior_preset=e.get('profile',{}).get('voice_preset')
        e.update(description=description,profile=updated_profile,revision=e['revision']+1)
        with self.f.asset_mutation():
            self.p.put('world-entity',e)
            self.sync_view_metadata(e)
            preset=updated_profile.get('voice_preset')
            if (preset or ('voice_preset' in profile and prior_preset and preset!=prior_preset)) and e.get('reference_id'):
                ref=self.app.asset_studio.get(e['reference_id'])
                if ref.get('voice')!=(preset or None):self.app.asset_studio.dispatch('PUT',[ref['id']],dict(expected_revision=ref['revision'],voice=preset or None),None)
            for r in self.p.all('world-asset'):
                if r.get('entity_id')==identity and not r.get('selected_asset_id'):
                    d=self.app.images.draft(r['draft_id']);s=self.prepare_settings(e,r,d)
                    self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings=s))
        return e

    def add_views(self,identity,data):
        e=self.entity(identity);self.p.check(e,data);model=self.model(data.get('model','gpt-image-2'))
        entries=data.get('views')
        if not isinstance(entries,list) or not 1<=len(entries)<=8:raise APIError('view_limit','Add 1-8 views at a time.')
        current=[r for r in self.p.all('world-asset') if r.get('entity_id')==identity]
        if len(current)+len(entries)>32:raise APIError('view_limit','Keep each asset to 32 views.')
        normalized=[]
        for item in entries:
            label=text(item.get('label'),80,'View name',True);details=text(item.get('details',''),800,'View details')
            kind='sheet' if e['category']=='Character' else 'coverage'
            normalized.append((kind,label,details))
        with self.p.mutation():
            result=[self.new_view(e,kind,label,model,details) for kind,label,details in normalized]
            e.update(revision=e['revision']+1);self.p.put('world-entity',e)
        return result

    def generate(self,pid,data,key):
        j=self.job(pid,data.get('job_id'))
        if data.get('approved') is not True:raise APIError('approval_required','Choose Generate to authorize these images.',403)
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):raise APIError('idempotency_required','Supply a unique generation key.')
        fingerprint=hashlib.sha256(json.dumps([pid,data,self.app.mock],sort_keys=True).encode()).hexdigest()
        previous=next((b for b in self.p.all('world-render') if b.get('key')==key),None)
        if previous:
            if previous['fingerprint']!=fingerprint:raise APIError('idempotency_conflict','Use a new key for different requests.',409)
            return previous
        if any(b['status']=='pending' for b in self.p.all('world-render')) or self.app.state['phase'] in ('connecting','waiting','generating','pending'):raise APIError('busy','Wait for the current generation to finish.',409)
        requests=data.get('requests',[])
        if not isinstance(requests,list) or not 1<=len(requests)<=8:raise APIError('batch_limit','Generate 1-8 images at a time.')
        model=self.model(data.get('model','gpt-image-2'));prepared=[]
        for request in requests:
            r=self.p.get(request.get('view_id'),'world-asset')
            if r['world_job_id']!=j['id']:raise APIError('invalid_view','Choose a view from this story.')
            self.p.check(r,request)
            e=self.entity(r['entity_id'])
            if r['kind'] in ('sheet','coverage') and not e.get('identity_asset_id'):raise APIError('identity_required','Confirm the main reference first.',409)
            d=self.app.images.draft(r['draft_id'])
            if not self.app.mock or self.app.prompting.current('image',d):
                self.app.prompting.require('image',d)
                requested=request.get('prompt')
                if requested is not None and requested not in (d['settings']['prompt'],d.get('prompt_preparation',{}).get('brief')):
                    raise APIError('prompt_preparation_required','Prepare and review this view for the updated creative brief before generating.',409)
                # Render the reviewed preparation exactly; templates are briefs.
                s=self.render_settings(d['settings'],model)
            else:
                s=self.prepare_settings(e,r,d,fresh=True,model=model,prompt=request.get('prompt'),
                    refresh_prompt=r['kind'] in ('portrait','location','prop'),character_sheet=request.get('character_sheet') is True)
            self.app.images.compile({**d,'settings':s});prepared.append((r,d,s))
        if not self.app.mock:
            if not self.app.agent.config['live_generations_enabled']:raise APIError('live_locked','Live generation is locked.',403)
            if model=='gpt-image-2' and not self.app.images.account_status()['subscription']['signed_in']:raise APIError('sign_in_required','Connect ChatGPT in Workspace & account.',403)
            if model=='grok-imagine-image-2.0' and not self.app.state['signed_in']:raise APIError('sign_in_required','Connect Grok in Workspace & account.',403)
        with self.p.mutation():
            drafts=[]
            for r,d,s in prepared:
                edited=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings=s));drafts.append(dict(view_id=r['id'],draft_id=d['id'],revision=edited['revision']))
            for request in drafts:request['revision']=self.app.images.draft(request['draft_id'])['revision']
            batch=self.p.new('world-render',production_id=pid,world_job_id=j['id'],mock=self.app.mock,status='pending',key=key,fingerprint=fingerprint,view_ids=[r['id'] for r,_,_ in prepared],requests=drafts,image_job_ids=[],completed=0,error=None,cancel_requested=False)
        self.app.spawn(self.worker,batch)
        return batch

    def prompt_draft(self,identity,data):
        r=self.p.get(identity,'world-asset');self.p.check(r,data)
        self.job(r['production_id'],r['world_job_id']);e=self.entity(r['entity_id'])
        if r['kind'] in ('sheet','coverage') and not e.get('identity_asset_id'):
            raise APIError('identity_required','Confirm the main reference before preparing variations.',409)
        d=self.app.images.draft(r['draft_id']);model=self.model(data.get('model',d['settings']['model']))
        brief=data.get('brief')
        if self.app.prompting.current('image',d) and (brief is None or brief in (d['settings']['prompt'],d.get('prompt_preparation',{}).get('brief'))):
            if d['settings']['model']!=model:
                with self.p.mutation():
                    d=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings=self.render_settings(d['settings'],model)))
            return dict(draft=copy.deepcopy(d),current=True)
        settings=self.prepare_settings(e,r,d,fresh=True,model=model,prompt=brief,
            refresh_prompt=True,character_sheet=r['kind'] in ('portrait','sheet'))
        if model==d['settings']['model']:
            for field in ('quality','resolution','n'):settings[field]=d['settings'][field]
        with self.p.mutation():
            edited=self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings=settings))
        return dict(draft=edited,current=False)

    def worker(self,batch):
        try:
            for i,request in enumerate(batch['requests']):
                with self.app.agent.lock:
                    fresh=self.p.get(batch['id'],'world-render')
                    if fresh.get('cancel_requested'):break
                    # Queued drafts are snapshots: edits while waiting stop the batch.
                    image=self.app.images.dispatch('POST',['drafts',request['draft_id'],'generate'],dict(expected_revision=request['revision'],approved=True),batch['id']+'-'+str(i))[1]
                    batch.update(image_job_ids=batch['image_job_ids']+[image['id']],revision=batch['revision']+1)
                    with self.p.sql:self.save_batch(batch)
                from openai_images import generation_timeout
                deadline=time.monotonic()+generation_timeout(image['model'],self.app.agent.config)+60
                while True:
                    with self.app.images.lock:job=copy.deepcopy(self.app.images.job(image['id']))
                    if job['status']!='pending' and self.app.state['phase'] not in ('generating','pending'):break
                    if time.monotonic()>deadline:raise APIError('timeout','The image is still pending. Remaining requests were not sent. Check its status before trying again.')
                    time.sleep(.2)
                if job['status']!='done':raise APIError('generation_failed',job.get('message','Image generation failed.'))
                with self.app.agent.lock,self.p.sql:
                    batch.update(completed=batch['completed']+1,revision=batch['revision']+1);self.save_batch(batch)
            with self.app.agent.lock,self.p.sql:
                cancelled=self.p.get(batch['id'],'world-render').get('cancel_requested',False)
                batch.update(status='cancelled' if cancelled else 'done',cancel_requested=cancelled,revision=batch['revision']+1);self.p.put('world-render',batch)
        except Exception as error:
            import openai_images
            with self.app.agent.lock,self.p.sql:
                batch.update(status='error',error=openai_images.safe_error(error) if isinstance(error,ValueError) else 'Generation stopped. Completed images are saved.',revision=batch['revision']+1);self.p.put('world-render',batch)

    def save_batch(self,batch):
        current=self.p.get(batch['id'],'world-render')
        batch['cancel_requested']=current.get('cancel_requested',False)
        batch['revision']=max(batch['revision'],current['revision']+1)
        return self.p.put('world-render',batch)

    def confirm(self,identity,data):
        r=self.p.get(identity,'world-asset');e=self.entity(r['entity_id']);self.p.check(r,data)
        if data.get('approved') is not True:raise APIError('review_required','Confirm the image after reviewing it.',403)
        asset_id=data.get('asset_id');candidate=next((o for o in self.view(r)['outputs'] if o['id']==asset_id),None)
        if not candidate:raise APIError('invalid_candidate','Choose an image from this view.')
        from candidate_review import available
        available(candidate)
        available(self.app.asset(asset_id)[0])
        if candidate.get('compatible') is False:raise APIError('identity_changed','Generate this view again with the current confirmed reference.',409)
        if r.get('selected_asset_id')==asset_id:return self.snapshot(e['production_id'],e['world_job_id'])
        is_main=r['kind'] in ('portrait','location','prop')
        replacing=is_main and e.get('identity_asset_id') and e['identity_asset_id']!=asset_id
        with self.f.asset_mutation():
            if candidate.get('job_id'):
                self.app.images.dispatch('POST',['jobs',candidate['job_id'],'approve'],dict(asset_id=asset_id,approved=True),None)
            else:self.safe_asset(asset_id)
            if is_main or r['kind']=='sheet':
                # Reapproving the same finished image can recover its canonical
                # handle. A different image gets a new handle so prior saved uses
                # of the detached reference remain unchanged.
                if is_main and not e.get('reference_id') and e.get('cleared_reference_id'):
                    prior=self.app.asset_studio.get(e['cleared_reference_id'])
                    if not prior.get('archived') and prior['images'] and prior['images'][0].get('asset_id')==asset_id:e['reference_id']=prior['id']
                if e.get('reference_id'):
                    ref=self.app.asset_studio.get(e['reference_id'])
                    if not any(a.get('asset_id')==asset_id for a in ref['images']):ref=self.app.asset_studio.dispatch('POST',[ref['id'],'adopt'],dict(expected_revision=ref['revision'],asset_id=asset_id,replace_index=0 if is_main else None),None)[1]
                    if replacing:ref=self.app.asset_studio.dispatch('PUT',[ref['id']],dict(expected_revision=ref['revision'],images=[{'asset_id':asset_id}]),None)[1]
                else:
                    stem=re.sub('[^A-Za-z0-9_]','',e['name'])[:32] or 'WorldAsset'
                    if not stem[0].isalpha():stem='Asset'+stem
                    handle=stem;n=2;used={a['handle'].casefold() for a in self.app.named_library()}
                    while handle.casefold() in used:handle=stem+str(n);n+=1
                    ref=self.app.save_reference(dict(title=e['name'],handle=handle,category=e['category'],description=library_description(e,self.app.agent.config['reference_description_limit']),voice=e.get('profile',{}).get('voice_preset') or None,images=[{'asset_id':asset_id}]))
                e['reference_id']=ref['id'];r['reference_id']=ref['id']
            if is_main:
                e['identity_asset_id']=asset_id
                e.pop('cleared_reference_id',None);e.pop('cleared_identity_asset_id',None)
            e.update(revision=e['revision']+1);self.p.put('world-entity',e)
            r.update(selected_asset_id=asset_id,revision=r['revision']+1);self.p.put('world-asset',r)
            if is_main:
                for other in self.p.all('world-asset'):
                    if other.get('entity_id')==e['id'] and other['kind'] in ('sheet','coverage'):
                        if replacing:
                            other.update(selected_asset_id=None,reference_id=None,revision=other['revision']+1);self.p.put('world-asset',other)
                        d=self.app.images.draft(other['draft_id']);s=copy.deepcopy(d['settings']);s['extras']=[{'asset_id':asset_id}];s['bindings']=[]
                        self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings=s))
            self.connect_shots(self.job(e['production_id'],e['world_job_id']))
        return self.snapshot(e['production_id'],e['world_job_id'])

    def return_image(self,identity,data):
        r=self.p.get(identity,'world-asset');self.entity(r['entity_id'])
        job=self.app.images.job(data.get('job_id'))
        candidate=next((o for o in self.view(r)['outputs'] if o['id']==data.get('asset_id') and o.get('job_id')==job['id']),None)
        if job['status']!='done' or not candidate:raise APIError('invalid_candidate','This image is not an edit of the view you opened. Return to its own workspace or choose the original draft.',409)
        from candidate_review import available
        available(candidate);asset,_=self.app.asset(candidate['id']);available(asset)
        if r.get('selected_asset_id')==asset['id']:return self.snapshot(r['production_id'],r['world_job_id'])
        self.p.check(r,data)
        # Return is an explicit adoption of an already reviewed image. Merely
        # generating/editing or opening the gallery never changes its selection.
        if asset.get('approved') and candidate.get('approved'):
            return self.confirm(identity,{**data,'asset_id':asset['id'],'approved':True})
        return self.snapshot(r['production_id'],r['world_job_id'])

    def upload_identity(self,identity,data):
        e=self.entity(identity);self.p.check(e,data)
        asset_id=data.get('asset_id');self.safe_asset(asset_id)
        kind='portrait' if e['category']=='Character' else 'prop' if e['category']=='Prop' else 'location'
        r=next(v for v in self.p.all('world-asset') if v.get('entity_id')==identity and v['kind']==kind)
        if e.get('identity_asset_id'):raise APIError('identity_locked','This asset already has a confirmed identity.',409)
        with self.f.asset_mutation():
            # A local upload is user supplied, not a generated candidate awaiting review.
            stem=re.sub('[^A-Za-z0-9_]','',e['name'])[:32] or 'WorldAsset'
            if not stem[0].isalpha():stem='Asset'+stem
            handle=stem;n=2;used={a['handle'].casefold() for a in self.app.named_library()}
            while handle.casefold() in used:handle=stem+str(n);n+=1
            ref=self.app.save_reference(dict(title=e['name'],handle=handle,category=e['category'],description=library_description(e,self.app.agent.config['reference_description_limit']),voice=e.get('profile',{}).get('voice_preset') or None,images=[{'asset_id':asset_id}]))
            e.update(identity_asset_id=asset_id,reference_id=ref['id'],revision=e['revision']+1)
            e.pop('cleared_reference_id',None);e.pop('cleared_identity_asset_id',None);self.p.put('world-entity',e)
            uploaded=list(r.get('uploaded_candidate_ids',[]))
            if asset_id not in uploaded:uploaded.append(asset_id)
            r.update(selected_asset_id=asset_id,reference_id=ref['id'],uploaded_candidate_ids=uploaded,revision=r['revision']+1);self.p.put('world-asset',r)
            self.connect_shots(self.job(e['production_id'],e['world_job_id']))
        return self.snapshot(e['production_id'],e['world_job_id'])

    def edit_view(self,identity,data):
        with self.app.agent.lock,self.app.images.lock:
            view=self.p.get(identity,'world-asset');self.p.check(view,data)
            if view['kind'] not in ('sheet','coverage'):
                raise APIError('invalid_view','Only optional view titles can be renamed.')
            title=text(data.get('title'),80,'View title',True)
            with self.p.mutation():
                view.update(view=title,revision=view['revision']+1)
                self.p.put('world-asset',view)
            entity=self.entity(view['entity_id'])
            return self.snapshot(entity['production_id'],entity['world_job_id'])

    def clear_view_approval(self,identity,data):
        with self.app.agent.lock,self.app.images.lock:
            view=self.p.get(identity,'world-asset');self.p.check(view,data)
            if view['kind'] not in ('sheet','coverage'):
                raise APIError('invalid_view','Clear the main approval from the entity controls.')
            if self.view(view)['pending']:
                raise APIError('busy','Wait for this view to finish generating.',409)
            with self.p.mutation():
                view.update(selected_asset_id=None,reference_id=None,revision=view['revision']+1)
                self.p.put('world-asset',view)
            entity=self.entity(view['entity_id'])
            return self.snapshot(entity['production_id'],entity['world_job_id'])

    def clear_approval(self,identity,data):
        """Detach current approval without removing images or altering saved uses."""
        with self.app.agent.lock,self.app.images.lock:
            e=self.entity(identity);self.p.check(e,data)
            views=[v for v in self.p.all('world-asset') if v.get('entity_id')==identity]
            draft_ids={v['draft_id'] for v in views}
            if (any(b['status']=='pending' for b in self.p.all('world-render'))
                    or any(j['status']=='pending' and j['draft']['id'] in draft_ids for j in self.app.images.db['jobs'])
                    or self.app.state['phase'] in ('connecting','waiting','generating','pending')):
                raise APIError('busy','Wait for the current generation to finish before clearing approval.',409)
            if not e.get('identity_asset_id'):return self.snapshot(e['production_id'],e['world_job_id'])
            with self.p.mutation():
                e.update(cleared_identity_asset_id=e['identity_asset_id'],cleared_reference_id=e.get('reference_id'),
                         identity_asset_id=None,reference_id=None,revision=e['revision']+1)
                self.p.put('world-entity',e)
                for view in views:
                    uploaded=list(view.get('uploaded_candidate_ids',[]));selected=view.get('selected_asset_id')
                    if not selected and view['kind'] in ('portrait','location','prop'):selected=e['cleared_identity_asset_id']
                    generated=any(any(o['id']==selected for o in j.get('outputs',[])) for j in self.image_jobs(view)[0])
                    if selected and not generated and selected not in uploaded:uploaded.append(selected)
                    view.update(selected_asset_id=None,reference_id=None,existing_reference_id=None,
                                uploaded_candidate_ids=uploaded,revision=view['revision']+1)
                    self.p.put('world-asset',view)
                from candidate_review import clear_asset_approval
                clear_asset_approval(self.app,e['cleared_identity_asset_id'])
            return self.snapshot(e['production_id'],e['world_job_id'])

    def connect_shots(self,j):
        # New builders explicitly attach the episode's frozen asset snapshots.
        # Approving a new Bible identity must never rewrite prior productions.
        if j.get('scope'):return
        if not j.get('applied'):return
        entities=[e for e in self.p.all('world-entity') if e['world_job_id']==j['id'] and e.get('reference_id')]
        planned=[(scene,shot) for scene in j.get('applied_plan',j['result'])['scenes'] for shot in scene['shots']]
        for sid,(scene,proposed) in zip(j['shot_ids'],planned):
            selected=[]
            names=proposed.get('characters',[])+[proposed.get('location','')]
            haystack=(scene['text']+' '+proposed['image_prompt']+' '+proposed['video_prompt']).casefold()
            for e in entities:
                if e['name'] in names or (not any(names) and re.search(r'(?<!\w)'+re.escape(e['name'].lstrip('@').casefold())+r'(?!\w)',haystack)):
                    selected.append(self.app.asset_studio.get(e['reference_id']))
            if not selected:continue
            shot=self.p.get(sid,'shot');d=self.app.images.draft(shot['image_id']);s=copy.deepcopy(d['settings'])
            count=len(s['extras'])+bool(s['base'])+sum(len(b['selected']) for b in s['bindings'])
            for ref in selected:
                binding=next((b for b in s['bindings'] if b['snapshot']['id']==ref['id']),None)
                if not binding:
                    if count>=5:continue
                    s=self.app.images.attach(s,[ref['handle']]);count+=1
                elif binding['snapshot']['images'][0]!=ref['images'][0]:
                    count+=1-len(binding['selected'])
                    binding.update(snapshot=copy.deepcopy(ref),selected=[0])
            if s!=d['settings']:self.app.images.edit(d['id'],dict(expected_revision=d['revision'],settings=s))
            video=self.app.agent.record(shot['video_id']);state=copy.deepcopy(video['scene'])
            for ref in selected:
                existing=next((n for n in state['named'] if n['id']==ref['id']),None)
                if existing:
                    if existing['images'][0]!=ref['images'][0]:
                        first=next((r for r in state['refs'] if r['id']==existing['refIds'][0]),None)
                        if first:
                            state['refs']=[r for r in state['refs'] if r['id'] not in existing['refIds'][1:]]
                            first['source']=self.app.agent.source(ref['images'][0])
                            existing.update(copy.deepcopy(ref),refIds=[first['id']])
                    continue
                if len(state['refs'])+len(ref['images'])<=7:state=self.app.agent.attach(state,[ref['handle']])
            if state!=video['scene']:self.app.agent.patch(video['id'],dict(expected_revision=video['revision'],changes=state))

    def bible(self,pid):
        from world_bible import render_bible
        j=self.job(pid);snapshot=self.snapshot(pid,j['id']);return render_bible(self.app,self.f.production(pid),j,snapshot,self.f.world(pid)), 'application/pdf'

    def dispatch(self,method,parts,data,key):
        if len(parts)==3 and parts[0]=='entities' and parts[2]=='workshop' and method=='GET':
            entity=self.entity(parts[1]);return 200,self.snapshot(entity['production_id'],entity['world_job_id'])
        if len(parts)==3 and parts[0]=='worlds':
            pid=parts[1]
            if parts[2]=='workshop':
                if method=='GET':return 200,self.snapshot(pid)
                if method=='POST':return 200,self.start(pid,data)
            if parts[2]=='reference' and method=='POST':return 201,self.reference(pid,data)
            if parts[2]=='generate' and method=='POST':return 202,self.generate(pid,data,key)
            if parts[2]=='bible.pdf' and method=='GET':return 200,self.bible(pid)
        if len(parts)==2 and parts[0]=='entities' and method=='PUT':return 200,self.edit(parts[1],data)
        if len(parts)==3 and parts[0]=='entities' and method=='POST':
            if parts[2]=='views':return 201,self.add_views(parts[1],data)
            if parts[2]=='upload':return 200,self.upload_identity(parts[1],data)
            if parts[2]=='clear-approval':return 200,self.clear_approval(parts[1],data)
        if len(parts)==2 and parts[0]=='assets' and method=='PUT':return 200,self.edit_view(parts[1],data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='prompt-draft' and method=='POST':return 200,self.prompt_draft(parts[1],data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='clear-approval' and method=='POST':return 200,self.clear_view_approval(parts[1],data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='confirm' and method=='POST':return 200,self.confirm(parts[1],data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='return-image' and method=='POST':return 200,self.return_image(parts[1],data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='attempts' and method=='POST':return 200,self.review_attempt(parts[1],data)
        if len(parts)==3 and parts[0]=='assets' and parts[2]=='review' and method=='POST':
            from candidate_review import review
            return 200,review(self,parts[1],data)
        if len(parts)==3 and parts[0]=='renders' and parts[2]=='cancel' and method=='POST':
            b=self.p.get(parts[1],'world-render');self.job(b['production_id'],b['world_job_id'])
            with self.p.sql:b.update(cancel_requested=True,revision=b['revision']+1);self.p.put('world-render',b)
            return 200,b
        return None
