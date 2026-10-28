"""Recoverable review of generated reference candidates; cached files stay intact."""
import copy
import json
import time
from agent_api import APIError
from story_studio import text


HIDDEN = ('rejected', 'trashed')


def state(asset):
    return asset.get('review_state') or ('approved' if asset.get('approved') else 'candidate')


def available(asset):
    if state(asset) in HIDDEN:
        raise APIError('candidate_unavailable', 'This image is '+state(asset)+'. Restore it to review before approving or reusing it.', 409)


def contains(value, identity):
    if isinstance(value, dict):return any(contains(v, identity) for v in value.values())
    if isinstance(value, list):return any(contains(v, identity) for v in value)
    return value == identity or value == '/api/assets/'+identity


def dependencies(app, identity):
    """Scan current work and immutable snapshots, excluding output provenance."""
    uses=[]
    for ref in app.references:
        if contains(ref.get('images', []),identity):uses.append(dict(kind='Reference',title=ref['title']))
    for draft in app.images.db['drafts']:
        if contains(draft.get('settings', {}),identity):uses.append(dict(kind='Image draft',title=draft['title']))
    for job in app.images.db['jobs']:
        if contains(job.get('draft',{}).get('settings',{}),identity):uses.append(dict(kind='Image request snapshot',title=job['draft']['title']))
    for scene in app.agent.db['scenes']:
        if contains(scene.get('scene',{}),identity):uses.append(dict(kind='Video scene',title=scene['title']))
    for job in app.history:
        if contains(job.get('settings',{}),identity):uses.append(dict(kind='Video request snapshot',title=job.get('title') or 'Saved video'))
    kinds=[row[0] for row in app.productions.sql.execute('SELECT DISTINCT kind FROM records')]
    for kind in kinds:
        for record in app.productions.all(kind):
            if contains(record,identity):
                uses.append(dict(kind=kind.replace('-',' ').title(),title=record.get('name') or record.get('title') or 'Saved '+kind.replace('-',' ')))
    return list({(u['kind'],u['title']):u for u in uses}.values())


def active_approvals(app, identity):
    """Current identities, unlike frozen request/episode history, need explicit clearing."""
    return [e for e in app.productions.all('world-entity') if e.get('identity_asset_id') == identity]


def clear_asset_approval(app, identity):
    """Clear the reusable image flag only after its last current identity is detached."""
    if active_approvals(app, identity):return
    asset, _ = app.asset(identity)
    if state(asset) in HIDDEN or not asset.get('approved'):return
    before_assets=copy.deepcopy(app.assets);before_images=copy.deepcopy(app.images.db)
    try:
        asset.update(approved=False, review_state='candidate', review_revision=asset.get('review_revision', 0)+1)
        for job in app.images.db['jobs']:
            for output in job.get('outputs', []):
                if output['id'] == identity:output.update(copy.deepcopy(asset))
        with app.lock:app.images.save(app.assets_path, app.assets)
        app.images.persist()
    except Exception:
        app.assets=before_assets;app.images.db=before_images
        with app.lock:app.images.save(app.assets_path,app.assets)
        app.images.persist()
        raise



def review(workshop, view_id, data):
    app=workshop.app;p=workshop.p
    with app.agent.lock,app.images.lock:
        view=p.get(view_id,'world-asset');entity=workshop.entity(view['entity_id']);p.check(view,data)
        identity=data.get('asset_id')
        candidate=next((o for o in workshop.view(view)['outputs'] if o['id']==identity),None)
        if candidate is None:raise APIError('invalid_candidate','Choose a candidate from this reference view.')
        asset,_=app.asset(identity)
        if view['kind'] in ('sheet','coverage'):
            return review_view(workshop,view,entity,candidate,data)
        if data.get('expected_review_revision')!=asset.get('review_revision',0):
            raise APIError('revision_conflict','This candidate changed elsewhere. Refresh its review state first.',409)
        action=data.get('action')
        if action not in ('reject','trash','restore'):raise APIError('invalid_review','Choose Reject, Move to Trash or Restore.')
        reason=text(data.get('reason',''),500,'Rejection reason')
        current=state(asset)
        if action=='trash' and current=='trashed':raise APIError('invalid_review','This image is already in Trash.',409)
        uses=dependencies(app,identity) if action!='restore' else []
        if action=='trash' or (action=='reject' and active_approvals(app,identity)):
            if uses:
                return {**workshop.snapshot(entity['production_id'],entity['world_job_id']),
                        'review_blocked':dict(dependencies=uses[:20],count=len(uses))}
        if action=='reject' and current=='trashed':raise APIError('candidate_unavailable','Restore this image from Trash before reviewing it.',409)
        if action=='restore' and current not in HIDDEN:raise APIError('invalid_review','This candidate is already available for review.',409)
        before_assets=copy.deepcopy(app.assets);before_images=copy.deepcopy(app.images.db)
        try:
            with p.mutation():
                if action=='trash':
                    asset['review_previous']=dict(state=current,reason=asset.get('review_reason',''),approved=asset.get('approved',False))
                    target='trashed';approved=False
                elif action=='reject':target='rejected';approved=False
                else:
                    previous=asset.pop('review_previous',{}) if current=='trashed' else {}
                    target=previous.get('state','candidate');approved=previous.get('approved',False)
                    reason=previous.get('reason','')
                asset.update(review_state=target,review_reason=reason if action!='trash' else asset.get('review_reason',''),approved=approved,
                             review_revision=asset.get('review_revision',0)+1,reviewed_at=time.time())
                asset.setdefault('review_history',[]).append(dict(action=action,reason=reason,at=asset['reviewed_at']))
                asset['review_history']=asset['review_history'][-50:]
                for job in app.images.db['jobs']:
                    for output in job.get('outputs',[]):
                        if output['id']==identity:output.update(copy.deepcopy(asset))
                with app.lock:app.images.save(app.assets_path,app.assets)
                app.images.persist()
                view['revision']+=1;p.put('world-asset',view)
        except Exception:
            with app.lock:app.assets=before_assets;app.images.save(app.assets_path,app.assets)
            app.images.db=before_images;app.images.persist()
            raise
        result=workshop.snapshot(entity['production_id'],entity['world_job_id'])
        if action=='reject' and uses:result['review_preserved']=dict(dependencies=uses[:20],count=len(uses))
        return result


def review_view(workshop,view,entity,candidate,data):
    """Review this angle only; preserve images already used by saved work."""
    if data.get('expected_review_revision')!=candidate.get('review_revision',0):
        raise APIError('revision_conflict','This candidate changed elsewhere. Refresh first.',409)
    action=data.get('action');current=state(candidate)
    if action not in ('reject','trash','restore'):raise APIError('invalid_review','Choose Reject, Move to Trash or Restore.')
    if current=='trashed' and action!='restore':raise APIError('candidate_unavailable','Restore this image from Trash first.',409)
    if action=='restore' and current not in HIDDEN:raise APIError('invalid_review','This image is already available.',409)
    if workshop.view(view)['pending']:raise APIError('busy','Wait for this view to finish generating.',409)
    reason=text(data.get('reason',''),500,'Rejection reason')
    with workshop.p.mutation():
        reviews=view.setdefault('candidate_reviews',{})
        prior=reviews.get(candidate['id'],{})
        target='rejected' if action=='reject' else 'trashed' if action=='trash' else prior.get('review_previous','candidate') if current=='trashed' else 'candidate'
        reviews[candidate['id']]=dict(review_state=target,review_reason=reason if action=='reject' else prior.get('review_reason','') if target in HIDDEN else '',review_revision=candidate.get('review_revision',0)+1,review_previous='rejected' if current=='rejected' else 'candidate')
        if action!='restore' and view.get('selected_asset_id')==candidate['id']:
            view.update(selected_asset_id=None,reference_id=None)
        view['revision']+=1;workshop.p.put('world-asset',view)
    return workshop.snapshot(entity['production_id'],entity['world_job_id'])
