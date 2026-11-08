import React,{useEffect,useState} from 'react';
import {thumbnail} from './studio-runtime';
import {service,useDialog} from './studio-service';

type Frame={shot_id:string;title:string;asset_id:string;src:string;name:string;role:string;timestamp_s:number|null;state?:unknown};
type Review={id:string;revision:number;title:string;consistent:string;changes:string;findings:string;frames:Frame[]};
type FrameGroup={shot_id:string;title:string;frames:Frame[]};
const frameLabel=(frame:Frame)=>frame.role+(frame.timestamp_s===null?'':` · ${Number(frame.timestamp_s.toFixed(2))}s`);
export function ContinuityReview({productionId,episodeId,close,prepare,changed}:{
 productionId:string;episodeId:string|null;close:()=>void;prepare:()=>Promise<void>;changed:()=>Promise<void>;
}){
 const path=`productions/continuity/${productionId}/${episodeId||'quick'}`;
 const [groups,setGroups]=useState<FrameGroup[]>([]),[reviews,setReviews]=useState<Review[]>([]);
 const [review,setReview]=useState<Review|null>(null),[choices,setChoices]=useState(['','']);
 const [target,setTarget]=useState(''),[side,setSide]=useState(1),[mode,setMode]=useState('both');
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false);
 const frames=groups.flatMap(group=>group.frames.map(frame=>({...frame,shot_id:group.shot_id,title:group.title})));
 useDialog(()=>{if(!busy&&(!dirty||window.confirm('Discard unsaved review notes?')))close();},'Frame Continuity Review',true);
 useEffect(()=>{
  Promise.all([service<FrameGroup[]>(path+'/frames'),service<Review[]>(path)])
   .then(([g,r])=>{setGroups(g);setReviews(r);}).catch(e=>setError(e.message));
 },[path]);
 useEffect(()=>{
  if(!dirty)return;
  const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};
  const previous=window.studioOverlayFlush;
  window.studioOverlayFlush=async()=>{throw Error('Save your continuity review before switching shots.');};
  window.addEventListener('beforeunload',guard);
  return()=>{window.removeEventListener('beforeunload',guard);window.studioOverlayFlush=previous;};
 },[dirty]);
 async function run(fn:()=>Promise<void>){
  setBusy(true);setError('');setNotice('');
  try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 function load(value:Review|null){
  setReview(value);setDirty(false);setTarget('');
 }
 const displayed=review?.frames||choices.flatMap(choice=>choice===''?[]:[frames[Number(choice)]]);
 const fields=[['title','Review title',120],['consistent','What should stay consistent',6000],['changes','What intentionally changes',6000],['findings','Findings from inspecting the images',12000]] as const;
 return <div className="p-modal-backdrop"><section className="p-modal p-takes" role="dialog" aria-modal="true" aria-label="Frame Continuity Review">
  <div className="p-section-head"><h2>Frame Continuity Review</h2><button aria-label="Close frame review" disabled={busy} onClick={()=>{if(!dirty||window.confirm('Discard unsaved review notes?'))close();}}>×</button></div>
  <label>Saved review<select value={review?.id||''} disabled={busy} onChange={e=>{
   const id=e.target.value;if(dirty&&!window.confirm('Discard unsaved review notes?'))return;
   void run(async()=>load(id?await service<Review>(path+'/'+id):null));
  }}><option value="">New comparison</option>{reviews.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
  {!review&&<>{choices.map((choice,i)=><label key={i}>Frame {i+1}<select value={choice} disabled={busy} onChange={e=>setChoices(old=>old.map((v,j)=>i===j?e.target.value:v))}>
   <option value="">Choose an image</option>{frames.map((frame,j)=><option key={j} value={j}>{frame.title} · {frameLabel(frame)} · {frame.name} ({frame.asset_id.slice(0,8)})</option>)}
  </select></label>)}<button disabled={busy||choices.some(c=>c==='')||choices[0]===choices[1]} onClick={()=>void run(async()=>{
   const value=await service<Review>(path,'POST',{frames:choices.map(c=>{const {shot_id,asset_id,role,timestamp_s}=frames[Number(c)];return {shot_id,asset_id,role,timestamp_s};})});
   setReviews(old=>[...old,value]);load(value);
  })}>Create review</button></>}
  {!!displayed.length&&<><div className="p-shot-actions" aria-label="Frame display">
   {['both','0','1'].map((value,i)=><button key={value} aria-pressed={mode===value} onClick={()=>setMode(value)}>{['Side by side','Frame 1','Frame 2'][i]}</button>)}
  </div><div style={{display:'grid',gridTemplateColumns:mode==='both'?'repeat(2,minmax(0,1fr))':'minmax(0,1fr)',gap:12}}>
   {displayed.map((frame,i)=>(mode==='both'||mode===String(i))&&<figure key={i} style={{margin:0}}>
    <img style={{width:'100%',maxHeight:'48vh',objectFit:'contain'}} src={frame.src} alt={`${frame.title} · ${frameLabel(frame)}`}/>
    <figcaption>{frame.title} · {frameLabel(frame)}</figcaption>
    {frame.state!==undefined&&<details><summary>Saved shot state</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:240,overflow:'auto'}}>{JSON.stringify(frame.state,null,2)}</pre></details>}
   </figure>)}
  </div></>}
  {review&&<>{fields.map(([field,label,max])=><label key={field}>{label}{field==='title'?
   <input disabled={busy} maxLength={max} value={review[field]} onChange={e=>{setReview({...review,[field]:e.target.value});setDirty(true);}}/>:
   <textarea disabled={busy} maxLength={max} rows={3} value={review[field]} onChange={e=>{setReview({...review,[field]:e.target.value});setDirty(true);}}/>}</label>)}
   <div className="p-shot-actions"><button disabled={busy||!dirty} onClick={()=>void run(async()=>{
    const {revision,title,consistent,changes,findings}=review;
    const saved=await service<Review>(path+'/'+review.id,'PUT',{expected_revision:revision,title,consistent,changes,findings});
    setReview(saved);setDirty(false);setReviews(old=>old.map(r=>r.id===saved.id?saved:r));setNotice('Review saved.');
   })}>Save review</button><button disabled={busy} onClick={()=>{if(!dirty||window.confirm('Discard unsaved review notes?'))void run(async()=>load(await service(path+'/'+review.id)));}}>Reload saved review</button></div>
   <h3>Attach a reviewed frame</h3>
   <label>Reviewed side<select value={side} onChange={e=>{setSide(Number(e.target.value));setTarget('');}}><option value={0}>Frame 1</option><option value={1}>Frame 2</option></select></label>
   <label>Destination shot<select value={target} onChange={e=>setTarget(e.target.value)}><option value="">Choose the destination shot</option>{groups.filter(g=>g.shot_id!==review.frames[side].shot_id).map(g=><option key={g.shot_id} value={g.shot_id}>{g.title}</option>)}</select></label>
   <button disabled={busy||dirty||!target||!review.findings.trim()} onClick={()=>void run(async()=>{
    await prepare();const shot=await service('productions/shots/'+target);
    const video=await service(path+'/'+review.id+'/attach','POST',{expected_revision:review.revision,side,target_shot_id:target,expected_video_revision:shot.video?.revision??0});
    const adjusted=shot.video?.scene.resolution==='1080p'&&video.scene.resolution==='720p';
    await changed();
    setNotice('Reviewed image attached to the destination video draft.'+(adjusted?' References use at most 720p. The draft now uses 720p.':''));
   })}>Attach as video reference</button></>}
  {error&&<p role="alert" className="p-error-inline">{error}</p>}{notice&&<p role="status">{notice}</p>}
 </section></div>;
}

type Preview={
 model:string;resolution:string;aspect_ratio:string;render_duration:number;intended_edit_duration:number|null;
 shot_revision:number;video_revision:number;valid:boolean;
 images:{field:string;role:string;tag:string|null;identity:string|null;timestamp_s:number|null;name:string;src:string|null}[];
 voices:{speaker:string|null;voice_id:string;included:boolean;tag:string}[];
 recording:{excerpt_id:string}|null;request:{prompt?:string}|null;
 issues:{field:string;code:string;message:string;severity:string}[];
};
export function GenerationPreview({shotId,close}:{shotId:string;close:()=>void}){
 const shotPath='productions/shots/'+shotId;
 const [preview,setPreview]=useState<Preview|null>(null),[duration,setDuration]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useDialog(()=>{if(!busy)close();},'Generation Request Preview',true);
 async function load(){
  const value=await service<Preview>(shotPath+'/generation-preview');
  setPreview(value);setDuration(value.intended_edit_duration?.toString()||'');
 }
 async function run(fn:()=>Promise<void>){
  setBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 useEffect(()=>{void run(load);},[shotId]);
 return <div className="p-modal-backdrop"><section className="p-modal p-takes" role="dialog" aria-modal="true" aria-label="Generation Request Preview">
  <div className="p-section-head"><h2>Generation Request Preview</h2><button aria-label="Close request preview" disabled={busy} onClick={close}>×</button></div>
  <p className="p-muted">Saved video inputs. Open the shot’s video editor to change images, voices or render settings.</p>
  <button disabled={busy} onClick={()=>void run(load)}>Refresh saved inputs</button>
  {error&&<p role="alert" className="p-error-inline">{error}</p>}
  {preview&&<>
   <p><strong>{preview.model}</strong> · {preview.resolution} · {preview.aspect_ratio} · {preview.render_duration}s render</p>
   <form onSubmit={e=>{e.preventDefault();void run(async()=>{
    await service(shotPath,'PUT',{expected_revision:preview.shot_revision,intended_edit_duration:duration===''?null:Number(duration)});
    await load();
   });}}>
    <label>Intended edit duration (seconds)<input type="number" step="any" min="0.001" max="3600" value={duration} disabled={busy} onChange={e=>setDuration(e.target.value)}/></label>
    <button disabled={busy||duration===(preview.intended_edit_duration?.toString()||'')}>Save edit duration</button>
   </form>
   <h3>Image inputs</h3>
   <div className="p-take-grid">{preview.images.map(item=><figure key={item.field} style={{margin:0}}>
    {item.src&&<img src={thumbnail(item.src,480)} referrerPolicy="no-referrer" alt={item.name} style={{width:'100%',maxHeight:200,aspectRatio:'auto',objectFit:'contain'}}/>}
    <figcaption>{item.role}{item.timestamp_s!==null&&` · ${Number(item.timestamp_s.toFixed(2))}s`}{item.tag&&` · ${item.tag}`}<br/>{item.identity||item.name}<br/><small>{item.field}</small></figcaption>
   </figure>)}</div>
   {!preview.images.length&&<p className="p-muted">No image inputs.</p>}
   <h3>Speaker voices</h3>
   {preview.voices.map(v=><p key={v.tag}>{v.speaker||'Unlabeled speaker'} · <code>{v.voice_id}</code> · {v.included?v.tag:'Audio disabled'}</p>)}
   {preview.recording&&<p>Uploaded recording excerpt · <code>{preview.recording.excerpt_id}</code></p>}
   {!preview.voices.length&&!preview.recording&&<p className="p-muted">No assigned voice or recording.</p>}
   <h3>{preview.valid?'Compiled request':'Request needs attention'}</h3>
   {preview.issues.length>0&&<ul>{preview.issues.map((issue,i)=><li key={i}><strong>{issue.severity==='error'?'Error':'Review'} · {issue.field}</strong> {issue.message}</li>)}</ul>}
   {preview.request?.prompt&&<details><summary>Compiled prompt</summary><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{preview.request.prompt}</p></details>}
  </>}
 </section></div>;
}
