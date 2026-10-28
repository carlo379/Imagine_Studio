"""Public agent contracts; browser publishing and consent are deliberately not agent routes."""
def contracts(paths,operation):
    def ref(name):return {'$ref':'#/components/schemas/'+name}
    def obj(properties,required=()):return {'type':'object','additionalProperties':False,'properties':properties,'required':list(required)}
    string={'type':'string'};nullable={'type':['string','null']};revision={'type':'integer','minimum':1}
    workspace=obj({'production_id':string,'episode_id':nullable,'story_scene_id':nullable,'shot_id':nullable,'stage':{'const':'develop'},'board_view':{'enum':['board','image']}},('production_id','stage'))
    visual=obj({'activeStep':{'type':'integer','minimum':0,'maximum':4},'expanded':{'type':'array','minItems':4,'maxItems':5,'items':{'type':'boolean'}},'heroChoice':{'type':'string','maxLength':128},'optionalChoice':{'type':'string','maxLength':128},'optionalOpen':{'type':'boolean'},'scrollTop':{'type':'number','minimum':0,'maximum':1000000}},('activeStep','expanded'))
    context=obj({'scope':{'type':'string','pattern':'^(series|episodes)/[^/]+$'},'entity_id':string,'view_id':string,'expected_revision':{**revision,'description':'Source workshop view revision, separate from the return-flow revision.'},'page':{'type':'integer','minimum':0,'maximum':5},'visual':visual,'job_id':string},('scope','entity_id','view_id','expected_revision','page','visual'))
    value=obj({'route':obj({'page':{'const':'project'},'workspace':workspace},('page','workspace')),'title':{'type':'string','maxLength':300},'context':context,'draft_id':string},('route','title','context','draft_id'))
    flow=obj({'id':string,'revision':revision,'status':{'enum':['open','return_requested','returned','finished','superseded']},'created_at':{'type':'number'},'updated_at':{'type':'number'},'expires_at':{'type':'number'},'value':ref('BrowserReturnContext')},('id','revision','status','created_at','updated_at','expires_at','value'))
    draft=obj({'id':string,'revision':{'type':'integer','minimum':0,'description':'Saved source revision; never a save instruction.'},'dirty':{'const':True},'data':{'type':'object','readOnly':True,'description':'Unsaved editor content. No credentials or embedded media; never accepted by an agent handoff write route.'}},('id','revision','dirty','data'))
    drafts=obj({key:{'anyOf':[ref('PendingBrowserDraft'),{'type':'null'}]} for key in ('book','image','video','timeline','editors')})
    snapshot=obj({'id':string,'revision':revision,'captured_at':{'type':'number'},'expires_at':{'type':'number'},'read_only':{'const':True},'drafts':drafts},('id','revision','captured_at','expires_at','read_only','drafts'))
    mutate=obj({'expected_revision':{**revision,'description':'Return-flow metadata revision, not a book/image/workshop revision.'}},('expected_revision',))
    paths.update({
        '/handoff':{'get':operation('Discover local return flows and human-consented read-only browser drafts')},
        '/handoff/flows':{'get':operation('List return flows in this workspace; opaque IDs, seven-day expiry')},
        '/handoff/flows/{id}':{'get':operation('Read a saved Bible/development return destination')},
        '/handoff/flows/{id}/request':{'post':operation('Request return in the originating browser tab; does not adopt an image or apply a draft',mutate)},
        '/handoff/flows/{id}/finish':{'post':operation('Finish after the originating browser acknowledged restoration; otherwise 409',mutate)},
        '/handoff/drafts':{'get':operation('List opted-in read-only unsaved snapshots; empty when disabled, revoked or expired')},
        '/handoff/drafts/{id}':{'get':operation('Read an opted-in snapshot; 404 after revocation or ten-minute expiry')}})
    responses={
        '/handoff':obj({'flows':string,'drafts':string,'tabs':string,'requests':string,'controls_consent_required':{'const':True},'read_only_drafts':{'const':True},'human_consent_required':{'const':True}},('flows','drafts','read_only_drafts','human_consent_required')),
        '/handoff/flows':{'type':'array','items':ref('BrowserReturnFlow')},
        '/handoff/drafts':{'type':'array','items':ref('BrowserDraftSnapshot')}}
    for path,ops in paths.items():
        if not path.startswith('/handoff'):continue
        schema=responses.get(path,ref('BrowserDraftSnapshot' if '/drafts/' in path else 'BrowserReturnFlow'))
        for op in ops.values():
            op['responses']['200']={'description':'Workspace-scoped handoff metadata','content':{'application/json':{'schema':schema}}}
            op['responses']['404']={'description':'Missing, expired or foreign-workspace ID'}
    return {'BrowserReturnContext':value,'BrowserReturnFlow':flow,'PendingBrowserDraft':draft,'BrowserDraftSnapshot':snapshot}
