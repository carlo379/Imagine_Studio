export type Source={kind:'upload'|'take';id:string};
export type SongCue={id:string;kind:string;start:number;end:number;text?:string;source?:string;method?:string;confidence?:number|null;uncertainty_s?:number|null;review_state:'suggested'|'reviewed'|'rejected'};
export type SongReview={id:string;revision:number;song_shot_id:string;song_anchor:number;clip_anchor:number;stale:boolean;comparisons?:{id:string;review_revision:number}[];source_metadata:{source:Source;duration:number;width:number;height:number;fps:string|null;frames:string|null};intervals:{start:number;end:number;state:string;reason?:string|null;note?:string}[];method:string;reviewer:string;notes:string};
export type SongShot={id:string;revision:number;title:string;order:number;start:number;end:number;duration:number;leading_handle:number;trailing_handle:number;mode:'singing'|'dance_only'|'cutaway';draft_id:string|null;production_shot_id:string|null;stale:boolean;poses:{song_time:number;asset_id:string;purpose:string}[];reference_handles:string[];cue_ids:string[];reviews:SongReview[]};
export type SongProject={id:string;revision:number;title:string;production_id:string;episode_id:string|null;story_scene_id:string|null;master_version:number;cue_revision:number;lyrics:string;master:{source:Source;duration:number;samples:number;sample_rate:number;channels:number};stems:Record<string,{source:Source}>;stem_alignment:Record<string,any>;analysis_jobs?:any[];analysis?:any;cues:SongCue[];shots:SongShot[];working_timeline_id:string|null};
export const SongClockGrid={
 songTime:(review:{song_anchor:number;clip_anchor:number},clip:number)=>review.song_anchor+(clip-review.clip_anchor),
 clipTime:(review:{song_anchor:number;clip_anchor:number},song:number)=>review.clip_anchor+(song-review.song_anchor),
 poseSlot:(local:number)=>Math.floor(local*3+.5),
 frame:(song:number,fps:number)=>Math.floor(song*fps+.5),
};
export function makeSelections(p:SongProject){return p.shots.flatMap(s=>s.reviews.filter(r=>!r.stale).slice(-1).flatMap(r=>r.intervals.filter(i=>i.state==='usable').map(i=>({review_id:r.id,expected_review_revision:r.revision,song_start:Math.max(s.start,SongClockGrid.songTime(r,i.start)),song_end:Math.min(s.end,p.master.duration,SongClockGrid.songTime(r,i.end))})).filter(i=>i.song_end>i.song_start))).sort((a,b)=>a.song_start-b.song_start);}
