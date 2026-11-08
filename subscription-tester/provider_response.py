"""Safe diagnostics for provider responses, shared by jobs and the UI."""

import re


def _reason(value, depth=0):
    if isinstance(value, str):
        return value.strip()
    if depth < 4 and isinstance(value, dict):
        for key in ('message', 'detail', 'reason', 'error_description', 'error', 'errors', 'title', 'code', 'type'):
            detail = _reason(value.get(key), depth + 1)
            if detail:
                return detail
    if depth < 4 and isinstance(value, list):
        for item in value[:10]:
            detail = _reason(item, depth + 1)
            if detail:
                return detail
    return ''


def _sanitize(detail, secrets):
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, '[redacted]')
    # Cookie headers can contain several semicolon-delimited credentials.
    detail = re.sub(r'(?im)\b(?:authorization|(?:set-)?cookie)["\']?\s*[:=]\s*[^\r\n]+', '[redacted]', detail)
    detail = re.sub(r'(?i)\bBearer\s+[^\s"\']+|(?:xai-|sk-)[A-Za-z0-9_-]+', '[redacted]', detail)
    detail = re.sub(r'(?i)\b(?:access_token|refresh_token|api_key|token|password)["\']?\s*[:=]\s*(?:"[^"]*"|\'[^\']*\'|[^\r\n,;]+)', '[redacted]', detail)
    detail = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', detail)
    detail = re.sub(r'data:[^\s"\']+', '[inline data omitted]', detail)
    detail = re.sub(r'https?://[^\s"\']+|/(?:Users|home|tmp|private)/[^\s"\']+', '[location omitted]', detail)
    detail = ''.join(c for c in detail if c.isprintable() or c.isspace())
    return ' '.join(detail.split())[:500]


def upstream_error(response, secrets=()):
    """Extract selected error fields, or bounded plain text. Never expose raw bodies."""
    try:
        payload = response.json()
    except ValueError:
        if response.headers.get('content-type', '').partition(';')[0].strip().lower() != 'text/plain':
            return ''
        try:
            raw = response.content
            detail = raw.decode('utf-8').strip() if len(raw) <= 4096 else ''
        except UnicodeError:
            return ''
        if detail.startswith(('<', '{', '[')) or any(not (c.isprintable() or c.isspace()) for c in detail):
            return ''
    else:
        detail = _reason(payload)
    return _sanitize(detail, secrets)


def response_object(response):
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def has_reported_failure(payload):
    return bool(payload and (payload.get('error') or payload.get('errors') or
                             payload.get('status') in ('failed', 'expired')))


def polling_status(response, payload):
    if payload is None:
        return None
    status = payload.get('status')
    if not status and response.status_code == 202 and not has_reported_failure(payload):
        return 'pending'
    return status


def authorization_secrets(headers):
    authorization = headers.get('Authorization', '')
    return authorization, authorization.removeprefix('Bearer ')


class ProviderResponseError(ValueError):
    def __init__(self, action, response, secrets=(), *, hint=''):
        self.http_status = response.status_code
        self.reason = upstream_error(response, secrets)
        detail = self.reason or 'The provider returned no usable error details.'
        super().__init__(f'{action} (HTTP {self.http_status}). {detail}' + (f' {hint}' if hint else ''))

    def fields(self):
        return {'http_status': self.http_status, 'upstream_error': self.reason}
