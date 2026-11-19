"""Standard-library client/CLI for Imagine Studio. No browser automation or xAI keys."""
import argparse
import base64
import json
import os
import re
import time
import warnings
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from user_data import data_home
ROOT=Path(__file__).resolve().parent

class StaleServerWarning(UserWarning):
    """The Studio server was started before the code on disk last changed."""

class AgentError(RuntimeError):
    def __init__(self,status,code,message):
        super().__init__(message);self.status=status;self.code=code

from song_client import SongClient

class LocalOnlyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A localhost service must never forward this workspace's bearer token.
        return None

class StudioClient(SongClient):
    def __init__(self,base_url='http://127.0.0.1:8765',token_file=None):
        url=urlsplit(base_url)
        if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.path not in ('','/') or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use a local HTTP origin without credentials or a path.')
        self.base=base_url.rstrip('/')+'/agent/v1'
        self.token=Path(token_file or data_home()/'studio/agent-token').expanduser().read_text().strip()
        self.opener=build_opener(ProxyHandler({}), LocalOnlyRedirects())
        self._resumed={}  # job id -> (resume_count expected, when resumed)
        self._code_checked=False

    def request(self,path='',method='GET',data=None,idempotency_key=None,*,params=None,timeout=30):
        if not isinstance(path,str) or '?' in path or '#' in path or '..' in path or '://' in path:
            raise ValueError('Use a relative API route.')
        if params is not None:
            if method!='GET' or not isinstance(params,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in params.items()):raise ValueError('Use string query parameters on GET requests.')
            path+='?'+urlencode(params) if params else ''
        resume=re.fullmatch(r'/?jobs/([A-Za-z0-9_-]+)/resume',path) if method=='POST' else None
        if resume:
            # Remember the resume so wait_for_job does not return the job's old error state.
            try:count=(self.request('jobs/'+resume[1]) or {}).get('resume_count',0)
            except AgentError:count=0
        headers={'Authorization':'Bearer '+self.token}
        if data is not None:headers['Content-Type']='application/json'
        if idempotency_key:headers['Idempotency-Key']=idempotency_key
        req=Request(self.base+'/'+path.lstrip('/'),data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
        try:
            with self.opener.open(req,timeout=timeout) as response:
                raw=response.read()
                if resume:self._resumed[resume[1]]=(count+1,time.monotonic())
                return json.loads(raw) if response.headers.get_content_type()=='application/json' else raw
        except HTTPError as e:
            try:detail=json.loads(e.read()).get('error',{})
            except (ValueError,AttributeError):detail={}
            finally:e.close()
            raise AgentError(e.code,detail.get('code','http_error'),detail.get('message','Local API request failed.')) from None

    def import_project(self, path):
        """Upload a raw ZIP without buffering it; poll project-archives/{id}."""
        with Path(path).expanduser().open('rb') as source:
            length = os.fstat(source.fileno()).st_size
            req = Request(self.base + '/project-archives/import', data=source,
                          headers={'Authorization': 'Bearer ' + self.token,
                                   'Content-Type': 'application/zip',
                                   'Content-Length': str(length)}, method='POST')
            try:
                # urllib/http.client streams file objects in bounded blocks.
                with self.opener.open(req, timeout=300) as response:
                    return json.load(response)
            except HTTPError as e:
                try:
                    detail = json.loads(e.read()).get('error', {})
                except (ValueError, AttributeError):
                    detail = {}
                finally:
                    e.close()
                raise AgentError(e.code, detail.get('code', 'http_error'),
                                 detail.get('message', 'Local API upload failed.')) from None

    def list_revisions(self,timeline_id):
        return self.request('editing/timelines/'+timeline_id+'/revisions')

    def restore_revision(self,timeline_id,revision,expected_revision):
        return self.request('editing/timelines/'+timeline_id+'/revisions/'+str(revision)+'/restore','POST',{'expected_revision':expected_revision})

    def select_take_from_edit(self,shot_id,take_id,expected_shot_revision):
        return self.request('editing/takes/select','POST',{'shot_id':shot_id,'take_id':take_id,'expected_shot_revision':expected_shot_revision})

    def transcribe_captions(self,timeline_id,expected_revision):
        return self.request('editing/timelines/'+timeline_id+'/captions/transcribe','POST',{'expected_revision':expected_revision})

    def preview_export(self,timeline_id,expected_revision,quality='draft'):
        return self.request('editing/timelines/'+timeline_id+'/preview','POST',{'expected_revision':expected_revision,'quality':quality})

    def import_captions(self,timeline_id,expected_revision,srt):
        return self.request('editing/timelines/'+timeline_id+'/captions/import','POST',{'expected_revision':expected_revision,'srt':srt})

    def upload(self,path):
        path=Path(path);raw=path.read_bytes()
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
        elif raw.startswith(b'\xff\xd8'):mime='image/jpeg'
        elif raw.startswith(b'RIFF') and raw[8:12]==b'WEBP':mime='image/webp'
        else:raise ValueError('Use a JPEG, PNG or WebP image.')
        return self.request('assets','POST',{'name':path.name,'data_url':'data:'+mime+';base64,'+base64.b64encode(raw).decode()})

    def upload_prop_model(self,path,*,name=None,units='mm',up_axis='z',reference_id=None):
        """Upload an STL or OBJ prop model; its true size comes from units."""
        path=Path(path);kind=path.suffix.lower().lstrip('.')
        body=dict(name=name or path.stem,format=kind,units=units,up_axis=up_axis,data_base64=base64.b64encode(path.read_bytes()).decode())
        if reference_id:body['reference_id']=reference_id
        return self.request('prop-models','POST',body)

    def render_prop(self,model_id,**pose):
        """Render a prop model at an exact frame position, distance, angle and lens (see prop-models/schema).
        The saved image asset is an image-model reference only; Studio refuses it as a video input."""
        return self.request('prop-models/'+model_id+'/render','POST',pose)

    def check_continuity(self,first_asset_id,last_asset_id,*,regions=None,tolerance_percent=0.5,title=None):
        """Compare a shot's first and last frames for fixed objects that moved or changed.
        regions: [{"name": "dish", "box": [x0, y0, x1, y1]}] as fractions of the frame."""
        body=dict(first={'asset_id':first_asset_id},last={'asset_id':last_asset_id},tolerance_percent=tolerance_percent)
        if regions:body['regions']=regions
        if title:body['title']=title
        return self.request('image-studio/continuity','POST',body)

    def lock_fixed_objects(self,first_asset_id,last_asset_id,regions,*,feather_px=12,name=None):
        """New last frame whose fixed objects are the first frame's own pixels (boxes or polygons)."""
        body=dict(first={'asset_id':first_asset_id},last={'asset_id':last_asset_id},regions=regions,feather_px=feather_px)
        if name:body['name']=name
        return self.request('image-studio/continuity/lock','POST',body)

    def keep_take(self,job_id,human_words):
        """The human keeps a take already judged retry or reject ("let's keep the first one")."""
        return self.request('jobs/'+job_id+'/keep','POST',{'human_words':human_words})

    def check_delivery(self,path,*,preset=None,spec=None,title=None):
        """Check a finished local video against a spec preset (contest_30s_1080p, x, youtube) or a custom spec."""
        body={'path':str(Path(path).expanduser().resolve())}
        for name,value in (('preset',preset),('spec',spec),('title',title)):
            if value is not None:body[name]=value
        return self.request('delivery/checks','POST',body,timeout=900)

    def fix_delivery(self,check_id,*,output_path=None,loudness=None):
        """Copy the picture untouched and re-encode only the sound to the spec; returns a check of the new file."""
        body={}
        if output_path:body['output_path']=str(Path(output_path).expanduser().resolve())
        if loudness is not None:body['loudness']=loudness
        return self.request('delivery/checks/'+check_id+'/fix','POST',body,timeout=900)

    def create_voice_line(self,title,voice,lines,**extra):
        """A Lite 480p scene for spoken lines only; lines are [{"text", "at_s"?, "delivery"?}]."""
        return self.request('sound/voice-lines','POST',dict(title=title,voice=voice,lines=lines,**extra))

    def save_stem(self,*,job_id=None,path=None,name=None,words=True):
        """Save a take's sound (job_id) or a local audio file (path) as a WAV stem with word times."""
        body={'words':words,**({'job_id':job_id} if job_id else {'path':str(Path(path).expanduser().resolve())})}
        if name:body['name']=name
        return self.request('sound/stems','POST',body,timeout=600)

    def place_stems(self,name,length_s,pieces):
        """Build a full-length stem from pieces placed at timeline times, with device presets."""
        return self.request('sound/place','POST',dict(name=name,length_s=length_s,pieces=pieces),timeout=600)

    def music_fit(self,hit_s,length_s,*,stem_id=None,path=None,song_event_s=None):
        body=dict(hit_s=hit_s,length_s=length_s,**({'stem_id':stem_id} if stem_id else {'path':str(Path(path).expanduser().resolve())}))
        if song_event_s is not None:body['song_event_s']=song_event_s
        return self.request('sound/music-fit','POST',body,timeout=300)

    def write_music(self,name,length_s,*,offset_s=0,keyframes=None,stem_id=None,path=None,fade_out_s=0):
        """The song slid by offset_s, trimmed to length, with volume keyframes [{"at_s", "db"}]."""
        body=dict(name=name,length_s=length_s,offset_s=offset_s,keyframes=keyframes or [],fade_out_s=fade_out_s,
                  **({'stem_id':stem_id} if stem_id else {'path':str(Path(path).expanduser().resolve())}))
        return self.request('sound/music','POST',body,timeout=600)

    def export_to_resolve(self,*,title=None,timeline_id=None,video=None,audio=None,fps=None,output_folder=None):
        """FCPXML (File > Import > Timeline in Resolve) plus a Lua script that adds the stems as named tracks."""
        body={}
        for name,value in (('title',title),('timeline_id',timeline_id),('video',video),('audio',audio),('fps',fps),('output_folder',output_folder)):
            if value is not None:body[name]=value
        return self.request('resolve/exports','POST',body,timeout=300)

    def place_prop(self,title,base_asset_id,reference_asset_id,target,product,*,approved=False,**extra):
        """Two image steps: GPT placement with the render as a separate reference, then Grok "reproduce exactly"."""
        return self.request('image-studio/prop-placement','POST',dict(title=title,base={'asset_id':base_asset_id},
            reference={'asset_id':reference_asset_id},target=target,product=product,approved=approved,**extra))

    def advance_prop_placement(self,run_id):return self.request('image-studio/prop-placement/'+run_id+'/advance','POST',{})

    def browser_tabs(self):return self.request('handoff/tabs')
    def request_browser(self,tab,kind,payload):
        return self.request('handoff/tabs/'+tab['id']+'/requests','POST',dict(expected_revision=tab['revision'],kind=kind,payload=payload))
    def browser_request(self,identity):return self.request('handoff/requests/'+identity)
    def export_book(self,identity,kind='series',format='markdown'):
        return self.request('documents/book','POST',dict(id=identity,kind=kind,format=format))
    def preview_edit(self,timeline):
        return self.request('editing/timelines/'+timeline['id']+'/preview','POST',dict(expected_revision=timeline['revision']))
    def preview_frame(self,export,timestamp_s):
        return self.request('editing/exports/'+export['id']+'/frame','POST',dict(expected_revision=export['snapshot']['revision'],timestamp_s=timestamp_s))

    def audio_reference_capabilities(self):return self.request('audio-references/schema')

    def upload_audio_reference(self,path,*,idempotency_key):
        path=Path(path)
        if path.stat().st_size>64*1024*1024:raise ValueError('Recording uploads must be at most 64 MB.')
        return self.request('audio-references','POST',dict(name=path.name,base64=base64.b64encode(path.read_bytes()).decode()),idempotency_key)

    def prepare_audio_excerpt(self,reference,start_s,end_s):
        return self.request('audio-references/'+reference['id']+'/excerpts','POST',dict(start_s=start_s,end_s=end_s))

    def attach_audio_reference(self,record,reference,excerpt,character_id=None):
        attachment=dict(reference_id=reference['id'],excerpt_id=excerpt['id'])
        if character_id:attachment['character_id']=character_id
        return self.edit_scene(record,dict(recording=attachment))

    def remove_audio_reference(self,record):return self.edit_scene(record,dict(recording=None))

    def create_scene(self,title,scene=None,named_references=None):
        return self.request('scenes','POST',{'title':title,'scene':scene or {},'named_references':named_references or []})

    def edit_scene(self,record,changes=None,**extra):
        return self.request('scenes/'+record['id'],'PATCH',{'expected_revision':record['revision'],'changes':changes or {},**extra})

    def review_scene_prompt(self,record,authored_by='agent'):
        return self.request('scenes/'+record['id']+'/review-prompt','POST',dict(expected_revision=record['revision'],reviewed=True,authored_by=authored_by))

    def validate(self,record):return self.request('scenes/'+record['id']+'/validate','POST',{})

    def check_server_code(self):
        """Return the server's code status ({'running', 'on_disk', 'stale', 'message'}) and warn
        (StaleServerWarning) when the server runs older code than the files on disk."""
        self._code_checked=True
        status=(self.request('') or {}).get('code')
        if status is None:
            status={'stale':None,'message':'This server does not report its code version: it predates the check. Restart it.'}
        if status.get('stale') is not False:warnings.warn(status['message'],StaleServerWarning,stacklevel=2)
        return status

    def generate(self,record,*,approved=False,idempotency_key,human_words=None,verdict=None,plan_id=None,agent=None,**extra):
        """Generate one take. The single human stop: approved=True with human_words, the human's
        own approval of this take, verbatim. It also covers the attached frames, scene edits since
        a plan was approved and the plan's take/budget limits, and lifts the review pause; pass
        verdict={'job_id', 'verdict', 'notes'?, 'tags'?} to record the last take's verdict in the same call."""
        body={'approved':approved,'expected_revision':record['revision'],**extra}
        for name,value in (('human_words',human_words),('verdict',verdict),('plan_id',plan_id),('agent',agent)):
            if value is not None:body[name]=value
        if not self._code_checked:
            try:self.check_server_code()
            except AgentError:pass
        return self.request('scenes/'+record['id']+'/generate','POST',body,idempotency_key)

    def approve_asset(self,asset_id,human_words,*,approved=True):
        """Mark any image asset (an upload, a locally edited frame) approved, relaying the human's own words."""
        return self.request('assets/'+asset_id+'/approve','POST',{'approved':approved,'human_words':human_words})

    def show_in_browser(self,record):return self.request('workspace','POST',{'scene_id':record['id']})

    def studio_account(self):
        """Safe workspace status, without human device links or codes."""
        return self.request('studio-account')

    def request_codex_reconnect(self):
        """Ask the human in Studio to reconnect this workspace; never start verification."""
        return self.request('studio-account/codex','POST',{})

    def codex_reconnect_status(self):
        """Poll idle/pending/connected/error. Connected is not an image-readiness check."""
        return self.request('studio-account/codex')

    def return_flows(self):return self.request('handoff/flows')
    def return_flow(self,identity):return self.request('handoff/flows/'+identity)
    def request_browser_return(self,flow):
        """Queue a return in the originating tab; does not write editor content."""
        return self.request('handoff/flows/'+flow['id']+'/request','POST',{'expected_revision':flow['revision']})
    def finish_browser_return(self,flow):
        """Requires the browser's restoration acknowledgement; otherwise 409."""
        return self.request('handoff/flows/'+flow['id']+'/finish','POST',{'expected_revision':flow['revision']})
    def browser_drafts(self):
        """Read human-opted-in snapshots only; this cannot save or apply a draft."""
        return self.request('handoff/drafts')
    def browser_draft(self,identity):return self.request('handoff/drafts/'+identity)

    def create_production(self, title, kind='quick', brief='', episode_title='Episode 1'):
        return self.request('productions','POST',dict(title=title,kind=kind,brief=brief,episode_title=episode_title))

    def production_context(self):return self.request('productions/context')

    def recent_productions(self,offset=0,limit=10,parent_id=None,archived=False,projects_only=False):
        """Items include is_project/project_label; counts respect projects_only."""
        return self.request('productions/recent','POST',dict(offset=offset,limit=limit,parent_id=parent_id,archived=archived,projects_only=projects_only))

    def check_grok_model_access(self):
        """Fresh model access check; does not verify image-generation access."""
        return self.request('account/grok-check','POST',{})

    def remembered_urls(self,include_archived=False):return self.request('urls/all' if include_archived else 'urls')
    def archive_url(self,record,archived=True):
        return self.request('urls/'+record['url_id']+'/archive','POST',dict(expected_revision=record['revision'],archived=archived))

    def image_test(self,prompt,*,approved=False,idempotency_key):
        return self.request('image-test','POST',dict(prompt=prompt,approved=approved),idempotency_key)
    def image_test_status(self,identity):return self.request('image-test/'+identity)

    def entity_workshop(self,identity):return self.request('filmmaking/entities/'+identity+'/workshop')
    def usage(self):return self.request('usage')
    def generate_workshop(self,identity,job_id,requests,*,scope='series',model='gpt-image-2',approved=False,idempotency_key):
        """Generate with human approval; identity is series/production id (series or worlds),
        or episode id (episodes). job_id comes from workshop.job.id. Each request
        uses view_id and the VIEW expected_revision, never draft.revision.
        Preview costs/allowance first with preview_workshop_generation().
        """
        if scope not in ('series','episodes','worlds'):raise ValueError('Choose series, episodes or worlds.')
        return self.request('filmmaking/'+scope+'/'+identity+'/generate','POST',dict(job_id=job_id,requests=requests,model=model,approved=approved),idempotency_key)
    def preview_workshop_generation(self,identity,job_id,requests,*,scope='series',model='gpt-image-2'):
        """Read-only paid-step preview with allowance; ids/revisions match generate_workshop."""
        if scope not in ('series','episodes','worlds'):raise ValueError('Choose series, episodes or worlds.')
        return self.request('filmmaking/'+scope+'/'+identity+'/generation-preview','POST',dict(job_id=job_id,requests=requests,model=model))
    def refresh_storybook_links(self,episode_id,expected_revision):
        """Explicitly refresh linked entity snapshots using the Storybook revision; scripts/media stay fixed."""
        return self.request('filmmaking/episodes/'+episode_id+'/storybook/refresh-links','POST',dict(expected_revision=expected_revision))
    def production_readiness(self,episode_id):
        """Read every linked entity's frozen confirmed image, missing-image flag and source-change badge."""
        return self.request('filmmaking/episodes/'+episode_id+'/storybook/readiness')
    def rename_image_candidate(self,view,candidate,title):
        """Correct a candidate title/filename using view and candidate-review revisions."""
        return self.request('filmmaking/assets/'+view['id']+'/rename-candidate','POST',dict(expected_revision=view['revision'],expected_review_revision=candidate.get('review_revision',0),asset_id=candidate['id'],title=title))
    def confirm_workshop_image(self,view,asset_id,*,approved=False,image_layout=None):
        """Confirm a candidate with the view revision; omitted layout keeps its generation layout."""
        return self.request('filmmaking/assets/'+view['id']+'/confirm','POST',dict(expected_revision=view['revision'],asset_id=asset_id,approved=approved,**({'image_layout':image_layout} if image_layout else {})))
    def preview_image_bible_change(self,view,entity,asset_id,changes,*,image_layout=None):
        return self.request('filmmaking/assets/'+view['id']+'/bible-change-preview','POST',dict(expected_revision=view['revision'],expected_entity_revision=entity['revision'],asset_id=asset_id,changes=changes,**({'image_layout':image_layout} if image_layout else {})))
    def confirm_image_bible_change(self,view_id,preview_id,*,approved=False):
        return self.request('filmmaking/assets/'+view_id+'/bible-change-confirm','POST',dict(preview_id=preview_id,approved=approved,authored_by='agent'))
    def clear_entity_approval(self,record):
        return self.request('filmmaking/entities/'+record['id']+'/clear-approval','POST',dict(expected_revision=record['revision']))
    def rename_view(self,record,title):
        return self.request('filmmaking/assets/'+record['id'],'PUT',dict(expected_revision=record['revision'],title=title))
    def clear_view_approval(self,record):
        return self.request('filmmaking/assets/'+record['id']+'/clear-approval','POST',dict(expected_revision=record['revision']))
    def return_developed_image(self,view,job_id,asset_id):
        return self.request('filmmaking/assets/'+view['id']+'/return-image','POST',dict(expected_revision=view['revision'],job_id=job_id,asset_id=asset_id))
    def review_attempts(self,view,attempt_ids,action='dismiss'):
        return self.request('filmmaking/assets/'+view['id']+'/attempts','POST',dict(expected_revision=view['revision'],attempt_ids=attempt_ids,action=action))
    def review_candidate(self,view,candidate,action,reason=''):
        return self.request('filmmaking/assets/'+view['id']+'/review','POST',dict(expected_revision=view['revision'],expected_review_revision=candidate.get('review_revision',0),asset_id=candidate['id'],action=action,reason=reason))
    def book_pdf(self,identity,kind='series'):
        if kind not in ('series','episodes'):raise ValueError('Choose series or episodes.')
        return self.request('filmmaking/'+kind+'/'+identity+'/book.pdf')

    def group_production(self,production_id,expected_revision,parent_production_id=None):
        return self.request('productions/'+production_id+'/membership','POST',dict(expected_revision=expected_revision,parent_production_id=parent_production_id))

    def trash_production(self,production_id,expected_revision):
        return self.request('productions/'+production_id+'/trash','POST',dict(expected_revision=expected_revision))

    def restore_production(self,production_id,expected_revision):
        return self.request('productions/'+production_id+'/restore','POST',dict(expected_revision=expected_revision))

    def create_shot(self, production_id, title, episode_id=None, story_scene_id=None):
        return self.request('productions/'+production_id+'/shots','POST',dict(title=title,episode_id=episode_id,story_scene_id=story_scene_id))

    def camera_presets(self):
        """Shared camera/movement presets and local renderer availability; no provider calls."""
        return self.request('filmmaking/presets')

    def shot_staging(self,shot_id):return self.request('filmmaking/shots/'+shot_id)
    def save_shot_staging(self,direction,staging):
        return self.request('filmmaking/shots/'+direction['shot_id'],'PUT',dict(expected_revision=direction['revision'],staging=staging))
    def camera_reference(self,direction):
        """PNG bytes from the local Node/Skia renderer for saved staging only; refuses a stale staging revision (409)."""
        return self.request('filmmaking/shots/'+direction['shot_id']+'/reference.png','POST',dict(expected_revision=direction['revision']))
    def compose_shot(self,direction,image_revision,prompt,png):
        """Transfer a local PNG into the linked image draft; never generate an image."""
        return self.request('filmmaking/shots/'+direction['shot_id']+'/compose','POST',dict(
            expected_revision=direction['revision'],expected_image_revision=image_revision,
            prompt=prompt,data_url='data:image/png;base64,'+base64.b64encode(png).decode()))

    def show_production(self, production_id, stage='develop', **selection):
        return self.request('productions/workspace','POST',dict(production_id=production_id,stage=stage,**selection))

    def creative_context(self, production_id, **scope):
        return self.request('creative/context','POST',dict(production_id=production_id,**scope))

    def ask_collaborator(self, production_id, message, *, idempotency_key, approved=False, **scope):
        return self.request('creative/messages','POST',dict(production_id=production_id,message=message,approved=approved,**scope),idempotency_key)

    def apply_creative_proposal(self, job_id):return self.request('creative/messages/'+job_id+'/apply','POST',{})
    def undo_creative_proposal(self, job_id):return self.request('creative/messages/'+job_id+'/undo','POST',{})
    def precision_edit(self, asset_id, operations, draft_id=None):
        return self.request('precision/edits','POST',dict(asset_id=asset_id,operations=operations,draft_id=draft_id))
    def develop_asset(self, reference_id, expected_revision, prompt=''):
        return self.request('asset-studio/'+reference_id+'/develop','POST',dict(expected_revision=expected_revision,prompt=prompt))

    def create_image(self,title,settings=None,named_references=None):
        return self.request('image-studio/drafts','POST',{'title':title,'settings':settings or {},'named_references':named_references or []})

    def open_edit(self,production_id,episode_id=None,story_scene_id=None):
        return self.request('editing/timelines/open','POST',dict(production_id=production_id,episode_id=episode_id,story_scene_id=story_scene_id))
    def render_edit(self,scene,parent,idempotency_key):
        return self.request('editing/timelines/'+scene['id']+'/render','POST',dict(expected_revision=scene['revision'],parent_timeline_id=parent['id'],expected_parent_revision=parent['revision']),idempotency_key)
    def edit_sources(self,production_id,episode_id=None):
        return self.request('editing/sources','POST',dict(production_id=production_id,episode_id=episode_id))
    def inspect_media(self,source):return self.request('editing/inspect','POST',dict(source=source))
    def upload_media(self,path):
        path=Path(path)
        if path.stat().st_size>64*1024*1024:raise ValueError('Media uploads must be at most 64 MB.')
        return self.request('editing/media','POST',dict(name=path.name,base64=base64.b64encode(path.read_bytes()).decode()))
    def save_edit(self,record,**changes):
        return self.request('editing/timelines/'+record['id'],'PUT',dict(expected_revision=record['revision'],**changes))
    def export_edit(self,record,idempotency_key):
        return self.request('editing/exports','POST',dict(timeline_id=record['id'],expected_revision=record['revision']),idempotency_key)
    def local_transcription(self):return self.request('editing/transcription')
    def configure_transcription(self,settings,model_path):return self.request('editing/transcription','PUT',dict(expected_revision=settings['revision'],local_transcription_model=model_path))
    def cancel_export(self,identity):return self.request('editing/exports/'+identity+'/cancel','POST',{})
    def wait_for_export(self,identity,timeout=3600,interval=2):
        deadline=time.monotonic()+timeout
        while True:
            job=self.request('editing/exports/'+identity)
            if job['status'] not in ('queued','rendering'):return job
            if time.monotonic()>=deadline:raise TimeoutError('Export polling timed out. Fetch this job instead of resubmitting.')
            time.sleep(interval)
    def download_export(self,identity,destination):
        Path(destination).write_bytes(self.request('editing/exports/'+identity+'/download'));return str(Path(destination).resolve())

    def validate_image(self,record):return self.request('image-studio/drafts/'+record['id']+'/validate','POST',{})

    def generate_image(self,record,*,approved=False,idempotency_key):
        return self.request('image-studio/drafts/'+record['id']+'/generate','POST',{'approved':approved,'expected_revision':record['revision']},idempotency_key)

    def resume_image(self,identity):
        return self.request('image-studio/jobs/'+identity+'/resume','POST',{})

    def download_image_candidate(self,identity,asset_id,destination):
        """Download candidate bytes with agent authentication: identity is its IMAGE JOB id.
        asset_id is outputs[].id; destination is a local path. Browser /api/assets URLs
        need a session or Bearer header and are not standalone public download links.
        """
        Path(destination).write_bytes(self.request('image-studio/jobs/'+identity+'/outputs/'+asset_id))
        return str(Path(destination).resolve())

    def wait_for_image(self,identity,timeout=600,interval=2):
        deadline=time.monotonic()+timeout
        while True:
            job=self.request('image-studio/jobs/'+identity)
            if job['status']!='pending':return job
            if time.monotonic()>=deadline:raise TimeoutError('Image polling timed out. Check this job; do not resubmit.')
            time.sleep(interval)

    def resume_job(self,identity):
        """Resume polling a saved request (never resubmits); follow with wait_for_job."""
        return self.request('jobs/'+identity+'/resume','POST',{})

    def wait_for_job(self,identity,timeout=600,interval=2,stale_grace=30):
        """Poll until the job leaves pending. Right after jobs/{id}/resume, an error state from
        before the resume is stale: keep waiting (up to stale_grace seconds) until the server
        shows the resumed attempt."""
        deadline=time.monotonic()+timeout
        while True:
            job=self.request('jobs/'+identity)
            expected=self._resumed.get(identity)
            if expected and job['status']!='pending' and job.get('resume_count',0)<expected[0] \
                    and time.monotonic()-expected[1]<stale_grace and time.monotonic()<deadline:
                time.sleep(interval);continue
            if job['status']!='pending':
                self._resumed.pop(identity,None);return job
            if time.monotonic()>=deadline:raise TimeoutError('Polling timed out. Fetch this job or resume it; do not resubmit.')
            time.sleep(interval)

    def download(self,identity,destination):
        Path(destination).write_bytes(self.request('jobs/'+identity+'/download'))
        return str(Path(destination).resolve())

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('route',nargs='?',default='schema')
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--token-file',type=Path)
    parser.add_argument('--method',choices=['GET','POST','PUT','PATCH'],default='GET')
    parser.add_argument('--data-file',type=Path,help='JSON request body; no shell quoting required.')
    parser.add_argument('--params-file',type=Path,help='JSON object of string GET query parameters.')
    parser.add_argument('--idempotency-key')
    parser.add_argument('--output',type=Path,help='Save binary responses to this file.')
    parser.add_argument('--upload',type=Path,help='Upload this image instead of calling route.')
    args=parser.parse_args()
    try:
        client=StudioClient(args.base_url,args.token_file)
        result=client.upload(args.upload) if args.upload else client.request(args.route,args.method,json.loads(args.data_file.read_text()) if args.data_file else ({} if args.method!='GET' else None),args.idempotency_key,params=json.loads(args.params_file.read_text()) if args.params_file else None)
        if isinstance(result,bytes):
            if not args.output:parser.error('Binary responses require --output.')
            args.output.write_bytes(result);print(str(args.output.resolve()))
        else:print(json.dumps(result,indent=2))
    except (AgentError,ValueError,OSError) as e:
        parser.exit(1,f'{e}\n')
