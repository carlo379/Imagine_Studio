"""Explicit contracts for model access, URL lifecycle and workshop parity actions."""
STRING={'type':'string'}
REVISION={'type':'integer','minimum':1}
NULL_ID={'type':['string','null']}

def obj(properties, required=(), **extra):
    return {'type':'object','properties':properties,**({'required':list(required)} if required else {}),**extra}

def ref(name):return {'$ref':'#/components/schemas/'+name}
def array(schema):return {'type':'array','items':schema}
def body(properties, required):return obj(properties,required,additionalProperties=False)

def contracts(paths, operation):
    dependency=obj({'kind':STRING,'title':STRING,'id':STRING})
    uses=obj({'dependencies':array(dependency),'count':{'type':'integer','minimum':0}},('dependencies','count'))
    output=obj({'id':STRING,'mime':STRING,'name':STRING,'src':STRING,'approved':{'type':'boolean'},
                'job_id':STRING,'draft_id':STRING,'compatible':{'type':'boolean'},'uploaded':{'type':'boolean'},
                'review_state':{'enum':['candidate','approved','rejected','trashed']},'review_reason':STRING,
                'review_revision':{'type':'integer','minimum':0}},('id','review_state','review_revision'))
    schemas={
        'ModelAccessCheck':obj({'signed_in':{'type':'boolean'},'verified':{'const':True},
                               'image_access_verified':{'const':False},'mock':{'type':'boolean'}},
                              ('signed_in','verified','image_access_verified')),
        'RememberedURL':obj({'url_id':STRING,'revision':REVISION,'archived':{'type':'boolean'},'src':{'type':'string','format':'uri'},'name':STRING},('url_id','revision','archived','src','name')),
        'DiagnosticRequest':obj({'id':STRING,'status':{'enum':['pending','done','error']},'mock':{'type':'boolean'},
                                 'phase':STRING,'message':STRING,'http_status':{'type':['integer','null']},
                                 'image':NULL_ID,'created_at':{'type':'number'},'updated_at':{'type':'number'}},('id','status','mock','phase','message','http_status','image','created_at','updated_at')),
        'WorkshopEntity':obj({'id':STRING,'revision':REVISION,'production_id':STRING,'world_job_id':STRING,
                              'name':STRING,'description':STRING,'category':{'enum':['Character','Location','Prop']},
                              'profile':obj({'reference_ids':{**array(STRING),'maxItems':5},'palette':array(STRING)}),
                              'identity_asset_id':NULL_ID,'reference_id':NULL_ID},('id','revision','production_id','world_job_id','name','category')),
        'WorkshopCandidate':output,
        'WorkshopView':obj({'id':STRING,'revision':REVISION,'production_id':STRING,'world_job_id':STRING,'entity_id':STRING,
                            'kind':STRING,'view':STRING,'draft_id':STRING,'selected_asset_id':NULL_ID,'reference_id':NULL_ID,
                            'selected':NULL_ID,'outputs':array(ref('WorkshopCandidate')),
                            'attempts':array(obj({'id':STRING,'error':STRING,'model':NULL_ID,'error_kind':NULL_ID,'dismissed':{'type':'boolean'}},('id','error','dismissed'))),
                            'draft':obj({'id':STRING,'revision':REVISION,'title':STRING,'settings':ref('ImageSettings')},('id','revision','settings')),
                            'pending':{'type':'boolean'},'render_state':{'enum':['idle','queued','generating']},
                            'error':NULL_ID,'error_model':NULL_ID,'error_kind':NULL_ID,'recommended_prompt':STRING},
                           ('id','revision','outputs','attempts','draft','pending','selected','render_state')),
        'WorkshopSnapshot':obj({'job':obj({'id':STRING,'revision':REVISION,'production_id':STRING,'scope':STRING,'status':STRING},('id','revision','production_id')),
                                'entities':array(ref('WorkshopEntity')),'views':array(ref('WorkshopView')),
                                'batches':array(obj({'id':STRING,'revision':REVISION,'status':STRING,'view_ids':array(STRING),'image_job_ids':array(STRING),'cancel_requested':{'type':'boolean'}},('id','revision','status','view_ids'))),
                                'review_preserved':uses,'review_blocked':uses},('job','entities','views','batches')),
        'ProductionSummary':obj({'id':STRING,'revision':REVISION,'title':STRING,'kind':{'enum':['quick','story']},
                                 'origin':STRING,'series_id':NULL_ID,'parent_production_id':NULL_ID,'archived':{'type':'boolean'},
                                 'is_project':{'type':'boolean'},'project_label':{'type':['string','null'],'enum':['Quick Video',None]},
                                 'item_type':{'enum':['video','image','script','story']},'group_id':NULL_ID,
                                 'child_count':{'type':'integer','minimum':0},'last_updated':{'type':'number'}},
                                ('id','revision','title','kind','is_project','project_label','item_type','group_id','child_count','last_updated')),
        'RecentProductions':obj({'items':array(ref('ProductionSummary')),'total':{'type':'integer','minimum':0},
                                 'production_total':{'type':'integer','minimum':0},'offset':{'type':'integer','minimum':0},
                                 'limit':{'type':'integer','minimum':1,'maximum':100},'has_more':{'type':'boolean'}},
                                ('items','total','production_total','offset','limit','has_more')),
    }
    def add(path, method, summary, request, response, status='200', mime='application/json'):
        op=operation(summary,request)
        op['responses'][status]={'description':summary,'content':{mime:{'schema':response}}}
        if status=='202':op['responses']['200']={'description':'Original request replay; never resubmitted','content':{mime:{'schema':response}}}
        paths.setdefault(path,{})[method]=op
    add('/account/grok-check','post','Fresh Grok model access check; no generation or cached substitute',body({},()),ref('ModelAccessCheck'))
    add('/urls','get','List active remembered URLs',None,array(ref('RememberedURL')))
    add('/urls','post','Remember HTTPS URL; an archived duplicate stays archived',body({'url':STRING,'name':{'type':'string','maxLength':120}},('url',)),array(ref('RememberedURL')))
    add('/urls/all','get','List remembered URLs including archived',None,array(ref('RememberedURL')))
    add('/urls/{id}','get','Read remembered URL by url_id, including archived',None,ref('RememberedURL'))
    add('/urls/{id}/archive','post','Remove or restore remembered URL; saved scene inputs remain intact',body({'expected_revision':REVISION,'archived':{'type':'boolean','default':True}},('expected_revision',)),ref('RememberedURL'))
    add('/image-test','post','Local mock diagnostic or replay of an existing diagnostic; new live images require Image Studio AI preparation',body({'prompt':{'type':'string','minLength':1,'maxLength':4096},'approved':{'const':True}},('prompt','approved')),ref('DiagnosticRequest'),'202')
    add('/image-test/{id}','get','Poll original diagnostic in current mode',None,ref('DiagnosticRequest'))
    add('/filmmaking/entities/{id}/workshop','get','Read owning workshop without changing saved work',None,ref('WorkshopSnapshot'))
    revision_body=body({'expected_revision':REVISION},('expected_revision',))
    add('/filmmaking/entities/{id}/clear-approval','post','Clear main entity approval when idle; preserve saved references and history',revision_body,ref('WorkshopSnapshot'))
    add('/filmmaking/assets/{id}','put','Rename an optional view or explicitly set this view image ratio',body({'expected_revision':REVISION,'ratio':{'type':'string'},'title':{'type':'string','minLength':1,'maxLength':80}},('expected_revision',)),ref('WorkshopSnapshot'))
    add('/filmmaking/assets/{id}/clear-approval','post','Clear optional view approval when idle',revision_body,ref('WorkshopSnapshot'))
    add('/filmmaking/assets/{id}/return-image','post','Adopt an approved edit belonging to this view; otherwise return unchanged snapshot',body({'expected_revision':REVISION,'job_id':STRING,'asset_id':STRING},('expected_revision','job_id','asset_id')),ref('WorkshopSnapshot'))
    # Two independent revision domains: view record and candidate review state.
    add('/filmmaking/assets/{id}/review','post','Reject, trash or restore candidate; inspect review_blocked/review_preserved',body({'expected_revision':REVISION,'expected_review_revision':{'type':'integer','minimum':0},'asset_id':STRING,'action':{'enum':['reject','trash','restore']},'reason':{'type':'string','maxLength':500}},('expected_revision','expected_review_revision','asset_id','action')),ref('WorkshopSnapshot'))
    add('/filmmaking/assets/{id}/attempts','post','Dismiss or restore failed attempts; no generation',body({'expected_revision':REVISION,'attempt_ids':{**array(STRING),'minItems':1,'maxItems':1000},'action':{'enum':['dismiss','restore']}},('expected_revision','attempt_ids','action')),ref('WorkshopView'))
    for kind in ('series','episodes'):
        add('/filmmaking/'+kind+'/{id}/book.pdf','get','Export saved book and approved references locally',None,{'type':'string','format':'binary'},mime='application/pdf')
    recent=paths['/productions/recent']['post']
    recent['requestBody']['content']['application/json']['schema']['properties']['projects_only']={'type':'boolean','default':False,'description':'Only Story / Series and explicit Quick Video projects. Both counts then reflect projects in the selected scope; child_count counts project children.'}
    recent['responses']['200']={'description':'Classified, paginated productions; counts respect projects_only','content':{'application/json':{'schema':ref('RecentProductions')}}}
    return schemas
