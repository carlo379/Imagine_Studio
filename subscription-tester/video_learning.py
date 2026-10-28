"""Human-reviewed, workspace-scoped video prompting lessons with reversible history.

The shipped capability guide is never rewritten by a generated result. Approved
observations supplement it for one exact served model and workspace mode.
"""
import copy
import threading
import time

from agent_api import APIError
import prompt_guides

VIDEO_MODELS = ('grok-imagine-video-1.5', 'grok-imagine-video-1.5-lite')


class VideoLearning:
    def __init__(self, app):
        self.app, self.p = app, app.productions
        self.lock = threading.RLock()

    def model(self, model):
        if model not in VIDEO_MODELS:
            raise APIError('unsupported_model', 'Choose a supported video model for this lesson.')
        return model

    def lesson(self, identity):
        row = self.p.get(identity, 'video-prompt-lesson')
        if row.get('mock') != self.app.mock:
            raise APIError('not_found', 'Lesson not found in this workspace mode.', 404)
        return row

    def version(self, model):
        rows = [r for r in self.p.all('video-learning-guide')
                if r['model'] == model and r['mock'] == self.app.mock]
        return rows[-1]['revision'] if rows else 0

    def bump(self, model):
        rows = [r for r in self.p.all('video-learning-guide')
                if r['model'] == model and r['mock'] == self.app.mock]
        if not rows:
            return self.p.new('video-learning-guide', model=model, mock=self.app.mock)['revision']
        row = rows[-1]
        row['revision'] += 1
        return self.p.put('video-learning-guide', row)['revision']

    def history(self, model):
        self.model(model)
        with self.lock:
            rows = [r for r in self.p.all('video-prompt-lesson')
                    if r['model'] == model and r['mock'] == self.app.mock]
            return dict(model=model, guide_version=self.version(model), lessons=copy.deepcopy(rows))

    @staticmethod
    def bounded(value, name, limit, required=True):
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise APIError('invalid_lesson', 'Use a concise ' + name + '.')
        return value.strip()

    def propose(self, review, data):
        """No second writer call. Propose only a finding-backed, human-confirmed lesson."""
        assessment = data.get('assessment')
        if assessment is None:
            assessment = 'successful' if data.get('successful') is True else 'needs_work'
        if data.get('approved') is not True or assessment not in ('successful', 'improved'):
            raise APIError('success_required', 'Confirm the successful take or the individual improvements '
                           'you reviewed before proposing a lesson.', 403)
        if review.get('status') != 'done' or review.get('mock') != self.app.mock:
            raise APIError('review_required', 'Finish reviewing this video before proposing a lesson.', 409)
        requirements = {r.get('id'): r for r in (review.get('result') or {}).get('requirements', [])}
        confirmed = data.get('confirmed_finding_ids')
        if confirmed is None and assessment == 'successful':
            # Legacy success confirmations already cover every assessed, met
            # finding. Partial improvement must always name the confirmed parts.
            confirmed = [identity for identity, finding in requirements.items()
                         if finding.get('status') == 'met']
        if (not isinstance(confirmed, list) or (assessment == 'improved' and not confirmed)
                or len(confirmed) > 30 or any(not isinstance(identity, str) for identity in confirmed)
                or len(set(confirmed)) != len(confirmed)
                or any(identity not in requirements or requirements[identity].get('status') != 'met'
                       for identity in confirmed)):
            raise APIError('evidence_required', 'Choose the met findings you personally confirmed '
                           'as improvements in this video.')
        confirmed_ids = set(confirmed)
        if ('candidate_index' in data and data['candidate_index'] is None) or not confirmed_ids:
            # Recording a human assessment is useful independently of proposing
            # a lesson. An empty success selection cannot support new learning.
            return None
        model = self.model(review.get('model') or review.get('snapshot', {}).get('request', {}).get('model'))
        snapshot = review.get('snapshot', {})
        served = snapshot.get('returned_model')
        if served != model:
            # A provider serving a different model is not evidence for the
            # requested model's prompting guide. An unknown served model cannot
            # support model-specific learning either.
            return None
        candidates = (review.get('result') or {}).get('lesson_candidates') or []
        if not candidates:
            return None
        index = data.get('candidate_index', 0)
        if type(index) is not int or not 0 <= index < len(candidates):
            raise APIError('invalid_lesson', 'Choose a lesson from this review.')
        candidate = candidates[index]
        guidance = self.bounded(candidate.get('guidance'), 'lesson', 1200)
        rationale = self.bounded(candidate.get('rationale'), 'evidence explanation', 1600)
        findings = candidate.get('finding_ids', [])
        if not isinstance(findings, list) or not findings or any(f not in requirements for f in findings):
            raise APIError('evidence_required', 'A lesson must point to requirements in its video review.')
        # Learning concerns only the parts that both the review and the human
        # confirm; remaining failures do not prevent those lessons.
        if any(requirements[f].get('status') != 'met' or f not in confirmed_ids for f in findings):
            return None
        fingerprint = prompt_guides.digest([review['id'], index, guidance, assessment, sorted(confirmed_ids)])
        with self.lock, self.p.sql:
            prior = next((r for r in self.p.all('video-prompt-lesson')
                          if r.get('proposal_fingerprint') == fingerprint and r['mock'] == self.app.mock), None)
            if prior:
                return prior
            video_id = review.get('video_job_id') or review.get('snapshot', {}).get('video_job_id')
            request = review.get('snapshot', {}).get('request', {})
            workflow = ('reference-to-video' if request.get('reference_images') else
                        'image-to-video' if request.get('image') else 'text-to-video')
            outcome = ('human-confirmed success' if assessment == 'successful' else
                       'human-confirmed improvement; take still needs work')
            evidence = dict(review_id=review['id'], review_revision=review['revision'],
                video_job_id=video_id, finding_ids=copy.deepcopy(findings), outcome=outcome,
                assessment=assessment, confirmed_finding_ids=copy.deepcopy(confirmed),
                confidence='tentative', confirmed_at=time.time(), returned_model=served,
                submission_provenance=snapshot.get('source', 'unknown'))
            return self.p.new('video-prompt-lesson', model=model, mock=self.app.mock, status='proposed',
                guidance=guidance, rationale=rationale, scope=workflow + '; comparable shot conditions only.',
                workflow=workflow,
                limitations='Sampled visual evidence and human approval establish an observation, not causality. '
                    'Audio delivery and exact spoken words are not assessed by visual review.',
                confidence='tentative', evidence=[evidence], guide_version=self.version(model),
                proposal_fingerprint=fingerprint)

    def approve(self, identity, data):
        if data.get('approved') is not True:
            raise APIError('approval_required', 'Review the lesson before adding it to your prompting guide.', 403)
        with self.lock, self.p.sql:
            row = self.lesson(identity)
            self.p.check(row, data)
            if row['status'] not in ('proposed', 'inactive'):
                raise APIError('already_reviewed', 'This lesson has already been reviewed.', 409)
            if data.get('expected_guide_version') != self.version(row['model']):
                raise APIError('guide_changed', 'Your learned guide changed. Refresh the lesson before applying it.', 409)
            row['guidance'] = self.bounded(data.get('guidance', row['guidance']), 'lesson', 1200)
            # Merge only equivalent, human-approved lessons; preserve every candidate.
            equivalent = next((r for r in self.p.all('video-prompt-lesson')
                if r['id'] != row['id'] and r['model'] == row['model'] and r['mock'] == self.app.mock
                and r['status'] == 'active' and r.get('workflow') == row.get('workflow')
                and r['guidance'].casefold() == row['guidance'].casefold()), None)
            active = [r for r in self.p.all('video-prompt-lesson') if r['model'] == row['model']
                      and r['mock'] == self.app.mock and r['status'] == 'active']
            if not equivalent and len(active) >= 24:
                raise APIError('guide_limit', 'Remove an older active lesson before adding another. '
                               'The guide holds 24 lessons per model to keep authoring focused.', 409)
            version = self.bump(row['model'])
            row.update(status='active', revision=row['revision']+1, approved_at=time.time(), guide_version=version)
            if equivalent:
                known = {e['review_id'] for e in equivalent['evidence']}
                equivalent['evidence'] += [e for e in row['evidence'] if e['review_id'] not in known]
                distinct = {e['video_job_id'] for e in equivalent['evidence'] if e.get('video_job_id')}
                equivalent.update(confidence='supported' if len(distinct) >= 3 else 'tentative',
                    revision=equivalent['revision']+1, guide_version=version)
                self.p.put('video-prompt-lesson', equivalent)
                row.update(status='merged', merged_into=equivalent['id'])
            self.p.put('video-prompt-lesson', row)
            return dict(lesson=row, guide_version=version, model=row['model'])

    def dismiss(self, identity, data):
        with self.lock, self.p.sql:
            row = self.lesson(identity)
            self.p.check(row, data)
            if row['status'] != 'proposed':
                raise APIError('already_reviewed', 'This lesson has already been reviewed.', 409)
            row.update(status='dismissed', revision=row['revision']+1)
            self.p.put('video-prompt-lesson', row)
            return dict(lesson=row, guide_version=self.version(row['model']), model=row['model'])

    def deactivate(self, identity, data):
        with self.lock, self.p.sql:
            row = self.lesson(identity)
            self.p.check(row, data)
            if row['status'] != 'active':
                raise APIError('inactive_lesson', 'This lesson is not active in your prompting guide.', 409)
            version = self.bump(row['model'])
            row.update(status='inactive', revision=row['revision']+1, guide_version=version)
            self.p.put('video-prompt-lesson', row)
            return dict(lesson=row, guide_version=version, model=row['model'])

    def supplement(self, model):
        """Bounded approved lessons become part of frozen guide text and its hash."""
        if model not in VIDEO_MODELS:
            return ''
        history = self.history(model)
        rows = [r for r in history['lessons'] if r['status'] == 'active']
        if not rows:
            return ''
        # Human observations cannot redefine API capabilities or override intent.
        text = '\n\n## Workspace video-review lessons (version ' + str(history['guide_version']) + ')\n'
        text += 'Human-reviewed observations for ' + model + '. Apply only to comparable conditions; '
        text += 'preserve current human intent, reference identities and model capabilities. '
        text += 'These observations do not prove that wording caused a result or guarantee future success.\n'
        for row in rows:
            text += '\n- [' + row['confidence'] + '; ' + row['scope'] + '; lesson ' + row['id'] + '] '
            text += row['guidance'] + '\n'
        return text
