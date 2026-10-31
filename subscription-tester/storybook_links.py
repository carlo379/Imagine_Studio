"""Explicit refresh and readiness of a Storybook's frozen entity links."""
import copy
from agent_api import APIError


def linked_ids(book):
    ids=list(book.get('selected_asset_ids',[]))
    for group in ('cast','places','props'):
        ids.extend(c['series_asset_id'] for c in book['guide'].get(group,[]) if c.get('series_asset_id'))
    return list(dict.fromkeys(ids))


def links(series,book):
    source={e['id']:e for e in series.library(book['production_id'],book['episode_id'])}
    frozen={e['id']:e for e in (book.get('inheritance') or {}).get('assets',[])}
    fields=('revision','name','category','description','profile','identity_asset_id','reference_id','reference')
    result=[]
    for identity in linked_ids(book):
        old=frozen.get(identity);current=source.get(identity)
        changed=old is None or current is None or any(old.get(k)!=current.get(k) for k in fields)
        result.append(dict(entity_id=identity,name=(old or current or {}).get('name',identity),category=(old or current or {}).get('category'),
            linked_revision=(old or {}).get('revision'),source_revision=(current or {}).get('revision'),source_changed=changed,source_missing=current is None,
            identity_asset_id=(old or {}).get('identity_asset_id'),source_identity_asset_id=(current or {}).get('identity_asset_id')))
    return result


def refresh(series,eid,data):
    book=series.book(eid)
    if data.get('expected_revision')!=book['revision']:
        raise APIError('revision_conflict',f"expected_revision must be the Episode Storybook revision; current is {book['revision']}.",409)
    ids=linked_ids(book);current={e['id']:e for e in series.library(book['production_id'],eid)}
    if any(i not in current for i in ids):raise APIError('source_missing','A linked source is unavailable. Remove or restore that link before refreshing.',409)
    inherited=copy.deepcopy(book.get('inheritance'))
    if inherited is None:inherited=series.inheritance(book['production_id'],eid,ids)
    inherited['assets']=[copy.deepcopy(current[i]) for i in ids]
    guide=copy.deepcopy(book['guide'])
    for group in ('cast','places','props'):
        for card in guide.get(group,[]):
            if card.get('series_asset_id') in current:
                source=current[card['series_asset_id']]
                card.update(copy.deepcopy(source.get('profile',{})),id=card['id'],series_asset_id=source['id'],name=source['name'])
    saved={k:v for k,v in book.items() if k not in ('episode','script_drafts','linked_entities')}
    saved.update(inheritance=inherited,guide=guide,revision=book['revision']+1)
    with series.p.sql:series.p.put('episode-book',saved)
    return series.book(eid)


def readiness(series,eid):
    book=series.book(eid);items=links(series,book)
    frozen={e['id']:e for e in (book.get('inheritance') or {}).get('assets',[])}
    for item in items:
        asset_id=item['identity_asset_id'];usable=False
        if asset_id:
            try:
                asset,path=series.app.asset(asset_id)
                usable=path.is_file() and asset.get('review_state') not in ('rejected','trashed') and bool(asset.get('approved') or not asset.get('generated')) and frozen.get(item['entity_id'],{}).get('status')!='needs replacement'
            except (ValueError,OSError):pass
        item.update(confirmed_main_image={'asset_id':asset_id,'src':'/api/assets/'+asset_id} if usable else None,needs_main_image=not usable)
    return dict(episode_id=eid,book_revision=book['revision'],entities=items,ready=all(not i['needs_main_image'] for i in items),needs_images=sum(i['needs_main_image'] for i in items))
