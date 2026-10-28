import React,{forwardRef,useEffect,useImperativeHandle,useLayoutEffect,useRef,useState} from 'react';

export type BookHandle={navigate:(chapter:number)=>void};
type Props={id:string;title:string;kind?:'bible'|'episode';subtitle?:string;imprint?:string;openLabel?:string;chapter:number;chapters:string[];disabled:boolean;onTurn:(chapter:number)=>void|Promise<void>;children:React.ReactNode[];previewPages:(chapter:number)=>React.ReactNode[]};

// Both sides use exactly this geometry; only their contents differ.
export function PaperPage({side,label,children}:{side:'left'|'right';label:string;children:React.ReactNode}){
 return <section className={'sb-page sb-'+side} aria-label={label}>{children}</section>;
}

export const BookFrame=forwardRef<BookHandle,Props>(function BookFrame(p,handle){
 const host=useRef<HTMLDivElement>(null),book=useRef<HTMLDivElement>(null),sheet=useRef<HTMLDivElement>(null),stationary=useRef<HTMLDivElement>(null),shadowCast=useRef<HTMLDivElement>(null),front=useRef<HTMLDivElement>(null),back=useRef<HTMLDivElement>(null);
 const [geometry,setGeometry]=useState({scale:1,phone:false});
 const [phase,setPhase]=useState<'closed'|'opening'|'open'>(()=>sessionStorage.getItem('sb-open-'+p.id)?'open':'closed');
 const [turning,setTurning]=useState(false),[side,setSide]=useState(0),[previewChapter,setPreviewChapter]=useState<number|null>(null);
 const raf=useRef(0),directionRef=useRef(1),targetRef=useRef(0);
 const phaseRef=useRef(phase),active=useRef(false),sideRef=useRef(side),props=useRef(p),geometryRef=useRef(geometry),timer=useRef<ReturnType<typeof setTimeout>|null>(null),alive=useRef(true);
 props.current=p;phaseRef.current=phase;sideRef.current=side;geometryRef.current=geometry;
 const drag=useRef<{pointer:number;start:number;direction:number;progress:number;target:number}|null>(null);
 const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
 useLayoutEffect(()=>{
  const update=()=>{if(!host.current)return;const w=host.current.clientWidth,phone=window.matchMedia('(max-width:600px) and (orientation:portrait)').matches;setGeometry({phone,scale:Math.min(1,w/(phone?540:1080))});};
  update();const observer=new ResizeObserver(update);observer.observe(host.current!);window.addEventListener('resize',update);
  return()=>{observer.disconnect();window.removeEventListener('resize',update);};
 },[]);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;if(timer.current)clearTimeout(timer.current);cancelAnimationFrame(raf.current);};},[]);
 useEffect(()=>{if(!active.current)setSide(0);},[p.chapter]);
 useLayoutEffect(()=>{book.current?.querySelectorAll<HTMLElement>('.sb-spread > .sb-page').forEach((el,i)=>{const hidden=geometry.phone&&i!==side;el.inert=hidden||phase!=='open'||turning;el.setAttribute('aria-hidden',String(hidden));});},[side,geometry.phone,phase,turning]);
 useLayoutEffect(()=>{if(previewChapter===null||!book.current||!back.current)return;const key=geometryRef.current.phone?(targetRef.current%2===0?'left':'right'):directionRef.current>0?'left':'right';const copy=snapshot(book.current.querySelector<HTMLElement>('.sb-preview > .sb-'+key));if(copy)back.current.replaceChildren(copy);},[previewChapter]);
 function settle(){cancelAnimationFrame(raf.current);if(!alive.current)return;active.current=false;drag.current=null;setTurning(false);setPreviewChapter(null);if(sheet.current){sheet.current.style.transition='none';sheet.current.style.visibility='hidden';}front.current?.replaceChildren();back.current?.replaceChildren();if(front.current)front.current.style.visibility='hidden';if(back.current)back.current.style.visibility='hidden';stationary.current?.replaceChildren();if(stationary.current)stationary.current.style.visibility='hidden';book.current?.style.setProperty('--turn-shadow','0');}
 function snapshot(node:HTMLElement|null){
  if(!node)return null;const copy=node.cloneNode(true) as HTMLElement;copy.setAttribute('inert','');copy.setAttribute('aria-hidden','true');
  const sources=node.querySelectorAll<HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement>('input,textarea,select');
  copy.querySelectorAll<HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement>('input,textarea,select').forEach((el,i)=>{el.value=sources[i].value;if(el instanceof HTMLInputElement)el.checked=(sources[i] as HTMLInputElement).checked;});
  copy.querySelectorAll<HTMLElement>('[id]').forEach(el=>el.removeAttribute('id'));
  // Copy the visible scroll position so a turn starts with precisely the page the reader saw.
  copy.querySelectorAll<HTMLElement>('.sb-page-scroll').forEach((el,i)=>{requestAnimationFrame(()=>{el.scrollTop=node.querySelectorAll<HTMLElement>('.sb-page-scroll')[i].scrollTop;});});
  return copy;
 }
 function prepare(direction:number,target:number){
  if(!book.current||!sheet.current)return;
  active.current=true;setTurning(true);directionRef.current=direction;targetRef.current=target;setPreviewChapter(geometryRef.current.phone?Math.floor(target/2):target);const s=sheet.current;
  const phone=geometryRef.current.phone;
  s.dataset.direction=String(direction);s.dataset.reduced=String(reduced());s.style.visibility='visible';s.style.transition='none';
  s.style.left=phone?'8px':direction>0?'540px':'8px';s.style.transformOrigin=direction>0?'left center':'right center';
  if(stationary.current&&!phone){stationary.current.style.opacity='1';stationary.current.style.left=direction>0?'8px':'540px';stationary.current.style.visibility='visible';stationary.current.replaceChildren(snapshot(book.current.querySelector<HTMLElement>(direction>0?'.sb-spread > .sb-left':'.sb-spread > .sb-right'))!);}
  front.current?.replaceChildren(snapshot(book.current.querySelector<HTMLElement>(phone?(sideRef.current===0?'.sb-spread > .sb-left':'.sb-spread > .sb-right'):direction>0?'.sb-spread > .sb-right':'.sb-spread > .sb-left'))!);
  const reverse=snapshot(book.current.querySelector<HTMLElement>(direction>0?'.sb-spread > .sb-left':'.sb-spread > .sb-right'));
  if(reverse)back.current?.replaceChildren(reverse);
  s.style.transform='rotateY(0deg)';s.style.opacity='1';if(front.current)front.current.style.visibility='visible';if(back.current)back.current.style.visibility='hidden';book.current.style.setProperty('--turn-shadow','0');
 }
 function progress(value:number,direction:number){
  const s=sheet.current;if(!s)return;
  if(reduced()){s.style.opacity=String(1-value);if(stationary.current)stationary.current.style.opacity=String(1-value);return;}
  s.style.transform=`rotateY(${direction*-180*value}deg)`;
  if(front.current)front.current.style.visibility=value<.5?'visible':'hidden';
  if(back.current)back.current.style.visibility=value>=.5?'visible':'hidden';
  book.current?.style.setProperty('--turn-shadow',String(Math.sin(Math.PI*value)*.28));
  s.style.setProperty('--sheet-shade',String(Math.sin(Math.PI*value)*.2));
  if(shadowCast.current)shadowCast.current.style.transform=`translateX(${direction*Math.cos(Math.PI*value)*150}px) scaleX(${.5+Math.sin(Math.PI*value)*3})`;
 }
 function finish(target:number,direction:number,from=0,commit=true){
  const complete=async()=>{
   try{
    if(commit){const nextChapter=geometryRef.current.phone?Math.floor(target/2):target;await props.current.onTurn(nextChapter);if(!alive.current)return;setSide(geometryRef.current.phone?target%2:0);
     // Use the newly rendered opposite side for the back face, preserving the actual page contents.
     await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
     if(back.current&&book.current){const newBack=snapshot(book.current.querySelector<HTMLElement>(geometryRef.current.phone?(target%2===0?'.sb-spread > .sb-left':'.sb-spread > .sb-right'):direction>0?'.sb-spread > .sb-left':'.sb-spread > .sb-right'));if(newBack)back.current.replaceChildren(newBack);}
    }
    const duration=reduced()?180:Math.max(220,800*(commit?1-from:from));
    if(sheet.current)sheet.current.style.transition='none';
    const started=performance.now();
    const tick=(now:number)=>{
     if(!alive.current)return;
     const t=Math.min(1,(now-started)/duration),eased=t*t*(3-2*t);
     progress(from+((commit?1:0)-from)*eased,direction);
     if(t<1)raf.current=requestAnimationFrame(tick);
     else{settle();if(commit)requestAnimationFrame(()=>book.current?.querySelector<HTMLElement>('.sb-spread .sb-page:not([aria-hidden="true"]) :is(h2,h3)')?.focus({preventScroll:true}));}
    };
    raf.current=requestAnimationFrame(tick);
   }catch{settle();}
  };void complete();
 }
 function navigate(chapter:number){
  if(props.current.disabled||active.current)return;
  chapter=Math.max(0,Math.min(p.chapters.length-1,chapter));
  if(phaseRef.current==='closed'){open(chapter);return;}
  if(phaseRef.current!=='open'||chapter===props.current.chapter)return;
  const direction=chapter>props.current.chapter?1:-1,target=geometryRef.current.phone?chapter*2:chapter;
  prepare(direction,target);finish(target,direction);
 }
 useImperativeHandle(handle,()=>({navigate}));
 function currentLeaf(){return geometryRef.current.phone?props.current.chapter*2+sideRef.current:props.current.chapter;}
 function step(direction:number){
  if(active.current||props.current.disabled||phaseRef.current!=='open')return;
  const target=currentLeaf()+direction,max=geometryRef.current.phone?props.current.chapters.length*2-1:props.current.chapters.length-1;if(target<0||target>max)return;
  prepare(direction,target);finish(target,direction);
 }
 function open(requested?:number){if(phaseRef.current!=='closed'||props.current.disabled||active.current)return;active.current=true;void (async()=>{try{if(!sessionStorage.getItem('sb-seen-'+p.id)&&props.current.chapter!==0)await props.current.onTurn(0);if(!alive.current)return;setSide(0);setPhase('opening');sessionStorage.setItem('sb-open-'+p.id,'1');sessionStorage.setItem('sb-seen-'+p.id,'1');timer.current=setTimeout(()=>{if(alive.current){active.current=false;setPhase('open');book.current?.focus({preventScroll:true});if(requested!==undefined&&requested!==props.current.chapter)requestAnimationFrame(()=>navigate(requested));}},reduced()?200:1050);}catch{active.current=false;}})();}
 function close(){if(active.current||phaseRef.current!=='open')return;sessionStorage.removeItem('sb-open-'+p.id);setPhase('closed');}
 function pointerDown(e:React.PointerEvent){
  if(active.current||props.current.disabled||phaseRef.current!=='open'||e.button!==0)return;
  const target=e.target as HTMLElement;if(target.closest('input,textarea,select,button,summary,a,label'))return;
  const rect=book.current!.getBoundingClientRect(),local=e.clientX-rect.left;
  // Only the outer paper edge is draggable; writing and scrolling remain natural.
  const edge=geometryRef.current.phone?36:48,direction=local>rect.width-edge?1:local<edge?-1:0;
  const next=currentLeaf()+direction,max=geometryRef.current.phone?props.current.chapters.length*2-1:props.current.chapters.length-1;if(!direction||next<0||next>max)return;
  e.preventDefault();book.current!.setPointerCapture(e.pointerId);prepare(direction,next);drag.current={pointer:e.pointerId,start:e.clientX,direction,progress:0,target:next};
 }
 function pointerMove(e:React.PointerEvent){const d=drag.current;if(!d||d.pointer!==e.pointerId)return;const width=540*geometryRef.current.scale;d.progress=Math.max(0,Math.min(1,(d.start-e.clientX)*d.direction/width));progress(d.progress,d.direction);}
 function pointerUp(e:React.PointerEvent,cancel=false){const d=drag.current;if(!d||d.pointer!==e.pointerId)return;drag.current=null;if(book.current?.hasPointerCapture(e.pointerId))book.current.releasePointerCapture(e.pointerId);finish(d.target,d.direction,d.progress,!cancel&&d.progress>.32);}
 const css={'--book-scale':geometry.scale,'--left-stack':`${2+p.chapter*1.5}px`,'--right-stack':`${2+(p.chapters.length-1-p.chapter)*1.5}px`} as React.CSSProperties;
 return <div className="sb-book-experience" onKeyDown={e=>{if((e.target as HTMLElement).closest('input,textarea,select,[contenteditable="true"]'))return;if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();step(e.key==='ArrowRight'?1:-1);}}}>
  <div className="sb-book-host" ref={host} style={{height:720*geometry.scale}}>
   <div className={'sb-book '+(p.kind?'sb-kind-'+p.kind+' ':'')+(geometry.phone?'sb-phone ':'')+'sb-is-'+phase} ref={book} style={css} tabIndex={0} role="group" aria-label={p.kind==='bible'?'Interactive Series Bible':p.kind==='episode'?'Interactive Episode Book':'Interactive storybook'} aria-busy={turning||phase==='opening'} data-chapter={p.chapter} data-side={side}
    onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={e=>pointerUp(e)} onPointerCancel={e=>pointerUp(e,true)}>
    <div className="sb-hardcover-base" aria-hidden="true"/><div className="sb-edges sb-edges-left" aria-hidden="true"/><div className="sb-edges sb-edges-right" aria-hidden="true"/>
    <div className="sb-spread" inert={phase!=='open'||turning}>
     {p.children.map((child,i)=><React.Fragment key={i}>{child}</React.Fragment>)}
    </div>
    <div className="sb-preview" aria-hidden="true" inert>{previewChapter!==null&&p.previewPages(previewChapter)}</div><div className="sb-binding" aria-hidden="true"/>
    <div className="sb-stationary-sheet" ref={stationary} aria-hidden="true" inert/><div className="sb-turn-shadow" aria-hidden="true"><div className="sb-shadow-cast" ref={shadowCast}/></div>
    <div className="sb-turn-sheet" ref={sheet} aria-hidden="true" inert>
     <div className="sb-sheet-face sb-sheet-front" ref={front}/><div className="sb-sheet-face sb-sheet-back" ref={back}/>
    </div>
    <div className="sb-cover" aria-hidden={phase==='open'} inert={phase==='open'}>
     <button className="sb-cover-front" onClick={()=>open()} disabled={phase!=='closed'} aria-label={p.kind==='bible'?'Open Series Bible':p.kind==='episode'?'Open Episode Book':'Open storybook'}>
      <span className="sb-cover-imprint">{p.imprint||(p.kind==='bible'?'IMAGINE STUDIO · SERIES BIBLE':p.kind==='episode'?'IMAGINE STUDIO · EPISODE COLLECTION':'IMAGINE STUDIO · STORY COLLECTION')}</span><span className="sb-cover-emblem" aria-hidden="true">✦</span><strong>{p.title}</strong><span className="sb-cover-subtitle">{p.subtitle||(p.kind==='bible'?'The foundation for every episode':p.kind==='episode'?'A new chapter in your world':'A world waiting to unfold')}</span><span className="sb-cover-rule"/><span className="sb-cover-open">{p.openLabel||(p.kind==='bible'?'Open your Bible':p.kind==='episode'?'Open your episode':'Open your story')} <span>↗</span></span>
     </button><div className="sb-cover-back" aria-hidden="true"><span>IMAGINE<br/>STUDIO</span></div>
    </div>
   </div>
  </div>
  <div className="sb-book-controls"><button disabled={phase!=='open'||turning||p.disabled||currentLeaf()===0} onClick={()=>step(-1)}>← Previous page</button><span role="status">{phase==='closed'?'Open the cover to begin':phase==='opening'?'Opening your story…':`${p.chapters[p.chapter]} · ${geometry.phone?'page '+(currentLeaf()+1)+' of '+(p.chapters.length*2):'spread '+(p.chapter+1)+' of '+p.chapters.length}`}</span><button disabled={phase!=='open'||turning||p.disabled||currentLeaf()===(geometry.phone?p.chapters.length*2-1:p.chapters.length-1)} onClick={()=>step(1)}>Next page →</button></div>
  <div className="sb-book-instructions"><span>{phase==='open'?'Use the arrows or drag a paper edge to turn.':'Your story stays saved inside the book.'}</span>{phase==='open'&&<button onClick={close} disabled={turning}>Close book</button>}</div>
 </div>;
});
