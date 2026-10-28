"""Consensual, tab-owned browser commands. Bearer callers never impersonate a browser."""
import copy
import json
import time
import uuid
from agent_api import APIError

class BrowserControls:
    def __init__(self, handoff):
        self.h=handoff
        self.path=handoff.app.storage/'browser-controls.json'
        self.db=json.loads(self.path.read_text()) if self.path.exists() else {'tabs':[], 'requests':[]}

    def persist(self):self.h.save(self.path,self.db)
    def public(self,row):
        value=copy.deepcopy({k:v for k,v in row.items() if k not in ('owner','auth_job_id')})
        if 'state' in row:value['controls_enabled']=self.h.db.get('control_consents',{}).get(row['owner'],0)>time.time()
        return value
    def clean(self):
        before=(len(self.db['tabs']),len(self.db['requests']),tuple((r['id'],r['revision']) for r in self.db['requests']))
        now=time.time()
        for r in self.db['requests']:
            if r['status']=='awaiting_human' and r.get('auth_job_id'):
                status=getattr(self,'identity_status',lambda _: 'error')(r['auth_job_id'])
                if status in ('connected','cancelled','error'):
                    r.update(status={'connected':'completed','cancelled':'rejected','error':'failed'}[status],revision=r['revision']+1,updated_at=now)
        self.db['tabs']=[t for t in self.db['tabs'] if t['expires_at']>now and self.h.db['consents'].get(t['owner'],0)>now]
        for r in self.db['requests']:
            if r['status'] in ('pending','awaiting_human') and not any(t['id']==r['tab_id'] for t in self.db['tabs']):
                r.update(status='expired',revision=r['revision']+1,updated_at=now,error='The originating tab stopped sharing or expired.')
        self.db['requests']=[r for r in self.db['requests'] if r['expires_at']>now]
        after=(len(self.db['tabs']),len(self.db['requests']),tuple((r['id'],r['revision']) for r in self.db['requests']))
        if after!=before:self.persist()

    def identity_action(self,owner,request_id,action):
        with self.h.lock:
            self.clean()
            r=self.get('requests',request_id);tab=self.get('tabs',r['tab_id'])
            if tab['owner']!=owner or r['kind']!='identity' or r['status']!='awaiting_human' or r['payload']['action'] not in (action,'switch' if action=='signin' else action):raise APIError('invalid_handoff','Identity request does not match this browser action.',409)
            r.update(status='executing',revision=r['revision']+1,updated_at=time.time());self.persist()
            return r

    def identity_result(self,r,action,result):
        with self.h.lock:
            r.update(revision=r['revision']+1,updated_at=time.time())
            if action=='signin':r.update(status='awaiting_human',auth_job_id=result['id'])
            else:r.update(status='completed')
            self.persist()

    def get(self,kind,identity):
        row=next((r for r in self.db[kind] if r['id']==identity),None)
        if not row:raise APIError('not_found','Browser context not found or expired.',404)
        return row

    def destination(self,route):
        self.h.fields(route,('page','workspace','tool','media','collection','overlay'))
        if route.get('page') not in ('home','projects','project','library','tool'):raise APIError('invalid_destination','Choose a Studio page.')
        if route.get('collection','all') not in ('all','images','videos','scripts','assets','uploads','exports'):raise APIError('invalid_destination','Choose a library collection.')
        if route.get('overlay') not in (None,'camera','movements'):raise APIError('invalid_destination','Choose a supported overlay.')
        if route.get('tool') not in (None,'image','video','scripts','assets','precision'):raise APIError('invalid_destination','Choose a Studio tool.')
        w=route.get('workspace')
        if route['page']=='project' and not isinstance(w,dict):raise APIError('invalid_destination','Include the project workspace.')
        if w is not None:
            self.h.fields(w,('production_id','episode_id','story_scene_id','shot_id','stage','board_view'))
            outline=self.h.app.productions.outline(w.get('production_id'))
            if outline['production'].get('archived'):raise APIError('invalid_destination','Restore the project before opening it.')
            if w.get('stage') not in ('develop','script','storyboard','generate','edit') or w.get('board_view','board') not in ('board','image'):raise APIError('invalid_destination','Choose a valid project stage.')
            if w.get('episode_id') and not any(e['id']==w['episode_id'] for e in outline['episodes']):raise APIError('invalid_destination','Episode is outside this project.')
            if w.get('shot_id') and not any(s['id']==w['shot_id'] and (not w.get('episode_id') or s.get('episode_id')==w['episode_id']) for s in outline['shots']):raise APIError('invalid_destination','Shot is outside this destination.')
            if w.get('story_scene_id') and not any(s['id']==w['story_scene_id'] for e in outline['episodes'] if not w.get('episode_id') or e['id']==w['episode_id'] for s in e['scenes']):raise APIError('invalid_destination','Scene is outside this destination.')
        if route['page']=='tool' and not route.get('tool'):raise APIError('invalid_destination','Include the tool.')
        if route.get('media'):
            media=route['media'];self.h.fields(media,('kind','id'))
            kind=media.get('kind');identity=media.get('id')
            if kind=='image':self.h.app.images.draft(identity)
            elif kind=='video':self.h.app.agent.record(identity)
            elif kind in ('script','scripts'):self.h.app.stories.record('episodes',identity)
            elif kind=='precision':self.h.app.asset(identity)
            elif kind=='assets':self.h.app.asset_studio.get(identity)
            else:raise APIError('invalid_destination','Choose saved media in this workspace.')
        return route

    def view(self,value):
        self.h.fields(value,('chapter','section','expanded','scroll_top','query','filter','position','playing','zoom','selection','field','expanded_editor'))
        for key,low,high in (('chapter',0,5),('scroll_top',0,1000000),('position',0,3600),('zoom',10,500)):
            if key in value and (type(value[key]) not in (int,float) or not low<=value[key]<=high):raise APIError('invalid_destination','Invalid '+key+'.')
        if 'chapter' in value and type(value['chapter']) is not int:raise APIError('invalid_destination','Chapter must be an integer.')
        if 'playing' in value and type(value['playing']) is not bool:raise APIError('invalid_destination','Playing must be boolean.')
        if 'expanded_editor' in value and (type(value['expanded_editor']) is not bool or 'field' not in value):raise APIError('invalid_destination','Expanded editor needs a field name and boolean state.')
        for key in ('section','query','filter','field'):
            if key in value and (not isinstance(value[key],str) or len(value[key])>300):raise APIError('invalid_destination','Invalid '+key+'.')
        if 'expanded' in value and (not isinstance(value['expanded'],list) or len(value['expanded'])>30 or any(type(v) is not bool for v in value['expanded'])):raise APIError('invalid_destination','Invalid expansion state.')
        if value.get('selection') is not None:
            self.h.fields(value['selection'],('kind','id'))
            if value['selection'].get('kind') not in ('clip','audio','title') or not isinstance(value['selection'].get('id'),str):raise APIError('invalid_destination','Choose a timeline selection.')

    def browser(self,owner,method,parts,data):
        self.clean()
        if method=='POST' and parts==['controls','consent']:
            self.h.fields(data,('enabled',))
            if type(data.get('enabled')) is not bool:raise APIError('invalid_consent','Choose whether to allow browser controls.')
            self.h.db.setdefault('control_consents',{})[owner]=time.time()+7200 if data['enabled'] else 0
            self.h.persist();return {'controls_enabled':data['enabled']}
        if method=='POST' and parts==['tabs']:
            if self.h.db['consents'].get(owner,0)<=time.time():raise APIError('consent_required','Enable agent handoff in this browser first.',403)
            self.h.fields(data,('route','editors','view'))
            self.destination(data.get('route'));self.view(data.get('view',{}))
            editors=data.get('editors',{})
            if not isinstance(editors,dict) or len(editors)>40:raise APIError('invalid_snapshot','Too many open editors.')
            for name,draft in editors.items():
                if not isinstance(name,str) or len(name)>200:raise APIError('invalid_snapshot','Invalid editor name.')
                self.h.fields(draft,('id','revision','dirty','data','actions'))
                if not isinstance(draft.get('id'),str) or type(draft.get('revision')) is not int or draft['revision']<0 or type(draft.get('dirty')) is not bool or not isinstance(draft.get('data'),dict):raise APIError('invalid_snapshot','Each editor needs its saved ID/revision, dirty flag and data.')
                if not isinstance(draft.get('actions'),list) or any(a not in ('save','reload','discard') for a in draft['actions']):raise APIError('invalid_snapshot','Publish supported editor actions.')
                self.h.snapshot({'editors':dict(id=name,revision=0,dirty=True,data=draft)})
            old=next((t for t in self.db['tabs'] if t['owner']==owner),None);now=time.time()
            changed=old is None or old['state']!=data
            tab=dict(id=old['id'] if old else uuid.uuid4().hex,owner=owner,revision=(old['revision']+int(changed)) if old else 1,state=copy.deepcopy(data),captured_at=now,expires_at=now+600)
            self.db['tabs']=[t for t in self.db['tabs'] if t['owner']!=owner]+[tab];self.persist()
            return {'tab':self.public(tab),'controls_enabled':self.h.db.get('control_consents',{}).get(owner,0)>now,'requests':[self.public(r) for r in self.db['requests'] if r['tab_id']==tab['id'] and r['status']=='pending']}
        if method=='POST' and len(parts)==3 and parts[0]=='requests' and parts[2]=='ack':
            self.h.fields(data,('expected_revision','status','error','auth_job_id'))
            r=self.get('requests',parts[1]);tab=self.get('tabs',r['tab_id'])
            if tab['owner']!=owner:raise APIError('not_found','Request belongs to another tab.',404)
            self.h.revision(r,data)
            if r['status'] not in ('pending','awaiting_human'):raise APIError('request_closed','Request already finished.',409)
            status=data.get('status')
            if status not in ('completed','failed','rejected','awaiting_human'):raise APIError('invalid_handoff','Invalid acknowledgement.')
            error=data.get('error')
            if error is not None and (not isinstance(error,str) or len(error)>500):raise APIError('invalid_handoff','Use a short error.')
            if data.get('auth_job_id'):
                if r['kind']!='identity' or not isinstance(data['auth_job_id'],str):raise APIError('invalid_handoff','Unexpected sign-in job.')
            r.update(status=status,error=error,revision=r['revision']+1,updated_at=time.time())
            if data.get('auth_job_id'):r['auth_job_id']=data['auth_job_id']
            self.persist();return self.public(r)
        return None

    def request(self,identity,data):
        self.h.fields(data,('expected_revision','kind','payload'))
        tab=self.get('tabs',identity);self.h.revision(tab,data)
        kind=data.get('kind');payload=data.get('payload')
        if kind=='navigate':
            self.h.fields(payload,('route','view'));self.destination(payload.get('route'));self.view(payload.get('view',{}))
        elif kind=='resolve':
            self.h.fields(payload,('editor','action'))
            if payload.get('action') not in ('save','reload','discard'):raise APIError('invalid_handoff','Choose save, reload or discard.')
            editor=tab['state']['editors'].get(payload.get('editor'))
            if editor is None or payload['action'] not in editor.get('actions',[]):raise APIError('invalid_handoff','This editor does not support that action.')
        elif kind=='identity':
            self.h.fields(payload,('action',))
            if payload.get('action') not in ('signin','switch','cancel','logout','guest','restore-guest'):raise APIError('invalid_handoff','Choose a supported identity action.')
        elif kind=='playback':self.view(payload)
        else:raise APIError('invalid_handoff','Choose navigate, resolve, identity or playback.')
        prior=next((r for r in self.db['requests'] if r['tab_id']==identity and r['status']=='pending' and r['expected_tab_revision']==tab['revision'] and r['kind']==kind and r['payload']==payload),None)
        if prior:return self.public(prior)
        now=time.time()
        r=dict(id=uuid.uuid4().hex,tab_id=identity,revision=1,status='pending',kind=kind,payload=copy.deepcopy(payload),expected_tab_revision=tab['revision'],created_at=now,updated_at=now,expires_at=now+600,error=None)
        r['expected_state']=copy.deepcopy({k:tab['state'][k] for k in ('route','editors')})
        if kind=='resolve':r['expected_editor']=copy.deepcopy(tab['state']['editors'][payload['editor']])
        self.db['requests'].append(r);self.persist();return self.public(r)

    def dispatch(self,method,parts,data,key=None):
        self.clean()
        if method=='GET' and parts==['tabs']:return 200,[self.public(t) for t in self.db['tabs']]
        if method=='GET' and len(parts)==2 and parts[0]=='tabs':return 200,self.public(self.get('tabs',parts[1]))
        if method=='POST' and len(parts)==3 and parts[0]=='tabs' and parts[2]=='requests':return 202,self.request(parts[1],data)
        if method=='GET' and len(parts)==2 and parts[0]=='requests':return 200,self.public(self.get('requests',parts[1]))
        return None
