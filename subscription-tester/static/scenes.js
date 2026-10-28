/* Shared persisted scenes: browser and agent API use the same record/revision. */
let sceneRecord=null,sceneTimer=null,sceneSaving=false,sceneDirty=false,sceneApplying=false,sceneReady=false,sceneConflict=false,sceneSaveError=null;
async function sceneAPI(path,method='GET',data,key){
  if(method==='GET'&&window.StudioRuntime)return window.StudioRuntime.json('/api/agent'+path);
  const response=await fetch('/api/agent'+path,{method,headers:method==='GET'?{}:{'Content-Type':'application/json','X-Tester':'local',...(key?{'Idempotency-Key':key}:{})},body:method==='GET'?undefined:JSON.stringify(data||{})});
  const result=await response.json();if(!response.ok){const error=Error(result.error?.message||'Scene request failed.');error.code=result.error?.code;error.status=response.status;throw error;}return result;
}
async function removeRememberedURL(source){
  try{
    await sceneAPI('/urls/'+source.url_id+'/archive','POST',{expected_revision:source.revision,archived:true});
    urls=await sceneAPI('/urls');persist();renderLibrary();
  }catch(error){
    if(error.code==='revision_conflict'){
      try{urls=await sceneAPI('/urls');renderLibrary();}catch{} // Preserve the original conflict message.
    }
    $('libraryError').textContent=error.message;
  }
}
function sceneStatus(text){$('sceneSyncStatus').textContent=text;}
function applyScene(record){if(sceneRecord?.id!==record.id&&$('allowUnapprovedStart'))$('allowUnapprovedStart').checked=false;sceneApplying=true;sceneSaveError=null;localStorage.removeItem('imagine-scene-recovery');sceneRecord=record;renderVideoHistory();project={...blank(),...structuredClone(record.scene)};$('sceneTitle').value=record.title;sceneDirty=false;sceneConflict=false;$('approved').checked=false;render();sceneApplying=false;sceneStatus('Saved · shared with agents');if(typeof storyContextBar==='function')storyContextBar();}
function keepSceneDraft(){
  if(sceneRecord)localStorage.setItem('imagine-scene-recovery',JSON.stringify({id:sceneRecord.id,base:sceneRecord,title:$('sceneTitle').value,scene:project,saved_at:Date.now()}));
}
function queueSceneSave(){
  if(!sceneReady||sceneApplying)return;
  if(!sceneDirty&&sceneRecord&&JSON.stringify(project)===JSON.stringify(sceneRecord.scene)&&$('sceneTitle').value===sceneRecord.title)return;
  sceneDirty=true;keepSceneDraft();if(sceneConflict)return;
  sceneStatus('Saving scene…');clearTimeout(sceneTimer);sceneTimer=setTimeout(saveScene,400);
}
async function saveScene(){
  if(sceneSaving||!sceneDirty||sceneConflict)return;
  const title=$('sceneTitle').value;
  if(!title.trim()){keepSceneDraft();sceneStatus('Enter a scene title · draft preserved');return;}
  sceneSaving=true;sceneDirty=false;const snapshot=structuredClone(project),base=structuredClone(sceneRecord);
  try{
    let saved,mergedApplied=false;
    try{saved=base?await sceneAPI('/scenes/'+base.id,'PUT',{expected_revision:base.revision,title,scene:snapshot}):await sceneAPI('/workspace','POST',{title,scene:snapshot});}
    catch(error){
      if(error.code!=='revision_conflict'||!base)throw error;
      const latest=await sceneAPI('/scenes/'+base.id),merged=mergeSceneSave(base,{title,scene:snapshot},latest);
      if(merged.conflicts.length){error.message='Another tab or agent changed '+merged.conflicts.join(', ')+'. Your draft is preserved; save a copy or review the saved scene.';throw error;}
      saved=await sceneAPI('/scenes/'+base.id,'PUT',{expected_revision:latest.revision,...merged.result});
      if(!sceneDirty&&JSON.stringify(project)===JSON.stringify(snapshot)&&$('sceneTitle').value===title){project=structuredClone(saved.scene);if((typeof document==='undefined'||document.activeElement!==$('sceneTitle'))&&$('sceneTitle').value!==saved.title)$('sceneTitle').value=saved.title;mergedApplied=true;}
    }
    sceneRecord=saved;sceneSaveError=null;if(mergedApplied){sceneApplying=true;render();sceneApplying=false;}
    if(sceneDirty)keepSceneDraft();else localStorage.removeItem('imagine-scene-recovery');
    sceneStatus(sceneDirty?'Saving latest edits…':'Saved · shared with agents');
    if(typeof window!=='undefined')window.dispatchEvent(new CustomEvent('production-media-renamed',{detail:{kind:'video',id:saved.id,title:saved.title}}));
  }catch(error){sceneDirty=true;sceneSaveError=error;sceneConflict=error.code==='revision_conflict';keepSceneDraft();sceneStatus((sceneConflict?'Save conflict':'Save failed')+' · '+error.message+' · draft preserved');toast(error.message);}
  finally{sceneSaving=false;if(sceneDirty&&!sceneConflict&&!sceneSaveError){clearTimeout(sceneTimer);sceneTimer=setTimeout(saveScene,100);}}
}
async function retrySceneSave(){sceneConflict=false;sceneSaveError=null;sceneDirty=true;await saveScene();}
async function syncScene(){
  if(!sceneReady||sceneSaving||sceneDirty||sceneConflict||(typeof document!=='undefined'&&document.activeElement===$('sceneTitle')))return;
  const baseline=sceneRecord;const title=$('sceneTitle').value, snapshot=JSON.stringify(project);
  try{
    const remoteURLs=await sceneAPI('/urls'),record=await sceneAPI('/workspace');
    // A network response may arrive after editing, saving, or selecting a different scene.
    if(sceneSaving||sceneDirty||sceneConflict||sceneRecord!==baseline||$('sceneTitle').value!==title||JSON.stringify(project)!==snapshot)return;
    urls=remoteURLs;
    if($('library')?.open)renderLibrary();
    if(record&&(!sceneRecord||record.id!==sceneRecord.id||record.revision!==sceneRecord.revision)){
      const [newAssets,newReferences]=await Promise.all([api('/api/assets'),api('/api/references')]);
      if(sceneSaving||sceneDirty||sceneConflict||sceneRecord!==baseline||$('sceneTitle').value!==title||JSON.stringify(project)!==snapshot)return;
      assets=newAssets;namedLibrary=newReferences;applyScene(record);toast('Scene updated through the shared workspace.');
    }
  }catch{} // Keep local drafts untouched on a failed refresh.
}
async function selectScene(record){
  clearTimeout(sceneTimer);if(sceneDirty&&!sceneConflict)await saveScene();
  if(sceneDirty||sceneConflict)return toast('Save a copy of your local draft before loading another scene.');
  applyScene(await sceneAPI('/workspace','POST',{scene_id:record.id}));$('scenesDialog').close();
}
async function createScene(copyDraft=false){
  if(!copyDraft&&sceneDirty&&!sceneConflict)await saveScene();
  if((sceneConflict||sceneDirty)&&!copyDraft)return toast('Use Save draft as copy before starting a new scene.');
  const record=await sceneAPI('/scenes','POST',{title:copyDraft?($('sceneTitle').value||'Scene')+' copy':'New scene',scene:copyDraft?structuredClone(project):blank(),story_context:copyDraft?sceneRecord?.story_context:null});
  sceneDirty=false;sceneConflict=false;applyScene(await sceneAPI('/workspace','POST',{scene_id:record.id}));
  if($('scenesDialog').open)$('scenesDialog').close();
}
async function openScenes(){
  try{const records=await sceneAPI('/scenes');const box=$('sceneCards');box.replaceChildren();
    for(const record of records){const card=el('article','history-card');card.append(el('strong','',record.title),el('p','hint',`${record.scene.duration}s · ${record.scene.resolution} · revision ${record.revision}${record.archived?' · archived':''}`));
      const row=el('div','row');if(!record.archived)row.append(button('Load scene',()=>selectScene(record).catch(e=>toast(e.message)),'secondary'));
      row.append(button(record.archived?'Restore':'Archive',async()=>{try{if(sceneRecord?.id===record.id&&!record.archived)return toast('Load another scene before archiving the current one.');await sceneAPI('/scenes/'+record.id+'/archive','POST',{expected_revision:record.revision,archived:!record.archived});openScenes();}catch(e){toast(e.message);}}));card.append(row);box.append(card);
    }$('scenesDialog').showModal();
  }catch(e){toast(e.message);}
}
async function initScenes(){
  for(const source of urls){if(source.src?.startsWith('https://'))await sceneAPI('/urls','POST',{url:source.src,name:source.name});}
  urls=await sceneAPI('/urls');
  sceneRecord=await sceneAPI('/workspace');
  if(!sceneRecord){try{sceneRecord=await sceneAPI('/workspace','POST',{title:'Current scene',scene:project});}catch(e){toast('Draft could not be shared: '+e.message);}}
  let recovery;try{recovery=JSON.parse(localStorage.getItem('imagine-scene-recovery'));}catch{}
  if(sceneRecord)project={...blank(),...structuredClone(sceneRecord.scene)};$('sceneTitle').value=sceneRecord?.title||'Unshared draft';
  $('sceneTitle').oninput=queueSceneSave;$('scenesOpen').onclick=openScenes;$('newScene').onclick=()=>createScene().catch(e=>toast(e.message));
  $('retrySceneSave').onclick=retrySceneSave;
  $('copyScene').onclick=()=>createScene(true).catch(e=>toast(e.message));$('reloadScene').onclick=async()=>{try{sceneDirty=false;sceneConflict=false;applyScene(await sceneAPI('/workspace'));$('scenesDialog').close();}catch(e){toast(e.message);}};
  $('closeScenes').onclick=()=>$('scenesDialog').close();sceneReady=true;if(recovery&&sceneRecord&&recovery.id===sceneRecord.id&&(JSON.stringify(recovery.scene)!==JSON.stringify(sceneRecord.scene)||recovery.title!==sceneRecord.title)){project=structuredClone(recovery.scene);$('sceneTitle').value=recovery.title;sceneRecord=recovery.base;sceneDirty=true;sceneStatus('Recovered unsaved draft · retry saving or save a copy');}else sceneStatus(sceneRecord?'Saved · shared with agents':'Draft not shared · fix missing inputs or start a new scene');window.StudioRuntime?.watch(syncScene,{areas:['video','productions'],active:()=>window.StudioRuntime.visible('videoStudio')});
}
