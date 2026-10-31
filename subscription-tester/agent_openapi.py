"""OpenAPI discovery for local agents; the written guide includes complete workflow examples."""
import re

def specification():
    scene={'type':'object','additionalProperties':False,'properties':{
        'model':{'type':'string','enum':['grok-imagine-video-1.5','grok-imagine-video-1.5-lite']},
        'duration':{'type':'integer','minimum':1,'maximum':15},'ratio':{'type':'string'},'resolution':{'type':'string'},
        'prompt':{'type':'string'},'audio':{'type':'boolean'},
        'refs':{'type':'array','items':{'$ref':'#/components/schemas/ReferenceImage'}},
        'recording':{'anyOf':[{'type':'null'},{'type':'object','additionalProperties':False,'required':['reference_id','excerpt_id'],'properties':{'reference_id':{'type':'string'},'excerpt_id':{'type':'string'},'character_id':{'type':'string'}}}]},
        'voices':{'type':'array','items':{'type':'object','required':['voice'],'properties':{'id':{'type':'string'},'voice':{'type':'string'}}}},
        'keys':{'type':'array','items':{'type':'object','required':['source','slot'],'properties':{'id':{'type':'string'},'source':{'$ref':'#/components/schemas/ImageSource'},'slot':{'type':'integer','description':'One-third-second slot; timestamp seconds × 3.'}}}},
        'first':{'anyOf':[{'$ref':'#/components/schemas/ImageSource'},{'type':'null'}]},
        'last':{'anyOf':[{'$ref':'#/components/schemas/ImageSource'},{'type':'null'}]},
        'named':{'type':'array','items':{'type':'object'},'description':'Scene snapshots returned by API; use named_references when attaching. Optional video_summary is a scene-only, one-line identity cue of 1–220 characters; the original description remains intact.'}}}
    operation=lambda text,body=None:{'summary':text,'responses':{'200':{'description':'Success'},'201':{'description':'Created'},'202':{'description':'Operation started'},'400':{'description':'Invalid input'},'403':{'description':'Authentication or approval required'},'409':{'description':'Revision or idempotency conflict'}},**({'requestBody':{'required':True,'content':{'application/json':{'schema':body}}}} if body else {})}
    object_body={'type':'object'}
    review_outcome={'type':'object','additionalProperties':False,'required':['approved','expected_revision'],
        'anyOf':[{'required':['assessment']},{'required':['successful']}],
        'properties':{'approved':{'const':True},'expected_revision':{'type':'integer','minimum':1},
            'assessment':{'enum':['successful','improved','needs_work']},'successful':{'type':'boolean','description':'Legacy assessment; use assessment for partial improvement.'},
            'confirmed_finding_ids':{'type':'array','maxItems':30,'uniqueItems':True,'items':{'type':'string'},'description':'Met findings personally confirmed by the human; improved requires at least one.'},
            'notes':{'type':'string','maxLength':4000},
            'candidate_index':{'anyOf':[{'type':'integer','minimum':0,'maximum':11},{'type':'null'}],'description':'Null records only the assessment, without a lesson proposal.'}}}
    review_refine={'type':'object','additionalProperties':False,'required':['approved','expected_revision','notes'],
        'properties':{'approved':{'const':True},'expected_revision':{'type':'integer','minimum':1},
            'provider':{'enum':['codex','grok']},'notes':{'type':'string','minLength':1,'maxLength':4000},
            'preserve_finding_ids':{'type':'array','maxItems':30,'uniqueItems':True,'items':{'type':'string'},'description':'Met findings whose successful behavior must remain unchanged.'},
            'force':{'type':'boolean','description':'Explicitly bypass an identical saved refinement result.'}}}
    scene_create={'type':'object','properties':{'title':{'type':'string'},'scene':{'$ref':'#/components/schemas/Scene'},'named_references':{'type':'array','items':{'type':'string'}}}}
    edit={'type':'object','required':['expected_revision'],'properties':{'expected_revision':{'type':'integer'},'title':{'type':'string'},'scene':{'$ref':'#/components/schemas/Scene'}}}
    patch={'type':'object','required':['expected_revision'],'properties':{'expected_revision':{'type':'integer'},'changes':{'$ref':'#/components/schemas/Scene'},**{key:{'type':'array','items':{'type':'string'}} for key in ('named_references','remove_named_references','restore_named_references')}}}
    paths={
        '/workspace/status':{'get':operation('Read cheap owner-scoped revision tokens for productions, video, images, scripts, account and inspection; no archival payloads')},
        '/library/page':{'post':operation('Read paginated library summaries; does not mutate drafts or generate media',{'type':'object','additionalProperties':False,'properties':{'collection':{'enum':['all','images','videos','scripts','assets','uploads','exports'],'default':'all'},'query':{'type':'string','maxLength':200},'filter':{'type':'string','maxLength':40},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100,'default':40}}})},
        '/productions/{id}/summary':{'get':operation('Read compact outline with episode/scene titles, shot statuses, selected thumbnails and take metadata; fetch shot/script detail on demand')},
        '/scenes/{id}/jobs':{'get':operation('Read video history for one saved scene, including uniquely matching legacy snapshots')},
        '/image-studio/drafts/{id}/jobs':{'get':operation('Read image history for one draft/version family in this workspace mode')},
        '/editing/export-summaries':{'get':operation('Read export progress and delivery metadata without full timeline snapshots')},
        '/assets/{id}/mirror':{'post':operation('Local image/video mirror; new asset with mirrored_from, take association retained; expected_shot_revision required for linked videos',object_body)},
        '/editing/timelines':{'get':operation('List named timelines and primary state; legacy first timeline remains primary')},
        '/editing/timelines/{id}/duplicate':{'post':operation('Duplicate as a new independent timeline with expected_revision and optional title',object_body)},
        '/editing/timelines/{id}/render':{'post':operation('Render a scene timeline and insert or replace one linked clip in its episode timeline',{'type':'object','additionalProperties':False,'required':['expected_revision','parent_timeline_id','expected_parent_revision'],'properties':{'expected_revision':{'type':'integer','minimum':1},'parent_timeline_id':{'type':'string'},'expected_parent_revision':{'type':'integer','minimum':1}}})},
        '/editing/timelines/{id}/primary':{'post':operation('Mark primary within episode or scene scope with expected_revision',object_body)},
        '/scene-layouts/{id}':{'get':operation('Read scene geography or shot end-state override'),'put':operation('Revisioned layout: expected_revision (0 initially), characters [{name,position:left|center|right,depth:foreground|background,facing:left|right|front|back,target}], camera_side',object_body)},
        '/lessons':{'get':operation('List project/global local lessons'),'post':operation('Add lesson: project_id optional, failed, worked, entities, model, shot_type, date, source_take',object_body)},
        '/lessons/search':{'post':operation('Search lessons by project_id, query, entities and model',object_body)},
        '/assets/{id}/annotations':{'post':operation('Record reviewed approval, known_text boolean and pose map from names to facing directions',object_body)},
        '/prompts/check':{'post':operation('Non-blocking data-driven video authoring preflight',{'type':'object','additionalProperties':False,'properties':{'scene_id':{'type':'string'},'scene':scene,'prompt':{'type':'string'},'shot_id':{'type':'string'}}})},
        '/usage':{'get':operation('Unknown provider media allowances, local daily model counts and recent limit errors')},
        '/':{'get':operation('Discover API version')},'/schema':{'get':operation('Discover runtime defaults, voices and configuration')},
        '/openapi.json':{'get':operation('OpenAPI specification')},'/account':{'get':operation('Account and current operation state')},
        '/account/login':{'post':operation('Start device login; human completes xAI sign-in',object_body)},
        '/video-review':{'get':operation('List saved video reviews in this workspace mode'),
            'post':operation('Review a completed take against its submitted request; explicit approval and idempotency key; no video generation',object_body)},
        '/video-review/{id}':{'get':operation('Read or poll a timestamped video review and prompt proposal')},
        '/video-review/schema':{'get':operation('Read local video-review capabilities and evidence limits')},
        '/video-review/lessons':{'get':operation('Read learned guide history for the model query parameter')},
        '/video-review/{id}/apply':{'post':operation('Explicitly apply only the reviewed direction, with draft and review revision checks',object_body)},
        '/video-review/{id}/outcome':{'post':operation('Record success, partial improvement or remaining work; propose lessons only from confirmed met findings',review_outcome)},
        '/video-review/{id}/refine':{'post':operation('Explicit focused writing pass using saved evidence and preserved findings; requires Idempotency-Key; returns a child review to poll',review_refine)},
        '/video-review/lessons/model/{model}':{'get':operation('Read model-specific learned guide version, lessons and supporting review evidence')},
        '/video-review/lessons/{id}/approve':{'post':operation('Explicitly add or restore a reviewed lesson; expected_revision and expected_guide_version required',object_body)},
        '/video-review/lessons/{id}/dismiss':{'post':operation('Dismiss a lesson proposal without changing the authoring guide',object_body)},
        '/video-review/lessons/{id}/deactivate':{'post':operation('Retract a learned rule from future authoring while preserving evidence and history',object_body)},
        '/jobs/{id}/capture-frame':{'post':operation('Capture a completed video frame locally; no generation usage',{'type':'object','additionalProperties':False,'required':['timestamp_s'],'properties':{'timestamp_s':{'type':'number','minimum':0},'data_url':{'type':'string','description':'Optional browser canvas image; omit for server ffmpeg extraction.'}}})},
        '/assets/{id}/place':{'post':operation('Place an image in a new or revision-checked video scene',{'type':'object','required':['target'],'properties':{'new_scene':{'type':'boolean'},'title':{'type':'string'},'scene_id':{'type':'string'},'expected_revision':{'type':'integer'},'target':{'enum':['first','last','reference','keyframe']},'slot':{'type':'integer','minimum':1,'description':'Keyframe seconds × 3; strictly less than duration × 3.'},'replace':{'type':'boolean'}}})},
        '/audio-references/schema':{'get':operation('Recording preparation and submission support; account entitlement remains unverified')},
        '/audio-references':{'get':operation('List private generation-reference recordings'),'post':operation('Upload audio-only WAV/MP3, at most 64 MB and one hour; Idempotency-Key required',{'type':'object','additionalProperties':False,'required':['name','base64'],'properties':{'name':{'type':'string'},'base64':{'type':'string'}}})},
        '/audio-references/{id}':{'get':operation('Inspect recording metadata and hash')},
        '/audio-references/{id}/download':{'get':operation('Preview original recording bytes in this workspace')},
        '/audio-references/{id}/excerpts':{'post':operation('Prepare immutable excerpt, at most 15 seconds; identical selections reuse the same ID',{'type':'object','additionalProperties':False,'required':['start_s','end_s'],'properties':{'start_s':{'type':'number','minimum':0},'end_s':{'type':'number','exclusiveMinimum':0}}})},
        '/audio-excerpts/{id}':{'get':operation('Inspect immutable excerpt, timing and source hash')},
        '/audio-excerpts/{id}/download':{'get':operation('Preview prepared excerpt bytes in this workspace')},
        '/assets':{'get':operation('List uploaded images'),'post':operation('Upload base64 image',{'type':'object','required':['data_url'],'properties':{'data_url':{'type':'string'},'name':{'type':'string'}}})},
        '/assets/{id}':{'get':operation('Download uploaded image bytes')},
        '/urls':{'get':operation('List reusable public image URLs'),'post':operation('Remember public HTTPS URL',{'type':'object','required':['url'],'properties':{'url':{'type':'string'},'name':{'type':'string'}}})},
        '/references':{'get':operation('List named references, including archived'),'post':operation('Create named reference',object_body)},
        '/references/{id}':{'get':operation('Get named reference'),'put':operation('Replace named reference details',object_body)},
        '/references/{id}/archive':{'post':operation('Archive or restore reference with archived boolean',object_body)},
        '/scenes':{'get':operation('List saved scenes'),'post':operation('Create scene with optional named reference handles',scene_create)},
        '/scenes/{id}':{'get':operation('Get scene and revision'),'put':operation('Replace scene with expected revision',edit),'patch':operation('Edit scene and attach, remove or restore named snapshots',patch)},
        '/scenes/{id}/review-prompt':{'post':operation('Record reviewed human or agent video prompt without generation authorization',{'type':'object','required':['expected_revision','reviewed'],'properties':{'expected_revision':{'type':'integer'},'reviewed':{'const':True},'authored_by':{'enum':['agent','human'],'default':'human'}}})},
        '/scenes/{id}/validate':{'post':operation('Return valid/errors and exact expanded provider request',object_body)},
        '/scenes/{id}/archive':{'post':operation('Archive or restore scene; expected revision required',object_body)},
        '/scenes/{id}/generate':{'post':operation('Generate only with explicit authorization and idempotency key',{'type':'object','required':['approved','expected_revision'],'properties':{'approved':{'type':'boolean','const':True},'expected_revision':{'type':'integer'},'allow_unapproved_start_frame':{'type':'boolean','default':False,'description':'Bypass start-frame approval only; asset must still be named and attached. Logged on generation.'}}})},
        '/workspace':{'get':operation('Current browser workspace scene or null'),'post':operation('Select scene_id, or initialize empty workspace',object_body)},
        '/jobs':{'get':operation('List mode-specific generation history')},'/jobs/{id}':{'get':operation('Get job status, error, request ID and output')},
        '/jobs/{id}/resume':{'post':operation('Resume existing request polling without resubmission',object_body)},
        '/jobs/{id}/download':{'get':operation('Download completed video bytes')},
        '/jobs/{id}/reuse':{'post':operation('Create new scene from history settings and snapshots',object_body)},
        '/image-test':{'post':operation('Original image diagnostic; approved=true required',object_body)}
    }
    from image_studio import IMAGE_RATIOS, IMAGE_MODEL, IMAGE_MODELS
    image_settings={'type':'object','additionalProperties':False,'properties':{
        'n':{'type':'integer','enum':[1,2,4],'default':1,'description':'Candidate count. Native Codex supports 1 only; discover counts per connection through image-studio/schema.'},'prompt':{'type':'string'},'ratio':{'type':'string','enum':list(IMAGE_RATIOS)},
        'model':{'type':'string','enum':list(IMAGE_MODELS),'default':IMAGE_MODEL},
        'resolution':{'type':'string','enum':list(dict.fromkeys(v for m in IMAGE_MODELS.values() for v in m['resolutions']))},'quality':{'type':'string','enum':['low','medium','high','xhigh','max','auto']},
        'base':{'anyOf':[{'$ref':'#/components/schemas/ImageSource'},{'type':'null'}]},
        'extras':{'type':'array','items':{'$ref':'#/components/schemas/ImageSource'}},
        'edit_region':{'type':['object','null'],'properties':{k:{'type':'number','minimum':0,'maximum':1} for k in ('x','y','width','height')},'required':['x','y','width','height']},
        'bindings':{'type':'array','items':{'type':'object','required':['snapshot','selected'],'properties':{'snapshot':{'type':'object','description':'Full immutable named-reference record returned by references API.'},'selected':{'type':'array','uniqueItems':True,'items':{'type':'integer','minimum':0,'maximum':6}}}}}}}
    image_create={'type':'object','properties':{'title':{'type':'string'},'parent_draft_id':{'type':'string','description':'Existing draft whose shot and image version family this draft belongs to.'},'settings':{'$ref':'#/components/schemas/ImageSettings'},'named_references':{'type':'array','items':{'type':'string'}}}}
    paths.update({
        '/image-studio/schema':{'get':operation('Discover image model, allowed values and local limits')},
        '/image-studio/openai-account':{'get':operation('OpenAI API-key presence and managed Codex subscription status; no tokens returned')},
        '/image-studio/openai-account/refresh':{'post':operation('Refresh OpenAI connection status; no generation',object_body)},
        '/image-studio/workspace':{'get':operation('Current image draft or null'),'post':operation('Select draft_id or create an image workspace',object_body)},
        '/image-studio/drafts':{'get':operation('List persistent image drafts'),'post':operation('Create image draft and attach named snapshots',image_create)},
        '/image-studio/drafts/{id}':{'get':operation('Get image draft and revision'),'put':operation('Save image draft with expected_revision',{'type':'object','required':['expected_revision'],'properties':{**image_create['properties'],'expected_revision':{'type':'integer'}}})},
        '/image-studio/drafts/{id}/refresh-reference':{'post':operation('Update one attached asset snapshot from the saved library, preserving selected image identities and renaming mentions',{'type':'object','required':['expected_revision','reference_id'],'properties':{'expected_revision':{'type':'integer'},'reference_id':{'type':'string'}}})},
        '/image-studio/drafts/{id}/validate':{'post':operation('Validate expanded prompt and return exact image request',object_body)},
        '/image-studio/drafts/{id}/versions':{'get':operation('List image drafts in the same version family')},
        '/image-studio/drafts/{id}/review-prompt':{'post':operation('Record explicit human review of the exact current manually written image prompt',{'type':'object','required':['expected_revision','reviewed'],'properties':{'expected_revision':{'type':'integer'},'reviewed':{'const':True}}})},
        '/image-studio/drafts/{id}/generate':{'post':operation('Create image candidates; explicit approval and Idempotency-Key required',{'type':'object','required':['approved','expected_revision'],'properties':{'approved':{'const':True},'expected_revision':{'type':'integer'}}})},
        '/image-studio/jobs':{'get':operation('List mode-specific image candidates and saved settings')},
        '/image-studio/jobs/{id}':{'get':operation('Fetch image status and locally cached outputs')},
        '/image-studio/jobs/{id}/resume':{'post':operation('Resume a saved Grok image request using GET polling only; never resubmits',object_body)},
        '/image-studio/jobs/{id}/discard':{'post':operation('Confirm discarding failed image recovery; retain cached outputs and record an audit entry',{'type':'object','additionalProperties':False,'required':['confirmed','request_id'],'properties':{'confirmed':{'const':True},'request_id':{'type':'string','minLength':1},'reason':{'type':'string','maxLength':500}}})},
        '/image-studio/jobs/{id}/outputs/{asset_id}':{'get':operation('Download one cached candidate by asset ID')},
        '/image-studio/jobs/{id}/download':{'get':operation('Download cached image bytes')},
        '/image-studio/jobs/{id}/reuse':{'post':operation('Create a draft from original settings and identity snapshots',object_body)},
        '/image-studio/jobs/{id}/refine':{'post':operation('Create a refinement draft; no generation',{'type':'object','required':['asset_id'],'properties':{'asset_id':{'type':'string'},'title':{'type':'string'},'prompt':{'type':'string'}}})},
        '/image-studio/jobs/{id}/reference-suggestion':{'post':operation('Suggest editable local reference metadata from approved image generation prompt',{'type':'object','required':['asset_id'],'properties':{'asset_id':{'type':'string'},'category':{'enum':['Location','Character','Prop'],'default':'Location'}}})},
        '/image-studio/jobs/{id}/reference':{'post':operation('Save approved image as a reusable named reference; no generation',{'type':'object','required':['asset_id'],'properties':{'asset_id':{'type':'string'},'title':{'type':'string'},'handle':{'type':'string'},'description':{'type':'string'},'category':{'enum':['Location','Character','Prop']},'images':{'type':'array','items':{'$ref':'#/components/schemas/ImageSource'}}}})},
        '/image-studio/jobs/{id}/approve':{'post':operation('Record human review or revoke image approval',{'type':'object','required':['asset_id','approved'],'properties':{'asset_id':{'type':'string'},'approved':{'type':'boolean'}}})},
        '/image-studio/jobs/{id}/transfer':{'post':operation('Transfer approved image into a new or existing video scene; no generation',{'type':'object','required':['asset_id','target'],'properties':{'new_scene':{'type':'boolean'},'title':{'type':'string'},'asset_id':{'type':'string'},'scene_id':{'type':'string'},'expected_revision':{'type':'integer'},'target':{'enum':['first','last','keyframe','reference']},'slot':{'type':'integer','description':'Keyframe time in one-third-second slots.'},'replace':{'type':'boolean'}}})}
    })
    story_scene={'type':'object','required':['title','text'],'properties':{'id':{'type':'string','description':'Retain a returned scene ID when editing; omit for a new scene.'},'title':{'type':'string','maxLength':120},'text':{'type':'string','maxLength':100000}}}
    story_edit={'type':'object','required':['expected_revision'],'properties':{'expected_revision':{'type':'integer'},'title':{'type':'string'},'notes':{'type':'string'},'scenes':{'type':'array','maxItems':150,'items':story_scene}}}
    paths.update({
        '/stories/schema':{'get':operation('Discover story limits, upload formats and verified writing providers')},
        '/stories/series':{'get':operation('List local series'),'post':operation('Create series',{'type':'object','required':['title'],'properties':{'title':{'type':'string','maxLength':120}}})},
        '/stories/series/{id}':{'get':operation('Get series continuity and asset handles'),'put':operation('Edit series; expected_revision required',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':{'type':'integer'},'title':{'type':'string'},'notes':{'type':'string'},'assets':{'type':'array','items':{'type':'string'}}}})},
        '/stories/episodes':{'get':operation('List episodes and script revisions'),'post':operation('Create an episode in a series',{'type':'object','required':['series_id','title'],'properties':{'series_id':{'type':'string'},'title':{'type':'string'}}})},
        '/stories/episodes/{id}':{'get':operation('Get scene-divided script and versions'),'put':operation('Save episode script while retaining stable scene IDs',story_edit)},
        '/stories/workspace':{'get':operation('Current story episode and selected scene'),'post':operation('Select episode_id and optional scene_id',object_body)},
        '/stories/episodes/{id}/apply-import':{'post':operation('Apply reviewed sections with scene, notes or other types; supporting text appends to episode notes',object_body)},
        '/stories/import-preview':{'post':operation('Parse text or base64 TXT/MD/DOCX; does not change scripts',object_body)},
        '/stories/links':{'get':operation('List linked image/video drafts and immutable script context')},
        '/stories/chats':{'get':operation('List local writing conversation jobs for this mode')},
        '/stories/chats/{id}':{'get':operation('Poll writing reply and proposal; no generation')},
        '/stories/episodes/{id}/context':{'post':operation('Read whole episode or scene at revision; scene_id and revision optional',object_body)},
        '/stories/episodes/{id}/media':{'post':operation('Create linked image/video draft; no generation',{'type':'object','required':['expected_revision','scene_id','kind'],'properties':{'expected_revision':{'type':'integer'},'scene_id':{'type':'string'},'kind':{'enum':['image','video']}}})},
        '/stories/episodes/{id}/chat':{'post':operation('Approved subscription writing message; explicit scope and idempotency key',{'type':'object','required':['expected_revision','message','approved'],'properties':{'expected_revision':{'type':'integer'},'message':{'type':'string','maxLength':12000},'provider':{'const':'codex'},'scope':{'enum':['episode','scene']},'scene_id':{'type':'string'},'previous_episode_ids':{'type':'array','maxItems':5,'items':{'type':'string'}},'approved':{'const':True}}})},
        '/stories/episodes/{id}/apply-proposal':{'post':operation('Apply reviewed writing proposal; rejects stale script revisions',{'type':'object','required':['expected_revision','job_id'],'properties':{'expected_revision':{'type':'integer'},'job_id':{'type':'string'}}})},
        '/stories/episodes/{id}/restore':{'post':operation('Restore a historical revision as a new revision',{'type':'object','required':['expected_revision','revision'],'properties':{'expected_revision':{'type':'integer'},'revision':{'type':'integer'}}})}
    })
    revision={'type':'integer','minimum':1}
    production_create={'type':'object','required':['kind','title'],'properties':{'kind':{'enum':['quick','story']},'title':{'type':'string','minLength':1,'maxLength':120},'brief':{'type':'string','maxLength':20000},'episode_title':{'type':'string','maxLength':120}}}
    shot_create={'type':'object','required':['title'],'properties':{'title':{'type':'string','maxLength':120},'episode_id':{'type':'string'},'story_scene_id':{'type':'string','description':'Required for stories; stable script scene ID.'}}}
    paths.update({
        '/productions':{'get':operation('List productions; idempotently index legacy work'),'post':operation('Create Quick Video or Story / Series with linked drafts; no generation',production_create)},
        '/productions/recent':{'post':operation('Page top-level productions or one story group; archived=true lists Trash; includes child_count, group_id and production_total',{'type':'object','properties':{'offset':{'type':'integer','minimum':0,'default':0},'limit':{'type':'integer','minimum':1,'maximum':100,'default':10},'parent_id':{'type':['string','null'],'description':'Active Story / Series ID; null lists roots'},'archived':{'type':'boolean','default':False}}})},
        '/productions/{id}/membership':{'post':operation('Move a production into a Story / Series; null makes it standalone; preserves scripts, media and timelines',{'type':'object','required':['expected_revision','parent_production_id'],'properties':{'expected_revision':revision,'parent_production_id':{'type':['string','null']}}})},
        '/productions/{id}/trash':{'post':operation('Recoverable deletion; originals retained; grouped children remain available',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision}})},
        '/productions/{id}/restore':{'post':operation('Restore a trashed production and its saved grouping if available',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision}})},
        '/productions/{id}/export':{'post':operation('Start a project ZIP archive with linked assets, Bible, storybooks, prompts, revisions and original media; returns archive task; no generation',{'type':'object','additionalProperties':False,'maxProperties':0})},
        '/project-archives/{id}':{'get':operation('Poll project archive status, completeness report and browser download URL')},
        '/productions/schema':{'get':operation('Discover production stages and supported actions')},
        '/productions/locate':{'post':operation('Locate the production and shot owning an existing media draft',{'type':'object','required':['kind','id'],'properties':{'kind':{'enum':['image','video']},'id':{'type':['string','null'],'description':'Use null with kind video to deselect without deleting the take.'}}})},
        '/productions/context':{'get':operation('Read selected stage, production outline and reusable assets; no credentials')},
        '/productions/workspace':{'get':operation('Read selected production, episode, scene, shot and stage'),'post':operation('Select connected human and agent workspace',{'type':'object','properties':{'production_id':{'type':['string','null']},'episode_id':{'type':['string','null']},'story_scene_id':{'type':['string','null']},'shot_id':{'type':['string','null']},'stage':{'enum':['develop','script','storyboard','generate','edit']},'board_view':{'enum':['board','image']}}})},
        '/productions/{id}':{'get':operation('Get complete production outline, scripts, shot media and takes'),'put':operation('Edit creative brief and title with revision protection',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision,'title':{'type':'string','maxLength':120},'brief':{'type':'string','maxLength':20000}}})},
        '/productions/{id}/versions':{'get':operation('Read production brief revision history')},
        '/productions/{id}/shot-trash':{'get':operation('List recoverable trashed shots')},
        '/productions/{id}/image-branches':{'get':operation('List legacy image branches with verified refinement lineage for explicit reassociation')},
        '/productions/{id}/episodes':{'post':operation('Add episode to a story production',{'type':'object','required':['title'],'properties':{'title':{'type':'string','maxLength':120}}})},
        '/productions/{id}/scenes':{'post':operation('Add script scene to an episode; keep episode title and notes',{'type':'object','required':['episode_id','expected_revision','title'],'properties':{'episode_id':{'type':'string'},'expected_revision':revision,'title':{'type':'string','maxLength':120},'text':{'type':'string','maxLength':100000}}})},
        '/productions/{id}/shots':{'post':operation('Create shot with linked image/video drafts and immutable script context',shot_create)},
        '/productions/shots/{id}':{'get':operation('Read shot, media, current approval status and takes'),'put':operation('Edit shot title, notes, reversible archive state and outline order',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision,'title':{'type':'string','maxLength':120},'notes':{'type':'string','maxLength':10000},'archived':{'type':'boolean'},'shot_order':{'type':'integer','minimum':0,'maximum':10000}}})},
        '/productions/shots/{id}/place-image':{'post':operation('Place approved image in shot video without generation',{'type':'object','required':['expected_revision','expected_video_revision','asset_id','target'],'properties':{'expected_revision':revision,'expected_video_revision':revision,'asset_id':{'type':'string'},'target':{'enum':['first','last','reference','keyframe']},'slot':{'type':'integer','minimum':1},'replace':{'type':'boolean'}}})},
        '/productions/shots/{id}/duplicate':{'post':operation('Explicitly duplicate a shot with independent media drafts and no chosen takes',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision}})},
        '/productions/shots/{id}/merge-image-branch':{'post':operation('Explicitly move a verified legacy refinement branch into shot image versions; preserve media',{'type':'object','required':['expected_revision','branch_id','expected_branch_revision'],'properties':{'expected_revision':revision,'branch_id':{'type':'string'},'expected_branch_revision':revision}})},
        '/productions/shots/{id}/select-take':{'post':operation('Select an approved image or completed video; null clears its selection',{'type':'object','required':['expected_revision','kind','id'],'properties':{'expected_revision':revision,'kind':{'enum':['image','video']},'id':{'type':['string','null'],'description':'Use null to deselect without deleting the take.'}}})},
        '/productions/shots/{id}/refresh-context':{'post':operation('Explicitly refresh linked script context; preserve all prompts and settings; no generation',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision}})}
    })
    selection={'type':'object','required':['production_id'],'properties':{'production_id':{'type':'string'},'episode_id':{'type':['string','null']},'scene_id':{'type':['string','null']},'shot_id':{'type':['string','null']},'scope':{'enum':['production','episode','scene','shot']},'stage':{'enum':['develop','script','storyboard','generate','edit']}}}
    region={'type':['object','null'],'properties':{k:{'type':'number','minimum':0,'maximum':1} for k in ('x','y','width','height')},'required':['x','y','width','height']}
    paths.update({
      '/creative/schema':{'get':operation('Discover assistant providers, scope and reversible action catalog')},
      '/creative/context':{'post':operation('Read exact production-aware assistant context; no provider call',selection)},
      '/creative/messages':{'get':operation('List persistent conversations and activity'),'post':operation('Send one approved subscription message; return a reviewable proposal',{'type':'object','required':['production_id','message','approved'],'properties':{**selection['properties'],'provider':{'enum':['codex','grok']},'model':{'type':'string','description':'Grok model; default configurable; no fallback'},'message':{'type':'string','maxLength':12000},'approved':{'const':True}}})},
      '/creative/messages/{id}':{'get':operation('Poll one reply; never resubmit on timeout')},
      '/creative/messages/{id}/apply':{'post':operation('Atomically apply stored proposal if every target revision still matches; no generation',object_body)},
      '/creative/messages/{id}/undo':{'post':operation('Undo the applied proposal if no later edits would be overwritten',object_body)},
      '/asset-studio/schema':{'get':operation('Discover canonical asset development, views and versions')},
      '/asset-studio':{'get':operation('List reusable assets with revision'),'post':operation('Create character, location or prop',object_body)},
      '/asset-studio/{id}':{'get':operation('Read canonical asset'),'put':operation('Edit metadata/views with expected_revision; existing scene snapshots preserved',object_body)},
      '/asset-studio/{id}/versions':{'get':operation('Read immutable canonical asset versions')},
      '/asset-studio/{id}/restore':{'post':operation('Restore a historical asset as a new version',object_body)},
      '/asset-studio/{id}/archive':{'post':operation('Archive or restore with expected_revision and archived boolean',object_body)},
      '/asset-studio/{id}/develop':{'post':operation('Create an image development draft using canonical identity; no generation',object_body)},
      '/asset-studio/{id}/adopt':{'post':operation('Add approved asset_id view or replace explicit replace_index; expected_revision required',object_body)},
      '/asset-studio/development/lookup':{'post':operation('Find the canonical asset linked to a development draft',object_body)},
      '/precision/schema':{'get':operation('Discover local editing limits and AI region behavior')},
      '/precision/edits':{'post':operation('Save local crop/rotate/resize/paint/erase as a new unapproved image job; originals preserved',{'type':'object','required':['asset_id','operations'],'properties':{'asset_id':{'type':'string'},'draft_id':{'type':'string'},'reference_id':{'type':'string'},'operations':{'type':'array','minItems':1,'maxItems':50,'items':{'type':'object','properties':{'kind':{'enum':['crop','rotate','resize','paint','erase']},'region':region,'degrees':{'enum':[90,180,270]},'width':{'type':'number'},'height':{'type':'integer'},'color':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'},'points':{'type':'array','items':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'number','minimum':0,'maximum':1}}}}}}}})},
      '/precision/refine':{'post':operation('Prepare region refinement in a new or revision-checked draft; no generation',{'type':'object','required':['asset_id'],'properties':{'asset_id':{'type':'string'},'draft_id':{'type':'string'},'expected_revision':revision,'title':{'type':'string'},'region':region,'settings':{'$ref':'#/components/schemas/ImageSettings'}}})}
    })
    edit_source={'type':'object','additionalProperties':False,'required':['kind','id'],'properties':{'kind':{'enum':['take','upload','image']},'id':{'type':'string'}}}
    edit_fields={'title':{'type':'string','maxLength':120},'clips':{'type':'array','maxItems':120,'items':{'type':'object','required':['id','source','in','out'],'properties':{'id':{'type':'string'},'source':edit_source,'in':{'type':'number','minimum':0},'out':{'type':'number','minimum':0},'label':{'type':'string','maxLength':120},'shot_id':{'type':['string','null']},'volume':{'type':'number','minimum':0,'maximum':2}}}},'audio':{'type':'array','maxItems':200,'items':{'type':'object','required':['id','source','in','out','start'],'properties':{'id':{'type':'string'},'source':edit_source,'in':{'type':'number','minimum':0},'out':{'type':'number','minimum':0},'start':{'type':'number','minimum':0},'volume':{'type':'number','minimum':0,'maximum':2},'label':{'type':'string','maxLength':120}}}},'titles':{'type':'array','maxItems':100,'items':{'type':'object','required':['id','text','start','end'],'properties':{'id':{'type':'string'},'text':{'type':'string','maxLength':500},'start':{'type':'number','minimum':0},'end':{'type':'number','minimum':0},'position':{'enum':['top','center','bottom']},'size':{'type':'number','minimum':16,'maximum':96},'color':{'enum':['#ffffff','#aef0ca','#ffdb8a']}}}},'output':{'type':'object','required':['ratio','resolution','fps'],'properties':{'ratio':{'enum':['16:9','9:16','1:1']},'resolution':{'enum':['720p','1080p']},'fps':{'enum':[24,30]}}}}
    edit_fields['clips']['items']['properties']['transition']={'type':'object','additionalProperties':False,'required':['type','duration'],'properties':{'type':{'enum':['cut','dissolve','fade']},'duration':{'type':'number','minimum':0,'maximum':2}},'description':'Incoming overlap in whole output frames, at most half either neighboring clip; first clip uses cut.'}
    for group in ('clips','audio'):
        props=edit_fields[group]['items']['properties']
        props.update(audio_fade_in={'type':'number','minimum':0,'maximum':2,'default':0},audio_fade_out={'type':'number','minimum':0,'maximum':2,'default':0},normalize={'type':'boolean','default':False})
    edit_fields['clips']['items']['properties']['render_link']={'type':'object','readOnly':True,'description':'Derived from rendered source media; source timeline_id, revision, export_id.','properties':{'timeline_id':{'type':'string'},'revision':{'type':'integer'},'export_id':{'type':'string'}}}
    edit_fields['clips']['items']['properties']['audio_offset']={'type':'number','minimum':-2,'maximum':2,'default':0,'description':'Whole frames; requires source handles.'}
    edit_fields['audio']['items']['properties']['lane']={'enum':['dialogue','music','sfx'],'default':'sfx'}
    edit_fields['output']['properties'].update(cut_audio_crossfade_frames={'type':'integer','minimum':0,'maximum':12,'default':2},loudness_target_lufs={'type':['number','null'],'minimum':-30,'maximum':-10,'default':None},ducking={'type':'object','description':'Normalize stems before bounded dry/wet sidechain ducking; target is a stem target when enabled. No post-duck loudness pass.','additionalProperties':False,'properties':{'enabled':{'type':'boolean','default':False},'amount_db':{'type':'number','minimum':0,'maximum':24,'default':10},'attack_ms':{'type':'number','minimum':5,'maximum':500,'default':80},'release_ms':{'type':'number','minimum':50,'maximum':2000,'default':400}}})
    edit_source={'oneOf':[edit_source,{'type':'object','additionalProperties':False,'required':['kind'],'properties':{'kind':{'const':'gap'}}}]}
    edit_fields['clips']['items']['properties']['source']=edit_source
    props=edit_fields['clips']['items']['properties']
    props.update(flip_h={'type':'boolean','default':False},flip_v={'type':'boolean','default':False},speed={'type':'number','minimum':.25,'maximum':4,'default':1},speed_audio={'enum':['preserve_pitch','mute'],'default':'preserve_pitch'},hold_start={'type':'number','minimum':0,'maximum':10,'default':0},hold_end={'type':'number','minimum':0,'maximum':10,'default':0},color={'type':'string','pattern':'^#[0-9a-fA-F]{6}$','default':'#000000'})
    for name,fields in [('crop',{'x':(0,1,0),'y':(0,1,0),'w':(.1,1,1),'h':(.1,1,1)}),('zoom',{'scale':(1,3,1),'x':(0,1,.5),'y':(0,1,.5)})]:
        props[name]={'type':'object','additionalProperties':False,'required':list(fields),'properties':{k:{'type':'number','minimum':v[0],'maximum':v[1],'default':v[2]} for k,v in fields.items()}}
    edit_fields['captions']={'type':'array','maxItems':2000,'items':{'type':'object','additionalProperties':False,'required':['id','start','end','text'],'properties':{'id':{'type':'string'},'start':{'type':'number','minimum':0},'end':{'type':'number','minimum':0},'text':{'type':'string','maxLength':2000},'speaker':{'type':'string','maxLength':80}}}}
    edit_fields['output']['properties']['resolution']['enum']=['480p','720p','1080p','source']
    edit_fields['output']['properties']['captions']={'type':'object','additionalProperties':False,'properties':{'mode':{'enum':['off','burn_in','sidecar','both'],'default':'off'},'position':{'enum':['top','center','bottom'],'default':'bottom'},'size':{'type':'number','minimum':16,'maximum':96,'default':48},'color':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$','default':'#ffffff'},'max_chars_per_line':{'type':'integer','minimum':8,'maximum':80,'default':32}}}
    edit_fields['markers']={'type':'array','maxItems':500,'items':{'type':'object','additionalProperties':False,'required':['id','time'],'properties':{'id':{'type':'string'},'time':{'type':'number','minimum':0},'label':{'type':'string','maxLength':80},'note':{'type':'string','maxLength':2000},'color':{'enum':['#aef0ca','#ffdb8a','#ff8888','#88bbff'],'default':'#aef0ca'},'clip_id':{'type':'string'},'clip_time':{'type':'number','minimum':0}}}}
    edit_fields['clips']['items']['properties']['color']={'oneOf':[{'type':'string','pattern':'^#[0-9a-fA-F]{6}$','description':'Gap color'}, {'type':'object','additionalProperties':False,'properties':{k:{'type':'number','minimum':v[0],'maximum':v[1],'default':v[2]} for k,v in {'brightness':(-.5,.5,0),'contrast':(.5,2,1),'saturation':(0,2,1),'temperature':(-1,1,0)}.items()}}]}
    edit_scope={'type':'object','required':['production_id'],'properties':{'production_id':{'type':'string'},'episode_id':{'type':['string','null']}}}
    paths.update({
      '/editing/transcription':{'get':operation('Read local model path, availability and settings revision; no downloads'),'put':operation('Configure a workspace local model folder without downloads',{'type':'object','additionalProperties':False,'required':['expected_revision','local_transcription_model'],'properties':{'expected_revision':{'type':'integer','minimum':0},'local_transcription_model':{'type':['string','null'],'maxLength':2000,'description':'Absolute local converted Whisper model folder; null uses configured/default path.'}}})},
      '/editing/schema':{'get':operation('Discover local editor limits, media sources and output settings')},
      '/editing/timelines/open':{'post':operation('Open primary timeline in quick video, episode or optional story_scene_id scope',{**edit_scope,'properties':{**edit_scope['properties'],'story_scene_id':{'type':['string','null']}}})},
      '/editing/timelines/{id}':{'get':operation('Read edit and revision'),'put':operation('Save sequence, trims, audio, titles or output with expected_revision',{'type':'object','required':['expected_revision'],'properties':{**edit_fields,'expected_revision':revision}})},
      '/editing/sources':{'post':operation('List videos/images from this production and active grouped descendants, reusable assets and uploads',edit_scope)},
      '/editing/inspect':{'post':operation('Inspect source duration, dimensions and audio without generation',{'type':'object','required':['source'],'properties':{'source':edit_source,'background':{'type':'boolean','default':False,'description':'Return cached/basic metadata immediately; queue local probe/optional analysis without downloading uncached takes.'},'analyze_loudness':{'type':'boolean','description':'Optional analysis: defaults to false with background=true and true for the original foreground request; explicit false skips loudness.'}}})},
      '/editing/media':{'get':operation('List private media uploads'),'post':operation('Upload local video/audio/images up to 64 MB; validate media before storing',{'type':'object','required':['name','base64'],'properties':{'name':{'type':'string'},'base64':{'type':'string'}}})},
      '/editing/media/{id}/download':{'get':operation('Download private source media')},
      '/editing/exports':{'get':operation('List local export history'),'post':operation('Export an immutable saved edit snapshot locally; no provider usage',{'type':'object','required':['timeline_id','expected_revision'],'properties':{'timeline_id':{'type':'string'},'expected_revision':revision}})},
      '/editing/timelines/{id}/preview':{'post':operation('Local preview export, draft 360p ultrafast CRF30 or full (default)',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision,'quality':{'enum':['draft','full'],'default':'full'}}})},
      '/editing/exports/{id}/frame':{'post':operation('Grab a frame from a full or draft export',{'type':'object','required':['expected_revision','timestamp_s'],'properties':{'expected_revision':revision,'timestamp_s':{'type':'number','minimum':0}}})},
      '/editing/timelines/{id}/captions/import':{'post':operation('Import literal SRT cues with revision protection',{'type':'object','required':['expected_revision','srt'],'properties':{'expected_revision':revision,'srt':{'type':'string','maxLength':2000000}}})},
      '/editing/timelines/{id}/captions/transcribe':{'post':operation('Transcribe using an installed local engine and model only; 503 if unavailable',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision}})},
      '/editing/caption-jobs/{id}':{'get':operation('Poll local caption transcription')},
      '/editing/exports/{id}/captions.srt':{'get':operation('Download exported SRT sidecar')},
      '/editing/takes/select':{'post':operation('Select a completed shot video take using the existing production selection rules',{'type':'object','additionalProperties':False,'required':['shot_id','take_id','expected_shot_revision'],'properties':{'shot_id':{'type':'string'},'take_id':{'type':['string','null']},'expected_shot_revision':revision}})},
      '/editing/timelines/{id}/revisions':{'get':operation('List saved revisions newest first')},
      '/editing/timelines/{id}/revisions/{n}':{'get':operation('Read a complete migrated saved revision')},
      '/editing/timelines/{id}/revisions/{n}/restore':{'post':operation('Restore saved contents as a new revision, preserving history',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision}})},
      '/editing/exports/{id}':{'get':operation('Poll progress and completion of a local export')},
      '/editing/exports/{id}/cancel':{'post':operation('Cancel local render, preserving edit and originals',object_body)},
      '/editing/exports/{id}/download':{'get':operation('Download completed MP4')},
      '/editing/exports/{id}/manifest':{'get':operation('Get immutable JSON edit manifest')},
      '/studio-account':{'get':operation('Read safe workspace identity and connection state')},
      '/studio-account/api-key':{'post':operation('Set or remove this private workspace OpenAI key; never returned',{'type':'object','required':['key'],'properties':{'key':{'type':['string','null'],'writeOnly':True}}})}
    })
    from filmmaking_studio import SCHEMA as world_plan
    world_answers={'type':'object','additionalProperties':False,'properties':{k:{'type':'string','maxLength':n} for k,n in {'title':120,'idea':6000,'genre':120,'tone':240,'theme':1000,'audience':240,'duration':120,'characters':6000,'locations':4000,'plot':6000,'style':2000,'rules':4000}.items()}}
    paths.update({
      '/filmmaking/schema':{'get':operation('Discover world planning and local shot direction tools')},
      '/filmmaking/series/{id}/bible':{'get':operation('Read independent Series Bible and read-only legacy provenance'),'put':operation('Save shared foundation, cast with voice directions/presets, locations and props; expected_revision required',object_body)},
      '/filmmaking/series/{id}/library':{'get':operation('Read reusable series entities and canonical reference versions'),'post':operation('Explicitly add an existing Asset Studio reference to this series',object_body)},
      '/filmmaking/series/{id}/library/promote':{'post':operation('Promote an episode entity for future reuse; expected_revision required; previous episode snapshots stay intact',object_body)},
      '/filmmaking/series/{id}/workshop':{'get':operation('Read Series Bible visual development'),'post':operation('Prepare characters, locations and props before writing any screenplay; no generation',object_body)},
      '/filmmaking/series/{id}/generate':{'post':operation('Generate explicitly approved subscription reference images from a reviewed custom or AI prompt; series id or production id accepted',object_body)},
      '/filmmaking/episodes/{id}/book':{'get':operation('Read an independent Episode Book, current script and frozen series inheritance'),'put':operation('Save episode questionnaire, cards and selected_asset_ids; refresh_inheritance explicit; title changes require expected_episode_revision',object_body)},
      '/filmmaking/episodes/{id}/library':{'get':operation('Read reusable series assets plus this episode\'s local entities')},
      '/filmmaking/episodes/{id}/workshop':{'get':operation('Read episode character, location and prop development'),'post':operation('Prepare this episode\'s visual cards; no generation',object_body)},
      '/filmmaking/episodes/{id}/generate':{'post':operation('Generate explicitly approved subscription references scoped to this episode',object_body)},
      '/filmmaking/episodes/{id}/jobs':{'get':operation('List plans belonging only to this episode in the current mode')},
      '/filmmaking/episodes/{id}/plan':{'post':operation('Plan selected episode with frozen series/asset context; explicit approval, book and episode revisions required',object_body)},
      '/filmmaking/episodes/{id}/upload-ai-review':{'post':operation('Start explicit AI semantic duplicate review; text, provider, expected_revision and approved:true; returns async job; requires idempotency key',object_body)},
      '/filmmaking/episodes/{id}/upload-ai-review/{review_id}':{'get':operation('Read status, error or exact-source comparisons from an episode upload AI review')},
      '/filmmaking/episodes/{id}/upload-preview':{'post':operation('Locally compare uploaded text or file metadata with Bible, Storybook and selected asset snapshots; returns comparisons and a review_token; no changes',object_body)},
      '/filmmaking/episodes/{id}/upload-apply':{'post':operation('Apply explicit uploaded/app/both choices with source, review_token, book/episode revisions, replace_existing and optional allow_dialogue_polish; retains original upload and previous state',object_body)},
      '/filmmaking/episodes/{id}/complete-production':{'post':operation('Complete production details from an immutable script; approval, provider, book/episode revisions, and optional allow_dialogue_polish; review uncertain identity matches and dialogue suggestions separately',object_body)},
      '/filmmaking/episodes/{id}/production-review':{'post':operation('Confirm production choices with job_id, expected_revision, resolutions mapping uncertain mention IDs to catalog IDs or new, and accepted_dialogue unit IDs; required before storyboard handoff',object_body)},
      '/filmmaking/episodes/{id}/apply':{'post':operation('Apply reviewed plan to selected episode only; preserves script versions, scene IDs and old media; explicit replace_existing protects existing scripts',object_body)},
      '/filmmaking/episodes/{id}/trash-script':{'post':operation('Move the episode script to Trash with revision protection; preserves media',object_body)},
      '/filmmaking/episodes/{id}/upload-ai-review/{review_id}':{'get':operation('Read semantic upload review scoped to this episode')},
      '/filmmaking/episodes/{id}/script':{'post':operation('Save manual or imported Episode Book script into selected episode; review and explicit replacement required for an existing script',object_body)},
      '/filmmaking/episodes/{id}/storyboard':{'post':operation('Prepare scene-linked storyboard from saved script without contacting a provider; idempotent',object_body)},
      '/filmmaking/episodes/{id}/refresh-assets':{'post':operation('Explicitly update draft references in revision-checked selected shots of this episode; selected takes protected unless allow_completed',object_body)},
      '/filmmaking/worlds/{id}':{'get':operation('Read guided world questionnaire for a production'),'put':operation('Save guided answers and structured cast/place/act cards',{'type':'object','required':['expected_revision','answers'],'properties':{'expected_revision':{'type':'integer','minimum':0},'answers':world_answers,'guide':{'type':'object','description':'cast (8), places (4), acts (8), script (60000 characters); cards have id, structured fields, reference_ids and palette'}}})},
      '/filmmaking/worlds/{id}/workshop':{'get':operation('Read visual entities, candidate galleries and generation batches'),'post':operation('Prepare visual studios from a reviewed story; no generation',object_body)},
      '/filmmaking/worlds/{id}/import-preview':{'post':operation('Parse TXT, Markdown, Fountain, DOCX or pasted text into reviewable book fields locally; no saved changes',object_body)},
      '/filmmaking/worlds/{id}/reference':{'post':operation('Upload a local reference image and extract its five-color palette',object_body)},
      '/filmmaking/worlds/{id}/generate':{'post':operation('Generate an explicitly approved batch of 1-8 subscription images; Idempotency-Key required',object_body)},
      '/filmmaking/worlds/{id}/bible.pdf':{'get':{'summary':'Download illustrated story bible with confirmed images','responses':{'200':{'description':'PDF document','content':{'application/pdf':{'schema':{'type':'string','format':'binary'}}}}}}},
      '/filmmaking/entities/{id}':{'put':operation('Save character or location details with expected_revision',object_body)},
      '/filmmaking/entities/{id}/views':{'post':operation('Prepare outfit sheets or location coverage using the confirmed reference',object_body)},
      '/filmmaking/entities/{id}/upload':{'post':operation('Use an uploaded image as the confirmed main identity',object_body)},
      '/filmmaking/assets/{id}/confirm':{'post':operation('Confirm own candidate; preserve identity and connect relevant storyboard shots',object_body)},
      '/filmmaking/renders/{id}/cancel':{'post':operation('Stop unsent requests after the current image finishes',object_body)},
      '/filmmaking/worlds/{id}/plan':{'post':operation('Build one subscription writing plan; explicit approval and idempotency required',{'type':'object','required':['expected_revision','approved','provider'],'properties':{'expected_revision':{'type':'integer'},'approved':{'const':True},'provider':{'enum':['codex','grok']},'revision_of':{'type':'string'},'expected_job_revision':{'type':'integer'},'scene_index':{'type':'integer','minimum':0},'instruction':{'type':'string','maxLength':2000}}})},
      '/filmmaking/worlds/{id}/jobs':{'get':operation('List this production world plans in the current mode')},
      '/filmmaking/worlds/{id}/assets':{'get':operation('List prepared asset views, candidates and approval state')},
      '/filmmaking/jobs/{id}':{'get':operation('Read plan status and result'),'put':operation('Save reviewed plan before applying',{'type':'object','required':['expected_revision','result'],'properties':{'expected_revision':{'type':'integer'},'result':world_plan}})},
      '/filmmaking/jobs/{id}/fork':{'post':operation('Copy a completed script as a new editable draft; preserves connected visuals and prior version',object_body)},
      '/filmmaking/jobs/{id}/apply':{'post':operation('Create a new episode, linked shots and asset drafts without generating media',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':{'type':'integer'},'result':world_plan,'image_model':{'enum':['gpt-image-2','grok-imagine-image-2.0']}}})},
      '/filmmaking/assets/{id}/adopt':{'post':operation('Adopt an approved candidate from this planned view as a canonical asset',{'type':'object','required':['expected_revision','asset_id'],'properties':{'expected_revision':{'type':'integer'},'asset_id':{'type':'string'}}})},
      '/filmmaking/shots/{id}':{'get':operation('Read saved 3D staging and revision'),'put':operation('Save camera, subject poses and staging; local operation',{'type':'object','required':['expected_revision','staging'],'properties':{'expected_revision':{'type':'integer','minimum':0},'staging':{'type':'object','description':'camera{yaw,elevation,distance,target_x,target_y,target_z,lens}, subjects[{name,asset_id,x,z,rotation,pose,arms,head}], ratio, environment, style'}}})},
      '/filmmaking/shots/{id}/opening-frame':{'get':operation('Read latest opening-frame proposal; no provider request'),'post':operation('Prepare first-frame direction using the selected image model provider writing connection; cached when unchanged; requires Idempotency-Key',{'type':'object','required':['expected_revision','expected_image_revision','approved'],'properties':{'expected_revision':revision,'expected_image_revision':revision,'approved':{'const':True},'force':{'type':'boolean','default':False}}})},
      '/filmmaking/opening-frame-jobs/{id}':{'get':operation('Poll mode-specific opening-frame preparation, prompt, references and review notes')},
      '/filmmaking/shots/{id}/opening-frame/apply':{'post':operation('Apply opening-frame prompt and frozen reference snapshots; revision/source checked; original settings backed up; no media generation',{'type':'object','required':['job_id','expected_revision','expected_image_revision'],'properties':{'job_id':{'type':'string'},'expected_revision':revision,'expected_image_revision':revision,'replace_prompt':{'type':'boolean','description':'Explicitly replace an edited prompt or a draft with image takes; otherwise only an unchanged starter draft can be applied.'}}})},
      '/filmmaking/shots/{id}/opening-frame/restore':{'post':operation('Restore pre-preparation image settings only if no newer edits exist',{'type':'object','required':['job_id','expected_revision','expected_image_revision'],'properties':{'job_id':{'type':'string'},'expected_revision':revision,'expected_image_revision':revision}})},
      '/filmmaking/shots/{id}/video-direction':{'get':operation('Read latest AI video direction, timing proposal and default writing provider; no provider call'),'post':operation('Prepare shot motion, compact identity cues and supported duration; no media generation; Idempotency-Key required',{'type':'object','required':['expected_revision','expected_video_revision','approved'],'properties':{'expected_revision':revision,'expected_video_revision':revision,'approved':{'const':True},'provider':{'enum':['codex','grok']},'instruction':{'type':'string','maxLength':2000,'description':'Optional human direction for camera, pacing, performance or corrections to the previous preparation. Stored with the proposal.'},'force':{'type':'boolean','default':False}}})},
      '/filmmaking/video-direction-jobs/{id}':{'get':operation('Poll mode-specific video direction, one-sentence asset summaries, duration reason and notes')},
      '/filmmaking/shots/{id}/video-direction/apply':{'post':operation('Apply reviewed prompt, scene-only identity cues and duration; source/revision checked and prior settings backed up',{'type':'object','required':['job_id','expected_revision','expected_video_revision'],'properties':{'job_id':{'type':'string'},'expected_revision':revision,'expected_video_revision':revision,'replace_settings':{'type':'boolean','description':'Explicitly replace existing direction or timing; otherwise only an unchanged starter draft may apply.'}}})},
      '/filmmaking/shots/{id}/video-direction/restore':{'post':operation('Restore previous video settings only before newer edits',{'type':'object','required':['job_id','expected_revision','expected_video_revision'],'properties':{'job_id':{'type':'string'},'expected_revision':revision,'expected_video_revision':revision}})},
      '/filmmaking/shots/{id}/compose':{'post':operation('Transfer PNG staging and direction into the linked image draft; no generation',{'type':'object','required':['expected_revision','expected_image_revision','prompt','data_url'],'properties':{'expected_revision':{'type':'integer'},'expected_image_revision':{'type':'integer'},'prompt':{'type':'string','maxLength':2200},'data_url':{'type':'string','description':'PNG data URL, at most 3 MB decoded and 4 million pixels'}}})},
      '/filmmaking/shots/{id}/movement':{'post':operation('Append reviewed camera direction to the video prompt without generating',{'type':'object','required':['expected_revision','prompt'],'properties':{'expected_revision':{'type':'integer'},'prompt':{'type':'string','maxLength':1500}}})}
    })
    from agent_parity_contracts import contracts
    parity_schemas=contracts(paths,operation)
    from handoff_contracts import contracts as handoff_contracts
    parity_schemas.update(handoff_contracts(paths,operation))
    from camera_contracts import contracts as camera_contracts
    parity_schemas.update(camera_contracts(paths,operation))
    reconnect={'type':'object','additionalProperties':False,'required':['id','status','step','human_action_required','error','requested_at','updated_at'],'properties':{
        'id':{'type':['string','null'],'description':'Opaque request ID; never a credential or verification code.'},
        'status':{'enum':['idle','pending','connected','error']},'step':{'enum':['none','human_start','device_verification','complete','error']},
        'human_action_required':{'type':'boolean'},'error':{'type':['string','null']},
        'requested_at':{'type':['number','null']},'updated_at':{'type':['number','null']}}}
    parity_schemas['CodexReconnectStatus']=reconnect
    safe_auth={'type':'object','additionalProperties':False,'properties':{'id':{'type':'string'},'status':{'type':'string'},'kind':{'type':'string'}}}
    parity_schemas['WorkspaceAccountStatus']={'type':'object','additionalProperties':False,'required':['workspace_id','kind','name','verified','mock_identity','isolated','can_restore_guest','accounts','auth','codex_reconnect','identity_provider','grok_identity_available','local_only'],'properties':{
        'workspace_id':{'type':'string','description':'Authenticated workspace; cannot be selected in a reconnect request.'},'kind':{'type':'string'},'name':{'type':'string'},
        **{name:{'type':'boolean'} for name in ('verified','mock_identity','isolated')},'can_restore_guest':{'const':False},
        'accounts':{'type':'array','maxItems':0,'items':{'type':'object'}},'auth':safe_auth,'codex_reconnect':{'$ref':'#/components/schemas/CodexReconnectStatus'},
        'identity_provider':{'const':'ChatGPT'},'grok_identity_available':{'const':False},'grok_identity_message':{'type':'string'},
        'grok_connection':{'type':'object','properties':{'signed_in':{'type':'boolean'},'status':{'type':'string'},'verified':{'const':False},'message':{'type':'string'}}},'local_only':{'const':True}}}
    paths['/studio-account']['get']['responses']['200']={'description':'Safe current-workspace status; no device URLs/codes or other identities','content':{'application/json':{'schema':{'$ref':'#/components/schemas/WorkspaceAccountStatus'}}}}
    paths['/studio-account/codex']={
        'post':operation('Request human-started ChatGPT reconnection for this workspace; never starts device verification',{'type':'object','additionalProperties':False,'maxProperties':0}),
        'get':operation('Poll reconnect request outcome; connected does not verify model access, generation or quota')}
    for method,code in (('post','202'),('get','200')):
        paths['/studio-account/codex'][method]['responses']={code:{'description':'Safe reconnect request status','content':{'application/json':{'schema':{'$ref':'#/components/schemas/CodexReconnectStatus'}}}},'400':{'description':'Invalid body; no workspace or identity selectors accepted'},'401':{'description':'Invalid or missing workspace token'},'403':{'description':'Workspace authorization required'},'409':{'description':'Workspace scope changed'}}
    parity_schemas['PromptGuideProvenance']={'type':'object','required':['contract_version','targets','guides'],'properties':{
        'contract_version':{'type':'integer'},'targets':{'type':'array','items':{'type':'object','required':['model'],'properties':{'model':{'type':'string'},'fields':{'type':'array','items':{'type':'string'}},'operation':{'type':'string'}}}},
        'guides':{'type':'array','items':{'type':'object','required':['file','sha256'],'properties':{'file':{'type':'string'},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}}}}}}
    parity_schemas['PromptPreparationJob']={'type':'object','required':['id','revision','kind','media_id','media_revision','provider','status','mock','provenance'],'properties':{
        'id':{'type':'string'},'revision':revision,'kind':{'enum':['image','video']},'media_id':{'type':'string'},'media_revision':revision,'provider':{'enum':['codex','grok']},'status':{'enum':['pending','done','error']},'mock':{'type':'boolean'},'applied':{'type':'boolean'},
        'provenance':{'$ref':'#/components/schemas/PromptGuideProvenance'},'result':{'type':['object','null'],'properties':{'prompt':{'type':'string'},'notes':{'type':'array','items':{'type':'string'}},'asset_summaries':{'type':'array','items':{'type':'object'}}}},'error':{'type':['string','null']},
        'writing_usage':{'type':'object','properties':{k:{'type':['integer','null'],'minimum':0} for k in ('input_tokens','output_tokens','cached_input_tokens','cache_write_input_tokens')}},'writing_returned_model':{'type':['string','null']},'writing_duration_ms':{'type':['integer','null'],'minimum':0}}}
    job_response={'description':'Saved prompt preparation; no media render','content':{'application/json':{'schema':{'$ref':'#/components/schemas/PromptPreparationJob'}}}}
    paths['/prompting/schema']={'get':operation('Discover mandatory guide-backed AI preparation and supported writer connections')}
    paths['/prompting/jobs/{id}']={'get':operation('Read a saved prompt job, guide provenance, notes and available writer cache usage')}
    paths['/prompting/jobs/{id}']['get']['responses']['200']=job_response
    for kind in ('image','video'):
        path='/prompting/'+kind+'/{id}'
        paths[path]={'get':operation('Read preparation readiness for the current '+kind+' draft'),
            'post':operation('Prepare a reviewable AI prompt with the complete applicable guide; no render; requires Idempotency-Key',{'type':'object','required':['expected_revision','approved'],'properties':{'expected_revision':revision,'approved':{'const':True},'provider':{'enum':['codex','grok']},'brief':{'type':'string','maxLength':50000},'instruction':{'type':'string','maxLength':2000},'force':{'type':'boolean'}}})}
        paths[path+'/apply']={'post':operation('Use the reviewed AI prompt; current guide/source/revision checked; no render',{'type':'object','required':['job_id','expected_revision','expected_media_revision'],'properties':{'job_id':{'type':'string'},'expected_revision':revision,'expected_media_revision':revision,'prompt':{'type':'string','maxLength':50000,'description':'Optional user revision of the AI-authored proposal, validated before application.'}}})}
        paths[path]['post']['responses']['202']=job_response
        paths[path]['get']['responses']['200']={'description':'Preparation status for the current saved inputs','content':{'application/json':{'schema':{'type':'object','required':['current','model','job','provenance'],'properties':{'current':{'type':'boolean'},'model':{'type':'string'},'job':{'anyOf':[{'$ref':'#/components/schemas/PromptPreparationJob'},{'type':'null'}]},'provenance':{'anyOf':[{'$ref':'#/components/schemas/PromptGuideProvenance'},{'type':'null'}]}}}}}}
        paths[path+'/apply']['post']['responses']['200']={
            'description':'Reviewed prompt saved; no media render',
            'content':{'application/json':{'schema':{
                'type':'object','required':['job','draft'],
                'properties':{'job':{'$ref':'#/components/schemas/PromptPreparationJob'},'draft':{'type':'object'}}
            }}}
        }
    paths['/filmmaking/assets/{id}/bible-change-preview']={'post':operation('Preview explicit descriptive changes from an own main candidate; no writing, generation or Bible update',{'type':'object','required':['expected_revision','expected_entity_revision','asset_id','changes'],'properties':{'expected_revision':revision,'expected_entity_revision':revision,'asset_id':{'type':'string'},'changes':{'type':'object','additionalProperties':{'type':'string'}},'image_layout':{'type':'string'}}})}
    paths['/filmmaking/assets/{id}/bible-change-confirm']={'post':operation('Approve the exact stored image-to-Bible preview; revision conflicts require a new preview',{'type':'object','required':['preview_id','approved'],'properties':{'preview_id':{'type':'string'},'approved':{'type':'boolean'},'authored_by':{'enum':['human','agent']}}})}
    paths['/filmmaking/assets/{id}/prompt-draft']={'post':operation('Build a workshop creative brief using current canonical details and inputs, or reuse an unchanged reviewed preparation; never writes final AI prose or renders',{'type':'object','required':['expected_revision'],'properties':{'expected_revision':revision,'model':{'type':'string'},'brief':{'type':'string'}}})}
    from agent_completion_contracts import contracts as completion_contracts
    parity_schemas.update(completion_contracts(paths,operation))
    paths['/workspace/status']['get']['responses']['200']={'description':'Opaque change tokens; compare equality only','content':{'application/json':{'schema':{'type':'object','required':['revision','areas'],'additionalProperties':False,'properties':{'revision':{'type':'string'},'areas':{'type':'object','additionalProperties':{'type':'string'}}}}}}}
    paths['/library/page']['post']['responses']['200']={'description':'Summary cards and original-image download metadata for this page','content':{'application/json':{'schema':{'type':'object','required':['items','originals','total','offset','limit','has_more'],'properties':{'items':{'type':'array','items':{'type':'object'}},'originals':{'type':'array','items':{'type':'object'}},'total':{'type':'integer'},'offset':{'type':'integer'},'limit':{'type':'integer'},'has_more':{'type':'boolean'}}}}}}
    paths['/productions/{id}/summary']['get']['responses']['200']={'description':'Compact display metadata; archives retained in detailed endpoints','content':{'application/json':{'schema':{'type':'object','required':['production','episodes','shots','summary'],'properties':{'production':{'type':'object'},'episodes':{'type':'array','items':{'type':'object'}},'shots':{'type':'array','items':{'type':'object'}},'summary':{'const':True}}}}}}
    for path in ('/scenes/{id}/jobs','/image-studio/drafts/{id}/jobs','/editing/export-summaries'):
        paths[path]['get']['responses']['200']={'description':'Workspace-scoped records','content':{'application/json':{'schema':{'type':'array','items':{'type':'object'}}}}}
    # Local recording contracts deliberately publish no invented provider payload.
    audio_source={'type':'object','required':['id','revision','media_id','duration','sha256','provider_upload_id'],
        'properties':{'id':{'type':'string'},'revision':{'const':1},'media_id':{'type':'string'},
            'name':{'type':'string'},'duration':{'type':'number'},'bytes':{'type':'integer'},
            'format':{'enum':['wav','mp3']},'sha256':{'type':'string'},'provider_upload_id':{'type':'null'}}}
    audio_excerpt={'type':'object','required':['id','reference_id','start_s','end_s','duration','media_id','sha256','source_sha256','provider_upload_id'],
        'properties':{**audio_source['properties'],'reference_id':{'type':'string'},'start_s':{'type':'number'},
            'end_s':{'type':'number'},'source_sha256':{'type':'string'}}}
    parity_schemas.update(AudioReference=audio_source,AudioExcerpt=audio_excerpt,
        UploadedAudioCapability={'type':'object','required':['local_preparation','generation_enabled','access','contract','reason','provider_formats','provider_limits'],
            'properties':{'local_preparation':{'const':True},'generation_enabled':{'const':True},
                'access':{'const':'unverified'},'contract':{'const':'reference_audios.url'},'reason':{'type':'string'},
                'provider_formats':{'type':'null'},'provider_limits':{'type':'null'}}})
    for path,method,code,schema in (
        ('/audio-references/schema','get','200',{'$ref':'#/components/schemas/UploadedAudioCapability'}),
        ('/audio-references','get','200',{'type':'array','items':{'$ref':'#/components/schemas/AudioReference'}}),
        ('/audio-references','post','201',{'$ref':'#/components/schemas/AudioReference'}),
        ('/audio-references/{id}','get','200',{'$ref':'#/components/schemas/AudioReference'}),
        ('/audio-references/{id}/excerpts','post','201',{'$ref':'#/components/schemas/AudioExcerpt'}),
        ('/audio-excerpts/{id}','get','200',{'$ref':'#/components/schemas/AudioExcerpt'})):
        paths[path][method]['responses'][code]={'description':'Private workspace recording preparation; no provider submission',
            'content':{'application/json':{'schema':schema}}}
    paths['/audio-references']['post']['parameters']=[{'in':'header','name':'Idempotency-Key','required':True,
        'schema':{'type':'string','minLength':8,'maxLength':100,'pattern':'^[A-Za-z0-9_-]+$'}}]
    for path in ('/audio-references/{id}/download','/audio-excerpts/{id}/download'):
        paths[path]['get']['responses']['200']={'description':'Private recording bytes; no-store',
            'content':{mime:{'schema':{'type':'string','format':'binary'}} for mime in ('audio/wav','audio/mpeg')}}
    from song_contracts import contracts as song_contracts
    parity_schemas.update(song_contracts(paths,operation))
    for path,methods in paths.items():
        for method,op in methods.items():
            op['operationId']=method+'_'+path.strip('/').replace('/','_').replace('{id}','by_id').replace('.','_')
            for name in re.findall(r'\{([^}]+)\}',path):op.setdefault('parameters',[]).append({'in':'path','name':name,'required':True,'schema':{'type':'string'}})
    paths['/filmmaking/worlds/{id}/plan']['post']['parameters'].append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}})
    for path in ('/filmmaking/worlds/{id}/generate','/image-test','/filmmaking/shots/{id}/opening-frame','/filmmaking/shots/{id}/video-direction'):
        paths[path]['post'].setdefault('parameters',[]).append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100,'pattern':'^[A-Za-z0-9_-]+$'}})
    for path in ('/filmmaking/series/{id}/generate','/filmmaking/episodes/{id}/generate','/filmmaking/episodes/{id}/plan','/filmmaking/episodes/{id}/complete-production','/filmmaking/episodes/{id}/upload-ai-review','/filmmaking/episodes/{id}/storyboard'):
        paths[path]['post']['parameters'].append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}})
    paths['/scenes/{id}/generate']['post']['parameters'].append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100,'pattern':'^[A-Za-z0-9_-]+$'}})
    paths['/image-studio/drafts/{id}/generate']['post']['parameters'].append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100,'pattern':'^[A-Za-z0-9_-]+$'}})
    paths['/stories/episodes/{id}/chat']['post']['parameters'].append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}})
    paths['/creative/messages']['post']['parameters']=[{'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}}]
    for kind in ('image','video'):
        paths['/prompting/'+kind+'/{id}']['post']['parameters'].append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}})
    paths['/editing/timelines/{id}/render']['post'].setdefault('parameters',[]).append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}})
    paths['/editing/exports']['post']['parameters']=[{'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}}]
    for path in ('/video-review','/video-review/{id}/refine'):
        paths[path]['post'].setdefault('parameters',[]).append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':100}})
    for path in ('/editing/exports/{id}/download','/editing/media/{id}/download','/assets/{id}','/jobs/{id}/download','/image-studio/jobs/{id}/download','/image-studio/jobs/{id}/outputs/{asset_id}'):
        paths[path]['get']['responses']['200']={'description':'Binary media','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
    return {'openapi':'3.1.0','info':{'title':'Imagine Studio Agent API','version':'1.0.0','description':'Local agent bearer token; never supply xAI API keys. See AGENT_API.md for authorization and scene workflow.'},
        'servers':[{'url':'/agent/v1'}],'security':[{'localAgentToken':[]}],'paths':paths,
        'components':{'securitySchemes':{'localAgentToken':{'type':'http','scheme':'bearer','description':'Read the private local agent-token file; not an xAI credential.'}},'schemas':{
            'ImageSettings':image_settings,'Scene':scene,'ImageSource':{'type':'object','properties':{'asset_id':{'type':'string'},'url':{'type':'string','description':'Public HTTPS or valid inline image data'},'id':{'type':'string','description':'Canonical uploaded asset id returned in scenes'},'src':{'type':'string','description':'Canonical source returned in scenes'}},'description':'Use asset_id or url; returned canonical sources use id/src.'},
            'ReferenceImage':{'type':'object','required':['source'],'properties':{'id':{'type':'string'},'source':{'$ref':'#/components/schemas/ImageSource'}}},**parity_schemas}}}
