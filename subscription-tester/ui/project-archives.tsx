import React,{useEffect,useRef,useState} from 'react';
import {service} from './studio-service';
import {requestJSON} from './studio-runtime';
type Task={id:string;status:'working'|'done'|'error';message:string;progress:number;title?:string;download?:string;project_id?:string;report?:{complete:boolean;missing_files:string[];remote_references:string[]}};
function useArchiveTask(key:string,finished?:()=>Promise<void>){
 const [task,setTask]=useState<Task|null>(null),[error,setError]=useState('');const notified=useRef('');const done=useRef(finished);done.current=finished;
 useEffect(()=>{const id=sessionStorage.getItem(key);setTask(id?{id,status:'working',message:'Checking project transfer…',progress:0}:null);},[key]);
 useEffect(()=>{if(!task||task.status!=='working')return;let active=true,timer:ReturnType<typeof setTimeout>;async function poll(){try{const next=await service<Task>('project-archives/'+task!.id);if(!active)return;setTask(next);if(next.status==='working')timer=setTimeout(poll,1000);}catch(e){if(active){setError((e as Error).message);setTask(null);sessionStorage.removeItem(key);}}}void poll();return()=>{active=false;clearTimeout(timer);};},[task?.id,task?.status,key]);
 useEffect(()=>{if(task?.status==='done'&&notified.current!==task.id){notified.current=task.id;void done.current?.().catch(e=>setError((e as Error).message));}},[task?.id,task?.status]);
 function begin(next:Task){sessionStorage.setItem(key,next.id);setError('');setTask(next);}
 return {task,begin,error,setError};
}
type ExportFile={name:string;createWritable:()=>Promise<{write:(chunk:Uint8Array)=>Promise<void>;close:()=>Promise<void>;abort:()=>Promise<void>}>};
type SavePicker=(options:{id:string;suggestedName:string;types:{description:string;accept:Record<string,string[]>}[]})=>Promise<ExportFile>;
function ExportSave({task}:{task:Task}){
 const picker=(window as Window & {showSaveFilePicker?:SavePicker}).showSaveFilePicker;
 const [saving,setSaving]=useState(false),[saved,setSaved]=useState(''),[error,setError]=useState(''),[progress,setProgress]=useState<number|null>(null);
 useEffect(()=>{setSaved('');setError('');setProgress(null);},[task.id]);
 async function save(){
  if(!picker||saving)return;
  setSaving(true);setSaved('');setError('');setProgress(null);
  let writable:Awaited<ReturnType<ExportFile['createWritable']>>|undefined;
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  try{
   const name=(task.title||'Imagine Studio project').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').slice(0,120).trim()||'Imagine Studio project';
   // The picker must open directly from this click, before any network awaits.
   const file=await picker.call(window,{id:'imagine-project-export',suggestedName:name+'.zip',types:[{description:'Imagine Studio project ZIP',accept:{'application/zip':['.zip']}}]});
   const response=await fetch(task.download!);
   if(!response.ok||!response.body)throw Error('The export could not be downloaded. Try again.');
   const total=Number(response.headers.get('Content-Length'))||0;
   writable=await file.createWritable();reader=response.body.getReader();let received=0;
   while(true){const chunk=await reader.read();if(chunk.done)break;await writable.write(chunk.value);received+=chunk.value.byteLength;if(total)setProgress(Math.min(100,Math.round(received/total*100)));}
   await writable.close();writable=undefined;setSaved('Saved '+file.name+' to your chosen folder.');
  }catch(e){
   if(writable)await writable.abort().catch(()=>{});
   if((e as Error).name!=='AbortError')setError((e as Error).message||'Could not save the ZIP. Try downloading it instead.');
  }finally{if(reader){await reader.cancel().catch(()=>{});reader.releaseLock();}setSaving(false);}
 }
 return <div className="pl-export-save">{picker&&<button className="p-primary" disabled={saving} onClick={()=>void save()}>{saving?'Saving ZIP…':'Save ZIP as…'}</button>}{saving&&progress!==null&&<progress max={100} value={progress} aria-label="Saving ZIP progress"/>}<p><a href={task.download} download onClick={e=>{if(saving)e.preventDefault();}}>Download project ZIP</a></p>{!picker&&<p>Your browser handles the save location. Enable “Ask where to save each file” in its download settings to choose a folder for every export.</p>}{saved&&<p role="status">{saved}</p>}{error&&<p role="alert">{error}</p>}</div>;
}
function ArchiveResult({task}:{task:Task|null}){
 if(!task)return null;
 return <div className="pl-archive-result" role="status" aria-live="polite"><p>{task.message}</p>{task.status==='working'&&<progress max={100} value={task.progress} aria-label="Project transfer progress"/>}{task.status==='done'&&<>{task.report&&!task.report.complete&&<><p><strong>Some media could not be included.</strong> {task.report.missing_files?.length||0} missing files; {task.report.remote_references?.length||0} external references. See Export report.json inside the ZIP.</p><details><summary>Show missing media</summary><ul>{task.report.missing_files?.map(p=><li key={p}>{p}</li>)}{task.report.remote_references?.map(p=><li key={p}>{p}</li>)}</ul></details></>}{task.download&&<ExportSave key={task.id} task={task}/>}</>}</div>;
}
export function ProjectExport({projectId,prepare}:{projectId:string;prepare:()=>Promise<void>}){
 const {task,begin,error,setError}=useArchiveTask((window.studioStoragePrefix||'')+'project-export-'+projectId);const [starting,setStarting]=useState(false);
 async function start(){setStarting(true);setError('');try{await prepare();begin(await service<Task>('productions/'+projectId+'/export','POST'));}catch(e){setError((e as Error).message);}finally{setStarting(false);}}
 return <div className="pl-archive"><h3>Export complete project</h3><p>Save the Bible, storybooks, characters, locations, props, prompts, history, timelines and linked media in one portable ZIP. Related productions in this group are included.</p><button disabled={starting||task?.status==='working'} onClick={()=>void start()}>{starting?'Saving project…':task?.status==='working'?'Exporting project…':'Export project…'}</button><ArchiveResult task={task}/>{error&&<p role="alert">{error}</p>}</div>;
}
export function ProjectImport({prepare,changed,open}:{prepare:()=>Promise<void>;changed:()=>Promise<void>;open:(id:string)=>Promise<void>}){
 const {task,begin,error,setError}=useArchiveTask((window.studioStoragePrefix||'')+'project-import',changed);const [uploading,setUploading]=useState(false);const input=useRef<HTMLInputElement>(null);
 async function upload(file:File){setUploading(true);setError('');try{if(file.size>20*1024**3)throw Error('Project ZIP files must be at most 20 GB.');await prepare();begin(await requestJSON('/api/project-archives/import',{method:'POST',headers:{'X-Tester':'local','Content-Type':'application/zip'},body:file}));}catch(e){setError((e as Error).message);}finally{setUploading(false);if(input.current)input.current.value='';}}
 return <div className="pl-import"><input ref={input} type="file" accept=".zip,application/zip" aria-label="Choose project ZIP" hidden onChange={e=>{const file=e.target.files?.[0];if(file)void upload(file);}}/><button disabled={uploading||task?.status==='working'} onClick={()=>input.current?.click()}>{uploading?'Uploading project…':task?.status==='working'?'Importing project…':'Import project…'}</button><ArchiveResult task={task}/>{task?.status==='done'&&task.project_id&&<button onClick={()=>void open(task.project_id!).catch(e=>setError((e as Error).message))}>Open imported project</button>}{error&&<p role="alert">{error}</p>}</div>;
}
