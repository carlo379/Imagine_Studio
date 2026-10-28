"""Private local thumbnails/posters. Never fetch remote media for a preview."""
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageOps
from agent_api import APIError

PLACEHOLDER=b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#18251e"/><path d="M145 68v44l38-22z" fill="#a9c7b2"/></svg>'

class MediaPreviews:
    def __init__(self,app):
        self.app=app;self.lock=threading.Lock();self.images=threading.BoundedSemaphore(2)
        self.pending=set();self.failed=set();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='media-posters')

    def source(self,kind,identity):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identity):raise APIError('invalid_media','Choose workspace media.')
        if kind=='image':
            try:return self.app.asset(identity)[1],True
            except ValueError:raise APIError('not_found','Image not found.',404) from None
        if kind=='upload':
            with self.app.agent.lock:m,path=self.app.editing.media_file(identity)
            if not m.get('video') and not m.get('image'):raise APIError('invalid_media','This source has no picture.')
            return path,bool(m.get('image'))
        if kind!='take':raise APIError('invalid_media','Choose an image, take or upload.')
        with self.app.agent.lock:
            job=self.app.editing.take_record(identity)
            if not job or job['status']!='done' or not job.get('video'):raise APIError('not_found','Take not found.',404)
            if job.get('imported_media_id'):return self.app.editing.media_file(job['imported_media_id'])[1],False
            path=Path(__file__).parent/'static'/'mock-video.mp4' if job.get('mock') else self.app.storage/'videos'/(identity+'.mp4')
        return (path if path.is_file() else None),False

    def get(self,kind,identity,width):
        if width not in (160,320,640,1280):raise APIError('invalid_size','Choose a 160, 320, 640 or 1280 pixel preview.')
        path,image=self.source(kind,identity)
        if path is None:return PLACEHOLDER,'image/svg+xml','uncached'
        stat=path.stat();key=hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}:{width}:v1'.encode()).hexdigest()
        cache=self.app.storage/'cache'/'previews'/(key+'.jpg')
        if cache.is_file():return cache.read_bytes(),'image/jpeg','ready'
        cache.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if image:
            with self.images:
                if not cache.is_file():
                    with Image.open(path) as original:
                        frame=ImageOps.exif_transpose(original);frame.thumbnail((width,width))
                        if frame.mode in ('RGBA','LA') or 'transparency' in frame.info:
                            rgba=frame.convert('RGBA');base=Image.new('RGB',rgba.size,'#15221b');base.paste(rgba,mask=rgba.getchannel('A'));frame=base
                        output=io.BytesIO();frame.convert('RGB').save(output,'JPEG',quality=78,optimize=True)
                    self.write(cache,output.getvalue())
            return cache.read_bytes(),'image/jpeg','ready'
        with self.lock:
            if key in self.failed:return PLACEHOLDER,'image/svg+xml','unavailable'
            if key not in self.pending and len(self.pending)<32:
                self.pending.add(key)
                def make():
                    try:
                        ffmpeg=self.app.editing.ffmpeg
                        if not ffmpeg:raise ValueError('FFmpeg unavailable')
                        result=subprocess.run([ffmpeg,'-v','error','-nostdin','-i',str(path),'-frames:v','1','-vf',f'scale={width}:-2','-f','image2pipe','-vcodec','mjpeg','-'],capture_output=True,timeout=15,check=True)
                        self.write(cache,result.stdout)
                    except (OSError,ValueError,subprocess.SubprocessError):
                        with self.lock:self.failed.add(key)
                    finally:
                        with self.lock:self.pending.discard(key)
                self.pool.submit(make)
        return PLACEHOLDER,'image/svg+xml','pending'

    @staticmethod
    def write(path,raw):
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temp.open('wb') as output:os.chmod(temp,0o600);output.write(raw)
            temp.replace(path)
        finally:temp.unlink(missing_ok=True)
