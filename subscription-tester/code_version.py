"""Which code the running server loaded, and whether the code on disk has changed since.

An agent talking to a server started before the last code change gets old behavior (old
approval rules, missing routes) with no sign of it. The server records a digest of its
Python and static files when it starts; GET /agent/v1/ and /schema report it together
with the digest of the files on disk now, and the SDK warns when they differ.
"""
import hashlib
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATTERNS = ('*.py', 'music_video/*.py', 'static/*.js', 'static/*.html')


def digest(root=ROOT):
    h = hashlib.sha256()
    for pattern in PATTERNS:
        for path in sorted(root.glob(pattern)):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            h.update(str(path.relative_to(root)).encode() + b'\0' + hashlib.sha256(data).digest())
    return h.hexdigest()[:16]


STARTED_AT = time.time()
STARTED_VERSION = digest()
_cache = {'at': 0.0, 'value': STARTED_VERSION}


def status():
    """{'running', 'on_disk', 'stale', 'started_at', 'message'}; the disk digest is cached for 5 s."""
    now = time.monotonic()
    if now - _cache['at'] > 5:
        _cache.update(at=now, value=digest())
    stale = _cache['value'] != STARTED_VERSION
    return dict(running=STARTED_VERSION, on_disk=_cache['value'], stale=stale, started_at=STARTED_AT,
                message=('The Studio code changed after this server started. Restart the server to use the current '
                         'rules and routes.' if stale else 'The server runs the code on disk.'))
