const assert=require('node:assert/strict');
const {mergeSceneSave}=require('../static/scene-save.js');
const vm=require('node:vm'),fs=require('node:fs');
const scene={prompt:'Original',first:null,refs:[],voices:[],audio:true,model:'1.5',named:[],duration:5,keys:[],last:null,resolution:'480p',ratio:'16:9'};
const base={id:'one',revision:1,title:'Title',scene};
let local={title:'Renamed',scene:structuredClone(scene)},remote={...base,revision:2,scene:{...scene,last:{id:'capture'}}};
let merge=mergeSceneSave(base,local,remote);assert.deepEqual(merge.conflicts,[]);assert.equal(merge.result.title,'Renamed');assert.equal(merge.result.scene.last.id,'capture');
remote={...base,scene:{...scene,prompt:'Remote'}};local.scene.prompt='Local';assert(mergeSceneSave(base,local,remote).conflicts.includes('prompt'));
local.scene=structuredClone(scene);local.scene.first={id:'new'};assert(mergeSceneSave(base,local,remote).conflicts.length);
const elements={sceneTitle:{value:'Title'},sceneSyncStatus:{textContent:''},approved:{checked:false}};
let resolveWorkspace;let calls=[];const storage=new Map();
const ctx={document:{activeElement:null},structuredClone,JSON,setTimeout,clearTimeout,Promise,mergeSceneSave,project:structuredClone(scene),assets:[],namedLibrary:[],urls:[],localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},$:id=>elements[id],toast:()=>{},render:()=>{},fetch:async()=>{},api:async()=>[]};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/scenes.js','utf8'),ctx);
vm.runInContext('sceneRecord='+JSON.stringify(base)+';sceneReady=true;',ctx);
ctx.sceneAPI=async(path,method,data)=>{calls.push({path,method,data});if(path==='/urls')return [];if(path==='/workspace')return new Promise(r=>resolveWorkspace=r);return {...base,revision:2,title:data.title,scene:data.scene};};
(async()=>{
 const syncing=ctx.syncScene();await new Promise(r=>setImmediate(r));ctx.project.prompt='Edited during refresh';vm.runInContext('sceneDirty=true',ctx);resolveWorkspace({...base,revision:2,scene:{...scene,prompt:'Stale remote'}});await syncing;assert.equal(ctx.project.prompt,'Edited during refresh');
 elements.sceneTitle.value='';await ctx.saveScene();assert.equal(vm.runInContext('sceneConflict',ctx),false);assert(storage.has('imagine-scene-recovery'));assert.match(elements.sceneSyncStatus.textContent,/Enter a scene title/);
 elements.sceneTitle.value='Title';await ctx.saveScene();assert.equal(vm.runInContext('sceneDirty',ctx),false);assert.equal(calls.at(-1).data.scene.prompt,'Edited during refresh');
 // A stale revision is merged without dropping local title or remote frame.
 vm.runInContext('sceneRecord='+JSON.stringify(base)+';sceneDirty=true;',ctx);ctx.project=structuredClone(scene);elements.sceneTitle.value='Local rename';let puts=0;
 ctx.sceneAPI=async(path,method,data)=>{if(method==='PUT'&&++puts===1){let e=Error('Scene changed');e.code='revision_conflict';throw e;}if(!method||method==='GET')return {...base,revision:4,scene:{...scene,last:{id:'frame'}}};return {...base,...data,revision:5};};
 await ctx.saveScene();assert.equal(puts,2);assert.equal(ctx.project.last?.id,'frame',elements.sceneSyncStatus.textContent);assert.equal(elements.sceneTitle.value,'Local rename');
 // A rebase preserves the focused input even when the API normalizes its title.
 vm.runInContext('sceneRecord='+JSON.stringify(base)+';sceneDirty=true;',ctx);ctx.project=structuredClone(scene);elements.sceneTitle.value='Teaser ';ctx.document.activeElement=elements.sceneTitle;puts=0;
 ctx.sceneAPI=async(path,method,data)=>{if(method==='PUT'&&++puts===1){const e=Error('Changed');e.code='revision_conflict';throw e;}if(!method||method==='GET')return {...base,revision:4,scene:{...scene,last:{id:'frame'}}};return {...base,...data,title:data.title.trim(),revision:5};};
 await ctx.saveScene();assert.equal(elements.sceneTitle.value,'Teaser ');assert.equal(vm.runInContext('sceneRecord.title',ctx),'Teaser');assert.equal(vm.runInContext('sceneConflict',ctx),false);
 assert.deepEqual(mergeSceneSave({...base,title:'Teaser '},{title:'Teaser 5A ',scene},{...base,title:'Teaser'}).conflicts,[]);
 console.log('Scene save: draft preservation, delayed refresh, blank title, and safe rebase checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
