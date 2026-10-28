import {useEffect,useRef} from 'react';
export type AgentEditor={id:string;revision:number;dirty:boolean;data:any;actions?:string[]};
export type EditorControl={capture:()=>AgentEditor|null;save?:()=>Promise<void>;reload?:()=>Promise<void>;discard?:()=>Promise<void>};
declare global {interface Window {studioAgentEditors?:Record<string,EditorControl>;studioAgentView?:()=>any;studioAgentSetView?:(value:any)=>Promise<void>;studioAgentViews?:Record<string,{capture:()=>any;apply:(value:any)=>Promise<void>}>}}
export function useAgentView(key:string,value:any,apply:(value:any)=>Promise<void>){
 const latest=useRef({value,apply});latest.current={value,apply};
 useEffect(()=>{const entry={capture:()=>latest.current.value,apply:async(v:any)=>latest.current.apply(v)};const registry=window.studioAgentViews||={};registry[key]=entry;return()=>{if(registry[key]===entry)delete registry[key];};},[key]);
}
export function useAgentEditor(key:string,control:EditorControl){
 const latest=useRef(control);latest.current=control;
 useEffect(()=>{const entry:EditorControl={capture:()=>{const v=latest.current.capture();return v?{...v,actions:['save','reload','discard'].filter(k=>typeof (latest.current as any)[k]==='function')}:null;}};
 for(const action of ['save','reload','discard'] as const)if(control[action])entry[action]=async()=>{const fn=latest.current[action];if(!fn)throw Error('This editor action is no longer available.');await fn();};
 const registry=window.studioAgentEditors||={};registry[key]=entry;return()=>{if(registry[key]===entry)delete registry[key];};
 },[key,!!control.save,!!control.reload,!!control.discard]);
}
export function editorSnapshots(){const result:Record<string,AgentEditor>={};for(const [key,editor] of Object.entries(window.studioAgentEditors||{})){const value=editor.capture();if(value)result[key]=structuredClone(value);}return result;}
export function stable(value:any):string{return JSON.stringify(value,(_key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);}
