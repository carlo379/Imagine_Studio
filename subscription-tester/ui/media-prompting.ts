import {service} from './creative';

declare global {interface Window {MediaPrompting?:{prepare:(kind:'image'|'video',id:string,options?:{brief?:string;instruction?:string;provider?:string;autoStart?:boolean})=>Promise<any>}}}

/** Preparation always ends at prompt review; rendering needs a separate click. */
export async function workshopPrompts(views:any[],model:string,brief?:string,instruction?:string,requireReviewed=false):Promise<boolean>{
 const drafts=[];
 for(const view of views){
  const value=await service('filmmaking/assets/'+view.id+'/prompt-draft','POST',{
   expected_revision:view.revision,model,...(brief!==undefined?{brief}:{})});
  if(!value.current||(instruction!==undefined&&instruction!==(value.draft.prompt_preparation?.instruction||'')))drafts.push(value.draft);
 }
 if(!drafts.length)return true;
 if(requireReviewed)throw Error('Your image inputs changed. Return to Prepare prompt and review a new prompt before generating.');
 if(!window.MediaPrompting)throw Error('Reload Imagine Studio to prepare prompts with AI.');
 for(const draft of drafts){
  const applied=await window.MediaPrompting.prepare('image',draft.id,{autoStart:true,instruction,provider:model.startsWith('grok-')?'grok':'codex'});
  if(!applied)break;
 }
 return false;
}

export const viewPromptReady=(view:any,model:string,brief?:string,instruction?:string)=>!!view?.draft?.prompt_preparation_current&&(instruction===undefined||instruction===(view.draft.prompt_preparation?.instruction||''))&&(brief===undefined||brief===view.draft.settings.prompt||brief===view.draft.prompt_preparation?.brief);
