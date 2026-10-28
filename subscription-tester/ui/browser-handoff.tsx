import React,{useEffect,useRef,useState} from 'react';
import {service} from './navigation';
import {editorSnapshots,stable} from './agent-editors';
type PendingDraft={id:string;revision:number;dirty:true;data:any};
declare global {interface Window {studioBookSnapshot?:()=>PendingDraft|null;studioTimelineSnapshot?:()=>PendingDraft|null;studioDevelopmentSnapshot?:()=>any}}
export function browserTab(){const key='imagine-handoff-tab';let id=sessionStorage.getItem(key);if(!id){id=crypto.randomUUID();sessionStorage.setItem(key,id);}return id;}
export async function browserHandoff(path='',method='GET',data?:any){
 const response=await fetch('/api/browser-handoff'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Tester':'local','X-Browser-Tab':browserTab(),...(window.studioWorkspaceId?{'X-Workspace-ID':window.studioWorkspaceId}:{})},body:method==='GET'?undefined:JSON.stringify(data||{})});
 const value=await response.json();if(!response.ok)throw Object.assign(Error(value.error?.message||'Browser handoff unavailable.'),{code:value.error?.code});return value;
}
export function AgentControls({route,navigate,view,applyView}:{route:()=>any;navigate:(r:any)=>Promise<void>;view:()=>any;applyView:(v:any)=>Promise<void>}){
 const latest=useRef({route,navigate,view,applyView});latest.current={route,navigate,view,applyView};
 const [requests,setRequests]=useState<any[]>([]),[enabled,setEnabled]=useState(false),[error,setError]=useState('');
 const running=useRef(false),pending=useRef<any[]>([]);
 async function execute(request:any,accept=true){
  if(running.current)return;running.current=true;setError('');
  try{
   if(!accept){await browserHandoff('/requests/'+request.id+'/ack','POST',{expected_revision:request.revision,status:'rejected'});return;}
   const current={route:latest.current.route(),editors:editorSnapshots()};
   if(stable(current)!==stable(request.expected_state))throw Error('The browser changed after this request. Read the tab again and retry.');
   const p=request.payload;
   if(request.kind==='identity'){
    window.dispatchEvent(new CustomEvent('studio-identity-request',{detail:request}));
    await browserHandoff('/requests/'+request.id+'/ack','POST',{expected_revision:request.revision,status:'awaiting_human'});
   }else{
    if(request.kind==='navigate'){await latest.current.navigate(p.route);await latest.current.applyView(p.view||{});}
    if(request.kind==='playback')await latest.current.applyView(p);
    if(request.kind==='resolve'){
     const editor=window.studioAgentEditors?.[p.editor],action=editor?.[p.action as 'save'|'reload'|'discard'];
     if(!action||stable(editor?.capture())!==stable(request.expected_editor))throw Error('The requested draft changed or closed. Read the tab again.');
     await action();
    }
    await browserHandoff('/requests/'+request.id+'/ack','POST',{expected_revision:request.revision,status:'completed'});
   }
  }catch(e){const message=(e as Error).message;setError(message);await browserHandoff('/requests/'+request.id+'/ack','POST',{expected_revision:request.revision,status:'failed',error:message.slice(0,500)}).catch(()=>{});}
  finally{running.current=false;pending.current=pending.current.filter(r=>r.id!==request.id);setRequests([...pending.current]);}
 }
 const executeRef=useRef(execute);executeRef.current=execute;
 useEffect(()=>{let alive=true,inflight=false;
  const poll=async()=>{if(inflight||running.current||document.hidden)return;inflight=true;try{const status=await browserHandoff();if(!status.sharing_enabled){if(alive)setRequests([]);return;}
   const state={route:latest.current.route(),editors:editorSnapshots(),view:latest.current.view()};
   const result=await browserHandoff('/tabs','POST',state);if(!alive)return;
   setEnabled(result.controls_enabled);pending.current=result.requests;setRequests(result.requests);
   const next=result.requests.find((r:any)=>result.controls_enabled&&r.kind!=='identity');if(next)await executeRef.current(next);
  }catch(e){if(alive)setError((e as Error).message);}finally{inflight=false;}};
  void poll();const timer=setInterval(poll,2000);return()=>{alive=false;clearInterval(timer);};
 },[]);
 return <details className="draft-handoff"><summary>Agent browser controls {enabled?'· Enabled':''}</summary><p>Enable draft sharing above to publish this tab. Browser controls allow agent requests to navigate, save, reload or discard the exact shared draft and control playback. Identity changes always require your action.</p><button type="button" aria-pressed={enabled} onClick={async()=>{try{const state=await browserHandoff('/controls/consent','POST',{enabled:!enabled});setEnabled(state.controls_enabled);}catch(e){setError((e as Error).message);}}}>{enabled?'Disable browser controls':'Allow browser controls for two hours'}</button>{requests.map(r=><div key={r.id}><p>Agent request: {r.kind} · {r.payload.action||r.payload.route?.page||'Update playback'}</p><button disabled={running.current} onClick={()=>void execute(r)}>Apply request</button><button disabled={running.current} onClick={()=>void execute(r,false)}>Decline</button></div>)}{error&&<p role="alert">{error}</p>}</details>;
}
export async function createReturnFlow(value:any){return browserHandoff('/flows','POST',value);}
export async function completeReturnFlow(flow:any){
 const path='handoff/flows/'+flow.id;
 for(let attempt=0;attempt<2;attempt++){
  const current=await service(path);if(current.status==='finished')return current;
  try{const applied=await browserHandoff('/flows/'+flow.id+'/returned','POST',{expected_revision:current.revision});return await service(path+'/finish','POST',{expected_revision:applied.revision});}
  catch(error){const latest=await service(path);if(latest.status==='finished')return latest;if(attempt===1||latest.revision===current.revision)throw error;}
 }
}
export function DraftHandoff({collect}:{collect:()=>any}){
 const capture=useRef(collect);capture.current=collect;
 const [enabled,setEnabled]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{let active=true;void browserHandoff().then(state=>{if(active)setEnabled(state.sharing_enabled);}).catch(()=>{});return()=>{active=false;};},[]);
 useEffect(()=>{if(!enabled)return;let active=true,publishing=false;
  const publish=async()=>{if(publishing||document.hidden)return;publishing=true;try{await browserHandoff('/drafts','POST',capture.current());if(active)setError('');}catch(e){if(active){setError((e as Error).message);if((e as any).code==='consent_required')setEnabled(false);}}finally{publishing=false;}};
  void publish();const timer=setInterval(publish,5000);return()=>{active=false;clearInterval(timer);};
 },[enabled]);
 async function toggle(){setBusy(true);setError('');try{const result=await browserHandoff('/drafts/consent','POST',{enabled:!enabled});setEnabled(result.sharing_enabled);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <details className="draft-handoff"><summary>Agent draft handoff {enabled?'· Sharing':''}</summary><p>Share a read-only view of pending book, image, video and timeline edits with agents in this local workspace. Saved work stays separate. Sharing lasts two hours; snapshots expire after ten minutes.</p><button type="button" disabled={busy} aria-pressed={enabled} onClick={()=>void toggle()}>{enabled?'Stop sharing & remove snapshot':'Share pending drafts'}</button>{error&&<p role="alert">{error}</p>}</details>;
}
