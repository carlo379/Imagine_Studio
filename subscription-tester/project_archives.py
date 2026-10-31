"""Portable, project-scoped archives. Never copy workspace credentials or databases.

ZIP members are explicit media paths plus a versioned JSON payload. Imports are
validated and staged before publishing, and all identities are remapped.
"""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit

from agent_api import APIError
from production_studio import OWNER

FORMAT = 'imagine-studio-project'
VERSION = 1
MAX_ARCHIVE = 20 * 1024**3
MAX_EXPANDED = 50 * 1024**3
MAX_JSON = 512 * 1024**2
MAX_DOCUMENT_JSON = 64 * 1024**2
MAX_MEMBERS = 100000
KINDS = set('image-bible-preview asset asset-development assistant caption-job direction edit-media episode-book episode-script-draft export image-job-audit imported-video media-prompt-job opening-frame-backup opening-frame-job production scene-layout script-upload-review series-bible series-member shot timeline video-direction-backup video-direction-job world world-asset world-entity world-job world-render'.split())
KINDS.update(('song-project','song-analysis','song-shot','song-review','song-assembly','song-comparison'))
STORES = {'evidence.reviews', 'sql', 'assets', 'references', 'history', 'video.scenes', 'video.urls', 'image.drafts', 'image.jobs', 'story.series', 'story.episodes', 'story.links', 'story.chats'}
FILE_PATH = re.compile(r'(?:assets/[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)|videos/[A-Za-z0-9_-]+\.mp4|edit-media/[A-Za-z0-9_-]+\.[a-z0-9]+|exports/[A-Za-z0-9_-]+/(?:export\.mp4|edit\.json|captions\.srt)|(?:video-request-snapshots|video-review-evidence)/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.(?:json|bin|jpg))\Z')
IDENTITY = re.compile(r'[A-Za-z0-9_-]{1,150}\Z')
SECRET_FIELDS = {'authorization','access_token','refresh_token','api_key','agent_token','cookie','cookies','headers','agent_key','agent_fingerprint','key','fingerprint'}


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k.lower() not in SECRET_FIELDS}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def identity_field(field):
    return field == 'id' or field.endswith(('_id', '_ids', 'Id', 'Ids'))


def defined_ids(value):
    if isinstance(value, dict):
        for k,v in value.items():
            if k in ('id','url_id') and isinstance(v,str) and IDENTITY.fullmatch(v) and not re.fullmatch(r'(?:frame|input)-\d{1,2}',v): yield v
            elif isinstance(v,(dict,list)): yield from defined_ids(v)
    elif isinstance(value,list):
        for item in value: yield from defined_ids(item)


def identifiers(value, field=''):
    """Only structured identities and local media URLs; never scan prose/prompts."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in ('parent_production_id', 'world_origin_id'):
                yield from identifiers(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from identifiers(v, field)
    elif isinstance(value, str):
        if identity_field(field):
            yield value
        if value.startswith(('/api/assets/', '/api/video-media/', '/api/edit-media/', '/api/exports/')):
            yield value.split('/')[3]


def owned_ids(value):
    """Reverse edges are ownership only, so shared inputs cannot collect other projects."""
    for field in ('production_id', 'episode_id', 'song_project_id', 'song_shot_id', 'shot_id', 'timeline_id', 'draft_id', 'world_job_id', 'entity_id', 'video_job_id', 'scene_id', 'media_id', 'video_id', 'image_id', 'job_id'):
        if value.get(field):
            yield value[field]
    for field in ('draft', 'context', 'story_context', 'settings'):
        nested = value.get(field)
        if isinstance(nested, dict):
            if field == 'draft' and nested.get('id'):
                yield nested['id']
            yield from owned_ids(nested)
            if nested.get('_studio_video_id'):
                yield nested['_studio_video_id']
            if isinstance(nested.get('_studio_story'), dict):
                yield from owned_ids(nested['_studio_story'])
    if value.get('version_root_id'):
        yield value['version_root_id']


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class ProjectArchives:
    def __init__(self, app):
        self.app = app
        self.jobs = {}
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.folder = app.storage / 'project-archives'
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def workspace_lock(self):
        with ExitStack() as stack:
            for service in (self.app.agent, self.app.images, self.app.stories, self.app.video_review, self.app):
                stack.enter_context(service.lock)
            yield

    def status(self, identity):
        with self.lock:
            if identity not in self.jobs and isinstance(identity,str) and re.fullmatch('[a-f0-9]{32}',identity):
                saved=self.folder/(identity+'.json')
                if saved.is_file(): self.jobs[identity]=json.loads(saved.read_text())
            if identity not in self.jobs:
                raise APIError('not_found', 'Archive task not found. Start a new export or import.', 404)
            return copy.deepcopy(self.jobs[identity])

    def update(self, identity, **fields):
        with self.lock:
            self.jobs[identity].update(fields)
            if fields.get('status') in ('done','error'):
                self.app.agent.save(self.folder/(identity+'.json'),self.jobs[identity])

    def start(self, operation, argument):
        if not self.operation.acquire(blocking=False):
            raise APIError('archive_busy', 'Wait for the current project export or import.', 409)
        identity = uuid.uuid4().hex
        with self.lock:
            self.jobs[identity] = dict(id=identity, operation=operation, status='working', message='Preparing project…', progress=0)
        try:
            self.app.spawn(self.worker, identity, operation, argument)
        except Exception:
            self.operation.release()
            raise
        return self.status(identity)

    def worker(self, identity, operation, argument):
        try:
            result = self.export(identity, argument) if operation == 'export' else self.restore(identity, argument)
            self.update(identity, status='done', progress=100, message='Project archive ready.' if operation == 'export' else 'Project imported as a separate copy.', **result)
        except Exception as exc:
            message = 'The ZIP is damaged or could not be read.' if isinstance(exc,(zipfile.BadZipFile,EOFError)) else str(exc) if isinstance(exc, APIError) else 'Project archive failed. Check available disk space and try again.'
            self.update(identity, status='error', message=message)
        finally:
            if operation == 'import':
                Path(argument).unlink(missing_ok=True)
            (self.folder / (identity + '.part')).unlink(missing_ok=True)
            self.operation.release()

    def inventory(self):
        app = self.app
        values = []
        for kind, body in app.productions.sql.execute('SELECT kind,body FROM records WHERE owner=?', (OWNER,)):
            if kind in KINDS:
                record = json.loads(body)
                versions = [json.loads(r[0]) for r in app.productions.sql.execute('SELECT body FROM versions WHERE id=? AND owner=? ORDER BY revision', (record['id'], OWNER))]
                values.append(dict(store='sql', kind=kind, record=record, versions=versions))
        other_history=app.storage/('history.json' if app.mock else 'mock-history.json')
        video_history=list(app.history)
        if other_history.is_file():
            existing={r['id'] for r in video_history}
            video_history.extend(r for r in json.loads(other_history.read_text()) if r['id'] not in existing)
        collections = {'evidence.reviews': app.video_review.db['reviews'], 'assets': app.assets, 'references': app.references, 'history': video_history}
        for prefix, service, fields in [('video', app.agent, ('scenes', 'urls')), ('image', app.images, ('drafts', 'jobs')), ('story', app.stories, ('series', 'episodes', 'links', 'chats'))]:
            collections.update({prefix + '.' + field: service.db.get(field, []) for field in fields})
        for store, rows in collections.items():
            values.extend(dict(store=store, record=r) for r in rows)
        return copy.deepcopy(values)

    def snapshot(self, pid):
        with self.workspace_lock():
            project = self.app.productions.get(pid, 'production')
            rows = self.inventory()
            group = {pid}
            while True:
                children = {e['record']['id'] for e in rows if e.get('kind') == 'production' and (e['record'].get('parent_production_id') in group or e['record'].get('world_origin_id') in group)}
                if children <= group:
                    break
                group |= children
            series_ids={e['record'].get('series_id') for e in rows if e.get('kind')=='production' and e['record']['id'] in group}
            excluded={e['record']['id'] for e in rows if e.get('kind')=='production' and e['record']['id'] not in group}
            excluded.update(e['record']['id'] for e in rows if e['store']=='story.series' and e['record']['id'] not in series_ids)
            excluded.update(e['record']['id'] for e in rows if e['store']=='story.episodes' and e['record'].get('series_id') not in series_ids)
            selected = set()
            known = set(group)
            # Primary entities are allowed to own dependent jobs. Shared reference
            # assets are forward-only dependencies and do not pull unrelated uses.
            anchors = set(group)
            reference_handles={e['record'].get('handle'):e['record']['id'] for e in rows if e['store']=='references'}
            while True:
                before = (len(selected),len(anchors),len(known))
                for i, entry in enumerate(rows):
                    r = entry['record']
                    primary = r.get('id') in group or bool(set(owned_ids(r)) & anchors)
                    if i not in selected and (primary or r.get('id',r.get('url_id')) in known):
                        selected.add(i)
                        known.update(value for value in identifiers(entry) if value not in excluded)
                    if i in selected:
                        if entry['store']=='story.series':
                            known.update(reference_handles[h] for h in r.get('assets',[]) if h in reference_handles)
                        # A forward dependency may become an owning entity on a
                        # later pass (e.g. a take selected by a timeline before
                        # its draft is visited). Promote it even if already seen.
                        if primary or entry['store'] in ('video.scenes','image.drafts','story.series','story.episodes') or entry.get('kind') in ('shot','world-entity','world-asset','timeline'):
                            if r.get('id') not in anchors:
                                anchors.add(r.get('id'))
                                anchors.update(identifiers({'scenes':r.get('scenes',[])}))
                        if r.get('series_id') and entry.get('kind')=='production' and r['id'] in group:
                            known.add(r['series_id']);anchors.add(r['series_id'])
                    if entry['store']=='story.episodes' and r.get('series_id') in anchors:
                        known.add(r['id'])
                if (len(selected),len(anchors),len(known)) == before:
                    break
            result = [clean(rows[i]) for i in sorted(selected)]
            for entry in result:
                r = entry['record']
                if r.get('status') in ('pending','queued','rendering','generating','running'):
                    raise APIError('project_busy', 'Wait for this project’s generation, writing or video export to finish, then export again.', 409)
                if entry.get('kind') == 'production' and r.get('parent_production_id') not in anchors:
                    r['parent_production_id'] = None
            return project, result

    def export(self, identity, pid):
        project, rows = self.snapshot(pid)
        self.update(identity, message='Collecting project media…', progress=10)
        files = {}
        missing = []
        def add(relative, source=None):
            if not FILE_PATH.fullmatch(relative):
                raise APIError('invalid_media', 'A saved media path is invalid.')
            source = Path(source) if source else self.app.storage / relative
            if not source.is_file():
                if relative not in missing:
                    missing.append(relative)
                return
            # Never follow a saved file symlink into credential or external folders.
            if source != source.resolve():
                missing.append(relative)
                return
            files[relative] = source
        for entry in rows:
            r = entry['record']; kind = entry.get('kind')
            if entry['store'] == 'assets':
                add(f"assets/{r['id']}.{r['ext']}")
            if kind == 'edit-media':
                add(f"edit-media/{r['id']}.{r['ext']}")
            if entry['store'] == 'history' and r.get('status') == 'done' and r.get('video') and not r.get('imported_media_id'):
                relative = 'videos/' + r['id'] + '.mp4'
                try:
                    source = self.app.download(r['id'], archive_record=r)
                    add(relative, source)
                    r['video'] = '/api/video-media/' + r['id']
                    r['archive_local_video'] = True
                except (ValueError, OSError):
                    missing.append(relative)
            categories = []
            if entry['store'] == 'history' and r.get('request_snapshot'):
                categories.append('video-request-snapshots')
            if entry['store'] == 'evidence.reviews':
                categories.append('video-review-evidence')
            for category in categories:
                folder = self.app.storage / category / r['id']
                if folder.is_dir():
                    for item in sorted(folder.iterdir()):
                        if item.is_file() and FILE_PATH.fullmatch(f'{category}/{r["id"]}/{item.name}'):
                            add(f'{category}/{r["id"]}/{item.name}')
                elif category == 'video-request-snapshots':
                    missing.append(f'{category}/{r["id"]}/request.json')
            if kind == 'export' and r.get('status') == 'done':
                for name in ('export.mp4', 'edit.json', 'captions.srt'):
                    relative = f"exports/{r['id']}/{name}"
                    if name == 'export.mp4' or (self.app.storage / relative).is_file():
                        add(relative)
        # Remote input images are intentionally not fetched from arbitrary URLs.
        # They are retained as metadata and explicitly listed as non-portable.
        asset_ids = {e['record']['id'] for e in rows if e['store'] == 'assets'}
        def missing_links(value):
            if isinstance(value,dict):
                for v in value.values(): missing_links(v)
            elif isinstance(value,list):
                for v in value: missing_links(v)
            elif isinstance(value,str) and value.startswith('/api/assets/'):
                aid = value.split('/')[3]
                if aid not in asset_ids: missing.append('Image asset ' + aid + ' (record missing)')
        missing_links(rows)
        remote = set()
        def urls(v):
            if isinstance(v, dict):
                for k, item in v.items():
                    if k in ('src','url') and isinstance(item, str) and item.startswith(('https://','http://')):
                        remote.add(item)
                    urls(item)
            elif isinstance(v, list):
                for item in v: urls(item)
        urls(rows)
        report = dict(complete=not missing and not remote, missing_files=sorted(set(missing)), remote_references=sorted(remote))
        manifest = dict(format=FORMAT, version=VERSION, title=project['title'], project_id=pid, mock=self.app.mock, created_at=time.time(), records=rows, files=[], report=report)
        temp = self.folder / (identity + '.part')
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            total = len(files)
            for n, (relative, source) in enumerate(sorted(files.items())):
                # Hash the actual archived bytes in one pass, including large videos.
                sha = hashlib.sha256(); size = 0
                with source.open('rb') as inp, archive.open('media/' + relative, 'w', force_zip64=True) as out:
                    for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                        sha.update(chunk); size += len(chunk); out.write(chunk)
                manifest['files'].append(dict(path=relative, size=size, sha256=sha.hexdigest()))
                self.update(identity, message=f'Packaging media {n+1} of {total}…', progress=10 + int(80 * (n+1) / max(1,total)))
            if len(rows)>MAX_MEMBERS or len(manifest['files'])>MAX_MEMBERS-10:
                raise APIError('archive_limit','The project contains too many archive records or files.')
            # Stream compact JSON instead of building an indented copy of every
            # historical snapshot in RAM. Compress metadata; keep media original.
            info=zipfile.ZipInfo('project.json')
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o600 << 16
            metadata_bytes=0
            encoder=json.JSONEncoder(ensure_ascii=False,separators=(',',':'))
            with archive.open(info,'w',force_zip64=True) as output:
                for fragment in encoder.iterencode(manifest):
                    chunk=fragment.encode('utf-8');metadata_bytes+=len(chunk)
                    if metadata_bytes>MAX_JSON:
                        raise APIError('archive_limit',f'Project metadata exceeds the {MAX_JSON//1024**2} MB limit; no history was removed.')
                    output.write(chunk)
            archive.writestr('Export report.json', json.dumps(report, ensure_ascii=False, indent=2))
            archive.writestr('README.txt', 'Imagine Studio project archive\n\nImport this ZIP through Your projects → Import project.\nproject.json preserves editable records, prompts and revision history.\nmedia/ contains original files. documents/ contains readable saved books.\nCheck Export report.json for missing files and external references.\nCredentials and browser-only unsaved drafts are excluded.\n')
            catalog=[]
            for entry in rows:
                r=entry['record']
                if entry['store']=='references' or entry.get('kind')=='world-entity':
                    catalog.append('## '+r.get('category','Asset')+': '+r.get('name',r.get('title','Asset'))+'\n\n'+r.get('description',''))
                    if r.get('profile'): catalog.append('```json\n'+json.dumps(r['profile'],indent=2,ensure_ascii=False)+'\n```')
            archive.writestr('documents/Assets.md','# Characters, locations and props\n\n'+'\n\n'.join(catalog))
            prompts = []
            def collect_prompts(value, label):
                if isinstance(value,dict):
                    for field,v in value.items():
                        if field in ('prompt','expanded_prompt','image_prompt','video_prompt','message','instruction') and isinstance(v,str) and v:
                            prompts.append('## ' + label + ' / ' + field + '\n\n' + v)
                        elif isinstance(v,(dict,list)): collect_prompts(v,label+' / '+field)
                elif isinstance(value,list):
                    for n,v in enumerate(value): collect_prompts(v,label+' '+str(n+1))
            for e in rows: collect_prompts(e['record'],e['store']+' '+e['record'].get('title',e['record'].get('id','')))
            archive.writestr('documents/Prompts.md','# Saved prompts and writing instructions\n\n'+'\n\n'.join(prompts),compress_type=zipfile.ZIP_DEFLATED)
            from document_exports import manuscript
            for entry in rows:
                r = entry['record']
                if entry.get('kind') in ('series-bible','episode-book','world'):
                    archive.writestr('documents/' + r['id'] + '.md', manuscript(r, r.get('answers',{}).get('title') or project['title']))
                if entry['store'] == 'story.episodes':
                    script = '# ' + r['title'] + '\n\n' + '\n\n'.join('## ' + s['title'] + '\n\n' + s['text'] for s in r.get('scenes', []))
                    archive.writestr('documents/' + r['id'] + '-script.md', script)
            if len(archive.infolist()) > MAX_MEMBERS:
                raise APIError('archive_limit','The project contains too many archive members.')
        if temp.stat().st_size > MAX_ARCHIVE:
            raise APIError('archive_limit','The project exceeds the current 20 GB archive limit.')
        temp.chmod(0o600)
        temp.replace(self.folder / (identity + '.zip'))
        return dict(title=project['title'], report=report, download='/api/project-archives/' + identity + '/download', record_count=len(rows), file_count=len(files))

    def download(self, identity):
        task = self.status(identity)
        if task['status'] != 'done' or task['operation'] != 'export':
            raise APIError('not_ready', 'The project archive is not ready.', 409)
        return self.folder / (identity + '.zip')

    def validate(self, archive):
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(members) > MAX_MEMBERS or len(set(names)) != len(names) or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise APIError('invalid_archive', 'Archive has duplicate entries or exceeds the extraction limits.')
        for m in members:
            p = PurePosixPath(m.filename)
            mode = m.external_attr >> 16
            if p.is_absolute() or '..' in p.parts or '\\' in m.filename or m.flag_bits & 1 or (mode & 0o170000) == 0o120000:
                raise APIError('invalid_archive', 'Archive contains an unsafe path, symlink or encrypted entry.')
        try:
            if archive.getinfo('project.json').file_size > MAX_JSON:
                raise APIError('invalid_archive', f'Project metadata exceeds {MAX_JSON//1024**2} MB.')
            manifest = json.loads(archive.read('project.json'))
        except (KeyError, ValueError):
            raise APIError('invalid_archive', 'This ZIP does not contain a valid Imagine Studio project.') from None
        if not isinstance(manifest,dict) or manifest.get('format') != FORMAT or type(manifest.get('version')) is not int or manifest['version'] != VERSION:
            raise APIError('archive_version', 'This project archive format is not supported by this version of Studio.')
        rows = manifest.get('records'); files = manifest.get('files')
        if not isinstance(rows,list) or not isinstance(files,list) or not isinstance(manifest.get('title'),str) or len(manifest['title']) > 120:
            raise APIError('invalid_archive', 'Invalid project records or file manifest.')
        if len(rows) > MAX_MEMBERS:
            raise APIError('invalid_archive','Too many project records.')
        report=manifest.get('report')
        if not isinstance(report,dict) or type(report.get('complete')) is not bool or any(not isinstance(report.get(k),list) or any(not isinstance(v,str) for v in report[k]) for k in ('missing_files','remote_references')):
            raise APIError('invalid_archive','Invalid export completeness report.')
        identities = set()
        for entry in rows:
            if not isinstance(entry,dict) or entry.get('store') not in STORES or not isinstance(entry.get('record'),dict):
                raise APIError('invalid_archive', 'Unknown project record collection.')
            r = entry['record']; rid = r.get('id',r.get('url_id'))
            if not isinstance(rid,str) or not IDENTITY.fullmatch(rid) or (entry['store'],rid) in identities:
                raise APIError('invalid_archive', 'Project identities must be valid and unique.')
            identities.add((entry['store'],rid))
            shapes = {
                'video.scenes': {'title':str,'scene':dict},
                'video.urls': {'src':str,'url_id':str},
                'image.drafts': {'title':str,'settings':dict},
                'image.jobs': {'draft':dict,'outputs':list,'status':str,'mock':bool},
                'history': {'settings':dict,'status':str,'mock':bool},
                'story.series': {'title':str,'assets':list},
                'story.episodes': {'title':str,'series_id':str,'scenes':list,'versions':list},
                'references': {'title':str,'handle':str,'images':list},
                'evidence.reviews': {'status':str,'video_job_id':str},
            }
            sql_shapes = {
                'production': {'title':str,'kind':str}, 'shot': {'production_id':str,'title':str},
                'series-bible': {'production_id':str,'answers':dict,'guide':dict},
                'episode-book': {'production_id':str,'episode_id':str,'answers':dict,'guide':dict},
                'world': {'production_id':str,'answers':dict},
                'timeline': {'production_id':str,'clips':list,'audio':list},
                'export': {'status':str,'snapshot':dict},
                'imported-video': {'settings':dict,'imported_media_id':str},
                'edit-media': {'ext':str,'mime':str},
            }
            shape = sql_shapes.get(entry.get('kind'),{}) if entry['store']=='sql' else shapes.get(entry['store'],{})
            if any(type(r.get(field)) is not expected for field,expected in shape.items()):
                raise APIError('invalid_archive','A project record has missing or invalid fields.')
            if entry.get('kind')=='production' and r['kind'] not in ('quick','story'):
                raise APIError('invalid_archive','Unknown project kind.')
            if entry['store'] == 'assets' and (r.get('ext') not in ('png','jpg','jpeg','webp') or r.get('src') != '/api/assets/'+rid):
                raise APIError('invalid_archive','Invalid image asset metadata.')
            if entry.get('kind') == 'edit-media' and r.get('ext') not in ('mp4','mov','webm','mp3','wav','m4a','ogg','aac','png','jpg','jpeg','webp'):
                raise APIError('invalid_archive','Invalid editing media metadata.')
            if entry['store'] == 'sql' and (entry.get('kind') not in KINDS or type(r.get('revision')) is not int or r['revision'] < 1 or not isinstance(entry.get('versions',[]),list)):
                raise APIError('invalid_archive', 'Invalid saved project record.')
            for version in entry.get('versions',[]):
                if not isinstance(version,dict) or version.get('id') != rid or type(version.get('revision')) is not int:
                    raise APIError('invalid_archive', 'Invalid project revision history.')
        if not any(e.get('kind') == 'production' and e['record']['id'] == manifest.get('project_id') for e in rows):
            raise APIError('invalid_archive', 'The archive root project is missing.')
        paths = set()
        for f in files:
            if not isinstance(f,dict) or not isinstance(f.get('path'),str) or not FILE_PATH.fullmatch(f['path']) or f['path'] in paths or type(f.get('size')) is not int or not isinstance(f.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}', f['sha256']):
                raise APIError('invalid_archive', 'Invalid media manifest.')
            paths.add(f['path'])
            if 'media/' + f['path'] not in names or archive.getinfo('media/' + f['path']).file_size != f['size']:
                raise APIError('invalid_archive', 'An archived media file is missing or has an invalid size.')
        return manifest

    def restore(self, identity, source):
        self.update(identity, message='Validating project archive…', progress=5)
        try:
            archive = zipfile.ZipFile(source)
        except zipfile.BadZipFile:
            raise APIError('invalid_archive', 'Choose an Imagine Studio project ZIP.') from None
        with archive, tempfile.TemporaryDirectory(prefix='import-', dir=self.folder) as staging:
            manifest = self.validate(archive)
            rows = clean(manifest['records'])
            # Remap all structured nested identities (cards, clips, scenes, etc.) as
            # well as top-level records. Never substitute text inside user prose.
            mapping = {value: uuid.uuid4().hex for value in defined_ids(rows)}
            for value in identifiers(rows):
                if value.startswith('reference-') and value[len('reference-'):] in mapping:
                    mapping[value]='reference-'+mapping[value[len('reference-'):]]
            for e in rows:
                r = e['record']
                if r.get('url_id'): mapping.setdefault(r['url_id'], uuid.uuid4().hex)
            def rewrite(v, field=''):
                if isinstance(v,dict): return {k:rewrite(item,k) for k,item in v.items()}
                if isinstance(v,list): return [rewrite(item,field) for item in v]
                if not isinstance(v,str): return v
                if identity_field(field):
                    return mapping.get(v,v)
                if FILE_PATH.fullmatch(v): return remap_path(v)
                if v.startswith(('/api/assets/','/api/video-media/','/api/edit-media/','/api/exports/')):
                    parts=v.split('/');parts[3]=mapping.get(parts[3],parts[3]);return '/'.join(parts)
                return v
            def remap_path(path):
                parts = path.split('/')
                if parts[0] in ('exports','video-request-snapshots','video-review-evidence'):
                    parts[1] = mapping.get(parts[1],parts[1])
                    stem,ext=parts[2].rsplit('.',1)
                    parts[2]=mapping.get(stem,stem)+'.'+ext
                else:
                    stem, ext = parts[1].rsplit('.',1);parts[1] = mapping.get(stem,stem) + '.' + ext
                return '/'.join(parts)
            staged = []
            rewritten_hashes = {}
            for n, f in enumerate(manifest['files']):
                relative = remap_path(f['path'])
                if relative == f['path']:
                    raise APIError('invalid_archive', 'Media file has no matching project identity.')
                dest = Path(staging) / relative; dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                sha = hashlib.sha256()
                with archive.open('media/' + f['path']) as inp, dest.open('xb') as out:
                    for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                        sha.update(chunk);out.write(chunk)
                if sha.hexdigest() != f['sha256']:
                    raise APIError('invalid_archive', 'A media checksum does not match. The project was not imported.')
                dest.chmod(0o600)
                if relative.endswith('.json'):
                    if dest.stat().st_size > MAX_DOCUMENT_JSON: raise APIError('invalid_archive','Editing metadata exceeds 64 MB.')
                    dest.write_text(json.dumps(rewrite(json.loads(dest.read_text()))))
                    rewritten_hashes[relative] = digest_file(dest)
                staged.append((dest,self.app.storage/relative))
                self.update(identity, message=f'Checking media {n+1} of {len(manifest["files"])}…', progress=10 + int(70*(n+1)/max(1,len(manifest['files']))))
            rows = rewrite(rows)
            def update_hashes(value):
                if isinstance(value,dict):
                    if isinstance(value.get('path'),str) and value['path'] in rewritten_hashes and 'sha256' in value:
                        value['sha256'] = rewritten_hashes[value['path']]
                    for v in value.values(): update_hashes(v)
                elif isinstance(value,list):
                    for v in value: update_hashes(v)
            update_hashes(rows)
            root = mapping[manifest['project_id']]
            imported_productions={e['record']['id'] for e in rows if e.get('kind')=='production'}
            imported_episodes={e['record']['id'] for e in rows if e['store']=='story.episodes'}
            def detach_external(value):
                if isinstance(value,dict):
                    if value.get('production_id') and value['production_id'] not in imported_productions:
                        value['production_id']=root
                    if value.get('episode_id') and value['episode_id'] not in imported_episodes:
                        value['episode_id']=None
                    for v in value.values(): detach_external(v)
                elif isinstance(value,list):
                    for v in value: detach_external(v)
            detach_external(rows)
            for entry in rows:
                r = entry['record']
                # Imports never resume remote requests, apply stale idempotency keys,
                # or fetch external video URLs. Existing media remains playable.
                if 'mock' in r:
                    r['archive_source_mock'] = r['mock'];r['mock'] = self.app.mock
                if 'recoverable' in r: r['recoverable'] = False
                if r.get('status') in ('pending','queued','rendering','generating','running'):
                    r.update(status='error', error='Interrupted work was imported. No request was resumed.')
                if entry['store'] == 'history' and r.get('video'):
                    r['archive_local_video'] = True
                    r['video'] = '/api/video-media/' + r['id']
                if entry.get('kind') == 'production' and r['id'] == root:
                    r.update(title=(manifest['title'][:100] + ' (imported)'), parent_production_id=None, archived=False)
            self.update(identity, message='Saving imported project…', progress=90)
            self.publish(rows, staged)
            return dict(project_id=root, title=manifest['title'], report=manifest.get('report',{}), record_count=len(rows), file_count=len(staged))

    def publish(self, rows, staged):
        app = self.app
        with self.workspace_lock(), tempfile.TemporaryDirectory(prefix='rollback-',dir=self.folder) as recovery:
            services = (app.agent,app.images,app.stories,app.video_review)
            old = [copy.deepcopy(s.db) for s in services]
            previous = [copy.deepcopy(v) for v in (app.assets,app.references,app.history)]
            # Canonical reference handles must remain unique; immutable attached
            # snapshots and their original @mentions remain unchanged.
            used={r.get('handle','').casefold() for r in app.references}
            renamed={}
            for entry in rows:
                r=entry['record']
                if entry['store']=='references' and r.get('handle'):
                    handle=r['handle']
                    if handle.casefold() in used:
                        suffix='_import_'+r['id'][:8]
                        handle=handle[:max(1,app.agent.config['reference_handle_limit']-len(suffix))]+suffix
                        renamed[r['id']]=handle
                        r['archive_original_handle']=r['handle'];r['handle']=handle
                    used.add(handle.casefold())
            renamed_handles={entry['record']['archive_original_handle']:entry['record']['handle'] for entry in rows if entry['store']=='references' and entry['record']['id'] in renamed}
            for entry in rows:
                if entry['store']=='story.series':
                    entry['record']['assets']=[renamed_handles.get(h,h) for h in entry['record'].get('assets',[])]
                if entry.get('kind')=='asset' and entry['record']['id'] in renamed:
                    entry['record']['handle']=renamed[entry['record']['id']]
            paths=[service.path for service in services]+[app.assets_path,app.references_path,app.history_path]
            backups=[]
            for n,path in enumerate(paths):
                backup=Path(recovery)/str(n)
                if path.exists(): shutil.copy2(path,backup)
                backups.append((path,backup if path.exists() else None))
            moved = []
            try:
                with app.productions.sql:
                    for src,dest in staged:
                        dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                        if dest.exists(): raise APIError('import_collision','An imported file identity already exists. Try importing again.')
                        src.replace(dest);moved.append(dest)
                    for entry in rows:
                        r = entry['record']; store = entry['store']
                        if store == 'sql':
                            if app.productions.sql.execute('SELECT 1 FROM records WHERE id=?',(r['id'],)).fetchone():
                                raise APIError('import_collision','An imported record identity already exists.')
                            app.productions.sql.execute('INSERT INTO records VALUES (?,?,?,?)',(r['id'],entry['kind'],OWNER,json.dumps(r)))
                            for v in entry.get('versions',[]):
                                app.productions.sql.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?,?)',(r['id'],v['revision'],OWNER,json.dumps(v)))
                        elif '.' in store:
                            prefix, field=store.split('.')
                            service={'video':app.agent,'image':app.images,'story':app.stories,'evidence':app.video_review}[prefix]
                            service.db.setdefault(field,[]).append(r)
                        else:
                            getattr(app,store).append(r)
                    for s in services: app.agent.save(s.path,s.db)
                    for name,path in [('assets',app.assets_path),('references',app.references_path),('history',app.history_path)]:
                        app.agent.save(path,getattr(app,name))
            except Exception:
                for s, db in zip(services,old): s.db=db
                app.assets,app.references,app.history=previous
                # Restoring prewritten files by rename also works when no free
                # disk space remains for a fresh JSON write.
                try:
                    for path,backup in backups:
                        if backup is not None: backup.replace(path)
                        else: path.unlink(missing_ok=True)
                finally:
                    for dest in moved: dest.unlink(missing_ok=True)
                raise

    def route(self, handler, method):
        """Browser ZIP transfer is streamed, separate from JSON upload limits."""
        try:
            if not handler.allowed_host() or not getattr(handler,'session_hash',None):
                raise APIError('browser_session_required','Open Studio in a local browser to transfer projects.',403)
            if method != 'GET' and (handler.headers.get('Origin') not in (f'http://127.0.0.1:{handler.server.server_port}',f'http://localhost:{handler.server.server_port}') or handler.headers.get('X-Tester') != 'local'):
                raise APIError('origin_required','Local browser origin required.',403)
            parts=urlsplit(handler.path).path.removeprefix('/api/project-archives').strip('/').split('/')
            if method == 'GET' and len(parts)==2 and parts[1]=='download':
                return handler.media(self.download(parts[0]),'application/zip','Imagine Studio project.zip')
            if method == 'POST' and parts == ['import']:
                length=int(handler.headers.get('Content-Length','0'))
                if not 0 < length <= MAX_ARCHIVE:
                    raise APIError('archive_limit','Project ZIP files must be between 1 byte and 20 GB.',413)
                fd,name=tempfile.mkstemp(prefix='upload-',suffix='.zip',dir=self.folder)
                try:
                    with os.fdopen(fd,'wb') as out:
                        remaining=length
                        while remaining:
                            chunk=handler.rfile.read(min(1024*1024,remaining))
                            if not chunk: raise APIError('invalid_archive','The project upload was interrupted.')
                            out.write(chunk);remaining-=len(chunk)
                    result=self.start('import',name)
                except Exception:
                    Path(name).unlink(missing_ok=True);raise
                return handler.send(202,result)
            raise APIError('not_found','Project archive route not found.',404)
        except APIError as exc:
            return handler.send(exc.status,{'error':{'code':exc.code,'message':str(exc)}})
        except (ValueError,OSError):
            return handler.send(400,{'error':{'code':'archive_failed','message':'Project transfer failed. Check disk space and try again.'}})
