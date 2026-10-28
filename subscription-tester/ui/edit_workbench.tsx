import React from 'react';
import {useDialog} from './studio-service';
import {AudioInspector,ColorInspector,PictureInspector} from './edit_tools';
import {Audio,Clip,Timeline,Title,Transition,clipLength,overlap,snap,duration} from './edit_model';

export function EditIcon({name}:{name:string}){
 const paths:Record<string,React.ReactNode>={
  play:<path d="m8 5 11 7-11 7Z"/>,pause:<path d="M8 5v14M16 5v14"/>,expand:<path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>,
  undo:<path d="m8 4-5 5 5 5M3 9h10a7 7 0 0 1 0 14"/>,redo:<path d="m16 4 5 5-5 5m5-5H11a7 7 0 0 0 0 14"/>,
  split:<><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8 8 12 12M8 16 20 4"/></>,
  marker:<path d="M6 3h12v18l-6-4-6 4Z"/>,plus:<path d="M12 5v14M5 12h14"/>,
  export:<path d="M14 4h6v6m0-6L10 14M9 4H4v16h16v-5"/>,refresh:<path d="M20 7v5h-5M4 17v-5h5m10-1a8 8 0 0 0-14-5m0 7a8 8 0 0 0 14 5"/>,
  film:<><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4m10 0h4M3 15h4m10 0h4"/></>,
  history:<path d="M3 4v5h5M4 9a9 9 0 1 1 0 8m8-11v6l4 2"/>,close:<path d="m6 6 12 12M6 18 18 6"/>
 };
 return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]||paths.film}</svg>;
}

export function EditDialog({close,busy,children}:{close:()=>void;busy:boolean;children:React.ReactNode}){
 useDialog(()=>{if(!busy)close();},'Export your edit',true);
 return <div className="ed-export-backdrop"><section className="ed-export-dialog" role="dialog" aria-modal="true" aria-label="Export your edit"><header><div><span className="p-eyebrow">LOCAL EXPORT</span><h2>Export your edit</h2></div><button disabled={busy} aria-label="Close export settings" onClick={close}><EditIcon name="close"/></button></header>{children}</section></div>;
}

type Info={duration:number;audio:boolean;image?:boolean;width?:number;height?:number};
export function WorkbenchInspector({timeline,item,title,kind,panel,setPanel,info,update,remove,transition,selectTake}:{
 timeline:Timeline;item:Clip|Audio|null|undefined;title:Title|null|undefined;kind?:'clip'|'audio'|'title';panel:string;setPanel:(panel:string)=>void;info?:Info;
 update:(patch:any)=>void;remove:()=>void;transition:(type:Transition['type'])=>void;selectTake:()=>void;
}){
 const fps=timeline.output.fps,still=item?.source.kind==='image'||info?.image,index=item?timeline.clips.indexOf(item):-1;
 if(!item&&!title)return <div className="ed-inspector-empty"><EditIcon name="film"/><h3>Select a timeline item</h3><p>Choose a clip to trim, adjust its picture or balance its sound. Your original media stays intact.</p></div>;
 if(title)return <div className="ed-inspector"><div className="ed-inspect-heading"><h3>Title</h3><small>Text &amp; placement</small></div><label>Text<textarea aria-label="Title text" value={title.text} maxLength={500} onChange={e=>update({text:e.target.value})}/></label><div className="ed-two">{(['start','end'] as const).map(k=><label key={k}>{k==='start'?'Start (s)':'End (s)'}<input type="number" min={0} step={1/fps} max={duration(timeline)} value={title[k]} onChange={e=>update({[k]:Number(e.target.value)})}/></label>)}</div><label>Position<select value={title.position} onChange={e=>update({position:e.target.value})}>{['top','center','bottom'].map(v=><option key={v}>{v}</option>)}</select></label><label>Size<input type="range" min={16} max={96} value={title.size} onChange={e=>update({size:Number(e.target.value)})}/></label><label>Color<select value={title.color} onChange={e=>update({color:e.target.value})}><option value="#ffffff">White</option><option value="#aef0ca">Mint</option><option value="#ffdb8a">Warm yellow</option></select></label><button className="ed-remove" onClick={remove}>Remove title</button></div>;
 if(!item)return null;
 return <div className="ed-inspector">
  <div className="ed-inspect-heading"><div><h3>{kind==='audio'?'Audio clip':still?'Image clip':item.source.kind==='gap'?'Gap':'Video clip'}</h3><span title={item.label}>{item.label}</span></div><small>{clipLength(item).toFixed(2)}s</small></div>
  <div className="ed-inspector-tabs" role="group" aria-label="Clip adjustments">{[['trim','Trim'],...(kind==='clip'?[['picture','Picture']]:[]),['audio','Audio']].map(([value,label])=><button key={value} aria-pressed={panel===value} onClick={()=>setPanel(value)}>{label}</button>)}</div>
  {panel==='trim'&&<>
   {still?<label>Display duration (s)<input aria-label="Image display duration" type="number" step={1/fps} min={.04} max={3600} value={item.out} onChange={e=>update({in:0,out:Number(e.target.value)})}/></label>:<div className="ed-two"><label>Trim in (s)<input aria-label="Clip trim in" type="number" step={1/fps} min={0} max={item.out-.04} value={item.in} onChange={e=>update({in:Number(e.target.value)})}/></label><label>Trim out (s)<input aria-label="Clip trim out" type="number" step={1/fps} min={item.in+.04} max={info?.duration} value={item.out} onChange={e=>update({out:Number(e.target.value)})}/></label></div>}
   <p>Keep the part you want. The original take is unchanged.</p>
   {kind==='audio'&&<label>Starts in edit (s)<input type="number" min={0} max={Math.max(0,duration(timeline)-.04)} step={1/fps} value={(item as Audio).start} onChange={e=>update({start:Number(e.target.value)})}/></label>}
   {kind==='clip'&&index>0&&<div className="ed-transition-controls"><label>Transition into clip<select aria-label="Incoming transition" value={(item as Clip).transition?.type||'cut'} onChange={e=>transition(e.target.value as Transition['type'])}><option value="cut">Cut</option><option value="dissolve">Dissolve</option><option value="fade">Fade through black</option></select></label>{!!overlap(item)&&<label>Overlap (s)<input aria-label="Transition duration" type="number" step={1/fps} min={1/fps} max={Math.min(2,clipLength(item)/2,clipLength(timeline.clips[index-1])/2)} value={overlap(item)} onChange={e=>update({transition:{type:(item as Clip).transition!.type,duration:snap(Number(e.target.value),fps)}})}/></label>}<small>Transitions overlap adjacent clips.</small></div>}
   {kind==='clip'&&<details className="ed-advanced"><summary>Speed &amp; frame holds</summary><PictureInspector item={item} fps={fps} mode="timing" update={update}/></details>}
   <details className="ed-advanced"><summary>Clip details</summary><label>Label<input value={item.label} maxLength={120} onChange={e=>update({label:e.target.value})}/></label>{item.render_link&&<p>Rendered scene · revision {item.render_link.revision}</p>}{kind==='clip'&&item.shot_id&&item.source.kind==='take'&&<button aria-label="Select this timeline take" onClick={selectTake}>★ Select this take for the shot</button>}</details>
  </>}
  {panel==='picture'&&kind==='clip'&&<><PictureInspector item={item} fps={fps} sourceRatio={(info?.width||16)/(info?.height||9)} ratio={Number(timeline.output.ratio.split(':')[0])/Number(timeline.output.ratio.split(':')[1])} mode="picture" update={update}/>{item.source.kind!=='gap'&&<details className="ed-advanced"><summary>Color adjustments</summary><ColorInspector item={item} update={update}/></details>}</>}
  {panel==='audio'&&<><label>Volume · {Math.round(item.volume*100)}%<input aria-label="Selected media volume" type="range" min={0} max={2} step={.01} value={item.volume} onChange={e=>update({volume:Number(e.target.value)})}/></label><button onClick={()=>update({volume:item.volume?0:1})}>{item.volume?'Mute clip':'Unmute clip'}</button><AudioInspector item={item} fps={fps} clip={kind==='clip'} info={item.source.kind==='gap'?{audio:false,duration:60}:info} update={update}/></>}
  <div className="ed-inspector-footer"><button className="ed-remove" onClick={remove}>Remove from edit</button></div>
 </div>;
}
