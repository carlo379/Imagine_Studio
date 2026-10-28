"""Pure editor v3 defaults, timing and FFmpeg graphs. No provider calls."""
import copy
from editing_captions import CAPTION_STYLE

DUCKING = dict(enabled=False, amount_db=10, attack_ms=80, release_ms=400)
COLOR_DEFAULT=dict(brightness=0,contrast=1,saturation=1,temperature=0)
PICTURE_FIELDS=dict(flip_h=False,flip_v=False,crop=dict(x=0,y=0,w=1,h=1),zoom=dict(scale=1,x=.5,y=.5),speed=1,speed_audio='preserve_pitch',hold_start=0,hold_end=0,color=COLOR_DEFAULT)
AUDIO_FIELDS = dict(audio_fade_in=0, audio_fade_out=0, normalize=False)
OUTPUT_FIELDS = dict(cut_audio_crossfade_frames=0, loudness_target_lufs=None, ducking=DUCKING,captions=CAPTION_STYLE)


def migrate_timeline(value):
    t = copy.deepcopy(value)
    t.setdefault('schema_version', 3)
    t.setdefault('story_scene_id', None)
    t.setdefault('captions', [])
    t.setdefault('markers', [])
    t.setdefault('output', {})
    for k,v in OUTPUT_FIELDS.items():t['output'].setdefault(k, copy.deepcopy(v))
    for c in t.get('clips', []):
        for k,v in {**AUDIO_FIELDS, **PICTURE_FIELDS, 'audio_offset':0}.items():c.setdefault(k,copy.deepcopy(v))
        if c['source'].get('kind')=='gap':
            if not isinstance(c.get('color'),str):c['color']='#000000'
        elif isinstance(c.get('color'),str):c['color']=copy.deepcopy(COLOR_DEFAULT)
    for a in t.get('audio', []):
        for k,v in {**AUDIO_FIELDS,'lane':'sfx'}.items():a.setdefault(k,v)
    return t


def length(c):return (c['out'] - c['in'])/c.get('speed',1)+c.get('hold_start',0)+c.get('hold_end',0)


def starts(clips):
    result=[];end=0
    for c in clips:
        start=end-c.get('transition',{}).get('duration',0);result.append(start);end=start+length(c)
    return result


def fmt(v):return f'{v:.6f}'.rstrip('0').rstrip('.') or '0'


def audio_filters(item, duration):
    f=['aresample=48000','aformat=sample_fmts=fltp:channel_layouts=stereo',f'volume={fmt(item.get("volume",1))}']
    if item.get('normalize'):f.append('loudnorm=I=-16:TP=-1.5:LRA=7')
    if item.get('audio_fade_in'):f.append(f'afade=t=in:st=0:d={fmt(item["audio_fade_in"])}')
    if item.get('audio_fade_out'):f.append(f'afade=t=out:st={fmt(duration-item["audio_fade_out"])}:d={fmt(item["audio_fade_out"])}')
    return f


def tempo(speed):
    result=[]
    while speed<.5:result.append('atempo=0.5');speed/=.5
    while speed>2:result.append('atempo=2');speed/=2
    if speed!=1:result.append('atempo='+fmt(speed))
    return result


def video_filters(c,w,h,fps):
    f=[]
    if c.get('flip_h'):f.append('hflip')
    if c.get('flip_v'):f.append('vflip')
    crop=c.get('crop',PICTURE_FIELDS['crop'])
    if crop!=PICTURE_FIELDS['crop']:f.append(f'crop=iw*{fmt(crop["w"])}:ih*{fmt(crop["h"])}:iw*{fmt(crop["x"])}:ih*{fmt(crop["y"])}')
    f += [f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2',f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2','setsar=1','format=yuv420p','settb=AVTB']
    z=c.get('zoom',PICTURE_FIELDS['zoom'])
    if z['scale']!=1:
        f += [f'scale=ceil({w}*{fmt(z["scale"])}/2)*2:ceil({h}*{fmt(z["scale"])}/2)*2',rf'crop={w}:{h}:max(0\,min(iw-ow\,iw*{fmt(z["x"])}-ow/2)):max(0\,min(ih-oh\,ih*{fmt(z["y"])}-oh/2))']
    color=c.get('color',COLOR_DEFAULT)
    if isinstance(color,dict) and color!=COLOR_DEFAULT:
        f.append(f'eq=brightness={fmt(color["brightness"])}:contrast={fmt(color["contrast"])}:saturation={fmt(color["saturation"])}')
        if color['temperature']:f.append(f'colorbalance=rs={fmt(color["temperature"]*.2)}:bs={fmt(-color["temperature"]*.2)}')
    f.append(f'fps={fps}')
    # tpad needs a known frame rate after retiming (not just timestamps),
    # otherwise FFmpeg 7 can silently omit the cloned hold frames.
    if c.get('hold_start') or c.get('hold_end'):f.append(f'tpad=start_mode=clone:start_duration={fmt(c.get("hold_start",0))}:stop_mode=clone:stop_duration={fmt(c.get("hold_end",0))}')
    # Rounded zoom dimensions can change SAR; every join input must stay square.
    # output_size and the zoom scale/crop above already keep dimensions even.
    f.append('setsar=1')
    return f


def output_size(t, sources, quality='full'):
    ratio=t['output']['ratio'];resolution=t['output']['resolution']
    if quality=='draft':return {'16:9':(640,360),'9:16':(360,640),'1:1':(360,360)}[ratio]
    if resolution=='source':
        first=next((m for c,(_,m) in zip(t['clips'],sources) if c['source'].get('kind')!='gap' and m.get('video') and m.get('width') and m.get('height')),None)
        if first:return max(2,round(first['width']/2)*2),max(2,round(first['height']/2)*2)
    if resolution=='480p':return {'16:9':(848,480),'9:16':(480,848),'1:1':(480,480)}[ratio]
    w,h={'16:9':(1280,720),'9:16':(720,1280),'1:1':(720,720)}[ratio]
    factor=1.5 if resolution=='1080p' else 1
    return round(w*factor),round(h*factor)


def build_export(t, sources, overlays=(), quality='full', balanced=False):
    """sources are (path, metadata) pairs for clips then audio; overlays are PNGs."""
    t=migrate_timeline(t);clips=t['clips'];fps=t['output']['fps'];positions=starts(clips)
    total=positions[-1]+length(clips[-1]);w,h=output_size(t,sources,quality)
    args=[];graph=[];video=[];audios=[]
    for i,(path,m) in enumerate(sources):
        item=(clips+t['audio'])[i]
        if item['source'].get('kind')=='gap':
            args+=['-f','lavfi','-i',f'color=c={item.get("color","#000000")}:s={w}x{h}:r={fps}:d={fmt(length(item))}']
        elif m.get('image'):args+=['-loop','1','-framerate',str(fps)]
        if item['source'].get('kind')!='gap':args+=['-i',str(path)]
        d=length(item)
        if i<len(clips):
            graph.append(f'[{i}:v]trim=start={fmt(item["in"])}:end={fmt(item["out"])},setpts=(PTS-STARTPTS)/{fmt(item.get("speed",1))},'+','.join(video_filters(item,w,h,fps))+f'[v{i}]')
            video.append(f'[v{i}]')
        offset=item.get('audio_offset',0) if i<len(clips) else 0
        # Split edits extend the source window into the available handles.
        left=item['in']+min(0,offset)*item.get('speed',1);right=item['out']+max(0,offset)*item.get('speed',1)
        tail=(t['output']['cut_audio_crossfade_frames']/fps if i<len(clips)-1 and not clips[i+1].get('transition',{}).get('duration',0) else 0)
        requested_right=right+tail*item.get("speed",1)
        available_right=min(requested_right,m.get('duration',right))
        if m.get('audio') and item.get('speed_audio')!='mute':
            chain=f'[{i}:a]atrim=start={fmt(left)}:end={fmt(available_right)},asetpts=PTS-STARTPTS,'
        else:chain=f'anullsrc=r=48000:cl=stereo,atrim=duration={fmt(right-left)},'
        chain+=','.join(tempo(item.get('speed',1))+audio_filters(item,(right-left)/item.get('speed',1)))
        # adelay can emit leading silence with no timestamp. Give those samples
        # a clock before atrim/amix, or the held clip's audio can end early.
        if item.get('hold_start'):chain+=f',adelay={round(item["hold_start"]*1000)}:all=1,asetpts=N/SR/TB'
        if item.get('hold_end'):chain+=f',apad=whole_dur={fmt(d)},atrim=duration={fmt(d)}'
        if tail:
            if available_right<requested_right-.001:chain+=f',afade=t=out:st={fmt(max(0,right-left-tail))}:d={fmt(tail)}'
            chain+=f',apad=whole_dur={fmt((right-left)/item.get("speed",1)+item.get("hold_start",0)+item.get("hold_end",0)+tail)},atrim=duration={fmt((right-left)/item.get("speed",1)+item.get("hold_start",0)+item.get("hold_end",0)+tail)}'
        graph.append(chain+f'[a{i}]');audios.append(f'[a{i}]')
    def join_tree(labels, video_track):
        def join(lo,hi):
            if hi-lo==1:return labels[lo],length(clips[lo])+(0 if video_track or lo==len(clips)-1 or clips[lo+1].get('transition',{}).get('duration',0) else t['output']['cut_audio_crossfade_frames']/fps)
            mid=(lo+hi)//2;left,ld=join(lo,mid);right,rd=join(mid,hi);tr=clips[mid].get('transition',{});d=tr.get('duration',0)
            name=f'[tree{"v" if video_track else "a"}{lo}_{hi}]'
            if video_track and d:
                effect='fade' if tr['type']=='dissolve' else 'fadeblack'
                graph.append(left+f'settb=AVTB,setpts=PTS-STARTPTS,fps={fps}[treefixed{lo}_{hi}]')
                graph.append(f'[treefixed{lo}_{hi}]'+right+f'xfade=transition={effect}:duration={fmt(d)}:offset={fmt(ld-d)}'+name)
            elif not video_track and (d or t['output']['cut_audio_crossfade_frames']):
                d=d or t['output']['cut_audio_crossfade_frames']/fps
                graph.append(left+right+f'acrossfade=d={fmt(d)}:c1=tri:c2=tri'+name)
            else:graph.append(left+right+f'concat=n=2:v={int(video_track)}:a={int(not video_track)}'+name)
            return name,ld+rd-d
        return join(0,len(labels))[0]
    if balanced:v=join_tree(video,True)
    else:
        v=video[0]
        for i,c in enumerate(clips[1:],1):
            tr=c.get('transition',{});d=tr.get('duration',0);target=f'[joinv{i}]'
            if d:
                effect='fade' if tr['type']=='dissolve' else 'fadeblack'
                graph.append(v+f'settb=AVTB,setpts=PTS-STARTPTS,fps={fps}[fixed{i}]')
                graph.append(f'[fixed{i}]'+video[i]+f'xfade=transition={effect}:duration={fmt(d)}:offset={fmt(positions[i])}'+target)
            else:graph.append(v+video[i]+'concat=n=2:v=1:a=0'+target)
            v=target
    lanes={'dialogue':[],'music':[],'sfx':[]}
    if not any(c.get('audio_offset',0) for c in clips):
        if balanced:a=join_tree(audios[:len(clips)],False)
        else:
            a=audios[0]
            for i,c in enumerate(clips[1:],1):
                d=c.get('transition',{}).get('duration',0)
                cut=not d
                d=d or t['output']['cut_audio_crossfade_frames']/fps
                if d:
                    graph.append(a+audios[i]+f'acrossfade=d={fmt(d)}:c1=tri:c2=tri[join a{i}]'.replace('join a','joina'))
                else:graph.append(a+audios[i]+'concat=n=2:v=0:a=1'+f'[joina{i}]')
                a=f'[joina{i}]'
        lanes['dialogue'].append(a)
    else:
        for i,c in enumerate(clips):
            at=positions[i]+c.get('audio_offset',0)
            a=audios[i]
            # Fade each independently placed signal against silence. Together
            # these triangular envelopes are the same crossfade as the joined
            # path, including dissolves when another clip has a split edit.
            incoming=c.get('transition',{}).get('duration',0) or (t['output']['cut_audio_crossfade_frames']/fps if i else 0)
            outgoing=(clips[i+1].get('transition',{}).get('duration',0) or t['output']['cut_audio_crossfade_frames']/fps) if i+1<len(clips) else 0
            for side,d in [('in',incoming),('out',outgoing)]:
                if not d:continue
                silence=f'[silence{i}{side}]';result=f'[ramp{i}{side}]'
                graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={fmt(d)}'+silence)
                graph.append((silence+a if side=='in' else a+silence)+f'acrossfade=d={fmt(d)}:c1=tri:c2=tri'+result)
                a=result
            if at<0:graph.append(a+f'atrim=start={fmt(-at)},asetpts=PTS-STARTPTS[early{i}]');a=f'[early{i}]';at=0
            graph.append(a+f'adelay={round(at*1000)}:all=1,asetpts=N/SR/TB[placed{i}]');lanes['dialogue'].append(f'[placed{i}]')
    for j,item in enumerate(t['audio'],len(clips)):
        graph.append(audios[j]+f'adelay={round(item["start"]*1000)}:all=1,asetpts=N/SR/TB[placed{j}]')
        lanes[item.get('lane','sfx')].append(f'[placed{j}]')
    graph.extend(mix_lanes(lanes,total,t['output']['ducking'],t['output']['loudness_target_lufs']))
    for i,(path,title) in enumerate(overlays,len(sources)):
        args+=(['-f','concat','-safe','0','-i',str(path)] if title.get('concat') else ['-loop','1','-i',str(path)])
        graph.append(v+f'[{i}:v]overlay=0:0:enable=\'gte(t,{fmt(title["start"])})*lt(t,{fmt(title["end"])})\':shortest=1[overlay{i}]')
        v=f'[overlay{i}]'
    return args+['-filter_complex',';'.join(graph),'-map',v,'-map','[aout]','-t',fmt(total),'-c:v','libx264','-preset','ultrafast' if quality=='draft' else 'veryfast','-crf','30' if quality=='draft' else '20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart','export.mp4']


def mix_lanes(lanes,total,duck,target=None):
    """Normalize stems before bounded ducking; no gain lift after the envelope."""
    graph=[]
    for lane,inputs in lanes.items():
        # A finite silence input supplies real, timestamped trailing samples.
        # apad followed by atrim can lose its tail at EOF on FFmpeg 9, making
        # short-stem loudness analysis depend on how the graph was partitioned.
        if inputs:
            silence=f'[silence_{lane}]'
            graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={fmt(total)}'+silence)
            filters=f'amix=inputs={len(inputs)+1}:normalize=0,atrim=duration={fmt(total)}'
            mixed=inputs+[silence]
        else:
            filters=f'anullsrc=r=48000:cl=stereo,atrim=duration={fmt(total)}'
            mixed=[]
        if duck['enabled'] and target is not None and inputs:
            filters+=f',loudnorm=I={fmt(target)}:TP=-1.5:LRA=7,aresample=48000'
        graph.append(''.join(mixed)+filters+f'[{lane}]')
    if duck['enabled'] and lanes['music']:
        graph.append('[dialogue]asplit=2[dialogue_mix][key_raw]')
        graph.append('[key_raw]volume=64[key]')
        # Dry blend bounds the reduction at amount_db. A saturated, normalized
        # sidechain drives the wet signal near zero while speech is present.
        # Elevated key levels extend detector recovery; compensate its time scale.
        wet=1-10**(-duck['amount_db']/20)
        graph.append(f'[music][key]sidechaincompress=threshold=0.000976563:ratio=20:level_sc=64:attack={fmt(duck["attack_ms"])}:release={fmt(max(1,duck["release_ms"]/10))}:makeup=1:mix={fmt(wet)}[ducked]')
        mix='[dialogue_mix][ducked][sfx]'
    else:mix='[dialogue][music][sfx]'
    final=f'amix=inputs=3:normalize=0,atrim=duration={fmt(total)}'
    if target is not None and not duck['enabled']:final+=f',loudnorm=I={fmt(target)}:TP=-1.5:LRA=7'
    graph.append(mix+final+',alimiter=limit=0.95:latency=1[aout]')
    return graph
