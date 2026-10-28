"""Local upload reconciliation. Only explicit metadata spans can be removed."""
import copy
import hashlib
import json
import re
from agent_api import APIError
from story_studio import import_file, text
from world_workshop import CAST, PLACE

LABELS={'title':'title','episode title':'title','premise':'idea','logline':'idea','synopsis':'idea','episode premise':'idea','conflict':'theme','conflict / what changes?':'theme','genre':'genre','tone':'tone','theme':'theme','audience':'audience','duration':'duration','running time':'duration','visual style':'style','style':'style','rules':'rules','world rules':'rules','continuity notes':'characters','world background':'locations','plot notes':'plot'}
GROUPS={'characters':'cast','cast':'cast','locations':'places','places':'places','props':'props','key props':'props'}

def scene_boundary(line):
    return re.match(r'^(?:#{1,6}\s*)?(?:\*\*)?(?:\d[^|\n]*\|\s*)?(?:INT\.?|EXT\.?|INT\.?/EXT\.?|SCENE\s+\d+)\b',line.strip(),re.I)

def metadata(source):
    """Recognize labeled paragraphs and Markdown metadata, never screenplay prose."""
    lines=source.splitlines(keepends=True); offsets=[];pos=0
    for line in lines:offsets.append(pos);pos+=len(line)
    group=None;name=None;in_script=False;items=[];i=0
    while i<len(lines):
        line=lines[i].strip().replace('**','');heading=re.match(r'^(#{1,6})\s+(.+?)\s*#*$',line)
        if scene_boundary(line):in_script=True;group=None;name=None
        label=None;value=None;start=i;end=i+1;kind='answer';field=None
        if heading:
            level=len(heading[1]);title=heading[2].strip();low=title.casefold()
            if low in ('script','episode script','screenplay'):in_script=True;group=None;name=None
            elif low in GROUPS:group=GROUPS[low];name=None;in_script=False
            elif level>=3 and group:
                name=title
                # A named asset heading may be followed by an unlabeled description.
                first=i+1
                while first<len(lines) and not lines[first].strip():first+=1
                if first<len(lines) and not scene_boundary(lines[first]) and not re.match(r'^\s*(?:#|(?:\*\*)?[A-Za-z /?_-]{2,40}:)',lines[first]):
                    start=first;end=first+1
                    while end<len(lines) and lines[end].strip() and not lines[end].lstrip().startswith('#') and not scene_boundary(lines[end]):end+=1
                    kind='card';field='description';label=name+' · description';value=''.join(lines[first:end]).strip()
            elif low in LABELS:
                kind='answer';field=LABELS[low];label=title;in_script=False;group=None;name=None
                while end<len(lines) and not lines[end].lstrip().startswith('#') and not scene_boundary(lines[end]):end+=1
                value=''.join(lines[i+1:end]).strip()
            elif level<=2:group=None;name=None
        else:
            explicit=re.match(r'^(?:[-*]\s*)?(Character|Location|Prop):\s*([^:—]+)(?::|—)\s*(.+)$',line,re.I)
            pair=re.match(r'^(?:[-*]\s*)?([A-Za-z /?_-]{2,40}):\s*(.+)$',line)
            if explicit and not in_script:
                kind='card';group={'character':'cast','location':'places','prop':'props'}[explicit[1].lower()];name=explicit[2].strip();field='description';label=name+' · description';value=explicit[3].strip()
            elif pair and not in_script:
                low=pair[1].lower().replace('_',' ')
                if group and name:
                    field=low.replace(' ','_');limits=CAST if group=='cast' else PLACE if group=='places' else {'description':10000,'purpose':10000,'details':10000}
                    if field in limits and field!='name':kind='card';label=name+' · '+low;value=pair[2].strip()
                if value is None and low in LABELS:kind='answer';field=LABELS[low];label=pair[1];value=pair[2].strip();group=None;name=None
                if value is not None:
                    while end<len(lines) and lines[end].strip() and not scene_boundary(lines[end]) and not re.match(r'^\s*(?:#|(?:\*\*)?[A-Za-z /?_-]{2,40}:)',lines[end],re.I):end+=1
                    value+=''.join(lines[i+1:end]).rstrip() if end==i+1 else '\n'+''.join(lines[i+1:end]).strip()
        if value and field:
            items.append(dict(id=str(len(items)),label=label,kind=kind,field=field,group=group if kind=='card' else None,name=name if kind=='card' else None,value=value,start=offsets[start],end=offsets[end] if end<len(lines) else len(source)))
        i=end
    return items

def get_path(doc,path):
    for part in path:doc=doc[part]
    return doc

def set_path(doc,path,value):
    parent=get_path(doc,path[:-1]);parent[path[-1]]=value

class ScriptUploadReview:
    def __init__(self,series):
        self.s=series;self.p=series.p
        from script_upload_ai import ScriptUploadAI
        self.ai=ScriptUploadAI(self)

    def compare(self,eid,source):
        book=self.s.book(eid);bible=self.s.bible(book['production_id']);items=metadata(source);comparisons=[]
        roots=[('book',book,[],'Episode Storybook'),('bible',bible,[],'Series Bible')]
        inherited=book.get('inheritance')
        if inherited:
            roots.append(('book',inherited,['inheritance'],"Episode’s saved series foundation"))
            if inherited.get('bible'):roots.append(('book',inherited['bible'],['inheritance','bible'],"Episode’s saved Bible copy"))
        for item in items:
            targets=[]
            for owner,root,prefix,label in roots:
                if item['kind']=='answer':
                    if item['field']=='title' and (owner!='book' or prefix):continue
                    value=root.get('answers',{}).get(item['field'],'')
                    if value:targets.append(dict(owner=owner,path=prefix+['answers',item['field']],label=label,value=value))
                else:
                    for n,card in enumerate(root.get('guide',{}).get(item['group'],[])):
                        if card.get('name','').casefold()==item['name'].casefold() and card.get(item['field']):
                            targets.append(dict(owner=owner,path=prefix+['guide',item['group'],n,item['field']],label=label+' · '+card['name'],value=card[item['field']]))
            # Selected asset snapshots are production context; update only the reviewed field.
            if inherited and item['kind']=='card':
                category={'cast':'Character','places':'Location','props':'Prop'}[item['group']]
                for n,asset in enumerate(inherited.get('assets',[])):
                    if asset.get('category')!=category or asset.get('name','').casefold()!=item['name'].casefold():continue
                    for tail in (['profile',item['field']], [item['field']] if item['field']=='description' else []):
                        if not tail:continue
                        try:value=get_path(asset,tail)
                        except (KeyError,TypeError):continue
                        if value:targets.append(dict(owner='book',path=['inheritance','assets',n]+tail,label='Selected asset snapshot · '+asset['name'],value=value))
            for previous in items[:int(item['id'])]:
                if all((previous[k] or '').casefold()==(item[k] or '').casefold() for k in ('kind','field','group','name','label')):
                    targets.append(dict(owner='upload',path=[previous['id']],label='Earlier uploaded detail',value=previous['value']))
            if targets:comparisons.append({**item,'targets':targets,'identical':all(t['value'].strip()==item['value'].strip() for t in targets)})
        signature=hashlib.sha256(json.dumps([source,book['revision'],book['episode']['revision'],bible['revision'],comparisons],sort_keys=True).encode()).hexdigest()
        return dict(source=source,comparisons=comparisons,review_token=signature,book_revision=book['revision'],bible_revision=bible['revision']),book,bible,items

    def preview(self,eid,data):
        source=import_file(data) if 'base64' in data else data.get('text','');text(source,60000,'Script',True)
        return self.compare(eid,source)[0]

    def apply(self,eid,data):
        source=data.get('source','');text(source,60000,'Script',True)
        with self.p.mutation():
            review,book,bible,items=self.compare(eid,source)
            if data.get('review_job_id'):
                job=self.ai.read(eid,data['review_job_id'])
                if job['status']!='done':raise APIError('review_required','Wait for the AI review to finish.')
                if job['source_script']!=source or job['book_revision']!=book['revision'] or job['bible_revision']!=bible['revision'] or job['episode_revision']!=book['episode']['revision']:raise APIError('revision_conflict','The script or saved details changed. Run the AI review again.',409)
                review=copy.deepcopy(job['result']);items=copy.deepcopy(review['items'])
                for target in job['targets']:
                    if target['owner']=='upload':items.append(dict(id=target['path'][0],start=target['start'],end=target['end']))
            if data.get('review_token')!=review['review_token']:raise APIError('revision_conflict','The script or saved information changed. Compare the upload again before applying.',409)
            self.p.check(book,data)
            if data.get('expected_episode_revision')!=book['episode']['revision']:raise APIError('revision_conflict','The episode changed. Review the upload again.',409)
            if any(j['status']=='pending' for j in self.s.jobs(eid)):raise APIError('busy','Wait for script writing to finish before applying an upload.',409)
            if book['guide']['script'].strip() and data.get('replace_existing') is not True:raise APIError('script_exists','Confirm replacing the current Script draft.',409)
            choices=data.get('choices',{})
            if not isinstance(choices,dict) or set(choices)!={c['id'] for c in review['comparisons']} or any(v not in ('uploaded','app','both') for v in choices.values()):raise APIError('review_required','Choose which information to keep for every comparison.')
            polish=data.get('allow_dialogue_polish',False)
            if type(polish) is not bool:raise APIError('invalid_options','Choose whether dialogue suggestions are allowed.')
            changed=copy.deepcopy(book);foundation=copy.deepcopy(bible);removed=set();writes={}
            for item in review['comparisons']:
                choice=choices[item['id']]
                if item.get('advisory_only') and choice!='both':raise APIError('script_preserved','This comparison is advisory. Keep narrative text and review it manually.')
                if choice=='app':removed.add(item['id'])
                if choice!='uploaded':continue
                for target in item['targets']:
                    if target['owner']=='upload':removed.add(target['path'][0]);continue
                    identity=json.dumps([target['owner'],target['path']])
                    if identity in writes and writes[identity]!=item['value']:raise APIError('conflicting_choices','Two uploaded details would replace the same app field. Keep only one uploaded version or keep both in the script.')
                    writes[identity]=item['value'];set_path(changed if target['owner']=='book' else foundation,target['path'],item['value'])
            # Reject contradictory decisions instead of silently discarding a chosen version.
            if any(choices.get(i)=='uploaded' for i in removed):raise APIError('conflicting_choices','Two duplicate choices conflict. Choose one uploaded detail to keep.')
            spans=sorted({(i['start'],i['end']) for i in items if i['id'] in removed})
            if data.get('review_job_id') and any(a<i['end'] and b>i['start'] for a,b in spans for i in review['comparisons'] if choices[i['id']] in ('uploaded','both')):raise APIError('conflicting_choices','A removal overlaps information you chose to keep. Review the conflicting choices.')
            merged=[]
            for start,end in spans:
                if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
                else:merged.append((start,end))
            result=source
            for start,end in reversed(merged):result=result[:start]+result[end:]
            text(result,60000,'Script',True);changed['guide']['script']=result
            # All normal field limits still apply; never truncate a chosen description.
            changed['answers']=self.s.answers(changed['answers'],episode=True);changed['guide']=self.s.guide(changed['guide'])
            foundation['answers']=self.s.answers(foundation['answers']);foundation['guide']=self.s.guide(foundation['guide'])
            from series_builder import ANSWERS
            for item in review['comparisons']:
                if choices[item['id']]=='uploaded' and item['kind']=='answer':
                    for target in item['targets']:
                        if target['owner']!='upload':text(item['value'],6000 if target['owner']=='book' and item['field']=='theme' else ANSWERS[item['field']],item['label'])
                elif choices[item['id']]=='uploaded' and item['kind']=='card':
                    limits=CAST if item['group']=='cast' else PLACE if item['group']=='places' else {'description':10000,'purpose':10000,'details':10000}
                    text(item['value'],limits[item['field']],item['label'])
                elif choices[item['id']]=='uploaded' and item['kind']=='beat':text(item['value'],6000,item['label'])
            self.p.new('episode-script-draft',episode_id=eid,script=source,label='Original upload before duplicate review')
            if book['guide']['script']:self.p.new('episode-script-draft',episode_id=eid,script=book['guide']['script'],label='Draft before script upload')
            self.p.new('script-upload-review',episode_id=eid,production_id=book['production_id'],source=source,choices=choices,comparisons=review['comparisons'],previous_book=book,previous_bible=bible)
            if foundation['answers']!=bible['answers'] or foundation['guide']!=bible['guide']:
                self.p.put('series-bible',dict(id=bible['id'],production_id=bible['production_id'],revision=bible['revision']+1,answers=foundation['answers'],guide=foundation['guide']))
            saved={k:changed[k] for k in ('id','production_id','episode_id','answers','guide','selected_asset_ids','inheritance')}
            if changed['answers']['title']!=book['answers']['title']:
                self.s.app.stories.episode_edit(self.s.app.stories.record('episodes',eid),dict(expected_revision=book['episode']['revision'],title=changed['answers']['title']))
            saved.update(revision=book['revision']+1,script_options={'allow_dialogue_polish':polish});self.p.put('episode-book',saved)
            for job in self.s.jobs(eid):
                if not job.get('script_inactive'):
                    job.update(script_inactive=True,revision=job['revision']+1);self.p.put('world-job',job)
        return self.s.book(eid)
