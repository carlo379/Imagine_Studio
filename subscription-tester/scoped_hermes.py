"""Private subprocess bridge to the existing pinned Hermes OAuth implementation."""
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlparse

def emit(value):print(json.dumps(value),flush=True)

def main():
    request=json.loads(sys.stdin.readline())
    with tempfile.TemporaryDirectory(prefix='imagine-hermes-') as folder:
        root=Path(folder);root.chmod(0o700);os.environ['HERMES_HOME']=folder
        for name in ('XAI_API_KEY','XAI_BASE_URL','XAI_OAUTH_BASE_URL'):os.environ.pop(name,None)
        if request.get('auth'):
            file=root/'auth.json';file.write_text(json.dumps(request['auth']));file.chmod(0o600)
        sys.path.insert(0,str(Path(__file__).parent/'.deps'/'hermes'))
        import logging
        logging.disable(logging.CRITICAL)
        import httpx
        from hermes_cli.auth import (_xai_oauth_discovery,_xai_oauth_request_device_code,_xai_oauth_poll_device_token,_save_xai_oauth_tokens,resolve_xai_oauth_runtime_credentials)
        if sys.argv[1]=='login':
            import time
            discovery=_xai_oauth_discovery(20)
            with httpx.Client(timeout=20,follow_redirects=False) as client:
                device=_xai_oauth_request_device_code(client);url=str(device.get('verification_uri_complete') or device['verification_uri']);parsed=urlparse(url)
                if parsed.scheme!='https' or parsed.hostname not in ('accounts.x.ai','auth.x.ai'):raise ValueError()
                emit({'event':'waiting','values':dict(phase='waiting',auth_status='waiting',auth_expires_at=time.time()+int(device['expires_in']),verification_url=url,user_code=str(device['user_code']),message='Approve this workspace in Grok, then return to Studio.')})
                payload=_xai_oauth_poll_device_token(client,token_endpoint=discovery['token_endpoint'],device_code=device['device_code'],expires_in=int(device['expires_in']),poll_interval=int(device['interval']))
            _save_xai_oauth_tokens(payload,discovery=discovery);headers=None
        else:
            c=resolve_xai_oauth_runtime_credentials();token=c.get('api_key','')
            if c.get('provider')!='xai-oauth' or c.get('auth_mode')!='oauth_device_code' or not token or token.startswith('xai-'):raise ValueError()
            headers={'Authorization':'Bearer '+token}
        emit({'event':'done','auth':json.loads((root/'auth.json').read_text()),'headers':headers})

if __name__=='__main__':
    try:main()
    except Exception:sys.exit(1)
