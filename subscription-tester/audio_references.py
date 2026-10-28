"""Private recording preparation for Grok audio-reference requests."""
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import uuid
from agent_api import APIError

def capabilities():
    return dict(local_preparation=True, generation_enabled=True, provider='xai-subscription-oauth',
        access='unverified', contract='reference_audios.url', reason='Temporary HTTPS recording delivery requires the cf CLI; xAI account entitlement and exact singing synchronization remain unverified. Provider access errors are reported without retry or preset fallback.',
        local_formats=['wav', 'mp3'], local_max_bytes=64*1024*1024,
        local_max_source_seconds=3600, local_max_excerpt_seconds=15, max_attachments=1,
        provider_formats=None, provider_limits=None, provider_upload_ids=[],
        exact_singing_sync='unverified',
        documentation='https://docs.x.ai/developers/model-capabilities/video/reference-to-video')


class AudioReferences:
    def __init__(self, app):
        self.app=app;self.p=app.productions;self.editor=app.editing

    def get(self, identity, kind='audio-reference'):
        if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):
            raise APIError('missing_audio_reference','Choose a recording in this workspace.',404)
        return self.p.get(identity,kind)

    def file(self, identity, kind='audio-reference'):
        record=self.get(identity,kind)
        _,path=self.editor.media_file(record['media_id'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
            raise APIError('audio_changed','Recording bytes changed. Upload it again.',409)
        return record,path

    def upload(self,data,key):
        if set(data)!={'name','base64'} or not isinstance(data.get('name'),str):
            raise APIError('invalid_audio_reference','Use name and base64 for a WAV or MP3 recording.')
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):
            raise APIError('idempotency_required','Supply an 8–100 character Idempotency-Key.')
        ext=Path(data['name']).suffix.lower().lstrip('.')
        if ext not in ('wav','mp3'):raise APIError('invalid_audio_reference','Upload a WAV or MP3 recording.')
        encoded=data['base64']
        if not isinstance(encoded,str) or len(encoded)>64*1024*1024*4//3+4:raise APIError('media_limit','Recording uploads must be at most 64 MB.')
        try:raw=base64.b64decode(encoded,validate=True)
        except ValueError:raise APIError('invalid_media','Upload valid base64 audio.') from None
        if not 0<len(raw)<=64*1024*1024:raise APIError('media_limit','Recording uploads must be at most 64 MB.')
        fingerprint=hashlib.sha256(json.dumps({'name':data['name'],'sha256':hashlib.sha256(raw).hexdigest()},sort_keys=True).encode()).hexdigest()
        for r in self.p.all('audio-reference'):
            if r['upload_key']==key:
                if r['fingerprint']!=fingerprint:raise APIError('idempotency_conflict','This upload key belongs to a different recording.',409)
                self.file(r['id']);return r
        # Probe content before adding it to the shared media store. No URLs or external paths.
        import tempfile
        with tempfile.TemporaryDirectory(dir=self.app.storage) as folder:
            path=Path(folder)/('input.'+ext);path.write_bytes(raw);path.chmod(0o600)
            self.probe_format(path,ext)
            info=self.editor.probe(path)
            if not info['audio'] or info['video']:raise APIError('invalid_audio_reference','Use an audio-only recording.')
        media=self.editor.upload(data)
        record=dict(id=uuid.uuid4().hex,revision=1,media_id=media['id'],name=media['name'],
            duration=media['duration'],bytes=media['bytes'],format=ext,sha256=hashlib.sha256(raw).hexdigest(),
            upload_key=key,fingerprint=fingerprint,provider_upload_id=None)
        with self.p.sql:self.p.put('audio-reference',record)
        return record

    def probe_format(self,path,ext):
        if not self.editor.ffprobe:raise APIError('editor_unavailable','Install FFmpeg to inspect recordings.',503)
        try:
            result=subprocess.run([self.editor.ffprobe,'-v','error','-protocol_whitelist','file,pipe','-f',ext,'-show_entries','format=format_name',
                '-of','json',str(path)],capture_output=True,timeout=20,check=True)
            formats=json.loads(result.stdout)['format']['format_name'].split(',')
            if ext not in formats:raise ValueError()
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            raise APIError('invalid_audio_reference','Recording content does not match its WAV or MP3 extension.') from None

    def excerpt(self,identity,data):
        if set(data)!={'start_s','end_s'}:raise APIError('invalid_excerpt','Use start_s and end_s in seconds.')
        source,path=self.file(identity);start,end=data['start_s'],data['end_s']
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or not 0<=start<end<=source['duration'] or end-start>15:
            raise APIError('invalid_excerpt','Choose an excerpt inside the recording, longer than zero and at most 15 seconds. Shot duration is not changed.')
        start,end=float(start),float(end)
        identity_hash=hashlib.sha256(json.dumps([source['id'],source['sha256'],start,end],separators=(',',':')).encode()).hexdigest()[:32]
        for r in self.p.all('audio-excerpt'):
            if r['id']==identity_hash:self.file(r['id'],'audio-excerpt');return r
        if start==0 and end==source['duration']:
            media_id=source['media_id'];sha=source['sha256'];duration=source['duration']
        else:
            if not self.editor.ffmpeg:raise APIError('editor_unavailable','Install FFmpeg to prepare excerpts.',503)
            import tempfile
            with tempfile.TemporaryDirectory(dir=self.app.storage) as folder:
                output=Path(folder)/'excerpt.wav'
                try:
                    subprocess.run([self.editor.ffmpeg,'-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(path),'-vn',
                        '-af',f'atrim=start={start}:end={end},asetpts=PTS-STARTPTS',
                        '-c:a','pcm_s24le',str(output)],capture_output=True,timeout=40,check=True)
                except (OSError,subprocess.SubprocessError):raise APIError('excerpt_failed','Could not prepare the excerpt; source is retained.') from None
                raw=output.read_bytes();sha=hashlib.sha256(raw).hexdigest()
                media=self.editor.upload(dict(name='Recording excerpt.wav',base64=base64.b64encode(raw).decode()))
                media_id=media['id'];duration=media['duration']
        record=dict(id=identity_hash,revision=1,reference_id=source['id'],source_sha256=source['sha256'],
            start_s=start,end_s=end,duration=duration,media_id=media_id,sha256=sha,provider_upload_id=None)
        with self.p.sql:self.p.put('audio-excerpt',record)
        return record

    def attachment(self,value):
        if value is None:return None
        if not isinstance(value,dict) or set(value)-{'reference_id','excerpt_id','character_id'} or not {'reference_id','excerpt_id'}<=set(value):
            raise APIError('invalid_audio_reference','Use reference_id, excerpt_id and optional character_id.')
        source,_=self.file(value['reference_id']);excerpt,_=self.file(value['excerpt_id'],'audio-excerpt')
        if excerpt['reference_id']!=source['id'] or excerpt['source_sha256']!=source['sha256']:
            raise APIError('invalid_audio_reference','Excerpt belongs to a different recording.')
        character=value.get('character_id')
        if character is not None:
            if not isinstance(character,str) or not any(r['id']==character and r['category']=='Character' and not r.get('archived') for r in self.app.named_library()):
                raise APIError('invalid_audio_reference','Choose a character reference in this workspace.')
        return dict(reference_id=source['id'],excerpt_id=excerpt['id'],**({'character_id':character} if character else {}))

    def inspection(self,value,shot_duration):
        value=self.attachment(value)
        if value is None:return None
        source=self.get(value['reference_id']);excerpt=self.get(value['excerpt_id'],'audio-excerpt')
        return dict(attachment=value,source=source,excerpt=excerpt,shot_duration=shot_duration,
            duration_mismatch=abs(excerpt['duration']-shot_duration)>.001,capability=capabilities())
