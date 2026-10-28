import React,{useEffect,useRef,useState} from 'react';
import {previewURL,thumbnail} from './studio-runtime';

export function MediaPoster({src,kind,id,alt='',width=320}:{src?:string;kind?:string;id?:string;alt?:string;width?:number}){
 const host=useRef<HTMLSpanElement>(null),[visible,setVisible]=useState(false),[poster,setPoster]=useState('');
 useEffect(()=>{if(typeof IntersectionObserver==='undefined'){setVisible(true);return;}const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'160px'});if(host.current)observer.observe(host.current);return()=>observer.disconnect();},[]);
 useEffect(()=>{if(!visible)return;let active=true,timer:ReturnType<typeof setTimeout>|undefined,objectURL='';const controller=new AbortController();setPoster('');
  if(!kind||kind==='image'){setPoster(thumbnail(src,width)||'');return;}
  if(!id)return;
  let attempts=0;
  const load=async()=>{try{const response=await fetch(previewURL(kind,id,width),{signal:controller.signal});if(!response.ok)return;const state=response.headers.get('X-Preview-State');if(state==='pending'){if(active&&attempts++<30)timer=setTimeout(load,Math.min(3000,500+attempts*250));return;}if(state&&state!=='ready')return;const blob=await response.blob();if(active){objectURL=URL.createObjectURL(blob);setPoster(objectURL);}}catch{/* Keep a small placeholder if media is not cached. */}};
  void load();return()=>{active=false;controller.abort();clearTimeout(timer);if(objectURL)URL.revokeObjectURL(objectURL);};
 },[visible,src,kind,id,width]);
 return <span ref={host} className="media-poster">{poster?<img src={poster} alt={alt} loading="lazy" decoding="async" draggable={false}/>:<span aria-label={alt||'Media preview'}>▷</span>}</span>;
}

export function DeferredVideo({src}:{src:string}){const [open,setOpen]=useState(false);return <details onToggle={e=>setOpen(e.currentTarget.open)}><summary>Preview</summary>{open&&<video src={src} controls preload="metadata"/>}</details>;}
