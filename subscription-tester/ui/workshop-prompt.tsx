import React,{useEffect,useRef,useState} from 'react';
import {service} from './studio-service';
import {viewPromptReady} from './media-prompting';

/** Inline authoring/review only. Rendering belongs to step 04. */
export function WorkshopPrompt({view,model,brief,instruction,disabled,save,refresh,continueToGenerate}:{view:any;model:string;brief?:string;instruction:string;disabled:boolean;save:()=>Promise<void>;refresh:()=>Promise<any>;continueToGenerate:()=>void}){
 const [draft,setDraft]=useState<any>(null),[job,setJob]=useState<any>(null),[text,setText]=useState(''),[error,setError]=useState(''),[working,setWorking]=useState(false),[reviewEdited,setReviewEdited]=useState(false);
 const alive=useRef(true),requesting=useRef(false),currentInputs=useRef('');
 const inputs=JSON.stringify([brief,instruction]);currentInputs.current=inputs;
 const jobInputs=useRef('');
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{let cancelled=false;setJob(null);setDraft(null);setReviewEdited(false);setError('');
  if(!view?.draft?.id)return;
  Promise.all([service('image-studio/drafts/'+view.draft.id),service('prompting/image/'+view.draft.id)]).then(([record,status]:any[])=>{
   if(cancelled)return;setDraft(record);setText(record.settings.prompt);
   if(status.current){setText(record.settings.prompt);setJob(status.job);jobInputs.current=inputs;return;}
   const saved=status.job;
   if(saved&&!saved.applied&&saved.media_revision===record.revision&&saved.instruction===instruction&&(brief===undefined||saved.brief===brief)){
    jobInputs.current=inputs;setJob(saved);if(saved.result)setText(saved.result.prompt);
   }
  }).catch(e=>{if(!cancelled)setError(e.message);});
  return()=>{cancelled=true;};
 },[view?.draft?.id]);
 useEffect(()=>{if(job?.status!=='pending')return;let cancelled=false,timer:ReturnType<typeof setTimeout>;
  const poll=async()=>{try{const value=await service('prompting/jobs/'+job.id);if(cancelled)return;setJob(value);if(value.result){setText(value.result.prompt);setReviewEdited(false);}if(value.status==='pending')timer=setTimeout(poll,1400);}catch(e:any){if(!cancelled){setError(e.message);timer=setTimeout(poll,2500);}}};
  timer=setTimeout(poll,1400);return()=>{cancelled=true;clearTimeout(timer);};
 },[job?.id,job?.status]);
 const pending=job?.status==='pending',ready=viewPromptReady(view,model,brief,instruction),proposal=job?.status==='done'&&!job.applied&&jobInputs.current===inputs;
 async function start(){if(requesting.current)return;requesting.current=true;setWorking(true);setError('');
  const captured=inputs;
  try{await save();const workshop=await refresh(),latest=workshop.views.find((v:any)=>v.id===view.id);
   const value=await service('filmmaking/assets/'+view.id+'/prompt-draft','POST',{expected_revision:latest.revision,model,...(brief!==undefined?{brief}:{})});
   if(!alive.current)return;setDraft(value.draft);jobInputs.current=captured;
   const result=await service('prompting/image/'+value.draft.id,'POST',{expected_revision:value.draft.revision,approved:true,provider:model.startsWith('grok-')?'grok':'codex',instruction,force:true},crypto.randomUUID());
   if(!alive.current)return;setJob(result);setReviewEdited(false);if(result.result)setText(result.result.prompt);await refresh();
  }catch(e:any){if(alive.current)setError(e.message);}finally{requesting.current=false;if(alive.current)setWorking(false);}
 }
 async function apply(){if(requesting.current)return;requesting.current=true;setWorking(true);setError('');
  try{await save();if(currentInputs.current!==jobInputs.current)throw Error('Direction changed. Prepare the prompt again before continuing.');
   await service('prompting/image/'+draft.id+'/apply','POST',{job_id:job.id,expected_revision:job.revision,expected_media_revision:draft.revision,prompt:text});
   await refresh();if(alive.current){setReviewEdited(false);continueToGenerate();}
  }catch(e:any){if(alive.current)setError(e.message);}finally{requesting.current=false;if(alive.current)setWorking(false);}
 }
 async function useOwnPrompt(){if(requesting.current)return;requesting.current=true;setWorking(true);setError('');
  try{await save();const snapshot=await refresh(),latest=snapshot.views.find((v:any)=>v.id===view.id);
   const value=await service('filmmaking/assets/'+view.id+'/prompt-draft','POST',{expected_revision:latest.revision,model,brief:text});
   await service('image-studio/drafts/'+value.draft.id+'/review-prompt','POST',{expected_revision:value.draft.revision,reviewed:true,authored_by:'human'});
   await refresh();setReviewEdited(false);continueToGenerate();
  }catch(e:any){if(alive.current)setError(e.message);}finally{requesting.current=false;if(alive.current)setWorking(false);}
 }
 return <div className="wb-inline-prompt">
  <p className="ft-note">Write and review your own prompt, or optionally ask AI to prepare it. The Bible controls appearance; regenerate mismatches unless you explicitly preview and confirm a Bible change.</p>
  <p role="status" className="wb-generation-status">{pending||working?'Preparing or saving your prompt…':ready?'Your reviewed prompt is ready.':proposal?'Prompt ready for review. No images have been generated.':'Prepare your image prompt to continue.'}</p>
  {error&&<p role="alert" className="wb-error">{error}</p>}{job?.status==='error'&&<p role="alert" className="wb-error">{job.error}</p>}
  {<><label>Image prompt · review and edit<textarea aria-label="Prepared image prompt" rows={12} maxLength={50000} disabled={disabled||working||pending} value={text} onChange={e=>{setText(e.target.value);setReviewEdited(true);}}/></label>
   {!!job?.result?.notes?.length&&<ul className="wb-prompt-notes">{job.result.notes.map((note:string,i:number)=><li key={i}>{note}</li>)}</ul>}
   <details><summary>Preparation details</summary><pre>{JSON.stringify({writer:job?.provider||view.draft.prompt_preparation?.writer,guides:job?.provenance?.guides||view.draft.prompt_preparation?.guides,usage:job?.writing_usage},null,2)}</pre></details></>}
  {job&&jobInputs.current!==inputs&&!ready&&<p className="ft-note">Direction changed. Prepare again to use your latest instructions.</p>}
  <div className="wb-prompt-actions"><button disabled={disabled||working||pending||!text.trim()} onClick={()=>void useOwnPrompt()}>I reviewed this prompt · continue →</button><button className={proposal||ready?undefined:"p-primary"} disabled={disabled||working||pending||!view||(brief!==undefined&&!brief.trim())} onClick={()=>void start()}>{pending?'Preparing…':proposal||ready?'Prepare again':'Prepare image prompt with AI'}</button>
   {(proposal||ready)&&<button className="p-primary" disabled={disabled||working||pending||!text.trim()||(ready&&reviewEdited&&!proposal)} onClick={()=>void(proposal?apply():continueToGenerate())}>{working?'Saving…':'Use prompt & continue →'}</button>}
  </div>{ready&&reviewEdited&&!proposal&&<p className="ft-note">Prepare again before changing an already reviewed prompt.</p>}
 </div>;
}
