import React,{useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';

type Props={anchor:React.RefObject<HTMLButtonElement|null>;id:string;label:string;close:()=>void;children:React.ReactNode};
export function menuPosition(anchor:{left:number;right:number;top:number;bottom:number},width:number,height:number,viewport:{width:number;height:number}){
 const gap=8,edge=8,w=Math.min(width,Math.max(0,viewport.width-edge*2)),h=Math.min(height,Math.max(0,viewport.height-edge*2));
 const above=anchor.top-gap-h,below=anchor.bottom+gap;
 const top=above>=edge?above:below+h<=viewport.height-edge?below:Math.max(edge,Math.min(above,viewport.height-edge-h));
 return {left:Math.max(edge,Math.min(anchor.right-w,viewport.width-edge-w)),top,width:w,maxHeight:Math.max(0,viewport.height-edge*2)};
}
export function FloatingMenu({anchor,id,label,close,children}:Props){
 const panel=useRef<HTMLDivElement>(null),closing=useRef(close);closing.current=close;
 const [position,setPosition]=useState({left:0,top:0,width:200,maxHeight:400,visibility:'hidden' as 'hidden'|'visible'});
 useLayoutEffect(()=>{
  const node=panel.current,trigger=anchor.current;if(!node||!trigger)return;
  const items=()=>Array.from(node.querySelectorAll<HTMLElement>('[role=menuitem]:not(:disabled)'));
  const place=()=>{const viewport=window.visualViewport,x=viewport?.offsetLeft||0,y=viewport?.offsetTop||0,rect=trigger.getBoundingClientRect(),position=menuPosition({left:rect.left-x,right:rect.right-x,top:rect.top-y,bottom:rect.bottom-y},200,node.scrollHeight||node.getBoundingClientRect().height||140,{width:viewport?.width||document.documentElement.clientWidth||window.innerWidth,height:viewport?.height||window.innerHeight});setPosition({...position,left:position.left+x,top:position.top+y,visibility:'visible'});};
  place();items()[0]?.focus({preventScroll:true});
  const outside=(event:PointerEvent)=>{if(!node.contains(event.target as Node)&&!trigger.contains(event.target as Node))closing.current();};
  const key=(event:KeyboardEvent)=>{
   if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closing.current();trigger.focus({preventScroll:true});return;}
   if(!node.contains(document.activeElement))return;
   if(event.key==='Tab'){closing.current();trigger.focus({preventScroll:true});return;}
   const controls=items(),index=controls.indexOf(document.activeElement as HTMLElement);let next:number|undefined;
   if(event.key==='ArrowDown')next=(index+1)%controls.length;if(event.key==='ArrowUp')next=(index-1+controls.length)%controls.length;if(event.key==='Home')next=0;if(event.key==='End')next=controls.length-1;
   if(next!==undefined&&controls[next]){event.preventDefault();event.stopPropagation();controls[next].focus();}
  };
  const scroll=(event:Event)=>{if(!(event.target instanceof window.Node)||!node.contains(event.target))closing.current();};
  document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',key,true);window.addEventListener('scroll',scroll,true);window.addEventListener('resize',place);window.visualViewport?.addEventListener('resize',place);
  return()=>{document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',key,true);window.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',place);window.visualViewport?.removeEventListener('resize',place);};
 },[anchor]);
 // Native dialogs occupy the browser top layer; mount inside it when present.
 const host=anchor.current?.closest('dialog')||document.body;
 return createPortal(<div ref={panel} id={id} role="menu" aria-label={label} className="wb-options-panel studio-floating-menu" style={{position:'fixed',...position}}>{children}</div>,host);
}
