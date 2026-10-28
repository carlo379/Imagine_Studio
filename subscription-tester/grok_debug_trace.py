"""Opt-in, credential-redacted diagnostics. No retries or request changes.

Enable with grok-trace.enabled in the private data directory; delete the flag to stop tracing without
restarting. HTTP byte contents and exception text are never recorded.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from user_data import data_home
FLAG = data_home() / 'grok-trace.enabled'
_LOCK = threading.Lock()
SAFE_HEADERS = {'host','accept','accept-encoding','connection','user-agent','content-type',
    'content-length','transfer-encoding','date','server','strict-transport-security',
    'vary','access-control-allow-origin','access-control-expose-headers','cf-cache-status',
    'cf-ray','content-encoding','x-request-id','request-id','traceparent','retry-after',
    'x-ratelimit-limit-requests','x-ratelimit-remaining-requests','x-metrics-e2e-ms',
    'x-zero-data-retention','x-data-retention'}

def utc(): return datetime.now(timezone.utc).isoformat()
def headers(value):
    return {k: v if k.lower() in SAFE_HEADERS else '[REDACTED]' for k,v in value.items()}

class Trace:
    def __init__(self, app, identity, authorization, loaded_at, load_seconds):
        token=authorization.removeprefix('Bearer ')
        claims={}
        try: claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='))
        except (ValueError,IndexError,TypeError): pass
        from workspace_accounts import CURRENT_PROFILE
        profile=CURRENT_PROFILE.get()
        if profile is None:
            from hermes_constants import get_hermes_home
            source=str(get_hermes_home()/'auth.json')
        else: source='encrypted private workspace profile'
        def timestamp(key):
            value=claims.get(key)
            return datetime.fromtimestamp(value,timezone.utc).isoformat() if type(value) in (int,float) else None
        self.path=app.storage/'.diagnostics'/'grok-http-trace.jsonl'
        self.start=time.monotonic();self.connection_created=None;self.first_read=None
        self.data={'job_id':identity,'pid':os.getpid(),'started_at':utc(),
            'credential':{'fingerprint_sha256_suffix':hashlib.sha256(token.encode()).hexdigest()[-6:],
                'issued_at':timestamp('iat'),'expires_at':timestamp('exp'),'worker_loaded_at':loaded_at,
                'load_seconds':load_seconds,'source':source},
            'attempt':1,'retries':0,'events':[],'connections_created':0,
            'client_policy':'fresh client for this request; no earlier pooled connection',
            'proxy_settings':{},'exception_type':None}
        import urllib.request
        for name,value in urllib.request.getproxies().items():
            if name=='no': self.data['proxy_settings'][name]='[bypass list configured]';continue
            p=urlsplit(value)
            self.data['proxy_settings'][name]={'scheme':p.scheme,'host':p.hostname,'port':p.port,
                'credentials':'[REDACTED]' if p.username or p.password else 'absent'}
    def event(self,name): self.data['events'].append({'event':name,'seconds':round(time.monotonic()-self.start,6)})
    def httpcore(self,name,info):
        self.event(name)  # Never serialize info: it can contain raw headers or TLS objects.
    def install(self,client):
        self.data['timeouts']=client.timeout.as_dict()
        self.data['trust_env']=client.trust_env
        self.data['transport_retries']=0
        pool=client._transport._pool
        self.data['initial_pool_connections']=len(pool.connections)
        pool._network_backend=Backend(pool._network_backend,self)
        client.event_hooks['request'].append(self.request)
        client.event_hooks['response'].append(self.response)
    def request(self,r):
        self.data.update(method=r.method,url=str(r.url),request_headers=headers(r.headers),
            body_bytes=len(r.content),body_sha256=hashlib.sha256(r.content).hexdigest())
        r.extensions['trace']=self.httpcore
    def response(self,r):
        self.data.update(http_status=r.status_code,response_headers=headers(r.headers),
            response_headers_seconds=round(time.monotonic()-self.start,6),
            provider_request_id=r.headers.get('x-request-id') or r.headers.get('request-id'))
    def finish(self,error=None):
        self.data.update(ended_at=utc(),total_seconds=round(time.monotonic()-self.start,6),
            time_to_first_byte_seconds=self.first_read,
            reused_connection=self.data['connections_created']==0,
            connection_age_at_first_byte_seconds=(round(self.first_read-(self.connection_created-self.start),6)
                if self.first_read is not None and self.connection_created is not None else None),
            exception_type=type(error).__name__ if error else None)
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with _LOCK:
            fd=os.open(self.path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
            with os.fdopen(fd,'a') as f:f.write(json.dumps(self.data)+'\n')

class Stream:
    def __init__(self,stream,trace):self.stream=stream;self.trace=trace
    def read(self,*args,**kwargs):
        result=self.stream.read(*args,**kwargs)
        if result and self.trace.first_read is None:
            self.trace.first_read=round(time.monotonic()-self.trace.start,6)
        return result
    def write(self,*args,**kwargs):return self.stream.write(*args,**kwargs)
    def close(self):return self.stream.close()
    def get_extra_info(self,*args,**kwargs):return self.stream.get_extra_info(*args,**kwargs)
    def start_tls(self,*args,**kwargs):return Stream(self.stream.start_tls(*args,**kwargs),self.trace)

class Backend:
    def __init__(self,backend,trace):self.backend=backend;self.trace=trace
    def connect_tcp(self,*args,**kwargs):
        stream=self.backend.connect_tcp(*args,**kwargs)
        self.trace.connection_created=time.monotonic();self.trace.data['connections_created']+=1
        return Stream(stream,self.trace)
    def connect_unix_socket(self,*args,**kwargs):
        stream=self.backend.connect_unix_socket(*args,**kwargs)
        self.trace.connection_created=time.monotonic();self.trace.data['connections_created']+=1
        return Stream(stream,self.trace)
    def sleep(self,*args,**kwargs):return self.backend.sleep(*args,**kwargs)

def begin(app,identity,authorization,loaded_at,load_seconds):
    if not FLAG.exists():return None
    return Trace(app,identity,authorization,loaded_at,load_seconds)

def post(client,endpoint,headers,body,trace):
    if trace is None:return client.post(endpoint,headers=headers,json=body)
    error=None
    try:
        trace.install(client)
        return client.post(endpoint,headers=headers,json=body)
    except Exception as exc:
        error=exc;raise
    finally:trace.finish(error)
