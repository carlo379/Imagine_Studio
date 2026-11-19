"""Prop placement: put a real product into a still at its true size, in two image steps.

The method that worked on a product ad after many failed single-model edits:

1. Render the official 3D model at the right size, position and angle (prop-models render).
2. GPT Image edit: the draft still as the base, and the render (or an approved still with
   the product placed right) as a separate reference: "replace the X with the product in
   the second image, same position, size and angle; change nothing else". GPT follows a
   separate product reference well.
3. Grok edit with that GPT image as the only reference and a minimal prompt: "Reproduce the
   input image exactly ... Change nothing." Grok copies it faithfully, in its own texture.

What failed, and is avoided here: Grok ignores a second, conflicting product reference; long
prompts describing the product make Grok redraw it; pasting a render into the image looks
pasted. Each step is an ordinary image generation (approved=true covers both steps of this
run). POST .../advance moves the run on when a step's image is ready; nothing retries on its
own.
"""
import copy
import json
import threading
import time
import uuid
from pathlib import Path

from agent_api import APIError

GPT_MODEL = 'gpt-image-2'
GROK_MODEL = 'grok-imagine-image-2.0'


def _text(value, name, limit, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise APIError('invalid_placement', f'{name} must be text of 1 to {limit} characters.')
    return value.strip()


def gpt_prompt(target, product, keep=None):
    return (f'Replace {target} in the first image with the {product} shown in the second image: same position, same size and the '
            f'same angle as in the second image. The second image is a product reference only; do not copy its background. '
            f'Change nothing else in the first image: keep every person, pose, object, color and the lighting.'
            + (f' {keep}' if keep else ''))


def grok_prompt(product):
    return (f'Reproduce the input image exactly: same composition, people, setting, the {product} and its mount, colors and lighting. '
            'Change nothing.')


class PropPlacement:
    def __init__(self, app, save_json):
        self.app = app
        self.save_json = save_json
        self.path = Path(app.storage) / 'prop-placements.json'
        self.lock = threading.Lock()
        try:
            self.runs = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.runs = []

    def _store(self, run):
        with self.lock:
            self.runs = [r for r in self.runs if r['id'] != run['id']] + [run]
            self.save_json(self.path, self.runs[-200:])

    def get(self, identity):
        with self.lock:
            run = next((r for r in self.runs if r['id'] == identity), None)
        if not run:
            raise APIError('not_found', 'Prop placement run not found.', 404)
        return copy.deepcopy(run)

    def _asset(self, source, label):
        if not isinstance(source, dict) or set(source) != {'asset_id'} or not isinstance(source['asset_id'], str):
            raise APIError('invalid_placement', f'{label} must be {{"asset_id": ...}}.')
        try:
            asset, _ = self.app.asset(source['asset_id'])
        except ValueError:
            raise APIError('not_found', f'{label} asset not found.', 404) from None
        return asset

    def _image(self, title, settings, key):
        """Create, review and generate one image draft through Image Studio."""
        images = self.app.images
        draft = images.dispatch('POST', ['drafts'], {'title': title[:120], 'settings': settings, 'named_references': []}, None)[1]
        draft = images.dispatch('POST', ['drafts', draft['id'], 'review-prompt'],
                                {'expected_revision': draft['revision'], 'reviewed': True, 'authored_by': 'agent'}, None)[1]
        job = images.dispatch('POST', ['drafts', draft['id'], 'generate'], {'approved': True, 'expected_revision': draft['revision']}, key)[1]
        return draft['id'], job['id']

    def create(self, data):
        allowed = {'title', 'base', 'reference', 'target', 'product', 'keep', 'ratio', 'approved', 'gpt_model', 'grok_model'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise APIError('invalid_placement', 'Send title, base, reference, target, product, approved and optional keep, ratio, gpt_model, grok_model.')
        if data.get('approved') is not True:
            raise APIError('approval_required', 'approved=true is required: this run makes two image generations.', 403)
        title = _text(data.get('title'), 'title', 100)
        base = self._asset(data.get('base'), 'base')
        reference = self._asset(data.get('reference'), 'reference')
        if base.get('kind') == 'continuity_check':
            raise APIError('invalid_placement', 'base must be a still, not a review image.')
        target = _text(data.get('target'), 'target (what to replace, e.g. "the wrong dish on the roof")', 300)
        product = _text(data.get('product'), 'product (e.g. "satellite dish")', 120)
        keep = _text(data.get('keep'), 'keep', 400, required=False)
        ratio = data.get('ratio', '16:9')
        if ratio not in ('16:9', '9:16', '1:1', '4:3', '3:4', 'auto'):
            raise APIError('invalid_placement', 'ratio is 16:9, 9:16, 1:1, 4:3, 3:4 or auto.')
        gpt_model = data.get('gpt_model', GPT_MODEL)
        grok_model = data.get('grok_model', GROK_MODEL)
        if not isinstance(gpt_model, str) or not isinstance(grok_model, str):
            raise APIError('invalid_placement', 'gpt_model and grok_model are image model IDs.')
        box = reference.get('bounding_box_px')
        true_ratio = round((box[2] - box[0]) / max(1, box[3] - box[1]), 3) if isinstance(box, list) and len(box) == 4 else None
        identity = uuid.uuid4().hex
        prompt = gpt_prompt(target, product, keep)
        draft, job = self._image(f'{title} · 1 GPT placement', dict(model=gpt_model, prompt=prompt, ratio=ratio, resolution='auto', quality='auto', n=1,
                                                                    base={'asset_id': base['id']}, extras=[{'asset_id': reference['id']}]), f'pp-{identity}-1')
        run = dict(id=identity, title=title, created_at=time.time(), base=base['id'], reference=reference['id'], target=target, product=product,
                   ratio=ratio, models=dict(gpt=gpt_model, grok=grok_model), true_ratio=true_ratio, status='step_1_running',
                   steps=[dict(step=1, kind='gpt_placement', prompt=prompt, draft_id=draft, job_id=job, output=None)], result=None)
        self._store(run)
        return run

    def advance(self, identity):
        run = self.get(identity)
        if run['status'] == 'done':
            return run
        step = run['steps'][-1]
        job = self.app.images.dispatch('GET', ['jobs', step['job_id']], {}, None)[1]
        if job['status'] == 'pending':
            return dict(run, waiting='The image for step %d is still being made. Advance again later; do not start a new run.' % step['step'])
        outputs = job.get('outputs') or []
        if job['status'] != 'done' or not outputs:
            run['status'] = f"step_{step['step']}_failed"
            run['error'] = job.get('message') or 'The image step failed.'
            self._store(run)
            return run
        step['output'] = outputs[0]['id']
        if step['step'] == 1:
            prompt = grok_prompt(run['product'])
            draft, job_id = self._image(f"{run['title']} · 2 Grok reproduce", dict(model=run['models']['grok'], prompt=prompt, ratio=run['ratio'],
                                                                                   resolution='2k', quality='auto', n=1, extras=[{'asset_id': step['output']}]),
                                        f"pp-{run['id']}-2")
            run['steps'].append(dict(step=2, kind='grok_reproduce', prompt=prompt, draft_id=draft, job_id=job_id, output=None))
            run['status'] = 'step_2_running'
        else:
            run['status'] = 'done'
            run['result'] = dict(asset_id=step['output'], gpt_asset_id=run['steps'][0]['output'],
                                 next_steps=['Show both images to the human right away (the GPT placement and the Grok reproduction).',
                                             'Zoom in and measure the product: its width-to-height ratio should match true_ratio '
                                             '(from the render) within about 5%.' if run['true_ratio'] else
                                             'Zoom in and measure the product against an official view.',
                                             'For an end frame, check it against the start frame with POST image-studio/continuity.'])
        self._store(run)
        return run

    def dispatch(self, method, parts, data, key):
        if not parts:
            if method == 'GET':
                with self.lock:
                    return 200, copy.deepcopy(list(reversed(self.runs)))
            if method == 'POST':
                return 201, self.create(data)
        if len(parts) == 1 and method == 'GET':
            return 200, self.get(parts[0])
        if len(parts) == 2 and parts[1] == 'advance' and method == 'POST':
            return 200, self.advance(parts[0])
        raise APIError('not_found', 'Prop placement route not found.', 404)
