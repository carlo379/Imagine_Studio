"""Loopback-local identities, private workspaces and encrypted provider credentials.

Independent OAuth implementation of the documented OpenAI local registration flow.
No provider token is accepted as a Studio session or sent to the renderer.
"""
import base64
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import queue
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode
import uuid
from cryptography.fernet import Fernet
from agent_api import APIError

CURRENT_PROFILE=ContextVar('studio_provider_profile',default=None)
ISSUER='https://auth.openai.com'
COOKIE='imagine_session'

def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def private_write(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    fd=temp.open('xb');temp.chmod(0o600)
    with fd:fd.write(raw)
    temp.replace(path)

class CredentialProfile:
    def __init__(self,root,cipher):
        self.root=root;self.cipher=cipher;self.lock=threading.RLock();self.locks={}
    def credential_lock(self,name):
        with self.lock:return self.locks.setdefault(name,threading.RLock())
    def get(self,name):
        with self.credential_lock(name):
            path=self.root/(name+'.enc')
            return json.loads(self.cipher.decrypt(path.read_bytes())) if path.exists() else None
    def set(self,name,value):
        with self.credential_lock(name):
            path=self.root/(name+'.enc')
            if value is None:path.unlink(missing_ok=True)
            else:private_write(path,self.cipher.encrypt(json.dumps(value).encode()))
    @contextmanager
    def codex_home(self):
        # Native Codex owns its auth format. A temporary, private profile avoids
        # inheriting this computer's global account or leaving plaintext tokens.
        with self.credential_lock('codex'),tempfile.TemporaryDirectory(prefix='imagine-codex-') as raw:
            path=Path(raw);path.chmod(0o700);auth=self.get('codex')
            if auth:private_write(path/'auth.json',json.dumps(auth).encode())
            try:yield path
            finally:
                file=path/'auth.json'
                if file.exists():self.set('codex',json.loads(file.read_text()))
    @contextmanager
    def timed_credential_lock(self,name,timeout):
        lock=self.credential_lock(name)
        if not lock.acquire(timeout=timeout):raise ValueError('Grok connection is busy. Finish sign-in or try checking again.')
        try:yield
        finally:lock.release()

    def grok(self,action,update=None,timeout=None):
        # Reading stdout directly can wait forever before p.wait's timeout runs.
        timeout = timeout if timeout is not None else (600 if action == 'login' else 30)
        deadline=time.monotonic()+timeout
        with self.timed_credential_lock('hermes',timeout):
            p=subprocess.Popen([sys.executable,str(Path(__file__).parent/'scoped_hermes.py'),action],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            events=queue.Queue()
            def read():
                try:
                    for line in p.stdout:events.put(line)
                finally:events.put(None)
            reader=threading.Thread(target=read,daemon=True);reader.start()
            try:
                p.stdin.write(json.dumps({'auth':self.get('hermes')})+'\n');p.stdin.close();result=None
                while True:
                    if time.monotonic()>=deadline:raise ValueError('Grok connection check timed out. Reconnect or try checking again.')
                    try:line=events.get(timeout=max(.001,deadline-time.monotonic()))
                    except queue.Empty:raise ValueError('Grok connection check timed out. Reconnect or try checking again.') from None
                    if line is None:break
                    data=json.loads(line)
                    if data.get('event')=='waiting' and update:update(**data['values'])
                    elif data.get('event')=='done':result=data
                if p.wait(timeout=max(.001,deadline-time.monotonic()))!=0 or not result:raise ValueError('Grok sign-in or refresh failed. Reconnect this workspace.')
                self.set('hermes',result['auth'])
                return result.get('headers')
            finally:
                if p.poll() is None:p.kill()
                p.wait();reader.join(timeout=2);p.stdout.close()

class WorkspaceAccounts:
    def __init__(self,legacy,isolated=False,mock_identity=False):
        self.legacy=legacy;self.isolated=isolated;self.mock_identity=bool(mock_identity and legacy.mock);self.root=legacy.storage/'identity';self.root.mkdir(parents=True,exist_ok=True,mode=0o700);self.root.chmod(0o700)
        key=self.root/'vault-key'
        if not key.exists():private_write(key,Fernet.generate_key())
        key.chmod(0o600);self.cipher=Fernet(key.read_bytes());self.lock=threading.RLock();self.apps={'local-owner':legacy};self.jobs={};self.profiles={}
        self.sql=sqlite3.connect(self.root/'accounts.sqlite3',check_same_thread=False);(self.root/'accounts.sqlite3').chmod(0o600)
        self.sql.executescript('''CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, identity TEXT UNIQUE, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, workspace TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS guest_returns(hash TEXT NOT NULL,workspace TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(hash,workspace));
        CREATE TABLE IF NOT EXISTS agents(hash TEXT PRIMARY KEY, workspace TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS codex_reconnect(workspace TEXT PRIMARY KEY,id TEXT NOT NULL,status TEXT NOT NULL,step TEXT NOT NULL,requested_at REAL NOT NULL,updated_at REAL NOT NULL,job_id TEXT);
        CREATE TABLE IF NOT EXISTS oauth(state TEXT PRIMARY KEY, session TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, verifier TEXT NOT NULL, nonce TEXT NOT NULL, redirect TEXT NOT NULL, client TEXT NOT NULL, expires REAL NOT NULL);''')
        with self.sql:
            self.sql.execute('INSERT OR IGNORE INTO workspaces VALUES (?,?,?,?,?)',('local-owner','personal','This Mac',None,time.time()));self.register_agent('local-owner',legacy)
        host=self.root/'host-id'
        if not host.exists():private_write(host,('urn:uuid:'+str(uuid.uuid4())).encode())
        self.host=host.read_text()
    def profile(self,identity):
        with self.lock:
            if identity not in self.profiles:self.profiles[identity]=CredentialProfile(self.root/'credentials'/identity,self.cipher)
            return self.profiles[identity]
    def app(self,identity):
        with self.lock:
            if identity not in self.apps:
                if not self.sql.execute('SELECT id FROM workspaces WHERE id=?',(identity,)).fetchone():raise APIError('workspace_not_found','Workspace not found.',404)
                from studio_server import Studio
                self.apps[identity]=Studio(mock=self.legacy.mock,storage=self.legacy.storage/'workspaces'/identity,profile=self.profile(identity))
                with self.sql:self.register_agent(identity,self.apps[identity])
            return self.apps[identity]
    def register_agent(self,identity,app):
        self.sql.execute('INSERT OR REPLACE INTO agents VALUES (?,?)',(digest(app.agent.token),identity))
        app.handoff.controls.identity_status=lambda job_id:self.jobs.get(job_id,{}).get('status','error') if self.jobs.get(job_id,{}).get('source')==identity else 'error'
    def new_guest(self):
        with self.lock,self.sql:
            identity=uuid.uuid4().hex;self.sql.execute('INSERT INTO workspaces VALUES (?,?,?,?,?)',(identity,'guest','Private guest workspace',None,time.time()))
        self.app(identity);return identity
    def session(self,identity,handler=None,old=None):
        raw=secrets.token_urlsafe(32)
        with self.lock,self.sql:
            if old:
                previous=self.sql.execute('SELECT s.workspace,w.kind FROM sessions s JOIN workspaces w ON w.id=s.workspace WHERE s.hash=?',(old,)).fetchone()
                returns=self.sql.execute('SELECT workspace,created FROM guest_returns WHERE hash=?',(old,)).fetchall()
                if previous and previous[1]=='guest' and previous[0]!=identity:returns.append((previous[0],time.time()))
                self.sql.execute('DELETE FROM sessions WHERE hash=?',(old,));self.sql.execute('DELETE FROM guest_returns WHERE hash=?',(old,))
                for workspace,created in returns:
                    if workspace!=identity:self.sql.execute('INSERT OR REPLACE INTO guest_returns VALUES (?,?,?)',(digest(raw),workspace,created))
            self.sql.execute('DELETE FROM guest_returns WHERE hash NOT IN (SELECT hash FROM sessions) AND hash!=?',(digest(raw),))
            self.sql.execute('DELETE FROM sessions WHERE expires<?',(time.time(),));self.sql.execute('INSERT INTO sessions VALUES (?,?,?)',(digest(raw),identity,time.time()+30*86400))
        if handler:
            handler.session_hash=digest(raw);handler.workspace_id=identity
            handler.session_cookie=f'{COOKIE}={raw}; HttpOnly; SameSite=Lax; Path=/; Max-Age={30*86400}'
        return raw
    def resolve(self,handler):
        if not handler.allowed_host():raise APIError('local_only','Local access only.',403)
        header=handler.headers.get('Authorization')
        with self.lock:
            if header:
                if not header.startswith('Bearer '):raise APIError('unauthorized','Use a workspace agent token.',401)
                row=self.sql.execute('SELECT workspace FROM agents WHERE hash=?',(digest(header[7:]),)).fetchone()
                if not row:raise APIError('unauthorized','Invalid workspace agent token.',401)
                handler.session_hash=None;identity=row[0]
            else:
                try:cookie=SimpleCookie(handler.headers.get('Cookie',''));raw=cookie[COOKIE].value if COOKIE in cookie else ''
                except Exception:raw=''
                row=self.sql.execute('SELECT workspace FROM sessions WHERE hash=? AND expires>?',(digest(raw),time.time())).fetchone() if raw else None
                if row:identity=row[0];handler.session_hash=digest(raw)
                else:
                    # APIs/media never silently attach an expired browser to another owner.
                    if handler.path not in ('/','/tester'):raise APIError('session_expired','Reopen the Studio home page to start a session.',401)
                    identity=self.new_guest() if self.isolated else 'local-owner';self.session(identity,handler)
        handler.workspace_id=identity;return self.app(identity)
    def status(self,identity,session_hash=None):
        with self.lock:
            expired=self.sql.execute('SELECT source FROM oauth WHERE expires<?',(time.time(),)).fetchall()
            with self.sql:self.sql.execute('DELETE FROM oauth WHERE expires<?',(time.time(),))
            for (source,) in expired:
                for j in self.jobs.values():
                    if j['source']==source and j['status']=='waiting' and j.get('kind')=='identity':j.update(status='error',url=None,error='Sign-in expired. Start again; your work is intact.')
            row=self.sql.execute('SELECT kind,name,identity FROM workspaces WHERE id=?',(identity,)).fetchone()
            accounts=self.sql.execute("SELECT id,name FROM workspaces WHERE kind=? ORDER BY created",('mock-account' if self.mock_identity else 'account',)).fetchall() if session_hash and identity=='local-owner' and not self.isolated else []
            can_return=bool(session_hash and self.sql.execute('SELECT 1 FROM guest_returns WHERE hash=?',(session_hash,)).fetchone())
            job=next((j for j in reversed(list(self.jobs.values())) if j['source']==identity),None)
        return dict(workspace_id=identity,kind=row[0],name=row[1],verified=row[2] is not None and row[0]=='account',mock_identity=self.mock_identity,isolated=self.isolated,can_restore_guest=can_return,
                    accounts=[dict(id=r[0],name=r[1]) for r in accounts],auth={k:v for k,v in (job or {}).items() if k in (('status','url','code','error','id','target','kind') if session_hash else ('status','id','kind'))},
                    codex_reconnect=self.codex_reconnect_status(identity),
                    identity_provider='ChatGPT',grok_identity_available=False,
                    grok_identity_message='Grok connects generation access; it does not verify a Studio workspace identity.',
                    grok_connection=dict(signed_in=self.app(identity).snapshot().get('signed_in',False),
                        status=self.app(identity).snapshot().get('auth_status','disconnected'),verified=False,
                        message='Saved connection status; use the Grok model-access check to verify access. No generation is sent.'),local_only=True)

    def codex_reconnect_status(self,identity):
        """A request's outcome, not a credential/model-access probe. Never return device secrets."""
        with self.lock,self.sql:
            row=self.sql.execute('SELECT id,status,step,requested_at,updated_at,job_id FROM codex_reconnect WHERE workspace=?',(identity,)).fetchone()
            if not row:return dict(id=None,status='idle',step='none',human_action_required=False,error=None,requested_at=None,updated_at=None)
            request_id,status,step,created,updated,job_id=row
            if status=='pending' and job_id:
                job=self.jobs.get(job_id)
                outcome=job.get('status') if job and job.get('source')==identity and job.get('kind')=='codex' else 'error'
                if outcome in ('connected','error','cancelled'):
                    status='connected' if outcome=='connected' else 'error';step='complete' if status=='connected' else 'error';updated=time.time()
                    self.sql.execute('UPDATE codex_reconnect SET status=?,step=?,updated_at=? WHERE workspace=?',(status,step,updated,identity))
            return dict(id=request_id,status=status,step=step,human_action_required=status=='pending',
                        error='ChatGPT sign-in did not finish. Ask the human to start again in Studio.' if status=='error' else None,
                        requested_at=created,updated_at=updated)

    def request_codex_reconnect(self,identity,data):
        if not isinstance(data,dict) or data:raise APIError('invalid_request','Reconnect requests accept an empty object; the workspace comes from authentication.')
        with self.lock,self.sql:
            current=self.codex_reconnect_status(identity)
            if current['status']!='pending':
                now=time.time()
                self.sql.execute('INSERT OR REPLACE INTO codex_reconnect VALUES (?,?,?,?,?,?,?)',(identity,uuid.uuid4().hex,'pending','human_start',now,now,None))
            return self.codex_reconnect_status(identity)

    def start_codex_reconnect(self,handler,data):
        """Only a real browser session may start the existing human verification flow."""
        if not handler.session_hash:raise APIError('browser_session_required','Start ChatGPT verification from a browser session.',403)
        if not isinstance(data,dict) or set(data)-{'request_id'}:raise APIError('invalid_request','Only the pending reconnect request ID is accepted.')
        identity=handler.workspace_id
        with self.lock:
            current=self.codex_reconnect_status(identity)
            if 'request_id' in data and (not isinstance(data['request_id'],str) or data['request_id']!=current['id']):
                raise APIError('reconnect_conflict','This reconnect request is no longer current. Refresh the Studio prompt.',409)
            if current['status']=='pending' and current['step']=='device_verification':raise APIError('sign_in_busy','Finish the current sign-in first.',409)
            result=self.codex_login(handler)
            if current['id']:
                with self.sql:self.sql.execute("UPDATE codex_reconnect SET status='pending',step='device_verification',job_id=?,updated_at=? WHERE workspace=?",(result['id'],time.time(),identity))
                self.codex_reconnect_status(identity)
            return result
    def start(self,handler,data):
        source=handler.workspace_id;target=data.get('account_id') or source
        with self.lock:
            row=self.sql.execute('SELECT kind FROM workspaces WHERE id=?',(target,)).fetchone()
            if not row or target!=source and row[0]!=('mock-account' if self.mock_identity else 'account'):raise APIError('invalid_account','Choose a saved account or connect this workspace.')
            if any(j['source']==source and j['status']=='waiting' for j in self.jobs.values()):raise APIError('sign_in_busy','Finish the current sign-in first.',409)
            connection=self.profile(target).get('openai') or {};client=connection.get('client_id','dynamic_agent_client')
            state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64);nonce=secrets.token_urlsafe(32)
            redirect=f'http://127.0.0.1:{handler.server.server_port}/auth/callback'
            params=dict(client_id=client,response_type='code',redirect_uri=redirect,scope='openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',resource='https://api.openai.com/v1',ext_agent_host_id=self.host,state=state,nonce=nonce,code_challenge_method='S256',code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
            if client=='dynamic_agent_client':params['agent_name_hint']='Imagine Studio'
            # OAuth transaction secrets are short lived; disk stores them encrypted.
            with self.sql:self.sql.execute('INSERT INTO oauth VALUES (?,?,?,?,?,?,?,?,?)',(digest(state),handler.session_hash,source,target,self.cipher.encrypt(verifier.encode()).decode(),nonce,redirect,client,time.time()+600))
            url=(f'http://127.0.0.1:{handler.server.server_port}/auth/mock?'+urlencode({'state':state})) if self.mock_identity else ISSUER+'/api/accounts/authorize?'+urlencode(params)
            j=dict(id=uuid.uuid4().hex,source=source,target=target,status='waiting',kind='identity',url=url);self.jobs[j['id']]=j
            return {k:v for k,v in j.items() if k not in ('source','target')}
    def mock_callback(self,handler,query):
        if not self.mock_identity:raise APIError('not_found','Mock identity is unavailable.',404)
        with self.lock,self.sql:
            row=self.sql.execute('SELECT session,source,target,expires FROM oauth WHERE state=?',(digest(query.get('state',[''])[0]),)).fetchone()
            if not row or row[0]!=handler.session_hash or row[3]<time.time():raise APIError('oauth_expired','Mock sign-in expired or belongs to another browser.',401)
            self.sql.execute('DELETE FROM oauth WHERE state=?',(digest(query['state'][0]),))
            self.sql.execute("UPDATE workspaces SET kind='mock-account',name='Mock ChatGPT account',identity=? WHERE id=?",('mock:'+row[2],row[2]))
            self.session(row[2],handler,row[0])
            for j in self.jobs.values():
                if j['source']==row[1] and j['status']=='waiting' and j.get('kind')=='identity':j.update(status='connected',url=None)
    def validate_identity(self,token,client,nonce):
        import jwt
        try:
            key=jwt.PyJWKClient(ISSUER+'/.well-known/jwks.json',timeout=15).get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256'],audience=client,issuer=ISSUER,options={'require':['iss','sub','aud','exp','iat','nonce']},leeway=30)
            if not isinstance(claims['sub'],str) or not claims['sub'] or not hmac.compare_digest(claims['nonce'],nonce):raise ValueError()
            if isinstance(claims['aud'],list) and len(claims['aud'])>1 and claims.get('azp')!=client:raise ValueError()
            if claims.get('azp',client)!=client:raise ValueError()
            return claims
        except Exception:raise APIError('identity_invalid','OpenAI identity verification failed. No account or credentials were changed.',401) from None
    def callback(self,handler,query):
        state=query.get('state',[''])[0]
        with self.lock,self.sql:
            row=self.sql.execute('SELECT session,source,target,verifier,nonce,redirect,client,expires FROM oauth WHERE state=?',(digest(state),)).fetchone()
            if not row or row[0]!=handler.session_hash or row[-1]<time.time():raise APIError('oauth_expired','This sign-in expired or belongs to another browser. Start again.',401)
            self.sql.execute('DELETE FROM oauth WHERE state=?',(digest(state),))
        session,source,target,verifier,nonce,redirect,previous,_=row
        try:
            if query.get('error'):raise APIError('sign_in_denied','Sign-in was cancelled or denied. Your workspace is unchanged.')
            client=query.get('client_id',[previous])[0];code=query.get('code',[''])[0]
            if not code or not re.fullmatch('[A-Za-z0-9_-]{1,200}',client) or client=='dynamic_agent_client' or previous!='dynamic_agent_client' and client!=previous:raise APIError('registration_invalid','OpenAI did not return the expected registered client.')
            import httpx
            response=httpx.post(ISSUER+'/api/accounts/oauth/token',data={'grant_type':'authorization_code','client_id':client,'code':code,'code_verifier':self.cipher.decrypt(verifier.encode()).decode(),'redirect_uri':redirect,'resource':'https://api.openai.com/v1'},timeout=30,follow_redirects=False)
            if response.status_code!=200:raise APIError('code_exchange_failed','OpenAI sign-in could not finish. Start a fresh sign-in; no generation was made.')
            tokens=response.json();claims=self.validate_identity(tokens.get('id_token',''),client,nonce)
            identity=json.dumps([ISSUER,client,claims['sub']],separators=(',',':'))
            with self.lock:
                old=self.sql.execute('SELECT identity FROM workspaces WHERE id=?',(target,)).fetchone()[0]
                if old and old!=identity:raise APIError('account_mismatch','This is a different account. Use Add account to keep workspaces separate.',403)
                match=self.sql.execute('SELECT id FROM workspaces WHERE identity=?',(identity,)).fetchone()
                destination=match[0] if match else target
                name=str(claims.get('name') or claims.get('email') or 'ChatGPT account')[:120]
                credentials=dict(client_id=client,issuer=ISSUER,subject=claims['sub'],email=claims.get('email'),name=name,id_token=tokens['id_token'],access_token=tokens.get('access_token'),refresh_token=tokens.get('refresh_token'),expires_at=time.time()+int(tokens.get('expires_in',3600)),scopes=str(tokens.get('scope','')).split())
                self.profile(destination).set('openai',credentials)
                with self.sql:self.sql.execute("UPDATE workspaces SET kind='account',name=?,identity=? WHERE id=?",(name,identity,destination))
                self.session(destination,handler,session)
                for j in self.jobs.values():
                    if j['source']==source and j['status']=='waiting':j.update(status='connected',url=None,target=destination)
            return destination
        except Exception:
            with self.lock:
                for j in self.jobs.values():
                    if j['source']==source and j['status']=='waiting':j.update(status='error',url=None,error='Sign-in did not finish. Your saved work is intact. Try again.')
            raise
    def codex_login(self,handler):
        identity=handler.workspace_id
        if self.legacy.mock:
            job=dict(id=uuid.uuid4().hex,source=identity,target=identity,status='connected',kind='codex');self.jobs[job['id']]=job
            return {'id':job['id'],'status':'connected','mock':True}
        if any(j['source']==identity and j['status'] in ('waiting','connecting') for j in self.jobs.values()):raise APIError('sign_in_busy','Finish the current sign-in first.',409)
        job=dict(id=uuid.uuid4().hex,source=identity,target=identity,status='connecting',kind='codex');self.jobs[job['id']]=job
        def work():
            from openai_images import codex_path
            p=None
            try:
                import os
                home_context=nullcontext(Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))) if identity=='local-owner' else self.profile(identity).codex_home()
                with home_context as home:
                    import os
                    env={k:v for k,v in os.environ.items() if not k.startswith('OPENAI_') and k not in ('CODEX_API_KEY','CODEX_AUTH_JSON','CHATGPT_ACCESS_TOKEN')};env['CODEX_HOME']=str(home)
                    p=subprocess.Popen([codex_path(),'login','--device-auth'],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                    timer=threading.Timer(600,lambda:p.terminate() if p.poll() is None else None);timer.daemon=True;timer.start()
                    for line in p.stdout:
                        line=re.sub(r'\x1b\[[0-9;]*m','',line)
                        url=re.search(r'https://auth\.openai\.com/[A-Za-z0-9/_-]+',line)
                        code=re.search(r'\b[A-Z0-9]{4}-[A-Z0-9]{5}\b',line)
                        if url:job.update(url=url[0],status='waiting')
                        if code:job['code']=code[0]
                    if p.wait()!=0 or not (home/'auth.json').exists():raise ValueError()
                    timer.cancel()
                job.update(status='connected',url=None,code=None)
            except Exception:job.update(status='error',error='Codex connection failed. Start again.',url=None,code=None)
            finally:
                if p and p.poll() is None:p.kill()
        self.app(identity).spawn(work);return {k:v for k,v in job.items() if k not in ('source','target')}
    def dispatch(self,handler,method,parts,data):
        identity=handler.workspace_id
        if method=='GET' and not parts:return 200,self.status(identity,handler.session_hash)
        if method=='GET' and parts==['codex']:return 200,self.codex_reconnect_status(identity)
        if method=='POST' and parts==['restore-guest']:
            with self.lock:
                row=self.sql.execute('SELECT workspace FROM guest_returns WHERE hash=? ORDER BY created DESC LIMIT 1',(handler.session_hash,)).fetchone()
                if not row:raise APIError('no_guest_work','There is no previous guest workspace in this browser.',404)
                self.session(row[0],handler,handler.session_hash)
            return 200,{'reload':True}
        if method=='POST' and parts==['signin']:return 202,self.start(handler,data)
        if method=='POST' and parts==['cancel']:
            with self.lock,self.sql:
                self.sql.execute('DELETE FROM oauth WHERE source=?',(identity,))
                for j in self.jobs.values():
                    if j['source']==identity and j['status']=='waiting' and j.get('kind')=='identity':j.update(status='cancelled',url=None)
            return 200,self.status(identity,handler.session_hash)
        if method=='POST' and parts==['codex']:
            if handler.session_hash:return 202,self.start_codex_reconnect(handler,data)
            return 202,self.request_codex_reconnect(identity,data)
        if method=='POST' and parts==['guest']:
            old=handler.session_hash;self.session(self.new_guest(),handler,old);return 200,{'reload':True}
        if method=='POST' and parts==['logout']:
            with self.lock,self.sql:
                self.sql.execute('DELETE FROM sessions WHERE workspace=?',(identity,));self.sql.execute('DELETE FROM oauth WHERE source=?',(identity,))
                for j in self.jobs.values():
                    if j['source']==identity and j['status']=='waiting' and j.get('kind')=='identity':j.update(status='cancelled',url=None)
            self.session(self.new_guest(),handler,handler.session_hash);return 200,{'reload':True}
        if method=='POST' and parts==['api-key']:
            if identity=='local-owner':raise APIError('personal_key','This Mac uses its existing server key. Use a private workspace to store a separate key.')
            key=data.get('key')
            if key is not None and (not isinstance(key,str) or not key.startswith('sk-') or len(key)>512):raise APIError('invalid_key','Enter an OpenAI API key, or null to remove it.')
            self.profile(identity).set('api-key',key);return 200,{'configured':bool(key)}
        raise APIError('not_found','Account route not found.',404)
