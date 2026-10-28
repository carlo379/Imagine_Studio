import {useAgentEditor} from './agent-editors';
import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {service} from './studio-service';

type DirectionJob={id:string;revision:number;video_id:string;video_revision:number;status:'pending'|'done'|'error';provider:string;video_model:string;auto_apply:boolean;applied?:boolean;restored?:boolean;error?:string;instruction?:string;previous_prompt?:string;previous_duration:number;prepared_prompt?:string;expanded_prompt_chars?:number;expanded_prompt_bytes?:number;prompt_budget_unit?:string;result?:{direction:string;asset_summaries:{handle:string;summary:string}[];duration_seconds:number;duration_reason:string;notes:string[];starting_frame_observations?:string[];issues?:{code:string;severity:'warning'|'error';message:string}[]}};
declare global {interface Window {studioVideoDirectionPending?:boolean}}

export function VideoDirection({shotId,prepare,changed}:{shotId:string;prepare:()=>Promise<void>;changed:(value:any)=>Promise<void>}){
 const [job,setJob]=useState<DirectionJob|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[provider,setProvider]=useState(''),[model,setModel]=useState(''),[duration,setDuration]=useState(5),[limit,setLimit]=useState(4096);
 const draftKey=((window as any).studioStoragePrefix||'')+'imagine-video-instructions-'+shotId;
 const [draft]=useState(()=>{try{const value=sessionStorage.getItem(draftKey);return {text:value||'',exists:value!==null};}catch{return {text:'',exists:false};}});
 const [instruction,setInstruction]=useState(draft.text),[instructionLimit,setInstructionLimit]=useState(2000),[loaded,setLoaded]=useState(false);
 const instructionTouched=useRef(draft.exists),submittedJob=useRef('');
 const active=useRef(true),running=useRef(false),autoAttempt=useRef('');
 const callbacks=useRef({prepare,changed});callbacks.current={prepare,changed};
 const panel=document.getElementById('videoDirectionPanel');
 useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
 useEffect(()=>{
  const sync=()=>{const value=(window.productionBridge as any).videoState?.();if(value){setModel(value.model);setDuration(value.duration);}};sync();window.addEventListener('video-direction-input',sync);return()=>window.removeEventListener('video-direction-input',sync);
 },[]);
 useEffect(()=>{let alive=true;void service('filmmaking/shots/'+shotId+'/video-direction').then(value=>{if(alive&&!running.current){setJob(value.job);setProvider(value.provider);setModel(value.video_model);setDuration(value.duration);setLimit(value.prompt_limit_chars);setInstructionLimit(value.instruction_limit_chars||2000);if(!instructionTouched.current)setInstruction(value.job?.instruction||'');}}).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoaded(true);});return()=>{alive=false;};},[shotId]);
 useEffect(()=>{if(!loaded&&!instructionTouched.current)return;try{sessionStorage.setItem(draftKey,instruction);}catch{}},[draftKey,instruction,loaded]);
 useAgentEditor('video-instructions',{capture:()=>({id:shotId,revision:job?.revision||0,dirty:!!instruction,data:{instruction,provider}}),discard:async()=>{if(busy)throw Error('Video preparation is busy.');setInstruction('');sessionStorage.removeItem(draftKey);}});
 async function run(fn:()=>Promise<void>){if(running.current)return;running.current=true;setBusy(true);setError('');try{await fn();}catch(e){if(active.current)setError((e as Error).message);}finally{running.current=false;if(active.current)setBusy(false);}}
 async function start(force=false,key:string=crypto.randomUUID()){
  if(window.studioShotDirectionDirty)throw Error('Save or cancel your shot direction changes before preparing a prompt.');
  await callbacks.current.prepare();if(!active.current)return;
  const shot=await service('productions/shots/'+shotId);if(!active.current)return;
  const value=await service<DirectionJob>('filmmaking/shots/'+shotId+'/video-direction','POST',{expected_revision:shot.revision,expected_video_revision:shot.video.revision,approved:true,provider:provider||undefined,instruction:instruction.trim(),force},key);
  if(active.current){submittedJob.current=value.id;setJob(value);setProvider(value.provider);setModel(shot.video.scene.model);setDuration(shot.video.scene.duration);}
 }
 useEffect(()=>{
  if(job?.status!=='pending')return;let alive=true,inflight=false;
  const poll=async()=>{if(inflight)return;inflight=true;try{const value=await service<DirectionJob>('filmmaking/video-direction-jobs/'+job.id);if(alive){setJob(value);setError('');}}catch(e){if(alive)setError((e as Error).message);}finally{inflight=false;}};
  const timer=setInterval(()=>void poll(),1800);return()=>{alive=false;clearInterval(timer);};
 },[job?.id,job?.status]);
 async function apply(value:DirectionJob,replace:boolean){
  await callbacks.current.prepare();if(!active.current)return;
  const shot=await service('productions/shots/'+shotId);if(!active.current)return;
  const result=await service('filmmaking/shots/'+shotId+'/video-direction/apply','POST',{job_id:value.id,expected_revision:value.revision,expected_video_revision:shot.video.revision,replace_settings:replace});
  if(active.current){setJob(result.job);setDuration(result.draft.scene.duration);await callbacks.current.changed(result);}
 }
 useEffect(()=>{
  if(busy||job?.status!=='done'||submittedJob.current!==job.id||instruction.trim()!==(job.instruction||'')||!job.auto_apply||job.applied||job.restored||autoAttempt.current===job.id)return;
  autoAttempt.current=job.id;void run(()=>apply(job,false));
 },[busy,job?.id,job?.status,job?.applied,instruction]);
 const pending=job?.status==='pending';
 useEffect(()=>{window.studioVideoDirectionPending=busy||pending;window.dispatchEvent(new Event('video-direction-status'));return()=>{window.studioVideoDirectionPending=false;window.dispatchEvent(new Event('video-direction-status'));};},[busy,pending]);
 useEffect(()=>{const hint=document.getElementById('videoDurationSuggestion');if(!hint)return;hint.hidden=!job?.result||!!job.restored;if(job?.result)hint.textContent='AI suggests '+job.result.duration_seconds+'s'+(duration!==job.result.duration_seconds?' · Your setting: '+duration+'s':'')+'. '+job.result.duration_reason;return()=>{hint.hidden=true;};},[job?.id,job?.result,duration,job?.restored]);
 const changedModel=job&&job.video_model!==model,changedProvider=job&&provider!==job.provider;
 const changedInstruction=job&&instruction.trim()!==(job.instruction||'');
 const proposal=job?.status==='done'&&!job.applied&&!job.restored;
 const content=<section className="opening-frame video-direction" aria-label="AI video direction and timing" aria-busy={busy||pending}>
  <div className="opening-frame-heading"><div><strong>Video direction &amp; timing</strong><small>{pending?'Preparing with '+(job.provider==='grok'?'Grok':'ChatGPT')+'…':'Visual references · Editable duration'}</small></div><label className="video-direction-provider">Writing connection<select aria-label="Video direction writing connection" disabled={!loaded||busy||pending} value={provider||'codex'} onChange={e=>setProvider(e.target.value)}><option value="codex">ChatGPT</option><option value="grok">Grok</option></select></label></div>
  <div className="video-direction-instructions"><label htmlFor="videoAIInstructions">Instructions for AI <span>(optional)</span></label><textarea id="videoAIInstructions" rows={3} maxLength={instructionLimit} value={instruction} disabled={busy||pending} aria-describedby="videoAIInstructionsHint videoAIInstructionsCount" placeholder="Example: Keep the camera stationary. Make Mark approach more slowly. End before the truck door opens." onChange={e=>{instructionTouched.current=true;setInstruction(e.target.value);}}/><small id="videoAIInstructionsHint">Give initial direction or explain what the previous preparation got wrong. AI reads the script, starting frame and attached reference images to prepare motion and performance.</small><div className="video-direction-instruction-actions"><small id="videoAIInstructionsCount">{instruction.length.toLocaleString()} / {instructionLimit.toLocaleString()} characters</small><button type="button" disabled={!loaded||busy||pending||instruction.length>instructionLimit} onClick={()=>void run(()=>start(!!job))}>{busy||pending?'Preparing…':job?'Prepare again':'Prepare with AI'}</button></div></div>
  {pending?<p role="status">Reading the script, frame images and character references, reconciling direction and estimating shot length. Your saved settings stay intact while AI works.</p>:!job?<p>Prepare motion from your opening frame and attached reference images, with a suggested shot duration. Uses the selected writing subscription; video generation is a separate action.</p>:null}
  {job?.status==='error'&&<p className="opening-frame-error" role="alert">{job.error}</p>}{error&&<p className="opening-frame-error" role="alert">{error}</p>}
  {changedInstruction&&!pending&&<p className="video-direction-instruction-status">Your instructions have changed. Click Prepare again to include them in a new proposal; the current video prompt stays unchanged.</p>}
  {job?.instruction&&<details className="video-direction-used-instructions"><summary>Instructions used for this preparation</summary><p>{job.instruction}</p></details>}
  {job?.result&&<><p><strong>AI duration: {job.result.duration_seconds}s.</strong> {job.result.duration_reason}</p><small>{(job.prompt_budget_unit==='UTF-8 bytes'?job.expanded_prompt_bytes:job.expanded_prompt_chars)?.toLocaleString()} / {limit.toLocaleString()} {job.prompt_budget_unit||'characters'} in the expanded request at preparation.</small>
   {!!job.result.starting_frame_observations?.length&&<details open><summary>Starting-frame observations</summary><ul>{job.result.starting_frame_observations.map((note,i)=><li key={i}>{note}</li>)}</ul></details>}
   {!!job.result.issues?.length&&<div className="video-direction-issues">{job.result.issues.map((issue,i)=><p key={i} className={issue.severity==='error'?'opening-frame-error':'video-direction-instruction-status'} role={issue.severity==='error'?'alert':'status'}>{issue.message}</p>)}</div>}
   {job.result.notes.length>0&&<ul>{job.result.notes.map((note,i)=><li key={i}>{note}</li>)}</ul>}
   {proposal&&<><p>Your existing direction or timing is preserved. Compare before replacing it.</p><details open><summary>Compare direction &amp; duration</summary><div className="opening-frame-compare"><div><h4>Previous · {job.previous_duration}s</h4><pre>{job.previous_prompt||'No direction yet'}</pre></div><div><h4>Prepared · {job.result.duration_seconds}s</h4><pre>{job.prepared_prompt}</pre></div></div></details><button className="p-primary" disabled={busy||pending||!!changedModel||!!changedProvider||!!changedInstruction} onClick={()=>void run(()=>apply(job,true))}>Use prompt &amp; duration</button></>}
   {job.applied&&<details><summary>Previous direction &amp; prepared version</summary><div className="opening-frame-compare"><div><h4>Previous · {job.previous_duration}s</h4><pre>{job.previous_prompt||'No direction yet'}</pre></div><div><h4>Prepared · {job.result.duration_seconds}s</h4><pre>{job.prepared_prompt}</pre></div></div>{!job.restored&&<button disabled={busy} onClick={()=>void run(async()=>{await callbacks.current.prepare();if(!active.current)return;const shot=await service('productions/shots/'+shotId);if(!active.current)return;const result=await service('filmmaking/shots/'+shotId+'/video-direction/restore','POST',{job_id:job.id,expected_revision:job.revision,expected_video_revision:shot.video.revision});if(active.current){setJob(result.job);setDuration(result.draft.scene.duration);await callbacks.current.changed(result);}})}>Restore previous direction &amp; duration</button>}{job.restored&&<p>Previous settings restored.</p>}</details>}
  </>}
 </section>;
 return panel?createPortal(content,panel):content;
}
