declare global {interface Window {StudioRuntime?:any;ensureStudio?:(kind:string)=>Promise<void>}}

export async function requestJSON(url:string,options:RequestInit={}):Promise<any>{
 if(window.StudioRuntime)return window.StudioRuntime.json(url,options);
 const response=await fetch(url,options),value=await response.json();
 if(!response.ok){const error:any=Error(value.error?.message||'Studio request failed.');error.code=value.error?.code;throw error;}
 return value;
}
export function watchChanges(task:()=>Promise<unknown>,areas=['productions'],active=()=>true,initial=false):()=>void{
 if(window.StudioRuntime)return window.StudioRuntime.watch(task,{areas,active,initial});
 // Standalone embedded/test consumers have no shell monitor.
 return()=>{};
}
export function thumbnail(src:string|undefined,width=320):string|undefined{return window.StudioRuntime?.thumbnail(src,width)||src;}
export function previewURL(kind:string,id:string,width=320):string{return window.StudioRuntime?.preview(kind,id,width)||'/api/previews/'+kind+'/'+encodeURIComponent(id)+'/'+width+'?workspace='+encodeURIComponent((window as any).studioWorkspaceId||'local-owner');}
