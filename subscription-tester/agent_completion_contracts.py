"""Contracts for the completed human/agent parity workflows."""
from agent_parity_contracts import obj,body,array,ref,STRING as S,REVISION as R,NULL_ID as N

def contracts(paths,operation):
    boolean={'type':'boolean'};approved={'const':True};zero={'type':'integer','minimum':0}
    def request(path,method,properties,required=()):
        paths[path][method]['requestBody']={'required':True,'content':{'application/json':{'schema':obj(properties,required)}}}
    def add(path,method,summary,properties=None,required=(),response=None,status='200',mime='application/json'):
        op=operation(summary,body(properties,required) if properties is not None else None)
        op['responses'][status]={'description':summary,'content':{mime:{'schema':response or {'type':'object'}}}}
        paths.setdefault(path,{})[method]=op
    # Workflow tools use the same typed request contracts as existing actions.
    request('/assets/{id}/mirror','post',{'expected_shot_revision':R})
    request('/editing/timelines/{id}/duplicate','post',{'expected_revision':R,'title':{'type':'string','minLength':1,'maxLength':120}},('expected_revision',))
    request('/editing/timelines/{id}/primary','post',{'expected_revision':R},('expected_revision',))
    position=obj({'name':{'type':'string','minLength':1,'maxLength':120},'position':{'enum':['left','center','right']},'depth':{'enum':['foreground','background']},'facing':{'enum':['left','right','front','back']},'target':{'type':'string','maxLength':120}},('name','position','depth','facing'))
    request('/scene-layouts/{id}','put',{'expected_revision':zero,'characters':{**array(position),'maxItems':50},'camera_side':{'type':'string','maxLength':120}},('expected_revision',))
    lesson_tags={'project_id':N,'entities':{**array({'type':'string','minLength':1,'maxLength':120}),'maxItems':30},'model':{'type':['string','null'],'maxLength':120},'shot_type':{'type':['string','null'],'maxLength':120}}
    request('/lessons','post',{**lesson_tags,'failed':{'type':'string','minLength':1,'maxLength':4000},'worked':{'type':'string','minLength':1,'maxLength':4000},'date':{'type':'string','format':'date'},'source_take':{'type':['string','null'],'maxLength':120}},('failed','worked'))
    request('/lessons/search','post',{**lesson_tags,'query':S})
    request('/assets/{id}/annotations','post',{'approved':boolean,'known_text':boolean,'pose':{'type':'object','maxProperties':50,'propertyNames':{'maxLength':120},'additionalProperties':{'enum':['left','right','front','back']}}})
    # Previously implemented production actions must be discoverable.
    add('/productions/{id}/reorder-shots','post','Reorder every active shot within one scene; check every shot revision',{'episode_id':N,'story_scene_id':N,'shot_ids':{**array(S),'uniqueItems':True},'expected_revisions':{'type':'object','additionalProperties':R}},('shot_ids','expected_revisions'))
    add('/productions/shots/{id}/import-video','post','Attach a saved video upload as a shot take without generation',{'expected_revision':R,'media_id':S,'source_label':{'type':'string','maxLength':120},'select':boolean},('expected_revision','media_id'),obj({'shot':{'type':'object'},'take':{'type':'object'}},('shot','take')),'201')
    paths['/productions/shots/{id}']['put']['requestBody']['content']['application/json']['schema']['properties']['story_direction']={'type':'string','minLength':1,'maxLength':10000,'description':'Action, dialogue, reactions and ending. Changes mark earlier takes and preserve the source manuscript.'}
    # GET parameters are parsed identically through the browser and bearer bridge.
    for path,names in (('/video-review',('scene_id','video_job_id','target_video_job_id')),('/video-review/lessons',('model',))):
        paths[path]['get']['parameters']=[{'in':'query','name':name,'required':False,'schema':{'type':'string','minLength':1,'maxLength':128}} for name in names]
    request('/video-review','post',{'approved':approved,'video_job_id':S,'scene_id':S,'provider':{'enum':['codex','grok']},'notes':{'type':'string','maxLength':4000},'previous_review_id':N,'force':boolean},('approved','video_job_id','scene_id'))
    request('/video-review/{id}/apply','post',{'approved':approved,'expected_scene_revision':R,'expected_review_revision':R,'expected_scene_prompt':S,'prompt':{'type':'string','maxLength':50000},'allow_dialogue_changes':boolean},('approved','expected_scene_revision','expected_review_revision'))
    request('/video-review/lessons/{id}/approve','post',{'approved':approved,'expected_revision':R,'expected_guide_version':zero,'guidance':{'type':'string','maxLength':1200}},('approved','expected_revision','expected_guide_version'))
    for action in ('dismiss','deactivate'):request('/video-review/lessons/{id}/'+action,'post',{'expected_revision':R},('expected_revision',))
    # Precisely describe formerly opaque substantive bodies. Empty commands are
    # explicitly empty; extensible creative records retain additional fields.
    for path in ('/account/login','/jobs/{id}/resume','/image-studio/openai-account/refresh','/image-studio/jobs/{id}/resume','/scenes/{id}/validate','/image-studio/drafts/{id}/validate','/editing/exports/{id}/cancel','/creative/messages/{id}/apply','/creative/messages/{id}/undo','/filmmaking/renders/{id}/cancel'):
        paths[path]['post']['requestBody']['content']['application/json']['schema']=body({},())
    request('/scenes/{id}/archive','post',{'expected_revision':R,'archived':boolean},('expected_revision',))
    request('/workspace','post',{'scene_id':N})
    request('/image-studio/workspace','post',{'draft_id':N})
    for path in ('/jobs/{id}/reuse','/image-studio/jobs/{id}/reuse'):request(path,'post',{'title':{'type':'string','maxLength':120}})
    request('/stories/workspace','post',{'episode_id':N,'scene_id':N})
    request('/stories/episodes/{id}/context','post',{'scene_id':N,'revision':R})
    upload={'text':{'type':'string','maxLength':60000},'name':{'type':'string','maxLength':200},'base64':S}
    for path in ('/stories/import-preview','/filmmaking/worlds/{id}/import-preview','/filmmaking/episodes/{id}/upload-preview'):request(path,'post',upload)
    section=obj({'id':S,'title':S,'text':S,'type':{'enum':['scene','notes','other']}},('title','text','type'))
    request('/stories/episodes/{id}/apply-import','post',{'expected_revision':R,'sections':{**array(section),'minItems':1,'maxItems':150}},('expected_revision','sections'))
    asset={'title':{'type':'string','maxLength':120},'handle':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,39}$'},'description':{'type':'string'},'category':{'enum':['Character','Location','Prop']},'images':{**array(ref('ImageSource')),'maxItems':7},'voice':N}
    for path,method in (('/references','post'),('/references/{id}','put'),('/asset-studio','post'),('/asset-studio/{id}','put')):
        request(path,method,{**asset,'expected_revision':R},('expected_revision',) if path.startswith('/asset-studio/') else ('title','handle','category'))
    request('/references/{id}/archive','post',{'archived':boolean})
    for action,extra,required in (('restore',{'revision':R},('revision',)),('archive',{'archived':boolean},()),('develop',{'prompt':S},()),('adopt',{'asset_id':S,'replace_index':{'type':['integer','null'],'minimum':0,'maximum':6}},('asset_id',))):
        request('/asset-studio/{id}/'+action,'post',{'expected_revision':R,**extra},('expected_revision',*required))
    request('/asset-studio/development/lookup','post',{'draft_id':S},('draft_id',))
    from world_workshop import CAST,PLACE
    card=obj({'id':S,'name':S,'title':S,'text':S,**{k:S for k in set(CAST)|set(PLACE)},'reference_ids':{**array(S),'maxItems':5},'palette':array(S),'series_asset_id':N})
    guide=obj({**{k:array(card) for k in ('cast','places','props','acts')},'script':S})
    answers={'type':'object','additionalProperties':S,'description':'Book answers and creative direction; limits are published by the book schema.'}
    book={'expected_revision':zero,'answers':answers,'guide':guide,'expected_episode_revision':R,'selected_asset_ids':array(S),'refresh_inheritance':boolean,'script_options':obj({'allow_dialogue_polish':boolean})}
    request('/filmmaking/series/{id}/bible','put',{k:v for k,v in book.items() if k in ('expected_revision','answers','guide')},('expected_revision',))
    request('/filmmaking/episodes/{id}/book','put',book,('expected_revision',))
    request('/filmmaking/series/{id}/library','post',{'reference_id':S},('reference_id',))
    request('/filmmaking/series/{id}/library/promote','post',{'entity_id':S,'expected_revision':R},('entity_id','expected_revision'))
    for path in ('/filmmaking/worlds/{id}/workshop','/filmmaking/series/{id}/workshop','/filmmaking/episodes/{id}/workshop'):request(path,'post',{'expected_revision':zero,'job_id':S,'model':S},('expected_revision',))
    generation={'job_id':S,'approved':approved,'model':S,'requests':{**array(obj({'view_id':S,'expected_revision':R,'prompt':S},('view_id','expected_revision'))),'minItems':1}}
    for kind in ('worlds','series','episodes'):request('/filmmaking/'+kind+'/{id}/generate','post',generation,('job_id','approved','requests'))
    writing={'expected_revision':zero,'expected_episode_revision':R,'approved':approved,'provider':{'enum':['codex','grok']},'image_model':S,'video_model':S,'allow_dialogue_polish':boolean,'revision_of':S,'expected_job_revision':R,'scene_index':zero,'instruction':S}
    for action in ('plan','complete-production','storyboard'):request('/filmmaking/episodes/{id}/'+action,'post',writing,('expected_revision','expected_episode_revision','approved'))
    request('/filmmaking/episodes/{id}/upload-ai-review','post',{**upload,'expected_revision':zero,'approved':approved,'provider':{'enum':['codex','grok']}},('text','expected_revision','approved'))
    request('/filmmaking/episodes/{id}/upload-apply','post',{'expected_revision':zero,'source':S,'review_token':S,'review_job_id':S,'expected_episode_revision':R,'replace_existing':boolean,'choices':{'type':'object','additionalProperties':{'enum':['uploaded','app','both']}},'allow_dialogue_polish':boolean},('expected_revision','source','review_token','expected_episode_revision','choices'))
    request('/filmmaking/episodes/{id}/production-review','post',{'job_id':S,'expected_revision':R,'resolutions':{'type':'object','additionalProperties':S},'accepted_dialogue':array(S)},('job_id','expected_revision','resolutions'))
    request('/filmmaking/episodes/{id}/apply','post',{'job_id':S,'expected_revision':R,'expected_episode_revision':R,'replace_existing':boolean,'result':{'type':'object'},'image_model':S},('job_id','expected_revision','expected_episode_revision'))
    request('/filmmaking/episodes/{id}/script','post',{'expected_revision':zero,'expected_episode_revision':R,'script':S,'replace_existing':boolean},('expected_revision','expected_episode_revision'))
    request('/filmmaking/episodes/{id}/trash-script','post',{'expected_revision':zero,'expected_episode_revision':R,'approved':approved,'expected_job_revisions':{'type':'object','additionalProperties':R}},('expected_revision','expected_episode_revision','approved','expected_job_revisions'))
    request('/filmmaking/episodes/{id}/refresh-assets','post',{'expected_revision':zero,'expected_episode_revision':R,'approved':approved,'allow_completed':boolean,'shots':{**array(obj({'id':S,'expected_revision':R},('id','expected_revision'))),'minItems':1,'maxItems':100}},('expected_revision','expected_episode_revision','approved','shots'))
    request('/filmmaking/worlds/{id}/workshop','post',{'job_id':S,'expected_revision':R,'model':S},('job_id','expected_revision'))
    request('/filmmaking/worlds/{id}/reference','post',{'name':S,'data_url':S},('data_url',))
    request('/filmmaking/entities/{id}','put',{'expected_revision':R,'profile':card,'description':{'type':'string','maxLength':10000}},('expected_revision',))
    request('/filmmaking/entities/{id}/views','post',{'expected_revision':R,'model':S,'views':array(obj({'label':S,'details':S},('label',)))},('expected_revision','views'))
    request('/filmmaking/entities/{id}/upload','post',{'expected_revision':R,'asset_id':S},('expected_revision','asset_id'))
    request('/filmmaking/assets/{id}/confirm','post',{'expected_revision':R,'asset_id':S,'approved':approved},('expected_revision','asset_id','approved'))
    request('/filmmaking/jobs/{id}/fork','post',{'expected_revision':R},('expected_revision',))
    # Browser commands are requests against explicit, consensually published tabs.
    route=obj({'page':{'enum':['home','projects','project','library','tool']},'workspace':obj({'production_id':S,'episode_id':N,'story_scene_id':N,'shot_id':N,'stage':{'enum':['develop','script','storyboard','generate','edit']},'board_view':{'enum':['board','image']}}),'tool':{'enum':['image','video','scripts','assets','precision']},'media':obj({'kind':S,'id':S},('kind','id')),'collection':{'enum':['all','images','videos','scripts','assets','uploads','exports']},'overlay':{'enum':['camera','movements']}},('page',),additionalProperties=False)
    view=obj({'chapter':{'type':'integer','minimum':0,'maximum':5},'section':S,'field':S,'expanded_editor':boolean,'expanded':{**array(boolean),'maxItems':30},'scroll_top':{'type':'number','minimum':0,'maximum':1000000},'query':S,'filter':S,'position':{'type':'number','minimum':0,'maximum':3600},'playing':boolean,'zoom':{'type':'number','minimum':10,'maximum':500},'selection':{'anyOf':[obj({'kind':{'enum':['clip','audio','title']},'id':S},('kind','id')),{'type':'null'}]}},additionalProperties=False)
    payloads=[obj({'kind':{'const':'navigate'},'payload':body({'route':ref('BrowserDestination'),'view':ref('BrowserView')},('route',))},('kind','payload')),obj({'kind':{'const':'resolve'},'payload':body({'editor':S,'action':{'enum':['save','reload','discard']}},('editor','action'))},('kind','payload')),obj({'kind':{'const':'identity'},'payload':body({'action':{'enum':['signin','switch','cancel','logout','guest','restore-guest']}},('action',))},('kind','payload')),obj({'kind':{'const':'playback'},'payload':ref('BrowserView')},('kind','payload'))]
    command=body({'expected_revision':R,'kind':{'enum':['navigate','resolve','identity','playback']},'payload':{'type':'object'}},('expected_revision','kind','payload'));command['oneOf']=payloads
    editor=obj({'id':S,'revision':zero,'dirty':boolean,'data':{'type':'object'},'actions':array({'enum':['save','reload','discard']})},('id','revision','dirty','data','actions'))
    state=obj({'route':ref('BrowserDestination'),'view':ref('BrowserView'),'editors':{'type':'object','additionalProperties':ref('AgentEditorSnapshot')}},('route','view','editors'))
    tab=obj({'id':S,'revision':R,'controls_enabled':boolean,'state':state,'captured_at':{'type':'number'},'expires_at':{'type':'number'}},('id','revision','state','captured_at','expires_at'))
    result=obj({'id':S,'tab_id':S,'revision':R,'status':{'enum':['pending','awaiting_human','executing','completed','failed','rejected','expired']},'kind':{'enum':['navigate','resolve','identity','playback']},'payload':{'type':'object'},'expected_tab_revision':R,'expected_state':{'type':'object'},'expected_editor':ref('AgentEditorSnapshot'),'created_at':{'type':'number'},'updated_at':{'type':'number'},'expires_at':{'type':'number'},'error':N},('id','tab_id','revision','kind','status','payload'))
    add('/handoff/tabs','get','List live, human-shared browser tabs; empty is not proof of no unsaved work',response=array(ref('AgentBrowserTab')))
    add('/handoff/tabs/{id}','get','Read the exact shared destination, view and supported editor actions',response=ref('AgentBrowserTab'))
    op=operation('Request navigation, draft resolution, identity handoff or playback in this tab; poll acknowledgement',command);op['responses']['202']={'description':'Request queued; no immediate content change','content':{'application/json':{'schema':ref('AgentBrowserRequest')}}};paths['/handoff/tabs/{id}/requests']={'post':op}
    add('/handoff/requests/{id}','get','Read completion, failure, human verification or expiry; no identity secrets',response=ref('AgentBrowserRequest'))
    export=obj({'filename':S,'mime':{'enum':['application/json','text/markdown']},'text':S},('filename','mime','text'))
    document=obj({'answers':answers,'guide':guide,'inheritance':{'type':['object','null']}},('answers','guide'))
    add('/documents/render','post','Format supplied book content with the same local formatter as the UI; no saved-state writes',{'document':ref('ExportBook'),'title':{'type':'string','maxLength':120},'plan':{'type':['object','null']},'family':{'enum':['series','story']},'format':{'enum':['markdown','json']}},('document',),ref('BookExport'))
    add('/documents/book','post','Export the saved Series Bible, episode or legacy story; current saved plan included',{'kind':{'enum':['series','episode','world']},'id':S,'format':{'enum':['markdown','json']}},('kind','id'),ref('BookExport'))
    add('/demo','get','Read versioned local demo images and scene recipe; mock mode only',response=obj({'version':{'const':1},'images':array(obj({'name':S,'data_url':S},('name','data_url'))),'scene':{'type':'object'}},('version','images','scene')))
    add('/demo/load','post','Create the shared demo storyboard in mock mode only; idempotent and no generation',{},(),obj({'id':S,'revision':R,'scene':ref('Scene')},('id','revision','scene')),'201')
    paths['/demo/load']['post']['parameters']=[{'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}}]
    add('/editing/timelines/{id}/preview','post','Render or reuse this exact saved timeline locally; poll the export, then request its composite frame',{'expected_revision':R},('expected_revision',),obj({'id':S,'status':{'enum':['queued','rendering','done']},'snapshot':{'type':'object'}},('id','status','snapshot')),'202')
    add('/editing/exports/{id}/frame','post','Read composite PNG at timeline time, including titles and transitions, from completed export',{'timestamp_s':{'type':'number','minimum':0,'maximum':3600},'expected_revision':R},('timestamp_s','expected_revision'),{'type':'string','format':'binary'},mime='image/png')
    return {'BrowserDestination':route,'BrowserView':view,'AgentEditorSnapshot':editor,'AgentBrowserTab':tab,'AgentBrowserRequest':result,'ExportBook':document,'BookExport':export}
