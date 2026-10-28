"""Manual tester requests: durable deduplication, safe status, no automatic retry."""
import copy
import hashlib
import json
import re
import threading
import time
import uuid
from agent_api import APIError


class DiagnosticRequests:
    def __init__(self, app, path=None, save=None):
        self.app, self.path, self.save = app, path, save
        self.lock = threading.RLock()
        self.records = json.loads(path.read_text()) if path and path.exists() else []
        changed = False
        for record in self.records:
            if record['status'] == 'pending':
                record.update(status='error', phase='error', message='Tester interrupted. No automatic retry was made.', updated_at=time.time())
                changed = True
        if changed:self.persist()

    def persist(self):
        if self.path:self.save(self.path, self.records)

    def public(self, record):
        return copy.deepcopy({k:v for k,v in record.items() if k not in ('key','fingerprint')})

    def get(self, identity):
        with self.lock:
            record = next((r for r in self.records if r['id'] == identity and r['mock'] == self.app.mock), None)
            if not record:raise APIError('not_found','Image diagnostic not found in this mode.',404)
            return self.public(record)

    def start(self, data, key, prompt_limit):
        if data.get('approved') is not True:raise APIError('approval_required','Explicit human authorization is required.',403)
        prompt = data.get('prompt')
        if not isinstance(prompt,str) or not 1 <= len(prompt.strip()) <= prompt_limit:
            raise APIError('invalid_prompt',f'Enter a prompt between 1 and {prompt_limit:,} characters.')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):
            raise APIError('idempotency_required','Provide an Idempotency-Key of 8–100 letters, numbers, underscores or hyphens.')
        prompt = prompt.strip()
        fingerprint = hashlib.sha256(json.dumps(dict(prompt=prompt,mock=self.app.mock),sort_keys=True).encode()).hexdigest()
        with self.lock:
            prior = next((r for r in self.records if r['key'] == key),None)
            if prior:
                if prior['fingerprint'] != fingerprint:raise APIError('idempotency_conflict','This key belongs to different diagnostic settings.',409)
                return 200,self.public(prior)
            if not self.app.mock and hasattr(self.app,'prompting'):
                raise APIError('prompt_preparation_required','Use Image Studio to prepare and review an AI prompt for Grok Image 2.0, then generate there. This legacy diagnostic uses a retired model; its saved history and local mock remain available.',409)
            now=time.time()
            record=dict(id=uuid.uuid4().hex,key=key,fingerprint=fingerprint,mock=self.app.mock,status='pending',phase='generating',message='Sending one image request…',http_status=None,image=None,created_at=now,updated_at=now)
            self.records.append(record);self.persist()
            def finish(snapshot):
                with self.lock:
                    # Do not store account state, device codes, credentials or headers.
                    record.update({k:snapshot.get(k) for k in ('phase','message','http_status','image')})
                    record.update(status='done' if snapshot.get('phase') == 'done' else 'error',updated_at=time.time())
                    self.persist()
            try:self.app.begin('generate',prompt,on_complete=finish)
            except Exception:
                self.records.remove(record);self.persist();raise
            return 202,self.public(record)
