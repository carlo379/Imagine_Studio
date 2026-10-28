import React from 'react';
import type {LibraryItem} from './navigation';
type Original={id:string;name?:string;mime?:string;ext?:string};
export function libraryDownloads(item:LibraryItem,originals:Original[]):{src:string;name:string;label:string}[]{
 const images=item.kind==='asset'?item.record.images||[]:item.kind==='image'&&item.status!=='draft'?[{asset_id:item.id,name:item.title}]:[];
 return images.flatMap((image:any,index:number)=>{
  let id=image.asset_id;
  if(!id&&typeof image.url==='string'){const match=image.url.match(/^\/api\/assets\/([a-f0-9]{32})$/);id=match?.[1];}
  if(typeof id!=='string'||!id)return [];
  const original=originals.find(a=>a.id===id);
  const ext=original?.ext||({'image/png':'png','image/jpeg':'jpg','image/webp':'webp'} as Record<string,string>)[original?.mime||'']||'';
  const label=image.name||image.label||`Image ${index+1}`;
  const fallback=(item.title+(images.length>1?' - '+label:'' )).replace(/[\\/<>:"|?*\x00-\x1f]/g,'_');
  const name=original?.name||(ext?fallback+'.'+ext:fallback);
  return [{src:'/api/assets/'+encodeURIComponent(id),name,label}];
 });
}
export function LibraryDownloads({item,originals}:{item:LibraryItem;originals:Original[]}){
 const downloads=libraryDownloads(item,originals);
 if(!downloads.length)return null;
 if(downloads.length===1)return <a className="library-download" href={downloads[0].src} download={downloads[0].name} aria-label={'Download '+item.title+' at full resolution'}>Download full resolution ↓</a>;
 return <details data-dismiss-menu><summary>Download images ↓</summary><div>{downloads.map((d,i)=><a className="library-download" key={d.src+':'+i} href={d.src} download={d.name} aria-label={'Download '+item.title+' — '+d.label+' at full resolution'}>{d.label} · Full resolution ↓</a>)}</div></details>;
}
