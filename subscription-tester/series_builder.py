"""Independent series foundations and episode books; legacy worlds remain untouched.

All production handoffs are explicit, revision checked and snapshot based. This
module uses the existing writing and visual transports, never a second provider.
"""
import copy
import hashlib
import json
import re
import uuid
from agent_api import APIError
from story_studio import text, split_script
from world_workshop import CAST, PLACE
from video_rules import VOICES
import prompt_guides

ANSWERS = {'title':120,'idea':6000,'genre':120,'tone':240,'theme':1000,'audience':240,'duration':120,'characters':6000,'locations':4000,'plot':6000,'style':2000,'rules':4000,'aspect_ratio':20}
PROP = {'name':80,'description':10000,'purpose':10000,'details':10000}


class SeriesBuilder:
    def __init__(self, film):
        self.f=film; self.app=film.app; self.p=film.p; self.w=film.workshop
        from script_production import ScriptProduction
        self.completion=ScriptProduction(self)
        from script_upload_review import ScriptUploadReview
        self.upload_review=ScriptUploadReview(self)

    def production(self, pid):
        production=self.f.production(pid)
        if production['kind']!='story':raise APIError('invalid_series','Choose a Story / Series project.')
        return production

    def episode(self, eid):
        episode=self.app.stories.record('episodes',eid)
        production=next((p for p in self.p.all('production') if p.get('series_id')==episode['series_id']),None)
        if not production:raise APIError('not_found','The episode has no series project.',404)
        return self.production(production['id']),copy.deepcopy(episode)

    def answers(self, value, episode=False):
        if not isinstance(value,dict) or set(value)-set(ANSWERS):raise APIError('invalid_book','Check the storybook fields.')
        if value.get('aspect_ratio') and value['aspect_ratio'] not in ('16:9','9:16','1:1','3:2','2:3'):raise APIError('invalid_ratio','Choose 16:9, 9:16, 1:1, 3:2 or 2:3.')
        return {k:text(value.get(k,''),6000 if episode and k=='theme' else limit,k.title()) for k,limit in ANSWERS.items()}

    def guide(self, value, *, candidate_asset_id=None):
        if not isinstance(value,dict) or set(value)-{'cast','places','props','acts','script'}:raise APIError('invalid_guide','Check the book cards.')
        script=value.get('script','');text(script,60000,'Script')
        out={'script':script}
        for key,limits,maximum in [('cast',{**CAST,'description':10000,'voice':10000,'voice_preset':80},12),('places',PLACE,12),('props',PROP,16),('acts',{'title':120,'text':6000},12)]:
            cards=value.get(key,[])
            if not isinstance(cards,list) or len(cards)>maximum:raise APIError('guide_limit',f'Use at most {maximum} {key} cards.')
            out[key]=[];seen=set()
            for card in cards:
                if not isinstance(card,dict) or set(card)-set(limits)-{'id','reference_ids','palette','series_asset_id'}:raise APIError('invalid_guide','Check the '+key+' fields.')
                identity=text(card.get('id',''),80,'Card id',True)
                if identity in seen:raise APIError('invalid_guide','Use unique card identifiers.')
                seen.add(identity);item={k:text(card.get(k,''),limit,k.title()) for k,limit in limits.items()};item['id']=identity
                if key=='cast' and item['voice_preset'] and item['voice_preset'] not in VOICES:raise APIError('invalid_voice','Choose a documented voice preset.')
                refs=card.get('reference_ids',[])
                if not isinstance(refs,list) or len(refs)>5:raise APIError('guide_limit','Use up to five inspiration images per card.')
                for ref in refs:self.w.safe_asset(ref,allow_candidate=candidate_asset_id)
                item['reference_ids']=list(refs)
                palette=card.get('palette',[])
                if not isinstance(palette,list) or len(palette)>6 or any(not isinstance(c,str) or not re.fullmatch('#[0-9a-fA-F]{6}',c) for c in palette):raise APIError('invalid_palette','Use up to six hex colors.')
                item['palette']=list(palette)
                if card.get('series_asset_id'):item['series_asset_id']=text(card['series_asset_id'],80,'Series asset')
                out[key].append(item)
        return out

    def bible(self, pid):
        production=self.production(pid)
        r=next((b for b in self.p.all('series-bible') if b['production_id']==pid),None)
        if not r:r=dict(id='bible-'+pid,revision=0,production_id=pid,answers=self.answers({'title':production['title']}),guide=self.guide({}))
        # The previous World Builder may represent either a series or an episode.
        # Expose its exact provenance so only a deliberate user action copies it.
        legacy=next((b for b in self.p.all('world') if b['production_id']==pid),None)
        return {**copy.deepcopy(r),'production':production,'legacy_world':copy.deepcopy(legacy)}

    def save_bible(self, pid, data):
        r=self.bible(pid);self.p.check(r,data)
        answers=self.answers(data.get('answers',r['answers']));guide=self.guide(data.get('guide',r['guide']))
        with self.f.asset_mutation():
            self.p.put('series-bible',dict(id=r['id'],revision=r['revision']+1,production_id=pid,answers=answers,guide=guide,**({'image_change_history':copy.deepcopy(r['image_change_history'])} if 'image_change_history' in r else {})))
            self.sync_cards('series-bible',r,guide)
        return self.bible(pid)

    def merge_card(self,entity,card,original=None):
        original=entity.get('source_card_snapshot',original or card)
        prior_name=entity['name'];prior_profile=copy.deepcopy(entity['profile'])
        if entity.get('source_card_snapshot')!=card:
            profile=copy.deepcopy(prior_profile)
            # Preserve fields explicitly refined in development. Source edits
            # replace copied values, never independently edited ones.
            for field,value in card.items():
                if value!=original.get(field) and profile.get(field)==original.get(field):
                    profile[field]=copy.deepcopy(value)
            description=entity['description']
            if description in (self.w.description(prior_profile),prior_name):
                description=self.w.description(profile) or card['name']
            name=card['name'] if prior_name==original.get('name') else prior_name
            entity.update(name=name,profile=profile,description=description,
                source_card_snapshot=copy.deepcopy(card),revision=entity['revision']+1)
            self.p.put('world-entity',entity)
            if entity.get('reference_id'):
                ref=self.app.asset_studio.get(entity['reference_id']);changes={}
                if entity['name']!=prior_name and ref['title']==prior_name:changes['title']=entity['name']
                if profile.get('voice_preset')!=prior_profile.get('voice_preset'):changes['voice']=profile.get('voice_preset') or None
                if changes:self.app.asset_studio.dispatch('PUT',[ref['id']],dict(expected_revision=ref['revision'],**changes),None)
        self.w.sync_view_metadata(entity)
        return entity

    def sync_cards(self,scope,book,guide):
        for key,category in [('cast','Character'),('places','Location'),('props','Prop')]:
            previous={c['id']:c for c in book['guide'].get(key,[])}
            for card in guide.get(key,[]):
                old=previous.get(card['id'])
                if not old or not card['name']:continue
                for entity in self.p.all('world-entity'):
                    if (entity.get('scope')!=scope or entity['production_id']!=book['production_id']
                            or entity.get('episode_id')!=book.get('episode_id')
                            or entity.get('source_card_id')!=card['id'] or entity['category']!=category):continue
                    self.merge_card(entity,card,old)

    def book(self, eid):
        production,episode=self.episode(eid)
        r=next((b for b in self.p.all('episode-book') if b['episode_id']==eid),None)
        if not r:r=dict(id='book-'+eid,revision=0,production_id=production['id'],episode_id=eid,answers=self.answers({'title':episode['title']},episode=True),guide=self.guide({}),selected_asset_ids=[],inheritance=None)
        result={**copy.deepcopy(r),'script_options':copy.deepcopy(r.get('script_options',{'allow_dialogue_polish':False})),'episode':episode,'script_drafts':[copy.deepcopy(d) for d in self.p.all('episode-script-draft') if d['episode_id']==eid]}
        # The episode's title is authoritative across the script and book tools.
        result['answers']['title']=episode['title']
        from storybook_links import links
        result['linked_entities']=links(self,result)
        return result

    def library(self, pid, eid=None):
        self.production(pid)
        if eid and self.episode(eid)[0]['id']!=pid:raise APIError('invalid_episode','Choose an episode in this series.')
        memberships={r['entity_id']:r for r in self.p.all('series-member') if r['production_id']==pid}
        items=[]
        for e in self.p.all('world-entity'):
            if e['production_id']!=pid:continue
            shared=e.get('scope')=='series-bible' or e['id'] in memberships or not e.get('scope')
            if not shared and not (eid and e.get('scope')=='episode-book' and e.get('episode_id')==eid):continue
            ref=self.app.asset_studio.get(e['reference_id']) if e.get('reference_id') else None
            if ref and ref.get('archived'):continue
            items.append({**copy.deepcopy(e),'scope':'series' if shared else 'episode','legacy':not bool(e.get('scope')),'reference':copy.deepcopy(ref),'handle':ref['handle'] if ref else None,'status':'needs replacement' if ref and ref.get('needs_replacement') else 'ready' if ref and e.get('identity_asset_id') else 'described'})
        # Older series selected canonical handles directly. Offer them for reuse
        # without manufacturing new world entities or changing their metadata.
        series=self.app.stories.record('series',self.production(pid)['series_id'])
        handles=series.get('assets',[])
        for ref in self.app.named_library():
            if ref.get('archived') or ref['handle'] not in handles or any(a.get('reference_id')==ref['id'] for a in items):continue
            items.append(dict(id='reference-'+ref['id'],revision=ref.get('revision',1),production_id=pid,name=ref['title'],category=ref['category'],description=ref['description'],profile={},scope='series',legacy=True,reference_id=ref['id'],identity_asset_id=next((i.get('asset_id') for i in ref['images'] if i.get('asset_id')),None),reference=copy.deepcopy(ref),handle=ref['handle'],status='needs replacement' if ref.get('needs_replacement') else 'ready' if ref['images'] else 'described'))
        return items

    def inheritance(self, pid, eid, ids):
        available={a['id']:a for a in self.library(pid,eid)}
        if not isinstance(ids,list) or len(ids)>40 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids) or any(i not in available for i in ids):raise APIError('invalid_series_asset','Select assets from this series or episode.')
        bible=self.bible(pid)
        return dict(bible_revision=bible['revision'],bible={k:copy.deepcopy(bible[k]) for k in ('id','revision','answers','guide')},answers=copy.deepcopy(bible['answers']),guide=copy.deepcopy(bible['guide']),assets=[copy.deepcopy(available[i]) for i in ids])

    def save_book(self, eid, data):
        r=self.book(eid);self.p.check(r,data)
        answers=self.answers(data.get('answers',r['answers']),episode=True);guide=self.guide(data.get('guide',r['guide']))
        options=data.get('script_options',r.get('script_options',{'allow_dialogue_polish':False}))
        if not isinstance(options,dict) or set(options)!={'allow_dialogue_polish'} or type(options['allow_dialogue_polish']) is not bool:raise APIError('invalid_options','Choose whether dialogue polishing is allowed.')
        ids=data.get('selected_asset_ids',r['selected_asset_ids'])
        inherited=r.get('inheritance')
        if inherited is None or data.get('refresh_inheritance') is True:inherited=self.inheritance(r['production_id'],eid,ids)
        elif ids!=r['selected_asset_ids']:
            if not isinstance(ids,list) or len(ids)>40 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise APIError('invalid_series_asset','Choose unique saved series assets.')
            old={a['id']:a for a in inherited['assets']}
            selection=self.inheritance(r['production_id'],eid,[i for i in ids if i not in old]);fresh={a['id']:a for a in selection['assets']}
            inherited=copy.deepcopy(inherited);inherited['assets']=[copy.deepcopy(old[i] if i in old else fresh[i]) for i in ids]
        # Guide-card links use the same frozen snapshots as selected library ids.
        # Capture only newly linked ids; existing snapshots never refresh on save.
        linked=list(dict.fromkeys(ids+[c['series_asset_id'] for group in ('cast','places','props') for c in guide.get(group,[]) if c.get('series_asset_id')]))
        held={a['id']:a for a in inherited['assets']}
        if data.get('refresh_inheritance') is not True:
            for asset in (r.get('inheritance') or {}).get('assets',[]):
                if asset['id'] in linked:held.setdefault(asset['id'],copy.deepcopy(asset))
        new_links=[identity for identity in linked if identity not in held]
        if new_links:
            captured=self.inheritance(r['production_id'],eid,new_links)
            held.update({a['id']:a for a in captured['assets']})
        inherited=copy.deepcopy(inherited);inherited['assets']=[held[identity] for identity in linked]
        episode=r['episode']
        with self.f.asset_mutation():
            if answers['title'] and answers['title']!=episode['title']:
                episode=self.app.stories.episode_edit(self.app.stories.record('episodes',eid),dict(expected_revision=data.get('expected_episode_revision'),title=answers['title']))
            self.p.put('episode-book',dict(id=r['id'],revision=r['revision']+1,production_id=r['production_id'],episode_id=eid,answers=answers,guide=guide,script_options=copy.deepcopy(options),selected_asset_ids=list(ids),inheritance=inherited,**({'image_change_history':copy.deepcopy(r['image_change_history'])} if 'image_change_history' in r else {})))
            self.sync_cards('episode-book',r,guide)
        return self.book(eid)

    def scoped_job(self, scope, identity):
        if scope=='series-bible':pid=identity;self.production(pid)
        else:pid=self.episode(identity)[0]['id']
        jobs=[j for j in self.p.all('world-job') if j.get('scope')==scope and j['production_id']==pid and (scope=='series-bible' or j.get('episode_id')==identity) and j['mock']==self.app.mock and j.get('purpose')=='visual-workshop']
        return jobs[-1] if jobs else None

    def visual_style(self, scope, book):
        own=book['answers']['style']
        if own or scope=='series-bible':return own
        foundation=book.get('inheritance')
        if foundation is None:foundation=self.inheritance(book['production_id'],book['episode_id'],book['selected_asset_ids'])
        return foundation['answers'].get('style','')

    def workshop(self, scope, identity, data=None):
        if scope not in ('series-bible','episode-book'):raise APIError('invalid_scope','Choose a series or episode book.')
        book=self.bible(identity) if scope=='series-bible' else self.book(identity)
        j=self.scoped_job(scope,identity)
        if data is None:
            return self.w.snapshot(book['production_id'],j['id']) if j else dict(job=None,entities=[],views=[],batches=[])
        self.p.check(book,data);model=self.w.model(data.get('model','gpt-image-2'))
        style=self.visual_style(scope,book)
        cards=[(category,card) for key,category in [('cast','Character'),('places','Location'),('props','Prop')] for card in book['guide'].get(key,[]) if card.get('name')]
        with self.f.asset_mutation():
            if j is None:
                j=self.p.new('world-job',scope=scope,purpose='visual-workshop',production_id=book['production_id'],episode_id=identity if scope=='episode-book' else None,world_revision=book['revision'],provider='manual',mock=self.app.mock,status='done',context={},workshop_started=True,result=dict(reply='Visual development from your book.',logline=book['answers']['idea'] or book['answers']['title'],synopsis=book['answers']['idea'],visual_style=style,assets=[],scenes=[]))
            # Updating a Bible never rewrites an episode or an existing identity.
            for category,card in cards:
                e=next((e for e in self.p.all('world-entity') if e.get('world_job_id')==j['id'] and e.get('source_card_id')==card['id'] and e['category']==category),None)
                if e is None:
                    e=self.p.new('world-entity',scope=scope,episode_id=identity if scope=='episode-book' else None,production_id=book['production_id'],world_job_id=j['id'],source_card_id=card['id'],source_card_snapshot=copy.deepcopy(card),name=card['name'],category=category,description=self.w.description(card) or card['name'],profile=copy.deepcopy(card),identity_asset_id=None,reference_id=None,suggested_views=[])
                    self.w.new_view(e,'portrait' if category=='Character' else 'prop' if category=='Prop' else 'location','Identity portrait' if category=='Character' else 'Main reference',model)
                else:self.merge_card(e,card)
            j['result']['visual_style']=style;j.update(world_revision=book['revision'],revision=j['revision']+1);self.p.put('world-job',j)
        return self.w.snapshot(book['production_id'],j['id'])

    def link_reference(self, pid, data):
        self.production(pid);ref=self.app.asset_studio.get(data.get('reference_id'))
        if ref.get('archived'):raise APIError('archived','Restore this asset before adding it.')
        for image in ref['images']:
            if image.get('asset_id'):self.w.safe_asset(image['asset_id'])
        existing=next((e for e in self.library(pid) if e.get('reference_id')==ref['id']),None)
        if existing and not existing.get('legacy'):return existing
        bible=self.bible(pid)
        snapshot=self.workshop('series-bible',pid,dict(expected_revision=bible['revision']))
        with self.p.mutation():
            identity=next((i.get('asset_id') for i in ref['images'] if i.get('asset_id')),None)
            e=self.p.new('world-entity',scope='series-bible',episode_id=None,production_id=pid,world_job_id=snapshot['job']['id'],source_card_id=None,name=ref['title'],category=ref['category'],description=ref['description'],profile={'voice_preset':ref.get('voice') or '', 'reference_ids':[identity] if identity else []},identity_asset_id=identity,reference_id=ref['id'],suggested_views=[])
            view=self.w.new_view(e,'portrait' if e['category']=='Character' else 'prop' if e['category']=='Prop' else 'location','Main reference','gpt-image-2')
            view.update(selected_asset_id=identity,reference_id=ref['id'],revision=view['revision']+1);self.p.put('world-asset',view)
        return next(a for a in self.library(pid) if a['id']==e['id'])

    def promote(self, pid, data):
        self.production(pid);e=self.w.entity(data.get('entity_id'));self.p.check(e,data)
        if e['production_id']!=pid or e.get('scope')!='episode-book':raise APIError('invalid_series_asset','Choose an asset created in an episode of this series.')
        membership=next((r for r in self.p.all('series-member') if r['entity_id']==e['id'] and r['production_id']==pid),None)
        if not membership:
            with self.p.sql:self.p.new('series-member',production_id=pid,entity_id=e['id'],source_episode_id=e['episode_id'],entity_snapshot=copy.deepcopy(e))
        return next(a for a in self.library(pid) if a['id']==e['id'])

    def key(self, key, scope, data):
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):raise APIError('idempotency_required','Supply a unique Idempotency-Key.')
        fingerprint=hashlib.sha256(json.dumps([scope,data,self.app.mock],sort_keys=True).encode()).hexdigest()
        old=next((j for j in self.p.all('world-job') if j.get('key')==key),None)
        if old and old.get('fingerprint')!=fingerprint:raise APIError('idempotency_conflict','Use a new key for different inputs.',409)
        return old,fingerprint

    def planning_context(self, book):
        inherited=book.get('inheritance') or self.inheritance(book['production_id'],book['episode_id'],book['selected_asset_ids'])
        guide=copy.deepcopy(book['guide']);answers=copy.deepcopy(book['answers'])
        for key in ('genre','tone','theme','audience','style','rules'):
            if not answers[key]:answers[key]=inherited['answers'].get(key,'')
        for asset in inherited['assets']:
            target={'Character':'cast','Location':'places','Prop':'props'}[asset['category']]
            if not any(c['name'].casefold()==asset['name'].casefold() for c in guide[target]):guide[target].append({**copy.deepcopy(asset['profile']),'id':asset['id'],'name':asset['name']})
        production=self.production(book['production_id'])
        own=self.episode_assets(book)
        return dict(questionnaire=answers,guide=guide,series_bible=inherited,episode_assets=own,production={k:production[k] for k in ('title','brief','kind')},episode=book['episode'],existing_assets=[a['reference'] for a in inherited['assets']+own if a.get('reference')])

    def episode_assets(self, book):
        cards={c['id'] for key in ('cast','places','props') for c in book['guide'].get(key,[]) if c.get('name')}
        # Cards explicitly developed in this episode are active production
        # references. Freeze them in the writing/storyboard job at handoff time.
        return [copy.deepcopy(a) for a in self.library(book['production_id'],book['episode_id']) if a.get('episode_id')==book['episode_id'] and a.get('reference') and a.get('identity_asset_id') and (a.get('source_card_id') in cards or a.get('source_card_id') is None)]

    def attach_snapshots(self, shot, assets, text_context, names=None):
        names=names or []
        refs=self.references(assets,text_context,names)
        image=self.app.images.draft(shot['image_id']);settings=copy.deepcopy(image['settings'])
        count=len(settings['extras'])+bool(settings['base'])+sum(len(b['selected']) for b in settings['bindings'])
        for ref in refs:
            if not ref['images']:continue
            binding=next((b for b in settings['bindings'] if b['snapshot']['id']==ref['id']),None)
            if binding:
                count-=len(binding['selected'])
                binding.update(snapshot=copy.deepcopy(ref),selected=[0]);count+=1
            elif count<5:settings['bindings'].append(dict(snapshot=copy.deepcopy(ref),selected=[0]));count+=1
        if settings!=image['settings']:self.app.images.edit(image['id'],dict(expected_revision=image['revision'],settings=settings))
        video=self.app.agent.record(shot['video_id']);state=copy.deepcopy(video['scene'])
        for ref in refs:
            if not ref['images']:continue
            old=next((n for n in state['named'] if n['id']==ref['id']),None)
            if old:
                state['refs']=[r for r in state['refs'] if r['id'] not in old['refIds']]
                state['voices']=[v for v in state['voices'] if v['id']!=old.get('voiceId')]
                state['named'].remove(old)
            if len(state['refs'])>=7:continue
            refid=uuid.uuid4().hex;state['refs'].append(dict(id=refid,source=self.app.agent.source(ref['images'][0]),namedId=ref['id']))
            voiceid=None
            if ref.get('voice') and len(state['voices'])<3:
                voiceid=uuid.uuid4().hex;state['voices'].append(dict(id=voiceid,voice=ref['voice'],namedId=ref['id']))
            state['named'].append({**copy.deepcopy(ref),'images':copy.deepcopy(ref['images'][:1]),'refIds':[refid],'voiceId':voiceid})
        if state!=video['scene']:self.app.agent.patch(video['id'],dict(expected_revision=video['revision'],changes=state))
        return refs

    def references(self, assets, context, names=None):
        refs=[];seen=set()
        for asset in assets:
            ref=asset.get('reference')
            if not ref or ref['id'] in seen:continue
            if asset['name'] not in (names or []) and not re.search(r'(?<!\w)'+re.escape(asset['name'].casefold())+r'(?!\w)',context.casefold()):continue
            seen.add(ref['id']);refs.append(ref)
        return refs

    def refresh_assets(self, eid, data):
        book=self.book(eid);self.p.check(book,data)
        self.app.stories.check(book['episode'],{'expected_revision':data.get('expected_episode_revision')})
        if data.get('approved') is not True:raise APIError('approval_required','Review and authorize updating these storyboard references.',403)
        entries=data.get('shots')
        if not isinstance(entries,list) or not 1<=len(entries)<=100:raise APIError('invalid_shots','Select 1–100 shots from this episode.')
        shots=[];seen=set()
        for entry in entries:
            if not isinstance(entry,dict):raise APIError('invalid_shots','Choose valid episode shots.')
            shot=self.p.get(entry.get('id'),'shot');self.p.check(shot,entry)
            if shot['id'] in seen or shot['production_id']!=book['production_id'] or shot.get('episode_id')!=eid:raise APIError('invalid_shots','Choose unique shots from this episode.')
            seen.add(shot['id'])
            if (shot.get('selected_image') or shot.get('selected_video')) and data.get('allow_completed') is not True:raise APIError('completed_shot','This shot has a selected take. Explicitly authorize changing its draft references; saved takes remain intact.',409)
            shots.append(shot)
        inherited=copy.deepcopy(book.get('inheritance') or self.inheritance(book['production_id'],eid,book['selected_asset_ids']))
        assets=inherited['assets']+self.episode_assets(book)
        script={s['id']:s for s in book['episode']['scenes']}
        with self.p.mutation():
            for shot in shots:
                scene=script.get(shot.get('story_scene_id'),{})
                image=self.app.images.draft(shot['image_id']);video=self.app.agent.record(shot['video_id'])
                context=scene.get('text','')+' '+image['settings']['prompt']+' '+video['scene']['prompt']
                self.attach_snapshots(shot,assets,context)
                shot.update(series_context=copy.deepcopy(inherited),episode_assets=self.episode_assets(book),revision=shot['revision']+1);self.p.put('shot',shot)
        return dict(shots=[self.p.view_shot(s) for s in shots],book=self.book(eid))

    def writing_access(self, provider):
        if provider not in ('codex','grok'):raise APIError('invalid_provider','Choose ChatGPT or Grok.')
        if any(j['status']=='pending' for j in self.p.all('world-job')):raise APIError('busy','Wait for the current writing request.',409)
        if not self.app.mock:
            if not self.app.agent.config['live_generations_enabled']:raise APIError('live_locked','Live requests are locked.',403)
            if provider=='grok' and not self.app.state['signed_in']:raise APIError('sign_in_required','Connect Grok from Workspace & account.',403)
            if provider=='codex' and not self.app.images.account_status()['subscription']['signed_in']:raise APIError('sign_in_required','Connect ChatGPT from Workspace & account.',403)
    def plan(self, eid, data, key):
        book=self.book(eid);old,fingerprint=self.key(key,['episode-plan',eid],data)
        if old:return old
        self.p.check(book,data);self.app.stories.check(book['episode'],{'expected_revision':data.get('expected_episode_revision')})
        if data.get('approved') is not True:raise APIError('approval_required','Authorize this writing request first.',403)
        if not book['answers']['idea'] and not book['guide']['script']:raise APIError('missing_idea','Describe this episode or upload its script.')
        provider=data.get('provider','codex');self.writing_access(provider)
        context=self.planning_context(book)
        if not context['questionnaire']['idea']:context['questionnaire']['idea']=book['guide']['script'][:6000]
        if data.get('revision_of'):
            original=self.p.get(data['revision_of'],'world-job')
            if original.get('scope')!='episode-book' or original.get('episode_id')!=eid or original['mock']!=self.app.mock or original['status']!='done':raise APIError('invalid_revision','Choose a completed plan from this episode.')
            self.p.check(original,{'expected_revision':data.get('expected_job_revision')})
            base=copy.deepcopy(original.get('applied_plan') or original['result']);index=data.get('scene_index')
            if type(index) is not int or not 0<=index<len(base['scenes']):raise APIError('invalid_revision','Choose a scene to revise.')
            context['revision_request']=dict(instruction=text(data.get('instruction'),2000,'Revision request',True),scene_index=index,base_plan=base)
        if len(json.dumps(context))>300000:raise APIError('context_limit','This episode has too much context to plan at once.')
        context=prompt_guides.planning(context,data.get('image_model','gpt-image-2'),data.get('video_model','grok-imagine-video-1.5'), app=self.app)
        with self.p.sql:j=self.p.new('world-job',scope='episode-book',purpose='episode-plan',production_id=book['production_id'],episode_id=eid,book_revision=book['revision'],episode_revision=book['episode']['revision'],world_revision=book['revision'],provider=provider,mock=self.app.mock,status='pending',context=context,provenance=prompt_guides.provenance(context),result=None,key=key,fingerprint=fingerprint)
        self.app.spawn(self.f.worker,j)
        return j

    def merge_scenes(self, episode, scenes):
        # Preserve IDs for retained positions/titles; old script versions retain
        # removed scenes, and their generated media contexts remain snapshots.
        used=set();out=[]
        for index,scene in enumerate(scenes):
            candidates=[s for s in episode['scenes'] if s['title']==scene['title'] and s['id'] not in used]
            existing=candidates[0] if len(candidates)==1 else episode['scenes'][index] if index<len(episode['scenes']) and episode['scenes'][index]['id'] not in used else None
            item=dict(title=scene['title'],text=scene['text'])
            if existing:item['id']=existing['id'];used.add(existing['id'])
            out.append(item)
        return out

    def script(self, eid, data):
        book=self.book(eid);self.p.check(book,data);episode=book['episode']
        self.app.stories.check(episode,{'expected_revision':data.get('expected_episode_revision')})
        if any(j['status']=='pending' for j in self.jobs(eid)):raise APIError('busy','Wait for script writing to finish before saving a manual script.',409)
        if episode['scenes'] and data.get('replace_existing') is not True:raise APIError('script_exists','This episode already has a script. Review it and explicitly replace it; its previous version will be retained.',409)
        raw=text(data.get('script',book['guide']['script']),60000,'Script')
        scenes=split_script(raw) if raw else [dict(title=a['title'] or 'Scene '+str(i+1),text=a['text']) for i,a in enumerate(book['guide']['acts']) if a['text']]
        if not scenes:raise APIError('missing_script','Write or upload the episode script first.')
        with self.p.mutation():
            episode=self.app.stories.episode_edit(self.app.stories.record('episodes',eid),dict(expected_revision=episode['revision'],scenes=self.merge_scenes(episode,scenes)))
            for j in self.jobs(eid):
                if not j.get('script_inactive'):
                    j.update(script_inactive=True,revision=j['revision']+1);self.p.put('world-job',j)
        return dict(book=self.book(eid),episode=episode)

    def trash_script(self, eid, data):
        book=self.book(eid);self.p.check(book,data);episode=book['episode']
        self.app.stories.check(episode,{'expected_revision':data.get('expected_episode_revision')})
        if data.get('approved') is not True:raise APIError('approval_required','Confirm clearing the current script.',403)
        jobs=self.jobs(eid)
        if any(j['status']=='pending' for j in jobs):raise APIError('busy','Wait for script writing to finish before clearing it.',409)
        if data.get('expected_job_revisions')!={j['id']:j['revision'] for j in jobs}:raise APIError('revision_conflict','Script versions changed. Refresh before clearing the current script.',409)
        with self.p.mutation():
            if book['guide']['script']:
                self.p.new('episode-script-draft',episode_id=eid,script=book['guide']['script'],label='Draft saved before trash')
            if episode['scenes']:
                self.app.stories.episode_edit(self.app.stories.record('episodes',eid),dict(expected_revision=episode['revision'],scenes=[]))
            guide=copy.deepcopy(book['guide']);guide['script']=''
            self.p.put('episode-book',dict(id=book['id'],revision=book['revision']+1,production_id=book['production_id'],episode_id=eid,answers=copy.deepcopy(book['answers']),guide=guide,script_options=copy.deepcopy(book.get('script_options',{'allow_dialogue_polish':False})),selected_asset_ids=list(book['selected_asset_ids']),inheritance=copy.deepcopy(book['inheritance'])))
            for j in jobs:
                if not j.get('script_inactive'):
                    j.update(script_inactive=True,revision=j['revision']+1);self.p.put('world-job',j)
        return dict(book=self.book(eid),jobs=self.jobs(eid))

    def jobs(self, eid):
        self.episode(eid)
        return [j for j in self.p.all('world-job') if j.get('scope')=='episode-book' and j.get('episode_id')==eid and j['mock']==self.app.mock and j.get('purpose') not in ('visual-workshop','upload-duplicate-review')]

    def fork(self, j, data):
        self.p.check(j,data)
        if j['status']!='done':raise APIError('not_ready','Wait for a completed episode plan.')
        book=self.book(j['episode_id'])
        with self.p.sql:
            return self.p.new('world-job',scope='episode-book',purpose='production-details' if j.get('purpose')=='production-details' else 'episode-plan',production_id=j['production_id'],episode_id=j['episode_id'],book_revision=book['revision'],episode_revision=book['episode']['revision'],world_revision=book['revision'],provider=j['provider'],mock=self.app.mock,status='done',context=copy.deepcopy(j.get('context',{})),result=copy.deepcopy(j['result'] if j.get('purpose')=='production-details' else j.get('applied_plan') or j['result']),source_job_id=j['id'],**({**{k:copy.deepcopy(j[k]) for k in ('catalog','source_script','allow_dialogue_polish')},'source_kind':'draft','completion':{**copy.deepcopy(j['completion']),'reviewed':False}} if j.get('purpose')=='production-details' else {}))

    def apply(self, eid, data):
        book=self.book(eid);j=self.p.get(data.get('job_id'),'world-job')
        if j.get('scope')!='episode-book' or j.get('episode_id')!=eid or j['production_id']!=book['production_id'] or j['mock']!=self.app.mock:raise APIError('invalid_plan','Choose a plan from this episode.')
        if j.get('applied'):return j
        self.p.check(j,data)
        if j['status']!='done':raise APIError('not_ready','Wait for a completed episode plan.')
        if j.get('script_inactive'):raise APIError('inactive_script','Restore this script as a new draft before creating its storyboard.',409)
        if j.get('book_revision')!=book['revision']:raise APIError('revision_conflict','The episode book changed. Review a new plan before applying.',409)
        episode=book['episode'];self.app.stories.check(episode,{'expected_revision':data.get('expected_episode_revision')})
        if episode['revision']!=j.get('episode_revision'):raise APIError('revision_conflict','The script changed after planning. Create a new plan; your edits are preserved.',409)
        if episode['scenes'] and data.get('replace_existing') is not True:raise APIError('script_exists','Review and explicitly replace the existing script. Its previous version and media remain saved.',409)
        if j.get('purpose')=='production-details':
            self.completion.check_job(j,eid)
            current=book['guide']['script'] if j['source_kind']=='draft' else '\n\n'.join('SCENE '+str(i+1)+' — '+s['title']+'\n'+s['text'] for i,s in enumerate(episode['scenes']))
            if current!=j['source_script']:raise APIError('script_changed','The script changed after production planning. Complete its details again; your edits are preserved.',409)
            if 'result' in data:self.completion.validate_edit(j,data['result'])
            plan,_=self.completion.final_plan(j)
        else:plan=self.f.validate_plan(data.get('result',j['result']))
        model=self.w.model(data.get('image_model','gpt-image-2'))
        return self.handoff(book,j,plan,model,replace_script=True)

    def handoff(self, book, j, plan, model, replace_script):
        from image_studio import DEFAULTS
        production=self.production(book['production_id']);episode=book['episode']
        inherited=copy.deepcopy(j.get('context',{}).get('series_bible') or book.get('inheritance') or self.inheritance(production['id'],episode['id'],book['selected_asset_ids']))
        own=copy.deepcopy(j.get('context',{}).get('episode_assets',self.episode_assets(book)))
        completed=j.get('purpose')=='production-details'
        if completed:
            _,matched=self.completion.final_plan(j)
            inherited['assets']=[a for a in inherited['assets'] if a['id'] not in {m['id'] for m in matched}]+matched
        with self.p.mutation():
            if replace_script:
                changes=dict(expected_revision=episode['revision'],scenes=self.merge_scenes(episode,plan['scenes']))
                if not completed:changes.update(title=book['answers']['title'] or episode['title'],notes=plan['synopsis'][:10000])
                episode=self.app.stories.episode_edit(self.app.stories.record('episodes',episode['id']),changes)
                if completed and j['completion']['accepted_dialogue']:
                    self.p.new('episode-script-draft',episode_id=episode['id'],script=j['source_script'],label='Original script before dialogue polish')
                    raw=self.completion.edited_script(j);guide=copy.deepcopy(book['guide']);guide['script']=raw
                    saved={k:copy.deepcopy(book[k]) for k in ('id','revision','production_id','episode_id','answers','guide','selected_asset_ids','inheritance','script_options')};saved.update(guide=guide,revision=saved['revision']+1);self.p.put('episode-book',saved)
                    book=self.book(episode['id'])
            shots=[]
            for index,scene in enumerate(plan['scenes']):
                for proposed in scene['shots']:
                    shot=self.p.create_shot(production,dict(title=proposed['title'],episode_id=episode['id'],story_scene_id=episode['scenes'][index]['id']))
                    names=proposed.get('characters',[])+[proposed.get('location','')]
                    context=(scene['text']+' '+proposed['image_prompt']).casefold()
                    refs=[a['reference'] for a in inherited['assets']+own if a['id'] in proposed.get('asset_ids',[]) and a.get('reference')] if completed else self.references(inherited['assets']+own,context,names)
                    if completed:refs=list({r['id']:r for r in refs}.values())
                    settings={**copy.deepcopy(DEFAULTS),'model':model,'prompt':proposed['image_prompt'],'quality':'auto' if model=='gpt-image-2' else 'low','resolution':'auto' if model=='gpt-image-2' else '1k'}
                    count=0
                    for ref in refs:
                        if not ref['images'] or count>=5:continue
                        settings['bindings'].append(dict(snapshot=copy.deepcopy(ref),selected=[0]));count+=1
                    image=self.app.images.draft(shot['image_id']);self.app.images.edit(image['id'],dict(expected_revision=image['revision'],settings=settings))
                    video=self.app.agent.record(shot['video_id']);state=copy.deepcopy(video['scene']);state['prompt']=proposed['video_prompt']
                    for ref in refs:
                        if not ref['images'] or len(state['refs'])>=7:continue
                        refid=uuid.uuid4().hex;state['refs'].append(dict(id=refid,source=self.app.agent.source(ref['images'][0]),namedId=ref['id']))
                        voiceid=None
                        if ref.get('voice') and len(state['voices'])<3:
                            voiceid=uuid.uuid4().hex;state['voices'].append(dict(id=voiceid,voice=ref['voice'],namedId=ref['id']))
                        state['named'].append({**copy.deepcopy(ref),'images':copy.deepcopy(ref['images'][:1]),'refIds':[refid],'voiceId':voiceid})
                    self.app.agent.patch(video['id'],dict(expected_revision=video['revision'],changes=state))
                    if completed:shot['contained_assets']=copy.deepcopy(proposed.get('contained_assets',[]))
                    shot.update(series_context=copy.deepcopy(inherited),episode_assets=copy.deepcopy(own),storyboard_image_prompt=proposed['image_prompt'],storyboard_video_prompt=proposed['video_prompt'],storyboard_visual_style=plan['visual_style'],revision=shot['revision']+1);self.p.put('shot',shot);shots.append(shot['id'])
            # New episode identities stay local until explicit promotion.
            workshop=self.workshop('episode-book',episode['id'],dict(expected_revision=book['revision'],model=model))
            for asset in plan['assets']:
                if any(a['name'].casefold()==asset['name'].casefold() and a['category']==asset['category'] for a in inherited['assets']):continue
                existing=next((e for e in self.p.all('world-entity') if e.get('world_job_id')==workshop['job']['id'] and e['name'].casefold()==asset['name'].casefold() and e['category']==asset['category']),None)
                if not existing:
                    e=self.p.new('world-entity',scope='episode-book',episode_id=episode['id'],production_id=production['id'],world_job_id=workshop['job']['id'],source_card_id=None,name=asset['name'],category=asset['category'],description=asset['description'],profile=copy.deepcopy(asset.get('profile',{})),identity_asset_id=None,reference_id=None,suggested_views=asset['views'])
                    self.w.new_view(e,'portrait' if e['category']=='Character' else 'prop' if e['category']=='Prop' else 'location','Main reference',model)
            j.update(applied=True,applied_plan=plan,shot_ids=shots,episode_id=episode['id'],script_revision=episode['revision'],asset_ids=[v['id'] for v in workshop['views']],revision=j['revision']+1);self.p.put('world-job',j)
        return j

    def storyboard(self, eid, data, key):
        book=self.book(eid);old,fingerprint=self.key(key,['manual-storyboard',eid],data)
        if old and old.get('applied'):return old
        self.p.check(book,data);self.app.stories.check(book['episode'],{'expected_revision':data.get('expected_episode_revision')})
        if old:
            if old['book_revision']!=book['revision'] or old['episode_revision']!=book['episode']['revision']:raise APIError('revision_conflict','The episode changed before this storyboard was prepared. Use a new request after reviewing it.',409)
            return self.handoff(book,old,old['result'],self.w.model(data.get('image_model','gpt-image-2')),replace_script=False)
        episode=book['episode']
        if not episode['scenes']:raise APIError('missing_script','Save the episode script before creating its storyboard.')
        context=self.planning_context(book)
        plan=dict(reply='Storyboard prepared from your saved script. No provider was contacted.',logline=book['answers']['idea'] or episode['title'],synopsis=episode['notes'] or book['answers']['idea'] or episode['title'],visual_style=context['questionnaire']['style'] or 'Use the established series style.',assets=[],scenes=[dict(title=s['title'],text=s['text'] or s['title'],shots=[dict(title=(s['title']+' · Opening shot')[:120],image_prompt=('Scene: '+s['title']+'. '+s['text']+'\nStyle: '+context['questionnaire']['style'])[:2200],video_prompt=('Action: '+s['text']+'\nTone: '+context['questionnaire']['tone'])[:2200] or 'Show the scene action.',characters=[],location='')]) for s in episode['scenes']])
        with self.p.sql:j=self.p.new('world-job',scope='episode-book',purpose='manual-storyboard',production_id=book['production_id'],episode_id=eid,book_revision=book['revision'],episode_revision=episode['revision'],mock=self.app.mock,provider='manual',status='done',context=context,result=plan,key=key,fingerprint=fingerprint)
        # The AI planner is intentionally bounded to eight scenes. A manually
        # written episode can use the script editor's full 150-scene limit.
        return self.handoff(book,j,plan,self.w.model(data.get('image_model','gpt-image-2')),replace_script=False)

    def export_pdf(self, scope, identity):
        from world_bible import render_bible
        is_series=scope=='series-bible'
        book=self.bible(identity) if is_series else self.book(identity)
        production=self.production(book['production_id'])
        assets=self.library(production['id']) if is_series else copy.deepcopy((book.get('inheritance') or {}).get('assets',[]))
        if not is_series:
            assets += [a for a in self.library(production['id'],identity) if a.get('episode_id')==identity and a['id'] not in {x['id'] for x in assets}]
        guide=book['guide']; entities=[]; views=[]; entries=[]
        for group,category in [('cast','Character'),('places','Location'),('props','Prop')]:
            for card in guide[group]:
                if card.get('name'):entries.append(dict(name=card['name'],category=category,description=card.get('description') or card.get('personality') or card.get('purpose') or '',profile=card))
        for asset in assets:
            entry=next((e for e in entries if e['category']==asset['category'] and e['name']==asset['name']),None)
            if not entry:
                entry=dict(name=asset['name'],category=asset['category'],description=asset['description'],profile=asset.get('profile',{}));entries.append(entry)
            entity={**entry,**asset};entities.append(entity)
            for i,ref in enumerate((asset.get('reference') or {}).get('images',[])):
                if ref.get('asset_id'):views.append(dict(entity_id=entity['id'],view=ref.get('label') or f'Reference {i+1}',selected_asset_id=ref['asset_id']))
        for entry in entries:
            if not any(e['category']==entry['category'] and e['name']==entry['name'] for e in entities):entities.append({**entry,'id':'card-'+str(len(entities))})
        answers=copy.deepcopy(book['answers'])
        if not is_series:
            foundation=(book.get('inheritance') or {}).get('answers',{})
            for field in ('genre','tone','audience','style','rules'):
                if not answers[field]:answers[field]=foundation.get(field,'')
        plan=dict(logline=answers['idea'] or 'A world ready for your ideas.',synopsis=answers['plot'] or '',visual_style=answers['style'] or '',assets=entries,scenes=[])
        if not is_series:
            jobs=[j for j in self.jobs(identity) if j['status']=='done' and not j.get('script_inactive')]
            if jobs:plan={**plan,**copy.deepcopy(jobs[-1].get('applied_plan') or jobs[-1]['result']), 'assets':entries}
            elif book['episode']['scenes']:plan['scenes']=[{**s,'shots':[]} for s in book['episode']['scenes']]
        job=dict(mock=self.app.mock,result=plan,context={'questionnaire':{'title':production['title'] if is_series else book['episode']['title']}})
        return render_bible(self.app,production,job,dict(entities=entities,views=views),{**book,'answers':answers,'series_title':production['title'] if not is_series else '', 'book_kind':'Series Bible' if is_series else 'Episode Storybook'}),'application/pdf'

    def dispatch(self, method, parts, data, key):
        if len(parts)>=2 and parts[0]=='series':
            # Resolve once, before any lookup, fingerprint or stored foreign key.
            matches=[p for p in self.p.all('production') if parts[1] in (p['id'],p.get('series_id'))]
            if len(matches)!=1:raise APIError('not_found','Series project not found. Supply its production id or linked series id.',404)
            parts=[parts[0],self.production(matches[0]['id'])['id'],*parts[2:]]
        if len(parts)==4 and parts[0]=='episodes' and parts[2]=='upload-ai-review' and method=='GET':
            self.episode(parts[1]);return 200,self.upload_review.ai.view(self.upload_review.ai.read(parts[1],parts[3]))
        if len(parts)==3 and parts[0]=='series':
            pid=parts[1];action=parts[2]
            if action=='book.pdf' and method=='GET':return 200,self.export_pdf('series-bible',pid)
            if action=='bible':
                if method=='GET':return 200,self.bible(pid)
                if method=='PUT':return 200,self.save_bible(pid,data)
            if action=='library':
                if method=='GET':return 200,self.library(pid)
                if method=='POST':return 201,self.link_reference(pid,data)
            if action=='workshop':
                if method=='GET':return 200,self.workshop('series-bible',pid)
                if method=='POST':return 200,self.workshop('series-bible',pid,data)
            if action in ('generate','generation-preview') and method=='POST':
                j=self.w.job(pid,data.get('job_id'))
                if j.get('scope')!='series-bible':raise APIError('invalid_plan','Choose the Series Bible workshop job_id.')
                if action=='generation-preview':return 200,self.w.generation_preview(pid,data)
                return 202,self.w.generate(pid,data,key)
        if len(parts)==4 and parts[0]=='series' and parts[2:] == ['library','promote'] and method=='POST':return 200,self.promote(parts[1],data)
        if len(parts)==4 and parts[0]=='episodes' and parts[2]=='storybook':
            from storybook_links import refresh,readiness
            if parts[3]=='refresh-links' and method=='POST':return 200,refresh(self,parts[1],data)
            if parts[3]=='readiness' and method=='GET':return 200,readiness(self,parts[1])
        if len(parts)==3 and parts[0]=='episodes':
            eid=parts[1];action=parts[2];pid=self.episode(eid)[0]['id']
            if action=='book.pdf' and method=='GET':return 200,self.export_pdf('episode-book',eid)
            if action=='book':
                if method=='GET':return 200,self.book(eid)
                if method=='PUT':return 200,self.save_book(eid,data)
            if action=='library' and method=='GET':return 200,self.library(pid,eid)
            if action=='workshop':
                if method=='GET':return 200,self.workshop('episode-book',eid)
                if method=='POST':return 200,self.workshop('episode-book',eid,data)
            if action in ('generate','generation-preview') and method=='POST':
                j=self.w.job(pid,data.get('job_id'))
                if j.get('scope')!='episode-book' or j.get('episode_id')!=eid:raise APIError('invalid_plan','Choose this episode workshop job_id.')
                if action=='generation-preview':return 200,self.w.generation_preview(pid,data)
                return 202,self.w.generate(pid,data,key)
            if action=='jobs' and method=='GET':return 200,self.jobs(eid)
            if action=='plan' and method=='POST':return 202,self.plan(eid,data,key)
            if action=='complete-production' and method=='POST':return 202,self.completion.start(eid,data,key)
            if action=='production-review' and method=='POST':return 200,self.completion.resolve(eid,data)
            if action=='upload-preview' and method=='POST':return 200,self.upload_review.preview(eid,data)
            if action=='upload-ai-review' and method=='POST':return 202,self.upload_review.ai.start(eid,data,key)
            if action=='upload-apply' and method=='POST':return 200,self.upload_review.apply(eid,data)
            if action=='apply' and method=='POST':return 200,self.apply(eid,data)
            if action=='script' and method=='POST':return 200,self.script(eid,data)
            if action=='trash-script' and method=='POST':return 200,self.trash_script(eid,data)
            if action=='storyboard' and method=='POST':return 200,self.storyboard(eid,data,key)
            if action=='refresh-assets' and method=='POST':return 200,self.refresh_assets(eid,data)
        return None
