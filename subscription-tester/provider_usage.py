"""Sanitized observations from existing xAI calls, never inferred balances."""
from collections.abc import Mapping
import copy
import json
import re
import time

# An explicit allowlist prevents credentials and arbitrary upstream headers from
# entering the agent API. Values remain provider strings, not computed quotas.
HEADERS={'retry-after','ratelimit-limit','ratelimit-remaining','ratelimit-reset'} | {
    prefix+kind+'-'+suffix for prefix in ('x-ratelimit-','x-rate-limit-')
    for kind in ('limit','remaining','reset') for suffix in ('requests','tokens','images','videos')}
HEADERS |= {'x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset'}


def observe(app,response,scope):
    headers=getattr(response,'headers',{})
    if not isinstance(headers,Mapping):return
    values={str(k).lower():str(v) for k,v in headers.items()
            if str(k).lower() in HEADERS and isinstance(v,(str,int,float)) and len(str(v))<=160
            and re.fullmatch(r'[0-9A-Za-z ,:;=.\-+/]+',str(v))}
    if not values:return
    with app.lock:
        path=app.storage/'grok-usage.json'
        from studio_server import save_json
        observations=read(app)
        observations[scope]=dict(source='xAI response headers',scope=scope,observed_at=time.time(),rate_limits=values)
        try:save_json(path,observations)
        except OSError:pass  # Telemetry must never interrupt a submitted generation.


def read(app):
    try:
        value=json.loads((app.storage/'grok-usage.json').read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def grok(app,scope):
    values=read(app)
    observation=values.get(scope) or values.get('grok_account')
    return dict(remaining='unknown',used_today='unknown',balance_available=False,
        reason='Grok subscription balance is unavailable and cannot be read by Studio through the connected subscription bridge. Rate limits are not a subscription balance.',
        rate_limit_observation=copy.deepcopy(observation) if observation and not app.mock else None)
