/* Clipboard input and local video captures share the persisted image library. */
let frameJob=null, frameSource=null, framePasteQueue=Promise.resolve();
async function flushFrameScene(){
  while(sceneSaving)await new Promise(r=>setTimeout(r,50));
  if(sceneDirty)await saveScene();
  if(sceneConflict||sceneDirty)throw Error('Save your draft or resolve its conflict before adding this image.');
}
async function placeFrame(source,target,slot,replace=false){
  await flushFrameScene();
  const record=await sceneAPI('/assets/'+source.id+'/place','POST',{scene_id:sceneRecord.id,expected_revision:sceneRecord.revision,target,slot,replace});
  await selectScene(record);toast('Image added to '+target+'.');
}
async function openFrameReuse(source,newScene=true){
  frameSource=source;
  const records=await sceneAPI('/scenes');const select=$('frameScene');select.replaceChildren(new Option('＋ New video scene','new'));
  for(const record of records.filter(r=>!r.archived))select.append(new Option(record.title,record.id));
  select.value=newScene?'new':sceneRecord.id;
  $('frameThumb').src=source.src;$('frameOrigin').textContent=source.source_video_job_id?`Captured at ${source.frame_seconds.toFixed(3)} seconds. Saved in your image library.`:'Pasted image saved in your image library.';
  $('frameTarget').value='first';$('frameReplace').checked=false;$('frameError').textContent='';
  await updateFrameTarget();$('frameReuse').showModal();
}
async function updateFrameTarget(){
  try{
    const record=$('frameScene').value==='new'?null:await sceneAPI('/scenes/'+$('frameScene').value);
    const scene=record?.scene||blank();const limited=scene.model!=='grok-imagine-video-1.5';
    for(const option of $('frameTarget').options)option.disabled=limited&&option.value!=='first';
    if($('frameTarget').selectedOptions[0].disabled)$('frameTarget').value=[...$('frameTarget').options].find(o=>!o.disabled).value;
    $('frameTimeBox').hidden=$('frameTarget').value!=='keyframe';$('frameTime').max=scene.duration-1/3;
    $('frameNote').textContent=limited?'Lite accepts a first image; references, last frames and keyframes require Video 1.5.':`Keyframes must fall strictly inside ${scene.duration}s, on a ⅓-second grid. Adding advanced references lowers 1080p to 720p.`;
  }catch(e){$('frameError').textContent=e.message;}
}
async function pasteFrameFiles(files,target){
  try{
    if(!files.length)throw Error('No PNG, JPEG or WebP image found. Copy the image itself, then paste again.');
    const sources=await uploadFiles(files);
    if(target==='library')return toast('Pasted images saved. Choose a thumbnail to use it.');
    if(target==='refs'){
      for(const source of sources)await placeFrame(source,'reference');
    }else if(['first','last','timeline'].includes(target)){
      const slot=target==='timeline'?freeSlot():undefined;
      if(target==='timeline'&&slot===null)throw Error('No free keyframe slots.');
      await placeFrame(sources[0],target==='timeline'?'keyframe':target,slot,target!=='timeline');
      if(sources.length>1)toast('First image placed. Other pasted images remain in the library.');
    }else await openFrameReuse(sources[0],false);
  }catch(e){toast(e.message);}
}
async function captureDisplayedFrame(){
  const video=$('video');video.pause();$('captureFrame').disabled=true;
  try{
    if(video.seeking)await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{video.removeEventListener('seeked',done);reject(Error('Wait for the video to finish seeking, then capture again.'));},5000);function done(){clearTimeout(timer);resolve();}video.addEventListener('seeked',done,{once:true});});
    if(video.readyState<2||!video.videoWidth||!frameJob)throw Error('Wait for the video frame to load.');
    const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext('2d').drawImage(video,0,0);
    const source=await sceneAPI('/jobs/'+frameJob+'/capture-frame','POST',{timestamp_s:video.currentTime,data_url:canvas.toDataURL('image/png')});
    assets.push(source);await openFrameReuse(source,true);
  }catch(e){toast(e.message);}finally{$('captureFrame').disabled=video.readyState<2;}
}
function initFrameTools(){
  $('captureFrame').onclick=captureDisplayedFrame;
  $('video').addEventListener('loadeddata',()=>{$('captureFrame').disabled=false;});
  $('video').addEventListener('error',()=>{ $('captureFrame').disabled=true;toast('The saved video could not load. Try Play again from history.');});
  $('pasteImage').onclick=async()=>{
    try{const items=await navigator.clipboard.read();const files=[];for(const item of items){const type=item.types.find(t=>['image/png','image/jpeg','image/webp'].includes(t));if(type)files.push(new File([await item.getType(type)],'Pasted image',{type}));}await pasteFrameFiles(files,'library');}
    catch{toast('Clipboard access unavailable. Focus an image slot or this picker and press ⌘V / Ctrl+V.');}
  };
  document.addEventListener('paste',event=>{
    if(event.defaultPrevented)return;
    if(event.target.closest('input,textarea,[contenteditable="true"]'))return;
    if(document.querySelector('[role="dialog"][aria-modal="true"]'))return;
    if($('frameReuse').open)return;
    if([...document.querySelectorAll('dialog[open]')].some(d=>d.id!=='library'))return;
    if(($('videoStudio').hidden||$('videoStudio').closest('[hidden]'))&&!$('library').open)return;
    const files=[...event.clipboardData.items].filter(i=>i.kind==='file'&&['image/png','image/jpeg','image/webp'].includes(i.type)).map(i=>i.getAsFile()).filter(Boolean);
    if(!files.length)return;event.preventDefault();
    const node=event.target.closest('#firstSlot,#lastSlot,#refDrop,#timeline');
    const target=$('library').open?'library':({firstSlot:'first',lastSlot:'last',refDrop:'refs',timeline:'timeline'}[node?.id]);
    framePasteQueue=framePasteQueue.then(()=>pasteFrameFiles(files,target));
  });
  $('closeFrameReuse').onclick=()=>$('frameReuse').close();
  $('frameScene').onchange=updateFrameTarget;$('frameTarget').onchange=updateFrameTarget;
  $('placeCapturedFrame').onclick=async()=>{
    $('placeCapturedFrame').disabled=true;$('frameError').textContent='';
    try{
      await flushFrameScene();const newScene=$('frameScene').value==='new';const record=newScene?null:await sceneAPI('/scenes/'+$('frameScene').value);
      const target=$('frameTarget').value;let slot;
      if(target==='keyframe'){const raw=Number($('frameTime').value)*3;slot=Math.round(raw);if(!Number.isFinite(raw)||Math.abs(raw-slot)>.00001)throw Error('Choose a time on the ⅓-second grid, such as 1 or 1.333333 seconds.');}
      const result=await sceneAPI('/assets/'+frameSource.id+'/place','POST',{new_scene:newScene,scene_id:record?.id,expected_revision:record?.revision,target,slot,replace:$('frameReplace').checked});
      await selectScene(result);$('frameReuse').close();$('videoTab').click();toast('Image added. Review the new scene before generating.');
    }catch(e){$('frameError').textContent=e.message;}finally{$('placeCapturedFrame').disabled=false;}
  };
}
