const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const settings={prompt:'Original',bindings:[],extras:[],base:null,edit_region:null,model:'image',ratio:'16:9',resolution:'auto',quality:'auto'};
const base={id:'image-one',revision:1,title:'Original name',settings};
const elements={imageTitle:{value:base.title},imageSync:{textContent:''},imagePrompt:{selectionStart:0,selectionEnd:0,setSelectionRange(){}},imageStatus:{textContent:''},imageApproved:{checked:false}};
const ctx={structuredClone,JSON,Promise,Set,setTimeout:()=>0,clearTimeout(){},$:id=>elements[id],window:{dispatchEvent(){},addEventListener(){}},CustomEvent:class{},document:{activeElement:null},toast(){},api:async()=>[]};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/image-studio.js','utf8'),ctx);
ctx.imageRender=()=>{};ctx.imageValidate=async()=>{};ctx.imageGate=()=>{};ctx.imageHistory=async()=>{};
const set=code=>vm.runInContext(code,ctx),get=code=>JSON.parse(JSON.stringify(vm.runInContext(code,ctx)));
function reset(){ctx.document.activeElement=null;elements.imageTitle.value=base.title;set('imageDraft='+JSON.stringify(base)+';imageSettings=structuredClone(imageDraft.settings);imageSaving=null;imageDirty=false;imageConflict=false;imageVersion=0;imageSchema={};imageJobs=[];imageActiveJob=null;');}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 reset();const latest={...base,revision:4,settings:{...settings,prompt:'Remote update'}};elements.imageTitle.value='My rename';set('imageDirty=true;imageVersion++');let writes=0;
 ctx.sceneAPI=async(path,method,data)=>{if(method==='PUT'){writes++;if(writes===1){const e=Error('Changed');e.code='revision_conflict';throw e;}assert.equal(data.expected_revision,4);return {...latest,...data,revision:5};}return latest;};
 await ctx.imageFlush();assert.equal(writes,2);assert.equal(get('imageDraft.title'),'My rename');assert.equal(get('imageSettings.prompt'),'Remote update');assert.equal(get('imageConflict'),false);

 reset();elements.imageTitle.value='Local name';set('imageDirty=true');writes=0;ctx.sceneAPI=async(path,method)=>{if(method==='PUT'){writes++;const e=Error('Changed');e.code='revision_conflict';throw e;}return {...base,revision:2,title:'Other name'};};
 await assert.rejects(ctx.imageFlush(),/Another tab or agent changed title/);assert.equal(writes,1);assert.equal(elements.imageTitle.value,'Local name');assert.equal(get('imageDirty'),true);assert.equal(get('imageConflict'),true);

 reset();let release;const remoteSave=new Promise(resolve=>release=resolve),requests=[];elements.imageTitle.value='First name';set('imageDirty=true;imageVersion++');
 ctx.sceneAPI=async(path,method,data)=>{requests.push(data);if(requests.length===1)return remoteSave;return {...base,...data,revision:data.expected_revision+1};};
 const first=ctx.imageFlush(),second=ctx.imageFlush();await tick();elements.imageTitle.value='Newest name';set('imageDirty=true;imageVersion++');const third=ctx.imageFlush();release({...base,...requests[0],revision:2});await Promise.all([first,second,third]);
 assert.deepEqual(requests.map(r=>r.expected_revision),[1,2]);assert.equal(get('imageDraft.title'),'Newest name');assert.equal(get('imageDirty'),false);

 reset();let releasePoll;const stalePoll=new Promise(resolve=>releasePoll=resolve);let loads=0;ctx.imageLoad=async()=>{loads++;};
 ctx.sceneAPI=async(path,method,data)=>path.endsWith('/workspace')?stalePoll:path.endsWith('/jobs')?[]:{...base,...data,revision:3};
 const polling=ctx.imagePoll();await tick();elements.imageTitle.value='Renamed while polling';set('imageDirty=true;imageVersion++');await ctx.imageFlush();releasePoll({...base,revision:2});await polling;
 assert.equal(loads,0);assert.equal(get('imageDraft.revision'),3);assert.equal(elements.imageTitle.value,'Renamed while polling');

 reset();let releaseEditing;const delayed=new Promise(resolve=>releaseEditing=resolve);ctx.sceneAPI=async path=>path.endsWith('/workspace')?delayed:[];const editingPoll=ctx.imagePoll();await tick();elements.imageTitle.value='Still typing';set('imageDirty=true;imageVersion++');releaseEditing({...base,revision:2});await editingPoll;assert.equal(loads,0);assert.equal(elements.imageTitle.value,'Still typing');assert.equal(get('imageDirty'),true);

 reset();elements.imageTitle.value='';set('imageDirty=true');ctx.sceneAPI=async()=>{const e=Error('Enter an image title');e.code='invalid_title';throw e;};await assert.rejects(ctx.imageFlush(),/Enter an image title/);assert.equal(get('imageConflict'),false);assert.equal(get('imageDirty'),true);
 elements.imageTitle.value='Valid name';ctx.sceneAPI=async(path,method,data)=>({...base,...data,revision:2});await ctx.imageFlush();assert.equal(get('imageDraft.title'),'Valid name');

 // The server trims stored names, but a pause must preserve the user's space and caret.
 reset();ctx.document.activeElement=elements.imageTitle;
 let raw='Teaser ',assignments=0;elements.imageTitle.selectionStart=7;
 Object.defineProperty(elements.imageTitle,'value',{configurable:true,get:()=>raw,set:value=>{raw=value;assignments++;elements.imageTitle.selectionStart=raw.length;}});
 ctx.sceneAPI=async(path,method,data)=>({...base,...data,title:data.title.trim(),revision:data.expected_revision+1});
 for(const name of ['Teaser ','Teaser 5A ','Teaser 5A Refinement']){
  raw=name;elements.imageTitle.selectionStart=name.length;set('imageDirty=true;imageVersion++');await ctx.imageFlush();
  assert.equal(raw,name);assert.equal(elements.imageTitle.selectionStart,name.length);assert.equal(assignments,0);
 }
 assert.equal(get('imageDraft.title'),'Teaser 5A Refinement');
 // Typing the next word while the prior save is in flight is not a competing rename.
 raw='Teaser ';set('imageDirty=true;imageVersion++');let finish;const trimmedSave=new Promise(resolve=>finish=resolve);let pendingWrites=0;
 ctx.sceneAPI=async(path,method,data)=>{pendingWrites++;if(pendingWrites===1)return trimmedSave;return {...base,...data,title:data.title.trim(),revision:data.expected_revision+1};};
 const pending=ctx.imageFlush();await tick();raw='Teaser 5A ';set('imageDirty=true;imageVersion++');finish({...base,revision:get('imageDraft.revision')+1,title:'Teaser',settings});await pending;
 assert.equal(raw,'Teaser 5A ');assert.equal(get('imageDraft.title'),'Teaser 5A');assert.equal(get('imageConflict'),false);assert.equal(assignments,0);
 // Background refresh waits until the user leaves the name field.
 loads=0;ctx.sceneAPI=async path=>path.endsWith('/workspace')?{...base,revision:100}:[];await ctx.imagePoll();assert.equal(loads,0);assert.equal(raw,'Teaser 5A ');
 const merge=ctx.mergeImageSave(base,{title:'Rename',settings:{...settings,bindings:[{id:'new'}]}},{...base,settings:{...settings,prompt:'New reference prompt'}});assert(merge.conflicts.length);assert.equal(base.title,'Original name');
 console.log('Image saves: safe rename merge, genuine conflicts, concurrent flush serialization, stale polling, typing preservation, validation recovery and coupled reference checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
