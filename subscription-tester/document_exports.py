"""One deterministic manuscript formatter for browser previews and agent exports."""
import copy
import json
import re
from agent_api import APIError

def manuscript(doc,title,plan=None,family='series'):
    a=doc.get('answers',{});g=doc.get('guide',{})
    named=lambda key:[c for c in g.get(key,[]) if c.get('name','').strip()]
    if family=='story':
        rows=['# '+title,a.get('idea'),a.get('genre') and 'Genre: '+a['genre'],a.get('tone') and 'Tone: '+a['tone'],a.get('duration') and 'Running time: '+a['duration'],'\n## Cast']
        rows += [c['name']+(' · '+c['role'] if c.get('role') else '')+'\n'+(c.get('motivation') or c.get('personality') or '') for c in named('cast')]
        rows += ['\n## Places']+[c['name']+'\n'+c.get('description','') for c in named('places')]+['\n## Story arc']
        rows += [c.get('title','')+'\n'+c.get('text','') for c in g.get('acts',[])]
        rows += [a.get('style') and '\n## Visual language\n'+a['style'],a.get('rules') and '\n## Continuity\n'+a['rules']]
        rows += ['\n## Script\n'+'\n\n'.join(s['title']+'\n'+s['text'] for s in plan['scenes']) if plan else g.get('script') and '\n## Uploaded story\n'+g['script']]
    else:
        rows=['# '+title,a.get('idea')]+['## '+k.capitalize()+'\n'+a[k] for k in ('genre','tone','theme','audience','duration','style','rules') if a.get(k)]
        for group,label in (('cast','Characters'),('places','Locations'),('props','Key props')):
            cards=[]
            for c in named(group):
                fields=[k.replace('_',' ')+': '+v for k,v in c.items() if k not in ('id','name','reference_ids','palette','series_asset_id') and isinstance(v,str) and v]
                cards.append('### '+c['name']+'\n'+'\n'.join(fields))
            rows.append('## '+label+'\n\n'+'\n\n'.join(cards))
        rows += [a.get('locations') and '## World background\n'+a['locations'],a.get('characters') and '## Continuity notes\n'+a['characters']]
        rows += ['## '+(x.get('title') or 'Story beat')+'\n'+x['text'] for x in g.get('acts',[]) if x.get('text')]
        rows += [a.get('plot') and '## Plot notes\n'+a['plot']]
        inherited=doc.get('inheritance')
        if inherited:rows.append('## Saved series foundation\nBible revision '+str(inherited['bible_revision'])+'\n\n'+inherited.get('answers',{}).get('idea','')+'\n\n'+'\n'.join(x['category']+': '+x['name'] for x in inherited.get('assets',[])))
        if plan:
            scenes=[]
            for scene in plan['scenes']:
                shots='\n\n'.join(x['title']+'\nImage: '+x['image_prompt']+'\nVideo: '+x['video_prompt'] for x in scene.get('shots',[]))
                scenes.append('### '+scene['title']+'\n'+scene['text']+'\n\n'+shots)
            rows.append('## Script\n\n'+'\n\n'.join(scenes))
        elif g.get('script'):rows.append('## Script\n'+g['script'])
    return '\n\n'.join(str(v) for v in rows if v)

class DocumentExports:
    def __init__(self,app):self.app=app
    def render(self,data):
        if set(data)-{'document','title','plan','family','format'}:raise APIError('invalid_document','Use the documented export fields.')
        doc=data.get('document');title=data.get('title','Untitled story');plan=data.get('plan');family=data.get('family','series');fmt=data.get('format','markdown')
        if not isinstance(doc,dict) or not isinstance(doc.get('answers'),dict) or not isinstance(doc.get('guide'),dict) or not isinstance(title,str) or len(title)>120 or family not in ('series','story') or fmt not in ('markdown','json'):raise APIError('invalid_document','Include a book, title, format and family.')
        if len(json.dumps(data,allow_nan=False).encode())>1024*1024:raise APIError('document_limit','Book exports are limited to 1 MB.',413)
        name=re.sub('[^a-zA-Z0-9 _-]','',title) or 'Untitled story'
        if fmt=='json':return dict(filename=name+' - book.json',mime='application/json',text=json.dumps({**copy.deepcopy(doc),**({'script_plan':plan} if plan else {})},indent=2,ensure_ascii=False))
        try:text=manuscript(doc,title,plan,family)
        except (TypeError,KeyError,AttributeError):raise APIError('invalid_document','Check book cards and script plan fields.') from None
        return dict(filename=name+(' - manuscript' if family=='series' else '')+'.md',mime='text/markdown',text=text)
    def saved(self,data):
        if set(data)-{'kind','id','format'}:raise APIError('invalid_document','Choose kind, id and format.')
        kind=data.get('kind');identity=data.get('id');series=self.app.filmmaking.series;p=self.app.productions
        if kind=='series':
            doc=series.bible(identity);title=doc['production']['title'];jobs=[]
        elif kind=='episode':
            doc=series.book(identity);title=doc['episode']['title'];jobs=[j for j in series.jobs(identity) if j['status']=='done' and not j.get('script_inactive')]
        elif kind=='world':
            doc=copy.deepcopy(self.app.filmmaking.world(identity));doc.setdefault('guide',{});title=doc['answers'].get('title') or p.get(identity,'production')['title'];jobs=[j for j in p.all('world-job') if j.get('production_id')==identity and not j.get('scope') and j['mock']==self.app.mock and j['status']=='done']
        else:raise APIError('invalid_document','Choose series, episode or world.')
        latest=jobs[-1] if jobs else None
        return self.render(dict(document=doc,title=title,plan=(latest.get('applied_plan') or latest['result']) if latest else None,family='story' if kind=='world' else 'series',format=data.get('format','markdown')))
    def dispatch(self,method,parts,data,key=None):
        if method=='POST' and parts==['render']:return 200,self.render(data)
        if method=='POST' and parts==['book']:return 200,self.saved(data)
        raise APIError('not_found','Document export route not found.',404)
