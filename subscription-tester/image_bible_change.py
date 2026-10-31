"""Explicit, revision-bound image-to-Bible changes. No vision or paid calls."""
import copy
from contextlib import contextmanager
import time
from agent_api import APIError
from candidate_review import available


def context(w,view_id,data):
    view=w.p.get(view_id,'world-asset');w.p.check(view,data)
    entity=w.entity(view['entity_id'])
    if view['kind'] not in ('portrait','location','prop'):
        raise APIError('invalid_view','Update the Bible from a main reference candidate; outfit variations do not redefine the identity.')
    candidate=next((o for o in w.view(view)['outputs'] if o['id']==data.get('asset_id')),None)
    if not candidate:raise APIError('invalid_candidate','Choose a candidate from this view.')
    available(candidate);asset,_=w.app.asset(candidate['id']);available(asset)
    if data.get('expected_entity_revision')!=entity['revision']:
        raise APIError('revision_conflict','The Bible entity changed. Preview again.',409)
    scope=entity.get('scope')
    book=w.f.series.bible(entity['production_id']) if scope=='series-bible' else w.f.series.book(entity['episode_id']) if scope=='episode-book' else w.f.world(entity['production_id'])
    return view,entity,candidate,book


def preview(w,view_id,data):
    view,e,candidate,book=context(w,view_id,data)
    if w.view(view)['pending']:raise APIError('busy','Wait for this reference generation to finish before updating the Bible.',409)
    if data.get('image_layout',candidate.get('image_layout','main')) not in ('main','front','side','back','head','character_sheet'):raise APIError('invalid_layout','Choose the actual image layout.')
    changes=data.get('changes')
    if not isinstance(changes,dict) or not changes or any(k not in e['profile'] or k in ('id','name','palette','series_asset_id') or (not isinstance(v,list) if k=='reference_ids' else not isinstance(v,str)) for k,v in changes.items()):
        raise APIError('invalid_changes','Supply descriptive profile fields or reference_ids (up to five available approved image ids).')
    key={'Character':'cast','Location':'places','Prop':'props'}[e['category']]
    guide=copy.deepcopy(book.get('guide',{}))
    card=next((c for c in guide.get(key,[]) if c['id']==e.get('source_card_id') or (not e.get('source_card_id') and c['name']==e['name'])),None)
    if card is None:raise APIError('missing_bible_card','Add this entity to its source Bible before proposing an image change.',409)
    diffs=[dict(field=k,before=e['profile'].get(k,''),bible_before=card.get(k,''),after=v) for k,v in changes.items() if v!=e['profile'].get(k) or v!=card.get(k)]
    if not diffs:raise APIError('no_changes','The proposed fields already match the Bible.')
    card.update(changes)
    guide=w.f.series.guide(guide,candidate_asset_id=candidate['id']) if e.get('scope') else w.normalize_guide(guide,candidate_asset_id=candidate['id'])
    with w.p.sql:return w.p.new('image-bible-preview',view_id=view_id,entity_id=e['id'],asset_id=candidate['id'],
        view_revision=view['revision'],entity_revision=e['revision'],review_revision=candidate.get('review_revision',0),
        book_id=book['id'],book_revision=book['revision'],changes=changes,diff=diffs,guide=guide,
        image_layout=data.get('image_layout',candidate.get('image_layout','main')),status='preview',source='image')


@contextmanager
def image_change_mutation(w,asset_id):
    # Coordinate the JSON approval metadata with the existing SQL/reference
    # rollback boundary. Nested confirm must not commit the outer transaction.
    asset,_=w.app.asset(asset_id);before=copy.deepcopy(asset)
    outputs=[(o,copy.deepcopy(o)) for job in w.app.images.db['jobs'] for o in job.get('outputs',[]) if o['id']==asset_id]
    try:
        with w.f.asset_mutation():yield
    except Exception:
        asset.clear();asset.update(before)
        for output,snapshot in outputs:output.clear();output.update(snapshot)
        w.app.images.save(w.app.assets_path,w.app.assets);w.app.images.persist()
        raise


def confirm(w,view_id,data):
    if data.get('authored_by','human') not in ('human','agent'):raise APIError('invalid_author','authored_by must be agent or human.')
    if data.get('approved') is not True:raise APIError('approval_required','Explicitly confirm the previewed Bible changes.',403)
    proposal=w.p.get(data.get('preview_id'),'image-bible-preview')
    if proposal['view_id']!=view_id:raise APIError('invalid_preview','This preview belongs to another view.')
    if proposal['status']=='applied':return w.snapshot(w.entity(proposal['entity_id'])['production_id'],w.entity(proposal['entity_id'])['world_job_id'])
    view,e,candidate,book=context(w,view_id,{**data,'asset_id':proposal['asset_id'],'expected_revision':proposal['view_revision'],'expected_entity_revision':proposal['entity_revision']})
    if book['id']!=proposal['book_id'] or book['revision']!=proposal['book_revision'] or candidate.get('review_revision',0)!=proposal['review_revision']:
        raise APIError('revision_conflict','The Bible or image review changed. Preview again.',409)
    if e.get('scope'):w.f.series.guide(proposal['guide'],candidate_asset_id=candidate['id'])
    else:w.normalize_guide(proposal['guide'],candidate_asset_id=candidate['id'])
    # Validate the ordinary confirmation before changing descriptive data.
    with image_change_mutation(w,candidate['id']):
        w.confirm(view_id,dict(expected_revision=view['revision'],asset_id=candidate['id'],approved=True,image_layout=proposal['image_layout']),coordinated=True)
        e=w.entity(e['id']);profile={**e['profile'],**proposal['changes']}
        description=e['description']
        for field,value in proposal['changes'].items():
            if not isinstance(value,str):continue
            description=description.replace(field.replace('_',' ').title()+': '+str(e['profile'].get(field,'')),field.replace('_',' ').title()+': '+value)
        e.update(profile=profile,description=description,revision=e['revision']+1)
        if e.get('scope'):e['source_card_snapshot']=next(c for c in proposal['guide'][{'Character':'cast','Location':'places','Prop':'props'}[e['category']]] if c['id']==e['source_card_id'])
        event=dict(source='image',asset_id=candidate['id'],preview_id=proposal['id'],diff=proposal['diff'],confirmed_at=time.time(),authored_by=data.get('authored_by','human'))
        e.setdefault('bible_change_history',[]).append(event);w.p.put('world-entity',e);w.sync_view_metadata(e)
        stored={k:v for k,v in book.items() if k not in ('production','legacy_world','episode','script_drafts')}
        stored.update(guide=proposal['guide'],revision=book['revision']+1)
        stored.setdefault('image_change_history',[]).append(event)
        w.p.put(e.get('scope') or 'world',stored)
        if e.get('reference_id'):
            from character_metadata import library_description
            ref=w.app.asset_studio.get(e['reference_id'])
            w.app.asset_studio.dispatch('PUT',[ref['id']],dict(expected_revision=ref['revision'],description=library_description(e,w.app.agent.config['reference_description_limit'])),None)
        proposal.update(status='applied',confirmation=copy.deepcopy(event),revision=proposal['revision']+1);w.p.put('image-bible-preview',proposal)
    return w.snapshot(e['production_id'],e['world_job_id'])
