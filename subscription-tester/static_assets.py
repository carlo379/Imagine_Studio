"""Versioned, compressed application files; workspace/API data stays uncached."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit,parse_qs


class StaticAssets:
    def __init__(self,root):self.root=Path(root);self.lock=threading.Lock();self.cache={}

    def content(self,path):
        stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
        with self.lock:
            if key not in self.cache:
                raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()[:20]
                if len(self.cache)>128:self.cache.clear()
                self.cache[key]=(raw,gzip.compress(raw,compresslevel=6) if len(raw)>1024 else None,digest)
            return self.cache[key]

    def index(self):
        html=(self.root/'index.html').read_text()
        manifest=self.root/'static'/'build'/'manifest.json'
        if manifest.is_file():
            try:html=html.replace('/static/production.js',json.loads(manifest.read_text())['entry'])
            except (OSError,ValueError,KeyError):pass
        def version(match):
            url=match[1]
            if url=='/static/workspace.js' or '/build/' in url:return match[0]
            path=self.root/url.lstrip('/')
            if path.is_file():return '"'+url+'?v='+self.content(path)[2]+'"'
            return match[0]
        return re.sub(r'"(/static/[^"?]+\.(?:js|css))"',version,html).encode()

    def serve(self,handler):
        parsed=urlsplit(handler.path);path=parsed.path
        if path=='/':return self.respond(handler,self.index(),'text/html; charset=utf-8','private, no-cache')
        if not path.startswith('/static/') or path=='/static/workspace.js':return False
        if not path.endswith(('.js','.css')):return False
        file=(self.root/path.lstrip('/')).resolve();base=(self.root/'static').resolve()
        if not file.is_relative_to(base) or not file.is_file():return False
        raw,compressed,digest=self.content(file)
        query=parse_qs(parsed.query)
        versioned=query.get('v')==[digest] or bool(re.search(r'/build/(?:chunks/)?[^/]+-[A-Z0-9]{8}\.js$',path))
        mime='text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8'
        return self.respond(handler,raw,mime,'public, max-age=31536000, immutable' if versioned else 'no-cache',compressed,digest)

    def respond(self,handler,raw,mime,cache,compressed=None,digest=None):
        if digest is None:
            digest=hashlib.sha256(raw).hexdigest()[:20]
            compressed=gzip.compress(raw,compresslevel=6) if len(raw)>1024 else None
        accepts=handler.headers.get('Accept-Encoding','')
        use_gzip=bool(compressed and any(part.strip().split(';')[0]=='gzip' and not re.search(r'q=0(?:\.0*)?(?:\s|$)',part) for part in accepts.split(',')))
        etag='"'+digest+('-gzip' if use_gzip else '')+'"'
        status=304 if handler.headers.get('If-None-Match')==etag else 200
        payload=compressed if use_gzip else raw
        handler.send_response(status);handler.send_header('Content-Type',mime);handler.send_header('Cache-Control',cache)
        handler.send_header('ETag',etag);handler.send_header('Vary','Accept-Encoding');handler.send_header('X-Content-Type-Options','nosniff')
        if use_gzip:handler.send_header('Content-Encoding','gzip')
        handler.send_header('Content-Length',str(len(payload) if status==200 else 0));handler.end_headers()
        if status==200:handler.wfile.write(payload)
        return True
