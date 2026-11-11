"""The shot kit: everything Grok needs before a take is generated.

Grok Imagine fails most often when it has to invent too much. A shot kit gives it known
pictures to move between. The agent builds it before generating:

1. 3D staging in Camera Control / Shared Scene Blocking, exported as a reference render
   (start mark, and end mark when the shot has an end state).
2. A first frame made by the image model from that staging plus the character identities,
   approved before use.
3. A last frame, only when the shot has a clear end state, made from the first frame so
   the two stay consistent. Free-flowing motion has no last frame.
4. A middle keyframe, only for complex action (several beats, a turn and a reach, a
   fall), made from the first frame and placed strictly inside the take.
5. A written direction: camera, action, the end state (or "free motion") and whether
   the action is complex.
6. A prompt that validates with no issues, with every named character attached.

The staging render itself must never be sent to the video model as a frame, keyframe or
reference: Grok would animate the mannequins. Plans cannot be approved, and takes cannot
be generated under a plan, until every shot's kit is ready.
"""
import copy
import re
import time

from agent_api import APIError

FIELDS=('camera','action','end_state','free_motion','staging_asset_id','last_frame_from_first','complex_action','middle_frame_from_first')
# Words and shapes that suggest several beats in one shot; used only for a visible hint.
SEQUENCE=re.compile(r'\b(then|after|before|while|until|meanwhile|finally|next|as soon as|turns? and|and then)\b',re.I)


def looks_complex(action):
    if not action:return False
    sentences=[x for x in re.split(r'[.;!?]+',action) if x.strip()]
    return len(sentences)>=3 or bool(SEQUENCE.search(action))


def _frame_id(entry):
    """Asset ID of a scene frame/reference entry, whatever shape it was saved in."""
    if not isinstance(entry,dict):return None
    source=entry.get('source') if isinstance(entry.get('source'),dict) else entry
    return source.get('id') or source.get('asset_id')


class ShotKit:
    def __init__(self, app):
        self.app=app

    def _record(self, scene_id):
        record=next((r for r in self.app.agent.db['scenes'] if r['id']==scene_id),None)
        if not record:raise APIError('not_found','Scene not found.',404)
        return record

    def _asset(self, asset_id):
        try:return self.app.asset(asset_id)[0]
        except (ValueError,KeyError,TypeError):return None

    def _usable(self, asset_id):
        """A frame is usable when it exists and, if generated, has been approved."""
        asset=self._asset(asset_id)
        if not asset:return False,'missing'
        if asset.get('generated') and asset.get('approved') is not True:return False,'not approved'
        return True,None

    # ----- editing -----
    def update(self, scene_id, data):
        if not isinstance(data,dict) or set(data)-set(FIELDS)-{'expected_revision'}:
            raise APIError('invalid_kit','Send expected_revision with '+', '.join(FIELDS)+'.')
        record=self._record(scene_id)
        if data.get('expected_revision')!=record['revision']:raise APIError('revision_conflict','Scene changed. Fetch it before editing its kit.',409)
        kit=dict(record.get('kit') or {})
        for key in ('camera','action','end_state'):
            if key in data:
                value=data[key]
                if value is not None and (not isinstance(value,str) or len(value)>2000):raise APIError('invalid_kit',f'{key} must be text of at most 2,000 characters.')
                kit[key]=(value or '').strip() or None
        for key in ('free_motion','last_frame_from_first','complex_action','middle_frame_from_first'):
            if key in data:
                if type(data[key]) is not bool:raise APIError('invalid_kit',f'{key} must be true or false.')
                kit[key]=data[key]
        if 'staging_asset_id' in data:
            value=data['staging_asset_id']
            if value is not None and not self._asset(value):raise APIError('invalid_kit','staging_asset_id must name an uploaded staging render.')
            kit['staging_asset_id']=value
        if kit.get('end_state') and kit.get('free_motion'):
            raise APIError('invalid_kit','A shot has either an end state or free motion, not both.')
        kit['updated_at']=time.time()
        # The kit is part of the shot, so changing it is a scene revision like any other edit.
        record.update(kit=kit,revision=record['revision']+1,updated_at=time.time())
        self.app.agent.save(self.app.agent.path,self.app.agent.db)
        return self.view(scene_id)

    # ----- readiness -----
    def readiness(self, record):
        kit=record.get('kit') or {};scene=record['scene']
        first=_frame_id(scene.get('first'));last=_frame_id(scene.get('last'))
        staging=kit.get('staging_asset_id')
        refs=[_frame_id(r) for r in scene.get('refs') or []]+[_frame_id(k) for k in scene.get('keys') or []]
        checks=[]
        def check(identity,label,ok,detail=None):checks.append(dict(id=identity,label=label,ok=bool(ok),detail=None if ok else detail))
        check('direction','Direction: camera and action written',kit.get('camera') and kit.get('action'),
              'Write the camera (framing, lens, movement) and the action.')
        check('end_state','End state decided',kit.get('end_state') or kit.get('free_motion'),
              'Say how the shot ends (end_state), or mark it free_motion.')
        check('staging','3D staging render saved',staging and self._asset(staging),
              'Stage the shot in Camera Control / Scene Blocking and save its reference render as staging_asset_id.')
        usable,why=self._usable(first) if first else (False,'missing')
        check('first_frame','First frame attached and approved',usable,
              f'First frame is {why}: generate it from the staging and the character identities, then approve it.')
        if kit.get('end_state'):
            usable,why=self._usable(last) if last else (False,'missing')
            check('last_frame','Last frame attached and approved (shot has an end state)',usable,
                  f'Last frame is {why}: generate the end state from the first frame, then approve it.')
            check('last_from_first','Last frame made from the first frame',kit.get('last_frame_from_first') is True,
                  'Make the last frame by editing the approved first frame, so they stay consistent, and set last_frame_from_first.')
        check('complexity','Complex action decided',isinstance(kit.get('complex_action'),bool),
              'Decide whether the action is complex (several beats, a turn and a reach, a fall): set complex_action true or false.')
        duration=scene.get('duration') or 0
        inside=[k for k in scene.get('keys') or [] if isinstance(k.get('slot'),(int,float)) and 0<k['slot']<duration*3]
        if kit.get('complex_action') is True:
            usable=[k for k in inside if self._usable(_frame_id(k))[0] and _frame_id(k)!=staging]
            check('middle_frame','Middle keyframe attached and approved (complex action)',usable,
                  'Complex action needs a middle keyframe strictly inside the take: generate the key pose from the first frame, approve it and attach it as a keyframe.')
            check('middle_from_first','Middle keyframe made from the first frame',kit.get('middle_frame_from_first') is True,
                  'Make the middle keyframe by editing the approved first frame, so the frames stay consistent, and set middle_frame_from_first.')
        check('no_mockup','Staging render not sent to the video model',not staging or staging not in [first,last,*refs],
              'The 3D staging render is attached as a frame or reference; Grok would animate the mannequins. Use the generated frames instead.')
        try:
            validation=self.app.agent.validation(record)
            issues=[i.get('message','') for i in validation.get('prompt_issues') or []]
            ok=validation.get('valid') and not issues
            detail='; '.join([*(validation.get('errors') or []),*issues])
        except APIError as error:ok,detail=False,str(error)
        check('prompt','Prompt validates with every named character attached',ok,detail or 'Fix the validation errors.')
        missing=[c for c in checks if not c['ok']]
        hints=[]
        if kit.get('complex_action') is False and looks_complex(kit.get('action')):
            hints.append('The action reads as several beats, but complex_action is false: check whether it needs a middle keyframe.')
        return dict(ready=not missing,checks=checks,missing=[c['detail'] for c in missing],hints=hints,
                    has_middle_frame=bool(inside),
                    has_last_frame=bool(last),free_motion=bool(kit.get('free_motion')),has_keyframes=bool(scene.get('keys')))

    def view(self, scene_id):
        record=self._record(scene_id)
        return dict(scene_id=record['id'],revision=record['revision'],kit=copy.deepcopy(record.get('kit') or {}),**self.readiness(record))

    def require_ready(self, record):
        state=self.readiness(record)
        if not state['ready']:
            raise APIError('shot_kit_incomplete',f"Shot “{record.get('title') or record['id']}” is not ready: "+' '.join(state['missing']),409)
        return state

    # ----- does the kit pay off? -----
    def stats(self):
        groups={}
        def add(name,verdict):
            g=groups.setdefault(name,dict(takes=0,keep=0,retry=0,reject=0));g['takes']+=1;g[verdict]+=1
        for job in self.app.records():
            review=job.get('human_review') or {};kit=job.get('kit')
            if review.get('status')!='reviewed' or not kit:continue
            verdict=review['verdict']
            add('complete kit' if kit.get('ready') else 'incomplete kit',verdict)
            add('first and last frames' if kit.get('has_last_frame') else 'first frame only',verdict)
            if kit.get('has_middle_frame'):add('with middle keyframe',verdict)
        for g in groups.values():g['keep_rate']=round(g['keep']/g['takes'],3)
        return dict(groups=groups,note='Keep rate of human verdicts by what the shot kit held when the take was generated.')
