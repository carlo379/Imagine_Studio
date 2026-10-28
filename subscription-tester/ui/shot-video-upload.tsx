import React,{useEffect,useRef,useState} from 'react';
import {service} from './navigation';
declare global {interface Window {studioShotVideoUploading?:boolean}}
export function ShotVideoUpload({shot,prepare,uploaded}:{shot:{id:string;revision:number;title:string};prepare:()=>Promise<void>;uploaded:(result:any)=>Promise<void>}){
 const panel=useRef<HTMLDetailsElement>(null);
 const running=useRef(false);
 useEffect(()=>{const open=(event:Event)=>{if((event as CustomEvent).detail?.shotId!==shot.id)return;if(panel.current){panel.current.open=true;panel.current.scrollIntoView?.({block:'center'});panel.current.querySelector<HTMLButtonElement>('button')?.focus();}};window.addEventListener('shot-video-upload-open',open);return()=>window.removeEventListener('shot-video-upload-open',open);},[shot.id]);
 const input=useRef<HTMLInputElement>(null),[source,setSource]=useState('Seedance'),[select,setSelect]=useState(true),[phase,setPhase]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[pending,setPending]=useState<string|null>(null);
 useEffect(()=>()=>{window.studioShotVideoUploading=false;},[]);
 async function attach(mediaId:string){return service('productions/shots/'+shot.id+'/import-video','POST',{expected_revision:shot.revision,media_id:mediaId,source_label:source.trim()||'External video',select});}
 async function run(file?:File){
  if(running.current)return;running.current=true;setPhase('Preparing shot…');setError('');setNotice('');
  let mediaId=pending;
  try{
   if(file){if(!/\.(mp4|mov|webm)$/i.test(file.name))throw Error('Choose an MP4, MOV or WebM video.');if(!file.size||file.size>64*1024*1024)throw Error('Choose a video up to 64 MB.');}
   await prepare();window.studioShotVideoUploading=true;
   if(file){setPending(null);mediaId=null;setPhase('Reading video…');const base64=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Could not read this video.'));reader.readAsDataURL(file);});setPhase('Uploading and checking video…');const media=await service('editing/media','POST',{name:file.name,base64});mediaId=media.id;setPending(mediaId);}
   if(!mediaId)throw Error('Choose a video to upload.');
   setPhase('Attaching video to this shot…');const result=await attach(mediaId);setPending(null);await uploaded(result);setNotice(select?'Video uploaded and selected for this shot.':'Video uploaded. Choose it in Shot details & takes when ready.');
  }catch(e){setError((mediaId?'The file is saved in Library → Uploads. ':'')+(e as Error).message);}finally{running.current=false;window.studioShotVideoUploading=false;setPhase('');if(input.current)input.current.value='';}
 }
 return <details ref={panel} className="p-shot-video-upload"><summary>Upload video to this shot</summary><p className="p-muted">Bring in a clip from Seedance or another tool. The original file and existing takes stay available.</p><div className="p-upload-options"><label>Source<input value={source} maxLength={120} disabled={!!phase} onChange={e=>setSource(e.target.value)}/></label><label className="p-upload-select"><input type="checkbox" checked={select} disabled={!!phase} onChange={e=>setSelect(e.target.checked)}/>Select uploaded video for this shot</label></div><input ref={input} type="file" accept=".mp4,.mov,.webm" hidden onChange={e=>{const file=e.target.files?.[0];if(file)void run(file);}}/><button className="p-primary" disabled={!!phase} onClick={()=>input.current?.click()}>＋ Upload video</button><small> MP4, MOV or WebM · Up to 64 MB · Original resolution</small>{phase&&<p className="p-video-upload-progress" role="status"><span className="vr-spinner" aria-hidden="true"/>{phase}</p>}{notice&&<p role="status">{notice}</p>}{error&&<p className="p-error-inline" role="alert">{error}</p>}{pending&&!phase&&<button onClick={()=>void run()}>Retry attaching saved upload</button>}</details>;
}
