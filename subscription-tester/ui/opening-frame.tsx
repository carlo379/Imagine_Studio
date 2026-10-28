import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {service} from './studio-service';

type FrameJob={id:string;revision:number;image_id:string;image_revision:number;status:'pending'|'done'|'error';provider:string;image_model:string;auto_apply:boolean;applied?:boolean;restored?:boolean;error?:string;previous_prompt?:string;result?:{prompt:string;opening_state:string;references:string[];notes:string[]}};
declare global {interface Window {studioOpeningFramePending?:boolean}}

export function OpeningFrame({shotId,request,prepare,changed}:{shotId:string;request?:string;prepare:()=>Promise<void>;changed:(value:any)=>Promise<void>}){
 const [job,setJob]=useState<FrameJob|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[model,setModel]=useState('');
 const active=useRef(true),running=useRef(false),autoAttempt=useRef('');
 const callbacks=useRef({prepare,changed});callbacks.current={prepare,changed};
 const panel=document.getElementById('openingFramePrompt');
 useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
 useEffect(()=>{
  const sync=()=>{const value=(window.productionBridge as any).imageState?.();if(value)setModel(value.model);};sync();window.addEventListener('image-model-changed',sync);return()=>window.removeEventListener('image-model-changed',sync);
 },[]);
 useEffect(()=>{let alive=true;void service('filmmaking/shots/'+shotId+'/opening-frame').then(value=>{if(alive&&!running.current){setJob(value.job);setModel(value.image_model);}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[shotId]);

 async function run(fn:()=>Promise<void>){if(running.current)return;running.current=true;setBusy(true);setError('');try{await fn();}catch(e){if(active.current)setError((e as Error).message);}finally{running.current=false;if(active.current)setBusy(false);}}
 async function start(force=false,key:string=crypto.randomUUID()){
  await callbacks.current.prepare();if(!active.current)return;
  const shot=await service('productions/shots/'+shotId);if(!active.current)return;
  const value=await service('filmmaking/shots/'+shotId+'/opening-frame','POST',{expected_revision:shot.revision,expected_image_revision:shot.image.revision,approved:true,force},key);
  if(active.current){setJob(value);setModel(shot.image.settings.model);}
 }
 useEffect(()=>{if(request)void run(()=>start(false,request));},[request]);
 useEffect(()=>{
  if(job?.status!=='pending')return;let alive=true,inflight=false;
  const poll=async()=>{if(inflight)return;inflight=true;try{const value=await service('filmmaking/opening-frame-jobs/'+job.id);if(alive){setJob(value);setError('');}}catch(e){if(alive)setError((e as Error).message);}finally{inflight=false;}};
  const timer=setInterval(()=>void poll(),1800);return()=>{alive=false;clearInterval(timer);};
 },[job?.id,job?.status]);
 async function apply(value:FrameJob,replace:boolean){
  await callbacks.current.prepare();if(!active.current)return;
  const shot=await service('productions/shots/'+shotId);if(!active.current)return;
  const result=await service('filmmaking/shots/'+shotId+'/opening-frame/apply','POST',{job_id:value.id,expected_revision:value.revision,expected_image_revision:shot.image.revision,replace_prompt:replace});
  if(active.current){setJob(result.job);await callbacks.current.changed(result);}
 }
 useEffect(()=>{
  if(!request||busy||job?.status!=='done'||!job.auto_apply||job.applied||job.restored||autoAttempt.current===job.id)return;
  autoAttempt.current=job.id;void run(()=>apply(job,false));
 },[request,busy,job?.id,job?.status,job?.applied]);
 const pending=job?.status==='pending';
 useEffect(()=>{window.studioOpeningFramePending=busy||pending;window.dispatchEvent(new Event('opening-frame-status'));return()=>{window.studioOpeningFramePending=false;window.dispatchEvent(new Event('opening-frame-status'));};},[busy,pending]);
 const provider=model.startsWith('grok')?'Grok':'ChatGPT',changedProvider=job&&job.image_model!==model;
 const proposal=job?.status==='done'&&!job.applied&&!job.restored;
 const content=<section className="opening-frame" aria-label="Opening frame for this shot" aria-busy={busy||pending}>
  <div className="opening-frame-heading"><div><strong>Opening frame</strong><small>{pending?'Preparing with '+(job.provider==='grok'?'Grok':'ChatGPT')+'…':provider+' · Script and saved asset context'}</small></div><button type="button" disabled={busy||pending} onClick={()=>void run(()=>start(true))}>{busy?'Preparing…':job?'Prepare again':'Prepare with AI'}</button></div>
  {pending?<p role="status">Reading the scene and shot action to describe the first visible instant. Your saved prompt stays intact while AI works.</p>:job?.applied&&!job.restored?<p className="opening-frame-ready">✓ Opening-frame version saved. Review or edit your prompt below, then generate your image.</p>:!job?<p>AI prepares a still image that sets up this shot’s animation. Image generation is your next action.</p>:null}
  {job?.status==='error'&&<p className="opening-frame-error" role="alert">{job.error}</p>}
  {error&&<p className="opening-frame-error" role="alert">{error}</p>}
  {changedProvider&&<p>The selected image model changed. Prepare again to use {provider} with its prompt limit.</p>}
  {job?.result&&<>
   <p>{job.result.opening_state}</p>
   {job.result.notes.length>0&&<ul>{job.result.notes.map((note,i)=><li key={i}>{note}</li>)}</ul>}
   {proposal&&<><p>Your current image prompt has been preserved. Review the opening-frame proposal before replacing it.</p><details open><summary>Compare prompts</summary><div className="opening-frame-compare"><div><h4>Current at preparation</h4><pre>{job.previous_prompt||'No prompt yet'}</pre></div><div><h4>Proposed opening frame</h4><pre>{job.result.prompt}</pre></div></div></details><button className="p-primary" disabled={busy||pending||!!changedProvider} onClick={()=>void run(()=>apply(job,true))}>Use this opening-frame prompt</button></>}
   {job.applied&&<details><summary>Previous prompt &amp; prepared version</summary><div className="opening-frame-compare"><div><h4>Previous</h4><pre>{job.previous_prompt||'No prompt yet'}</pre></div><div><h4>Prepared</h4><pre>{job.result.prompt}</pre></div></div>{!job.restored&&<button disabled={busy} onClick={()=>void run(async()=>{await callbacks.current.prepare();if(!active.current)return;const shot=await service('productions/shots/'+shotId);if(!active.current)return;const result=await service('filmmaking/shots/'+shotId+'/opening-frame/restore','POST',{job_id:job.id,expected_revision:job.revision,expected_image_revision:shot.image.revision});if(active.current){setJob(result.job);await callbacks.current.changed(result);}})}>Restore previous prompt</button>}{job.restored&&<p>Previous prompt restored.</p>}</details>}
  </>}
 </section>;
 return panel?createPortal(content,panel):content;
}
