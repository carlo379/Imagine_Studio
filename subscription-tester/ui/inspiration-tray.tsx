import React,{useEffect,useRef,useState} from 'react';
import {useDialog} from './studio-service';
function visible(element:HTMLElement){
 for(let node:HTMLElement|null=element;node;node=node.parentElement){
  if(node.hidden||node.getAttribute('aria-hidden')==='true'||(node.tagName==='DIALOG'&&!node.hasAttribute('open')))return false;
  const style=window.getComputedStyle(node);if(style.display==='none'||style.visibility==='hidden')return false;
 }
 return true;
}
export function InspirationTray({ids,disabled=false,upload,remove,preview,label='Image',paper=false,developmentPaste=false,onImagePaste,onLibrary}:{ids:string[];disabled?:boolean;upload:(files:File[])=>Promise<void>;remove:(id:string)=>void;preview?:(image:any)=>void;label?:string;paper?:boolean;developmentPaste?:boolean;onImagePaste?:()=>void;onLibrary?:()=>void}){
 const tray=useRef<HTMLDivElement>(null),file=useRef<HTMLInputElement>(null),pasteButton=useRef<HTMLButtonElement>(null),lock=useRef(false),reading=useRef(false),[working,setWorking]=useState(false),[message,setMessage]=useState(''),[opened,setOpened]=useState<string|null>(null),[sourceMenu,setSourceMenu]=useState(false),locked=disabled||working;
 async function add(files:File[]){if(disabled||lock.current)return;if(!files.length){setMessage('Copy an image, then paste it here. Links and text do not attach an image.');return;}if(files.length+ids.length>5){setMessage('Choose up to '+(5-ids.length)+' more images. Nothing was added.');return;}if(files.some(f=>f.size>10*1024*1024||!['image/png','image/jpeg','image/webp'].includes(f.type))){setMessage('Use PNG, JPEG or WebP, up to 10 MB each. Nothing was added.');return;}lock.current=true;setWorking(true);setMessage('');try{await upload(files);}catch(error:any){setMessage(error.message||'Images could not be added.');}finally{lock.current=false;setWorking(false);}}
 async function paste(){if(locked||reading.current||ids.length>=5)return;pasteButton.current?.focus();if(!navigator.clipboard?.read){setMessage('Press ⌘V or Ctrl+V now to paste a copied image.');tray.current?.focus({preventScroll:true});return;}reading.current=true;setWorking(true);try{const items=await navigator.clipboard.read(),files:File[]=[];for(const item of items){const type=item.types.find(t=>['image/png','image/jpeg','image/webp'].includes(t));if(type){const blob=await item.getType(type);files.push(new File([blob],'Pasted inspiration '+(files.length+1)+'.'+(type==='image/jpeg'?'jpg':type.split('/')[1]),{type}));}}await add(files);}catch{setMessage('Clipboard access is unavailable. Press ⌘V or Ctrl+V here to paste instead.');tray.current?.focus({preventScroll:true});}finally{reading.current=false;setWorking(false);}}
 const receivePaste=useRef<(event:ClipboardEvent)=>void>(()=>{});
 receivePaste.current=event=>{
  const root=tray.current,target=event.target as HTMLElement|null;if(!root||!target?.closest||event.defaultPrevented)return;
  // Text editors and other dialogs retain their own clipboard behavior.
  if(target.closest('input,textarea,[contenteditable]:not([contenteditable="false"])'))return;
  const dialog=root.closest<HTMLElement>('[role="dialog"],dialog'),targetDialog=target.closest('[role="dialog"],dialog');
  const topDialog=Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"],dialog[open]')).filter(visible).at(-1);
  if((targetDialog&&targetDialog!==dialog)||(topDialog&&topDialog!==dialog))return;
  if(root.contains(target)){if(!visible(root))return;}
  else{
   if(!developmentPaste)return;
   const owner=root.closest<HTMLElement>('[data-inspiration-paste-scope]'),scope=dialog||owner;
   if(!owner||!scope||!visible(owner)||(!scope.contains(target)&&target!==document.body))return;
   const recipients=Array.from(scope.querySelectorAll<HTMLElement>('[data-development-paste="true"]')).filter(node=>{
    const currentOwner=node.closest<HTMLElement>('[data-inspiration-paste-scope]');return currentOwner&&visible(currentOwner)&&node.closest('[role="dialog"],dialog')===dialog;
   });
   if(recipients.length!==1||recipients[0]!==root)return;
  }
  const files=Array.from(event.clipboardData?.items||[]).filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter((item):item is File=>!!item);
  if(!files.length||(!root.contains(target)&&!files.some(f=>f.type.startsWith('image/'))))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(locked||lock.current||reading.current)return;
  onImagePaste?.();void add(files);
 };
 useEffect(()=>{if(!sourceMenu)return;const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.stopPropagation();setSourceMenu(false);tray.current?.querySelector<HTMLButtonElement>('.inspiration-tray-choose')?.focus();}};const outside=(event:PointerEvent)=>{if(!tray.current?.contains(event.target as Node))setSourceMenu(false);};document.addEventListener('keydown',key,true);document.addEventListener('pointerdown',outside);return()=>{document.removeEventListener('keydown',key,true);document.removeEventListener('pointerdown',outside);};},[sourceMenu]);
 useEffect(()=>{const receive=(event:ClipboardEvent)=>receivePaste.current(event);document.addEventListener('paste',receive,true);return()=>document.removeEventListener('paste',receive,true);},[]);
 return <div ref={tray} tabIndex={0} className={'inspiration-tray '+(paper?'inspiration-paper':'')+(onLibrary?' inspiration-source-picker':'')} aria-label={label+' inspiration images'} data-development-paste={developmentPaste?'true':undefined} onPointerDown={event=>{if(!(event.target as HTMLElement).closest('button,input'))tray.current?.focus({preventScroll:true});}}>
 <div className="inspiration-tray-count">{ids.length} / 5 images</div><div className="inspiration-tray-grid">{ids.map((id,i)=><div className="inspiration-tray-tile" key={id}><button className="inspiration-tray-preview" disabled={locked} aria-label={'Preview '+label.toLowerCase()+' inspiration '+(i+1)} onClick={()=>preview?preview({id}):setOpened(id)}><img src={'/api/assets/'+id} alt={label+' inspiration '+(i+1)}/></button><button className="inspiration-tray-remove" disabled={locked} aria-label={'Remove '+label.toLowerCase()+' inspiration '+(i+1)} onClick={()=>remove(id)}>×</button></div>)}{ids.length<5&&<div className="inspiration-tray-add"><button disabled={locked} className="inspiration-tray-choose" aria-label={'Add '+label.toLowerCase()+' inspiration images'} aria-expanded={onLibrary?sourceMenu:undefined} onClick={()=>onLibrary?setSourceMenu(!sourceMenu):file.current?.click()}><span aria-hidden="true">＋</span>{working?'Adding…':onLibrary?'Add images ▾':'Add images'}</button>{onLibrary?sourceMenu&&<div className="inspiration-source-menu" aria-label="Image sources"><button disabled={locked} onClick={()=>{setSourceMenu(false);file.current?.click();}}><SourceIcon kind="computer"/>From computer</button><button disabled={locked} onClick={()=>{setSourceMenu(false);onLibrary();}}><SourceIcon kind="library"/>From Library</button><button disabled={locked} onClick={()=>{setSourceMenu(false);void paste();}}><SourceIcon kind="paste"/>Paste image</button></div>:<button ref={pasteButton} disabled={locked} className="inspiration-tray-paste" aria-label={'Paste '+label.toLowerCase()+' inspiration image'} onClick={()=>void paste()}>or Paste image</button>}</div>}</div>
 <input ref={file} hidden multiple type="file" accept="image/png,image/jpeg,image/webp" aria-label={label+' inspiration files'} disabled={locked||ids.length>=5} onChange={event=>{const files=Array.from(event.target.files||[]);event.target.value='';if(files.length)void add(files);}}/><small className="inspiration-tray-limits">PNG, JPEG or WebP · Up to 5 images · 10 MB each</small>{message&&<p className="inspiration-tray-message" role="status">{message}</p>}{opened&&<InspirationPreview id={opened} close={()=>setOpened(null)}/>}
 </div>;
}
function InspirationPreview({id,close}:{id:string;close:()=>void}){useDialog(close,'Inspiration image preview',true);return <div className="ft-backdrop inspiration-preview-backdrop"><section className="inspiration-preview-dialog" role="dialog" aria-modal="true" aria-label="Inspiration image preview"><header><strong>Inspiration image</strong><button aria-label="Close inspiration preview" onClick={close}>×</button></header><img src={'/api/assets/'+id} alt="Inspiration image"/></section></div>;}

function SourceIcon({kind}:{kind:'computer'|'library'|'paste'}){return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{kind==='computer'?<><rect x="3" y="3" width="18" height="13" rx="2"/><path d="M8 21h8m-4-5v5"/></>:kind==='library'?<><rect x="7" y="3" width="14" height="16" rx="2"/><path d="M3 7v12a2 2 0 0 0 2 2h12m-7-7 3-3 5 5"/><circle cx="16" cy="7" r="1"/></>:<><rect x="5" y="5" width="14" height="17" rx="2"/><rect x="9" y="2" width="6" height="5" rx="1"/></>}</svg>;}
