"""Paginated library cards. Detailed drafts/jobs keep their existing routes."""
import copy
import re
from agent_api import APIError


def page(app,data):
    if set(data)-{'collection','query','filter','offset','limit'}:raise APIError('invalid_page','Use collection, query, filter, offset and limit.')
    collection=data.get('collection','all');query=data.get('query','');status=data.get('filter','all');offset=data.get('offset',0);limit=data.get('limit',40)
    if collection not in ('all','images','videos','scripts','assets','uploads','exports') or not isinstance(query,str) or len(query)>200 or not isinstance(status,str) or len(status)>40 or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise APIError('invalid_page','Use a valid collection, query up to 200 characters, and a page size of 1–100.')
    items=[];originals={a['id']:a for a in app.library()}
    def add(kind,state,title,record,src=None,draft_id=None,prefix=None):
        link=record.get('story_context') or {}
        small={k:copy.deepcopy(record[k]) for k in ('id','revision','name','mime','ext','approved','status','handle','images','timeline_id','message','download','output','category','src','bytes','generated','mock','image_job_id') if k in record}
        if link:small['story_context']={k:link[k] for k in ('series_id','episode_id','scene_id') if k in link}
        small['_summary']=True
        items.append(dict(key=(prefix or kind)+'-'+record['id'],kind=kind,status=state,title=title,id=record['id'],src=src,date=record.get('updated_at') or record.get('created_at',0),record=small,draftId=draft_id))
    if collection in ('all','images'):
        drafts=app.images.db['drafts'];jobs=[j for j in app.images.db['jobs'] if j['mock']==app.mock]
        latest={}
        for j in reversed(jobs):latest.setdefault(j['draft']['id'],j)
        by_job={j['id']:j for j in jobs}
        for d in drafts:add('image','draft',d['title'],d,(latest.get(d['id'],{}).get('outputs') or [{}])[0].get('src'),prefix='image-draft')
        for a in originals.values():
            j=by_job.get(a.get('image_job_id'),{})
            add('image',('approved' if a.get('approved') else 'candidate') if a.get('generated') else 'upload',a['name'],{**a,'story_context':j.get('draft',{}).get('story_context')},a['src'],j.get('draft',{}).get('id'))
    if collection in ('all','videos'):
        scenes={r['id']:r for r in app.agent.db['scenes']}
        for d in scenes.values():add('video','archived' if d.get('archived') else 'draft',d['title'],d,prefix='video-draft')
        for j in app.records():
            draft_id=j['settings'].get('_studio_video_id') or j['settings'].get('_studio_scene_id')
            if not draft_id:
                draft_id=next((d['id'] for d in scenes.values() if d['scene']==j['settings'].get('_studio_scene')),None)
            add('video','take',j['settings'].get('_studio_title') or j['settings'].get('prompt','')[:70] or 'Video take',{**j,'story_context':scenes.get(draft_id,{}).get('story_context')},'/api/video-media/'+j['id'] if j.get('video') else None,draft_id,prefix='video-take')
    if collection in ('all','scripts'):
        for e in app.stories.db['episodes']:add('script','script',e['title'],e)
    if collection in ('all','assets'):
        for a in app.named_library():
            image=(a.get('images') or [{}])[0]
            add('asset','archived' if a.get('archived') else a['category'].lower(),a['title'],a,'/api/assets/'+image['asset_id'] if image.get('asset_id') else image.get('url'))
    if collection in ('all','videos','exports'):
        for j in app.productions.all('export'):
            add('export','export',j['snapshot']['title'],j,j.get('src'))
    if collection in ('all','uploads'):
        for m in app.productions.all('edit-media'):add('upload',m.get('kind','upload'),m['name'],m,'/api/edit-media/'+m['id'])
    query=query.casefold()
    items=[i for i in items if (status=='all' or i['status']==status) and query in (i['title']+' '+i['status']+' '+i['record'].get('handle','')).casefold()]
    items.sort(key=lambda i:(i['date'],i['key']),reverse=True)
    selected=items[offset:offset+limit];ids={i['id'] for i in selected if i['kind']=='image'}
    ids.update(image.get('asset_id') for i in selected for image in i['record'].get('images',[]))
    for i in selected:
        for image in i['record'].get('images',[]):
            match=re.fullmatch(r'/api/assets/([A-Za-z0-9_-]+)',image.get('url',''))
            if match:ids.add(match[1])
    return dict(items=selected,total=len(items),offset=offset,limit=limit,has_more=offset+limit<len(items),originals=[copy.deepcopy(originals[i]) for i in ids if i in originals])
