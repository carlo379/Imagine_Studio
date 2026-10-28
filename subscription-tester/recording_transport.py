"""Convert approved local recordings to scoped, temporary HTTPS references.

The xAI public-files service rejects audio; a one-file relay is used instead.
The caller owns its lifetime through an ExitStack across submission and polling.
No provider request, relay or upload is performed by scene validation.
"""
import base64
import copy
import hashlib
import ipaddress
import subprocess
import re
import time
from urllib.parse import urlsplit

class RecordingTransportError(ValueError):
    pass

def verify_public_dns(client,url,expected_hash):
    """Check a newly provisioned tunnel without changing the OS DNS settings.

    curl --resolve keeps TLS certificate/SNI checks for the original hostname.
    Only an IP from public DNS for this exact tunnel is used, never credentials.
    """
    host=urlsplit(url).hostname
    if not host or not host.endswith('.trycloudflare.com'):return False
    for endpoint in ('https://cloudflare-dns.com/dns-query','https://dns.google/resolve'):
        try:
            answer=client.get(endpoint,params={'name':host,'type':'A'},headers={'Accept':'application/dns-json'},timeout=5).json()
            for record in answer.get('Answer',[]):
                if record.get('type')!=1:continue
                address=ipaddress.ip_address(record['data'])
                if address.version!=4 or not address.is_global:continue
                fetched=subprocess.run(['curl','--disable','--silent','--show-error','--fail','--max-time','8',
                    '--proto','=https','--resolve',f'{host}:443:{address}',url],capture_output=True,timeout=10)
                if fetched.returncode==0 and hashlib.sha256(fetched.stdout).hexdigest()==expected_hash:return True
        except Exception:pass
    return False

def verify_delivery(client,url,expected_hash,timeout=120):
    deadline=time.monotonic()+timeout
    last='no response'
    while True:
        try:
            response=client.get(url,timeout=5)
            if response.status_code==200 and hashlib.sha256(response.content).hexdigest()==expected_hash:return
            last='HTTP '+str(response.status_code) if response.status_code!=200 else 'recording hash mismatch'
        except Exception as error:
            last=type(error).__name__
            if last=='ConnectError' and verify_public_dns(client,url,expected_hash):return
        if time.monotonic()>=deadline:
            raise RecordingTransportError(f'Temporary audio URL did not return the exact recording bytes ({last}). No video was submitted.')
        time.sleep(2)

def prepare_recordings(client, headers, body, *, resources=None):
    from recording_relay import RecordingRelay
    result=copy.deepcopy(body);uploads=[]
    for item in result.get('reference_audios',[]):
        value=item.get('url','')
        if not value.startswith('data:audio/'):continue
        if resources is None:
            raise RecordingTransportError('Recording delivery needs a managed lifetime. No video was submitted.')
        match=re.fullmatch(r'data:(audio/(?:wav|mpeg));base64,([A-Za-z0-9+/=]+)',value)
        if not match:raise RecordingTransportError('Invalid local recording data; no video was submitted.')
        mime=match[1]
        try:raw=base64.b64decode(match[2],validate=True)
        except ValueError:raise RecordingTransportError('Invalid local recording bytes. No video was submitted.') from None
        try:relay=resources.enter_context(RecordingRelay(raw,mime))
        except Exception as error:
            raise RecordingTransportError('Could not start temporary audio delivery. Check the cf CLI installation and network connection. No video was submitted.') from error
        parsed=urlsplit(relay.url)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.trycloudflare.com') or parsed.username or parsed.password:
            raise RecordingTransportError('Invalid temporary audio delivery URL. No video was submitted.')
        digest=hashlib.sha256(raw).hexdigest()
        verify_delivery(client,relay.url,digest)
        item['url']=relay.url
        uploads.append(dict(transport='temporary-https-relay',sha256=digest,delivery_verified=True,
            bytes=len(raw),expires_after_seconds=3600))
    return result,uploads
