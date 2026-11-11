"""Approve a production plan once, then let the agent generate inside it.

A plan lists the scenes (shots) to make, how many takes each may use and an optional
budget: a cap on total takes and on Grok usage percentage. The human approves the plan
once, in the browser or through an agent relaying their own words. Generation under the
plan replaces the per-request approved=true. Every safety step still applies: the human
review pause, usage readings while costs are being learned, and the rejected-shot rule.

Verdicts drive each shot: keep finishes it; retry authorizes one more take, which may
change the scene; reject means the shot must be rethought, so a changed scene needs the
plan approved again. Any edit to the plan clears its approval.
"""
import copy
import hashlib
import json
import time
import uuid

from agent_api import APIError

MAX_ITEMS=200
MAX_TAKES_PER_ITEM=5
DEFAULT_TAKES_PER_ITEM=2


def _text(value, field, limit, required=False):
    if value is None and not required:return ''
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        raise APIError('invalid_plan',f'{field} must be text of at most {limit:,} characters'+(' and not empty.' if required else '.'))
    return value.strip()


class Plans:
    def __init__(self, app, save_json):
        self.app=app;self.save_json=save_json
        self.path=app.storage/('mock-plans.json' if app.mock else 'plans.json')
        self.plans=json.loads(self.path.read_text()) if self.path.exists() else []

    # ----- storage and lookups -----
    def _save(self):self.save_json(self.path,self.plans)

    def _plan(self, plan_id):
        plan=next((p for p in self.plans if p['id']==plan_id),None)
        if not plan:raise APIError('not_found','Plan not found.',404)
        return plan

    def _scene(self, scene_id):
        return next((r for r in self.app.agent.db['scenes'] if r['id']==scene_id),None)

    @staticmethod
    def digest(plan):
        """Fingerprint of what the human approves: the shots, their take limits and the budget."""
        content=dict(items=[[i['scene_id'],i['label'],i['max_takes']] for i in plan['items']],budget=plan['budget'])
        return hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()

    def _jobs(self, plan_id, scene_id=None):
        jobs=[j for j in self.app.records() if (j.get('plan') or {}).get('id')==plan_id
              and (scene_id is None or j['plan'].get('item')==scene_id)]
        return sorted(jobs,key=lambda j:j.get('created_at',0))

    # ----- validation of plan content -----
    def _items(self, items):
        if not isinstance(items,list) or not items or len(items)>MAX_ITEMS:
            raise APIError('invalid_plan',f'items must list 1–{MAX_ITEMS} shots.')
        out=[];seen=set()
        for index,item in enumerate(items):
            if not isinstance(item,dict) or set(item)-{'scene_id','label','max_takes'}:
                raise APIError('invalid_plan',f'Item {index+1}: send scene_id, optional label and optional max_takes only.')
            scene=self._scene(item.get('scene_id'))
            if not scene:raise APIError('invalid_plan',f"Item {index+1}: scene {item.get('scene_id')!r} not found.")
            if scene.get('archived'):raise APIError('invalid_plan',f"Item {index+1}: scene {scene['id']} is archived.")
            if scene['id'] in seen:raise APIError('invalid_plan',f"Item {index+1}: scene {scene['id']} is listed twice.")
            seen.add(scene['id'])
            takes=item.get('max_takes',DEFAULT_TAKES_PER_ITEM)
            if type(takes) is not int or not 1<=takes<=MAX_TAKES_PER_ITEM:
                raise APIError('invalid_plan',f'Item {index+1}: max_takes must be a whole number from 1 to {MAX_TAKES_PER_ITEM}.')
            out.append(dict(scene_id=scene['id'],label=_text(item.get('label'),'label',200) or scene.get('title',''),max_takes=takes))
        return out

    @staticmethod
    def _budget(budget):
        budget=budget or {}
        if not isinstance(budget,dict) or set(budget)-{'usage_percent','max_takes'}:
            raise APIError('invalid_plan','budget accepts usage_percent and max_takes only.')
        cap=budget.get('usage_percent')
        if cap is not None and (isinstance(cap,bool) or not isinstance(cap,(int,float)) or not 0<cap<=100):
            raise APIError('invalid_plan','budget.usage_percent must be a number above 0 and at most 100 (percent of the weekly Grok allowance).')
        takes=budget.get('max_takes')
        if takes is not None and (type(takes) is not int or takes<1):
            raise APIError('invalid_plan','budget.max_takes must be a whole number of at least 1.')
        return dict(usage_percent=None if cap is None else float(cap),max_takes=takes)

    # ----- plan lifecycle -----
    def create(self, data):
        if not isinstance(data,dict) or set(data)-{'title','notes','items','budget'}:
            raise APIError('invalid_plan','Send title, optional notes, items and optional budget.')
        now=time.time()
        plan=dict(id=uuid.uuid4().hex,revision=1,created_at=now,updated_at=now,status='draft',
                  title=_text(data.get('title'),'title',200,required=True),notes=_text(data.get('notes'),'notes',4000),
                  items=self._items(data.get('items')),budget=self._budget(data.get('budget')),approval=None)
        with self.app.lock:
            self.plans.insert(0,plan);self._save()
        return self.view(plan['id'])

    def update(self, plan_id, data):
        if not isinstance(data,dict) or set(data)-{'expected_revision','title','notes','items','budget'}:
            raise APIError('invalid_plan','Send expected_revision with title, notes, items and/or budget.')
        with self.app.lock:
            plan=self._plan(plan_id)
            if data.get('expected_revision')!=plan['revision']:raise APIError('revision_conflict','Plan changed. Fetch it again before saving.',409)
            if plan['status']=='closed':raise APIError('plan_closed','This plan is closed.',409)
            before=self.digest(plan)
            if 'title' in data:plan['title']=_text(data['title'],'title',200,required=True)
            if 'notes' in data:plan['notes']=_text(data['notes'],'notes',4000)
            if 'items' in data:plan['items']=self._items(data['items'])
            if 'budget' in data:plan['budget']=self._budget(data['budget'])
            if self.digest(plan)!=before:plan.update(status='draft',approval=None)
            plan.update(revision=plan['revision']+1,updated_at=time.time());self._save()
        return self.view(plan_id)

    def approve(self, plan_id, data, *, source):
        allowed={'expected_revision'}|({'human_words'} if source=='agent_relay' else set())
        if not isinstance(data,dict) or set(data)-allowed:raise APIError('invalid_plan','Send '+' and '.join(sorted(allowed))+'.')
        words=None
        if source=='agent_relay':
            words=data.get('human_words')
            if not isinstance(words,str) or not words.strip() or len(words)>2000:
                raise APIError('invalid_plan',"human_words must quote the human's own approval, verbatim (1–2,000 characters).")
            words=words.strip()
        # Every shot's kit must be ready before the human can approve (checked outside the lock).
        for item in self._plan(plan_id)['items']:
            scene=self._scene(item['scene_id'])
            if scene:self.app.shot_kit.require_ready(scene)
        with self.app.lock:
            plan=self._plan(plan_id)
            if data.get('expected_revision')!=plan['revision']:raise APIError('revision_conflict','Plan changed. Show the human the current plan before approving.',409)
            if plan['status']=='closed':raise APIError('plan_closed','This plan is closed.',409)
            revisions={}
            for item in plan['items']:
                scene=self._scene(item['scene_id'])
                if not scene or scene.get('archived'):raise APIError('invalid_plan',f"Scene {item['scene_id']} is missing or archived.")
                revisions[item['scene_id']]=scene['revision']
            plan['approval']=dict(approved_at=time.time(),plan_hash=self.digest(plan),scene_revisions=revisions,source=source,
                                  **({'human_words':words} if words is not None else {}))
            plan.update(status='approved',revision=plan['revision']+1,updated_at=time.time());self._save()
        return self.view(plan_id)

    def close(self, plan_id, data):
        with self.app.lock:
            plan=self._plan(plan_id)
            if (data or {}).get('expected_revision')!=plan['revision']:raise APIError('revision_conflict','Plan changed. Fetch it again.',409)
            plan.update(status='closed',revision=plan['revision']+1,updated_at=time.time());self._save()
        return self.view(plan_id)

    # ----- costs -----
    def _rates(self):
        return {res:c['percent_per_second'] for res,c in self.app.usage_calibration()['resolutions'].items() if c['established']}

    @staticmethod
    def _estimate(rates, resolution, duration):
        rate=rates.get(resolution)
        return None if rate is None or not isinstance(duration,(int,float)) else round(rate*duration,3)

    def _spent(self, jobs, rates):
        """Usage spent by these takes: measured from readings when available, else the learned estimate."""
        total,unknown=0.0,0
        for job in jobs:
            usage=job.get('usage') or {}
            if job.get('mock'):continue
            if usage.get('before') is not None and usage.get('after') is not None and usage['after']>=usage['before']:
                total+=usage['after']-usage['before'];continue
            settings=job.get('settings') or {}
            estimate=self._estimate(rates,settings.get('resolution'),settings.get('duration'))
            if estimate is None:unknown+=1
            else:total+=estimate
        return round(total,3),unknown

    # ----- the gate used by generation -----
    def authorize(self, plan_id, scene):
        """Raise unless this plan allows one more take of this scene now. Returns the plan item."""
        plan=self._plan(plan_id)
        if plan['status']=='closed':raise APIError('plan_closed','This plan is closed.',409)
        if plan['status']!='approved' or not plan.get('approval') or plan['approval']['plan_hash']!=self.digest(plan):
            raise APIError('plan_not_approved','The human has not approved the current version of this plan. Show it to them and ask.',403)
        item=next((i for i in plan['items'] if i['scene_id']==scene['id']),None)
        if item:self.app.shot_kit.require_ready(scene)
        if not item:raise APIError('not_in_plan','This scene is not part of the approved plan. Add it to the plan and ask the human to approve again.',403)
        jobs=self._jobs(plan_id,scene['id'])
        verdicts=[(j.get('human_review') or {}).get('verdict') for j in jobs]
        if 'keep' in verdicts:raise APIError('plan_item_done','The human kept a take of this shot; it is finished.',409)
        latest=jobs[-1] if jobs else None
        approved_revision=plan['approval']['scene_revisions'].get(scene['id'])
        if scene['revision']!=approved_revision:
            retry=latest and (latest.get('human_review') or {}).get('verdict')=='retry' \
                and scene['revision']>=((latest.get('agent_scene') or {}).get('revision') or 0)
            if not retry:
                raise APIError('plan_scene_changed','This shot changed since the human approved the plan. Only a retry verdict '
                    'authorizes a changed take; after a reject or any other change, update the plan and ask the human to approve it again.',409)
        since=[j for j in jobs if j.get('created_at',0)>=plan['approval']['approved_at']]
        if len(since)>=item['max_takes']:
            raise APIError('plan_takes_exhausted',f"This shot has used all {item['max_takes']} takes the plan allows. Ask the human before making more.",409)
        all_jobs=self._jobs(plan_id)
        if plan['budget']['max_takes'] is not None and len(all_jobs)>=plan['budget']['max_takes']:
            raise APIError('plan_budget_exceeded',f"The plan's limit of {plan['budget']['max_takes']} takes is used up. Ask the human before continuing.",409)
        cap=plan['budget']['usage_percent']
        if cap is not None and not self.app.mock:
            rates=self._rates();spent,_=self._spent(all_jobs,rates)
            body=scene['scene']
            estimate=self._estimate(rates,body.get('resolution'),body.get('duration')) or 0
            if spent+estimate>cap:
                raise APIError('plan_budget_exceeded',f'This take would bring the plan to about {spent+estimate:.2f}% of the weekly Grok '
                    f'allowance, over its {cap:g}% budget. Ask the human before continuing.',409)
        return item

    # ----- read model -----
    def view(self, plan_id):
        with self.app.lock:plan=copy.deepcopy(self._plan(plan_id))
        rates=self._rates();items=[];expected=worst=0.0;unknown_estimates=0
        approval=plan.get('approval') or {}
        current=plan['status']=='approved' and approval.get('plan_hash')==self.digest(plan)
        for item in plan['items']:
            scene=self._scene(item['scene_id']) or {}
            body=scene.get('scene') or {}
            jobs=self._jobs(plan['id'],item['scene_id'])
            verdicts=[(j.get('human_review') or {}).get('verdict') for j in jobs]
            estimate=self._estimate(rates,body.get('resolution'),body.get('duration'))
            if estimate is None:unknown_estimates+=1
            else:expected+=estimate;worst+=estimate*item['max_takes']
            approved_revision=(approval.get('scene_revisions') or {}).get(item['scene_id'])
            state=('kept' if 'keep' in verdicts else 'awaiting_review' if any((j.get('human_review') or {}).get('status')=='pending' for j in jobs)
                   else 'rejected' if verdicts and verdicts[-1]=='reject' else 'retry' if verdicts and verdicts[-1]=='retry'
                   else 'takes_used_up' if approval and len([j for j in jobs if j.get('created_at',0)>=approval['approved_at']])>=item['max_takes']
                   else 'in_progress' if jobs else 'not_started')
            kit=self.app.shot_kit.readiness(scene) if scene else dict(ready=False,checks=[],missing=['Scene missing.'])
            items.append(dict(item,kit=dict(ready=kit['ready'],checks=kit['checks'],hints=kit.get('hints',[])),title=scene.get('title'),resolution=body.get('resolution'),duration=body.get('duration'),
                approved_revision=approved_revision,current_revision=scene.get('revision'),takes_used=len(jobs),
                job_ids=[j['id'] for j in jobs],verdicts=verdicts,state=state,estimate_percent_per_take=estimate))
        spent,unmeasured=self._spent(self._jobs(plan['id']),rates)
        plan.update(items=items,approved=current,
            totals=dict(shots=len(items),shots_kept=sum(1 for i in items if i['state']=='kept'),
                takes_used=sum(i['takes_used'] for i in items),max_takes=plan['budget']['max_takes'] or sum(i['max_takes'] for i in items),
                estimate_percent_expected=round(expected,2),estimate_percent_worst_case=round(worst,2),
                shots_without_estimate=unknown_estimates,shots_kit_ready=sum(1 for i in items if i['kit']['ready']),usage_percent_spent=spent,takes_without_usage_figure=unmeasured,
                usage_percent_cap=plan['budget']['usage_percent']),
            estimate_note=('Estimates use the learned cost per second; shots at resolutions still being learned have no estimate yet.'
                           if unknown_estimates else 'Expected assumes one take per shot; worst case uses every allowed take.'))
        return plan

    def list(self):
        with self.app.lock:ids=[p['id'] for p in self.plans]
        return [self.view(i) for i in ids]
