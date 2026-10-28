import React,{useEffect,useRef,useState} from 'react';
import {service} from './studio-service';

type Connection={connected:boolean;pending?:boolean;offline?:boolean};
type Status='connected'|'disconnected'|'pending'|'unknown';
const models=[{id:'gpt-image-2',provider:'codex',name:'ChatGPT · Image 2',label:'Image 2'},{id:'grok-imagine-image-2.0',provider:'grok',name:'Grok Imagine',label:'Grok'}];
export const imageModelChoiceKey=()=> (window.studioStoragePrefix||'imagine-')+'image-model-choice-v1';
export function rememberedImageModel(){try{const value=window.sessionStorage.getItem(imageModelChoiceKey());return models.some(m=>m.id===value)?value:null;}catch{return null;}}
function rememberImageModel(model:string){try{window.sessionStorage.setItem(imageModelChoiceKey(),model);}catch{}window.dispatchEvent(new Event('studio-image-model-choice'));}
export function ImageModelPicker({model,onChange,disabled=false}:{model:string;onChange:(model:string)=>void;disabled?:boolean}){
 const [grok,setGrok]=useState<Connection|undefined>(window.studioGrokConnection),[codex,setCodex]=useState<Connection>(),[prompt,setPrompt]=useState<string|null>(null);
 const [choice,setChoice]=useState(rememberedImageModel),choiceDialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const sync=()=>setChoice(rememberedImageModel());window.addEventListener('studio-image-model-choice',sync);return()=>window.removeEventListener('studio-image-model-choice',sync);},[]);
 useEffect(()=>{if(!choice){if(choiceDialog.current?.showModal)choiceDialog.current.showModal();else choiceDialog.current?.setAttribute('open','');}},[choice]);
 const requested=useRef<string|null>(null),selected=useRef(model);selected.current=model;
 useEffect(()=>{let alive=true,inflight=false;
  const updateGrok=(event:Event)=>setGrok((event as CustomEvent).detail);
  async function load(){if(inflight)return;inflight=true;try{const value=await service<any>('image-studio/openai-account');if(alive)setCodex({connected:value.subscription?.signed_in===true});}catch{if(alive)setCodex({connected:false,offline:true});}finally{inflight=false;}}
  window.addEventListener('studio-grok-connection',updateGrok);window.addEventListener('focus',load);const timer=setInterval(load,15000);void load();
  return()=>{alive=false;clearInterval(timer);window.removeEventListener('studio-grok-connection',updateGrok);window.removeEventListener('focus',load);};
 },[]);
 function status(provider:string):Status{const value=provider==='grok'?grok:codex;return !value||value.offline?'unknown':value.pending?'pending':value.connected?'connected':'disconnected';}
 const active=models.find(item=>item.id===model)||models[0];
 useEffect(()=>{if(requested.current!==active.provider)return;const value=status(active.provider);if(value==='disconnected'){setPrompt(active.provider);requested.current=null;}else if(value==='connected'){setPrompt(null);requested.current=null;}},[model,grok,codex]);
 useEffect(()=>{if(prompt&&status(prompt)==='connected')setPrompt(null);},[grok,codex,prompt]);
 const hint=(provider:string)=>{const value=status(provider);return value==='connected'?'Sign-in saved. Image generation and available quota are not verified.':value==='disconnected'?'Sign-in needed':value==='pending'?'Sign-in in progress':'Connection status unavailable';};
 function choose(id:string,provider:string){if(disabled)return;rememberImageModel(id);setChoice(id);onChange(id);setPrompt(null);requested.current=provider;if(status(provider)==='disconnected'){setPrompt(provider);requested.current=null;}}
 function connect(){if(!prompt)return;window.dispatchEvent(new CustomEvent('studio-reconnect-provider',{detail:{provider:prompt}}));}
 return <div className="image-model-picker" onKeyDown={event=>{if(event.key==='Escape'&&prompt){event.stopPropagation();requested.current=null;setPrompt(null);}}}><>{!choice&&<dialog ref={choiceDialog} className="account-dialog" aria-label="Choose your image model" onCancel={event=>event.preventDefault()}><h2>Choose your image model</h2><p>Remember this choice for new images in this workspace session. You can change it with the model buttons. Selecting a model does not generate an image.</p>{models.map(item=><button type="button" key={item.id} disabled={disabled} onClick={()=>choose(item.id,item.provider)}>{item.name}</button>)}</dialog>}</><div className="image-model-controls"><div className="image-provider-tabs" role="group" aria-label="Image model">{models.map(item=><button type="button" key={item.id} disabled={disabled} aria-pressed={model===item.id} aria-label={item.name+' — '+hint(item.provider)} title={item.name+' — '+hint(item.provider)} onClick={()=>choose(item.id,item.provider)}><span className={'image-connection-dot '+status(item.provider)} aria-hidden="true"/>{item.label}</button>)}</div><button className="image-connection-settings" type="button" disabled={disabled} aria-label={'Manage '+active.name+' connection'} title={'Manage '+active.name+' connection'} onClick={()=>window.dispatchEvent(new CustomEvent('studio-manage-image-provider',{detail:{provider:active.provider}}))}><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M9.5 3h5l.7 2.4 2 .9 2.2-.6 2.5 4.3-1.6 1.8v2.4l1.6 1.8-2.5 4.3-2.2-.6-2 .9-.7 2.4h-5l-.7-2.4-2-.9-2.2.6-2.5-4.3 1.6-1.8v-2.4L1.6 10l2.5-4.3 2.2.6 2-.9z" transform="translate(0 -1) scale(1 .96)"/><circle cx="12" cy="12" r="3"/></svg></button></div>{prompt&&<div className="image-connect-prompt" role="status" aria-live="polite"><strong>{prompt==='grok'?'Connect Grok Imagine':'Connect ChatGPT · Image 2'}</strong><p>Sign in to use this model. Your descriptions and images stay saved.</p><div><button type="button" disabled={disabled} onClick={connect}>Sign in ↗</button><button type="button" onClick={()=>{requested.current=null;setPrompt(null);}}>Later</button></div></div>}</div>;
}

let promptSchema:Promise<any>|null=null;
export function useImagePromptLimit(model:string){
 const [schema,setSchema]=useState<any>(null);
 useEffect(()=>{let alive=true;if(!promptSchema)promptSchema=service('image-studio/schema').catch(()=>{promptSchema=null;return null;});void promptSchema.then(value=>{if(alive)setSchema(value);});return()=>{alive=false;};},[model]);
 return schema?.models?.[model]?.prompt_limit_chars||(model==='gpt-image-2'?32000:4096);
}
