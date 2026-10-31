"""Local Grok Imagine studio. The original image tester remains at /tester."""
import argparse
import base64
import copy
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
from contextvars import copy_context
from contextlib import ExitStack
from urllib.parse import parse_qs, urlsplit
from urllib.parse import urlparse
from http.server import ThreadingHTTPServer

from server import Tester, Handler, ROOT
from agent_api import AgentAPI, APIError
from image_studio import ImageStudio
from named_references import normalize as normalize_reference
from video_rules import MODELS, RATIOS, VOICES, validate_video, image_input, MODEL_CAPABILITIES

from user_data import data_home, outside_source, require_migration
STATE = data_home() / 'studio'
CONFIG = json.loads((ROOT / 'studio-config.json').read_text())
VIDEO_ENDPOINT = 'https://api.x.ai/v1/videos/generations'


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data))
    temp.chmod(0o600)
    temp.replace(path)


def upstream_error(response, secrets=()):
    """Keep useful JSON error text locally without response headers or credentials."""
    try:
        payload = response.json()
    except Exception:
        return ''
    if not isinstance(payload, dict):
        return ''
    error = payload.get('error', payload)
    if isinstance(error, dict):
        detail = error.get('message') or error.get('detail') or error.get('code')
    else:
        detail = error
    if not isinstance(detail, str):
        detail = payload.get('message') or payload.get('detail')
    if not isinstance(detail, str):
        return ''
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, '[redacted]')
    detail = re.sub(r'(?i)Bearer\s+\S+|(?:xai-|sk-)[A-Za-z0-9_-]+', '[redacted]', detail)
    detail = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', detail)
    detail = re.sub(r'data:[^\s"\']+', '[image data]', detail)
    detail = re.sub(r'https?://[^\s"\']+', '[URL]', detail)
    return ' '.join(detail.split())[:1200]


def oauth_headers():
    from workspace_accounts import CURRENT_PROFILE
    profile=CURRENT_PROFILE.get()
    if profile is not None:return profile.grok('headers')
    from hermes_cli.auth import resolve_xai_oauth_runtime_credentials
    credentials = resolve_xai_oauth_runtime_credentials()
    token = credentials.get('api_key', '')
    if credentials.get('provider') != 'xai-oauth' or credentials.get('auth_mode') != 'oauth_device_code' or not token or token.startswith('xai-'):
        raise ValueError('Subscription OAuth is required.')
    return {'Authorization': 'Bearer ' + token}


class Studio(Tester):
    def check_grok_connection(self):
        """Verify credentials upstream without consuming image-generation allowance."""
        if self.mock:return {'signed_in':True,'verified':True,'image_access_verified':False,'mock':True}
        import httpx
        try:
            headers=oauth_headers()
            with httpx.Client(timeout=20,follow_redirects=False) as client:
                response=client.get('https://api.x.ai/v1/models',headers=headers)
                from provider_usage import observe
                observe(self,response,'grok_account')
        except Exception:
            raise ValueError('Could not verify Grok. Check your connection or reconnect, then check again.') from None
        if response.status_code==200:
            self.update(signed_in=True,auth_status='connected',auth_error=None)
            return {'signed_in':True,'verified':True,'image_access_verified':False}
        if response.status_code==401:
            self.update(signed_in=False,auth_status='error',auth_error='Grok rejected your sign-in. Reconnect to continue.')
            return {'signed_in':False,'verified':True,'image_access_verified':False}
        raise ValueError(f'Grok connection check returned HTTP {response.status_code}. Your sign-in was kept; try checking again.')

    def __init__(self, mock=True, storage=STATE, profile=None):
        super().__init__(mock)
        self.profile=profile
        self.storage = Path(storage).resolve()
        from diagnostic_requests import DiagnosticRequests
        self.diagnostics = DiagnosticRequests(self,self.storage/'image-tests.json',save_json)
        self.assets_path = self.storage / 'assets.json'
        self.history_path = self.storage / ('mock-history.json' if mock else 'history.json')
        self.assets = json.loads(self.assets_path.read_text()) if self.assets_path.exists() else []
        self.history = json.loads(self.history_path.read_text()) if self.history_path.exists() else []
        self.references_path = self.storage / 'references.json'
        self.references = json.loads(self.references_path.read_text()) if self.references_path.exists() else []
        self.job = None
        self.download_locks = {}
        signed_in = False
        if not mock:
            auth_path = data_home() / 'hermes' / 'auth.json'
            if profile is not None:
                signed_in=bool(profile.get('hermes'))
            elif auth_path.exists():
                # Read only the local provider presence, without exporting account tokens.
                auth = json.loads(auth_path.read_text())
                signed_in = bool(auth.get('providers', {}).get('xai-oauth', {}).get('tokens', {}).get('access_token'))
        self.state.update(signed_in=signed_in, auth_status='connected' if signed_in else 'disconnected', message=('Mock mode. No xAI calls will be made.' if mock else
                      'Ready. Choose Generate to create an image or video.' if CONFIG['live_generations_enabled'] else
                      'Ready. Live video generation is locked in studio-config.json.'),
                          progress=None, job_id=None, video=None, request_id=None)

        self.agent = AgentAPI(self, CONFIG, save_json)
        self.images = ImageStudio(self, CONFIG, save_json)
        from story_studio import StoryStudio
        self.stories = StoryStudio(self, save_json)
        from production_studio import ProductionStudio
        self.productions = ProductionStudio(self)
        from asset_studio import AssetStudio
        from creative_studio import CreativeStudio
        from precision_studio import PrecisionStudio
        self.asset_studio=AssetStudio(self)
        self.creative=CreativeStudio(self)
        self.precision=PrecisionStudio(self)
        from editing_studio import EditingStudio
        self.editing=EditingStudio(self)
        from song_performance import SongPerformance
        self.song_performance=SongPerformance(self)
        from filmmaking_studio import FilmmakingStudio
        self.filmmaking=FilmmakingStudio(self)
        from media_prompting import MediaPrompting
        self.prompting=MediaPrompting(self)
        from video_learning import VideoLearning
        self.video_learning=VideoLearning(self)
        from video_review import VideoReview
        self.video_review=VideoReview(self, save_json)
        from browser_handoff import BrowserHandoff
        self.handoff=BrowserHandoff(self,save_json)
        from document_exports import DocumentExports
        self.documents=DocumentExports(self)
        from project_archives import ProjectArchives
        self.archives=ProjectArchives(self)

    def spawn(self,target,*args):
        from workspace_accounts import CURRENT_PROFILE
        context=copy_context();context.run(CURRENT_PROFILE.set,self.profile)
        thread=threading.Thread(target=lambda:context.run(target,*args),daemon=True);thread.start();return thread

    def login(self):
        if self.profile is None or self.mock:return super().login()
        try:
            self.profile.grok('login',self.update)
            self.update(phase='ready',signed_in=True,auth_status='connected',auth_error=None,verification_url=None,user_code=None,message='Grok connected to this private workspace.')
        except Exception:self.update(phase='error',signed_in=False,auth_status='error',auth_error='Grok sign-in failed. Reconnect this workspace.',verification_url=None,user_code=None,message='Sign-in did not finish. Try again.')

    def begin(self, action, prompt='', on_complete=None):
        if self.snapshot()['phase'] == 'pending':
            raise ValueError('A video render is already running.')
        return super().begin(action, prompt, on_complete)

    def snapshot(self):
        result = super().snapshot()
        result.update(live_enabled=CONFIG['live_generations_enabled'], plan=None, usage=None)
        return result

    def library(self):
        with self.lock:
            from candidate_review import state,HIDDEN
            return copy.deepcopy([a for a in self.assets if state(a) not in HIDDEN])

    def named_library(self):
        with self.lock:
            from candidate_review import state,HIDDEN
            records=copy.deepcopy(self.references)
            assets={a['id']:a for a in self.assets}
            for record in records:
                record['needs_replacement']=any(
                    state(assets[i['asset_id']]) in HIDDEN or (assets[i['asset_id']].get('generated') and not assets[i['asset_id']].get('approved'))
                    for i in record.get('images',[]) if i.get('asset_id') in assets)
            return records

    def save_reference(self, data):
        with self.agent.lock:
            return self._save_reference(data)

    def _save_reference(self, data):
        record = normalize_reference(data, self.named_library(), self.asset, CONFIG)
        with self.lock:
            previous=next((r for r in self.references if r['id']==record['id']),None)
            if previous and 'expected_revision' in data and data['expected_revision']!=previous.get('revision',1):
                from agent_api import APIError
                raise APIError('revision_conflict','The asset changed. Reload it before saving.',409)
            record['revision']=previous.get('revision',1)+1 if previous else 1
            if any(r['id'] != record['id'] and r['handle'].casefold() == record['handle'].casefold() for r in self.references):
                raise ValueError('This mention name is already used.')
            self.references = [r for r in self.references if r['id'] != record['id']]
            self.references.insert(0, record)
            save_json(self.references_path, self.references)
            if hasattr(self,'productions'):
                if self.productions.sql.in_transaction:self.productions.put('asset',copy.deepcopy(record))
                else:
                    with self.productions.sql:self.productions.put('asset',copy.deepcopy(record))
        return copy.deepcopy(record)

    def archive_reference(self, identity, archived):
        with self.agent.lock:
            return self._archive_reference(identity, archived)

    def _archive_reference(self, identity, archived):
        with self.lock:
            record = next((r for r in self.references if r['id'] == identity), None)
            if not record:
                raise ValueError('Reference not found.')
            record['archived'] = bool(archived)
            record['revision']=record.get('revision',1)+1
            save_json(self.references_path, self.references)
            if hasattr(self,'productions'):
                if self.productions.sql.in_transaction:self.productions.put('asset',copy.deepcopy(record))
                else:
                    with self.productions.sql:self.productions.put('asset',copy.deepcopy(record))
        return {'ok': True}

    def records(self):
        with self.lock:
            generated=copy.deepcopy(self.history)
        imported=[job for job in self.productions.all('imported-video') if job.get('mock')==self.mock] if hasattr(self,'productions') else []
        return sorted(generated+imported,key=lambda job:job.get('created_at',0),reverse=True)

    def upload(self, data):
        value = {'url': data.get('data_url')}
        image_input(value)
        if not value['url'].startswith('data:'):
            raise ValueError('Upload an image file, or use the URL control.')
        mime, encoded = value['url'].split(',', 1)
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > CONFIG['upload_limit_mb'] * 1024 * 1024:
            raise ValueError('Image exceeds the configured local upload limit.')
        identity = uuid.uuid4().hex
        ext = {'data:image/png;base64': 'png', 'data:image/jpeg;base64': 'jpg', 'data:image/webp;base64': 'webp'}[mime]
        path = self.storage / 'assets' / f'{identity}.{ext}'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(raw)
        path.chmod(0o600)
        asset = {'id': identity, 'name': str(data.get('name', 'Image'))[:120], 'ext': ext,
                 'mime': mime[5:-7], 'bytes': len(raw), 'src': f'/api/assets/{identity}'}
        with self.lock:
            self.assets.append(asset)
            save_json(self.assets_path, self.assets)
        return asset

    def asset(self, identity):
        with self.lock:
            match = next((x for x in self.assets if x['id'] == identity), None)
        if not match:
            raise ValueError('An uploaded image is missing. Upload it again.')
        path = self.storage / 'assets' / f"{identity}.{match['ext']}"
        return match, path

    def resolve(self, settings):
        body = copy.deepcopy(settings)
        recording=body.pop('_studio_audio_reference',None) or (body.get('_studio_scene') or {}).get('recording')
        if recording:
            from audio_references import AudioReferences
            service=AudioReferences(self)
            recording=service.attachment(recording)
            if body.get('reference_audios'):raise APIError('conflicting_audio','Remove preset voice assignments before attaching a recording.')
            _,path=service.file(recording['excerpt_id'],'audio-excerpt')
            mime='audio/mpeg' if path.suffix.lower()=='.mp3' else 'audio/wav'
            # Local validated representation only. The worker replaces these bytes
            # with a temporary HTTPS URL after generation approval, never on validate.
            body['reference_audios']=[{'url':f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode()}]
        # Scene snapshots are local UI metadata, never provider request fields.
        body.pop('_studio_scene', None)
        body.pop('_studio_story', None)
        body.pop('_studio_video_id', None)
        allow_start=body.pop('allow_unapproved_start_frame',False)

        def resolve_image(value, allow=False):
            if isinstance(value, dict) and set(value) == {'asset_id'}:
                asset, path = self.asset(value['asset_id'])
                if asset.get('generated') and not asset.get('approved') and not allow:
                    raise ValueError('Review and approve the Image Studio candidate before using it in a video.')
                return {'url': f"data:{asset['mime']};base64," + base64.b64encode(path.read_bytes()).decode()}
            return value

        for field in ('image', 'last_frame'):
            if field in body:
                body[field] = resolve_image(body[field],allow_start and field=='image')
        body['reference_images'] = [resolve_image(x) for x in body.get('reference_images', [])]
        for key in body.get('keyframes', []):
            key['image'] = resolve_image(key.get('image'))
        if not body['reference_images']:
            del body['reference_images']
        return validate_video(body, CONFIG)

    def start_video(self, settings, approved, agent_key=None, agent_fingerprint=None):
        if not self.mock and not CONFIG['live_generations_enabled']:
            raise ValueError('Live video generation is locked in studio-config.json.')
        if not approved:
            raise ValueError('Confirm this generation before sending it.')
        from workflow_tools import start_frame_gate,usage
        frame_gate=start_frame_gate(self,settings)
        allowance_warnings=usage(self)['recent_limit_errors']
        if not frame_gate['allowed']:raise APIError('start_frame_required',' '.join(frame_gate['missing']),409)
        body = self.resolve(settings)
        if not self.mock:
            from video_prompt_checks import blocked
            issues = self.prompting.request_status(body, settings.get('_studio_video_id'), settings.get('_studio_scene'))['prompt_issues']
            if blocked(issues):
                raise APIError('prompt_conflict', ' '.join(i['message'] for i in issues if i['severity'] == 'error'), 409)
        with self.lock:
            if self.state['phase'] in ('connecting', 'waiting', 'generating', 'pending'):
                raise ValueError('Wait for the current operation to finish.')
            if not self.state['signed_in']:
                raise ValueError('Sign in first.')
            self.job = {'id': uuid.uuid4().hex, 'created_at': time.time(), 'mock': self.mock,
                        'settings': copy.deepcopy(settings), 'status': 'pending', 'video': None, 'request_id': None,
                        'agent_key':agent_key, 'agent_fingerprint':agent_fingerprint,
                        'allow_unapproved_start_frame':frame_gate['override'],
                        'allowance_warnings':allowance_warnings,
                        'requested_model':body['model'], 'returned_model':None, 'model_identity':'unconfirmed'}
            job = self.job
            if hasattr(self,'prompting'):
                from prompt_guides import digest
                prepared=next((r.get('prompt_preparation') for r in self.agent.db['scenes'] if r.get('prompt_preparation',{}).get('request_fingerprint')==digest(body)),None)
                if prepared:job['prompt_preparation']=copy.deepcopy(prepared)
                reviewed=next((r.get('manual_prompt_review') for r in self.agent.db['scenes'] if r['id']==settings.get('_studio_video_id') and r.get('manual_prompt_review',{}).get('revision')==r['revision'] and r['manual_prompt_review'].get('request_fingerprint')==digest(body)),None)
                if reviewed:job['prompt_provenance']=copy.deepcopy(reviewed)
            # Preserve the actual outbound prompt and resolved local image bytes,
            # so later review never substitutes the current editor or library.
            job['request_snapshot']=self.video_review.capture_submission(job, body, settings)
            self.state.update(phase='generating', progress=None, video=None, request_id=None,
                              job_id=job['id'], message='Starting mock generation…' if self.mock else 'Submitting video request…')
            self.history.insert(0, job)
            save_json(self.history_path, self.history)
        self.spawn(self.video_worker,body,job)
        return job['id']

    def finish(self, job, status, message, video=None):
        with self.lock:
            job.update(status=status, video=video, message=message)
            if re.search(r'quota|rate.?limit|usage.?limit|HTTP 429',message,re.I):job['limit_error_at']=time.time()
            self.state.update(phase=status, message=message, video=video, progress=100 if status == 'done' else None)
            save_json(self.history_path, self.history)

    def video_worker(self, body, job):
        try:
            if self.mock:
                for percentage in (15, 40, 70, 90):
                    self.update(phase='pending', progress=percentage, message=f'Mock render · {percentage}%')
                    time.sleep(.4)
                self.finish(job, 'done', 'Mock video ready. No subscription usage consumed.', '/static/mock-video.mp4')
                return
            import httpx
            with httpx.Client(timeout=60, follow_redirects=False) as client, ExitStack() as recording_resources:
                if body is not None:
                    headers = oauth_headers()
                    from recording_transport import prepare_recordings, RecordingTransportError
                    try:
                        body,uploads=prepare_recordings(client,headers,body,resources=recording_resources)
                    except RecordingTransportError as error:
                        self.finish(job,'error',str(error));return
                    if uploads:
                        with self.lock:
                            job['audio_provider_uploads']=uploads
                            save_json(self.history_path,self.history)
                    response = client.post(VIDEO_ENDPOINT, headers=headers, json=body)
                    from provider_usage import observe
                    observe(self,response,'grok_video')
                    if response.status_code not in (200, 202):
                        self.update(http_status=response.status_code)
                        detail = upstream_error(response, (headers['Authorization'], headers['Authorization'].removeprefix('Bearer ')))
                        if response.status_code==401:
                            self.update(signed_in=False,auth_status='error',auth_error='Grok sign-in expired. Reconnect before generating again.')
                        with self.lock:
                            job['http_status'] = response.status_code
                            job['upstream_error'] = detail
                            if response.status_code==403 and 'reference_audios' in detail and 'not enabled' in detail:
                                job['audio_reference_access']='denied'
                        access_hint=' Ask xAI to enable caller-supplied audio-reference URLs for this team before retrying.' if job.get('audio_reference_access')=='denied' else ''
                        self.finish(job, 'error', f'xAI rejected the request (HTTP {response.status_code}).' + (f' {detail}' if detail else ' No detailed JSON error was returned.') + access_hint + ' No automatic retry was made.')
                        return
                    identity = response.json().get('request_id', '')
                    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', identity):
                        raise ValueError('Invalid request identifier.')
                    with self.lock:
                        job['request_id'] = identity
                        save_json(self.history_path, self.history)
                else:
                    identity = job['request_id']
                self.update(phase='pending', request_id=identity, message='Rendering video. Polling xAI…')
                deadline = time.monotonic() + CONFIG['poll_timeout_seconds']
                while time.monotonic() < deadline:
                    result = client.get(f'https://api.x.ai/v1/videos/{identity}', headers=oauth_headers())
                    from provider_usage import observe
                    observe(self,result,'grok_video')
                    if result.status_code not in (200, 202):
                        self.finish(job, 'error', f'Polling stopped (HTTP {result.status_code}). The job may still be running; use Resume polling. Do not submit a duplicate.')
                        return
                    payload = result.json() if result.content else {}
                    status = payload.get('status') or ('pending' if result.status_code == 202 else None)
                    if status == 'done':
                        video = payload.get('video', {})
                        url = video.get('url', '')
                        if video.get('respect_moderation') is False:
                            self.finish(job, 'error', 'The output was filtered by moderation.')
                            return
                        if urlparse(url).scheme != 'https':
                            raise ValueError('Invalid video output URL.')
                        with self.lock:
                            job['output_duration'] = video.get('duration')
                            job['requested_model'] = job.get('requested_model') or job.get('settings',{}).get('model')
                            job['returned_model'] = payload.get('model') if isinstance(payload.get('model'),str) else None
                            job['model_identity'] = 'confirmed' if job['returned_model'] else 'unconfirmed'
                            job['usage'] = {key: value for key, value in payload.get('usage', {}).items() if type(value) in (int, float, bool)}
                        self.finish(job, 'done', 'Video ready. Remaining Grok allowance cannot be read by Studio. Check Grok Settings → Usage for the balance and deduction.', url)
                        return
                    if status in ('failed', 'expired'):
                        code = payload.get('error', {}).get('code', '')
                        messages = {'invalid_argument': 'xAI rejected an input or moderation check.', 'permission_denied': 'Your account lacks video access.',
                                    'failed_precondition': 'The model does not support these settings.', 'service_unavailable': 'xAI is temporarily overloaded.',
                                    'internal_error': 'xAI could not complete the render.'}
                        self.finish(job, 'error', 'Request expired.' if status == 'expired' else messages.get(code, 'Video generation failed.'))
                        return
                    if status != 'pending':
                        raise ValueError('Unknown polling status.')
                    percentage = payload.get('progress')
                    self.update(progress=percentage if type(percentage) in (int, float) and 0 <= percentage <= 100 else None)
                    time.sleep(CONFIG['poll_interval_seconds'])
                self.finish(job, 'error', 'Local polling timed out. The request may still finish. Resume polling instead of creating another generation.')
        except Exception:
            self.finish(job, 'error', 'Network, token refresh, or response validation failed. If a request ID exists, resume polling instead of submitting again.')

    def resume(self, identity):
        with self.lock:
            if self.state['phase'] in ('connecting', 'waiting', 'generating', 'pending'):
                raise ValueError('Wait for the current operation to finish.')
            job = next((j for j in self.history if j['id'] == identity), None)
            if not job or job['mock'] or not job.get('request_id') or job['status'] == 'done':
                raise ValueError('Choose an unfinished live request with a saved request ID.')
            self.job = job
            self.state.update(phase='pending', job_id=identity, request_id=job['request_id'], video=None,
                              progress=None, message='Resuming the saved request. No new generation is submitted.')
        self.spawn(self.video_worker,None,job)

    def download(self, identity, *, archive_record=None):
        with self.lock:
            guard = self.download_locks.setdefault(identity, threading.Lock())
        with guard:
            return self._download(identity, archive_record)

    def _download(self, identity, archive_record=None):
        job = archive_record if archive_record is not None else next((j for j in self.records() if j['id'] == identity), None)
        if not job or job['status'] != 'done' or not job.get('video'):
            raise ValueError('Choose a completed video.')
        if job.get('imported_media_id'):
            return self.editing.media_file(job['imported_media_id'])[1]
        cached = self.storage / 'videos' / (job['id'] + '.mp4')
        if job.get('archive_local_video'):
            if not cached.is_file(): raise ValueError('The archived video file is missing.')
            return cached
        if job['mock']:
            return ROOT / 'static' / 'mock-video.mp4'
        path = self.storage / 'videos' / (job['id'] + '.mp4')
        if path.exists():
            return path
        # Download only the exact HTTPS result recorded from xAI, never a caller-supplied URL.
        import httpx
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = path.with_suffix('.part')
        try:
            with httpx.stream('GET', job['video'], timeout=120, follow_redirects=False) as response:
                response.raise_for_status()
                size = 0
                with temp.open('wb') as output:
                    os.chmod(temp, 0o600)
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > CONFIG['download_limit_mb'] * 1024 * 1024:
                            raise ValueError('Video exceeds the configured local download limit.')
                        output.write(chunk)
            temp.replace(path)
            return path
        except Exception:
            temp.unlink(missing_ok=True)
            raise ValueError('Download failed. The temporary output URL may have expired.') from None


def scoped_request(method):
    def call(self):
        manager=getattr(self.server,'accounts',None)
        if manager is None:return method(self)
        from workspace_accounts import CURRENT_PROFILE
        from agent_api import APIError
        try:
            if self.headers.get('Host')==f'localhost:{self.server.server_port}' and self.path in ('/','/tester'):
                self.send_response(302);self.send_header('Location',f'http://127.0.0.1:{self.server.server_port}'+self.path);self.send_header('Content-Length','0');self.end_headers();return
            self.request_app=manager.resolve(self)
            claimed=self.headers.get('X-Workspace-ID')
            if claimed and claimed!=self.workspace_id and self.path!='/api/studio-account':
                raise APIError('workspace_changed','The account changed in another window. Reload before continuing.',409)
            token=CURRENT_PROFILE.set(self.app.profile)
            try:return method(self)
            finally:CURRENT_PROFILE.reset(token)
        except APIError as e:return self.send(e.status,{'error':{'code':e.code,'message':str(e)}})
        except (BrokenPipeError,ConnectionResetError):return
        except Exception:return self.send(500,{'error':{'code':'local_error','message':'This operation could not finish. Your saved work is intact.'}})
    return call

class StudioHandler(Handler):
    def end_headers(self):
        if getattr(self,'session_cookie',None):self.send_header('Set-Cookie',self.session_cookie)
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        script_hash=''
        if self.path=='/tester':
            import hashlib
            inline=re.search(r'<script>(.*?)</script>',(ROOT/'tester.html').read_text(),re.S)
            if inline:script_hash=" 'sha256-"+base64.b64encode(hashlib.sha256(inline[1].encode()).digest()).decode()+"'"
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'"+script_hash+"; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def media(self,path,mime='video/mp4',attachment=None):
        size=path.stat().st_size;start,end,status=0,size-1,200;requested=self.headers.get('Range')
        if requested:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
            if not m or not any(m.groups()):return self.send(416,{'error':'Invalid media range.'})
            left,right=m.groups();start=int(left) if left else max(0,size-int(right));end=min(int(right),size-1) if left and right else size-1
            if start>end or start>=size:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
            status=206
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','private, no-store');self.send_header('X-Content-Type-Options','nosniff')
        if attachment:self.send_header('Content-Disposition',f'attachment; filename="{attachment}"')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    chunk=f.read(min(65536,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass

    def accounts_route(self,method):
        from agent_api import APIError
        manager=self.server.accounts;identity_request=None;controls=None
        try:
            browser=self.path.startswith('/api/')
            origin=self.headers.get('Origin');allowed=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
            if method!='GET' and browser and (origin not in allowed or self.headers.get('X-Tester')!='local'):raise APIError('origin_required','Local browser origin required.',403)
            if method!='GET' and browser and not self.session_hash:raise APIError('browser_session_required','A browser session is required to start human verification.',403)
            if not browser and (not self.app.agent.authorized(self.headers.get('Authorization')) or origin and origin not in allowed):raise APIError('unauthorized','Workspace bearer token required.',403)
            data={}
            if method!='GET':
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192:raise APIError('body_limit','Account request is too large.')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise APIError('invalid_request','Use a JSON object.')
            prefix='/api/studio-account' if browser else '/agent/v1/studio-account';parts=self.path[len(prefix):].strip('/').split('/') if self.path!=prefix else []
            if (parts==['codex'] or method=='GET' and not parts) and self.headers.get('X-Workspace-ID') not in (None,self.workspace_id):raise APIError('workspace_changed','This browser workspace changed. Reload Studio before reconnecting.',409)
            if not browser and parts in (['signin'],['logout'],['guest'],['restore-guest'],['cancel']):raise APIError('browser_session_required','Start identity or account switching from a browser session. Agents can manage their own workspace credentials.',403)
            controls=self.app.handoff.controls;identity_request=None
            if browser and self.headers.get('X-Handoff-Request'):
                if method!='POST' or len(parts)!=1:raise APIError('invalid_handoff','Use an identity action.')
                owner=self.app.handoff.owner(self.session_hash,self.headers.get('X-Browser-Tab'))
                identity_request=controls.identity_action(owner,self.headers['X-Handoff-Request'],parts[0])
            status,result=manager.dispatch(self,method,parts,data)
            if identity_request:controls.identity_result(identity_request,parts[0],result)
            return self.send(status,result)
        except APIError as e:
            if identity_request:
                identity_request.update(status='failed',error=str(e)[:500],revision=identity_request['revision']+1,updated_at=time.time());controls.persist()
            return self.send(e.status,{'error':{'code':e.code,'message':str(e)}})
        except (ValueError,TypeError,KeyError):return self.send(400,{'error':{'code':'invalid_request','message':'Invalid account request.'}})

    def browser_handoff_route(self,method):
        from agent_api import APIError
        try:
            if not getattr(self,'session_hash',None):raise APIError('browser_session_required','Browser context requires a human browser session.',403)
            if method!='GET' and (self.headers.get('Origin') not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}') or self.headers.get('X-Tester')!='local'):raise APIError('origin_required','Local browser origin required.',403)
            data={}
            if method!='GET':
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=270000:raise APIError('body_limit','Browser snapshot is too large.')
                data=json.loads(self.rfile.read(length))
            suffix=self.path[len('/api/browser-handoff'):].strip('/');parts=suffix.split('/') if suffix else []
            return self.send(200,self.app.handoff.browser_dispatch(self.session_hash,self.headers.get('X-Browser-Tab'),method,parts,data))
        except APIError as e:return self.send(e.status,{'error':{'code':e.code,'message':str(e)}})
        except (ValueError,TypeError,KeyError):return self.send(400,{'error':{'code':'invalid_request','message':'Invalid browser handoff.'}})

    def video_review_route(self, method):
        """Workspace-scoped review endpoints; starting review is a separate approval."""
        try:
            if not self.allowed_host():
                raise APIError('local_only', 'Local workspace access required.', 403)
            parsed=urlsplit(self.path)
            suffix=parsed.path[len('/api/video-review'):].strip('/')
            parts=suffix.split('/') if suffix else []
            if method=='GET' and len(parts)==3 and parts[0]=='evidence':
                return self.media(self.app.video_review.evidence_file(parts[1],parts[2]), 'image/jpeg')
            if method=='GET' and len(parts)==3 and parts[0]=='references':
                path,mime=self.app.video_review.reference_file(parts[1],parts[2])
                return self.media(path,mime)
            data={k:v[-1] for k,v in parse_qs(parsed.query).items()}
            if method!='GET':
                origin=self.headers.get('Origin')
                if origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}') or self.headers.get('X-Tester')!='local':
                    raise APIError('origin_required', 'Local browser origin required.', 403)
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256000:
                    raise APIError('body_limit','Video review request exceeds the local limit.',413)
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise APIError('invalid_request','Use a JSON object.')
            status,result=self.app.video_review.dispatch(method,parts,data,self.headers.get('Idempotency-Key'))
            return self.send(status,result)
        except APIError as exc:
            return self.send(exc.status,{'error':{'code':exc.code,'message':str(exc)}})
        except (ValueError,TypeError,KeyError):
            return self.send(400,{'error':{'code':'invalid_request','message':'Invalid video review request. Your saved work is intact.'}})
        except OSError:
            return self.send(500,{'error':{'code':'storage_error','message':'Video review evidence could not be read or saved.'}})

    @scoped_request
    def do_GET(self):
        if not self.allowed_host():return self.send(403,{'error':'Local access only.'})
        from static_assets import StaticAssets
        if not hasattr(self.server,'static_assets'):self.server.static_assets=StaticAssets(ROOT)
        if self.server.static_assets.serve(self):return
        if self.path.startswith('/api/project-archives/'):
            return self.app.archives.route(self, 'GET')
        if self.path.startswith('/api/previews/'):
            from agent_api import APIError
            from media_previews import MediaPreviews
            parsed=urlsplit(self.path);match=re.fullmatch(r'/api/previews/(image|take|upload)/([A-Za-z0-9_-]+)/(160|320|640|1280)',parsed.path)
            if not match:return self.send(404,{'error':'Preview not found.'})
            if parse_qs(parsed.query).get('workspace')!=[getattr(self,'workspace_id','local-owner')]:return self.send(403,{'error':'Open this preview in its workspace.'})
            try:
                with self.app.lock:
                    if not hasattr(self.app,'previews'):self.app.previews=MediaPreviews(self.app)
                raw,mime,state=self.app.previews.get(match[1],match[2],int(match[3]))
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','private, max-age=3600' if state=='ready' else 'no-store');self.send_header('X-Preview-State',state)
                self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw);return
            except (APIError,ValueError,OSError):return self.send(404,{'error':'Preview unavailable.'})
        if self.path.startswith('/api/browser-handoff'):return self.browser_handoff_route('GET')
        if self.path.startswith('/api/video-review'):return self.video_review_route('GET')
        if self.path.startswith('/api/studio-account') or self.path.startswith('/agent/v1/studio-account'):return self.accounts_route('GET')
        if self.path.startswith('/auth/callback?'):
            try:
                self.server.accounts.callback(self,parse_qs(urlsplit(self.path).query));body=b'<!doctype html><title>Connected</title><p>Connected to Imagine Studio.</p><a href="/">Continue to Studio</a><script src="/static/auth-complete.js"></script>'
                return self.send(200,body,'text/html; charset=utf-8')
            except Exception:return self.send(400,b'<!doctype html><title>Sign-in incomplete</title><p>Sign-in could not finish. Your work is intact.</p><a href="/">Return to Studio and try again</a>','text/html; charset=utf-8')
        if self.path.startswith('/auth/mock?'):
            try:self.server.accounts.mock_callback(self,parse_qs(urlsplit(self.path).query));return self.send(200,b'<!doctype html><title>Mock connection</title><p>Mock account connected. No provider contacted.</p><a href="/">Continue to Studio</a><script src="/static/auth-complete.js"></script>','text/html; charset=utf-8')
            except Exception:return self.send(400,{'error':'Mock sign-in did not finish.'})
        if self.path=='/static/workspace.js':
            # Scope browser drafts, and reject stale tabs after account switches.
            namespace='' if self.workspace_id=='local-owner' else 'workspace-'+self.workspace_id+':'
            code='window.studioWorkspaceId='+json.dumps(self.workspace_id)+';window.studioStoragePrefix='+json.dumps(namespace)+';'+(ROOT/'static/workspace-runtime.js').read_text()
            return self.send(200,code.encode(),'text/javascript')
        if self.path in ('/static/workspace-runtime.js','/static/auth-complete.js','/static/editing.css','/static/editing-workbench.css','/static/filmmaking.css','/static/world-workshop.css','/static/series-builder.css'):
            mime='text/css' if self.path.endswith('.css') else 'text/javascript';return self.send(200,(ROOT/self.path.lstrip('/')).read_bytes(),mime)
        if self.path.startswith('/api/edit-media/'):
            try:m,path=self.app.editing.media_file(self.path.rsplit('/',1)[1]);return self.media(path,m['mime'])
            except ValueError:return self.send(404,{'error':'Media not found in this workspace.'})
        if self.path.startswith('/api/exports/'):
            try:
                parts=self.path.strip('/').split('/');identity=parts[2];manifest=len(parts)==4 and parts[3]=='manifest';download=len(parts)==4 and parts[3]=='download'
                path=self.app.editing.file(identity,manifest);return self.media(path,'application/json' if manifest else 'video/mp4','edit.json' if manifest else 'studio-export.mp4' if download else None)
            except ValueError:return self.send(404,{'error':'Export not found or not ready in this workspace.'})
        if self.path.startswith('/agent/v1') or self.path.startswith('/api/agent'):
            return self.app.agent.serve(self, 'GET', self.path.startswith('/api/agent'))
        if not self.allowed_host():
            return self.send(403, {'error': 'Local access only.'})
        routes = {'/static/account-flow.js': ('static/account-flow.js','text/javascript'), '/static/account-ui.js': ('static/account-ui.js','text/javascript'), '/static/production.js': ('static/production.js', 'text/javascript'), '/static/production.css': ('static/production.css', 'text/css'), '/static/production-bridge.js': ('static/production-bridge.js','text/javascript'), '/': ('index.html', 'text/html; charset=utf-8'), '/tester': ('tester.html', 'text/html; charset=utf-8'),
                  '/static/named-scene.js': ('static/named-scene.js', 'text/javascript'), '/static/named-ui.js': ('static/named-ui.js', 'text/javascript'),
                  '/static/story-studio.js': ('static/story-studio.js', 'text/javascript'), '/static/story-studio.css': ('static/story-studio.css', 'text/css'),
                  '/static/frame-tools.js': ('static/frame-tools.js', 'text/javascript'),
                  '/static/provider-recovery.js': ('static/provider-recovery.js', 'text/javascript'),
                  '/static/scene-save.js': ('static/scene-save.js', 'text/javascript'),
                  '/static/asset-autocomplete.js': ('static/asset-autocomplete.js', 'text/javascript'), '/static/asset-autocomplete.css': ('static/asset-autocomplete.css', 'text/css'),
                  '/static/scenes.js': ('static/scenes.js', 'text/javascript'), '/static/studio.js': ('static/studio.js', 'text/javascript'), '/static/studio.css': ('static/studio.css', 'text/css'),
                  '/static/image-studio.js': ('static/image-studio.js', 'text/javascript'), '/static/image-studio.css': ('static/image-studio.css', 'text/css'),
                  '/static/media-prompting.js': ('static/media-prompting.js', 'text/javascript'), '/static/media-prompting.css': ('static/media-prompting.css', 'text/css'),
                  '/static/video-review.js': ('static/video-review.js', 'text/javascript'), '/static/video-review.css': ('static/video-review.css', 'text/css'),
                  '/static/mock-video.mp4': ('static/mock-video.mp4', 'video/mp4')}
        if self.path in routes:
            path, mime = routes[self.path]
            return self.send(200, (ROOT / path).read_bytes(), mime)
        if self.path.startswith('/api/video-media/'):
            try:
                path = self.app.download(self.path.rsplit('/', 1)[1])
                size = path.stat().st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get('Range')
                if requested:
                    match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                    if not match or not any(match.groups()):
                        raise ValueError('Invalid range')
                    left, right = match.groups()
                    start = int(left) if left else max(0, size-int(right))
                    end = min(int(right), size-1) if left and right else size-1
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header('Content-Range', f'bytes */{size}')
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    status = 206
                self.send_response(status)
                self.send_header('Content-Type', {'mov':'video/quicktime','webm':'video/webm'}.get(path.suffix.lstrip('.'),'video/mp4'))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Cache-Control', 'private, no-store')
                if status == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                with path.open('rb') as media:
                    media.seek(start)
                    remaining = end-start+1
                    while remaining:
                        chunk = media.read(min(65536, remaining))
                        if not chunk: break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            except (BrokenPipeError, ConnectionResetError):
                return
            except (ValueError, OSError):
                return self.send(400, {'error': 'Video unavailable. The saved output may have expired.'})
        if self.path.startswith('/api/download/'):
            try:
                path = self.app.download(self.path.rsplit('/', 1)[1])
                raw = path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', {'mov':'video/quicktime','webm':'video/webm'}.get(path.suffix.lstrip('.'),'video/mp4'))
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Content-Disposition', 'attachment; filename=imagine-video'+path.suffix)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(raw)
                return
            except (ValueError, OSError):
                return self.send(400, {'error': 'Download unavailable. The output URL may have expired.'})
        if self.path == '/api/assets':
            return self.send(200, self.app.library())
        if self.path == '/api/references':
            return self.send(200, self.app.named_library())
        if self.path == '/api/history':
            return self.send(200, self.app.records())
        if self.path == '/api/config':
            return self.send(200, {**CONFIG, 'models': MODELS, 'model_capabilities': MODEL_CAPABILITIES, 'ratios': RATIOS, 'voices': VOICES})
        if self.path.startswith('/api/assets/'):
            try:
                asset, path = self.app.asset(self.path.rsplit('/', 1)[1])
                return self.send(200, path.read_bytes(), asset['mime'])
            except (ValueError, OSError):
                return self.send(404, {'error': 'Image not found.'})
        return super().do_GET()

    @scoped_request
    def do_PATCH(self):
        return self.app.agent.serve(self, 'PATCH', self.path.startswith('/api/agent'))

    @scoped_request
    def do_PUT(self):
        return self.app.agent.serve(self, 'PUT', self.path.startswith('/api/agent'))

    @scoped_request
    def do_POST(self):
        if self.path.startswith('/api/project-archives/'):
            return self.app.archives.route(self, 'POST')
        if self.path.startswith('/api/browser-handoff'):return self.browser_handoff_route('POST')
        if self.path.startswith('/api/video-review'):return self.video_review_route('POST')
        if self.path.startswith('/api/studio-account') or self.path.startswith('/agent/v1/studio-account'):return self.accounts_route('POST')
        if self.path.startswith('/agent/v1') or self.path.startswith('/api/agent'):
            return self.app.agent.serve(self, 'POST', self.path.startswith('/api/agent'))
        if self.path in ('/api/login', '/api/generate'):
            return super().do_POST()
        origin = self.headers.get('Origin')
        if not self.allowed_host() or self.headers.get('X-Tester') != 'local' or origin not in (
                f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            return self.send(403, {'error': 'Local browser origin required.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= (CONFIG['upload_limit_mb'] * 1024 * 1024 * 4 // 3 + 8192):
                raise ValueError('Request exceeds the configured local size limit.')
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/grok/check':
                return self.send(200, self.app.check_grok_connection())
            if self.path == '/api/upload':
                return self.send(201, self.app.upload(data))
            if self.path == '/api/references/save':
                return self.send(200, self.app.save_reference(data))
            if self.path == '/api/references/archive':
                return self.send(200, self.app.archive_reference(data['id'], data.get('archived') is True))
            if self.path == '/api/validate':
                from workflow_tools import start_frame_gate
                frame_gate=start_frame_gate(self.app,data['settings'])
                if not frame_gate['allowed']:return self.send(200,dict(valid=False,request=data['settings'],start_frame_gate=frame_gate,prompt_generation_blocked=True,prompt_issues=[]))
                body = self.app.resolve(data['settings'])
                status = self.app.prompting.request_status(body, data.get('scene_id'), data['settings'].get('_studio_scene'))
                from workflow_tools import start_frame_gate,check,usage
                gate=start_frame_gate(self.app,data['settings'])
                preflight=check(self.app,dict(scene_id=data.get('scene_id'),scene=data['settings'].get('_studio_scene'),prompt=data['settings'].get('_studio_scene',{}).get('prompt',body.get('prompt',''))))
                return self.send(200, {'valid': True, 'request': body, **status,'start_frame_gate':gate,'preflight':preflight,'usage':usage(self.app)})
            if self.path == '/api/resume':
                self.app.resume(data['id'])
                return self.send(202, {'ok': True})
            if self.path == '/api/video':
                identity = self.app.start_video(data['settings'], data.get('approved') is True)
                return self.send(202, {'id': identity})
            return self.send(404, {'error': 'Not found.'})
        except ValueError as exc:
            # Only local validation text reaches this handler; OAuth exceptions are caught in workers.
            return self.send(400, {'error': str(exc)})
        except (TypeError, KeyError, AttributeError) as exc:
            from request_diagnostics import structure_failure
            operation='validate this video request' if self.path=='/api/validate' else 'process this request'
            return self.send(400, {'error': structure_failure(exc,operation)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Use stored OAuth. Generations still require the config approval gate.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--state-dir', type=Path, default=STATE, help='Separate local assets, scenes, history and agent token.')
    parser.add_argument('--private-workspaces',action='store_true',help='Create a separate guest workspace for every browser session; never share this Mac owner credentials.')
    args = parser.parse_args()
    from ffmpeg_runtime import require_supported_linux
    try:
        require_supported_linux()
    except RuntimeError as error:
        parser.error(str(error))
    require_migration()
    args.state_dir = outside_source(args.state_dir)
    http = ThreadingHTTPServer(('127.0.0.1', args.port), StudioHandler)
    http.tester = Studio(mock=not args.live, storage=args.state_dir)
    from workspace_accounts import WorkspaceAccounts
    http.accounts=WorkspaceAccounts(http.tester,args.private_workspaces,mock_identity=not args.live)
    print(f'Imagine Studio: http://127.0.0.1:{args.port} ({"live" if args.live else "mock"})', flush=True)
    http.serve_forever()
