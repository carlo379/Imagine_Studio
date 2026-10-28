"""Release 1 production relationships. Legacy media stays intact; no provider calls here."""
import copy
import json
import shutil
import sqlite3
import time
import uuid
import weakref
from contextlib import contextmanager, ExitStack, nullcontext
from agent_api import APIError
from story_studio import text

STAGES = ('develop', 'script', 'storyboard', 'generate', 'edit')
OWNER = 'local-user'

class ProductionStudio:
    def __init__(self, app):
        self.app = app
        self.path = app.storage / 'productions.sqlite3'
        first = not self.path.exists()
        if first:
            backup = app.storage / 'backups' / 'before-production-release-1'
            backup.mkdir(parents=True, exist_ok=True, mode=0o700)
            for name in ('scenes.json', 'stories.json', 'image-studio.json', 'assets.json', 'references.json', 'history.json', 'mock-history.json'):
                source = app.storage / name
                if source.exists() and not (backup / name).exists():
                    shutil.copy2(source, backup / name)
                    (backup / name).chmod(0o600)
        # Browser requests and workers share this connection. Disable statement
        # reuse: concurrent cached cursors can return invalid rows on this runtime.
        # Keep existing transaction/mutation behavior; no stored-data migration.
        self.sql = sqlite3.connect(self.path, check_same_thread=False, cached_statements=0)
        self.path.chmod(0o600)
        self._close = weakref.finalize(self, self.sql.close)
        self.sql.executescript('''
          CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS versions (id TEXT NOT NULL, revision INTEGER NOT NULL, owner TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(id,revision));
          CREATE TABLE IF NOT EXISTS workspace (owner TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS records_kind_owner ON records(kind,owner);
        ''')
        self.sql.commit()
        self.index()

    def all(self, kind):
        return [json.loads(r[0]) for r in self.sql.execute('SELECT body FROM records WHERE kind=? AND owner=? ORDER BY rowid', (kind, OWNER))]

    def get(self, identity, kind):
        row = self.sql.execute('SELECT body FROM records WHERE id=? AND kind=? AND owner=?', (identity, kind, OWNER)).fetchone()
        if not row: raise APIError('not_found', kind.title() + ' not found in this workspace.', 404)
        return json.loads(row[0])

    def put(self, kind, r):
        r['updated_at'] = time.time()
        self.sql.execute('INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (r['id'], kind, OWNER, json.dumps(r)))
        self.sql.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?,?)', (r['id'], r['revision'], OWNER, json.dumps(r)))
        return copy.deepcopy(r)

    def new(self, record_kind, **fields):
        return self.put(record_kind, dict(id=uuid.uuid4().hex, revision=1, created_at=time.time(), **fields))

    def check(self, record, data):
        if data.get('expected_revision') != record['revision']:
            raise APIError('revision_conflict', 'This production changed. Refresh it before saving. Your draft has not been applied.', 409)

    def media_renamed(self, kind, identity, title):
        # One-shot Quick Videos represent the same creation in the editor,
        # outline and project library. Larger projects retain their own name.
        field = 'video_id' if kind == 'video' else 'image_id'
        shots = self.all('shot')
        # Preserve an outer coordinated edit's rollback boundary.
        with (nullcontext() if self.sql.in_transaction else self.sql):
            for shot in shots:
                if shot.get(field) != identity:
                    continue
                if shot['title'] != title:
                    shot.update(title=title, revision=shot['revision']+1)
                    self.put('shot', shot)
                production = self.get(shot['production_id'], 'production')
                if production['kind'] == 'quick' and sum(s['production_id'] == production['id'] for s in shots) == 1 and production['title'] != title:
                    production.update(title=title, revision=production['revision']+1)
                    self.put('production', production)

    @contextmanager
    def mutation(self):
        # Roll back the existing JSON stores if creation of linked records fails.
        services = (self.app.agent, self.app.images, self.app.stories)
        with ExitStack() as stack:
            for service in services: stack.enter_context(service.lock)
            before = [copy.deepcopy(s.db) for s in services]
            try:
                with self.sql: yield
            except Exception:
                for service, db in zip(services, before):
                    # Workers retain references to these job objects. Do not detach them
                    # when rolling back draft/link edits during an in-flight generation.
                    for field in ('jobs','chats'):
                        if field in service.db: db[field] = service.db[field]
                    service.db = db
                    self.app.agent.save(service.path, db)
                raise

    def discover(self):
        """Idempotently index existing work, including work made through older tools/APIs."""
        productions = self.all('production')
        mapped = {p.get('series_id'): p for p in productions if p.get('series_id')}
        for series in self.app.stories.db['series']:
            if series['id'] not in mapped:
                mapped[series['id']] = self.new('production', kind='story', title=series['title'], brief=series['notes'], series_id=series['id'])
        shots = self.all('shot')
        videos = {s.get('video_id') for s in shots}
        images = {identity for s in shots for identity in self.image_ids(s)}
        def parent(record):
            ctx = record.get('story_context', {})
            p = mapped.get(ctx.get('series_id'))
            if p: return p, ctx.get('episode_id'), ctx.get('scene_id')
            return self.new('production', kind='quick', title=record['title'], brief='', series_id=None, origin='media'), None, None
        for video in self.app.agent.db['scenes']:
            if video['id'] in videos: continue
            p, ep, scene = parent(video)
            shot = self.new('shot', production_id=p['id'], episode_id=ep, story_scene_id=scene, title=video['title'], notes='', video_id=video['id'], image_id=None, selected_image=None, selected_video=None)
            shots.append(shot)
        for image in reversed(self.app.images.db['drafts']):
            if image['id'] in images: continue
            if image.get('parent_draft_id'):
                owner=next((s for s in shots if image['parent_draft_id'] in self.image_ids(s) or image.get('version_root_id') in self.image_ids(s)),None)
                if owner:
                    owner['image_version_ids']=list(dict.fromkeys([*self.image_ids(owner),image['id']]))
                    owner['revision']+=1;self.put('shot',owner);images.add(image['id'])
                    continue
            ctx = image.get('story_context', {})
            partner = next((s for s in shots if not s['image_id'] and s.get('episode_id') == ctx.get('episode_id') and s.get('story_scene_id') == ctx.get('scene_id') and ctx.get('scene_id')), None)
            if partner:
                partner['image_id'] = image['id']; partner['revision'] += 1; self.put('shot', partner)
            else:
                p, ep, scene = parent(image)
                shots.append(self.new('shot', production_id=p['id'], episode_id=ep, story_scene_id=scene, title=image['title'], notes='', video_id=None, image_id=image['id'], selected_image=None, selected_video=None))
        # Infer membership only from saved script context, never from titles.
        # An explicit null is a user's choice to keep the production standalone.
        media={r['id']:r for r in [*self.app.agent.db['scenes'],*self.app.images.db['drafts']]}
        for p in self.all('production'):
            if p['kind']!='quick' or 'parent_production_id' in p or p.get('archived'):continue
            parents={mapped[ctx['series_id']]['id'] for s in shots if s['production_id']==p['id'] for field in ('video_id','image_id') for ctx in [media.get(s.get(field),{}).get('story_context') or {}] if ctx.get('series_id') in mapped}
            if len(parents)==1:
                p.update(parent_production_id=parents.pop(),revision=p['revision']+1);self.put('production',p)

        # Workshop ownership includes Bible views without episode script context.
        owners={v['draft_id']:v['production_id'] for v in self.all('world-asset')}
        for p in self.all('production'):
            if self.is_project(p):
                for shot in shots:
                    if shot['production_id']==p['id'] and shot.get('image_id'):owners.setdefault(shot['image_id'],p['id'])
        drafts={d['id']:d for d in self.app.images.db['drafts']}
        outputs={o['id']:j['draft']['id'] for j in self.app.images.db['jobs'] for o in j.get('outputs',[])}
        jobs={j['draft']['id']:j for j in self.app.images.db['jobs']}
        while True:
            added=False
            for identity,draft in drafts.items():
                if identity in owners:continue
                base=(draft.get('settings',{}).get('base') or {}).get('asset_id')
                base=jobs.get(identity,{}).get('parent_asset_id') or base
                source=outputs.get(base)
                if source in owners:owners[identity]=owners[source];added=True
            if not added:break
        for p in self.all('production'):
            linked=[s for s in shots if s['production_id']==p['id']]
            parents={owners[s['image_id']] for s in linked if s.get('image_id') in owners}
            if p['kind']=='quick' and len(parents)==1 and p['id'] not in parents:
                owner=parents.pop()
                if p.get('parent_production_id')!=owner or p.get('origin')!='media':
                    p.update(parent_production_id=owner,origin='media',revision=p['revision']+1);self.put('production',p)

    def is_project(self,p,shots=None,videos=None,images=None):
        if p['kind']=='story' or p.get('origin')=='quick_video':return True
        if p.get('origin')=='media':return False
        # Older explicit Quick Video projects created a paired video/image shot.
        videos=videos if videos is not None else {v['id']:v for v in self.app.agent.db['scenes']}
        images=images if images is not None else {d['id']:d for d in self.app.images.db['drafts']}
        shots=shots if shots is not None else self.all('shot')
        return any(s.get('video_id') in videos and s.get('image_id') in images and p['created_at']<=images[s['image_id']].get('created_at',images[s['image_id']].get('updated_at',0)) for s in shots if s['production_id']==p['id'])

    def index(self):
        # Discovery links legacy drafts. Editing a prompt does not create a new
        # relationship; avoid rebuilding the index on every outline poll.
        stamp = (tuple(s['id'] for s in self.app.stories.db['series']),
                 tuple((s['id'],(s.get('story_context') or {}).get('series_id')) for s in self.app.agent.db['scenes']),
                 tuple((d['id'],d.get('parent_draft_id'),d.get('version_root_id'),(d.get('story_context') or {}).get('series_id')) for d in self.app.images.db['drafts']),
                 tuple((j['id'],j.get('parent_asset_id')) for j in self.app.images.db['jobs']),
                 tuple(self.sql.execute("SELECT id,json_extract(body,'$.revision') FROM records WHERE kind='world-asset' AND owner=?",(OWNER,))))
        if getattr(self, '_discovery_stamp', None) == stamp:return
        if self.sql.in_transaction: self.discover()
        else:
            with self.sql: self.discover()
        self._discovery_stamp = stamp

    def summary(self, identity):
        """Browser outline without archival series/script/request snapshots."""
        self.index()
        p = self.get(identity, 'production')
        episodes = [dict(id=e['id'],title=e['title'],revision=e['revision'],
            scenes=[dict(id=s['id'],title=s['title']) for s in e['scenes']])
            for e in self.app.stories.db['episodes'] if p['series_id'] and e['series_id']==p['series_id']]
        fields = ('id','revision','production_id','episode_id','story_scene_id','title','video_id','image_id',
            'image_version_ids','selected_image','selected_video','image_selection_cleared','shot_order','archived',
            'story_direction','story_direction_updated_at','video_mode','start_frame_asset_id','updated_at')
        # Project only small columns in SQLite; do not deserialize each shot's
        # repeated Bible and catalog archives just to draw an outline.
        projection=','.join("json_extract(body,'$.%s')" % f for f in fields)
        rows=self.sql.execute('SELECT '+projection+' FROM records WHERE kind=? AND owner=? AND json_extract(body,\'$.production_id\')=?',('shot',OWNER,identity))
        shots=[dict(zip(fields,row)) for row in rows]
        videos={r['id']:r for r in self.app.agent.db['scenes']};images={r['id']:r for r in self.app.images.db['drafts']}
        image_jobs={};video_jobs={};legacy=[]
        for j in self.app.images.db['jobs']:
            if j['mock']==self.app.mock:image_jobs.setdefault(j['draft']['id'],[]).append(j)
        with self.app.lock:jobs=list(self.app.history)
        jobs += [j for j in self.all('imported-video') if j.get('mock')==self.app.mock]
        for j in jobs:
            vid=j['settings'].get('_studio_video_id')
            if vid:video_jobs.setdefault(vid,[]).append(j)
            elif j['settings'].get('_studio_scene'):legacy.append(j)
        episode_map={e['id']:e for e in self.app.stories.db['episodes']}
        for shot in shots:
            versions=shot.get('image_version_ids')
            shot['image_version_ids']=json.loads(versions) if isinstance(versions,str) else (versions or [])
            v=videos.get(shot['video_id']);im=images.get(shot['image_id'])
            shot['video']=dict(id=v['id'],revision=v['revision'],title=v['title'],archived=v.get('archived',False),scene={'duration':v['scene']['duration']}) if v else None
            shot['image']=dict(id=im['id'],revision=im['revision'],title=im['title']) if im else None
            ijs=[j for i in self.image_ids(shot) for j in image_jobs.get(i,[])]
            vjs=list(video_jobs.get(shot['video_id'],[]))
            if v and legacy and sum(r['scene']==v['scene'] for r in videos.values())==1:
                vjs += [j for j in legacy if j['settings']['_studio_scene']==v['scene']]
            shot['image_takes']=[dict(id=j['id'],status=j['status'],created_at=j['created_at'],outputs=copy.deepcopy(j.get('outputs',[]))) for j in ijs]
            shot['video_takes']=[dict(id=j['id'],status=j['status'],created_at=j['created_at'],video='/api/video-media/'+j['id'] if j.get('video') else None) for j in vjs]
            shot['image_versions']=[dict(id=images[i]['id'],revision=images[i]['revision'],title=images[i]['title']) for i in self.image_ids(shot) if i in images]
            approved=[a for j in ijs for a in j.get('outputs',[]) if a.get('approved')]
            current=next((a for a in approved if a['id']==shot.get('selected_image')),None)
            if not current and not shot.get('image_selection_cleared'):current=next(iter(approved),None)
            shot['approved_image']=copy.deepcopy(current)
            shot['image_ready']=bool(current or (v and v['scene']['first']))
            shot['video_ready']=any(j['status']=='done' for j in vjs)
            ep=episode_map.get(shot['episode_id'])
            shot['orphaned']=bool(ep and not any(s['id']==shot['story_scene_id'] for s in ep['scenes']))
            shot['script_changed']=bool(ep and any(r and r.get('story_context',{}).get('script_revision')!=ep['revision'] for r in (v,im)))
            shot['status']='Script changed' if shot['script_changed'] else 'Video ready' if shot['video_ready'] else 'Image ready' if shot['image_ready'] else 'To storyboard'
            shot['notes']='';shot['_summary']=True
        order={(e['id'],s['id']):(ei,si) for ei,e in enumerate(episodes) for si,s in enumerate(e['scenes'])}
        shots=sorted((s for s in shots if not s.get('archived')),key=lambda s:(order.get((s['episode_id'],s['story_scene_id']),(10000,10000)),s['shot_order'] if s.get('shot_order') is not None else 100000))
        return dict(production=p,episodes=episodes,shots=shots,summary=True)

    def recent(self, data):
        limit=data.get('limit',10);offset=data.get('offset',0)
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
            raise APIError('invalid_page','Use a page size of 1–100 and a nonnegative offset.')
        self.index()
        videos={r['id']:r for r in self.app.agent.db['scenes']}
        images={r['id']:r for r in self.app.images.db['drafts']}
        def metadata(kind,fields):
            projection=','.join("json_extract(body,'$.%s')" % f for f in fields)
            return [dict(zip(fields,row)) for row in self.sql.execute('SELECT '+projection+' FROM records WHERE kind=? AND owner=?',(kind,OWNER))]
        shots=metadata('shot',('id','production_id','video_id','image_id','activity_at'))
        timelines=metadata('timeline',('id','production_id','revision','updated_at'))
        exports=metadata('export',('timeline_id','updated_at'));items=[]
        jobs=self.app.records()
        archived=data.get('archived',False)
        if type(archived) is not bool:raise APIError('invalid_page','Archived must be true or false.')
        productions=self.all('production');active={p['id']:p for p in productions if not p.get('archived')}
        parent_id=data.get('parent_id')
        if parent_id is not None and type(parent_id) is not str:raise APIError('invalid_parent','Use a Story / Series production ID.')
        if parent_id is not None:
            parent=self.get(parent_id,'production')
            if parent['kind']!='story' or parent.get('archived'):raise APIError('invalid_parent','Choose an active Story / Series.')
        for p in productions:
            if bool(p.get('archived'))!=archived:continue
            linked=[s for s in shots if s['production_id']==p['id']]
            vs=[videos[s['video_id']] for s in linked if s['video_id'] in videos]
            ims=[images[s['image_id']] for s in linked if s['image_id'] in images]
            episodes=[e for e in self.app.stories.db['episodes'] if p['series_id'] and e['series_id']==p['series_id']]
            video_content=any(any(v['scene'].get(k) for k in ('prompt','first','last','refs','keys','named','voices')) for v in vs)
            image_content=any(any(r['settings'].get(k) for k in ('prompt','base','extras','bindings')) for r in ims)
            if p['kind']=='story':
                item_type='script' if not video_content and not image_content and any(e['scenes'] or e['notes'] for e in episodes) else 'story'
            elif video_content:item_type='video'
            elif image_content or (ims and not vs):item_type='image'
            elif vs and ims:
                # Opening an imported image lazily creates a blank video draft.
                # Retain the image identity while that new video is still blank.
                image_time=min(r.get('created_at',r.get('updated_at',p['created_at'])) for r in ims)
                video_time=min(r.get('created_at',r.get('updated_at',p['created_at'])) for r in vs)
                item_type='image' if image_time<video_time else 'video'
            else:item_type='video'
            date_records=[*ims,*episodes] if item_type=='image' else [*vs,*ims,*episodes]
            dates=[r.get('updated_at',r.get('created_at',0)) for r in date_records]
            dates += [s.get('activity_at') or 0 for s in linked]
            edits=[t for t in timelines if t['production_id']==p['id']]
            dates += [t['updated_at'] for t in edits if t['revision']>1]
            dates += [j['updated_at'] for j in exports if j['timeline_id'] in {t['id'] for t in edits}]
            if p['revision']>1:dates.append(p['updated_at'])
            for job in self.app.images.db['jobs']:
                if job['mock']==self.app.mock and job['draft']['id'] in {r['id'] for r in ims}:dates.append(job['created_at'])
            for job in jobs:
                if job['settings'].get('_studio_video_id') in {r['id'] for r in vs}:dates.append(job['created_at'])
            updated=max(dates,default=0) or p['updated_at']
            effective_parent=p.get('parent_production_id') if p.get('parent_production_id') in active else None
            project=self.is_project(p,shots,videos,images)
            items.append({**p,'project_label':'Quick Video' if project and p['kind']=='quick' else None,'is_project':project,'item_type':item_type,'last_updated':updated,'group_id':effective_parent,'child_count':sum(c.get('parent_production_id')==p['id'] for c in active.values())})
        production_total=len(items)
        if data.get('projects_only'):
            for p in items:p['child_count']=sum(c['is_project'] and c.get('group_id')==p['id'] for c in items)
        # A group's position reflects recent work anywhere inside it.
        by_id={p['id']:p for p in items}
        for p in items:
            ancestor=p.get('group_id');visited={p['id']}
            while ancestor in by_id and ancestor not in visited:
                visited.add(ancestor);by_id[ancestor]['last_updated']=max(by_id[ancestor]['last_updated'],p['last_updated']);ancestor=by_id[ancestor].get('group_id')
        if not archived:items=[p for p in items if p['group_id']==parent_id]
        if data.get('projects_only'):
            items=[p for p in items if p['is_project']]
            production_total=len(items)
        items.sort(key=lambda r:(-r['last_updated'],r['id']))
        return dict(items=items[offset:offset+limit],total=len(items),production_total=production_total,offset=offset,limit=limit,has_more=offset+limit<len(items))

    def manage(self,p,action,data):
        self.check(p,data)
        if action=='membership':
            if p.get('archived'):raise APIError('archived','Restore this production from Trash first.',409)
            target=data.get('parent_production_id')
            if 'parent_production_id' not in data:raise APIError('invalid_parent','Choose a Story / Series, or null for standalone.')
            if target is not None and type(target) is not str:raise APIError('invalid_parent','Use a Story / Series production ID or null.')
            if target is not None:
                parent=self.get(target,'production')
                if parent['kind']!='story' or parent.get('archived'):raise APIError('invalid_parent','Choose an active Story / Series.')
                seen={p['id']};ancestor=parent
                while ancestor:
                    if ancestor['id'] in seen:raise APIError('invalid_parent','A production cannot belong to itself or one of its descendants.')
                    seen.add(ancestor['id']);next_id=ancestor.get('parent_production_id');ancestor=self.get(next_id,'production') if next_id else None
            p['parent_production_id']=target
        elif action=='trash':
            if p.get('archived'):raise APIError('archived','This production is already in Trash.',409)
            p.update(archived=True,archived_at=time.time())
            if self.workspace()['production_id']==p['id']:self.select({'production_id':None})
        elif action=='restore':
            if not p.get('archived'):raise APIError('not_archived','This production is not in Trash.',409)
            p.update(archived=False,archived_at=None)
        p['revision']+=1
        return self.put('production',p)

    def episode(self, p, identity):
        ep = self.app.stories.record('episodes', identity)
        if not p['series_id'] or ep['series_id'] != p['series_id']:
            raise APIError('invalid_parent', 'Choose an episode from this production.')
        return ep

    def create_shot(self, p, data):
        title = text(data.get('title', 'Shot 1'), 120, 'Shot title', True)
        ctx = None
        if p['kind'] == 'story':
            ep = self.episode(p, data.get('episode_id'))
            if not data.get('story_scene_id'): raise APIError('missing_scene', 'Choose a script scene before adding a shot.')
            ctx = self.app.stories.context(ep['id'], data['story_scene_id'])
        video = self.app.agent.create({'title':title, 'scene':{}, 'story_context':ctx})
        image = self.app.images.create({'title':title, 'settings':{}, 'story_context':ctx})
        return self.new('shot', production_id=p['id'], episode_id=ctx['episode_id'] if ctx else None, story_scene_id=ctx['scene_id'] if ctx else None, title=title, notes='', video_id=video['id'], image_id=image['id'], selected_image=None, selected_video=None)

    def media(self, shot, kind):
        field = 'video_id' if kind == 'video' else 'image_id'
        if not shot[field]:
            data = {'title':shot['title']}
            if shot.get('story_scene_id'): data['story_context'] = self.app.stories.context(shot['episode_id'], shot['story_scene_id'])
            r = self.app.agent.create(data) if kind == 'video' else self.app.images.create(data)
            shot[field] = r['id']; shot['revision'] += 1; self.put('shot', shot)
        return self.app.agent.record(shot[field]) if kind == 'video' else self.app.images.draft(shot[field])

    def view_shot(self, shot):
        result = copy.deepcopy(shot)
        video = next((r for r in self.app.agent.db['scenes'] if r['id'] == shot['video_id']), None)
        image = next((r for r in self.app.images.db['drafts'] if r['id'] == shot['image_id']), None)
        result['video'] = copy.deepcopy(video); result['image'] = copy.deepcopy(image)
        image_takes = [j for j in self.app.images.db['jobs'] if j['mock'] == self.app.mock and j['draft']['id'] in self.image_ids(shot)]
        result['image_versions']=[copy.deepcopy(d) for d in self.app.images.db['drafts'] if d['id'] in self.image_ids(shot)]
        # Old jobs have no draft ID. Match their full saved settings snapshot only.
        unique_snapshot = video and sum(r['scene']==video['scene'] for r in self.app.agent.db['scenes'])==1
        video_takes = [j for j in self.app.records() if j['settings'].get('_studio_video_id') == shot['video_id'] or (unique_snapshot and not j['settings'].get('_studio_video_id') and j['settings'].get('_studio_scene') == video['scene'])]
        result['image_takes'] = copy.deepcopy(image_takes); result['video_takes'] = video_takes
        approved = [a for j in image_takes for a in j.get('outputs', []) if a.get('approved')]
        current = next((a for a in approved if a['id'] == shot.get('selected_image')), None)
        if not current and not shot.get('image_selection_cleared'):current=next(iter(approved),None)
        result['approved_image'] = current
        result['image_ready'] = bool(current or (video and video['scene']['first']))
        result['video_ready'] = any(j['status'] == 'done' for j in video_takes)
        result['script_changed'] = False
        if shot.get('episode_id'):
            ep = self.app.stories.record('episodes', shot['episode_id'])
            result['orphaned'] = not any(s['id'] == shot['story_scene_id'] for s in ep['scenes'])
            result['script_changed'] = any(r and r.get('story_context', {}).get('script_revision') != ep['revision'] for r in (video, image))
        result['story_direction'] = shot.get('story_direction', shot.get('storyboard_video_prompt', ''))
        if not result['story_direction']:
            for job in reversed(self.all('world-job')):
                if shot['id'] in job.get('shot_ids', []):
                    plan=job.get('applied_plan') or job.get('result') or {}
                    entries=[entry for scene in plan.get('scenes',[]) for entry in scene.get('shots',[])]
                    index=job['shot_ids'].index(shot['id'])
                    if index<len(entries):result['story_direction']=entries[index].get('video_prompt','')
                    break
        for take in [*result['video_takes'], *result['image_takes']]:
            take['earlier_direction'] = bool(shot.get('story_direction_updated_at') and take.get('created_at', 0) < shot['story_direction_updated_at'])
        if not shot.get('story_direction'):
            result['story_direction']=result['story_direction'].split('\nCanonical identities:')[0].split('\nIncluded objects:')[0].strip()
        result['status'] = 'Script changed' if result['script_changed'] else 'Video ready' if result['video_ready'] else 'Image ready' if result['image_ready'] else 'To storyboard'
        return result

    def image_ids(self, shot):
        return list(dict.fromkeys(i for i in [shot.get('image_id'),*shot.get('image_version_ids',[])] if i))

    def image_branches(self, production_id):
        """Offer only pixel-linked legacy refinements, never title-based guesses."""
        shots=[s for s in self.all('shot') if s['production_id']==production_id and not s.get('archived')]
        outputs={o['id']:j['draft']['id'] for j in self.app.images.db['jobs'] for o in j.get('outputs',[])}
        candidates=[]
        for branch in shots:
            draft=self.app.images.draft(branch['image_id']) if branch.get('image_id') else None
            source=outputs.get(((draft or {}).get('settings',{}).get('base') or {}).get('asset_id'))
            parents=[s for s in shots if s['id']!=branch['id'] and source in self.image_ids(s) and s.get('episode_id')==branch.get('episode_id') and s.get('story_scene_id')==branch.get('story_scene_id')]
            view=self.view_shot(branch)
            video=view.get('video')
            video_work=video and any(video['scene'].get(k) for k in ('prompt','refs','first','last','keys'))
            linked_work=any(json.loads(row[0]).get('shot_id')==branch['id'] for row in self.sql.execute("SELECT body FROM records WHERE kind NOT IN ('shot','production') AND owner=?",(OWNER,)))
            in_edit=any(c.get('shot_id')==branch['id'] for t in self.all('timeline') for c in t.get('clips',[]))
            if len(parents)==1 and not branch.get('notes') and not branch.get('selected_video') and not view['video_takes'] and not video_work and not linked_work and not in_edit:
                parent=parents[0]
                candidates.append(dict(branch_id=branch['id'],branch_title=branch['title'],branch_revision=branch['revision'],shot_id=parent['id'],shot_title=parent['title'],shot_revision=parent['revision']))
        return candidates

    def outline(self, identity):
        self.index()
        p = self.get(identity, 'production')
        episodes = [copy.deepcopy(e) for e in self.app.stories.db['episodes'] if e['series_id'] == p['series_id']] if p['series_id'] else []
        scope_order={(episode['id'],scene['id']):(ei,si) for ei,episode in enumerate(episodes) for si,scene in enumerate(episode['scenes'])}
        return dict(production=p, episodes=episodes, shots=[self.view_shot(s) for s in sorted(self.all('shot'), key=lambda s:(scope_order.get((s.get('episode_id'),s.get('story_scene_id')),(10000,10000)),s.get('shot_order',100000))) if s['production_id'] == identity and not s.get('archived')])

    def workspace(self):
        row = self.sql.execute('SELECT body FROM workspace WHERE owner=?', (OWNER,)).fetchone()
        return json.loads(row[0]) if row else dict(production_id=None, episode_id=None, story_scene_id=None, shot_id=None, stage='develop', board_view='board')

    def select(self, data):
        old = self.workspace(); identity = data.get('production_id', old['production_id'])
        if identity is None:
            value = dict(production_id=None, episode_id=None, story_scene_id=None, shot_id=None, stage='develop', board_view='board')
        else:
            p = self.get(identity, 'production'); same = identity == old['production_id']; stage = data.get('stage', old['stage'] if same else 'develop')
            if p.get('archived'):raise APIError('archived','Restore this production from Trash before opening it.',409)
            if stage not in STAGES: raise APIError('invalid_stage', 'Choose Develop, Script, Storyboard or Generate.')
            if p['kind']=='quick' and stage=='script':raise APIError('invalid_stage','Quick Video skips Script. Choose Develop, Storyboard or Generate.')
            same = identity == old['production_id']
            value = dict(production_id=identity, stage=stage, episode_id=data.get('episode_id', old['episode_id'] if same else None), story_scene_id=data.get('story_scene_id', old['story_scene_id'] if same else None), shot_id=data.get('shot_id', old['shot_id'] if same else None), board_view=data.get('board_view', old.get('board_view','board') if same else 'board'))
            if value['board_view'] not in ('board','image'): raise APIError('invalid_view', 'Choose board or image.')
            if value['shot_id']:
                shot = self.get(value['shot_id'], 'shot')
                if shot.get('archived'):raise APIError('archived','Restore this shot from Shot trash first.',409)
                if shot['production_id'] != identity: raise APIError('invalid_parent', 'Choose a shot from this production.')
                value.update(episode_id=shot['episode_id'], story_scene_id=shot['story_scene_id'])
                for kind in ('video','image'):
                    r = self.media(shot, kind)
                    service = self.app.agent if kind == 'video' else self.app.images
                    if kind == 'video' and r.get('archived'): raise APIError('archived', 'Restore this saved video draft in Existing work first.')
                    if service.db['current_id'] != r['id']:
                        service.db['current_id'] = r['id']; self.app.agent.save(service.path, service.db)
            if value['episode_id']:
                ep = self.episode(p, value['episode_id'])
                sid = value['story_scene_id']
                # Deleted script scenes remain available as shots but no longer select an invalid story context.
                if sid and not any(s['id']==sid for s in ep['scenes']): sid = None
                context={'episode_id':ep['id'], 'scene_id':sid}
                if self.app.stories.db['workspace']!=context:
                    self.app.stories.db['workspace']=context;self.app.stories.persist()
        self.sql.execute('INSERT OR REPLACE INTO workspace VALUES (?,?)', (OWNER,json.dumps(value)))
        return value

    def dispatch(self, method, parts, data, key=None):
        if len(parts)==2 and parts[1]=='summary' and method=='GET':return 200,self.summary(parts[0])
        if parts == ['recent'] and method == 'POST':return 200,self.recent(data)
        if parts == ['locate'] and method == 'POST':
            kind=data.get('kind')
            if kind not in ('image','video'):raise APIError('invalid_media','Choose image or video.')
            with self.sql:self.discover()
            shot=next((s for s in self.all('shot') if (data.get('id') in self.image_ids(s) if kind=='image' else s['video_id']==data.get('id'))),None)
            if not shot:raise APIError('not_found','Media draft is not in this workspace.',404)
            if kind=='image' and shot['image_id']!=data['id']:
                with self.sql:
                    shot['image_version_ids']=self.image_ids(shot)
                    shot.update(image_id=data['id'],revision=shot['revision']+1)
                    self.put('shot',shot)
            return 200,dict(production_id=shot['production_id'],shot_id=shot['id'])
        if parts == ['context'] and method == 'GET':
            w=self.workspace();return 200,dict(workspace=w,outline=self.outline(w['production_id']) if w['production_id'] else None,assets=self.app.named_library(),mock=self.app.mock)
        if parts == ['schema'] and method == 'GET':
            return 200, dict(stages=STAGES, kinds=['quick','story'], pagination={'route':'POST productions/recent','default_limit':10,'max_limit':100,'filters':['parent_id','archived','projects_only'],'classification':{'is_project':'Story / Series or explicit Quick Video; Bible and standalone image drafts are not projects','project_label':'Quick Video for explicit quick projects; null otherwise'},'counts':'total counts the selected group scope; production_total counts all active/archived records unless projects_only=true, when both counts reflect projects in the selected group scope; child_count then counts project children','fields':['items','total','production_total','offset','limit','has_more']},organization={'membership':'POST productions/{id}/membership with expected_revision and parent_production_id (null detaches)','trash':'POST productions/{id}/trash with expected_revision; originals retained; children become standalone while the parent is in Trash','restore':'POST productions/{id}/restore with expected_revision; saved grouping returns if the parent is active'},item_types=['video','image','script','story'], owner=OWNER, storage='SQLite relationships; original media and scripts retained', actions=['create production','edit brief','group production','detach production','trash production','restore production','create episode','create scene','create shot','edit shot','select workspace','place approved image','select take','refresh script context','version history'])
        if parts == ['workspace']:
            if method == 'GET': return 200, self.workspace()
            if method == 'POST':
                with self.mutation(): return 200, self.select(data)
        if not parts:
            if method == 'GET':
                self.index()
                return 200, [p for p in self.all('production') if not p.get('archived')]
            if method == 'POST':
                title = text(data.get('title',''),120,'Production title',True); brief = text(data.get('brief',''),20000,'Creative brief')
                kind = data.get('kind')
                if kind not in ('quick','story'): raise APIError('invalid_kind','Choose Quick Video or Story / Series.')
                with self.mutation():
                    series = self.app.stories.dispatch('POST',['series'],{'title':title},None)[1] if kind == 'story' else None
                    p = self.new('production',kind=kind,title=title,brief=brief,series_id=series['id'] if series else None,origin='quick_video' if kind=='quick' else 'story')
                    if kind == 'quick': self.create_shot(p, {'title':title})
                    else: self.app.stories.dispatch('POST',['episodes'],{'series_id':series['id'],'title':data.get('episode_title','Episode 1')},None)
                    return 201, self.outline(p['id'])
        if parts and parts[0] == 'shots' and len(parts)>=2:
            s = self.get(parts[1], 'shot')
            if len(parts)==2 and method=='GET': return 200,self.view_shot(s)
            if len(parts)==2 and method=='PUT':
                self.check(s,data)
                with self.mutation():
                    direction = text(data['story_direction'],10000,'Shot direction',True) if 'story_direction' in data else None
                    if 'archived' in data and type(data['archived']) is not bool: raise APIError('invalid_input','Archived must be a boolean.')
                    if 'shot_order' in data and (type(data['shot_order']) is not int or not 0 <= data['shot_order'] <= 10000): raise APIError('invalid_input','Choose a valid shot order.')
                    s.update(title=text(data.get('title',s['title']),120,'Shot title',True),notes=text(data.get('notes',s['notes']),10000,'Shot notes'),revision=s['revision']+1,activity_at=time.time())
                    if direction is not None and direction!=s.get('story_direction',s.get('storyboard_video_prompt')):
                        s.update(story_direction=direction,storyboard_video_prompt=direction,story_direction_updated_at=time.time())
                    if 'shot_type' in data and (not isinstance(data['shot_type'],str) or len(data['shot_type'])>120):raise APIError('invalid_input','Shot type must be text up to 120 characters.')
                    if 'video_mode' in data and data['video_mode'] not in ('text_to_video','image_to_video'):raise APIError('invalid_input','Choose text_to_video or image_to_video.')
                    if data.get('start_frame_asset_id'):self.app.asset(data['start_frame_asset_id'])
                    for field in ('archived','shot_order','video_mode','start_frame_asset_id','shot_type'):
                        if field in data: s[field]=data[field]
                    return 200,self.put('shot',s)
            if len(parts)==3 and method=='POST':
                self.check(s,data)
                with self.mutation():
                    action=parts[2]
                    if action=='import-video':
                        if not isinstance(data.get('media_id'),str):raise APIError('invalid_media','Choose a saved video upload.')
                        media,path=self.app.editing.media_file(data['media_id'])
                        if not media.get('video') or media.get('ext') not in ('mp4','mov','webm'):raise APIError('invalid_media','Choose an uploaded MP4, MOV or WebM video.')
                        if type(data.get('select',True)) is not bool:raise APIError('invalid_input','Select uploaded take must be a boolean.')
                        source=text(data.get('source_label','External video'),120,'Video source',True)
                        video=self.media(s,'video')
                        job=self.new('imported-video',status='done',mock=self.app.mock,imported_media_id=media['id'],source_label=source,requested_model='external-video',returned_model=None,settings={'model':'external-video','duration':media['duration'],'resolution':str(media.get('height') or '')+'p','aspect_ratio':str(media.get('width'))+':'+str(media.get('height')),'generate_audio':media.get('audio',False),'prompt':'','_studio_video_id':video['id'],'_studio_title':s['title'],'_studio_shot_direction':s.get('story_direction','')})
                        job['video']='/api/video-media/'+job['id'];self.put('imported-video',job)
                        if data.get('select',True):s['selected_video']=job['id']
                        s.update(revision=s['revision']+1,activity_at=time.time());self.put('shot',s)
                        return 201,dict(shot=self.view_shot(s),take=job)
                    if action=='place-image':
                        from frame_tools import place
                        v=self.media(s,'video')
                        result=place(self.app.agent,data.get('asset_id'),{**data,'scene_id':v['id'],'expected_revision':data.get('expected_video_revision'),'new_scene':False})
                        s['selected_image']=data['asset_id']; s['revision']+=1; s['activity_at']=time.time(); self.put('shot',s)
                        return 200,dict(shot=self.view_shot(s),video=result)
                    if action=='select-take':
                        kind=data.get('kind'); value=data.get('id'); view=self.view_shot(s)
                        if kind=='image':
                            valid=('id' in data and value is None) or any(a['id']==value and a.get('approved') for j in view['image_takes'] for a in j.get('outputs',[]))
                        elif kind=='video': valid=('id' in data and value is None) or any(j['id']==value and j['status']=='done' for j in view['video_takes'])
                        else: valid=False
                        if not valid: raise APIError('invalid_take','Choose an approved image or completed video from this shot.')
                        if kind=='image':s['image_selection_cleared']=value is None
                        s['selected_'+kind]=value; s['revision']+=1;s['activity_at']=time.time();self.put('shot',s);return 200,self.view_shot(s)
                    if action=='duplicate':
                        video=self.app.agent.create({'title':s['title']+' copy','scene':copy.deepcopy(self.media(s,'video')['scene']),'story_context':self.media(s,'video').get('story_context')})
                        image=self.app.images.create({'title':s['title']+' copy','settings':copy.deepcopy(self.media(s,'image')['settings']),'story_context':self.media(s,'image').get('story_context')})
                        return 201,self.new('shot',production_id=s['production_id'],episode_id=s['episode_id'],story_scene_id=s['story_scene_id'],title=s['title']+' copy',notes=s['notes'],video_id=video['id'],image_id=image['id'],selected_image=None,selected_video=None)
                    if action=='merge-image-branch':
                        candidate=next((c for c in self.image_branches(s['production_id']) if c['branch_id']==data.get('branch_id') and c['shot_id']==s['id']),None)
                        if not candidate:raise APIError('invalid_branch','This image branch cannot be safely reassociated. Review its shot separately.',409)
                        branch=self.get(candidate['branch_id'],'shot')
                        if data.get('expected_branch_revision')!=branch['revision']:raise APIError('revision_conflict','The branch changed. Refresh before moving its versions.',409)
                        s['image_version_ids']=list(dict.fromkeys([*self.image_ids(s),*self.image_ids(branch)]))
                        if not s.get('selected_image'):s['selected_image']=branch.get('selected_image')
                        s['revision']+=1;self.put('shot',s)
                        branch.update(archived=True,merged_into=s['id'],revision=branch['revision']+1);self.put('shot',branch)
                        return 200,self.view_shot(s)
                    if action=='refresh-context':
                        if not s['story_scene_id']: raise APIError('missing_scene','This quick shot has no script context.')
                        ctx=self.app.stories.context(s['episode_id'],s['story_scene_id'])
                        for kind in ('video','image'):
                            r=self.media(s,kind);r['story_context']=copy.deepcopy(ctx);r['revision']+=1
                            service=self.app.agent if kind=='video' else self.app.images;self.app.agent.save(service.path,service.db)
                        s['revision']+=1;s['activity_at']=time.time();self.put('shot',s);return 200,self.view_shot(s)
        if parts and parts[0]!='shots':
            p=self.get(parts[0],'production')
            if len(parts)==2 and method=='GET' and parts[1]=='shot-trash':return 200,[self.view_shot(s) for s in self.all('shot') if s['production_id']==p['id'] and s.get('archived') and not s.get('merged_into')]
            if len(parts)==2 and method=='GET' and parts[1]=='image-branches':return 200,self.image_branches(p['id'])
            if len(parts)==1 and method=='GET': return 200,self.outline(p['id'])
            if len(parts)==1 and method=='PUT':
                self.check(p,data)
                title = text(data.get('title',p['title']),120,'Production title',True)
                brief = text(data.get('brief',p['brief']),20000,'Creative brief')
                with self.mutation():
                    if title != p['title'] and p.get('series_id'):
                        series = self.app.stories.record('series',p['series_id'])
                        series.update(title=title,revision=series['revision']+1)
                        self.app.stories.persist()
                    p.update(title=title,brief=brief,revision=p['revision']+1)
                    return 200,self.put('production',p)
            if len(parts)==2 and parts[1]=='versions' and method=='GET':
                return 200,[json.loads(r[0]) for r in self.sql.execute('SELECT body FROM versions WHERE id=? AND owner=? ORDER BY revision DESC',(p['id'],OWNER))]
            if len(parts)==2 and method=='POST':
                with self.mutation():
                    if parts[1] in ('membership','trash','restore'):return 200,self.manage(p,parts[1],data)
                    if p.get('archived'):raise APIError('archived','Restore this production from Trash first.',409)
                    if parts[1]=='reorder-shots':
                        siblings=[shot for shot in self.outline(p['id'])['shots'] if shot.get('episode_id')==data.get('episode_id') and shot.get('story_scene_id')==data.get('story_scene_id')]
                        ids=data.get('shot_ids'); revisions=data.get('expected_revisions',{})
                        if not isinstance(ids,list) or not all(isinstance(identity,str) for identity in ids) or len(ids)!=len(set(ids)) or set(ids)!={shot['id'] for shot in siblings}:raise APIError('invalid_order','Reorder all active shots within the same scene. Reload if shots changed.',409)
                        for shot in siblings:
                            if revisions.get(shot['id'])!=shot['revision']:raise APIError('revision_conflict','The shot list changed. Reload before reordering.',409)
                        for order,identity in enumerate(ids):
                            shot=self.get(identity,'shot');shot.update(shot_order=order,revision=shot['revision']+1,activity_at=time.time());self.put('shot',shot)
                        return 200,self.outline(p['id'])
                    if parts[1]=='shots': return 201,self.create_shot(p,data)
                    if parts[1]=='episodes':
                        if p['kind']!='story':raise APIError('invalid_kind','Quick Video does not use episodes.')
                        return self.app.stories.dispatch('POST',['episodes'],{'series_id':p['series_id'],'title':data.get('title','')},None)
                    if parts[1]=='scenes':
                        ep=self.episode(p,data.get('episode_id'));self.app.stories.check(ep,data)
                        scenes=[*copy.deepcopy(ep['scenes']),dict(title=data.get('title','New scene'),text=data.get('text',''))]
                        return 201,self.app.stories.episode_edit(ep,{'expected_revision':data['expected_revision'],'scenes':scenes})
        raise APIError('not_found','Production route not found.',404)
