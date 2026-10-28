"""Local, workspace-owned navigation metadata and explicitly shared read-only drafts."""
import copy
import hashlib
import json
import math
import re
import threading
import time
import uuid
from agent_api import APIError

class BrowserHandoff:
    def __init__(self,app,save):
        self.app,self.save=app,save;self.lock=threading.RLock();self.path=app.storage/'browser-handoff.json'
        self.db=json.loads(self.path.read_text()) if self.path.exists() else {'flows':[],'consents':{},'drafts':[]}
        from browser_controls import BrowserControls
        self.controls=BrowserControls(self)

    def fields(self,data,allowed):
        if not isinstance(data,dict) or set(data)-set(allowed):raise APIError('invalid_handoff','Unexpected handoff fields.')

    def owner(self,session,tab):
        if not session:raise APIError('browser_session_required','Only a human browser session can publish browser context.',403)
        if not isinstance(tab,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',tab):raise APIError('invalid_tab','Use the current browser tab ID.')
        return hashlib.sha256((session+'\0'+tab).encode()).hexdigest()

    def public(self,row):return copy.deepcopy({k:v for k,v in row.items() if k!='owner'})
    def persist(self):self.save(self.path,self.db)

    def clean(self):
        now=time.time()
        before=(len(self.db['drafts']),len(self.db['consents']),len(self.db['flows']))
        self.db['drafts']=[d for d in self.db['drafts'] if d['expires_at']>now and self.db['consents'].get(d['owner'],0)>now]
        self.db['consents']={o:t for o,t in self.db['consents'].items() if t>now}
        self.db['flows']=[f for f in self.db['flows'] if f['expires_at']>now]
        if before!=(len(self.db['drafts']),len(self.db['consents']),len(self.db['flows'])):self.persist()

    def flow(self,identity):
        self.clean();row=next((f for f in self.db['flows'] if f['id']==identity),None)
        if not row:raise APIError('not_found','Return flow not found in this workspace, or expired.',404)
        return row

    def revision(self,row,data):
        if type(data.get('expected_revision')) is not int or data['expected_revision']!=row['revision']:raise APIError('revision_conflict','This handoff changed. Read it again before continuing.',409)

    def validate_context(self,value):
        self.fields(value,('route','title','context','draft_id'))
        if not isinstance(value.get('title'),str) or len(value['title'])>300:raise APIError('invalid_handoff','Use a short return title.')
        route=value.get('route');self.fields(route,('page','workspace'))
        if route.get('page')!='project':raise APIError('invalid_handoff','Return to a saved project.')
        workspace=route.get('workspace');self.fields(workspace,('production_id','episode_id','story_scene_id','shot_id','stage','board_view'))
        if not isinstance(workspace.get('production_id'),str) or not workspace['production_id']:raise APIError('invalid_handoff','Include the saved project ID.')
        for name in ('episode_id','story_scene_id','shot_id'):
            if workspace.get(name) is not None and (not isinstance(workspace[name],str) or len(workspace[name])>128):raise APIError('invalid_handoff','Invalid project destination ID.')
        if workspace.get('board_view','board') not in ('board','image'):raise APIError('invalid_handoff','Invalid project board view.')
        if workspace.get('stage')!='develop':raise APIError('invalid_handoff','Return to the development stage.')
        context=value.get('context');self.fields(context,('scope','entity_id','view_id','expected_revision','page','visual','job_id'))
        if any(not isinstance(context.get(k),str) or not context[k] or len(context[k])>128 for k in ('scope','entity_id','view_id')):raise APIError('invalid_handoff','Include the source scope, entity and view IDs.')
        if type(context.get('page')) is not int or not 0<=context['page']<=5:raise APIError('invalid_handoff','Choose a book chapter from 0 to 5.')
        if type(context.get('expected_revision')) is not int or context['expected_revision']<1:raise APIError('invalid_handoff','Include the source view revision.')
        visual=context.get('visual');self.fields(visual,('activeStep','expanded','heroChoice','optionalChoice','optionalOpen','scrollTop'))
        expanded=visual.get('expanded')
        # Preserve current five-step and previously saved four-step return flows.
        if not isinstance(expanded,list) or len(expanded) not in (4,5) or any(type(v) is not bool for v in expanded):raise APIError('invalid_handoff','Include four or five section expansion states.')
        if type(visual.get('activeStep')) is not int or not 0<=visual['activeStep']<len(expanded):raise APIError('invalid_handoff','Choose a development section.')
        scroll=visual.get('scrollTop',0)
        if type(scroll) not in (int,float) or not math.isfinite(scroll) or not 0<=scroll<=1000000:raise APIError('invalid_handoff','Invalid scroll position.')
        for key in ('heroChoice','optionalChoice'):
            if key in visual and (not isinstance(visual[key],str) or len(visual[key])>128):raise APIError('invalid_handoff','Invalid candidate selection.')
        if 'optionalOpen' in visual and type(visual['optionalOpen']) is not bool:raise APIError('invalid_handoff','Invalid optional section state.')
        entity=self.app.productions.get(context['entity_id'],'world-entity');view=self.app.productions.get(context['view_id'],'world-asset')
        pid=workspace.get('production_id');production=self.app.productions.get(pid,'production')
        if production.get('archived') or entity['production_id']!=pid or view.get('entity_id')!=entity['id']:raise APIError('invalid_handoff','Return context does not belong to this project.')
        scope='episodes/'+entity['episode_id'] if entity.get('episode_id') else 'series/'+pid
        if context.get('scope')!=scope or (scope.startswith('episodes/') and workspace.get('episode_id')!=entity['episode_id']):raise APIError('invalid_handoff','Return scope does not match the entity.')
        if not isinstance(value.get('draft_id'),str):raise APIError('invalid_handoff','Include the saved image draft ID.')
        self.app.images.draft(value['draft_id'])
        outputs=self.app.filmmaking.workshop.view(view)['outputs']
        drafts={view['draft_id'],*(o.get('draft_id') for o in outputs)}
        if value['draft_id'] not in drafts:raise APIError('invalid_handoff','Image draft does not belong to this view.')
        if context.get('job_id') and self.app.images.job(context['job_id'])['draft']['id']!=value['draft_id']:raise APIError('invalid_handoff','Image job does not belong to this draft.')
        if visual.get('heroChoice') and visual['heroChoice'] not in {o['id'] for o in outputs}:raise APIError('invalid_handoff','Candidate does not belong to this view.')

    def create(self,owner,data):
        self.validate_context(data);self.clean()
        for previous in self.db['flows']:
            if previous['owner']==owner and previous['status'] in ('open','return_requested'):
                previous.update(status='superseded',revision=previous['revision']+1,updated_at=time.time())
        now=time.time();row=dict(id=uuid.uuid4().hex,owner=owner,revision=1,status='open',created_at=now,updated_at=now,expires_at=now+7*86400,value=copy.deepcopy(data))
        self.db['flows'].append(row);self.persist();return self.public(row)

    def request(self,identity,data):
        self.fields(data,('expected_revision',));row=self.flow(identity);self.revision(row,data)
        if row['status'] not in ('open','return_requested'):raise APIError('flow_closed','This return flow is already completed.',409)
        self.validate_context(row['value'])
        if row['status']=='open':row.update(status='return_requested',revision=row['revision']+1,updated_at=time.time());self.persist()
        return self.public(row)

    def finish(self,identity,data):
        self.fields(data,('expected_revision',));row=self.flow(identity);self.revision(row,data)
        if row['status'] not in ('returned','finished'):raise APIError('return_not_applied','The originating browser must restore the destination before this flow can finish.',409)
        if row['status']=='returned':row.update(status='finished',revision=row['revision']+1,updated_at=time.time());self.persist()
        return self.public(row)

    def snapshot(self,value):
        self.fields(value,('book','image','video','timeline','editors'))
        def inspect(item,depth=0):
            if depth>24:raise APIError('snapshot_limit','Draft nesting is too deep.')
            if isinstance(item,dict):
                if any(str(k).lower().replace('_','').replace('-','') in ('apikey','accesstoken','refreshtoken','idtoken','token','secret','authorization','cookie','cookies','password','credentials','auth') for k in item):raise APIError('unsafe_snapshot','Credentials are not browser drafts.')
                for v in item.values():inspect(v,depth+1)
            elif isinstance(item,list):
                for v in item:inspect(v,depth+1)
            elif isinstance(item,str) and item.startswith('data:'):raise APIError('snapshot_limit','Share local image IDs, not embedded image data.')
        inspect(value)
        if len(json.dumps(value,allow_nan=False).encode())>256*1024:raise APIError('snapshot_limit','Shared drafts are limited to 256 KB.')
        for draft in value.values():
            if draft is None:continue
            self.fields(draft,('id','revision','dirty','data'))
            if not isinstance(draft.get('id'),str) or type(draft.get('revision')) is not int or draft['revision']<0 or draft.get('dirty') is not True or not isinstance(draft.get('data'),dict):raise APIError('invalid_snapshot','Each pending draft needs its saved ID/revision, dirty=true, and read-only data.')

    def browser_dispatch(self,session,tab,method,parts,data):
        owner=self.owner(session,tab)
        with self.lock:
            self.clean()
            control=self.controls.browser(owner,method,parts,data)
            if control is not None:return control
            if method=='GET' and not parts:return {'flows':[self.public(f) for f in self.db['flows'] if f['owner']==owner and f['status'] not in ('finished','superseded')],'sharing_enabled':self.db['consents'].get(owner,0)>time.time()}
            if method=='POST' and parts==['flows']:return self.create(owner,data)
            if method=='POST' and parts==['drafts','consent']:
                self.fields(data,('enabled',))
                if type(data.get('enabled')) is not bool:raise APIError('invalid_consent','Choose whether to share drafts.')
                if data['enabled']:self.db['consents'][owner]=time.time()+2*3600
                else:
                    self.db['consents'].pop(owner,None);self.db['drafts']=[d for d in self.db['drafts'] if d['owner']!=owner]
                    self.db.get('control_consents',{}).pop(owner,None);self.controls.clean();self.controls.persist()
                self.persist();return {'sharing_enabled':data['enabled']}
            if method=='POST' and parts==['drafts']:
                if self.db['consents'].get(owner,0)<=time.time():raise APIError('consent_required','Enable read-only draft sharing in this browser first.',403)
                self.snapshot(data);old=next((d for d in self.db['drafts'] if d['owner']==owner),None);now=time.time()
                row=dict(id=old['id'] if old else uuid.uuid4().hex,owner=owner,revision=old['revision']+1 if old else 1,captured_at=now,expires_at=now+600,read_only=True,drafts=copy.deepcopy(data))
                self.db['drafts']=[d for d in self.db['drafts'] if d['owner']!=owner]+[row];self.persist();return self.public(row)
            if method=='POST' and len(parts)==3 and parts[0]=='flows' and parts[2]=='returned':
                self.fields(data,('expected_revision',));row=self.flow(parts[1])
                if row['owner']!=owner:raise APIError('not_found','This flow belongs to another browser tab.',404)
                self.revision(row,data)
                if row['status'] not in ('open','return_requested','returned'):raise APIError('flow_closed','This flow is finished.',409)
                if row['status']!='returned':row.update(status='returned',revision=row['revision']+1,updated_at=time.time());self.persist()
                return self.public(row)
        raise APIError('not_found','Browser handoff route not found.',404)

    def dispatch(self,method,parts,data,key=None):
        with self.lock:
            self.clean()
            control=self.controls.dispatch(method,parts,data,key)
            if control is not None:return control
            if method=='GET' and not parts:return 200,{'flows':'/agent/v1/handoff/flows','drafts':'/agent/v1/handoff/drafts','tabs':'/agent/v1/handoff/tabs','requests':'/agent/v1/handoff/requests/{id}','read_only_drafts':True,'human_consent_required':True,'controls_consent_required':True}
            if method=='GET' and parts==['flows']:return 200,[self.public(f) for f in self.db['flows']]
            if method=='GET' and len(parts)==2 and parts[0]=='flows':return 200,self.public(self.flow(parts[1]))
            if method=='POST' and len(parts)==3 and parts[0]=='flows' and parts[2]=='request':return 200,self.request(parts[1],data)
            if method=='POST' and len(parts)==3 and parts[0]=='flows' and parts[2]=='finish':return 200,self.finish(parts[1],data)
            if method=='GET' and parts==['drafts']:return 200,[self.public(d) for d in self.db['drafts']]
            if method=='GET' and len(parts)==2 and parts[0]=='drafts':
                row=next((d for d in self.db['drafts'] if d['id']==parts[1]),None)
                if not row:raise APIError('not_found','Shared draft not found, expired, or sharing was revoked.',404)
                return 200,self.public(row)
        raise APIError('not_found','Handoff route not found.',404)
