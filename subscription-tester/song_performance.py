"""Song-clock planning and review, sharing Studio's records, drafts and editing engine.

No method in this module submits a generation request or changes candidate approval.
"""
import copy
from fractions import Fraction
import hashlib
import json
import math
import re
import subprocess
import threading
import uuid

from agent_api import APIError
from song_analysis import VERSION, digest, measure
from video_rules import MODEL_CAPABILITIES, MODELS

MODES = ('singing','dance_only','cutaway')
KINDS = ('song-project','song-analysis','song-analysis-job','song-shot','song-review','song-assembly','song-comparison')
DENIAL = 'Caller-supplied URLs in reference_audios are not enabled for this team.'


def uid():
    return uuid.uuid4().hex


def finite(value, low=0, high=3600):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise APIError('invalid_song_time',f'Use a finite time between {low} and {high}.')
    return value


def text(value, maximum=4000):
    if not isinstance(value,str) or len(value)>maximum:
        raise APIError('invalid_song_text',f'Use text up to {maximum} characters.')
    return value


def fields(data, allowed, required=()):
    if not isinstance(data,dict) or set(data)-set(allowed) or set(required)-set(data):
        raise APIError('invalid_song_request','Use the documented fields: '+', '.join(sorted(allowed)))
    for name,value in data.items():
        if name.startswith('expected_') and name.endswith('revision') and (type(value) is not int or value<1):
            raise APIError('invalid_song_revision','Expected revisions must be positive integers.')


def frame(value, fps):
    # Round ties upward explicitly. Fractions avoid cumulative binary float rounding.
    x=Fraction(str(value))*fps
    return (x.numerator*2+x.denominator)//(2*x.denominator)


def song_time(review, clip):
    return review['song_anchor']+(clip-review['clip_anchor'])


class SongPerformance:
    def __init__(self, app):
        self.app=app; self.p=app.productions; self.e=app.editing
        self.events={}
        with self.p.sql:
            for job in self.p.all('song-analysis-job'):
                if job['status'] in ('queued','running'):
                    job.update(status='error',error='Server restarted; start a new local analysis.',revision=job['revision']+1)
                    self.p.put('song-analysis-job',job)

    def schema(self):
        return dict(schema_version=1,modes=list(MODES),clock='Half-open [start,end), seconds on immutable master; sample indices retained. Picture quantization: nearest frame, ties upward.',
            defaults=dict(model=MODELS[0],resolution='480p'),models=copy.deepcopy(MODEL_CAPABILITIES),
            interior_anchor_grid=dict(numerator=1,denominator=3),duration_seconds=dict(minimum=1,maximum=15,integer=True),
            local_analysis=dict(available=bool(self.e.ffmpeg and self.e.ffprobe),tool_version=VERSION,
                transcription=self.e.transcription_settings(),forced_alignment=False,manual_cues=True),
            recording_generation=dict(enabled=False,access='denied',http_status=403,evidence=DENIAL),
            singing='Preset generated singing is an attempt; precise mouth synchronization remains unverified.',
            routes=['schema','projects','projects/{id}','projects/{id}/analyze','analysis-jobs/{id}',
                'analysis-jobs/{id}/cancel','analysis-jobs/{id}/apply','projects/{id}/shots','shots/{id}',
                'shots/{id}/prepare','shots/{id}/apply-draft','shots/{id}/take-reviews',
                'shots/{id}/take-reviews/{review_id}','shots/{id}/comparisons','comparisons/{id}',
                'projects/{id}/assemble'])

    def metadata(self, source, audio=False, video=False):
        fields(source,('kind','id'),('kind','id'))
        if source['kind'] not in ('upload','take'):
            raise APIError('invalid_song_source','Use private uploaded audio/video or a completed workspace take.')
        m,path=self.e.source(source)
        if audio and not m.get('audio') or video and not m.get('video'):
            raise APIError('invalid_song_source','Choose media containing the required audio/video stream.')
        try:
            result=subprocess.run([self.e.ffprobe,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=25,check=True)
            info=json.loads(result.stdout)
            a=next((s for s in info['streams'] if s['codec_type']=='audio'),{})
            v=next((s for s in info['streams'] if s['codec_type']=='video'),{})
            rate=int(a.get('sample_rate',48000))
            exact=Fraction(a.get('duration_ts','0'))*Fraction(a.get('time_base','1/48000')) if a.get('duration_ts') else Fraction(str(info['format']['duration']))
            duration=float(Fraction(v.get('duration',info['format']['duration']))) if video else float(exact)
            return dict(source=copy.deepcopy(source),media_id=source['id'],sha256=digest(path),duration=duration,
                sample_rate=rate,channels=int(a.get('channels',0)),samples=round(exact*rate),
                width=v.get('width'),height=v.get('height'),fps=v.get('avg_frame_rate'),frames=v.get('nb_frames'),
                provenance='workspace-private-media'),path
        except (subprocess.SubprocessError,OSError,KeyError,ValueError,TypeError):
            raise APIError('invalid_song_source','The private source could not be inspected.') from None

    def scope(self,data):
        production=self.p.get(data.get('production_id'),'production')
        episode=data.get('episode_id'); scene=data.get('story_scene_id')
        if production['kind']=='story':
            ep=self.p.episode(production,episode)
            if scene and not any(s['id']==scene for s in ep['scenes']):
                raise APIError('invalid_parent','Choose a script scene in this episode.')
        elif episode or scene:
            raise APIError('invalid_parent','Quick productions have no episode/script scene.')
        return dict(production_id=production['id'],episode_id=episode,story_scene_id=scene)

    def sources(self,data):
        master,_=self.metadata(data['master'],audio=True)
        stems=data.get('stems',{})
        fields(stems,('lead_vocal','instrumental','drums'))
        return master,{role:{**self.metadata(source,audio=True)[0],'role':role} for role,source in stems.items()}

    def create(self,data):
        fields(data,('title','production_id','episode_id','story_scene_id','master','stems','lyrics'),('title','production_id','master'))
        scope=self.scope(data); master,stems=self.sources(data)
        title=text(data['title'],120).strip()
        if not title:raise APIError('invalid_song_text','Name the song project.')
        with self.p.sql:
            return self.p.new('song-project',schema_version=1,**scope,title=title,master=master,stems=stems,
                master_version=1,lyrics=text(data.get('lyrics',''),50000),analysis_id=None,analysis_revision=0,
                cue_revision=1,cues=[],stem_alignment={},working_timeline_id=None,archived=False)

    def project(self,identity):
        p=self.p.get(identity,'song-project')
        shots=[self.shot_view(s,p) for s in self.p.all('song-shot') if s['song_project_id']==identity]
        analysis=self.p.get(p['analysis_id'],'song-analysis') if p.get('analysis_id') else None
        jobs=[{k:j.get(k) for k in ('id','revision','status','progress','error','analysis_id','created_at')} for j in self.p.all('song-analysis-job') if j['song_project_id']==identity]
        return {**p,'shots':shots,'analysis_jobs':jobs,'analysis':{**analysis,'stale':analysis['master_version']!=p['master_version'] or analysis['lyrics']!=p['lyrics']} if analysis else None}

    def cues(self,cues,p):
        if not isinstance(cues,list) or len(cues)>10000:raise APIError('invalid_song_cues','Use at most 10000 cues.')
        result=[]; ids=set(); rate=p['master']['sample_rate']
        for c in cues:
            fields(c,('id','kind','start','end','text','method','source','confidence','review_state','uncertainty_s'),('kind','start','end'))
            identity=c.get('id',uid())
            if not isinstance(identity,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',identity) or identity in ids:raise APIError('invalid_song_cues','Cue IDs must be unique.')
            ids.add(identity)
            a=finite(c['start'],0,p['master']['duration']);b=finite(c['end'],0,p['master']['duration'])
            if b<=a:raise APIError('invalid_song_cues','Cue end must be after its start.')
            if c['kind'] not in ('word','phrase','beat','bar','section','vocal_activity','music_activity','instrumental_gap'):raise APIError('invalid_song_cues','Choose a documented cue kind.')
            if c.get('review_state','reviewed') not in ('suggested','reviewed','rejected'):raise APIError('invalid_song_cues','Choose suggested, reviewed or rejected.')
            item={**copy.deepcopy(c),'id':identity,'start':round(a*rate)/rate,'end':round(b*rate)/rate,
                'text':text(c.get('text',''),2000),'method':text(c.get('method','manual'),120),
                'source':text(c.get('source','human'),120),'review_state':c.get('review_state','reviewed')}
            if item['end']<=item['start']:raise APIError('invalid_song_cues','A cue must span at least one master sample.')
            if c.get('confidence') is not None:finite(c['confidence'],0,1)
            if c.get('uncertainty_s') is not None:finite(c['uncertainty_s'],0,3600)
            result.append(item)
        return result

    def patch_project(self,identity,data):
        fields(data,('expected_revision','title','lyrics','master','stems','cues','stem_alignment','archived'),('expected_revision',))
        old=self.p.get(identity,'song-project'); self.p.check(old,data); p=copy.deepcopy(old)
        if 'title' in data:
            p['title']=text(data['title'],120).strip()
            if not p['title']:raise APIError('invalid_song_text','Name the project.')
        if 'lyrics' in data:
            p['lyrics']=text(data['lyrics'],50000)
            if p['lyrics']!=old['lyrics']:p['cue_revision']+=1
        if 'master' in data or 'stems' in data:
            master,stems=self.sources(dict(master=data.get('master',old['master']['source']),
                stems=data.get('stems',{k:v['source'] for k,v in old['stems'].items()})))
            if master!=old['master'] or stems!=old['stems']:
                p.update(master=master,stems=stems,master_version=old['master_version']+1,
                    analysis_id=None,analysis_revision=old['analysis_revision']+1,cues=[],
                    cue_revision=old['cue_revision']+1,stem_alignment={},working_timeline_id=None)
        if 'cues' in data:p.update(cues=self.cues(data['cues'],p),cue_revision=p['cue_revision']+1)
        if 'stem_alignment' in data:
            findings=data['stem_alignment'];fields(findings,tuple(p['stems']))
            for role, finding in findings.items():
                fields(finding,('status','human_correction_s','note'),('status','human_correction_s'))
                if finding['status'] not in ('verified','rejected','needs_review'):raise APIError('invalid_alignment','Choose a documented status.')
                finite(finding['human_correction_s'],-3600,3600);text(finding.get('note',''),2000)
            p['stem_alignment']={**p['stem_alignment'],**{role:{**p['stem_alignment'].get(role,{}),**copy.deepcopy(finding)} for role,finding in findings.items()}}
        if 'archived' in data:
            if type(data['archived']) is not bool:raise APIError('invalid_song_request','archived must be boolean.')
            p['archived']=data['archived']
        p['revision']+=1
        with self.p.sql:self.p.put('song-project',p)
        return self.project(identity)

    def fingerprint(self,data):
        return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

    def replay(self,kind,key,data):
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):
            raise APIError('idempotency_key_required','Use an Idempotency-Key of 8–100 letters, digits, underscores or hyphens.')
        old=next((j for j in self.p.all(kind) if j.get('key')==key),None)
        if old and old['fingerprint']!=self.fingerprint(data):raise APIError('idempotency_conflict','This key belongs to different frozen inputs.',409)
        return old

    def analyze(self,identity,data,key):
        fields(data,('expected_revision',),('expected_revision',))
        payload=dict(project_id=identity,**data)
        previous=self.replay('song-analysis-job',key,payload)
        if previous:return previous
        p=self.p.get(identity,'song-project');self.p.check(p,data)
        if not self.e.ffmpeg:raise APIError('analysis_unavailable','Install FFmpeg or enter cues manually.',503)
        snapshot=copy.deepcopy(p)
        with self.p.sql:
            job=self.p.new('song-analysis-job',song_project_id=identity,key=key,fingerprint=self.fingerprint(payload),
                snapshot=snapshot,status='queued',progress=0,error=None,analysis_id=None)
        self.events[job['id']]=threading.Event();self.app.spawn(self.analysis_worker,job['id'])
        return job

    def job_update(self,identity,**updates):
        with self.app.agent.lock,self.p.sql:
            j=self.p.get(identity,'song-analysis-job');j.update(updates,revision=j['revision']+1)
            return self.p.put('song-analysis-job',j)

    def analysis_worker(self,identity):
        try:
            job=self.p.get(identity,'song-analysis-job');p=job['snapshot'];cancel=self.events[identity].is_set
            self.job_update(identity,status='running',progress=.05)
            _,master=self.e.source(p['master']['source'])
            if digest(master)!=p['master']['sha256']:raise ValueError('Master source changed.')
            paths={}
            for role,m in p['stems'].items():
                _,path=self.e.source(m['source'])
                if digest(path)!=m['sha256']:raise ValueError('Stem source changed.')
                paths[role]=path
            from importlib.metadata import version,PackageNotFoundError
            try:engine_version=version('faster-whisper')
            except PackageNotFoundError:engine_version=None
            cache_key=self.fingerprint(dict(master=p['master']['sha256'],stems={k:v['sha256'] for k,v in p['stems'].items()},version=VERSION,
                lyrics=p['lyrics'],engine_version=engine_version,recognizer_version=2,stem_alignment=p['stem_alignment'],transcription=self.e.transcription_settings()))
            cached=next((r for r in self.p.all('song-analysis') if r.get('cache_key')==cache_key),None)
            result=copy.deepcopy(cached['result']) if cached else measure(self.e.ffmpeg,master,paths,p['master']['duration'],cancel,p['stem_alignment'])
            if not cached:self.recognize(result,master,cancel)
            if cancel():raise InterruptedError()
            # Atomic final publication. Suggested analysis never mutates reviewed cues.
            with self.app.agent.lock,self.p.sql:
                if cancel():raise InterruptedError()
                a=self.p.new('song-analysis',song_project_id=p['id'],cache_key=cache_key,master_sha256=p['master']['sha256'],
                    master_version=p['master_version'],project_revision=p['revision'],cue_revision=p['cue_revision'],
                    lyrics=p['lyrics'],result=result)
                self.job_update(identity,status='done',progress=1,analysis_id=a['id'])
        except InterruptedError:self.job_update(identity,status='cancelled',error=None)
        except Exception:
            self.job_update(identity,status='error',error='Local analysis failed. Sources and reviewed cues are intact; manual timing remains available.')

    def recognize(self,result,path,cancel):
        if not self.e.transcriber_available():
            result['notes'].append('Local transcription unavailable. Add words/phrases manually; no models downloaded.')
            return
        try:
            if callable(getattr(self.e,'transcriber',None)):
                segments=self.e.transcriber(path)
            else:
                from faster_whisper import WhisperModel
                engine=WhisperModel(str(self.e.transcription_model()),device='cpu',compute_type='int8',local_files_only=True)
                segments,_=engine.transcribe(str(path),word_timestamps=True)
            skipped=0
            for seg in segments:
                if cancel():raise InterruptedError()
                get=lambda x,k,default=None:x.get(k,default) if isinstance(x,dict) else getattr(x,k,default)
                words=get(seg,'words',[]) or []
                for word in words:
                    start,end=float(get(word,'start')),float(get(word,'end'))
                    if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:
                        skipped+=1
                        continue
                    result['cues'].append(dict(id=uid(),kind='word',start=start,end=end,
                        text=get(word,'word',''),method='local-ASR-approximate',source='recognized_words',
                        confidence=get(word,'probability'),uncertainty_s=None,review_state='suggested'))
            result['notes'].append('Recognized words are separate from supplied literal lyrics; ASR is approximate, not forced alignment.')
            if skipped:result['notes'].append(f'Skipped {skipped} recognized words with invalid timing; review literal lyrics for omissions.')
        except InterruptedError:raise
        except Exception:result['notes'].append('Local transcription failed; manual word timing remains available.')

    def apply_analysis(self,identity,data):
        fields(data,('expected_revision','expected_project_revision'),('expected_revision','expected_project_revision'))
        job=self.p.get(identity,'song-analysis-job');self.p.check(job,data)
        p=self.p.get(job['song_project_id'],'song-project');self.p.check(p,dict(expected_revision=data['expected_project_revision']))
        if job['status']!='done':raise APIError('analysis_not_ready','Only a completed local analysis can be applied.',409)
        a=self.p.get(job['analysis_id'],'song-analysis')
        if a['master_version']!=p['master_version'] or a['lyrics']!=p['lyrics']:raise APIError('stale_analysis','Song inputs changed. Start a new analysis.',409)
        # Preserve reviewed/rejected layers. Reanalysis replaces only machine suggestions.
        human=[c for c in p['cues'] if c.get('review_state')!='suggested' or c.get('source')=='human']
        claimed={c['id'] for c in human}
        cues=human+[c for c in a['result']['cues'] if c['id'] not in claimed]
        p.update(cues=self.cues(cues,p),analysis_id=a['id'],analysis_revision=p['analysis_revision']+1,
            cue_revision=p['cue_revision']+1,revision=p['revision']+1)
        for role,finding in a['result']['stem_alignment'].items():
            if p['stem_alignment'].get(role,{}).get('status') not in ('verified','rejected'):p['stem_alignment'][role]=finding
        with self.p.sql:self.p.put('song-project',p)
        return self.project(p['id'])

    def cue_basis(self,p,s):
        relevant=[c for c in p['cues'] if c['id'] in s['cue_ids'] or (c['start']<s['end'] and c['end']>s['start'])]
        values=[{k:v for k,v in cue.items() if k!='id'} for cue in relevant]
        return self.fingerprint(dict(lyrics=p['lyrics'] if s['mode']=='singing' else None,cues=sorted(values,key=lambda c:json.dumps(c,sort_keys=True))))

    def shot_view_stale(self,s,p):
        return s['master_version']!=p['master_version'] or s.get('cue_basis')!=self.cue_basis(p,s)

    def shot_view(self,s,p=None):
        p=p or self.p.get(s['song_project_id'],'song-project')
        return {**s,'stale':self.shot_view_stale(s,p),
            'reviews':[self.review_view(r,s,p) for r in self.p.all('song-review') if r['song_shot_id']==s['id']]}

    def shot_values(self,p,data,old=None):
        defaults=dict(title='Performance shot',order=0,start=0,end=min(3,p['master']['duration']),mode='cutaway',
            story_beat='',lyric_text='',cue_ids=[],choreography='',camera='',holds='',duration=3,leading_handle=0,trailing_handle=0,
            production_shot_id=None,draft_id=None,reference_handles=[],first=None,last=None,poses=[],prompt='',resolution='480p',model=MODELS[0])
        allowed=set(defaults)
        fields(data,allowed)
        s={**defaults,**({k:v for k,v in old.items() if k in allowed} if old else {}),**copy.deepcopy(data)}
        for name,limit in [('title',120),('story_beat',4000),('lyric_text',4000),('choreography',4000),('camera',4000),('holds',4000),('prompt',50000)]:text(s[name],limit)
        if not s['title'].strip():raise APIError('invalid_song_shot','Name the musical shot.')
        finite(s['start'],0,p['master']['duration']);finite(s['end'],0,p['master']['duration'])
        if s['end']<=s['start'] or s['mode'] not in MODES:raise APIError('invalid_song_shot','Choose a mode and positive song interval.')
        if type(s['duration']) is not int or not 1<=s['duration']<=15:raise APIError('invalid_song_shot','Generation length must be 1–15 integer seconds.')
        finite(s['leading_handle'],0,15);finite(s['trailing_handle'],0,15)
        if s['end']-s['start']+s['leading_handle']+s['trailing_handle']>s['duration']+1e-8:raise APIError('invalid_song_shot','Song interval and explicit handles exceed generation length.')
        if type(s['order']) is not int or not 0<=s['order']<=10000:raise APIError('invalid_song_shot','Order must be a nonnegative integer.')
        for name in ('cue_ids','reference_handles'):
            if not isinstance(s[name],list) or len(s[name])>100 or any(not isinstance(x,str) for x in s[name]):raise APIError('invalid_song_shot','Use lists of IDs/handles.')
        if any(x not in {c['id'] for c in p['cues']} for x in s['cue_ids']):raise APIError('invalid_song_shot','A linked cue is missing.')
        if s['production_shot_id']:
            linked=self.p.get(s['production_shot_id'],'shot')
            if any(linked.get(k)!=p.get(k) for k in ('production_id','episode_id')) or (p.get('story_scene_id') and linked.get('story_scene_id')!=p['story_scene_id']):raise APIError('invalid_parent','Choose a production shot in the song scope.')
            if s['draft_id'] and s['draft_id']!=linked['video_id']:raise APIError('invalid_parent','Draft does not belong to the linked shot.')
            s['draft_id']=linked['video_id']
        if s['draft_id']:
            self.app.agent.record(s['draft_id'])
            links=[r for r in self.p.all('shot') if r.get('video_id')==s['draft_id']]
            if any(any(r.get(k)!=p.get(k) for k in ('production_id','episode_id')) or (p.get('story_scene_id') and r.get('story_scene_id')!=p['story_scene_id']) for r in links):raise APIError('invalid_parent','Draft belongs to another production scope.')
        for name in ('first','last'):
            if s[name] is not None:s[name]=self.asset_source(s[name])
        if not isinstance(s['poses'],list) or len(s['poses'])>4:raise APIError('invalid_pose','Use up to four interior poses.')
        slots=set()
        for pose in s['poses']:
            fields(pose,('song_time','asset_id','purpose'),('song_time','asset_id','purpose'))
            finite(pose['song_time'],s['start']-s['leading_handle'],s['start']+s['duration']-s['leading_handle'])
            local=Fraction(str(pose['song_time']))-Fraction(str(s['start']))+Fraction(str(s['leading_handle']))
            slot=frame(float(local),3)
            if slot<=0 or slot>=s['duration']*3 or slot in slots:raise APIError('pose_collision','Interior poses must snap to distinct third-second slots strictly inside the clip.')
            slots.add(slot);self.asset_source({'asset_id':pose['asset_id']});text(pose['purpose'],1000)
        if s['model'] not in MODELS or s['resolution'] not in ('480p','720p','1080p'):raise APIError('unsupported_inputs','Choose a supported model and resolution.')
        return s

    def asset_source(self,source):
        fields(source,('asset_id',),('asset_id',))
        asset,_=self.app.asset(source['asset_id'])
        from candidate_review import available
        available(asset)
        if asset.get('generated') and not asset.get('approved'):raise APIError('image_not_approved','Approve the pose/frame candidate before attaching it.')
        return copy.deepcopy(source)

    def create_shot(self,identity,data):
        fields(data,('expected_revision','shot'),('expected_revision','shot'))
        p=self.p.get(identity,'song-project');self.p.check(p,data)
        s=self.shot_values(p,data['shot'])
        with self.p.sql:
            s=self.p.new('song-shot',song_project_id=identity,master_version=p['master_version'],cue_revision=p['cue_revision'],cue_basis=self.cue_basis(p,s),**s)
            p['revision']+=1;self.p.put('song-project',p)
        return self.shot_view(s,p)

    def patch_shot(self,identity,data):
        fields(data,('expected_revision','expected_project_revision','changes'),('expected_revision','expected_project_revision','changes'))
        old=self.p.get(identity,'song-shot');self.p.check(old,data)
        p=self.p.get(old['song_project_id'],'song-project');self.p.check(p,dict(expected_revision=data['expected_project_revision']))
        s={**old,**self.shot_values(p,data['changes'],old), 'master_version':p['master_version'],'cue_revision':p['cue_revision'],'revision':old['revision']+1}
        s['cue_basis']=self.cue_basis(p,s)
        if old.get('preparation'):
            s['preparation']={**old['preparation'],'stale':True}
        with self.p.sql:
            self.p.put('song-shot',s);p['revision']+=1;self.p.put('song-project',p)
        return self.shot_view(s,p)

    def fresh(self,s,p):
        if self.shot_view_stale(s,p):raise APIError('stale_plan','The master/cues changed. Review and save this plan before using it.',409)

    def prepare(self,identity,data):
        fields(data,('expected_revision','expected_project_revision','expected_draft_revision'),('expected_revision','expected_project_revision'))
        s=self.p.get(identity,'song-shot');self.p.check(s,data)
        p=self.p.get(s['song_project_id'],'song-project');self.p.check(p,dict(expected_revision=data['expected_project_revision']));self.fresh(s,p)
        draft=self.app.agent.record(s['draft_id']) if s.get('draft_id') else None
        if draft:self.p.check(draft,dict(expected_revision=data.get('expected_draft_revision')))
        scene=copy.deepcopy(draft['scene']) if draft else self.app.agent.normalize({})
        if scene.get('recording'):raise APIError('restricted_recording','Remove the draft recording attachment explicitly. This workspace never sends custom audio.')
        before=copy.deepcopy(scene)
        scene.update(model=s['model'],duration=s['duration'],resolution=s['resolution'],audio=s['mode']=='singing')
        scene=self.app.agent.attach(scene,s['reference_handles'])
        scene['first']=self.app.agent.source(s['first']) if s['first'] else scene['first']
        scene['last']=self.app.agent.source(s['last']) if s['last'] else scene['last']
        if s['poses']:
            scene['keys']=[dict(id=uid(),slot=frame(pose['song_time']-s['start']+s['leading_handle'],3),source=self.app.agent.source({'asset_id':pose['asset_id']})) for pose in s['poses']]
        if s['mode']=='singing':
            if not s['lyric_text'].strip():raise APIError('lyrics_required','Select one short literal lyric phrase for a singing shot.')
            if not scene['voices']:scene['voices']=[dict(id=uid(),voice='ursa')]
            direction='Generated singing attempt. Sing exactly '+json.dumps(s['lyric_text'],ensure_ascii=False)+'. Keep the face unobstructed, movement modest, and use one clear gesture.'
        elif s['mode']=='dance_only':
            direction='Dance with simple repeated physical motion. Keep the mouth closed or in a closed-mouth smile throughout.'
        else:direction='Story-relevant coverage. Keep visible mouths closed. Show the intended action and preserve continuity.'
        # A human prompt is authoritative. Deterministic mode direction is a visible proposal.
        prior=s.get('preparation') or {}
        inherited=scene['prompt'] if draft and scene['prompt']!=prior.get('applied_prompt') else ''
        scene['prompt']=s['prompt'] or inherited or '\n'.join(x for x in (direction,s['story_beat'],s['choreography'],s['camera'],s['holds']) if x)
        if inherited and not s['prompt']:self.app.agent.retag(before,scene)
        from media_prompting import validate_tags
        validate_tags(scene['prompt'],scene)
        body=self.app.agent.compile(scene) # Full expansion and supported-input validation, no generation.
        resolved=self.app.resolve(body)
        return dict(scene=scene,request=resolved,shot_revision=s['revision'],project_revision=p['revision'],
            draft_revision=draft['revision'] if draft else None,analysis_revision=p['analysis_revision'],cue_revision=p['cue_revision'],
            song_anchor=s['start'],clip_anchor=s['leading_handle'],
            anchors=[dict(**pose,proposed_clip_time=pose['song_time']-s['start']+s['leading_handle'],
                snapped_clip_time=frame(pose['song_time']-s['start']+s['leading_handle'],3)/3) for pose in s['poses']],
            note='Prepared locally. Review the expanded request; applying does not authorize generation or approve takes.')

    def apply_draft(self,identity,data):
        fields(data,('expected_revision','expected_project_revision','expected_draft_revision','preparation'),('expected_revision','expected_project_revision','preparation'))
        s=self.p.get(identity,'song-shot');self.p.check(s,data)
        proposal=self.prepare(identity,{k:v for k,v in data.items() if k!='preparation'})
        # Compare stable preparation; randomly created input IDs are reconciled below.
        provided=data['preparation']
        if not isinstance(provided,dict) or any(provided.get(k)!=proposal[k] for k in ('shot_revision','project_revision','draft_revision','analysis_revision','cue_revision')):
            raise APIError('stale_preparation','Review the current local proposal before applying.',409)
        candidate=provided.get('scene')
        # Validate shape before walking untrusted nested inputs.
        self.app.agent.normalize(candidate)
        # Verify exact submitted scene against deterministic preparation ignoring internal new IDs.
        def semantic(scene):
            value=copy.deepcopy(scene)
            for kind in ('voices','keys','refs'):
                for item in value.get(kind,[]):item.pop('id',None)
            for item in value.get('named',[]):item.pop('refIds',None);item.pop('voiceId',None)
            return value
        if semantic(candidate)!=semantic(proposal['scene']):raise APIError('stale_preparation','Prepared inputs differ. Prepare again before applying.',409)
        self.app.agent.compile(candidate)
        with self.p.mutation():
            if not s['draft_id']:
                p=self.p.get(s['song_project_id'],'song-project')
                production=self.p.get(p['production_id'],'production')
                if production['kind']=='story' and not p['story_scene_id']:
                    raise APIError('missing_scene','Link an existing production shot or create the song project in a selected script scene.')
                linked=self.p.create_shot(production,dict(title=s['title'],episode_id=p['episode_id'],story_scene_id=p['story_scene_id']))
                s.update(production_shot_id=linked['id'],draft_id=linked['video_id'])
                draft=self.app.agent.record(s['draft_id'])
            else:draft=self.app.agent.record(s['draft_id'])
            draft=self.app.agent.edit(draft['id'],dict(expected_revision=draft['revision'],scene=candidate))
            s.update(revision=s['revision']+1,preparation=dict(shot_revision=s['revision'],draft_revision=draft['revision'],
                analysis_revision=proposal['analysis_revision'],cue_revision=proposal['cue_revision'],master_version=s['master_version'],method='deterministic-reviewed-proposal',applied_prompt=candidate['prompt']))
            self.p.put('song-shot',s)
        return dict(shot=self.shot_view(s),draft=draft,validation=self.app.agent.validation(draft))

    def review_view(self,r,s=None,p=None):
        s=s or self.p.get(r['song_shot_id'],'song-shot');p=p or self.p.get(s['song_project_id'],'song-project')
        return {**r,'stale':r['master_sha256']!=p['master']['sha256'] or r['master_version']!=p['master_version'] or r['plan_revision']!=s['revision'] or self.shot_view_stale(s,p),
            'lip_sync_approved':False,'comparisons':[{k:c.get(k) for k in ('id','review_revision','clip_start','song_start','export_id')} for c in self.p.all('song-comparison') if c['review_id']==r['id']]}

    def create_review(self,identity,data):
        fields(data,('expected_revision','source'),('expected_revision','source'))
        s=self.p.get(identity,'song-shot');self.p.check(s,data);p=self.p.get(s['song_project_id'],'song-project');self.fresh(s,p)
        metadata,_=self.metadata(data['source'],video=True)
        evidence=dict(kind='imported-fixture-or-user-media')
        if data['source']['kind']=='take':
            job=self.e.take_record(data['source']['id']);settings=job.get('settings',{})
            if s['draft_id'] and settings.get('_studio_video_id')!=s['draft_id'] and job.get('draft_id')!=s['draft_id']:raise APIError('invalid_parent','Choose a take belonging to the linked draft, or explicitly import a saved fixture.')
            submission=self.app.video_review._read_snapshot(job,uid()) if job.get('request_snapshot') else {}
            evidence=dict(job_id=job['id'],draft_id=settings.get('_studio_video_id'),draft_revision=submission.get('scene_revision'),
                request_snapshot=copy.deepcopy(job.get('request_snapshot')),evidence_source='immutable_submission' if submission else 'saved_settings_only',
                settings_sha256=self.fingerprint(settings),request_id=job.get('request_id'))
        with self.p.sql:
            r=self.p.new('song-review',song_project_id=p['id'],song_shot_id=identity,plan_revision=s['revision'],
                master_version=p['master_version'],master_sha256=p['master']['sha256'],analysis_id=p['analysis_id'],analysis_revision=p['analysis_revision'],cue_revision=p['cue_revision'],
                source_metadata=metadata,generation_evidence=evidence,song_anchor=s['start'],clip_anchor=s['leading_handle'],intervals=[],
                reviewer='',method='unassessed',notes='')
        return self.review_view(r,s,p)

    def get_review(self,shot_id,identity):
        r=self.p.get(identity,'song-review')
        if r['song_shot_id']!=shot_id:raise APIError('not_found','Review not found for this shot.',404)
        return r

    def patch_review(self,shot_id,identity,data):
        fields(data,('expected_revision','song_anchor','clip_anchor','intervals','reviewer','method','notes'),('expected_revision',))
        r=self.get_review(shot_id,identity);self.p.check(r,data)
        s=self.p.get(shot_id,'song-shot');p=self.p.get(s['song_project_id'],'song-project')
        if self.review_view(r,s,p)['stale']:raise APIError('stale_review','Create a new association for the changed plan/master. Historical review is preserved.',409)
        for k in ('song_anchor','clip_anchor'):
            if k in data:r[k]=finite(data[k],0,p['master']['duration'] if k=='song_anchor' else r['source_metadata']['duration'])
        for k,limit in (('reviewer',200),('notes',4000)):
            if k in data:r[k]=text(data[k],limit)
        if 'method' in data:
            if data['method'] not in ('unassessed','automated','sampled_frames','human_continuous_playback'):raise APIError('invalid_review','Choose explicit assessment provenance.')
            r['method']=data['method']
        if 'intervals' in data:
            if not isinstance(data['intervals'],list) or len(data['intervals'])>1000:raise APIError('invalid_review','Use at most 1000 source-local intervals.')
            if any(not isinstance(i,dict) for i in data['intervals']):raise APIError('invalid_review','Intervals must be objects.')
            end=0
            for i in sorted(data['intervals'],key=lambda i:i.get('start',0)):
                fields(i,('start','end','state','reason','note'),('start','end','state'))
                a=finite(i['start'],0,r['source_metadata']['duration']);b=finite(i['end'],0,r['source_metadata']['duration'])
                if b<=a or a<end:raise APIError('invalid_review','Use nonoverlapping positive source-local intervals.')
                end=b
                if i['state'] not in ('usable','rejected','unassessed'):raise APIError('invalid_review','Choose usable, rejected or unassessed.')
                if i.get('reason') not in (None,'timing','identity','anatomy','action','continuity','other'):raise APIError('invalid_review','Choose a documented rejection reason.')
                if i['state']=='rejected' and not i.get('reason'):raise APIError('invalid_review','Record a rejection reason.')
                if i['state']=='usable' and r['method'] in ('unassessed','automated'):raise APIError('invalid_review','Automated/unassessed checks cannot accept a usable window.')
                text(i.get('note',''),2000)
            r['intervals']=copy.deepcopy(data['intervals'])
        if r['method'] in ('unassessed','automated') and any(i['state']=='usable' for i in r['intervals']):raise APIError('invalid_review','Usable windows require explicit human assessment provenance.')
        r['revision']+=1
        with self.p.sql:self.p.put('song-review',r)
        return self.review_view(r,s,p)

    def timeline(self,p,clips,audio,title,fps=24,resolution='480p'):
        from editing_tools import OUTPUT_FIELDS
        settings=self.e.validate(dict(title=title[:120],clips=clips,audio=audio,titles=[],captions=[],markers=[],
            output={**copy.deepcopy(OUTPUT_FIELDS),'ratio':'16:9','resolution':resolution,'fps':fps,'cut_audio_crossfade_frames':0}))
        return self.p.new('timeline',production_id=p['production_id'],episode_id=p['episode_id'],story_scene_id=p['story_scene_id'],
            primary=False,schema_version=3,**settings)

    def comparison(self,identity,data,key):
        fields(data,('expected_revision','review_id','expected_review_revision','fps'),('expected_revision','review_id','expected_review_revision'))
        payload=dict(shot_id=identity,**data);previous=self.replay('song-comparison',key,payload)
        if previous:return self.comparison_view(previous)
        s=self.p.get(identity,'song-shot');self.p.check(s,data);p=self.p.get(s['song_project_id'],'song-project');self.fresh(s,p)
        r=self.get_review(identity,data['review_id']);self.p.check(r,dict(expected_revision=data['expected_review_revision']))
        if self.review_view(r,s,p)['stale']:raise APIError('stale_review','Review inputs changed.',409)
        fps=data.get('fps',24)
        if fps not in (24,30):raise APIError('invalid_output','Choose 24 or 30 FPS.')
        metadata,path=self.metadata(r['source_metadata']['source'],video=True)
        if metadata['sha256']!=r['source_metadata']['sha256']:raise APIError('source_changed','Take source changed.',409)
        if any(j['status'] in ('queued','rendering') for j in self.p.all('export')):
            raise APIError('export_busy','Wait for or cancel the current local export before starting a comparison.',409)
        _,master_path=self.e.source(p['master']['source'])
        if digest(master_path)!=p['master']['sha256']:raise APIError('source_changed','The master source changed.',409)
        # Compare only the natural-speed overlap, without adding silence or padding the song.
        clip_start=max(0,r['clip_anchor']-r['song_anchor'])
        clip_end=min(metadata['duration'],r['clip_anchor']+p['master']['duration']-r['song_anchor'])
        clip_start=math.ceil(clip_start*fps-1e-8)/fps;clip_end=math.floor(clip_end*fps+1e-8)/fps
        if clip_end-clip_start<1/fps:raise APIError('invalid_alignment','The take does not overlap the master song.')
        song_start=song_time(r,clip_start);song_end=song_time(r,clip_end)
        with self.p.sql:
            t=self.timeline(p,[dict(id=uid(),source=metadata['source'],**{'in':clip_start,'out':clip_end},volume=0,label=s['title'])],
                [dict(id=uid(),source=p['master']['source'],**{'in':song_start,'out':song_end},start=0,volume=1,lane='music',label='Original master')],s['title']+' comparison',fps)
            c=self.p.new('song-comparison',song_project_id=p['id'],song_shot_id=s['id'],review_id=r['id'],review_revision=r['revision'],
                key=key,fingerprint=self.fingerprint(payload),snapshot=dict(project=p,shot=s,review=r),timeline_id=t['id'],
                timeline_revision=t['revision'],clip_start=clip_start,song_start=song_start,export_id=None)
        job=self.e.export(t['id'],dict(expected_revision=t['revision']),'song-compare-'+c['id'])
        with self.p.sql:c['export_id']=job['id'];self.p.put('song-comparison',c)
        return self.comparison_view(c)

    def comparison_view(self,c):
        return {**c,'export':self.p.get(c['export_id'],'export') if c.get('export_id') else None}

    def assemble(self,identity,data,key):
        fields(data,('expected_revision','selections','fps','apply','expected_timeline_revision','resolution'),('expected_revision','selections','apply'))
        payload=dict(project_id=identity,**data);previous=self.replay('song-assembly',key,payload)
        if previous:return previous
        p=self.p.get(identity,'song-project');self.p.check(p,data)
        if type(data['apply']) is not bool:raise APIError('invalid_song_request','apply must be boolean.')
        fps=data.get('fps',24)
        if fps not in (24,30):raise APIError('invalid_output','Choose 24 or 30 FPS.')
        selection=data['selections']
        if not isinstance(selection,list) or len(selection)>120:raise APIError('invalid_selection','Use at most 120 explicit selections.')
        if any(not isinstance(item,dict) for item in selection):raise APIError('invalid_selection','Selections must be objects.')
        clips=[]; placements=[];snapshots=[]; singing=0
        for item in sorted(selection,key=lambda x:x.get('song_start',0)):
            fields(item,('review_id','expected_review_revision','song_start','song_end'),('review_id','expected_review_revision','song_start','song_end'))
            r=self.p.get(item['review_id'],'song-review');self.p.check(r,dict(expected_revision=item['expected_review_revision']))
            if r['song_project_id']!=identity:raise APIError('invalid_parent','Review belongs to another song project.')
            s=self.p.get(r['song_shot_id'],'song-shot');self.fresh(s,p)
            if self.review_view(r,s,p)['stale']:raise APIError('stale_review','A selected review is stale.',409)
            a=finite(item['song_start'],0,p['master']['duration']);b=finite(item['song_end'],0,p['master']['duration'])
            if b<=a:raise APIError('invalid_selection','Select a positive song window.')
            left=frame(a,fps);right=frame(b,fps)
            # Complete master retained; final picture uses the frame containing its last sample.
            if abs(b-p['master']['duration'])<1/p['master']['sample_rate']:right=math.ceil(p['master']['duration']*fps)
            if right<=left:raise APIError('invalid_selection','Selection is shorter than an output frame.')
            local_a=r['clip_anchor']+(left/fps-r['song_anchor']);local_b=local_a+(right-left)/fps
            # The final frame may extend past master end, but must exist in the source.
            if not any(i['state']=='usable' and i['start']<=local_a+1e-7 and i['end']>=local_b-1e-7 for i in r['intervals']):raise APIError('unreviewed_window','Picture must fit wholly in an explicitly usable source window.')
            metadata,_=self.metadata(r['source_metadata']['source'],video=True)
            if metadata['sha256']!=r['source_metadata']['sha256'] or local_a<0 or local_b>metadata['duration']+1e-8:raise APIError('source_changed','Take source is missing, changed, or too short.')
            if placements and left<placements[-1]['end_frame']:raise APIError('overlap_selection','Selections collide after frame quantization.')
            placements.append(dict(review_id=r['id'],song_start=a,song_end=b,start_frame=left,end_frame=right,actual_start=left/fps,actual_end=right/fps,mode=s['mode']))
            clips.append(dict(id=uid(),source=metadata['source'],**{'in':local_a,'out':local_b},volume=0,label=s['title'],speed=1))
            snapshots.append(dict(review=r,shot=s))
            if s['mode']=='singing':singing+=(right-left)/fps
        missing=[];at=0;last=math.ceil(p['master']['duration']*fps)
        for placement in placements:
            if placement['start_frame']>at:missing.append(dict(start=at/fps,end=placement['start_frame']/fps))
            at=placement['end_frame']
        if at<last:missing.append(dict(start=at/fps,end=p['master']['duration']))
        findings=dict(selected_singing_seconds=singing,missing_spans=missing,placements=placements,
            unchecked_reviews=[r['id'] for r in self.p.all('song-review') if r['song_project_id']==identity and not any(i['state']=='usable' for i in r['intervals'])],
            plans_without_footage=[s['id'] for s in self.p.all('song-shot') if s['song_project_id']==identity and not any(x['shot']['id']==s['id'] for x in snapshots)])
        _,master_path=self.e.source(p['master']['source'])
        if digest(master_path)!=p['master']['sha256']:raise APIError('source_changed','The master source changed.',409)
        if not data['apply']:
            with self.p.sql:return self.p.new('song-assembly',song_project_id=identity,key=key,fingerprint=self.fingerprint(payload),
                project_revision=p['revision'],coverage=findings,can_apply=bool(clips) and not missing,snapshot=dict(project=p,selections=snapshots),timeline_id=None,timeline_revision=None)
        if missing or not clips:raise APIError('missing_coverage','Select reviewed footage for every song interval before applying. Inspect the assembly proposal for missing spans.',409)
        old=self.p.get(p['working_timeline_id'],'timeline') if p.get('working_timeline_id') else None
        if old:self.p.check(old,dict(expected_revision=data.get('expected_timeline_revision')))
        with self.p.sql:
            t=self.timeline(p,clips,[dict(id=uid(),source=p['master']['source'],**{'in':0,'out':p['master']['duration']},start=0,volume=1,lane='music',label='Original immutable master')],p['title']+' — song working edit',fps,data.get('resolution','480p'))
            # Each assembly is a separate timeline; all previous working edits and primary edit survive.
            a=self.p.new('song-assembly',song_project_id=identity,key=key,fingerprint=self.fingerprint(payload),
                snapshot=dict(project=p,selections=snapshots),coverage=findings,timeline_id=t['id'],timeline_revision=t['revision'])
            t['song_assembly_id']=a['id'];self.p.put('timeline',t)
            p.update(working_timeline_id=t['id'],revision=p['revision']+1);self.p.put('song-project',p)
        return a

    def validate_working_edit(self,timeline,values):
        """Normal Edit tools retain song invariants; new coverage comes through explicit reviews.

        A dissolve is allowed only when both clips have real reviewed handles and
        the authored anchor mapping is preserved, rather than pulling later cuts left.
        """
        if not timeline.get('song_assembly_id'):return
        assembly=self.p.get(timeline['song_assembly_id'],'song-assembly')
        frozen=assembly['snapshot'];project=frozen['project'];master=project['master'];fps=values['output']['fps']
        from editing_tools import starts,length
        def fail(message):raise APIError('song_clock_conflict',message+' Use Song Performance to select new reviewed coverage or create a separate ordinary edit.',409)
        audio=values['audio']
        if len(audio)!=1:fail('A song working edit needs its one continuous original master track.')
        track=audio[0]
        if track['source']!=master['source'] or abs(track['in'])>1e-9 or abs(track['out']-master['duration'])>1/master['sample_rate']/2 or track['start']!=0 or track['volume']!=1 or track.get('normalize') or track.get('audio_fade_in') or track.get('audio_fade_out'):
            fail('The original master must keep its complete samples, start, gain and natural speed.')
        if values['output']['ducking']['enabled'] or values['output']['loudness_target_lufs'] is not None:
            fail('Song master processing would change the original mix.')
        clips=values['clips']
        if not clips:fail('The complete song needs selected picture coverage.')
        positions=starts(clips);total=positions[-1]+length(clips[-1]);expected=math.ceil(master['duration']*fps-1e-9)/fps
        if abs(total-expected)>1e-6:fail('This edit shifts the song duration. Compensate transition overlap with real reviewed source handles.')
        for clip,start in zip(clips,positions):
            if clip['volume']!=0 or clip.get('hold_start') or clip.get('hold_end'):
                fail('Generated audio and frozen source holds cannot enter a song working edit.')
            if abs(start*fps-round(start*fps))>1e-5 or abs(length(clip)*fps-round(length(clip)*fps))>1e-5:
                fail('Song picture boundaries must be explicitly quantized to output frames.')
            options=[]
            for entry in frozen['selections']:
                review=entry['review'];shot=entry['shot']
                if review['source_metadata']['source']!=clip['source']:continue
                if shot['mode']=='singing' and clip.get('speed',1)!=1:continue
                if abs(song_time(review,clip['in'])-start)>1e-6:continue
                if not any(i['state']=='usable' and i['start']<=clip['in']+1e-7 and i['end']>=clip['out']-1e-7 for i in review['intervals']):continue
                options.append(entry)
            if not options:fail('A picture trim, speed or transition no longer fits its frozen reviewed source-to-song mapping.')
        _,path=self.e.source(master['source'])
        if digest(path)!=master['sha256']:fail('The original master source changed.')

    def dispatch(self,method,parts,data,key):
        if parts==['schema'] and method=='GET':return 200,self.schema()
        if parts==['projects'] and method=='GET':return 200,[self.project(p['id']) for p in self.p.all('song-project') if not p.get('archived')]
        if parts==['projects'] and method=='POST':return 201,self.create(data)
        if len(parts)==2 and parts[0]=='projects' and method=='GET':return 200,self.project(parts[1])
        if len(parts)==2 and parts[0]=='projects' and method=='PATCH':return 200,self.patch_project(parts[1],data)
        if len(parts)==3 and parts[0]=='projects' and parts[2]=='analyze' and method=='POST':return 202,self.analyze(parts[1],data,key)
        if len(parts)==2 and parts[0]=='analysis-jobs' and method=='GET':return 200,self.p.get(parts[1],'song-analysis-job')
        if len(parts)==3 and parts[0]=='analysis-jobs' and parts[2]=='cancel' and method=='POST':
            fields(data,('expected_revision',),('expected_revision',));job=self.p.get(parts[1],'song-analysis-job');self.p.check(job,data)
            if job['status'] not in ('done','error','cancelled'):
                self.events.setdefault(job['id'],threading.Event()).set();job=self.job_update(job['id'],status='cancelled')
            return 200,job
        if len(parts)==3 and parts[0]=='analysis-jobs' and parts[2]=='apply' and method=='POST':return 200,self.apply_analysis(parts[1],data)
        if len(parts)==3 and parts[0]=='projects' and parts[2]=='shots' and method=='GET':return 200,self.project(parts[1])['shots']
        if len(parts)==3 and parts[0]=='projects' and parts[2]=='shots' and method=='POST':return 201,self.create_shot(parts[1],data)
        if len(parts)==2 and parts[0]=='shots' and method=='GET':return 200,self.shot_view(self.p.get(parts[1],'song-shot'))
        if len(parts)==2 and parts[0]=='shots' and method=='PATCH':return 200,self.patch_shot(parts[1],data)
        if len(parts)==3 and parts[0]=='shots' and parts[2]=='prepare' and method=='POST':return 200,self.prepare(parts[1],data)
        if len(parts)==3 and parts[0]=='shots' and parts[2]=='apply-draft' and method=='POST':return 200,self.apply_draft(parts[1],data)
        if len(parts)==3 and parts[0]=='shots' and parts[2]=='take-reviews' and method=='GET':return 200,self.shot_view(self.p.get(parts[1],'song-shot'))['reviews']
        if len(parts)==3 and parts[0]=='shots' and parts[2]=='take-reviews' and method=='POST':return 201,self.create_review(parts[1],data)
        if len(parts)==4 and parts[0]=='shots' and parts[2]=='take-reviews' and method=='GET':return 200,self.review_view(self.get_review(parts[1],parts[3]))
        if len(parts)==4 and parts[0]=='shots' and parts[2]=='take-reviews' and method=='PATCH':return 200,self.patch_review(parts[1],parts[3],data)
        if len(parts)==3 and parts[0]=='shots' and parts[2]=='comparisons' and method=='POST':return 202,self.comparison(parts[1],data,key)
        if len(parts)==2 and parts[0]=='comparisons' and method=='GET':return 200,self.comparison_view(self.p.get(parts[1],'song-comparison'))
        if len(parts)==3 and parts[0]=='projects' and parts[2]=='assemble' and method=='POST':return 200,self.assemble(parts[1],data,key)
        raise APIError('not_found','Unknown Song Performance operation.',404)
