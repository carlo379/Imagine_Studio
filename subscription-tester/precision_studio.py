"""Deterministic local corrections and provider-specific region guidance. Originals survive."""
import base64
import copy
import io
import math
import re
import time
import uuid
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from agent_api import APIError

MAX_PIXELS=16_000_000
Image.MAX_IMAGE_PIXELS=MAX_PIXELS

def region(value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)!= {'x','y','width','height'}:raise APIError('invalid_region','Select a rectangular image region.')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in value.values()):raise APIError('invalid_region','Region coordinates must be finite numbers.')
    x,y,w,h=(value[k] for k in ('x','y','width','height'))
    if x<0 or y<0 or w<=0 or h<=0 or x+w>1.000001 or y+h>1.000001:raise APIError('invalid_region','Keep the selected region inside the image.')
    return copy.deepcopy(value)

def load(path):
    try:
        with Image.open(path) as src:
            if src.width*src.height>MAX_PIXELS:raise APIError('image_limit','Local editing supports up to 16 million pixels.')
            return ImageOps.exif_transpose(src).convert('RGBA')
    except (UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise APIError('invalid_image','Upload a readable PNG, JPEG or WebP image.') from None

def png(im):
    out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()

def bounds(im,r):
    r=region(r)
    x,y,w,h=(r[k] for k in ('x','y','width','height'))
    left,top=round(x*im.width),round(y*im.height)
    return left,top,min(im.width,max(left+1,round((x+w)*im.width))),min(im.height,max(top+1,round((y+h)*im.height)))

def mask_for(path,r):
    im=load(path);mask=Image.new('RGBA',im.size,(0,0,0,255));box=bounds(im,r)
    ImageDraw.Draw(mask).rectangle((box[0],box[1],box[2]-1,box[3]-1),fill=(0,0,0,0))
    return png(im),png(mask)

class PrecisionStudio:
    def __init__(self,app):self.app=app
    def transform(self,data):
        asset,path=self.app.asset(data.get('asset_id'));im=load(path)
        reference=self.app.asset_studio.get(data['reference_id']) if data.get('reference_id') else None
        if reference and {'asset_id':asset['id']} not in reference['images']:raise APIError('invalid_parent','Choose an image from this canonical asset.')
        ops=data.get('operations',[])
        if not isinstance(ops,list) or not 1<=len(ops)<=50:raise APIError('invalid_edit','Choose 1–50 local editing operations.')
        for op in ops:
            if not isinstance(op,dict):raise APIError('invalid_edit','Use an editing operation.')
            kind=op.get('kind')
            if kind=='crop':im=im.crop(bounds(im,op.get('region')))
            elif kind=='rotate':
                angle=op.get('degrees')
                if angle not in (90,180,270):raise APIError('invalid_edit','Rotate by 90, 180 or 270 degrees.')
                im=im.rotate(-angle,expand=True)
            elif kind=='resize':
                w,h=op.get('width'),op.get('height')
                if type(w) is not int or type(h) is not int or not 1<=w<=8192 or not 1<=h<=8192 or w*h>MAX_PIXELS:raise APIError('image_limit','Use positive dimensions up to 8192 per edge and 16 million pixels.')
                im=im.resize((w,h),Image.Resampling.LANCZOS)
            elif kind in ('paint','erase'):
                points=op.get('points');width=op.get('width',.01);color=op.get('color','#ffffff')
                if not isinstance(points,list) or not 1<=len(points)<=5000 or type(width) not in (int,float) or not math.isfinite(width) or not 0<width<=.2:raise APIError('invalid_edit','Use a brush width from 0–20% of the image and up to 5000 points.')
                if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color):raise APIError('invalid_edit','Choose a valid brush color.')
                coords=[]
                for p in points:
                    if not isinstance(p,list) or len(p)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1 for n in p):raise APIError('invalid_edit','Brush points must be inside the image.')
                    coords.append((round(p[0]*(im.width-1)),round(p[1]*(im.height-1))))
                size=max(1,round(width*min(im.size)));fill=(0,0,0,0) if kind=='erase' else color
                draw=ImageDraw.Draw(im);draw.line(coords,fill=fill,width=size,joint='curve')
                for x,y in (coords[0],coords[-1]):draw.ellipse((x-size/2,y-size/2,x+size/2,y+size/2),fill=fill)
            else:raise APIError('invalid_edit','Choose crop, rotate, resize, paint or erase.')
        with self.app.agent.lock,self.app.images.lock:
            draft=copy.deepcopy(self.app.images.draft(data['draft_id'])) if data.get('draft_id') else self.app.images.create({'title':asset['name'][:95]+' · corrected','settings':{'base':{'asset_id':asset['id']}}})
            job=dict(id=uuid.uuid4().hex,created_at=time.time(),mock=self.app.mock,draft=draft,provider='local',model='local-edit',billing='Local edit · no provider usage',status='done',message='Local correction saved. Review before approving.',outputs=[],operations=copy.deepcopy(ops),parent_asset_id=asset['id'],expanded_prompt='',source_count=1)
            output=self.app.images.cache(png(im),job);output['parent_asset_id']=asset['id'];output['local_edit']=True
            self.app.agent.save(self.app.assets_path,self.app.assets)
            job['outputs']=[output];self.app.images.db['jobs'].insert(0,job);self.app.images.persist()
            if reference:
                with self.app.productions.sql:self.app.productions.new('asset-development',reference_id=reference['id'],reference_revision=reference['revision'],draft_id=draft['id'])
            return copy.deepcopy(job)
    def dispatch(self,method,parts,data,key):
        if parts==['schema'] and method=='GET':return 200,dict(operations=['crop','rotate','resize','paint','erase'],max_pixels=MAX_PIXELS,region='Normalized x,y,width,height in 0..1',originals_preserved=True,ai_mask_models=['gpt-image-2.5-flare','gpt-image-2.5-sunburst'],subscription_region_mode='Prompt guidance; no mask guarantee')
        if parts==['edits'] and method=='POST':return 201,self.transform(data)
        if parts==['refine'] and method=='POST':
            self.app.asset(data.get('asset_id'));r=region(data.get('region'));settings=data.get('settings',{})
            if not isinstance(settings,dict):raise APIError('invalid_settings','Use image settings.')
            details={'title':data.get('title','Precision refinement'),'settings':{**settings,'base':{'asset_id':data['asset_id']},'edit_region':r}}
            # A refinement is a new candidate draft; never rewrite its source workflow.
            with self.app.images.lock:
                if data.get('draft_id'):
                    source=self.app.images.draft(data['draft_id'])
                    if source['revision']!=data.get('expected_revision'):
                        raise APIError('revision_conflict','Image draft changed. Reload it or save a copy.',409)
                    details['story_context']=copy.deepcopy(source.get('story_context'))
                    details['parent_draft_id']=source['id']
                    for binding in details['settings'].get('bindings',[]):binding['selected']=[]
                    details['settings']['extras']=[]
                draft=self.app.images.create(details)
            return 201,draft
        raise APIError('not_found','Precision editor route not found.',404)
