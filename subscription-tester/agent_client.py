"""Standard-library client/CLI for Imagine Studio. No browser automation or xAI keys."""
import argparse
import base64
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from user_data import data_home
ROOT=Path(__file__).resolve().parent

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

    def request(self,path='',method='GET',data=None,idempotency_key=None,*,params=None):
        if not isinstance(path,str) or '?' in path or '#' in path or '..' in path or '://' in path:
            raise ValueError('Use a relative API route.')
        if params is not None:
            if method!='GET' or not isinstance(params,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in params.items()):raise ValueError('Use string query parameters on GET requests.')
            path+='?'+urlencode(params) if params else ''
        headers={'Authorization':'Bearer '+self.token}
        if data is not None:headers['Content-Type']='application/json'
        if idempotency_key:headers['Idempotency-Key']=idempotency_key
        req=Request(self.base+'/'+path.lstrip('/'),data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
        try:
            with self.opener.open(req,timeout=30) as response:
                raw=response.read()
                return json.loads(raw) if response.headers.get_content_type()=='application/json' else raw
        except HTTPError as e:
            try:detail=json.loads(e.read()).get('error',{})
            except (ValueError,AttributeError):detail={}
            finally:e.close()
            raise AgentError(e.code,detail.get('code','http_error'),detail.get('message','Local API request failed.')) from None

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

    def generate(self,record,*,approved=False,idempotency_key):
        return self.request('scenes/'+record['id']+'/generate','POST',{'approved':approved,'expected_revision':record['revision']},idempotency_key)

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
        Path(destination).write_bytes(self.request('image-studio/jobs/'+identity+'/outputs/'+asset_id))
        return str(Path(destination).resolve())

    def wait_for_image(self,identity,timeout=600,interval=2):
        deadline=time.monotonic()+timeout
        while True:
            job=self.request('image-studio/jobs/'+identity)
            if job['status']!='pending':return job
            if time.monotonic()>=deadline:raise TimeoutError('Image polling timed out. Check this job; do not resubmit.')
            time.sleep(interval)

    def wait_for_job(self,identity,timeout=600,interval=2):
        deadline=time.monotonic()+timeout
        while True:
            job=self.request('jobs/'+identity)
            if job['status']!='pending':return job
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
