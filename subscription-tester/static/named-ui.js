/* Shares the studio's local image library and scene state. */
let namedLibrary=[], editor=null,editorAfterSave=null;
const namedSource = input => lookup(input);
function handleFromTitle(title){return title.normalize('NFKD').replace(/[^A-Za-z0-9 ]/g,'').trim().replace(/ +/g,'_').replace(/^[^A-Za-z]+/,'').slice(0,config.reference_handle_limit);}
function namedExpansion(){return NamedScene.expand(project.prompt,project.named||[],project.refs,activeVoices(),!!activeFirst());}
function attachNamed(record,insert=false){
  if(project.named?.some(n=>n.id===record.id)){if(insert)insertTag('@'+record.handle+' ');return true;}
  if(project.named?.some(n=>n.handle.toLowerCase()===record.handle.toLowerCase())){toast('A snapshot with this mention name is already in this scene. Remove it before using the updated reference.');return false;}
  if(project.refs.length+record.images.length>14){toast(`Adding ${record.title} would exceed 14 reference images. Remove other images first.`);return false;}
  if(record.voice&&project.voices.length>=3){toast('This reference would exceed 3 saved voices. Remove a voice first.');return false;}
  const refs=record.images.map(image=>({id:uid(),source:namedSource(image),namedId:record.id}));
  const voice=record.voice?{id:uid(),voice:record.voice,namedId:record.id}:null;
  const binding={...record,refIds:refs.map(r=>r.id),voiceId:voice?.id||null};
  change(()=>{project.refs.push(...refs);if(voice)project.voices.push(voice);(project.named||=[]).push(binding);});
  if(insert)insertTag('@'+record.handle+' ');
  return true;
}
function syncMentions(){for(const handle of NamedScene.mentions(project.prompt)){if((project.named||[]).some(n=>n.handle.toLowerCase()===handle.toLowerCase()))continue;const record=namedLibrary.find(r=>!r.archived&&r.handle.toLowerCase()===handle.toLowerCase());if(record)attachNamed(record);}}
function removeSceneNamed(binding){change(()=>{project.refs=project.refs.filter(r=>!binding.refIds.includes(r.id));project.voices=project.voices.filter(v=>v.id!==binding.voiceId);project.named=project.named.filter(n=>n!==binding);project.prompt=project.prompt.replace(new RegExp('@'+binding.handle+'(?![A-Za-z0-9_])','gi'),binding.title);});}
function removeSceneNamedView(binding,ref){
  change(()=>{
    project.refs=project.refs.filter(r=>r.id!==ref.id);
    const index=binding.refIds.indexOf(ref.id);
    if(index>=0){binding.refIds.splice(index,1);binding.images.splice(index,1);}
  });
}
function keepAttachedSceneViews(binding){
  const indexes=binding.refIds.map((id,i)=>project.refs.some(r=>r.id===id)?i:-1).filter(i=>i>=0);
  if(!indexes.length)return;
  change(()=>{binding.images=indexes.map(i=>binding.images[i]);binding.refIds=indexes.map(i=>binding.refIds[i]);});
}
function restoreSceneNamed(binding){
  const missing=binding.refIds.filter(id=>!project.refs.some(r=>r.id===id));
  if(project.refs.length+missing.length>14)return toast('Remove other images before restoring this reference.');
  if(binding.voiceId&&!project.voices.some(v=>v.id===binding.voiceId)&&project.voices.length>=3)return toast('Remove a voice before restoring this reference.');
  change(()=>{binding.refIds.forEach((id,i)=>{if(!project.refs.some(r=>r.id===id))project.refs.push({id,source:namedSource(binding.images[i]),namedId:binding.id});});if(binding.voiceId&&!project.voices.some(v=>v.id===binding.voiceId))project.voices.push({id:binding.voiceId,voice:binding.voice,namedId:binding.id});});
}
function renderSceneNamed(){const box=$('sceneNamed');box.replaceChildren();box.hidden=true;}
function renderVideoReferenceCards(){
  const box=$('refs');box.replaceChildren();box.classList.add('video-reference-list');
  const groups=[],seen=new Set();
  for(const ref of project.refs){
    const binding=(project.named||[]).find(n=>n.refIds.includes(ref.id));
    if(binding){if(!seen.has(binding.id)){seen.add(binding.id);groups.push({binding,refs:project.refs.filter(r=>binding.refIds.includes(r.id))});}}
    else groups.push({binding:null,refs:[ref]});
  }
  for(const binding of project.named||[])if(!seen.has(binding.id))groups.push({binding,refs:[]});
  for(const {binding,refs} of groups){
    const card=el('article','video-reference-card'),heading=el('div','video-reference-heading'),identity=el('div','video-reference-identity');
    const name=binding?.title||refs[0]?.source.name||'Reference image';
    identity.append(el('strong','',name),el('small','hint',binding?binding.category+' · @'+binding.handle:'Additional image reference'));
    heading.append(identity);const remove=button('×',()=>binding?removeSceneNamed(binding):change(()=>{project.refs=project.refs.filter(r=>r.id!==refs[0].id);}),'video-reference-remove');remove.setAttribute('aria-label','Remove '+name+' from video');heading.append(remove);card.append(heading);
    const views=el('div','video-reference-views');
    for(const ref of refs){
      const i=project.refs.findIndex(r=>r.id===ref.id),tag='IMAGE_'+(i+(activeFirst()?1:0)),view=el('div','video-reference-view');
      const image=button('',()=>previewSource(ref.source),'video-reference-preview');image.setAttribute('aria-label','Preview '+name+' · '+tag);image.append(thumbnail(ref.source));dragSource(image,ref.source,{refId:ref.id});view.append(image);
      const row=el('div','video-reference-view-actions'),insert=button(tag,()=>insertTag('<'+tag+'>'),'video-reference-tag');insert.setAttribute('aria-label','Insert '+tag+' into direction');
      const left=button('←',()=>change(()=>{[project.refs[i-1],project.refs[i]]=[project.refs[i],project.refs[i-1]];}),'video-reference-order');left.disabled=i===0;left.setAttribute('aria-label','Move '+name+' reference earlier');
      const right=button('→',()=>change(()=>{[project.refs[i],project.refs[i+1]]=[project.refs[i+1],project.refs[i]];}),'video-reference-order');right.disabled=i===project.refs.length-1;right.setAttribute('aria-label','Move '+name+' reference later');
      row.append(insert,left,right);view.append(row);
      if(refs.length>1){const removeView=button('Remove view',()=>binding?removeSceneNamedView(binding,ref):change(()=>{project.refs=project.refs.filter(r=>r.id!==ref.id);}),'video-reference-view-remove');removeView.setAttribute('aria-label','Remove '+name+' · '+tag);view.append(removeView);}
      view.ondragover=e=>e.preventDefault();view.ondrop=async e=>{e.preventDefault();e.stopPropagation();const data=dragData(e);if(data?.refId){change(()=>{const from=project.refs.findIndex(r=>r.id===data.refId);if(from<0)return;const [item]=project.refs.splice(from,1);project.refs.splice(i,0,item);});}else await drop(e,'refs');};views.append(view);
    }
    if(!refs.length)views.append(el('p','video-reference-missing',binding?.voiceId?'Voice reference · no active image':'Reference images are missing'));
    card.append(views);
    if(binding){
      const actions=el('div','video-reference-actions');actions.append(button('Insert name',()=>insertTag('@'+binding.handle+' '),'video-reference-insert'));
      const missingImages=binding.refIds.some(id=>!project.refs.some(r=>r.id===id));
      const missingVoice=binding.voiceId&&!project.voices.some(v=>v.id===binding.voiceId);
      if(missingImages||missingVoice){
        if(missingImages&&refs.length)actions.append(button(refs.length===1?'Use attached view only':'Use attached views',()=>keepAttachedSceneViews(binding),'video-reference-restore'));
        actions.append(button('Restore views',()=>restoreSceneNamed(binding),'video-reference-restore'));
        card.append(el('p','video-reference-missing',missingImages&&refs.length?'A removed view is still linked. Keep the attached views or restore the missing ones.':'Some saved views or the voice are missing. Restore them or remove this asset.'));
      }card.append(actions);
      if(binding.description||binding.video_summary){const details=el('details','video-reference-details');details.append(el('summary','',binding.video_summary?'Video identity cue':'Identity details'),el('p','',binding.video_summary||binding.description));if(binding.video_summary){const original=el('details');original.append(el('summary','','Original asset description'),el('p','',binding.description));details.append(original);}card.append(details);}
    }
    box.append(card);
  }
}

async function openNamed(){try{namedLibrary=await api('/api/references');renderNamedCards();$('namedDialog').showModal();}catch(error){toast(error.message);}}
function renderNamedCards(){
  const box=$('namedCards'),query=$('namedSearch').value.toLowerCase(),category=$('namedFilter').value;box.replaceChildren();
  const records=namedLibrary.filter(r=>(category==='archived'?r.archived:!r.archived)&&(category==='all'||category==='archived'||r.category===category)&&`${r.title} ${r.handle} ${r.description}`.toLowerCase().includes(query));
  for(const record of records){const card=el('article','named-card'),images=el('div','named-card-images');for(const input of record.images.slice(0,3))images.append(thumbnail(namedSource(input)));if(!record.images.length)images.append(el('span','voice-only','♫'));card.append(images,el('span','named-category',record.category),el('h3','',record.title),el('code','', '@'+record.handle),el('p','',record.description||'No description'),el('small','hint',`${record.images.length} images${record.voice?' · '+record.voice+' voice':''}`));if(record.needs_replacement)card.append(el('p','error','Needs replacement · this reference contains an unapproved or rejected image. Existing work is preserved.'));const actions=el('div','row');if(!record.archived){actions.append(button(studioView==='image'?'Use for image':'Use in scene',()=>{if(studioView==='image'){imageAttach(record);$('namedDialog').close();}else if(attachNamed(record,true))$('namedDialog').close();},'primary'),button('Edit',()=>openEditor(record),'secondary'));if(record.needs_replacement)actions.firstChild.disabled=true;}else actions.append(button('Restore',()=>archiveNamed(record,false),'secondary'));actions.append(button(record.archived?'':'Archive',()=>archiveNamed(record,true)));if(record.archived)actions.lastChild.remove();card.append(actions);box.append(card);}
  if(!records.length)box.append(el('p','hint',category==='archived'?'No archived references.':'Save a Character, Location or Prop, then reuse it by @name in any scene.'));
}
async function archiveNamed(record,archived){try{await api('/api/references/archive',{id:record.id,archived});record.archived=archived;renderNamedCards();toast(archived?'Archived locally. Existing scenes retain their snapshot.':'Reference restored.');}catch(e){toast(e.message);}}
function openEditor(record,afterSave=null){
  editorAfterSave=afterSave;
  $('referenceSuggestionNote').hidden=true;
  editor=record?{...structuredClone(record),expected_revision:record.revision||1}:{title:'',handle:'',description:'',category:'Character',voice:null,images:[]};
  $('editorHeading').textContent=record?'Edit reference':'New reference';$('referenceTitle').value=editor.title;$('referenceHandle').value=editor.handle;$('referenceHandle').dataset.manual=record?'true':'';$('referenceDescription').value=editor.description;$('referenceCategory').value=editor.category;$('referenceVoice').value=editor.voice||'';$('referenceError').textContent='';renderEditorImages();referenceVoiceFields();$('referenceEditor').showModal();
}
function referenceVoiceFields(){$('referenceVoiceFields').hidden=!!editor?._imageOrigin&&$('referenceCategory').value!=='Character';}
function renderEditorImages(){const box=$('editorImages');box.replaceChildren();editor.images.forEach((image,i)=>{const card=el('div','editor-image');card.append(thumbnail(namedSource(image)));const actions=el('div','reorder');for(const [text,delta] of [['←',-1],['→',1]]){const move=button(text,()=>{[editor.images[i],editor.images[i+delta]]=[editor.images[i+delta],editor.images[i]];renderEditorImages();});move.disabled=i+delta<0||i+delta>=editor.images.length;move.setAttribute('aria-label',`Move saved image ${i+1} ${delta<0?'left':'right'}`);actions.append(move);}const remove=button('×',()=>{editor.images.splice(i,1);renderEditorImages();});remove.setAttribute('aria-label',`Remove saved image ${i+1}`);actions.append(remove);card.append(actions);box.append(card);});$('editorImageCount').textContent=`${editor.images.length} / 7`;$('editorAddImage').disabled=editor.images.length>=7;}
function editorChoose(source){if(editor.images.length>=7)return toast('Save at most 7 images in one reference.');editor.images.push(sourceBody(source));renderEditorImages();$('library').close();}
async function initNamed(){
  namedLibrary=await api('/api/references');project.named||=[];
  config.voices.forEach(voice=>$('referenceVoice').append(new Option(voice.charAt(0).toUpperCase()+voice.slice(1),voice)));
  $('referenceTitle').maxLength=config.reference_title_limit;$('referenceDescription').maxLength=config.reference_description_limit;$('referenceHandle').maxLength=config.reference_handle_limit;
  $('namedOpen').onclick=openNamed;$('sceneReferences').onclick=openNamed;$('closeNamed').onclick=()=>$('namedDialog').close();$('newNamed').onclick=()=>openEditor();$('closeEditor').onclick=()=>$('referenceEditor').close();$('namedSearch').oninput=renderNamedCards;$('namedFilter').onchange=renderNamedCards;
  $('referenceCategory').onchange=referenceVoiceFields;
  $('referenceTitle').oninput=()=>{if(!$('referenceHandle').dataset.manual)$('referenceHandle').value=handleFromTitle($('referenceTitle').value);};$('referenceHandle').oninput=()=>$('referenceHandle').dataset.manual='true';
  $('editorAddImage').onclick=()=>openLibrary('editor');
  const zone=$('editorImageDrop');zone.ondragover=e=>e.preventDefault();zone.ondrop=async e=>{e.preventDefault();try{const data=dragData(e);const sources=e.dataTransfer.files.length?await uploadFiles([...e.dataTransfer.files]):data?.source?[data.source]:[];for(const source of sources){if(editor.images.length>=7)break;editor.images.push(sourceBody(source));}renderEditorImages();}catch(error){$('referenceError').textContent=error.message;}};
  $('referenceForm').onsubmit=async e=>{e.preventDefault();$('saveNamed').disabled=true;try{const origin=editor._imageOrigin;const details={...editor,title:$('referenceTitle').value,handle:$('referenceHandle').value,description:$('referenceDescription').value,category:$('referenceCategory').value,voice:$('referenceVoiceFields').hidden?null:$('referenceVoice').value||null};const record=origin?await imageAPI('/jobs/'+origin.job_id+'/reference','POST',{...details,asset_id:origin.asset_id}):await api('/api/references/save',details);namedLibrary=[record,...namedLibrary.filter(r=>r.id!==record.id)];if(editorAfterSave)await editorAfterSave(record);$('referenceEditor').close();renderNamedCards();toast('Asset saved locally. Existing scenes keep their snapshots; adopt the updated version explicitly.');}catch(error){$('referenceError').textContent=error.message;}finally{$('saveNamed').disabled=false;}};
  syncMentions();renderSceneNamed();
}
