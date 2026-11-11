"""Human-chosen director and reviewer models, and independent AI review of each take.

The human chooses which model directs (runs Studio, writes prompts) and which model
reviews takes, because the model sets the quality of both. Studio cannot start an agent
itself: the agent running Studio starts a *separate* reviewer session on the chosen
model and gives it only the review packet. Studio enforces what it can:

- generation declares the director's model and session; a different model is refused;
- the packet holds the story beat, references, sampled frames and the human's past
  verdicts, never the director's reasoning;
- a review must come from the chosen reviewer model in a different session from the
  director's, must say how many frames it examined, and is refused when malformed;
- code, not the reviewer, turns the scores and issues into a suggestion;
- when a reviewer is configured, a relayed human verdict waits for the AI review
  (or a recorded reason it could not run), so the review cannot be skipped silently;
- every suggestion is compared with the human's verdict to measure agreement.

Model and session names are declared by the caller and cannot be verified, as with
approved=true. They are recorded so the human can see who did what.
"""
import copy
import json
import math
import re
import subprocess
import time

from agent_api import APIError

LENSES=('story','identity','craft','performance')
CATEGORIES=('story','identity','continuity','anatomy','craft','camera','performance','audio','other')
FRAME_COUNT=12
NAME=re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,99}$')

BRIEF='''You are the film director reviewing one generated video take. You did not write its prompt.
Judge the take against the STORY BEAT it must play, not merely against the prompt wording.
Use the contact sheet and frames (times are seconds into the take), the approved references
and the human's past verdicts, which show this person's taste. Their words outrank your preferences.

Score each lens from 0 to 10:
- story: does the take play the beat in the story context?
- identity: characters, wardrobe, props and location match the references and the scene?
- craft: anatomy (hands, faces, limbs), artifacts, camera, composition, light?
- performance: expression, action, eyelines and holds suit the beat?

List each issue with severity "blocking" (the take cannot be used as is: broken anatomy, off-model
character, wrong action, story beat missing, unusable artifacts) or "polish" (better if fixed, usable now),
its category, the time in seconds when visible, the problem and a concrete fix for the next prompt.
Sampled stills cannot prove motion between frames, lip sync or audio: say so instead of guessing.
Report how many frames you actually examined. Return only the JSON described in submit.schema.'''


def _name(value, field):
    if not isinstance(value,str) or not NAME.match(value.strip()):
        raise APIError('invalid_identity',f'{field} must name the model or session (1–100 letters, digits or . _ : / @ + -).')
    return value.strip()


class DirectorReview:
    def __init__(self, app, save_json):
        self.app=app;self.save_json=save_json
        self.path=app.storage/'agent-roles.json'
        self.roles=json.loads(self.path.read_text()) if self.path.exists() else {'director':None,'reviewer':None}

    # ----- roles chosen by the human -----
    def get_roles(self):
        with self.app.lock:return copy.deepcopy(self.roles)

    def set_roles(self, data, *, source):
        allowed={'director','reviewer'}|({'human_words'} if source=='agent_relay' else set())
        if not isinstance(data,dict) or set(data)-allowed or not set(data)&{'director','reviewer'}:
            raise APIError('invalid_roles','Send director and/or reviewer'+(' with human_words.' if source=='agent_relay' else '.'))
        words=None
        if source=='agent_relay':
            words=data.get('human_words')
            if not isinstance(words,str) or not words.strip() or len(words)>2000:
                raise APIError('invalid_roles',"human_words must quote the human's own choice, verbatim (1–2,000 characters).")
        update={}
        for role in ('director','reviewer'):
            if role not in data:continue
            value=data[role]
            if value is None:update[role]=None;continue
            if not isinstance(value,dict) or set(value)-{'model','product'} or 'model' not in value:
                raise APIError('invalid_roles',f'{role} must be {{"model": ..., "product": ...}} or null.')
            update[role]=dict(model=_name(value['model'],f'{role}.model'),
                              product=_name(value.get('product') or 'unspecified',f'{role}.product'))
        with self.app.lock:
            self.roles.update(update)
            self.roles.update(updated_at=time.time(),source=source)
            if words:self.roles['human_words']=words.strip()
            else:self.roles.pop('human_words',None)
            self.save_json(self.path,self.roles)
            return copy.deepcopy(self.roles)

    def check_director(self, agent):
        """Validate the generating agent's declared identity. Returns it, normalised."""
        director=self.get_roles().get('director')
        if agent is None:
            if director:
                raise APIError('director_identity_required',f"Declare agent: {{model, session_id}}. The human chose {director['model']} as director.",403)
            return None
        if not isinstance(agent,dict) or set(agent)-{'model','session_id','product'}:
            raise APIError('invalid_identity','agent must be {"model": ..., "session_id": ..., "product": optional}.')
        identity=dict(model=_name(agent.get('model'),'agent.model'),session_id=_name(agent.get('session_id'),'agent.session_id'))
        if agent.get('product'):identity['product']=_name(agent['product'],'agent.product')
        if director and identity['model']!=director['model']:
            raise APIError('wrong_director_model',f"The human chose {director['model']} to direct, not {identity['model']}. "
                           'Ask the human, or switch to the chosen model.',403)
        return identity

    # ----- frames and the packet -----
    def _job(self, job_id):
        job=next((j for j in self.app.records() if j['id']==job_id),None)
        if not job:raise APIError('not_found','Job not found.',404)
        return job

    def frames(self, job):
        """Sample FRAME_COUNT frames across the take and a labelled contact sheet; cached per job."""
        folder=self.app.storage/'review-frames'/job['id']
        manifest=folder/'frames.json'
        if manifest.exists():return json.loads(manifest.read_text())
        if job.get('status')!='done':return []
        editing=self.app.editing
        if not editing.ffmpeg:raise APIError('ffmpeg_unavailable','FFmpeg is required to sample review frames.',503)
        path=self.app.download(job['id'])
        duration=float(editing.probe(path).get('duration') or 0)
        if duration<=0:raise APIError('review_capture','The take has no readable duration.')
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        times=[round(duration*(i+.5)/FRAME_COUNT,2) for i in range(FRAME_COUNT)]
        frames=[]
        for index,second in enumerate(times):
            out=folder/f'frame-{index:02d}.jpg'
            subprocess.run([editing.ffmpeg,'-v','error','-y','-ss',f'{second:.3f}','-i',str(path),'-frames:v','1',
                            '-vf','scale=960:-2','-q:v','3',str(out)],capture_output=True,check=True,timeout=60)
            if out.exists():frames.append(dict(index=index,time_s=second,file=out.name))
        if frames:self._contact_sheet(folder,frames)
        manifest.write_text(json.dumps(frames))
        return frames

    @staticmethod
    def _contact_sheet(folder, frames):
        from PIL import Image,ImageDraw
        tiles=[Image.open(folder/f['file']).convert('RGB') for f in frames]
        width=480;height=round(tiles[0].height*width/tiles[0].width)
        cols=4;rows=math.ceil(len(tiles)/cols);label=22
        sheet=Image.new('RGB',(cols*width,rows*(height+label)),(12,16,22))
        draw=ImageDraw.Draw(sheet)
        for i,(tile,frame) in enumerate(zip(tiles,frames)):
            x,y=(i%cols)*width,(i//cols)*(height+label)
            sheet.paste(tile.resize((width,height)),(x,y+label))
            draw.text((x+6,y+4),f"#{frame['index']}  {frame['time_s']:.2f}s",fill=(220,230,240))
        sheet.save(folder/'contact-sheet.jpg',quality=88)

    def frame_file(self, job_id, name):
        if not re.fullmatch(r'(frame-\d{2}|contact-sheet)\.jpg',name):raise APIError('not_found','Frame not found.',404)
        job=self._job(job_id);self.frames(job)
        path=self.app.storage/'review-frames'/job['id']/name
        if not path.exists():raise APIError('not_found','Frame not found.',404)
        return path.read_bytes()

    @staticmethod
    def _asset_ids(settings):
        ids=[]
        def take(value):
            if isinstance(value,dict) and isinstance(value.get('asset_id'),str):ids.append(value['asset_id'])
        take(settings.get('image'));take(settings.get('last_frame'))
        for ref in settings.get('reference_images') or []:take(ref)
        for key in settings.get('keyframes') or []:take(key.get('image'))
        return list(dict.fromkeys(ids))

    def packet(self, job_id, *, base=''):
        job=self._job(job_id)
        if job.get('status')=='pending':raise APIError('not_finished','Wait for the take to finish before reviewing it.',409)
        settings=job.get('settings') or {}
        plan_item=None
        if job.get('plan'):
            try:
                view=self.app.plans.view(job['plan']['id'])
                plan_item=next((dict(plan=view['title'],shot=i['label']) for i in view['items'] if i['scene_id']==job['plan']['item']),None)
            except APIError:plan_item=None
        scene=next((r for r in self.app.agent.db['scenes'] if r['id']==(job.get('agent_scene') or {}).get('id')),None)
        frames=self.frames(job) if job.get('status')=='done' else []
        prefix=f'{base}/jobs/{job["id"]}/review-frames/'
        taste=[dict(verdict=r['verdict'],tags=r['tags'],notes=r['notes'],human_words=r.get('human_words'),prompt=r['prompt'])
               for r in self.app.human_reviews()[:20]]
        roles=self.get_roles()
        return dict(job_id=job['id'],job_status=job.get('status'),error=job.get('message') if job.get('status')!='done' else None,
            brief=BRIEF,
            story=dict(plan=plan_item,scene_title=scene.get('title') if scene else None,
                       story_context=settings.get('_studio_story'),requested_prompt=settings.get('prompt',''),
                       duration_s=settings.get('duration'),resolution=settings.get('resolution')),
            references=[dict(asset_id=a,url=f'{base}/assets/{a}') for a in self._asset_ids(settings)],
            frames=[dict(f,url=prefix+f['file']) for f in frames],
            contact_sheet_url=prefix+'contact-sheet.jpg' if frames else None,
            human_taste=taste,past_disagreements=self.agreement()['recent_disagreements'][:10],
            required_reviewer=roles.get('reviewer'),director=job.get('agent_identity'),
            submit=dict(route=f'POST jobs/{job["id"]}/ai-review',schema=dict(
                reviewer={'model':'the chosen reviewer model','session_id':"your own session, not the director's",'product':'optional'},
                scores={k:'0-10' for k in LENSES},issues=[{'severity':'blocking|polish','category':'|'.join(CATEGORIES),
                'time_s':'optional seconds','problem':'what is wrong','fix':'concrete prompt change'}],
                frames_examined='how many frames you looked at (>0)',summary='one or two sentences')))

    # ----- submission and the computed suggestion -----
    @staticmethod
    def suggestion(scores, issues):
        if scores['story']<5:return 'reject'
        if any(i['severity']=='blocking' for i in issues) or min(scores.values())<6:return 'retry'
        return 'keep'

    def _validated(self, data):
        if data.get('unavailable') is True:
            if set(data)-{'unavailable','reason','reviewer'}:raise APIError('invalid_review','An unavailable review sends reason and optional reviewer only.')
            reason=data.get('reason')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise APIError('invalid_review','Say why the review could not run.')
            return dict(status='unavailable',reason=reason.strip(),suggestion=None,submitted_at=time.time())
        if set(data)-{'reviewer','scores','issues','frames_examined','summary'}:
            raise APIError('invalid_review','Send reviewer, scores, issues, frames_examined and summary.')
        reviewer=data.get('reviewer')
        if not isinstance(reviewer,dict) or set(reviewer)-{'model','session_id','product'}:
            raise APIError('invalid_review','reviewer must be {"model", "session_id", "product"?}.')
        reviewer=dict(model=_name(reviewer.get('model'),'reviewer.model'),session_id=_name(reviewer.get('session_id'),'reviewer.session_id'),
                      **({'product':_name(reviewer['product'],'reviewer.product')} if reviewer.get('product') else {}))
        scores=data.get('scores')
        if not isinstance(scores,dict) or set(scores)!=set(LENSES) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<=v<=10 for v in scores.values()):
            raise APIError('invalid_review','scores needs story, identity, craft and performance, each 0–10. A missing score is a failed review, not a pass.')
        issues=data.get('issues')
        if not isinstance(issues,list) or len(issues)>20:raise APIError('invalid_review','issues must be a list of at most 20 items (empty when there are none).')
        clean=[]
        for n,issue in enumerate(issues):
            if not isinstance(issue,dict) or issue.get('severity') not in ('blocking','polish') or issue.get('category') not in CATEGORIES \
                    or not isinstance(issue.get('problem'),str) or not issue['problem'].strip() or not isinstance(issue.get('fix',''),str):
                raise APIError('invalid_review',f'Issue {n+1}: needs severity blocking|polish, a category, a problem and a fix.')
            t=issue.get('time_s')
            if t is not None and (isinstance(t,bool) or not isinstance(t,(int,float)) or t<0):raise APIError('invalid_review',f'Issue {n+1}: time_s must be seconds.')
            clean.append(dict(severity=issue['severity'],category=issue['category'],time_s=t,problem=issue['problem'].strip()[:500],fix=issue.get('fix','').strip()[:500]))
        examined=data.get('frames_examined')
        if type(examined) is not int or examined<1:raise APIError('invalid_review','frames_examined must say how many frames you looked at. A review without frames is a failure.')
        summary=data.get('summary','')
        if not isinstance(summary,str) or len(summary)>1000:raise APIError('invalid_review','summary must be at most 1,000 characters.')
        scores={k:float(scores[k]) for k in LENSES}
        return dict(status='done',reviewer=reviewer,scores=scores,issues=clean,frames_examined=examined,
                    summary=summary.strip(),suggestion=self.suggestion(scores,clean),submitted_at=time.time())

    def submit(self, job_id, data):
        if not isinstance(data,dict):raise APIError('invalid_review','Send a JSON object.')
        record=self._validated(data);roles=self.get_roles()
        with self.app.lock:
            job=next((j for j in self.app.history if j['id']==job_id),None)
            if not job:raise APIError('not_found','Job not found.',404)
            if job.get('status')=='pending':raise APIError('not_finished','Wait for the take to finish.',409)
            if job.get('ai_review'):raise APIError('review_exists','This take already has an AI review.',409)
            if record['status']=='done':
                chosen=roles.get('reviewer')
                if chosen and record['reviewer']['model']!=chosen['model']:
                    raise APIError('wrong_reviewer_model',f"The human chose {chosen['model']} to review, not {record['reviewer']['model']}.",403)
                director=job.get('agent_identity') or {}
                if director.get('session_id') and director['session_id']==record['reviewer']['session_id']:
                    raise APIError('reviewer_not_independent','The reviewer must run in a new session, separate from the director that generated this take.',403)
            job['ai_review']=record
            self.app.save_history()
            return copy.deepcopy(job)

    def required_before_verdict(self, job):
        """When the human chose a reviewer, a relayed verdict on an agent take waits for the AI review."""
        # Called while the caller holds app.lock, which is not re-entrant: read without locking.
        return bool(self.roles.get('reviewer')) and bool(job.get('agent_key')) and not job.get('ai_review')

    # ----- agreement between the reviewer and the human -----
    def agreement(self):
        rows=[]
        for job in self.app.records():
            ai=job.get('ai_review') or {};human=job.get('human_review') or {}
            if ai.get('status')=='done' and human.get('status')=='reviewed':
                rows.append(dict(job_id=job['id'],ai=ai['suggestion'],human=human['verdict'],reviewer_model=ai['reviewer']['model'],
                                 scores=ai['scores'],human_words=human.get('human_words') or human.get('notes'),at=human.get('reviewed_at') or 0))
        rows.sort(key=lambda r:r['at'],reverse=True)
        agreed=sum(1 for r in rows if r['ai']==r['human'])
        by_model={}
        for r in rows:
            m=by_model.setdefault(r['reviewer_model'],dict(compared=0,agreed=0));m['compared']+=1;m['agreed']+=int(r['ai']==r['human'])
        return dict(compared=len(rows),agreed=agreed,agreement_rate=round(agreed/len(rows),3) if rows else None,
                    ai_stricter=sum(1 for r in rows if r['ai']!='keep' and r['human']=='keep'),
                    ai_looser=sum(1 for r in rows if r['ai']=='keep' and r['human']!='keep'),by_reviewer_model=by_model,
                    recent_disagreements=[dict(job_id=r['job_id'],ai=r['ai'],human=r['human'],human_words=r['human_words'],scores=r['scores'])
                                          for r in rows if r['ai']!=r['human']][:20])
