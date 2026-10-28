/* The new shell reuses the proven controls and their conflict-safe saves. */
window.productionBridge={
  loading:false,
  historyShot:null,
  imageSelectionBusy:false,
  syncImageSelection(){
    const button=$('imageSelectShot');if(!button)return;
    const shot=this.historyShot,job=imageActiveJob,output=imageSelectedOutput(job);
    const member=shot?.image_takes?.some(t=>t.id===job?.id)||shot?.image_versions?.some(d=>d.id===job?.draft?.id)||shot?.image?.id===job?.draft?.id;
    const available=this.guided()&&member&&job?.status==='done'&&!!output&&!['rejected','trashed'].includes(output.review_state);
    const selected=available&&shot.selected_image===output.id;
    button.hidden=!available;button.disabled=this.imageSelectionBusy||this.loading;
    button.textContent=this.imageSelectionBusy?'Saving selection…':selected?'✓ Selected · Deselect':'Select for shot';
    button.setAttribute('aria-pressed',String(!!selected));
    button.title=selected?'Remove the chosen image; keep this version in history.':'Approve this image and choose it for the shot.';
  },
  async selectDisplayedImage(){
    if(this.imageSelectionBusy)return;
    const shotId=this.historyShot?.id,job=imageActiveJob,output=imageSelectedOutput(job);
    if(!this.guided()||!shotId||!output)return;
    const deselect=this.historyShot.selected_image===output.id;
    this.imageSelectionBusy=true;this.syncImageSelection();
    try{
      const shot=await sceneAPI('/productions/shots/'+shotId);
      if(this.historyShot?.id!==shotId||imageActiveJob?.id!==job.id||imageSelectedOutput()?.id!==output.id)throw Error('The displayed image changed. Review it before selecting.');
      if(deselect&&shot.selected_image!==output.id){this.historyShot=shot;throw Error('The selected image changed elsewhere. Review it before deselecting.');}
      if(!deselect&&!output.approved){await imageAPI('/jobs/'+job.id+'/approve','POST',{asset_id:output.id,approved:true});assets=await api('/api/assets');imageShowJob(await imageAPI('/jobs/'+job.id));}
      const saved=await sceneAPI('/productions/shots/'+shotId+'/select-take','POST',{expected_revision:shot.revision,kind:'image',id:deselect?null:output.id});
      if(this.historyShot?.id===shotId)this.historyShot=saved;
      await imageHistory();window.dispatchEvent(new CustomEvent('production-media-renamed',{detail:{kind:'image',id:imageDraft.id}}));
    }catch(error){toast(error.message);}finally{this.imageSelectionBusy=false;this.syncImageSelection();}
  },
  videoSelectionBusy:false,
  updateVideoSelection(shot){
    if(this.historyShot?.id===shot.id)this.historyShot=shot;
    this.syncVideoSelection();
  },
  syncVideoSelection(){
    const button=$('selectVideoTake');if(!button)return;
    const shot=this.historyShot;
    const scoped=this.guided()&&!!shot?.video?.id&&shot.video.id===sceneRecord?.id;
    const take=scoped&&(shot.video_takes.find(j=>j.id===frameJob)||history.find(j=>j.id===frameJob&&j.settings?._studio_video_id===shot.video.id));
    const available=!!take&&take.status==='done'&&!!take.video&&!$('video').hidden;
    const selected=available&&shot.selected_video===frameJob;
    button.hidden=!available;
    button.disabled=this.videoSelectionBusy||this.loading;
    button.textContent=this.videoSelectionBusy?'Saving selection…':selected?'✓ Selected · Deselect':'Select for shot';
    button.setAttribute('aria-pressed',String(!!selected));
    button.title=selected?'Remove this shot’s selection. The video stays in your history.':'Use the video currently displayed as this shot’s chosen take.';
  },
  async selectDisplayedVideo(){
    if(this.videoSelectionBusy)return;
    const shotId=this.historyShot?.id,jobId=frameJob,sceneId=sceneRecord?.id;
    if(!this.guided()||!shotId||!jobId||this.historyShot.video?.id!==sceneId)return;
    const deselect=this.historyShot.selected_video===jobId;
    this.videoSelectionBusy=true;this.syncVideoSelection();
    try{
      // Choosing a completed take changes the shot relationship only. Unrelated
      // image, script and prompt drafts must not block or be saved by this action.
      const shot=await sceneAPI('/productions/shots/'+shotId);
      if(this.historyShot?.id!==shotId||frameJob!==jobId||sceneRecord?.id!==sceneId)throw Error('The displayed shot or video changed. Select the video you want again.');
      if(deselect&&shot.selected_video!==jobId){this.historyShot=shot;throw Error('The selected take changed elsewhere. Review the current selection before deselecting.');}
      if(!deselect&&shot.selected_video===jobId){this.historyShot=shot;return;}
      const saved=await sceneAPI('/productions/shots/'+shotId+'/select-take','POST',{expected_revision:shot.revision,kind:'video',id:deselect?null:jobId});
      if(this.historyShot?.id===shotId)this.historyShot=saved;
      window.dispatchEvent(new CustomEvent('production-media-renamed',{detail:{kind:'video',id:sceneId}}));
    }catch(error){toast(error.message);}
    finally{this.videoSelectionBusy=false;this.syncVideoSelection();}
  },
  guided:()=>document.body.dataset.productionGuided==='true',
  ready:()=>true,
  dirty:()=>sceneDirty||sceneSaving||imageDirty||!!imageSaving||storyDirty||storySaving,
  async flush(){
    await imageFlush();await storyFlush();
    const deadline=Date.now()+5000;
    while(sceneSaving&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,50));
    if(!sceneSaving&&sceneDirty&&!sceneConflict)await saveScene();
    while(sceneSaving&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,50));
    if(sceneSaving||sceneDirty||sceneConflict)throw Error('Your video edits need attention. Wait for saving or use the save controls before leaving this shot.');
  },
  async show(workspace,outline){
    const kind=workspace.stage==='script'?'story':workspace.stage==='generate'?'video':workspace.stage==='storyboard'&&workspace.board_view==='image'?'image':null;
    if(!kind)return;
    await window.ensureStudio(kind);
    this.loading=true;try{
      let shot=outline?.shots.find(s=>s.id===workspace.shot_id);
      if(shot?._summary)shot=await sceneAPI('/productions/shots/'+shot.id);
      this.historyShot=shot||null;
      if(kind==='video'&&shot?.video){
        if(sceneRecord?.id!==shot.video.id)applyScene(await sceneAPI('/scenes/'+shot.video.id));
        await refreshHistory();
        const take=shot.video_takes.find(j=>j.id===shot.selected_video&&j.status==='done')||shot.video_takes.find(j=>j.status==='done');
        if(take?.video)showVideo(take.video,take.id);else{shownVideo=null;frameJob=null;$('video').pause();$('video').removeAttribute('src');$('video').hidden=true;$('emptyPreview').hidden=false;$('download').hidden=true;$('captureFrame').hidden=true;}
      }
      if(kind==='image'&&shot?.image){
        if(imageDraft?.id!==shot.image.id)await imageLoad(await imageAPI('/drafts/'+shot.image.id));
        await imageHistory();
        const take=shot.image_takes.find(j=>j.outputs.some(a=>a.id===shot.selected_image));if(take){imageCandidateIds.set(take.id,shot.selected_image);imageShowJob(take);}
      }
      if(kind==='story'&&workspace.episode_id){
        if(storyEpisode?.id!==workspace.episode_id||storySceneId!==workspace.story_scene_id)await storySelectEpisode(workspace.episode_id,workspace.story_scene_id);
      }
      if(kind==='video'||kind==='image')await poll();
      productionSetStudio(kind);
    }finally{this.loading=false;this.syncVideoSelection();this.syncImageSelection();}
  },
  async reloadMedia(shot){this.loading=true;try{
    this.historyShot=shot;
    renderVideoHistory();renderImageHistory();
    if(shot.video)applyScene(await sceneAPI('/scenes/'+shot.video.id));
    if(shot.image)await imageLoad(await imageAPI('/drafts/'+shot.image.id));
    }finally{this.loading=false;this.syncVideoSelection();this.syncImageSelection();}
  },
  async openTool(view){await window.ensureStudio(view);productionSetStudio(view);},
  async openMedia(kind,id){await window.ensureStudio(kind);this.loading=true;try{if(kind==='image')await imageSelect(await imageAPI('/drafts/'+id));else if(kind==='video')await selectScene(await sceneAPI('/scenes/'+id));else{[storySeries,storyEpisodes,storyLinks]=await Promise.all([storyAPI('/series'),storyAPI('/episodes'),storyAPI('/links')]);storySelectors();const episode=await storyAPI('/episodes/'+id);await storySelectEpisode(id,episode.scenes.length===1?episode.scenes[0].id:null);}}finally{this.loading=false;}},
  async newMedia(kind){await window.ensureStudio(kind);this.loading=true;try{if(kind==='image'){await imageNew();return imageDraft;}if(kind==='video'){await createScene();return sceneRecord;}const series=await storyAPI('/series','POST',{title:'Standalone script'});const ep=await storyAPI('/episodes','POST',{series_id:series.id,title:'Untitled script'});const record=await storyAPI('/episodes/'+ep.id,'PUT',{expected_revision:ep.revision,scenes:[{title:'Script',text:''}]});[storySeries,storyEpisodes]=await Promise.all([storyAPI('/series'),storyAPI('/episodes')]);storySelectors();await storySelectEpisode(record.id,record.scenes[0].id);return record;}finally{this.loading=false;}},
  async recover(kind,copy){await window.ensureStudio(kind);this.loading=true;try{if(kind==='image'){if(copy)await imageNew(true);else await imageLoad(await imageAPI('/drafts/'+imageDraft.id));return imageDraft;}if(kind==='video'){if(copy)await createScene(true);else{sceneDirty=false;sceneConflict=false;applyScene(await sceneAPI('/scenes/'+sceneRecord.id));}return sceneRecord;}const original=structuredClone(storyEpisode);if(copy){const series=await storyAPI('/series','POST',{title:'Standalone script'});const ep=await storyAPI('/episodes','POST',{series_id:series.id,title:original.title+' copy'});const record=await storyAPI('/episodes/'+ep.id,'PUT',{expected_revision:ep.revision,notes:original.notes,scenes:original.scenes.map(({title,text})=>({title,text}))});storyDirty=false;[storySeries,storyEpisodes]=await Promise.all([storyAPI('/series'),storyAPI('/episodes')]);storySelectors();await storySelectEpisode(record.id,record.scenes[0]?.id);return record;}storyDirty=false;await storySelectEpisode(original.id,storySceneId);return storyEpisode;}finally{this.loading=false;}},
  async useImage(asset,target){await window.ensureStudio(target==='video'?'video':'image');if(target==='asset'){openEditor({title:asset.name.replace(/\.[^.]+$/,''),handle:'',description:'',category:'Character',voice:null,images:[{asset_id:asset.id}]});return;}if(target==='video'){project.first=asset;queueSceneSave();render();await saveScene();return;}if(target==='base'){const record=await imageAPI('/drafts','POST',{title:imageDraft.title,parent_draft_id:imageDraft.id,story_context:imageDraft.story_context,settings:{...structuredClone(imageSettings),base:{asset_id:asset.id},prompt:'',bindings:imageSettings.bindings.map(b=>({...structuredClone(b),selected:[]})),extras:[]}});await imageSelect(record);imageWorkspaceTab('compose');return;}if(imageCount()>=imageSourceLimit())throw Error('Remove a reference before adding another.');imageChoose(asset);await imageFlush();},
  async saveDialogs(){if($('storyImportDialog').open)sessionStorage.setItem('imagine-import-'+storyEpisode?.id,JSON.stringify({parsed:storyImport,text:$('storyImportText').value,index:storyImportIndex}));if($('storyChatDialog').open)sessionStorage.setItem('imagine-script-message-'+storyEpisode?.id,$('storyChatMessage').value);if(!$('referenceEditor').open)return;const form=$('referenceForm');if(!form.reportValidity())throw Error('Complete the asset details before switching tools.');if(!$('referenceTitle').value.trim()||!$('referenceHandle').value.trim())throw Error('Add the asset name and handle, or close the asset editor, before switching tools.');if($('saveNamed').disabled)throw Error('Wait for the asset to finish saving.');form.requestSubmit();for(let i=0;i<100&&$('saveNamed').disabled;i++)await new Promise(r=>setTimeout(r,50));if($('referenceEditor').open)throw Error($('referenceError').textContent||'The asset could not be saved. Your edits are still open.');},
  async assets(){await window.ensureStudio('video');document.getElementById('namedOpen').click();},
  async refresh(){await refreshHistory();await imageHistory();},
  imageResult(){const job=imageActiveJob,output=imageSelectedOutput(job);return job?.status==='done'&&output?{job_id:job.id,asset_id:output.id}:null;},
  async showImageJob(id){imageShowJob(await imageAPI('/jobs/'+id));},
  selected(){return {video:sceneRecord?.id,image:imageDraft?.id,script:storyEpisode?.id};},
  imageState(){return imageDraft&&imageSettings?{id:imageDraft.id,revision:imageDraft.revision,model:imageSettings.model,prompt:imageSettings.prompt}:null;},
  videoState(){return sceneRecord?{id:sceneRecord.id,revision:sceneRecord.revision,model:project.model,prompt:project.prompt,duration:project.duration}:null;},
  draftSnapshot(){return structuredClone({image:imageDraft&&imageDirty?{id:imageDraft.id,revision:imageDraft.revision,dirty:true,data:{title:$('imageTitle').value,settings:imageSettings}}:null,video:sceneRecord&&sceneDirty?{id:sceneRecord.id,revision:sceneRecord.revision,dirty:true,data:{title:$('sceneTitle').value,scene:project}}:null});}
};

// Loading refreshed data is passive. Only explicit selection in a visible studio
// may change the production route, and only if that route is still current.
function productionSelectionOrigin(kind){
  const pane=$(kind+'Studio'),host=$('productionToolHost');
  if(!window.productionBridge.guided()||window.productionBridge.loading||!host||host.hidden||!pane||pane.hidden||pane.closest('[hidden]'))return null;
  return window.location.hash;
}
function productionSelectedMedia(kind,id,origin){
  if(origin!==null&&productionSelectionOrigin(kind)===origin)window.dispatchEvent(new CustomEvent('production-media-selected',{detail:{kind,id,selection:true}}));
}
const productionImageSelect=imageSelect;
imageSelect=async function(record){const origin=productionSelectionOrigin('image');await productionImageSelect(record);if(imageDraft?.id===record.id)productionSelectedMedia('image',record.id,origin);};
const productionSelectScene=selectScene;
selectScene=async function(record){const origin=productionSelectionOrigin('video');await productionSelectScene(record);if(sceneRecord?.id===record.id)productionSelectedMedia('video',record.id,origin);};
const productionCreateScene=createScene;
createScene=async function(copy=false){const origin=productionSelectionOrigin('video'),previous=sceneRecord?.id;await productionCreateScene(copy);if(sceneRecord?.id&&sceneRecord.id!==previous)productionSelectedMedia('video',sceneRecord.id,origin);};
const productionSetStudio=setStudio;
setStudio=function(view){if(window.studioNavigate&&!window.productionBridge.loading){return window.studioNavigate(view).catch(e=>toast(e.message));}productionSetStudio(view);};
window.productionBridge.createAsset=async()=>{await window.ensureStudio('video');return openEditor(null,()=>window.dispatchEvent(new Event('assets-updated')));};
window.productionBridge.editAsset=async(record)=>{await window.ensureStudio('video');return openEditor(record,()=>window.dispatchEvent(new Event('assets-updated')));};
window.productionBridge.developAsset=async function(record){await window.ensureStudio('image');await this.flush();await imageSelect(record);await setStudio('image');};
window.productionBridge.savedPrecision=async function(job){await window.ensureStudio('image');await this.flush();assets=await api('/api/assets');await imageSelect(job.draft);imageShowJob(job);await imageHistory();await setStudio('image');};
window.productionBridge.refinedPrecision=async function(record){await window.ensureStudio('image');assets=await api('/api/assets');await imageSelect(record);await setStudio('image');};
function openPrecisionForImage(base=false){const output=imageSelectedOutput();const source=base?lookup(imageSettings.base):output||lookup(imageSettings.base);if(!source?.id){toast('Choose a local image or generated candidate for precision editing.');return;}window.dispatchEvent(new CustomEvent('precision-open',{detail:{asset:source,draft:imageDraft,settings:structuredClone(imageSettings)}}));}
$('imagePrecision').onclick=async()=>{try{await imageFlush();openPrecisionForImage();}catch(e){toast(e.message);}};
$('imagePrecisionBase').onclick=async()=>{try{await imageFlush();openPrecisionForImage(true);}catch(e){toast(e.message);}};
const productionImageShowJob=imageShowJob;
imageShowJob=function(job){productionImageShowJob(job);const output=imageSelectedOutput(job);$('imageAdoptAsset').hidden=true;if(!output?.approved)return;const id=job.id;sceneAPI('/asset-studio/development/lookup','POST',{draft_id:job.draft.id}).then(record=>{if(imageActiveJob?.id!==id||imageSelectedOutput()?.id!==output.id||!record)return;$('imageAdoptAsset').textContent='Add view to @'+record.handle;$('imageAdoptAsset').hidden=false;$('imageAdoptAsset').onclick=async()=>{try{const current=await sceneAPI('/asset-studio/'+record.id);await sceneAPI('/asset-studio/'+record.id+'/adopt','POST',{expected_revision:current.revision,asset_id:output.id});namedLibrary=await api('/api/references');window.dispatchEvent(new Event('assets-updated'));toast('Approved view saved as a new asset version.');}catch(e){toast(e.message);}};}).catch(()=>{});};

function productionInstallAssets(){if(storyReady&&!$('storyImportOpen').dataset.productionInstalled){$('storyImportOpen').dataset.productionInstalled='true';const importOpen=$('storyImportOpen').onclick;$('storyImportOpen').onclick=async()=>{await importOpen();try{const saved=JSON.parse(sessionStorage.getItem('imagine-import-'+storyEpisode?.id)||'null');if(saved){storyImport=saved.parsed;storyImportIndex=saved.index||0;$('storyImportText').value=saved.text||'';storyImportRender();}}catch{}};const chatOpen=$('storyChatOpen').onclick;$('storyChatOpen').onclick=async()=>{await chatOpen();$('storyChatMessage').value=sessionStorage.getItem('imagine-script-message-'+storyEpisode?.id)||$('storyChatMessage').value;};} $('namedOpen').textContent='Asset Studio';$('namedOpen').onclick=()=>window.studioNavigate?window.studioNavigate('assets'):window.dispatchEvent(new Event('asset-studio-open'));$('libraryOpen').onclick=()=>window.dispatchEvent(new CustomEvent('studio-library-open',{detail:{collection:'images'}}));$('scenesOpen').onclick=()=>window.dispatchEvent(new CustomEvent('studio-library-open',{detail:{collection:'videos'}}));$('imageDrafts').onclick=()=>window.dispatchEvent(new CustomEvent('studio-library-open',{detail:{collection:'images'}}));$('imageManageAssets').onclick=()=>{$('imageAssetDialog').close();window.dispatchEvent(new Event('asset-studio-open'));};}
window.addEventListener('studio-tool-ready',productionInstallAssets);window.addEventListener('studio-ready',productionInstallAssets,{once:true});

$('selectVideoTake').onclick=()=>window.productionBridge.selectDisplayedVideo();
$('imageSelectShot').onclick=()=>window.productionBridge.selectDisplayedImage();
