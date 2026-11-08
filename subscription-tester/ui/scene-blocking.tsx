import React,{useEffect,useRef,useState} from 'react';
import {service} from './studio-service';
import {Camera,Staging,Subject,Prop,Eyeline,initialStaging,newSubject,drawStage,frameSize,cameraPosition,presets} from './filmmaking-model';

export function CameraSettings({camera:c,change}:{camera:Camera;change:(value:Partial<Camera>)=>void}){
 return <><h3>Camera</h3>{([
  ['yaw','Orbit',-180,180,1],['elevation','Elevation',-10,85,1],['distance','Distance',1,15,.1],
  ['lens','Lens · mm',18,120,1],['target_y','Look-at height',.1,3,.1],['target_x','Look-at horizontal',-5,5,.1],['target_z','Look-at depth',-5,5,.1]
 ] as const).map(([key,label,min,max,step])=><label className="ft-range" key={key}><span>{label}<output>{Number(c[key].toFixed(1))}</output></span>
  <input type="range" aria-label={label} min={min} max={max} step={step} value={c[key]} onChange={e=>change({[key]:Number(e.target.value)})}/></label>)}</>;
}

type Geometry=Pick<Staging,'subjects'|'environment'|'style'>&{props:Prop[];eyelines:Eyeline[]};
type ActorMark=Pick<Subject,'x'|'z'|'rotation'|'pose'|'arms'|'head'>&{subject:number};
type View={id:string;name:string;camera:Camera;marks?:ActorMark[]};
type Layout={id?:string;revision:number;title:string;geometry:Geometry;views:View[]};
type Link={revision:number;layout_id:string|null;view_id:string|null};
const defaultProp:Prop={name:'Prop',x:1,y:0,z:0,width:.6,height:.6,depth:.6,rotation:0};
const newView=(name:string,camera:Camera):View=>({id:crypto.randomUUID(),name,camera});
function blank(stage:Staging):Layout{
 return {revision:0,title:'Scene layout',geometry:{subjects:stage.subjects,environment:stage.environment,style:stage.style,props:[],eyelines:[]},views:[newView('Camera 1',stage.camera)]};
}
const axes=[['x','Horizontal',-5,5],['z','Depth',-5,5]] as const;
function Controls<T extends object>({item,fields,change,prefix=''}:{item:T;fields:readonly (readonly [keyof T,string,number,number])[];change:(patch:Partial<T>)=>void;prefix?:string}){
 return <>{fields.map(([key,label,min,max])=><label className="ft-range" key={String(key)}><span>{label}<output>{Number(Number(item[key]).toFixed(2))}</output></span>
  <input type="range" aria-label={prefix+label} min={min} max={max} step={.01} value={Number(item[key])} onChange={e=>change({[key]:Number(e.target.value)} as Partial<T>)}/></label>)}</>;
}

export function SceneBlocking({shotId,staging,onDirty}:{shotId:string;staging:Staging;onDirty:(dirty:boolean)=>void}){
 const [path,setPath]=useState(''),[list,setList]=useState<Layout[]>([]),[layout,setLayout]=useState<Layout|null>(null);
 const [link,setLink]=useState<Link|null>(null),[viewId,setViewId]=useState(''),[actor,setActor]=useState(0),[prop,setProp]=useState(0);
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false);
 const canvas=useRef<HTMLCanvasElement>(null);
 const linkPath='filmmaking/shots/'+shotId+'/blocking';
 function open(next:Layout,id?:string){
  setLayout(next);setViewId(next.views.find(v=>v.id===id)?.id||next.views[0].id);
  setActor(0);setProp(0);setDirty(false);onDirty(false);
 }
 useEffect(()=>{
  let current=true;
  (async()=>{
   const [shot,savedLink]=await Promise.all([service('productions/shots/'+shotId),service<Link>(linkPath)]);
   const url='filmmaking/blocking/'+shot.production_id+'/'+(shot.episode_id||'quick');
   const layouts=await service<Layout[]>(url);
   const saved=savedLink.layout_id?await service<Layout>(url+'/'+savedLink.layout_id):null;
   if(current){setPath(url);setList(layouts);setLink(savedLink);open(saved||blank(staging),savedLink.view_id||undefined);}
  })().catch(e=>{if(current)setError(e.message);});
  return()=>{current=false;onDirty(false);};
 },[shotId]);
 const view=layout?.views.find(v=>v.id===viewId);
 const stage=layout&&view?{...layout.geometry,camera:view.camera,ratio:'9:16',
  subjects:layout.geometry.subjects.map((subject,i)=>({...subject,...view.marks?.find(m=>m.subject===i)}))}:null;
 useEffect(()=>{if(canvas.current&&stage)drawStage(canvas.current,stage);},[layout,viewId]);
 async function run(fn:()=>Promise<void>){
  setBusy(true);setError('');setNotice('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 function edit(patch:Partial<Layout>){
  setLayout(previous=>previous?{...previous,...patch}:previous);setDirty(true);onDirty(true);
 }
 function switchLayout(id:string){
  if(dirty&&!window.confirm('Discard unsaved scene blocking changes?'))return;
  void run(async()=>open(id?await service<Layout>(path+'/'+id):blank(staging),id===link?.layout_id?link.view_id||undefined:undefined));
 }
 if(!layout||!view||!stage)return <p role={error?'alert':'status'}>{error||'Loading scene blocking…'}</p>;
 const g=layout.geometry,s=stage.subjects[actor],p=g.props[prop],eye=g.eyelines.find(e=>e.subject===actor),cameraEye=cameraPosition(view.camera);
 const mark=view.marks?.find(m=>m.subject===actor);
 function geometry(patch:Partial<Geometry>){edit({geometry:{...g,...patch}});}
 function sharedActor(patch:Partial<Subject>){geometry({subjects:g.subjects.map((value,i)=>i===actor?{...value,...patch}:value)});}
 function saveMark(value?:ActorMark){
  const marks=(view!.marks||[]).filter(m=>m.subject!==actor);
  edit({views:layout!.views.map(v=>v.id===viewId?{...v,marks:value?[...marks,value]:marks}:v)});
 }
 function moveActor(patch:Partial<ActorMark>){if(mark)saveMark({...mark,...patch});else sharedActor(patch);}
 function moveProp(patch:Partial<Prop>){geometry({props:g.props.map((value,i)=>i===prop?{...value,...patch}:value)});}
 function moveEye(patch:Partial<Eyeline>){
  const target={subject:actor,x:0,y:1.65,z:0,...eye,...patch};
  geometry({eyelines:[...g.eyelines.filter(value=>value.subject!==actor),target]});
 }
 function camera(patch:Partial<Camera>){edit({views:layout!.views.map(v=>v.id===viewId?{...v,camera:{...v.camera,...patch}}:v)});}
 const size=frameSize('9:16'),isLinked=link?.layout_id===layout.id&&link?.view_id===viewId;
 return <>
  <div className="ft-presets">
   <label>Scene layout<select value={layout.id||''} disabled={busy} onChange={e=>switchLayout(e.target.value)}>
    <option value="">New layout from shot staging</option>{list.map(value=><option key={value.id} value={value.id}>{value.title}</option>)}
   </select></label>
   <label>Layout name<input disabled={busy} maxLength={120} value={layout.title} onChange={e=>edit({title:e.target.value})}/></label>
   <label>Camera view<select disabled={busy} value={viewId} onChange={e=>setViewId(e.target.value)}>{layout.views.map(value=><option key={value.id} value={value.id}>{value.name}{link?.layout_id===layout.id&&link?.view_id===value.id?' · Used by this shot':''}</option>)}</select></label>
   <label>View name<input disabled={busy} maxLength={80} value={view.name} onChange={e=>edit({views:layout.views.map(v=>v.id===viewId?{...v,name:e.target.value}:v)})}/></label>
   <button disabled={busy||layout.views.length>=16} onClick={()=>{const value=newView('Camera '+(layout.views.length+1),view.camera);edit({views:[...layout.views,value]});setViewId(value.id);}}>Add camera view</button>
   <button disabled={busy||layout.views.length<=1||isLinked} onClick={()=>{const views=layout.views.filter(v=>v.id!==viewId);edit({views});setViewId(views[0].id);}}>Remove view</button>
  </div>
  {error&&<p className="ft-error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  <fieldset disabled={busy} style={{border:0,padding:0,minWidth:0}}>
  <div className="ft-camera-layout"><div className="ft-camera-center">
   <div className="ft-camera-preview" style={{aspectRatio:'9 / 16',width:'min(100%, 32vh)',marginInline:'auto'}}>
    <canvas ref={canvas} width={size.width} height={size.height} aria-label="Portrait scene blocking preview"/>
   </div>
   <div className="ft-map-row"><div><h3>Top view</h3>
    <svg viewBox="-7 -7 14 14" role="img" aria-label="Plan view showing props, actors, camera and eyelines">
     <rect x="-7" y="-7" width="14" height="14" fill="#112b25"/>
     {g.props.map((value,i)=><rect key={i} x={value.x-value.width/2} y={value.z-value.depth/2}
      width={value.width} height={value.depth} transform={`rotate(${-value.rotation} ${value.x} ${value.z})`}
      fill={i===prop?'#d4ad83':'#8a6c4d'}><title>{value.name}</title></rect>)}
     {g.eyelines.map(value=><path key={value.subject} d={`M${stage.subjects[value.subject].x} ${stage.subjects[value.subject].z}L${value.x} ${value.z}`}
      stroke="#f8d993" strokeWidth=".05" strokeDasharray=".15 .1"/>)}
     <path d={`M${cameraEye[0]} ${cameraEye[2]}L${view.camera.target_x} ${view.camera.target_z}`} stroke="white" strokeWidth=".05"/>
     <circle cx={cameraEye[0]} cy={cameraEye[2]} r=".18" fill="white"/>
     {stage.subjects.map((value,i)=><g key={i}><circle cx={value.x} cy={value.z} r=".3" fill={i===actor?'#99e4c2':'#84a89b'}/>
      <text x={value.x} y={value.z+.12} textAnchor="middle" fontSize=".35" fill="#112b25">{i+1}</text><title>{value.name}</title></g>)}
    </svg></div><div>
     <label>Environment<textarea rows={2} value={g.environment} maxLength={800} onChange={e=>geometry({environment:e.target.value})}/></label>
     <label>Look<input value={g.style} maxLength={500} onChange={e=>geometry({style:e.target.value})}/></label>
    </div></div>
   <div className="ft-presets">{Object.entries(presets).map(([name,value])=><button key={name} onClick={()=>camera({...initialStaging().camera,...value})}>{name}</button>)}</div>
  </div><aside className="ft-camera-inspector">
   <CameraSettings camera={view.camera} change={camera}/>
   <h3>Actors</h3>
   <label>Actor<select value={actor} onChange={e=>setActor(Number(e.target.value))}>{g.subjects.map((value,i)=><option key={i} value={i}>{i+1}. {value.name}</option>)}</select></label>
   <button disabled={g.subjects.length>=4} onClick={()=>{geometry({subjects:[...g.subjects,newSubject(g.subjects.length)]});setActor(g.subjects.length);}}>Add actor</button>
   <button disabled={g.subjects.length<=1} onClick={()=>{
    const keep=<T extends {subject:number},>(items:T[])=>items.filter(value=>value.subject!==actor)
     .map(value=>({...value,subject:value.subject>actor?value.subject-1:value.subject}));
    edit({geometry:{...g,subjects:g.subjects.filter((_,i)=>i!==actor),eyelines:keep(g.eyelines)},
     views:layout.views.map(value=>({...value,marks:keep(value.marks||[])}))});setActor(0);
   }}>Remove actor</button>
   <label>Actor name<input maxLength={80} value={s.name} onChange={e=>sharedActor({name:e.target.value})}/></label>
   <label><input type="checkbox" checked={!!mark} onChange={e=>{
    const {x,z,rotation,pose,arms,head}=s;
    saveMark(e.target.checked?{subject:actor,x,z,rotation,pose,arms,head}:undefined);
   }}/> Set an actor mark for this view</label>
   <p className="p-muted">{mark?'Pose controls edit the selected view’s actor mark.':'Pose controls edit the shared layout.'}</p>
   <label>Pose<select value={s.pose} onChange={e=>moveActor({pose:e.target.value})}>{['stand','walk','sit','crouch','reach','fight','slide'].map(value=><option key={value}>{value}</option>)}</select></label>
   <Controls<Subject> item={s} fields={[...axes,['rotation','Facing',-180,180],['arms','Arm lift',-90,150],['head','Head turn',-60,60]]} change={moveActor} prefix="Actor "/>
   <label><input type="checkbox" checked={!!eye} onChange={e=>e.target.checked?moveEye({x:s.x,z:Math.max(-5,s.z-1)}):geometry({eyelines:g.eyelines.filter(v=>v.subject!==actor)})}/> Eyeline target</label>
   {eye&&<Controls item={eye} fields={[...axes,['y','Height',0,5]]} change={moveEye} prefix="Eyeline "/>}
   <h3>Props</h3>
   <button disabled={g.props.length>=24} onClick={()=>{geometry({props:[...g.props,{...defaultProp,name:'Prop '+(g.props.length+1)}]});setProp(g.props.length);}}>Add prop</button>
   {p&&<>
    <label>Prop<select value={prop} onChange={e=>setProp(Number(e.target.value))}>{g.props.map((value,i)=><option key={i} value={i}>{value.name}</option>)}</select></label>
    <label>Prop name<input maxLength={80} value={p.name} onChange={e=>moveProp({name:e.target.value})}/></label>
    <Controls item={p} fields={[...axes,['y','Base height',0,4],['width','Width',.02,8],['height','Height',.02,5],['depth','Length',.02,8],['rotation','Rotation',-180,180]]} change={moveProp} prefix="Prop "/>
    <button onClick={()=>{geometry({props:g.props.filter((_,i)=>i!==prop)});setProp(0);}}>Remove prop</button>
   </>}
  </aside></div></fieldset>
  <footer className="ft-build-bar">
   <button disabled={busy||(!dirty&&!!layout.id)} onClick={()=>void run(async()=>{
    const payload={title:layout.title,geometry:g,views:layout.views};
    const saved=layout.id?await service<Layout>(path+'/'+layout.id,'PUT',{...payload,expected_revision:layout.revision}):
     await service<Layout>(path,'POST',payload);
    setLayout(saved);setDirty(false);onDirty(false);setList(await service(path));setNotice('Scene layout saved.');
   })}>Save scene layout</button>
   <button disabled={busy||!layout.id||!dirty} onClick={()=>switchLayout(layout.id!)}>Reload saved layout</button>
   <button disabled={busy||dirty||!layout.id||isLinked||!link} onClick={()=>void run(async()=>{
    setLink(await service<Link>(linkPath,'PUT',{expected_revision:link!.revision,
     layout_id:layout.id,view_id:viewId,expected_layout_revision:layout.revision}));setNotice('This shot now uses the saved camera view.');
   })}>Use view for this shot</button>
   {link?.layout_id&&<button disabled={busy} onClick={()=>void run(async()=>{
    setLink(await service<Link>(linkPath,'PUT',{expected_revision:link.revision,layout_id:null,view_id:null}));setNotice('Shared view unlinked.');
   })}>Unlink shot view</button>}
   <button disabled={busy||dirty||!layout.id} onClick={()=>void run(async()=>{
    const response=await fetch(`/api/agent/${path}/${layout.id}/views/${viewId}/reference.png`,{
     method:'POST',headers:{'Content-Type':'application/json','X-Tester':'local'},body:JSON.stringify({expected_revision:layout.revision})
    });
    if(!response.ok){const failure=await response.json();throw Error(failure.error?.message||'Could not export this view.');}
    const url=URL.createObjectURL(await response.blob());const anchor=document.createElement('a');
    anchor.href=url;anchor.download='composition.png';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
   })}>Export portrait PNG</button>
  </footer>
 </>;
}
