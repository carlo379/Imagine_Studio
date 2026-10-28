/* Saved asset mentions; no network generation or prompt rewriting. */
(function(root){
 function mentionAtCaret(text,start,end=start){
  if(start!==end)return null;
  const match=text.slice(0,start).match(/(^|[^A-Za-z0-9_@])@([A-Za-z0-9_]*)$/);
  if(!match)return null;
  return {start:start-match[2].length-1,end:start+(text.slice(start).match(/^[A-Za-z0-9_]*/)||[''])[0].length,query:match[2]};
 }
 function filterAssets(records,query){const q=query.toLowerCase();return records.filter(r=>!r.archived&&(r.handle.toLowerCase().includes(q)||r.title.toLowerCase().includes(q))).sort((a,b)=>Number(b.handle.toLowerCase().startsWith(q))-Number(a.handle.toLowerCase().startsWith(q))||a.title.localeCompare(b.title));}
 function syncImageMentions(settings,records){
  if(settings.base)return 0;
  let count=(settings.base?1:0)+settings.extras.length+settings.bindings.reduce((n,b)=>n+b.selected.length,0),added=0;
  const attached=new Set(settings.bindings.map(b=>b.snapshot.handle.toLowerCase()));
  for(const match of settings.prompt.matchAll(/(?:^|[^A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]*)/g)){
   const key=match[1].toLowerCase(),record=records.find(r=>!r.archived&&r.handle.toLowerCase()===key);
   if(attached.has(key)||!record?.images.length||count>=5||settings.bindings.length>=20)continue;
   settings.bindings.push({snapshot:structuredClone(record),selected:[0]});attached.add(key);count++;added++;
  }return added;
 }
 root.AssetMentions={mentionAtCaret,filterAssets,syncImageMentions};if(typeof module!=='undefined')module.exports=root.AssetMentions;
})(typeof window==='undefined'?globalThis:window);
function initAssetAutocomplete(id,kind){
 const input=$(id),wrap=el('div','asset-mention-wrap'),list=el('div','asset-mention-list');input.before(wrap);wrap.append(input,list);list.id=id+'AssetOptions';list.role='listbox';list.setAttribute('aria-label','Available assets');list.hidden=true;
 input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls',list.id);input.setAttribute('aria-haspopup','listbox');input.setAttribute('aria-expanded','false');
 let active=0,matches=[],token=null,version=0;
 const close=()=>{list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');};
 function records(){const saved=new Map(namedLibrary.filter(r=>!r.archived).map(r=>[r.id,r]));const attached=kind==='image'?imageSettings?.bindings.map(b=>b.snapshot):project.named;for(const r of attached||[])saved.set(r.id,{...r,archived:false});return [...saved.values()];}
 function show(){token=AssetMentions.mentionAtCaret(input.value,input.selectionStart,input.selectionEnd);if(!token)return close();matches=AssetMentions.filterAssets(records(),token.query);active=Math.min(active,Math.max(0,matches.length-1));list.replaceChildren();
  if(!matches.length)list.append(el('p','hint','No matching assets. Save one in References.'));
  matches.forEach((record,i)=>{const option=button('',()=>pick(i),'asset-mention-option');option.role='option';option.id=list.id+'-'+i;option.tabIndex=-1;const unavailable=kind==='image'&&!record.images.length;option.setAttribute('aria-disabled',String(unavailable));option.setAttribute('aria-selected',String(i===active));option.classList.toggle('active',i===active);option.append(el('strong','',record.title),el('span','hint','@'+record.handle+' · '+record.category+(unavailable?' · needs an image':'')));option.onmousedown=e=>e.preventDefault();list.append(option);});
  list.hidden=false;input.setAttribute('aria-expanded','true');if(matches[active])input.setAttribute('aria-activedescendant',list.id+'-'+active);else input.removeAttribute('aria-activedescendant');
 }
 async function pick(index){const record=matches[index],at=token;if(!record||!at)return;try{
  if(kind==='image'){if(!imageSettings.bindings.some(b=>b.snapshot.id===record.id)&&!await imageAttach(record))return;}
  else if(!attachNamed(record))return;
  const inserted='@'+record.handle+' ';const value=input.value.slice(0,at.start)+inserted+input.value.slice(at.end);
  if(kind==='image'){imageSettings.prompt=value;input.value=value;imageTouch();}else{project.prompt=value;render();}
  close();input.focus();input.setSelectionRange(at.start+inserted.length,at.start+inserted.length);
 }catch(error){toast(error.message);}
 }
 input.addEventListener('input',()=>{active=0;show();});input.addEventListener('click',show);input.addEventListener('keyup',e=>{if(!['ArrowDown','ArrowUp','Enter','Tab','Escape'].includes(e.key))show();});
 input.addEventListener('keydown',e=>{if(list.hidden)return;if(e.key==='Escape'){e.preventDefault();version++;close();}else if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();if(matches.length)active=(active+(e.key==='ArrowDown'?1:-1)+matches.length)%matches.length;show();list.children[active]?.scrollIntoView({block:'nearest'});}else if((e.key==='Enter'||e.key==='Tab')&&matches.length){e.preventDefault();pick(active);}});
 input.addEventListener('blur',()=>setTimeout(()=>{if(!wrap.contains(document.activeElement))close();},100));
 input.addEventListener('focus',async()=>{const current=++version;try{const refs=await api('/api/references');if(current!==version)return;namedLibrary=refs;if(kind==='image'&&imageSettings&&AssetMentions.syncImageMentions(imageSettings,refs))imageTouch(true);if(document.activeElement===input)show();}catch{}});
 document.addEventListener('pointerdown',e=>{if(!wrap.contains(e.target))close();});
}
