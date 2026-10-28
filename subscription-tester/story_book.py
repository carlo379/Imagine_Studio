"""Local, reviewable manuscript extraction. Never rewrites the supplied story."""
import re
import uuid
from pathlib import Path
from story_studio import text, import_file, split_script


def preview(data):
    source=import_file(data) if 'base64' in data else data.get('text','')
    text(source,60000,'Story',True)
    lines=source.splitlines()
    answers={}
    labels={'title':'title','genre':'genre','tone':'tone','duration':'duration','running time':'duration','audience':'audience','theme':'theme','style':'style','visual style':'style','rules':'rules','premise':'idea','logline':'idea','synopsis':'idea'}
    limits={'title':120,'genre':120,'tone':240,'duration':120,'audience':240,'theme':6000 if data.get('scope')=='episode' else 1000,'style':2000,'rules':4000,'idea':6000}
    for line in lines:
        match=re.match(r'^\s*(?:#{1,6}\s*)?([A-Za-z ]{2,20}):\s*(.+)$',line)
        if match and match[1].lower() in labels:
            key=labels[match[1].lower()];answers[key]=match[2].strip()[:limits[key]]
    title_match=re.search(r'^\s*(?:Title:\s*|#\s+)([^\n]+)',source,re.M|re.I)
    answers.setdefault('title',(title_match[1].strip() if title_match else Path(data.get('name','Uploaded story')).stem)[:120])
    # Only infer names from explicit screenplay cues or labeled character/location lines.
    cast=[];places=[]
    def add(entries,name,detail,key,maximum):
        name=name.strip(' #*:.-')[:80]
        if name and len(entries)<maximum and not any(c['name'].casefold()==name.casefold() for c in entries):
            entries.append(dict(id=str(uuid.uuid4()),name=name,**{key:detail.strip()[:500 if key=='personality' else 1200]}))
    reserved={'FADE IN','FADE OUT','CUT TO','DISSOLVE TO','CONTINUED','THE END','END','BLACK','TITLE','OPENING NOTES'}
    for i,line in enumerate(lines):
        explicit=re.match(r'^\s*(?:[-*]\s*)?(Character|Location):\s*([^:—]+)(?::|—)?\s*(.*)$',line,re.I)
        if explicit:
            is_cast=explicit[1].lower()=='character';add(cast if is_cast else places,explicit[2],explicit[3],'personality' if is_cast else 'description',8 if is_cast else 4)
        location=re.match(r'^\s*(?:\d+\.?\s*)?(?:INT\.?|EXT\.?|INT\.?/EXT\.?|I/E\.?)[ .]+(.+?)(?:\s+[-–—]\s+(DAY|NIGHT|DAWN|DUSK|MORNING|EVENING|CONTINUOUS))?\s*$',line,re.I)
        if location:
            add(places,location[1],'','description',4)
            found=next((p for p in places if p['name'].casefold()==location[1].strip(' #*:.-')[:80].casefold()),None)
            if location[2] and found:found['time']=location[2].title()
        cue=re.sub(r'\s*\((?:V\.O\.|O\.S\.|CONT.D)\)\s*$','',line.strip())
        if cue and len(cue)<=40 and cue.isupper() and re.fullmatch(r'[A-Z][A-Z .\x27-]*',cue) and cue.rstrip(':') not in reserved and not re.match(r'^(ACT|SCENE|INT|EXT|CHAPTER)\b',cue) and i+1<len(lines) and lines[i+1].strip() and not lines[i+1].strip().isupper():
            add(cast,cue.title(),'','personality',8)
    matches=list(re.finditer(r'^\s*(?:#{1,6}\s*)?((?:ACT\s+(?:\d+|[IVX]+)|CHAPTER\s+\d+)[^\n]*)\s*$',source,re.M|re.I))
    acts=[]
    for i,m in enumerate(matches[:8]):
        end=matches[i+1].start() if i+1<len(matches) else len(source)
        acts.append(dict(id=str(uuid.uuid4()),title=m[1].strip()[:120],text=source[m.end():end].strip()[:6000]))
    if not acts:
        scenes=split_script(source)
        if len(scenes)>1:
            acts=[dict(id=str(uuid.uuid4()),title=s['title'][:120],text=s['text'][:6000]) for s in scenes[:8] if s['title']!='Opening notes']
    prose=[line.strip() for line in lines if line.strip() and not line.startswith('#') and not re.match(r'^\s*(?:(?:Title|Genre|Tone|Character|Location|Act|Chapter)\b|INT\.|EXT\.)',line,re.I)]
    answers.setdefault('idea',('\n'.join(prose) or source)[:6000])
    return dict(answers=answers,guide=dict(cast=cast,places=places,acts=acts,script=source),review_required=True,notes=['Original text is preserved in full.','Names and settings are extracted from screenplay headings and explicit labels. Review or add details for prose stories.'])
