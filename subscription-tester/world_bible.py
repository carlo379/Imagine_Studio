"""Illustrated, local PDF export of the reviewed story and approved references."""
import io
from html import escape

def render_bible(app,production,job,workshop,world):
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image,Table,TableStyle,PageBreakIfNotEmpty,KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from PIL import Image as PILImage
    production={**production,'title':job.get('context',{}).get('questionnaire',{}).get('title') or world.get('answers',{}).get('title') or production['title']}
    buffer=io.BytesIO();styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='StudioTitle',fontName='Helvetica-Bold',fontSize=30,leading=35,textColor=colors.HexColor('#123a2b'),spaceAfter=20))
    styles.add(ParagraphStyle(name='StudioBody',fontName='Helvetica',fontSize=10,leading=15,textColor=colors.HexColor('#273b33'),spaceAfter=10))
    styles.add(ParagraphStyle(name='StudioSection',fontName='Helvetica-Bold',fontSize=18,leading=23,textColor=colors.HexColor('#123a2b'),spaceBefore=14,spaceAfter=12))
    styles.add(ParagraphStyle(name='StudioSmall',fontSize=8,leading=12,textColor=colors.HexColor('#526b60'),spaceAfter=8))
    def clean(value):return str(value).replace('\u2011','-').replace('\u2013','-').replace('\u2014','-').replace('\u2192','to').replace('\u00b7','/').replace('\u2019',"'").replace('\u2018',"'").replace('\u201c','"').replace('\u201d','"')
    def p(value,style='StudioBody'):return Paragraph(escape(clean(value)).replace('\n','<br/>'),styles[style])
    def picture(identity,max_w=475,max_h=270):
        _,path=app.asset(identity)
        with PILImage.open(path) as im:w,h=im.size
        scale=min(max_w/w,max_h/h)
        return Image(str(path),width=w*scale,height=h*scale,hAlign='LEFT')
    story=[p('IMAGINE STUDIO / '+world.get('book_kind','STORY BIBLE').upper(),'StudioSmall'),p(production['title'],'StudioTitle')]
    if world.get('series_title'):story.append(p('Series: '+world['series_title'],'StudioSmall'))
    if job['mock']:story.append(p('LOCAL EXAMPLE - generated previews are geometric test images.','StudioSmall'))
    plan=job.get('applied_plan',job['result'])
    story.extend([p(plan['logline'],'StudioSection'),p(plan['synopsis'])])
    if plan['visual_style']:story.extend([p('Visual direction','StudioSection'),p(plan['visual_style'])])
    if world.get('book_kind'):
        for key,label in [('genre','Genre'),('tone','Tone'),('theme','Themes'),('audience','Audience'),('locations','World background'),('rules','Continuity'),('characters','Series notes')]:
            if world['answers'].get(key):story.extend([p(label,'Heading3'),p(world['answers'][key])])
        for act in world.get('guide',{}).get('acts',[]):
            if act.get('text'):story.extend([p(act.get('title') or 'Story beat','Heading3'),p(act['text'])])
    places=world.get('guide',{}).get('places',[])
    for place in places:
        if place.get('palette'):
            palette=Table([['']*len(place['palette'])],colWidths=[475/len(place['palette'])]*len(place['palette']),rowHeights=20)
            palette.setStyle(TableStyle([('BACKGROUND',(i,0),(i,0),colors.HexColor(c)) for i,c in enumerate(place['palette'])]))
            story.extend([p(place['name']+' / palette','StudioSmall'),palette,Spacer(1,10)])
        for identity in place.get('reference_ids',[]):story.extend([p(place['name']+' / reference inspiration','StudioSmall'),picture(identity,max_h=160),Spacer(1,12)])
    while story and isinstance(story[-1],Spacer):story.pop()
    story.append(PageBreakIfNotEmpty())
    categories=[('Character','Cast & outfits'),('Location','Locations & coverage'),('Prop','Props')]
    for index,(category,label) in enumerate(categories):
        entities=[e for e in workshop['entities'] if e['category']==category]
        assets=[a for a in plan['assets'] if a['category']==category]
        if not assets:continue
        story.append(p(label,'StudioSection'))
        for a in assets:
            entity=next((e for e in entities if e['name']==a['name']),None)
            story.extend([p(a['name'],'Heading2'),p(entity['description'] if entity else a['description'])])
            if entity:
                profile=entity.get('profile',{})
                for k,v in profile.items():
                    if k not in ('id','name','reference_ids','palette') and isinstance(v,str) and v and k.title()+': '+v not in entity['description']:story.append(p(k.title()+': '+v,'StudioSmall'))
                views=[v for v in workshop['views'] if v.get('entity_id')==entity['id'] and v.get('selected_asset_id')]
                if not views and entity.get('identity_asset_id'):story.extend([picture(entity['identity_asset_id']),Spacer(1,12)])
                for v in views:story.extend([KeepTogether([p(v['view'],'StudioSmall'),picture(v['selected_asset_id'])]),Spacer(1,14)])
        while story and isinstance(story[-1],Spacer):story.pop()
        if not world.get('book_kind') or plan['scenes'] or world.get('guide',{}).get('script') or any(a['category'] in [c[0] for c in categories[index+1:]] for a in plan['assets']):story.append(PageBreakIfNotEmpty())
    if plan['scenes'] or world.get('guide',{}).get('script') or not world.get('book_kind'):story.append(p('Script & shot plan','StudioSection'))
    if not plan['scenes'] and world.get('guide',{}).get('script'):story.append(p(world['guide']['script']))
    for i,scene in enumerate(plan['scenes']):
        story.extend([p(f'{i+1:02} / '+scene['title'],'Heading2'),p(scene['text'])])
        for shot in scene['shots']:
            story.extend([p(shot['title'],'Heading3'),p('Image: '+shot['image_prompt'],'StudioSmall'),p('Motion: '+shot['video_prompt'],'StudioSmall')])
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#b7d2c4'));canvas.line(42,36,553,36)
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#526b60'));canvas.drawString(42,23,'Imagine Studio / '+clean(production['title'])[:80]);canvas.drawRightString(553,23,str(doc.page))
    doc=SimpleDocTemplate(buffer,pagesize=(595,842),rightMargin=60,leftMargin=60,topMargin=48,bottomMargin=52,title=production['title']+' - '+world.get('book_kind','Story Bible'),author='Imagine Studio')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
