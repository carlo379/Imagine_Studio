import React,{useEffect,useRef,useState} from 'react';
import {service} from './studio-service';

export function InspirationLibrary({ids,disabled,attach,close}:{ids:string[];disabled:boolean;attach:(ids:string[])=>Promise<void>;close:()=>void}){
 const [images,setImages]=useState<any[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[query,setQuery]=useState(''),[selected,setSelected]=useState<string[]>([]),[adding,setAdding]=useState(false);
 const lock=useRef(false),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{let cancelled=false;
  Promise.all([service('assets'),service('references'),service('image-studio/jobs')]).then(([assets,references,jobs]:any[])=>{
   if(cancelled)return;
   const titles=new Map<string,string>();
   for(const job of jobs)for(const output of job.outputs||[])titles.set(output.id,job.draft?.title||output.name||'Generated image');
   for(const reference of references)if(!reference.archived)for(const image of reference.images||[])if(image.asset_id)titles.set(image.asset_id,reference.title);
   setImages(assets.filter((a:any)=>a.mime?.startsWith('image/')&&!['rejected','trashed'].includes(a.review_state)&&(!a.generated||a.approved)).slice().reverse().map((a:any)=>({...a,title:titles.get(a.id)||a.name||'Image'})));setLoading(false);
  }).catch(e=>{if(!cancelled){setError(e.message);setLoading(false);}});
  return()=>{cancelled=true;};
 },[]);
 useEffect(()=>{if(!adding)setSelected(current=>current.filter(id=>!ids.includes(id)));},[ids.join('|'),adding]);
 const visible=images.filter(image=>(image.title+' '+image.name).toLowerCase().includes(query.toLowerCase())),remaining=5-ids.length;
 async function add(){if(lock.current)return;lock.current=true;setAdding(true);setError('');try{if(selected.length>remaining)throw Error('Choose up to '+remaining+' more inspiration images.');await attach(selected);if(alive.current)setSelected([]);}catch(e:any){if(alive.current)setError(e.message);}finally{lock.current=false;if(alive.current)setAdding(false);}}
 return <section className="wb-inspiration-library" aria-label="Choose inspiration from Library"><div className="wb-library-heading"><h3>02 Choose inspiration from your Library</h3></div>
  <p className="ft-note">Library images · Choose uploads or approved generated images.</p>
  <label>Search Library images<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search by name, such as Studio"/></label>
  {loading&&<p role="status">Loading Library images…</p>}{error&&<p role="alert" className="wb-error">{error}</p>}
  <div className="wb-library-image-grid">{visible.map(image=>{const attached=ids.includes(image.id),chosen=selected.includes(image.id);return <button className={'wb-library-image '+(chosen?'selected':'')} key={image.id} aria-label={'Select '+image.title} aria-pressed={chosen} disabled={disabled||adding||attached||(!chosen&&selected.length>=remaining)} onClick={()=>setSelected(current=>current.includes(image.id)?current.filter(id=>id!==image.id):[...current,image.id])}><img src={image.src||'/api/assets/'+image.id} alt={image.title} loading="lazy"/><strong>{image.title}</strong><small>{attached?'✓ Already attached':chosen?'✓ Selected':image.generated?'Approved image':'Uploaded image'}</small></button>;})}</div>
  {!loading&&!visible.length&&<p className="ft-note">{query?'No Library images match your search.':'No eligible images yet. Upload an image or approve a generated image first.'}</p>}
  <p className="wb-library-selection-count" role="status">{selected.length} selected · {ids.length} / 5 attached</p><div className="wb-library-actions"><button className="p-primary" disabled={disabled||adding||!selected.length||selected.length>remaining} onClick={()=>void add()}>{adding?'Adding…':'Add '+selected.length+' selected '+(selected.length===1?'image':'images')}</button><button disabled={adding} onClick={close}>Done browsing</button></div>
 </section>;
}
