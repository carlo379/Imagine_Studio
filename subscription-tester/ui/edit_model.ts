export type Source={kind:'take'|'upload'|'image'|'gap';id?:string};
export type Transition={type:'cut'|'dissolve'|'fade';duration:number};
export type AudioTools={audio_fade_in?:number;audio_fade_out?:number;audio_offset?:number;normalize?:boolean;lane?:'dialogue'|'music'|'sfx'};
export type PictureTools={flip_h?:boolean;flip_v?:boolean;crop?:{x:number;y:number;w:number;h:number};zoom?:{scale:number;x:number;y:number};speed?:number;speed_audio?:'preserve_pitch'|'mute';hold_start?:number;hold_end?:number;color?:string|{brightness:number;contrast:number;saturation:number;temperature:number}};
export type Clip=AudioTools&PictureTools&{id:string;source:Source;in:number;out:number;volume:number;label:string;shot_id?:string;transition?:Transition;render_link?:{timeline_id:string;revision:number;export_id:string}};
export type Audio=Omit<Clip,'transition'>&{start:number};
export type Title={id:string;text:string;start:number;end:number;position:'top'|'center'|'bottom';size:number;color:string};
export type Caption={id:string;start:number;end:number;text:string;speaker?:string};
export type CaptionStyle={mode:'off'|'burn_in'|'sidecar'|'both';position:'top'|'center'|'bottom';size:number;color:string;max_chars_per_line:number};
export type Marker={id:string;time:number;label:string;note:string;color:string;clip_id?:string;clip_time?:number};
export type Timeline={id:string;revision:number;production_id:string;episode_id:string|null;story_scene_id?:string|null;title:string;clips:Clip[];audio:Audio[];titles:Title[];captions?:Caption[];markers?:Marker[];output:{ratio:string;resolution:string;fps:number;captions?:CaptionStyle;cut_audio_crossfade_frames?:number;loudness_target_lufs?:number|null;ducking?:{enabled:boolean;amount_db:number;attack_ms:number;release_ms:number}}};
export const seconds=(v:number)=>Number(v.toFixed(3));
export const clipLength=(c:Clip)=>(c.out-c.in)/(c.speed||1)+(c.hold_start||0)+(c.hold_end||0);
export const sourceTime=(c:Clip,local:number)=>c.in+Math.max(0,Math.min((c.out-c.in)/(c.speed||1),local-(c.hold_start||0)))*(c.speed||1);
export const overlap=(c:Clip)=>c.transition?.type!=='cut'?c.transition?.duration||0:0;
export const offsets=(clips:Clip[])=>{let end=0;return clips.map(c=>{const start=end-overlap(c);end=start+clipLength(c);return seconds(start);});};
export const duration=(t:Timeline)=>seconds(t.clips.reduce((sum,c)=>sum+clipLength(c)-overlap(c),0));
export const snap=(v:number,fps:number)=>seconds(Math.round(v*fps)/fps);
export const cut:Transition={type:'cut',duration:0};
export function normalizeClips(clips:Clip[],fps:number):Clip[]{return clips.map((original,i)=>{const c=normalizeAudio(normalizePicture(original),clipLength(original),fps);if(!i||!overlap(c))return {...c,transition:{...cut}};const prev=clips[i-1];const max=Math.min(2,clipLength(c)/2,clipLength(prev)/2);const d=seconds(Math.floor(Math.min(overlap(c),max)*fps+.01)/fps);return {...c,transition:d>=1/fps-.001?{type:c.transition!.type,duration:d}:{...cut}};});}
export function splitClip(t:Timeline,identity:string,at:number,makeId:()=>string,still=false):Clip[]{
 const i=t.clips.findIndex(c=>c.id===identity);if(i<0)throw Error('Select a clip to split.');
 const c=t.clips[i],local=snap(at-offsets(t.clips)[i],t.output.fps),frame=Math.ceil(.04*t.output.fps)/t.output.fps;
 const incoming=overlap(c),outgoing=i+1<t.clips.length?overlap(t.clips[i+1]):0;
 if(local<Math.max(frame,2*incoming)-.001||clipLength(c)-local<Math.max(frame,2*outgoing)-.001)throw Error('Place the playhead inside the clip, away from its edges and transition overlaps.');
 if(local<=(c.hold_start||0)||local>=clipLength(c)-(c.hold_end||0))throw Error('Split inside the moving part, outside frame holds.');const point=seconds(sourceTime(c,local));if(still||c.source.kind==='image'||c.source.kind==='gap')return [...t.clips.slice(0,i),{...c,in:0,out:seconds((local-(c.hold_start||0))*(c.speed||1)),hold_end:0},{...c,id:makeId(),in:0,out:seconds((clipLength(c)-local-(c.hold_end||0))*(c.speed||1)),hold_start:0,transition:{...cut}},...t.clips.slice(i+1)];return [...t.clips.slice(0,i),{...c,out:point,hold_end:0},{...c,id:makeId(),in:point,hold_start:0,transition:{...cut}},...t.clips.slice(i+1)];
}
export function moveClip(clips:Clip[],from:number,insertion:number):Clip[]{const copy=[...clips];if(from<0||from>=copy.length)return copy;const [c]=copy.splice(from,1);copy.splice(Math.max(0,Math.min(copy.length,insertion>from?insertion-1:insertion)),0,c);return copy;}

export function normalizeAudio<T extends AudioTools>(c:T,length:number,fps:number):T{return {...c,audio_fade_in:seconds(Math.floor(Math.max(0,Math.min(2,length/2,c.audio_fade_in||0))*fps+.001)/fps),audio_fade_out:seconds(Math.floor(Math.max(0,Math.min(2,length/2,c.audio_fade_out||0))*fps+.001)/fps),audio_offset:snap(Math.max(-2,Math.min(2,c.audio_offset||0)),fps),normalize:!!c.normalize};}
export function migrateTimeline(t:Timeline):Timeline{return {...t,captions:t.captions||[],markers:t.markers||[],output:{captions:{mode:'off',position:'bottom',size:48,color:'#ffffff',max_chars_per_line:32},cut_audio_crossfade_frames:0,loudness_target_lufs:null,ducking:{enabled:false,amount_db:10,attack_ms:80,release_ms:400},...t.output},clips:t.clips.map(c=>normalizeAudio(normalizePicture(c),clipLength(c),t.output.fps)),audio:t.audio.map(a=>{const {audio_offset,...values}=normalizeAudio(a,a.out-a.in,t.output.fps);return {...values,lane:a.lane||'sfx'};})};}

export function normalizePicture(c:Clip):Clip{const range=(v:number,a:number,b:number)=>Math.max(a,Math.min(b,v));const crop={x:0,y:0,w:1,h:1,...c.crop};crop.w=range(crop.w,.1,1);crop.h=range(crop.h,.1,1);crop.x=range(crop.x,0,1-crop.w);crop.y=range(crop.y,0,1-crop.h);const neutral={brightness:0,contrast:1,saturation:1,temperature:0},color=typeof c.color==='object'?{brightness:range(c.color.brightness??0,-.5,.5),contrast:range(c.color.contrast??1,.5,2),saturation:range(c.color.saturation??1,0,2),temperature:range(c.color.temperature??0,-1,1)}:neutral;return {...c,color:c.source.kind==='gap'?(typeof c.color==='string'?c.color:'#000000'):color,speed_audio:c.speed_audio==='mute'?'mute':'preserve_pitch',flip_h:!!c.flip_h,flip_v:!!c.flip_v,speed:range(c.speed||1,.25,4),hold_start:range(c.hold_start||0,0,10),hold_end:range(c.hold_end||0,0,10),crop,zoom:{scale:range(c.zoom?.scale||1,1,3),x:range(c.zoom?.x??.5,0,1),y:range(c.zoom?.y??.5,0,1)}};}

export const captionStyle=(t:Timeline):CaptionStyle=>({mode:'off',position:'bottom',size:48,color:'#ffffff',max_chars_per_line:32,...t.output.captions});
export function splitCaption(c:Caption,id:string):Caption[]{const middle=seconds((c.start+c.end)/2),words=c.text.split(/\s+/),at=Math.max(1,Math.ceil(words.length/2));return [{...c,end:middle,text:words.slice(0,at).join(' ')},{...c,id,start:middle,text:words.slice(at).join(' ')||c.text}];}

export function anchoredMarkers(markers:Marker[],clips:Clip[]):Marker[]{const at=offsets(clips);return markers.map(m=>{const i=clips.findIndex(c=>c.id===m.clip_id);return i<0?m:{...m,time:seconds(at[i]+Math.min(m.clip_time||0,clipLength(clips[i])))};});}
export function normalizeOutput(output:Timeline['output']):Timeline['output']{const clamp=(value:number|undefined,low:number,high:number,fallback:number)=>Math.max(low,Math.min(high,Number.isFinite(value)?value!:fallback)),duck=output.ducking,style=output.captions;return {...output,cut_audio_crossfade_frames:Math.round(clamp(output.cut_audio_crossfade_frames,0,12,0)),loudness_target_lufs:output.loudness_target_lufs==null?null:clamp(output.loudness_target_lufs,-30,-10,-16),ducking:{enabled:!!duck?.enabled,amount_db:clamp(duck?.amount_db,0,24,10),attack_ms:clamp(duck?.attack_ms,5,500,80),release_ms:clamp(duck?.release_ms,50,2000,400)},captions:{mode:style?.mode||'off',position:style?.position||'bottom',size:clamp(style?.size,16,96,48),color:style?.color||'#ffffff',max_chars_per_line:Math.round(clamp(style?.max_chars_per_line,8,80,32))}};}

export const EDIT_LIMITS={clips:120,audio:200,titles:100};
export function trackLimitError(t:Pick<Timeline,'clips'|'audio'|'titles'>):string{for(const k of ['clips','audio','titles'] as const)if(t[k].length>EDIT_LIMITS[k])return `Use at most ${EDIT_LIMITS[k]} ${k==='clips'?'clip':k==='titles'?'title':'audio'} items per timeline.`;return '';}

export type AudioSourceInfo={audio:boolean;duration:number};
export function audioOffsetBounds(c:Clip,info:AudioSourceInfo|undefined,fps:number){
 const frames=(v:number)=>Math.min(2*fps,Math.max(0,Math.floor((v+.001)*fps)));
 if(!info?.audio)return {min:0,max:0};
 return {min:seconds(-frames(c.in/(c.speed||1))/fps),max:seconds(frames((info.duration-c.out)/(c.speed||1))/fps)};
}
export function audioOffsetProblem(c:Clip,info:AudioSourceInfo|undefined,fps:number):string{
 const offset=c.audio_offset||0;if(!offset||!info)return '';
 if(!info.audio)return `${c.label}: this source has no audio. Reset audio offset to 0.`;
 const {min,max}=audioOffsetBounds(c,info,fps);
 if(offset>=min-.001&&offset<=max+.001)return '';
 const available=Math.max(0,offset<0?c.in:info.duration-c.out)/(c.speed||1);
 return `${c.label}: audio offset ${offset.toFixed(3)}s needs spare audio ${offset<0?'before the trim start':'after the trim end'}; ${available.toFixed(3)}s available. Reset audio offset or trim the clip to leave spare audio.`;
}

// Pack items that do not overlap into the same visible timeline row.
export function timelineRows(items:{id:string;start:number;end:number}[]){
 const ends:number[]=[],rowById:Record<string,number>={};
 for(const item of [...items].sort((a,b)=>a.start-b.start||a.end-b.end)){
  let row=ends.findIndex(end=>end<=item.start+.001);
  if(row<0)row=ends.length;
  ends[row]=item.end;rowById[item.id]=row;
 }
 return {rowById,rows:Math.max(1,ends.length)};
}
