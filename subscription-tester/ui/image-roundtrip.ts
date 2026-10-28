import {Route,service} from './navigation';
import {createReturnFlow} from './browser-handoff';
export type ImageReturn={route:Route;title:string;draft_id?:string;flow_id?:string;flow_revision?:number;context:{scope:string;entity_id:string;view_id:string;expected_revision:number;page:number;visual:any;job_id?:string}};
const key='imagine-image-return';
export function readImageReturn():ImageReturn|null{try{const value=JSON.parse(sessionStorage.getItem(key)||'null');return value?.route&&value?.context?.view_id?value:null;}catch{return null;}}
export function rememberImageReturn(value:ImageReturn){sessionStorage.setItem(key,JSON.stringify(value));}
export async function persistImageReturn(value:ImageReturn&{draft_id:string}){const flow=await createReturnFlow(value);const saved={...value,flow_id:flow.id,flow_revision:flow.revision};rememberImageReturn(saved);return saved;}
export function clearImageReturn(){sessionStorage.removeItem(key);}
export async function finishImageReturn(value:ImageReturn,result:{job_id:string;asset_id:string}|null){
 const context={...value.context,visual:{...value.context.visual}};
 if(value.flow_id){context.visual.flow_id=value.flow_id;context.visual.flow_revision=value.flow_revision;}
 if(result){const saved=await service('filmmaking/assets/'+context.view_id+'/return-image','POST',{expected_revision:context.expected_revision,...result});const view=saved.views.find((v:any)=>v.id===context.view_id);(context as any).adopted=view?.selected===result.asset_id;context.visual.heroChoice=result.asset_id;}
 const pid=value.route.workspace?.production_id;
 sessionStorage.setItem('imagine-series-tab-'+pid,context.scope.startsWith('series/')?'bible':'episodes');
 if(context.scope.startsWith('episodes/'))sessionStorage.setItem('episode-book-open-'+pid,'1');
 sessionStorage.setItem('imagine-development-return-'+context.scope,JSON.stringify(context));
 return value.route;
}
