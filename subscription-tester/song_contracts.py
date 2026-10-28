"""Discoverable Song Performance request/response contracts, shared by OpenAPI and UI."""

def contracts(paths, operation):
    def obj(properties, required=()):return dict(type='object',properties=properties,required=list(required),additionalProperties=False)
    def ref(name):return {'$ref':'#/components/schemas/Song'+name}
    def arr(item):return dict(type='array',items=item)
    string={'type':'string'};num={'type':'number'};revision={'type':'integer','minimum':1}
    nullable={'type':['string','null']}
    source=obj({'kind':{'enum':['upload','take']},'id':string},('kind','id'))
    cue=obj(dict(id=string,kind={'enum':['word','phrase','beat','bar','section','vocal_activity','music_activity','instrumental_gap']},
        start=num,end=num,text=string,method=string,source=string,confidence={'type':['number','null']},
        review_state={'enum':['suggested','reviewed','rejected']},uncertainty_s={'type':['number','null']}),('kind','start','end'))
    pose=obj(dict(song_time=num,asset_id=string,purpose=string),('song_time','asset_id','purpose'))
    asset={'anyOf':[obj({'asset_id':string},('asset_id',)),{'type':'null'}]}
    shot_fields=dict(title=string,order={'type':'integer'},start=num,end=num,mode={'enum':['singing','dance_only','cutaway']},
        story_beat=string,lyric_text=string,cue_ids=arr(string),choreography=string,camera=string,holds=string,
        duration={'type':'integer','minimum':1,'maximum':15},leading_handle=num,trailing_handle=num,
        production_shot_id=nullable,draft_id=nullable,reference_handles=arr(string),first=asset,last=asset,poses=arr(pose),prompt=string,
        resolution={'enum':['480p','720p','1080p']},model={'enum':['grok-imagine-video-1.5','grok-imagine-video-1.5-lite']})
    interval=obj(dict(start=num,end=num,state={'enum':['usable','rejected','unassessed']},
        reason={'enum':['timing','identity','anatomy','action','continuity','other',None]},note=string),('start','end','state'))
    metadata=obj(dict(source=source,media_id=string,sha256=string,duration=num,sample_rate={'type':'integer'},channels={'type':'integer'},
        samples={'type':'integer'},width={'type':['integer','null']},height={'type':['integer','null']},fps=nullable,frames=nullable,provenance=string),
        ('source','sha256','duration','samples','sample_rate'))
    stems=obj({role:source for role in ('lead_vocal','instrumental','drums')})
    common=dict(id=string,revision=revision,created_at=num,updated_at=num)
    def record(extra,required=()):
        # Returned records allow forward-compatible metadata, not arbitrary input fields.
        return dict(type='object',properties={**common,**extra},required=['id','revision',*required])
    schemas={
        'SongSource':source,'SongCue':cue,'SongPose':pose,'SongMedia':metadata,'SongShotChanges':obj(shot_fields),
        'SongReview':record(dict(song_project_id=string,song_shot_id=string,plan_revision=revision,master_version=revision,
            master_sha256=string,analysis_id=nullable,analysis_revision={'type':'integer'},cue_revision=revision,
            source_metadata=metadata,generation_evidence={'type':'object'},song_anchor=num,clip_anchor=num,intervals=arr(interval),
            reviewer=string,method={'enum':['unassessed','automated','sampled_frames','human_continuous_playback']},notes=string,
            stale={'type':'boolean'},lip_sync_approved={'const':False}),('source_metadata','song_anchor','clip_anchor','intervals','method')),
        'SongShot':record({**shot_fields,'song_project_id':string,'master_version':revision,'cue_revision':revision,'stale':{'type':'boolean'},'reviews':arr(ref('Review'))}),
        'SongProject':record(dict(schema_version={'const':1},production_id=string,episode_id=nullable,story_scene_id=nullable,
            title=string,master=metadata,stems={'type':'object','additionalProperties':metadata},master_version=revision,lyrics=string,
            analysis_id=nullable,analysis_revision={'type':'integer'},cue_revision=revision,cues=arr(cue),stem_alignment={'type':'object'},
            working_timeline_id=nullable,archived={'type':'boolean'},analysis_jobs=arr(ref('AnalysisJob')),shots=arr(ref('Shot')),analysis={'type':['object','null']}),('master','lyrics','cue_revision','master_version')),
        'SongAnalysisJob':record(dict(song_project_id=string,status={'enum':['queued','running','done','error','cancelled']},
            progress=num,error={'type':['string','null']},analysis_id=nullable,snapshot=ref('Project')),('status','progress')),
        'SongPreparation':obj(dict(scene={'$ref':'#/components/schemas/Scene'},request={'type':'object'},
            shot_revision=revision,project_revision=revision,draft_revision={'type':['integer','null']},analysis_revision={'type':'integer'},
            cue_revision=revision,song_anchor=num,clip_anchor=num,anchors=arr({'type':'object'}),note=string),
            ('scene','request','shot_revision','project_revision','draft_revision','analysis_revision','cue_revision')),
        'SongAssembly':record(dict(song_project_id=string,timeline_id=string,timeline_revision=revision,coverage={'type':'object'},snapshot={'type':'object'})),
        'SongComparison':record(dict(song_project_id=string,song_shot_id=string,review_id=string,review_revision=revision,timeline_id=string,
            timeline_revision=revision,clip_start=num,song_start=num,export_id=nullable,export={'type':['object','null']})),
        'SongCapabilities':obj(dict(schema_version={'const':1},modes=arr(string),clock=string,defaults={'type':'object'},models={'type':'object'},
            interior_anchor_grid={'type':'object'},duration_seconds={'type':'object'},local_analysis={'type':'object'},
            recording_generation=obj(dict(enabled={'const':False},access={'const':'denied'},http_status={'const':403},evidence=string),('enabled','access','http_status','evidence')),
            singing=string,routes=arr(string)),('schema_version','local_analysis','recording_generation','models','modes')),
    }
    def add(path,method,summary,request=None,response=None,status='200',key=False):
        op=operation(summary,request)
        op['responses'][status]={'description':summary,'content':{'application/json':{'schema':response or {'type':'object'}}}}
        if key:op.setdefault('parameters',[]).append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':8,'maxLength':100,'pattern':'^[A-Za-z0-9_-]+$'}})
        paths['/song-performance/'+path]=paths.get('/song-performance/'+path,{})
        paths['/song-performance/'+path][method]=op
    rev=obj({'expected_revision':revision},('expected_revision',))
    prep_fields=dict(expected_revision=revision,expected_project_revision=revision,expected_draft_revision=revision)
    add('schema','get','Song capabilities; custom-recording denial does not block local import',response=ref('Capabilities'))
    add('projects','get','List workspace song projects',response=arr(ref('Project')))
    add('projects','post','Create a song project from private workspace sources',obj(dict(title=string,production_id=string,episode_id=nullable,story_scene_id=nullable,master=source,stems=stems,lyrics=string),('title','production_id','master')),ref('Project'),'201')
    add('projects/{id}','get','Read song, analysis and plans',response=ref('Project'))
    add('projects/{id}','patch','Revise song inputs and editable cues; preserve historical versions',obj(dict(expected_revision=revision,title=string,lyrics=string,master=source,stems=stems,cues=arr(cue),stem_alignment={'type':'object'},archived={'type':'boolean'}),('expected_revision',)),ref('Project'))
    add('projects/{id}/analyze','post','Start idempotent local measurements; no generation',rev,ref('AnalysisJob'),'202',True)
    add('analysis-jobs/{id}','get','Read local analysis status',response=ref('AnalysisJob'))
    add('analysis-jobs/{id}/cancel','post','Cancel local analysis without applying partial results',rev,ref('AnalysisJob'))
    add('analysis-jobs/{id}/apply','post','Merge completed suggestions while preserving human cues',obj(dict(expected_revision=revision,expected_project_revision=revision),('expected_revision','expected_project_revision')),ref('Project'))
    add('projects/{id}/shots','get','List musical shot plans',response=arr(ref('Shot')))
    add('projects/{id}/shots','post','Create shot on the song clock',obj(dict(expected_revision=revision,shot=ref('ShotChanges')),('expected_revision','shot')),ref('Shot'),'201')
    add('shots/{id}','get','Read plan and reviews',response=ref('Shot'))
    add('shots/{id}','patch','Review changed master/cues and revise musical plan',obj(dict(expected_revision=revision,expected_project_revision=revision,changes=ref('ShotChanges')),('expected_revision','expected_project_revision','changes')),ref('Shot'))
    add('shots/{id}/prepare','post','Prepare exact expanded Grok request locally; never generates',obj(prep_fields,('expected_revision','expected_project_revision')),ref('Preparation'))
    add('shots/{id}/apply-draft','post','Apply reviewed proposal to existing draft workflow; no generation',obj({**prep_fields,'preparation':ref('Preparation')},('expected_revision','expected_project_revision','preparation')),obj(dict(shot=ref('Shot'),draft={'type':'object'},validation={'type':'object'}),('shot','draft','validation')))
    add('shots/{id}/take-reviews','get','List take associations and assessments',response=arr(ref('Review')))
    add('shots/{id}/take-reviews','post','Freeze measured take metadata and source/generation evidence',obj(dict(expected_revision=revision,source=source),('expected_revision','source')),ref('Review'),'201')
    add('shots/{id}/take-reviews/{review_id}','get','Read source-local review',response=ref('Review'))
    add('shots/{id}/take-reviews/{review_id}','patch','Record anchor pair, multiple intervals and assessment provenance',obj(dict(expected_revision=revision,song_anchor=num,clip_anchor=num,intervals=arr(interval),reviewer=string,method={'enum':['unassessed','automated','sampled_frames','human_continuous_playback']},notes=string),('expected_revision',)),ref('Review'))
    add('shots/{id}/comparisons','post','Render immutable original-song comparison through existing editor',obj(dict(expected_revision=revision,review_id=string,expected_review_revision=revision,fps={'enum':[24,30]}),('expected_revision','review_id','expected_review_revision')),ref('Comparison'),'202',True)
    add('comparisons/{id}','get','Read comparison and existing export status',response=ref('Comparison'))
    selection=obj(dict(review_id=string,expected_review_revision=revision,song_start=num,song_end=num),('review_id','expected_review_revision','song_start','song_end'))
    add('projects/{id}/assemble','post','Propose coverage or create separate song working timeline; never fills shortages',obj(dict(expected_revision=revision,selections=arr(selection),fps={'enum':[24,30]},apply={'type':'boolean'},expected_timeline_revision=revision,resolution={'enum':['480p','720p','1080p','source']}),('expected_revision','selections','apply')),{'anyOf':[ref('Assembly'),obj(dict(project_revision=revision,coverage={'type':'object'},can_apply={'type':'boolean'}),('project_revision','coverage','can_apply'))]},key=True)
    return schemas
