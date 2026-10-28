"""Revisioned local timeline and FFmpeg exports. Provider generations are never invoked."""
import base64
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
import importlib.util
from collections import deque
from editing_captions import CAPTION_STYLE,from_srt,to_srt,wrapped
from PIL import Image,ImageDraw,ImageFont
from agent_api import APIError
from editing_tools import migrate_timeline, build_export, AUDIO_FIELDS, OUTPUT_FIELDS, DUCKING, audio_filters, PICTURE_FIELDS, COLOR_DEFAULT, length
from media_inspection import MediaInspection

RATIOS = {'16:9': (1280,720), '9:16': (720,1280), '1:1': (720,720)}
MIME = {'mp4':'video/mp4','mov':'video/quicktime','webm':'video/webm','mp3':'audio/mpeg','wav':'audio/wav','m4a':'audio/mp4','ogg':'audio/ogg','aac':'audio/aac','png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp'}

def timeline_duration(clips):
    return round(sum(length(c)-c.get('transition',{}).get('duration',0) for c in clips),9)

def number(value, low, high, label, precision=3):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise APIError('invalid_timeline',f'{label} must be between {low} and {high}.')
    return round(value,precision)

class EditingStudio:
    def __init__(self,app):
        self.app=app;self.p=app.productions;self.processes={};self.cancellations={};self.lock=threading.RLock()
        self.inspection=MediaInspection(app.storage)
        self.ffmpeg=shutil.which('ffmpeg') or ('/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').exists() else None)
        self.ffprobe=shutil.which('ffprobe') or ('/opt/homebrew/bin/ffprobe' if Path('/opt/homebrew/bin/ffprobe').exists() else None)
        with self.p.sql:
            for j in self.p.all('export'):
                if j['status'] in ('queued','rendering'):
                    j.update(status='error',error='The server restarted. The saved edit is intact; export it again.');self.p.put('export',j)
    def probe(self,path):
        if not self.ffprobe:raise APIError('editor_unavailable','Install FFmpeg to inspect and export media.',503)
        try:
            r=subprocess.run([self.ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,timeout=20,check=True)
            d=json.loads(r.stdout);streams=d.get('streams',[]);duration=float(d['format']['duration'])
            if not math.isfinite(duration) or not 0.04 <= duration <= 3600:raise ValueError()
            v=next((s for s in streams if s['codec_type']=='video'),None)
            if v and (int(v['width'])*int(v['height'])>3840*2160*2):raise ValueError()
            return dict(duration=round(duration,3),video=bool(v),audio=any(s['codec_type']=='audio' for s in streams),width=v.get('width') if v else None,height=v.get('height') if v else None)
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            raise APIError('invalid_media','This media could not be read. Use a video or audio file up to one hour long.') from None
    def loudness(self,path):
        if not self.ffmpeg:return None
        saved=self.inspection.get(path)
        if 'loudness_lufs' in saved:return saved['loudness_lufs']
        stat=path.stat();cache=getattr(self,'_loudness',{});key=(str(path),stat.st_size,stat.st_mtime_ns)
        if key not in cache:
            try:
                r=subprocess.run([self.ffmpeg,'-v','info','-nostdin','-i',str(path),'-t','30','-vn','-af','loudnorm=print_format=json','-f','null','-'],capture_output=True,timeout=40)
                match=re.search(r'"input_i"\s*:\s*"([^"]+)"',r.stderr.decode(errors='replace'));value=float(match[1]) if match else float('nan')
                cache[key]=value if math.isfinite(value) else None
            except (OSError,ValueError,subprocess.TimeoutExpired):cache[key]=None
            self._loudness=cache
            self.inspection.put(path,{'loudness_lufs':cache[key]})
        return cache[key]

    @property
    def inspection_revision(self):return self.inspection.revision

    def take_record(self,identity):
        """Find one take without copying the entire generation history."""
        with self.app.lock:
            job=next((j for j in self.app.history if j['id']==identity),None)
            if job:return copy.deepcopy(job)
        with self.app.agent.lock:
            try:job=self.p.get(identity,'imported-video')
            except APIError as error:
                if error.code=='not_found':return None
                raise
        return job if job.get('mock')==self.app.mock else None

    def inspect(self,data):
        if set(data)-{'source','background','analyze_loudness'} or any(k in data and type(data[k]) is not bool for k in ('background','analyze_loudness')):
            raise APIError('invalid_inspection','Use source and optional boolean background/analyze_loudness flags.')
        source=data.get('source')
        if data.get('background') is not True:
            m,path=self.source(source)
            return {**m,'loudness_lufs':self.loudness(path) if m.get('audio') and data.get('analyze_loudness',True) else None}
        # Basic metadata is available without decoding a whole audio track.
        if not isinstance(source,dict):raise APIError('invalid_source','Choose workspace media.')
        kind=source.get('kind');identity=source.get('id');path=None
        if kind=='gap' and source=={'kind':'gap'}:
            return dict(duration=60,video=True,audio=False,width=1280,height=720,loudness_lufs=None,inspection_status='ready')
        if set(source)!={'kind','id'} or kind not in ('take','upload','image') or not isinstance(identity,str):
            raise APIError('invalid_source','Choose workspace media.')
        if kind=='upload':
            with self.app.agent.lock:m,path=self.media_file(identity)
        elif kind=='image':m,path=self.source(source)
        else:
            with self.app.agent.lock:
                job=self.take_record(identity)
                if not job or job['status']!='done' or not job.get('video'):raise APIError('missing_take','Choose a completed video in this workspace.',404)
                settings=job['settings']
                m=dict(id=identity,duration=settings.get('duration',0),video=True,audio=settings.get('generate_audio',True),width=None,height=None)
                if job.get('imported_media_id'):m,path=self.media_file(job['imported_media_id'])
                elif job.get('mock') and not job.get('archive_local_video'):path=Path(__file__).parent/'static'/'mock-video.mp4'
                else:path=self.app.storage/'videos'/(identity+'.mp4')
            # Opening a timeline never downloads all its uncached takes.
            if not path.is_file():return {**m,'loudness_lufs':None,'inspection_status':'uncached'}
        cached=self.inspection.get(path);metadata=cached.get('metadata')
        if metadata:m={**m,**metadata}
        needs_probe=not metadata and kind=='take' and not cached.get('inspection_error')
        needs_loudness=data.get('analyze_loudness') is True and m.get('audio') and 'loudness_lufs' not in cached and not cached.get('inspection_error')
        if needs_probe or needs_loudness:
            def analyze():
                try:
                    info=self.probe(path) if needs_probe else m
                    self.inspection.put(path,{'metadata':info,'inspection_error':None})
                    if data.get('analyze_loudness') is True and info.get('audio'):self.loudness(path)
                except (APIError,OSError):
                    try:self.inspection.put(path,{'inspection_error':'This source could not be inspected. Open or replace its local media file.'})
                    except OSError:pass
            self.inspection.schedule(path,analyze)
        return {**m,'loudness_lufs':cached.get('loudness_lufs'),'loudness_current':'loudness_lufs' in cached,'inspection_error':cached.get('inspection_error'),'inspection_status':'unavailable' if cached.get('inspection_error') else 'pending' if needs_probe or needs_loudness else 'ready'}

    def upload(self,data):
        name=data.get('name','');ext=Path(name).suffix.lower().lstrip('.') if isinstance(name,str) else ''
        if ext not in MIME:raise APIError('invalid_media','Upload video, audio, PNG, JPEG or WebP.')
        try:raw=base64.b64decode(data['base64'],validate=True)
        except (ValueError,KeyError,TypeError):raise APIError('invalid_media','Upload a valid media file.') from None
        if not 0 < len(raw) <= 64*1024*1024:raise APIError('media_limit','Media uploads must be at most 64 MB.')
        identity=uuid.uuid4().hex;path=self.app.storage/'edit-media'/f'{identity}.{ext}'
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(raw);path.chmod(0o600)
        try:info=self.image_info(path) if MIME[ext].startswith('image/') else self.probe(path)
        except Exception:path.unlink(missing_ok=True);raise
        with self.p.sql:return self.p.put('edit-media',dict(id=identity,revision=1,created_at=time.time(),name=name[:120],ext=ext,mime=MIME[ext],bytes=len(raw),**info))
    def media_file(self,identity):
        m=self.p.get(identity,'edit-media');path=self.app.storage/'edit-media'/f"{m['id']}.{m['ext']}"
        if not path.is_file():raise APIError('missing_media','The source file is missing.',404)
        return m,path
    def source(self,value):
        if value=={'kind':'gap'}:return dict(video=True,audio=False,duration=60,width=1280,height=720),None
        if not isinstance(value,dict) or set(value)!={'kind','id'} or value['kind'] not in ('take','upload','image') or not isinstance(value['id'],str):
            raise APIError('invalid_source','Choose a completed video, approved image, asset image or uploaded media.')
        if value['kind']=='upload':return self.media_file(value['id'])
        if value['kind']=='image':
            try:m,path=self.app.asset(value['id'])
            except ValueError:raise APIError('missing_media','Choose an image in this workspace.',404) from None
            if m.get('generated') and (m.get('mock')!=self.app.mock or not m.get('approved')):raise APIError('image_not_approved','Approve this generated image in Image Studio before adding it to an edit.')
            return {**m,**self.image_info(path)},path
        job=self.take_record(value['id'])
        if not job or job['status']!='done' or not job.get('video'):raise APIError('missing_take','Choose a completed video in this workspace.',404)
        try:path=self.app.download(job['id'])
        except ValueError:raise APIError('missing_media','This video is not cached locally and its saved download failed. Upload your saved MP4 in Edit to use it.',404) from None
        info=self.inspection.get(path).get('metadata')
        if not info:
            info=self.probe(path);self.inspection.put(path,{'metadata':info,'inspection_error':None})
        return dict(id=job['id'],name=job.get('settings',{}).get('_studio_scene',{}).get('title','Video take'),**info),path
    def image_info(self,path):
        try:
            with Image.open(path) as im:
                w,h=im.size
                if im.format not in ('PNG','JPEG','WEBP') or w*h>3840*2160*2:raise ValueError()
                im.verify()
            return dict(image=True,video=False,audio=False,duration=3,width=w,height=h)
        except (OSError,ValueError,Image.DecompressionBombError):raise APIError('invalid_media','Use a readable PNG, JPEG or WebP image up to 16.6 megapixels.') from None
    def timeline(self,pid,episode_id=None,story_scene_id=None):
        o=self.p.summary(pid)
        if o['production']['kind']=='story':
            if not any(e['id']==episode_id for e in o['episodes']):raise APIError('missing_episode','Choose an episode to edit.')
        elif episode_id is not None:raise APIError('invalid_parent','Quick videos do not have episodes.')
        scene=None
        if story_scene_id is not None:
            scene=next((s for e in o['episodes'] if e['id']==episode_id for s in e['scenes'] if s['id']==story_scene_id),None)
            if scene is None:raise APIError('missing_scene','Choose a scene in this production and episode.')
        candidates=[t for t in self.p.all('timeline') if t['production_id']==pid and t['episode_id']==episode_id and t.get('story_scene_id')==story_scene_id]
        existing=next((t for t in candidates if t.get('primary')),candidates[0] if candidates else None)
        if existing:return migrate_timeline(existing)
        with self.p.sql:return self.p.new('timeline',production_id=pid,episode_id=episode_id,story_scene_id=story_scene_id,primary=True,title=scene['title'] if scene else o['production']['title'],clips=[],audio=[],titles=[],captions=[],markers=[],schema_version=3,output={'ratio':'16:9','resolution':'720p','fps':24,**copy.deepcopy(OUTPUT_FIELDS),'cut_audio_crossfade_frames':2})
    def validate(self,data):
        if not isinstance(data,dict) or set(data)-{'title','clips','audio','titles','captions','markers','output'}:raise APIError('invalid_timeline','Use title, clips, audio, titles and output.')
        title=data.get('title','Untitled edit')
        if not isinstance(title,str) or not title.strip() or len(title)>120:raise APIError('invalid_title','Name the edit using at most 120 characters.')
        output=data.get('output',{});clips=data.get('clips',[]);audio=data.get('audio',[]);titles=data.get('titles',[])
        if not isinstance(output,dict) or set(output)-{'ratio','resolution','fps',*OUTPUT_FIELDS} or not {'ratio','resolution','fps'}<=set(output) or output.get('ratio') not in RATIOS or output.get('resolution') not in ('480p','720p','1080p','source') or type(output.get('fps')) is not int or output['fps'] not in (24,30):raise APIError('invalid_output','Choose 16:9, 9:16 or 1:1; 720p or 1080p; and 24 or 30 fps.')
        output = {**copy.deepcopy(OUTPUT_FIELDS), **output}
        frames=output['cut_audio_crossfade_frames']
        if type(frames) is not int or not 0<=frames<=12:raise APIError('invalid_output','Cut audio crossfade must be 0–12 whole frames.')
        target=output['loudness_target_lufs']
        if target is not None:output['loudness_target_lufs']=number(target,-30,-10,'Loudness target LUFS')
        duck=output['ducking']
        if not isinstance(duck,dict) or set(duck)-set(DUCKING):raise APIError('invalid_output','Use enabled, amount_db, attack_ms and release_ms for ducking.')
        duck={**DUCKING,**duck}
        if type(duck['enabled']) is not bool:raise APIError('invalid_output','Ducking enabled must be boolean.')
        for k,lo,hi in [('amount_db',0,24),('attack_ms',5,500),('release_ms',50,2000)]:duck[k]=number(duck[k],lo,hi,'Ducking '+k)
        output['ducking']=duck
        style=output['captions']
        if not isinstance(style,dict) or set(style)-set(CAPTION_STYLE):raise APIError('invalid_captions','Use mode, position, size, color and max_chars_per_line for captions.')
        style={**CAPTION_STYLE,**style}
        if style['mode'] not in ('off','burn_in','sidecar','both') or style['position'] not in ('top','center','bottom'):raise APIError('invalid_captions','Choose off/burn_in/sidecar/both and top/center/bottom.')
        style['size']=number(style['size'],16,96,'Caption size')
        if not isinstance(style['color'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',style['color']):raise APIError('invalid_captions','Use a hex caption color.')
        if type(style['max_chars_per_line']) is not int or not 8<=style['max_chars_per_line']<=80:raise APIError('invalid_captions','Caption line width must be an integer 8–80.')
        output['captions']=style
        for track,items,limit in (('clip',clips,120),('audio',audio,200),('title',titles,100)):
            if not isinstance(items,list) or len(items)>limit:raise APIError('timeline_limit',f'Use at most {limit} {track} items per timeline.')
        ids=set();out={'title':title.strip(),'output':copy.deepcopy(output),'clips':[],'audio':[],'titles':[],'captions':[],'markers':[]};total=0
        def identity(item):
            i=item.get('id')
            if not isinstance(i,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,100}',i) or i in ids:raise APIError('invalid_id','Timeline item IDs must be unique.')
            ids.add(i);return i
        for c in clips:
            if not isinstance(c,dict) or set(c)-{'id','source','in','out','volume','label','shot_id','transition','audio_offset','render_link',*AUDIO_FIELDS,*PICTURE_FIELDS}:raise APIError('invalid_clip','Use the documented clip fields.')
            m,_=self.source(c.get('source'))
            if not (m['video'] or m.get('image')):raise APIError('invalid_clip','Clips require video or image media.')
            limit=60 if c['source'].get('kind')=='gap' else 3600 if m.get('image') else m['duration']
            a=number(c.get('in',0),0,limit,'Trim start',9);b=number(c.get('out',m['duration']),0,limit,'Trim end',9)
            if m.get('image') and a!=0:raise APIError('invalid_clip','Still images start at zero; set out to their display duration.')
            if b-a<.04:raise APIError('invalid_trim','Each clip must contain at least 0.04 seconds.')
            label=c.get('label',m.get('name','Video'));shot_id=c.get('shot_id')
            if not isinstance(label,str) or len(label)>120:raise APIError('invalid_clip','Clip labels may contain up to 120 characters.')
            if shot_id:self.p.get(shot_id,'shot')
            item=dict(id=identity(c),source=copy.deepcopy(c['source']),**{'in':a,'out':b},volume=number(c.get('volume',1),0,2,'Clip volume'),label=label,shot_id=shot_id)
            if m.get('render_link'):item['render_link']=copy.deepcopy(m['render_link'])
            for k in ('flip_h','flip_v'):
                if type(c.get(k,False)) is not bool:raise APIError('invalid_clip',k+' must be boolean.')
                item[k]=c.get(k,False)
            item['speed']=number(c.get('speed',1),.25,4,'Clip speed')
            item['speed_audio']=c.get('speed_audio','preserve_pitch')
            if item['speed_audio'] not in ('preserve_pitch','mute'):raise APIError('invalid_clip','Choose preserve_pitch or mute for speed audio.')
            for k in ('hold_start','hold_end'):
                item[k]=number(c.get(k,0),0,10,k);self.whole_frame(item[k],output['fps'],k)
            for k,defaults in [('crop',PICTURE_FIELDS['crop']),('zoom',PICTURE_FIELDS['zoom'])]:
                v=c.get(k,defaults)
                if not isinstance(v,dict) or set(v)!=set(defaults):raise APIError('invalid_clip','Use the documented '+k+' fields.')
                item[k]={field:number(value,.1 if field in ('w','h') else 1 if field=='scale' else 0,3 if field=='scale' else 1,k+' '+field) for field,value in v.items()}
            if item['crop']['x']+item['crop']['w']>1.000001 or item['crop']['y']+item['crop']['h']>1.000001:raise APIError('invalid_clip','Crop must fit inside the source frame.')
            color=c.get('color','#000000' if c['source'].get('kind')=='gap' else COLOR_DEFAULT)
            if c['source'].get('kind')=='gap':
                if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise APIError('invalid_clip','Gap color must be a hex color.')
            else:
                if isinstance(color,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',color):color=COLOR_DEFAULT # phase-2 neutral legacy metadata
                if not isinstance(color,dict) or set(color)-set(COLOR_DEFAULT):raise APIError('invalid_clip','Use brightness, contrast, saturation and temperature for color.')
                color={**COLOR_DEFAULT,**color}
                for field,lo,hi in [('brightness',-.5,.5),('contrast',.5,2),('saturation',0,2),('temperature',-1,1)]:color[field]=number(color[field],lo,hi,'Color '+field)
            item['color']=copy.deepcopy(color)
            if c['source'].get('kind')=='gap' and a!=0:raise APIError('invalid_clip','Gap trim starts at zero.')
            item.update(self.audio_options(c,length(item),output['fps']))
            offset=number(c.get('audio_offset',0),-2,2,'Audio lead/lag')
            self.whole_frame(offset,output['fps'],'Audio lead/lag')
            available=(a if offset<0 else max(0,m['duration']-b))/item['speed']
            if offset and not m['audio']:raise APIError('invalid_audio_handle',f'Clip "{label}" ({item["id"]}) has no audio track. Reset audio offset to 0.')
            if offset and abs(offset)>available+.001:
                side='before the trim start' if offset<0 else 'after the trim end'
                raise APIError('invalid_audio_handle',f'Clip "{label}" ({item["id"]}): audio offset {offset:+.3f}s needs spare audio {side}; {available:.3f}s available. Reset audio offset to 0 or trim the clip to leave spare audio.')
            item['audio_offset']=offset
            if 'transition' in c:
                tr=c['transition']
                if not isinstance(tr,dict) or set(tr)!={'type','duration'} or tr['type'] not in ('cut','dissolve','fade'):raise APIError('invalid_transition','Choose cut, dissolve or fade with a duration in seconds.')
                d=number(tr['duration'],0,2,'Transition duration')
                if tr['type']=='cut':
                    if d!=0:raise APIError('invalid_transition','A cut has no overlap; set duration to zero.')
                else:
                    if not out['clips']:raise APIError('invalid_transition','The first clip cannot have an incoming transition.')
                    prev=out['clips'][-1];bound=min(2,length(item)/2,length(prev)/2)
                    if d<1/output['fps']-.001 or d>bound+.001:raise APIError('invalid_transition',f'Transitions need at least one frame and at most {bound:.3f}s (half of either neighboring clip).')
                    if abs(d*output['fps']-round(d*output['fps']))>.031:raise APIError('invalid_transition','Transition duration must use whole output frames.')
                item['transition']={'type':tr['type'],'duration':d}
            out['clips'].append(item)
        total=timeline_duration(out['clips'])
        if total>3600:raise APIError('timeline_limit','Keep the edit under one hour.')
        for a in audio:
            if not isinstance(a,dict) or set(a)-{'id','source','in','out','start','volume','label','lane',*AUDIO_FIELDS}:raise APIError('invalid_audio','Use the documented audio fields.')
            m,_=self.source(a.get('source'))
            if not m['audio']:raise APIError('invalid_audio','This source has no audio track.')
            left=number(a.get('in',0),0,m['duration']+.001,'Audio trim start',9);right=number(a.get('out',m['duration']),0,m['duration']+.001,'Audio trim end',9)
            start=number(a.get('start',0),0,max(total,0),'Audio start',9)
            if right-left<.04 or start>=total:raise APIError('invalid_audio','Place audio within the edit and give it a positive duration.')
            label=a.get('label',m.get('name','Audio'))
            if not isinstance(label,str) or len(label)>120:raise APIError('invalid_audio','Audio labels may contain up to 120 characters.')
            out['audio'].append(dict(id=identity(a),source=copy.deepcopy(a['source']),**{'in':left,'out':right},start=start,volume=number(a.get('volume',1),0,2,'Audio volume'),label=label))
            if a.get('lane','sfx') not in ('dialogue','music','sfx'):raise APIError('invalid_audio','Choose dialogue, music or sfx lane.')
            out['audio'][-1].update(self.audio_options(a,right-left,output['fps']),lane=a.get('lane','sfx'))
        for t in titles:
            if not isinstance(t,dict) or set(t)-{'id','text','start','end','position','size','color'}:raise APIError('invalid_title','Use the documented title fields.')
            text=t.get('text','');start=number(t.get('start',0),0,total,'Title start');end=number(t.get('end',0),0,total,'Title end')
            if not isinstance(text,str) or not text.strip() or len(text)>500 or any(ord(c)<32 and c!='\n' for c in text) or end<=start:raise APIError('invalid_title','Titles need 1–500 characters and a positive duration within the edit.')
            if t.get('position','bottom') not in ('top','center','bottom') or t.get('color','#ffffff') not in ('#ffffff','#aef0ca','#ffdb8a'):raise APIError('invalid_title','Choose a supported title position and color.')
            out['titles'].append(dict(id=identity(t),text=text,start=start,end=end,position=t.get('position','bottom'),size=number(t.get('size',36),16,96,'Title size'),color=t.get('color','#ffffff')))
        captions=data.get('captions',[])
        if not isinstance(captions,list) or len(captions)>2000:raise APIError('invalid_captions','Use at most 2000 caption cues.')
        for cue in captions:
            if not isinstance(cue,dict) or set(cue)-{'id','start','end','text','speaker'}:raise APIError('invalid_captions','Use id, start, end, text and optional speaker.')
            start=number(cue.get('start'),0,total,'Caption start');end=number(cue.get('end'),0,total,'Caption end')
            text=cue.get('text');speaker=cue.get('speaker')
            if end<=start or not isinstance(text,str) or not text.strip() or len(text)>2000 or any(ord(c)<32 and c!='\n' for c in text):raise APIError('invalid_captions','Captions need text and positive duration within the edit.')
            if speaker is not None and (not isinstance(speaker,str) or not 1<=len(speaker)<=80 or '\n' in speaker):raise APIError('invalid_captions','Speaker must be 1–80 characters on one line.')
            item=dict(id=identity(cue),start=start,end=end,text=text)
            if speaker:item['speaker']=speaker
            out['captions'].append(item)
        markers=data.get('markers',[])
        if not isinstance(markers,list) or len(markers)>500:raise APIError('invalid_marker','Use at most 500 markers.')
        from editing_tools import starts
        positions=starts(out['clips'])
        for marker in markers:
            if not isinstance(marker,dict) or set(marker)-{'id','time','label','note','color','clip_id','clip_time'}:raise APIError('invalid_marker','Use documented marker fields.')
            label=marker.get('label','Marker');note=marker.get('note','');color=marker.get('color','#aef0ca')
            if not isinstance(label,str) or len(label)>80 or not isinstance(note,str) or len(note)>2000 or color not in ('#aef0ca','#ffdb8a','#ff8888','#88bbff'):raise APIError('invalid_marker','Marker label ≤80, note ≤2000; choose a palette color.')
            item=dict(id=identity(marker),time=number(0 if marker.get('clip_id') else marker.get('time',0),0,total,'Marker time'),label=label,note=note,color=color)
            if marker.get('clip_id'):
                index=next((i for i,c in enumerate(out['clips']) if c['id']==marker['clip_id']),None)
                if index is None:raise APIError('invalid_marker','The marker anchor clip is missing.')
                local=number(marker.get('clip_time'),0,length(out['clips'][index]),'Marker clip_time')
                item.update(clip_id=marker['clip_id'],clip_time=local,time=round(positions[index]+local,3))
            elif 'clip_time' in marker:raise APIError('invalid_marker','clip_time needs a clip_id anchor.')
            out['markers'].append(item)
        return out
    @staticmethod
    def whole_frame(value,fps,label):
        if abs(value*fps-round(value*fps))>.031:raise APIError('invalid_timeline',label+' must use whole output frames.')

    def audio_options(self,item,duration,fps):
        values={}
        for k in ('audio_fade_in','audio_fade_out'):
            v=number(item.get(k,0),0,min(2,duration/2),k)
            self.whole_frame(v,fps,k);values[k]=v
        if type(item.get('normalize',False)) is not bool:raise APIError('invalid_audio','Normalize must be boolean.')
        values['normalize']=item.get('normalize',False)
        return values

    def tools_worker(self,identity):
        folder=self.app.storage/'exports'/identity;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            t=migrate_timeline(self.p.get(identity,'export')['snapshot']);total=timeline_duration(t['clips'])
            sources=[]
            for item in t['clips']+t['audio']:
                m,path=self.source(item['source']);sources.append((path,m))
            from editing_tools import output_size
            quality=self.p.get(identity,'export').get('quality','full');w,h=output_size(t,sources,quality);overlays=[]
            for i,title in enumerate(t['titles']):
                path=folder/f'title-{i}.png';self.title_image(title,w,h,path);overlays.append((path,title))
            style=t['output']['captions']
            if style['mode'] in ('burn_in','both'):
                events=sorted({0,total,*[cue[k] for cue in t['captions'] for k in ('start','end')]});entries=[]
                for i,(start,end) in enumerate(zip(events,events[1:])):
                    active=[cue for cue in t['captions'] if cue['start']<=start<cue['end']]
                    path=folder/f'title-caption-{i}.png'
                    if active:self.title_image({**style,'text':'\n'.join(wrapped(cue,style) for cue in active)},w,h,path)
                    else:Image.new('RGBA',(w,h)).save(path)
                    entries.extend([f"file '{path.name}'",f'duration {end-start:.6f}'])
                blank=folder/'title-caption-end.png';Image.new('RGBA',(w,h)).save(blank);entries.extend([f"file '{blank.name}'",'duration 0.1',f"file '{blank.name}'"])
                track=folder/'caption-track.ffconcat';track.write_text('\n'.join(entries)+'\n');overlays.append((track,dict(start=0,end=total,concat=True)))
            if style['mode'] in ('sidecar','both'):(folder/'captions.srt').write_text(to_srt(t['captions']))
            self.update(identity,status='rendering')
            if len(sources)+len(overlays)>4:
                from editing_batches import bounded_export
                bounded_export(self,identity,build_export(t,sources,overlays,quality,balanced=True),folder,total,t['output']['fps'])
            else:self.run(identity,build_export(t,sources,overlays,quality),folder,0,1,total)
            info=self.probe(folder/'export.mp4');(folder/'edit.json').write_text(json.dumps({**t,'export_files':['export.mp4','edit.json']+(['captions.srt'] if (folder/'captions.srt').exists() else [])},indent=2))
            for path in folder.iterdir():path.chmod(0o600)
            self.finish_render(identity)
            self.update(identity,status='done',progress=1,media=info,src='/api/exports/'+identity,download='/api/exports/'+identity+'/download')
        except InterruptedError:self.update(identity,status='cancelled',error=None)
        except Exception as error:self.update(identity,status='error',error=str(error) if isinstance(error,(APIError,ValueError)) else 'Export failed; original media and edit are intact.')
        finally:
            for path in folder.glob('title-*.png'):path.unlink(missing_ok=True)
            (folder/'caption-track.ffconcat').unlink(missing_ok=True)
            if self.p.get(identity,'export')['status']!='done':(folder/'export.mp4').unlink(missing_ok=True)

    def save(self,identity,data):
        if set(data)-{'expected_revision','title','clips','audio','titles','captions','markers','output'}:raise APIError('invalid_timeline','Use only the documented timeline fields.')
        old=migrate_timeline(self.p.get(identity,'timeline'));self.p.check(old,data)
        settings={k:data.get(k,old[k]) for k in ('title','clips','audio','titles','captions','markers','output')}
        if isinstance(settings['output'],dict):settings['output']={**old['output'],**settings['output']}
        values=self.validate(settings)
        if hasattr(self.app,'song_performance'):self.app.song_performance.validate_working_edit(old,values)
        with self.p.sql:return self.p.put('timeline',{**old,**values,'revision':old['revision']+1})
    def sources(self,pid,episode_id):
        root=self.p.summary(pid);family={pid:root['production']};active=[p for p in self.p.all('production') if not p.get('archived')]
        while True:
            children=[p for p in active if p.get('parent_production_id') in family and p['id'] not in family]
            if not children:break
            family.update({p['id']:p for p in children})
        takes={};images={};assets=[]
        for production_id,p in family.items():
            o=root if production_id==pid else self.p.summary(production_id)
            for s in o['shots']:
                # Group membership alone does not associate a quick production with
                # an episode. Keep that related work available in the story library.
                if production_id==pid and episode_id and s['episode_id']!=episode_id:continue
                common=dict(name=s['title'],shot_id=s['id'],shot_revision=s['revision'],production_id=p['id'],production_title=p['title'])
                for j in s['video_takes']:
                    if j['status']=='done' and j.get('video'):
                        takes[j['id']]=dict(common,source={'kind':'take','id':j['id']},video=True,selected=s.get('selected_video')==j['id'],created_at=j['created_at'],src='/api/video-media/'+j['id'])
                for j in s['image_takes']:
                    if j['status']!='done':continue
                    for a in j.get('outputs',[]):
                        images[a['id']]=dict(common,source={'kind':'image','id':a['id']},image=True,approved=bool(a.get('approved')),created_at=j['created_at'],src='/api/assets/'+a['id'])
                if s.get('approved_image'):
                    a=s['approved_image'];images.setdefault(a['id'],dict(common,source={'kind':'image','id':a['id']},image=True,approved=True,src='/api/assets/'+a['id']))
        for ref in self.app.named_library():
            if ref.get('archived'):continue
            for i,picture in enumerate(ref.get('images',[])):
                asset_id=picture.get('asset_id')
                if not asset_id:continue # URL-only references need an explicit local upload.
                try:m,path=self.app.asset(asset_id)
                except ValueError:continue
                if m.get('generated') and m.get('mock')!=self.app.mock:continue
                assets.append(dict(source={'kind':'image','id':asset_id},name=ref['title'],category=ref.get('category'),handle=ref.get('handle'),image=True,approved=not m.get('generated') or bool(m.get('approved')),src='/api/assets/'+asset_id,reference_id=ref['id'],image_index=i))
        order=lambda items:sorted(items,key=lambda m:m.get('created_at',0),reverse=True)
        uploads=[{**m,'source':{'kind':'upload','id':m['id']},'src':'/api/edit-media/'+m['id']} for m in self.p.all('edit-media')]
        # Shared original uploads and captured frames also belong to the workspace
        # media shelf. Generated candidates remain in their production's Images.
        uploads.extend({**m,'image':True,'approved':True,'source':{'kind':'image','id':m['id']},'src':'/api/assets/'+m['id']} for m in self.app.library() if not m.get('generated'))
        return {'takes':order(takes.values()),'images':order(images.values()),'assets':assets,'uploads':uploads, 'scope':{'production_count':len(family),'title':root['production']['title'],'episode_id':episode_id,'related_work_all_episodes':True}}
    def export(self,identity,data,key,render_into=None):
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',key):raise APIError('idempotency_key_required','Supply a unique Idempotency-Key for this export.')
        if not self.ffmpeg:raise APIError('editor_unavailable','Install FFmpeg to export your edit.',503)
        if data.get('quality','full') not in ('draft','full'):raise APIError('invalid_output','Choose draft or full export quality.')
        timeline=self.p.get(identity,'timeline');self.p.check(timeline,data);validated=self.validate({k:migrate_timeline(timeline)[k] for k in ('title','clips','audio','titles','captions','markers','output')})
        if hasattr(self.app,'song_performance'):self.app.song_performance.validate_working_edit(timeline,validated)
        if not timeline['clips']:raise APIError('empty_timeline','Add at least one video or image clip before exporting.')
        with self.lock:
            if key:
                old=next((j for j in self.p.all('export') if j.get('key')==key),None)
                if old:
                    if old['timeline_id']!=identity or old['snapshot']['revision']!=timeline['revision'] or old.get('quality','full')!=data.get('quality','full') or old.get('render_into')!=render_into:raise APIError('idempotency_conflict','Use a new idempotency key for a different edit.',409)
                    return old
            if any(j['status'] in ('queued','rendering') for j in self.p.all('export')):raise APIError('export_busy','Wait for the current export or cancel it.',409)
            with self.p.sql:j=self.p.new('export',timeline_id=identity,snapshot=copy.deepcopy(timeline),status='queued',progress=0,error=None,key=key,quality=data.get('quality','full'),render_into=render_into)
            if timeline['output']['resolution']=='source':
                dims=[(m.get('width'),m.get('height')) for c in timeline['clips'] for m,_ in [self.source(c['source'])] if m.get('video') and c['source'].get('kind')!='gap']
                if len(set(dims))>1:
                    with self.p.sql:j['warnings']=['Source sizes differ; the first video sets the export size.'];self.p.put('export',j)
            self.cancellations[j['id']]=threading.Event()
            self.app.spawn(self.worker,j['id'])
            return j
    def update(self,identity,**values):
        with self.app.agent.lock,self.p.sql:
            j=self.p.get(identity,'export');j.update(values);self.p.put('export',j)
    def run(self,identity,args,folder,progress_start,progress_span,duration):
        event=self.cancellations[identity]
        if event.is_set():raise InterruptedError()
        p=subprocess.Popen([self.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-threads','2','-filter_complex_threads','1',*args,'-progress','pipe:1'],cwd=folder,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        with self.lock:self.processes[identity]=p
        last=0;tail=deque(maxlen=40)
        def drain():
            for line in p.stderr:tail.append(line.rstrip()[:2000])
        reader=threading.Thread(target=drain,daemon=True);reader.start()
        monitor_stop=threading.Event();peak=[0]
        def monitor():
            while not monitor_stop.is_set():
                try:
                    rss=subprocess.check_output(['ps','-o','rss=','-p',str(p.pid)],stderr=subprocess.DEVNULL,text=True,timeout=2).strip()
                    if rss:peak[0]=max(peak[0],int(rss))
                except (OSError,ValueError,subprocess.SubprocessError):pass
                monitor_stop.wait(.05)
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        try:
            for line in p.stdout:
                if event.is_set():p.terminate();raise InterruptedError()
                if line.startswith('out_time_us='):
                    try:v=min(1,float(line.strip().split('=',1)[1])/1e6/duration)
                    except ValueError:continue
                    if time.monotonic()-last>.4:self.update(identity,progress=round(progress_start+v*progress_span,3));last=time.monotonic()
            if p.wait(timeout=15)!=0:
                if event.is_set():raise InterruptedError()
                reader.join(timeout=2);detail='\n'.join(tail)
                self.update(identity,ffmpeg_stderr=detail,ffmpeg_exit_code=p.returncode)
                raise ValueError('FFmpeg export failed:\n'+detail)
        finally:
            if p.poll() is None:p.kill()
            p.wait();reader.join(timeout=2);monitor_stop.set();watcher.join(timeout=3);p.stdout.close();p.stderr.close();self.processes.pop(identity,None)
            old=self.p.get(identity,'export').get('ffmpeg_peak_rss_kib',0)
            if peak[0]>old:self.update(identity,ffmpeg_peak_rss_kib=peak[0])
    def worker(self,identity):
        export_job=self.p.get(identity,'export');snapshot=migrate_timeline(export_job['snapshot'])
        if len(snapshot['clips'])+len(snapshot['audio'])+len(snapshot['titles'])>4 or export_job.get('quality')=='draft' or snapshot['output']['resolution'] in ('480p','source') or snapshot['output']['captions']['mode']!='off' or any(c.get('source',{}).get('kind')=='gap' or any(c.get(k,v)!=v for k,v in PICTURE_FIELDS.items()) for c in snapshot['clips']) or snapshot['output']['cut_audio_crossfade_frames'] or snapshot['output']['loudness_target_lufs'] is not None or snapshot['output']['ducking']['enabled'] or any(c.get('audio_offset') or any(c.get(k) for k in AUDIO_FIELDS) or c.get('lane','sfx')!='sfx' for c in snapshot['clips']+snapshot['audio']):return self.tools_worker(identity)
        folder=self.app.storage/'exports'/identity;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            t=self.p.get(identity,'export')['snapshot'];total=timeline_duration(t['clips']);w,h=RATIOS[t['output']['ratio']]
            if t['output']['resolution']=='1080p':w=int(w*1.5);h=int(h*1.5)
            fps=t['output']['fps'];self.update(identity,status='rendering')
            for i,c in enumerate(t['clips']):
                m,path=self.source(c['source']);duration=c['out']-c['in']
                args=(['-loop','1','-framerate',str(fps),'-i',str(path)] if m.get('image') else ['-ss',str(c['in']),'-i',str(path)])
                if not m['audio']:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                args+=['-map','0:v:0','-map','0:a:0' if m['audio'] else '1:a:0','-t',str(duration),'-vf',f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p','-af',f'aresample=48000,volume={c["volume"]},apad','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-ar','48000','-ac','2',f'clip-{i}.mp4']
                self.run(identity,args,folder,i/len(t['clips'])*.45,.45/len(t['clips']),duration)
            # Render only short boundary pieces, keeping memory bounded even for
            # long edits. Interior pieces and transitions are concatenated in order.
            pieces=[];has_transitions=any(c.get('transition',{}).get('duration',0)>0 for c in t['clips'])
            for i,c in enumerate(t['clips']):
                incoming=c.get('transition',{}).get('duration',0)
                outgoing=t['clips'][i+1].get('transition',{}).get('duration',0) if i+1<len(t['clips']) else 0
                if incoming:
                    prev=t['clips'][i-1];tail=prev['out']-prev['in']-incoming;name=f'trans-{i}.mp4'
                    effect='fade' if c['transition']['type']=='dissolve' else 'fadeblack'
                    # xfade requires both a common time base and an explicit
                    # constant frame rate, even for our normalized MP4 inputs.
                    # Apply fps last: timestamp filters can clear frame-rate
                    # metadata in FFmpeg 7.x before xfade checks its inputs.
                    filters=f'[0:v]settb=AVTB,setpts=PTS-STARTPTS,fps={fps}[v0];[1:v]settb=AVTB,setpts=PTS-STARTPTS,fps={fps}[v1];[v0][v1]xfade=transition={effect}:duration={incoming}:offset=0[v];[0:a][1:a]acrossfade=d={incoming}:c1=tri:c2=tri[a]'
                    args=['-ss',str(tail),'-i',f'clip-{i-1}.mp4','-i',f'clip-{i}.mp4','-filter_complex',filters,'-map','[v]','-map','[a]','-t',str(incoming),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',name]
                    self.run(identity,args,folder,.45+i/len(t['clips'])*.25,.125/len(t['clips']),incoming);pieces.append(name)
                length=c['out']-c['in']-incoming-outgoing
                if length>.001:
                    name=f'piece-{i}.mp4' if has_transitions else f'clip-{i}.mp4'
                    if has_transitions:
                        args=['-ss',str(incoming),'-i',f'clip-{i}.mp4','-t',str(length),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',name]
                        self.run(identity,args,folder,.45+i/len(t['clips'])*.25,.125/len(t['clips']),length)
                    pieces.append(name)
            (folder/'clips.txt').write_text(''.join(f"file '{name}'\n" for name in pieces))
            args=['-f','concat','-safe','1','-i','clips.txt'];filters=[];mix=['[0:a]']
            for i,a in enumerate(t['audio'],1):
                _,path=self.source(a['source']);args+=['-ss',str(a['in']),'-t',str(a['out']-a['in']),'-i',str(path)]
                filters.append(f'[{i}:a]aresample=48000,aformat=channel_layouts=stereo,volume={a["volume"]},adelay={round(a["start"]*1000)}:all=1[a{i}]');mix.append(f'[a{i}]')
            filters.append(''.join(mix)+f'amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95:latency=1[aout]')
            video='[0:v]'
            for i,title in enumerate(t['titles']):
                # Rasterize literal text ourselves; no drawtext support or filter
                # escaping is needed, and title text can never become a command.
                self.title_image(title,w,h,folder/f'title-{i}.png')
                args+=['-loop','1','-i',f'title-{i}.png']
                input_index=1+len(t['audio'])+i
                filters.append(video+f"[{input_index}:v]overlay=0:0:enable='gte(t,{title['start']})*lt(t,{title['end']})':shortest=1[v{i}]");video=f'[v{i}]'
            args+=['-filter_complex',';'.join(filters),'-map',video if t['titles'] else '0:v:0','-map','[aout]','-t',str(total),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','export.mp4']
            self.run(identity,args,folder,.7,.3,total)
            info=self.probe(folder/'export.mp4');(folder/'edit.json').write_text(json.dumps(t,indent=2))
            for p in folder.iterdir():p.chmod(0o600)
            with self.app.agent.lock:
                if self.cancellations[identity].is_set():raise InterruptedError()
                self.finish_render(identity)
            self.update(identity,status='done',progress=1,media=info,src='/api/exports/'+identity,download='/api/exports/'+identity+'/download')
        except InterruptedError:self.update(identity,status='cancelled',error=None)
        except Exception as exc:self.update(identity,status='error',error=str(exc) if isinstance(exc,(APIError,ValueError)) else 'Export failed. Your saved edit and original media are intact.')
        finally:
            for p in folder.glob('clip-*.mp4'):p.unlink(missing_ok=True)
            for pattern in ('piece-*.mp4','trans-*.mp4'):
                for p in folder.glob(pattern):p.unlink(missing_ok=True)
            for p in folder.glob('title-*.png'):p.unlink(missing_ok=True)
            (folder/'clips.txt').unlink(missing_ok=True)
            if self.p.get(identity,'export')['status']!='done':(folder/'export.mp4').unlink(missing_ok=True)
    def file(self,identity,manifest=False):
        j=self.p.get(identity,'export')
        if j['status']!='done':raise APIError('export_not_ready','Wait for the export to finish.',409)
        path=self.app.storage/'exports'/identity/('edit.json' if manifest else 'export.mp4')
        if not path.exists():raise APIError('missing_export','The export file is missing.',404)
        return path
    def title_image(self,title,w,h,path):
        font_path=next((p for p in ('/System/Library/Fonts/Supplemental/Arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(p).exists()),None)
        size=round(title['size']*h/720);font=ImageFont.truetype(font_path,size) if font_path else ImageFont.load_default(size=size)
        image=Image.new('RGBA',(w,h));draw=ImageDraw.Draw(image);lines=[]
        for paragraph in title['text'].split('\n'):
            line=''
            for char in paragraph:
                if line and draw.textlength(line+char,font=font)>w*.88:lines.append(line);line=''
                line+=char
            lines.append(line)
        text='\n'.join(lines);spacing=round(size*.15);bounds=draw.multiline_textbbox((0,0),text,font=font,spacing=spacing);tw,th=bounds[2]-bounds[0],bounds[3]-bounds[1]
        x=(w-tw)/2;y={'top':h*.08,'center':(h-th)/2,'bottom':h*.88-th}[title['position']]
        draw.rectangle((x-10,y-8,x+tw+10,y+th+8),fill=(0,0,0,140));draw.multiline_text((x-bounds[0],y-bounds[1]),text,font=font,fill=title['color'],spacing=spacing,align='center');image.save(path)
    def preview(self,identity,data):
        if set(data)-{'expected_revision','quality'} or 'expected_revision' not in data or data.get('quality','full') not in ('draft','full'):raise APIError('invalid_preview','Supply expected_revision and optional draft/full quality.')
        timeline=self.p.get(identity,'timeline');self.p.check(timeline,data)
        existing=next((j for j in reversed(self.p.all('export')) if j['timeline_id']==identity and j['snapshot']['revision']==timeline['revision'] and j.get('quality','full')==data.get('quality','full') and j['status'] in ('queued','rendering','done')),None)
        return existing or self.export(identity,data,'preview-'+uuid.uuid4().hex)

    def preview_frame(self,identity,data):
        if set(data)!={'timestamp_s','expected_revision'}:raise APIError('invalid_preview','Supply timestamp_s and the exported timeline revision.')
        job=self.p.get(identity,'export');snapshot=job['snapshot']
        if type(data['expected_revision']) is not int or data['expected_revision']!=snapshot['revision']:raise APIError('revision_conflict','This preview belongs to another timeline revision.',409)
        total=timeline_duration(snapshot['clips']);timestamp=number(data['timestamp_s'],0,total,'Preview timestamp')
        path=self.file(identity)
        if not self.ffmpeg:raise APIError('editor_unavailable','Install FFmpeg to preview the edit.',503)
        timestamp=min(timestamp,max(0,total-1/snapshot['output']['fps']))
        try:result=subprocess.run([self.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-i',str(path),'-ss',str(timestamp),'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        except (OSError,subprocess.TimeoutExpired):raise APIError('preview_failed','The composite preview could not be extracted. Retry the local preview.',503) from None
        if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
            detail='\n'.join(result.stderr.decode(errors='replace').splitlines()[-40:])
            self.update(identity,frame_ffmpeg_stderr=detail)
            raise APIError('preview_failed','Frame extraction failed:\n'+detail,503)
        return result.stdout,'image/png'

    def revisions(self,identity,revision=None):
        from production_studio import OWNER
        self.p.get(identity,'timeline')
        rows=[json.loads(row[0]) for row in self.p.sql.execute('SELECT body FROM versions WHERE id=? AND owner=? ORDER BY revision DESC',(identity,OWNER))]
        if revision is not None:
            value=next((row for row in rows if row['revision']==revision),None)
            if value is None:raise APIError('not_found','Timeline revision not found.',404)
            return migrate_timeline(value)
        return [dict(revision=row['revision'],created_at=row.get('updated_at',row['created_at']),clip_count=len(row['clips']),duration=timeline_duration(row['clips']),title=row['title']) for row in rows]

    def restore_revision(self,identity,revision,data):
        if set(data)!={'expected_revision'}:raise APIError('invalid_timeline','Supply expected_revision.')
        old=self.revisions(identity,revision)
        return self.save(identity,{**{k:old[k] for k in ('title','clips','audio','titles','captions','markers','output')},'expected_revision':data['expected_revision']})

    def transcription_model(self):
        saved=next(iter(self.p.all('editor-transcription')),{}).get('local_transcription_model')
        from user_data import relocated_path
        return relocated_path(saved or self.app.agent.config.get('local_transcription_model') or self.app.storage/'transcription-model')

    def transcription_settings(self,data=None):
        old=next(iter(self.p.all('editor-transcription')),None)
        if data is not None:
            if not isinstance(data,dict) or set(data)!={'expected_revision','local_transcription_model'}:raise APIError('invalid_transcription','Supply expected_revision and local_transcription_model (absolute folder path, or null for default).')
            revision=old['revision'] if old else 0
            if type(data['expected_revision']) is not int or data['expected_revision']!=revision:raise APIError('revision_conflict','Transcription settings changed. Refresh before saving.',409)
            value=data['local_transcription_model']
            if value is not None:
                if not isinstance(value,str) or not value.strip() or len(value)>2000 or any(ord(c)<32 for c in value) or not Path(value).expanduser().is_absolute():raise APIError('invalid_transcription','Choose an absolute local model folder path, or null for the default.')
                value=str(Path(value).expanduser().resolve())
            with self.p.sql:
                old=self.p.put('editor-transcription',{**old,'revision':revision+1,'local_transcription_model':value}) if old else self.p.new('editor-transcription',local_transcription_model=value)
        model=self.transcription_model();engine=importlib.util.find_spec('faster_whisper') is not None
        present=all((model/name).is_file() for name in ('model.bin','config.json','tokenizer.json'))
        available=callable(getattr(self,'transcriber',None)) or engine and present
        message='Local transcription is ready. No model downloads.' if available else 'Install the optional transcription dependencies and select a complete local model folder, or import an SRT instead. No model is downloaded.'
        return dict(revision=old['revision'] if old else 0,local_transcription_model=str(model),engine_available=engine,model_present=present,available=available,message=message)

    def transcriber_available(self):return self.transcription_settings()['available']

    def transcribe(self,identity,data):
        if not isinstance(data,dict) or set(data)!={'expected_revision'}:raise APIError('invalid_captions','Supply only expected_revision.')
        timeline=migrate_timeline(self.p.get(identity,'timeline'));self.p.check(timeline,data)
        if not self.transcriber_available():raise APIError('transcriber_unavailable','No local transcriber and cached model are available. Import an SRT instead; no model is downloaded.',503)
        with self.p.sql:job=self.p.new('caption-job',timeline_id=identity,snapshot=timeline,status='queued',local_transcription_model=str(self.transcription_model()))
        self.app.spawn(self.transcribe_worker,job['id']);return self.p.get(job['id'],'caption-job')

    def transcribe_worker(self,identity):
        from editing_tools import starts
        job=self.p.get(identity,'caption-job');t=job['snapshot'];cues=[]
        try:
            hook=getattr(self,'transcriber',None)
            if hook is None:
                from faster_whisper import WhisperModel
                model=WhisperModel(job.get('local_transcription_model',str(self.transcription_model())),local_files_only=True,device='cpu',compute_type='int8')
                def hook(path):
                    segments,_=model.transcribe(str(path));return [dict(start=s.start,end=s.end,text=s.text) for s in segments]
            positions=starts(t['clips']);total=timeline_duration(t['clips'])
            tracks=[(c,positions[i]+c.get('audio_offset',0)+c.get('hold_start',0)) for i,c in enumerate(t['clips'])]+[(a,a['start']) for a in t['audio'] if a.get('lane')=='dialogue']
            for item,at in tracks:
                m,path=self.source(item['source'])
                if not m.get('audio') or item.get('speed_audio')=='mute' or not item.get('volume',1):continue
                speed=item.get('speed',1);left=item['in']+min(0,item.get('audio_offset',0))*speed;right=item['out']+max(0,item.get('audio_offset',0))*speed
                for seg in hook(path):
                    start=max(0,at+(max(left,seg['start'])-left)/speed);end=min(total,at+(min(right,seg['end'])-left)/speed)
                    if end>start:cues.append(dict(id=uuid.uuid4().hex,start=round(start,3),end=round(end,3),text=seg['text'].strip(),**({'speaker':seg['speaker']} if seg.get('speaker') else {})))
            cues.sort(key=lambda c:c['start']);self.save(t['id'],dict(expected_revision=t['revision'],captions=cues))
            with self.p.sql:job.update(status='done',caption_count=len(cues));self.p.put('caption-job',job)
        except Exception as error:
            with self.p.sql:job.update(status='error',error=('Local transcription failed: '+str(error)+'. Import an SRT instead.') if isinstance(error,ValueError) else 'Local transcription failed. Check the offline model or import an SRT instead.');self.p.put('caption-job',job)

    def render_timeline(self,identity,data,key):
        if set(data)!={'expected_revision','parent_timeline_id','expected_parent_revision'}:raise APIError('invalid_render','Supply expected_revision, parent_timeline_id and expected_parent_revision.')
        prior=next((j for j in self.p.all('export') if j.get('key')==key),None)
        if prior:
            wanted=dict(timeline_id=data['parent_timeline_id'],expected_revision=data['expected_parent_revision'])
            if prior['timeline_id']!=identity or prior['snapshot']['revision']!=data['expected_revision'] or prior.get('render_into')!=wanted:raise APIError('idempotency_conflict','Use a new idempotency key for a different scene render.',409)
            return prior
        child=self.p.get(identity,'timeline');self.p.check(child,data)
        parent=self.p.get(data['parent_timeline_id'],'timeline');self.p.check(parent,dict(expected_revision=data['expected_parent_revision']))
        if not child.get('story_scene_id') or parent.get('story_scene_id') or (child['production_id'],child['episode_id'])!=(parent['production_id'],parent['episode_id']):raise APIError('invalid_parent','Render a scene timeline into an episode timeline in the same production and episode.')
        if child['output']['fps']!=parent['output']['fps']:raise APIError('invalid_output','Scene and episode frame rates must match before render-and-replace.')
        return self.export(identity,dict(expected_revision=data['expected_revision']),key,render_into=dict(timeline_id=parent['id'],expected_revision=parent['revision']))

    def finish_render(self,identity):
        if self.cancellations[identity].is_set():raise InterruptedError()
        job=self.p.get(identity,'export');target=job.get('render_into')
        if not target:return
        # Never overwrite an edit made while FFmpeg was running. Keep the export
        # available even if insertion conflicts; retry with current revisions.
        with self.app.agent.lock:
            try:
                parent=self.p.get(target['timeline_id'],'timeline');self.p.check(parent,target)
                source=job['snapshot'];path=self.app.storage/'exports'/identity/'export.mp4';info=self.probe(path)
                link=dict(timeline_id=source['id'],revision=source['revision'],export_id=identity)
                media_id=uuid.uuid4().hex;dest=self.app.storage/'edit-media'/f'{media_id}.mp4';dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copyfile(path,dest);dest.chmod(0o600)
                try:
                    with self.p.sql:
                        self.p.put('edit-media',dict(id=media_id,revision=1,created_at=time.time(),name=source['title'][:120],ext='mp4',mime='video/mp4',bytes=dest.stat().st_size,render_link=link,**info))
                        clips=copy.deepcopy(parent['clips']);index=next((i for i,c in enumerate(clips) if c.get('render_link',{}).get('timeline_id')==source['id']),None)
                        old=clips[index] if index is not None else {}
                        clip=dict(id=old.get('id',uuid.uuid4().hex),source=dict(kind='upload',id=media_id),**{'in':0,'out':timeline_duration(source['clips'])},volume=old.get('volume',1),label=source['title'][:120],transition=old.get('transition',dict(type='cut',duration=0)))
                        if index is None:clips.append(clip)
                        else:clips[index]=clip
                        result=self.save(parent['id'],dict(expected_revision=parent['revision'],clips=clips))
                        self.update(identity,render_status='inserted',parent_timeline_id=parent['id'],parent_revision=result['revision'],rendered_clip_id=clip['id'])
                except Exception:
                    dest.unlink(missing_ok=True);raise
            except (APIError,ValueError) as error:self.update(identity,render_status='error',render_error=str(error))

    def timelines(self):
        rows=self.p.all('timeline');seen=set();result=[]
        for row in rows:
            scope=(row['production_id'],row['episode_id'],row.get('story_scene_id'))
            primary=row.get('primary',scope not in seen);seen.add(scope)
            result.append({**migrate_timeline(row),'primary':primary})
        return result

    def dispatch(self,method,parts,data,key):
        if parts==['export-summaries'] and method=='GET':
            rows=self.p.sql.execute("SELECT json_remove(body,'$.snapshot.clips','$.snapshot.audio','$.snapshot.titles','$.snapshot.captions','$.snapshot.markers') FROM records WHERE kind='export' AND owner=?",('local-user',))
            jobs=sorted((json.loads(row[0]) for row in rows),key=lambda j:j['created_at'],reverse=True);seen=set()
            for job in jobs:
                delivery=job.get('quality','full')!='draft' and job['status']=='done' and job['timeline_id'] not in seen
                job['latest_delivery']=delivery
                if delivery:seen.add(job['timeline_id'])
            return 200,jobs
        if parts==['transcription'] and method=='GET':return 200,self.transcription_settings()
        if parts==['transcription'] and method=='PUT':return 200,self.transcription_settings(data)
        if len(parts)==3 and parts[0]=='timelines' and parts[2]=='render' and method=='POST':return 202,self.render_timeline(parts[1],data,key)
        if parts==['timelines'] and method=='GET':return 200,self.timelines()
        if len(parts)==3 and parts[0]=='timelines' and parts[2]=='duplicate' and method=='POST':
            old=self.p.get(parts[1],'timeline');self.p.check(old,data)
            if set(data)-{'expected_revision','title'} or not isinstance(data.get('title',old['title']+' copy'),str) or not 1<=len(data.get('title',old['title']+' copy'))<=120:raise APIError('invalid_title','Use a title up to 120 characters.')
            fields={k:v for k,v in migrate_timeline(old).items() if k not in ('id','revision','created_at','updated_at')}
            fields.update(title=data.get('title',old['title']+' copy'),primary=False,duplicated_from=old['id'])
            with self.p.sql:return 201,self.p.new('timeline',**fields)
        if len(parts)==3 and parts[0]=='timelines' and parts[2]=='primary' and method=='POST':
            old=self.p.get(parts[1],'timeline');self.p.check(old,data)
            if set(data)!={'expected_revision'}:raise APIError('invalid_timeline','Supply expected_revision.')
            with self.p.sql:
                for row in self.p.all('timeline'):
                    if (row['production_id'],row['episode_id'],row.get('story_scene_id'))==(old['production_id'],old['episode_id'],old.get('story_scene_id')):
                        row.update(primary=row['id']==old['id'],revision=row['revision']+1);self.p.put('timeline',row)
            return 200,self.p.get(old['id'],'timeline')
        if parts==['takes','select'] and method=='POST':
            if set(data)!={'shot_id','take_id','expected_shot_revision'}:raise APIError('invalid_take','Supply shot_id, take_id and expected_shot_revision.')
            if not isinstance(data['shot_id'],str) or (data['take_id'] is not None and not isinstance(data['take_id'],str)) or type(data['expected_shot_revision']) is not int:raise APIError('invalid_take','Use text shot/take IDs and an integer shot revision.')
            return self.p.dispatch('POST',['shots',data['shot_id'],'select-take'],dict(expected_revision=data['expected_shot_revision'],kind='video',id=data['take_id']))
        if len(parts)==3 and parts[0]=='timelines' and parts[2]=='revisions' and method=='GET':return 200,self.revisions(parts[1])
        if len(parts)==4 and parts[0]=='timelines' and parts[2]=='revisions' and method=='GET':
            if not parts[3].isdigit():raise APIError('invalid_revision','Use an integer revision.')
            return 200,self.revisions(parts[1],int(parts[3]))
        if len(parts)==5 and parts[0]=='timelines' and parts[2]=='revisions' and parts[4]=='restore' and method=='POST':
            if not parts[3].isdigit():raise APIError('invalid_revision','Use an integer revision.')
            return 200,self.restore_revision(parts[1],int(parts[3]),data)
        if len(parts)==4 and parts[0]=='timelines' and parts[2:]==['captions','transcribe'] and method=='POST':return 202,self.transcribe(parts[1],data)
        if len(parts)==4 and parts[0]=='timelines' and parts[2:]==['captions','import'] and method=='POST':
            if set(data)!={'expected_revision','srt'}:raise APIError('invalid_captions','Supply expected_revision and srt.')
            try:cues=from_srt(data.get('srt'))
            except ValueError as error:raise APIError('invalid_captions',str(error)) from None
            return 200,self.save(parts[1],dict(expected_revision=data.get('expected_revision'),captions=cues))
        if len(parts)==2 and parts[0]=='caption-jobs' and method=='GET':return 200,self.p.get(parts[1],'caption-job')
        if len(parts)==3 and parts[0]=='exports' and parts[2]=='captions.srt' and method=='GET':
            self.file(parts[1]);path=self.app.storage/'exports'/parts[1]/'captions.srt'
            if not path.exists():raise APIError('not_found','This export has no caption sidecar.',404)
            return 200,(path.read_bytes(),'application/x-subrip')
        if len(parts)==3 and parts[0]=='timelines' and parts[2]=='preview' and method=='POST':return 202,self.preview(parts[1],data)
        if len(parts)==3 and parts[0]=='exports' and parts[2]=='frame' and method=='POST':return 200,self.preview_frame(parts[1],data)
        if method=='GET' and parts==['schema']:return 200,{'version':3,'routes':['timelines','timelines/{id}/duplicate','timelines/{id}/primary','timelines/{id}/render','timelines/open','transcription','timelines/{id}','sources','inspect','media','exports','exports/{id}','exports/{id}/cancel','timelines/{id}/preview','exports/{id}/frame','timelines/{id}/captions/import','timelines/{id}/captions/transcribe','caption-jobs/{id}','exports/{id}/captions.srt','takes/select','timelines/{id}/revisions','timelines/{id}/revisions/{n}','timelines/{id}/revisions/{n}/restore'],'limits':{'clips':120,'audio':200,'titles':100,'captions':2000,'markers':500,'upload_mb':64,'duration_seconds':3600},'output':{'ratios':list(RATIOS),'resolutions':['480p','720p','1080p','source'],'fps':[24,30],**copy.deepcopy(OUTPUT_FIELDS),'cut_audio_crossfade_frames':{'default_new':2,'default_v2':0,'range':[0,12]},'loudness_target_lufs':{'default':None,'range':[-30,-10]},'ducking':DUCKING},'fields':{'clip':['id','source','in','out','volume','label','shot_id','transition','audio_offset','render_link',*AUDIO_FIELDS,*PICTURE_FIELDS],'audio':['id','source','in','out','start','volume','label','lane',*AUDIO_FIELDS],'title':['id','text','start','end','position','size','color'],'caption':['id','start','end','text','speaker'],'marker':['id','time','label','note','color','clip_id','clip_time']},'source':{'kind':['take','upload','image','gap'],'id':'workspace media ID'},'images':{'default_seconds':3,'in':0,'out':'display duration from 0.04 to 3600 seconds','generated':'approval required'},'transition':{'type':['cut','dissolve','fade'],'duration':'incoming overlap in seconds; whole output frames; 0 for cut, at least one frame and at most 2s or half either adjacent clip; first clip must be cut'},'timing':'Clip starts are cumulative lengths minus incoming overlaps. Split by replacing a clip with two trimmed copies with unique IDs; the second uses cut.', 'source_scope':'Selected episode plus active grouped child productions; assets and uploads from this workspace.', 'export':{'expected_revision':'required','idempotency_key':'send Idempotency-Key header'},'markers':{'palette':['#aef0ca','#ffdb8a','#ff8888','#88bbff'],'max_label':80,'max_note':2000,'anchor':'clip_id and clip_time; time recomputed on save'},'color':{'defaults':COLOR_DEFAULT,'brightness':[-.5,.5],'contrast':[.5,2],'saturation':[0,2],'temperature':[-1,1],'temperature_filter':'colorbalance red/blue approximation'},'picture_tools':{'defaults':PICTURE_FIELDS,'speed':[.25,4],'holds':'0–10 whole-frame seconds','crop':'fractions 0–1; w/h >= .1; must fit inside source','zoom':'scale 1–3, x/y 0–1','gap':'source {kind:gap}, in 0, out .04–60; hex color'},'audio_tools':{'audio_fade_in':'0 to min(2, half item duration), whole frames; default 0','audio_fade_out':'same as fade in','audio_offset':'clip only, -2 to 2 whole-frame seconds, default 0; source handles required','normalize':False,'lane':['dialogue','music','sfx'],'ducking_algorithm':'normalize stems before bounded dry/wet sidechain ducking; no post-duck loudness boost','ducking_ranges':{'amount_db':[0,24],'attack_ms':[5,500],'release_ms':[50,2000]}},'captions':{'style':CAPTION_STYLE,'max_cues':2000,'transcriber_available':self.transcriber_available(),'text_limit':2000},'inspect_fields':['duration','video','audio','image','width','height','loudness_lufs'],'preview_quality':['draft','full'],'ffmpeg_available':bool(self.ffmpeg and self.ffprobe)}
        if method=='POST' and parts==['timelines','open']:return 200,self.timeline(data.get('production_id'),data.get('episode_id'),data.get('story_scene_id'))
        if method=='POST' and parts==['sources']:return 200,self.sources(data.get('production_id'),data.get('episode_id'))
        if method=='POST' and parts==['inspect']:
            return 200,self.inspect(data)
        if method=='GET' and parts==['media']:return 200,self.p.all('edit-media')
        if method=='POST' and parts==['media']:return 201,self.upload(data)
        if len(parts)==2 and parts[0]=='timelines':
            if method=='GET':return 200,migrate_timeline(self.p.get(parts[1],'timeline'))
            if method=='PUT':return 200,self.save(parts[1],data)
        if method=='POST' and parts==['exports']:return 202,self.export(data.get('timeline_id'),data,key)
        if method=='GET' and parts==['exports']:
            jobs=sorted(self.p.all('export'),key=lambda j:j['created_at'],reverse=True);seen=set()
            for job in jobs:
                delivery=job.get('quality','full')!='draft' and job['status']=='done' and job['timeline_id'] not in seen
                job['latest_delivery']=delivery
                if delivery:seen.add(job['timeline_id'])
            return 200,jobs
        if len(parts)==2 and parts[0]=='exports' and method=='GET':return 200,self.p.get(parts[1],'export')
        if len(parts)==3 and parts[0]=='exports' and parts[2] in ('download','manifest') and method=='GET':
            manifest=parts[2]=='manifest';path=self.file(parts[1],manifest);return (200,json.loads(path.read_text())) if manifest else (200,(path.read_bytes(),'video/mp4'))
        if len(parts)==3 and parts[0]=='media' and parts[2]=='download' and method=='GET':
            m,path=self.media_file(parts[1]);return 200,(path.read_bytes(),m['mime'])
        if len(parts)==3 and parts[0]=='exports' and parts[2]=='cancel' and method=='POST':
            j=self.p.get(parts[1],'export')
            if j['status'] in ('queued','rendering'):
                self.cancellations[parts[1]].set();p=self.processes.get(parts[1])
                if p:p.terminate()
            return 200,self.p.get(parts[1],'export')
        raise APIError('not_found','Editing route not found.',404)
