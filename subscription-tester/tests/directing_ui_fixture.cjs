const assert=require('node:assert/strict');
const {buildSync}=require('esbuild');
const {JSDOM}=require('jsdom');
const {base,productionId,episodeId,reviewId,shotId,layoutId,scenario,targetId}=JSON.parse(process.argv[2]);
const dom=new JSDOM('<div id="root"></div>',{url:base,pretendToBeVisual:true});
const win=dom.window;
for(const key of ['window','document','HTMLElement','Event','MouseEvent','sessionStorage','HTMLCanvasElement'])global[key]=win[key];
global.IS_REACT_ACT_ENVIRONMENT=true;
const nativeFetch=global.fetch;
const pending=new Set();
const opening=nativeFetch(base);
global.fetch=(url,options={})=>{
 const response=opening.then(session=>nativeFetch(new URL(url,base),{...options,headers:{...options.headers,
  Cookie:session.headers.get('set-cookie').split(';')[0],Origin:base}}));
 pending.add(response);void response.then(()=>pending.delete(response),()=>pending.delete(response));
 return response;
};
win.HTMLCanvasElement.prototype.getContext=()=>new Proxy({createLinearGradient:()=>({addColorStop(){}})},
 {get:(object,key)=>object[key]||(()=>{})});
let exported;
URL.createObjectURL=blob=>{exported=blob;return 'blob:'+base+'/fixture';};
URL.revokeObjectURL=()=>{};
win.HTMLAnchorElement.prototype.click=function(){assert.equal(this.download,'composition.png');};

function load(entry){
 const code=buildSync({entryPoints:[entry],bundle:true,write:false,format:'cjs',
  platform:'node',external:['react','react-dom'],logLevel:'silent'}).outputFiles[0].text;
 const mod={exports:{}};
 new Function('require','module','exports',code)(require,mod,mod.exports);
 return mod.exports;
}
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client');
const settle=async()=>{
 // A route may trigger more fetches after its response is decoded.
 for(let attempt=0;attempt<3;attempt++){
  await Promise.all([...pending]);await new Promise(resolve=>setTimeout(resolve,50));
 }
};
const button=name=>[...document.querySelectorAll('button')].find(b=>b.textContent===name);
const control=label=>[...document.querySelectorAll('label')].find(el=>el.textContent.startsWith(label))?.querySelector('select,input,textarea');
const change=(element,value)=>{
 Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element),'value').set.call(element,value);
 element.dispatchEvent(new win.Event(element.tagName==='SELECT'?'change':'input',{bubbles:true}));
};
const click=async name=>act(async()=>{assert(button(name),name);button(name).click();await settle();});
const enter=async(element,value)=>act(async()=>{assert(element);change(element,value);await settle();});

(async()=>{
 const root=createRoot(document.querySelector('#root'));
 if(scenario==='blocking'){
  const {CameraControl}=load('ui/filmmaking.tsx');
  await act(async()=>root.render(React.createElement(CameraControl,{shotId,close(){},prepare:async()=>{},transferred:async()=>{}})));
  await act(settle);
  await click('Shared Scene Blocking');
  await enter(control('Scene layout'),layoutId);
  assert.equal(control('Camera view').options.length,2);
  await enter(control('Camera view'),'rivals');
  assert.equal(control('View name').value,'Rivals’ angle');
  await enter(control('Prop name'),'Market stall');
  await enter(document.querySelector('[aria-label="Prop Horizontal"]'),'1.25');
  await click('Save scene layout');
  assert.match(document.querySelector('[role=status]').textContent,/layout saved/);
  await click('Use view for this shot');
  await click('Export portrait PNG');
  assert.equal(exported.type,'image/png');
  assert(exported.size>1000);
 }else if(['preview','hunter','chicken','sorceress'].includes(scenario)){
  const {GenerationPreview}=load('ui/directing-tools.tsx');
  await act(async()=>root.render(React.createElement(GenerationPreview,{shotId,close(){}})));
  await act(settle);
  if(scenario==='hunter'){
   assert.match(document.body.textContent,/Hunter · rex/);
  }else if(scenario==='sorceress'){
   assert.match(document.body.textContent,/Sorceress · eve/);
  }else{
   assert.equal(document.querySelectorAll('figure img').length,3);
   assert.match(document.body.textContent,/First frame/);
   assert.match(document.body.textContent,/Keyframe/);
   assert.match(document.body.textContent,/Last frame/);
   if(scenario==='preview')assert.match(document.body.textContent,/Sorceress · eve/);
   assert.match(document.body.textContent,/4s render/);
   assert.equal(control('Intended edit duration').value,'1.5');
   if(scenario==='preview'){
    await enter(control('Intended edit duration'),'1.25');
    await click('Save edit duration');
    assert.equal(control('Intended edit duration').value,'1.25');
   }
  }
 }else{
  const {ContinuityReview}=load('ui/directing-tools.tsx');
  await act(async()=>root.render(React.createElement(ContinuityReview,{productionId,episodeId,close(){},
   prepare:async()=>{},changed:async()=>{}})));
  await act(settle);
  await enter(control('Saved review'),reviewId);
  assert.equal(document.querySelectorAll('figure img').length,2);
  for(const img of document.querySelectorAll('figure img'))assert((await fetch(img.src)).ok);
  assert.match(control('What intentionally changes').value,/Only the hunter/);
  await click('Frame 1');
  assert.equal(document.querySelectorAll('figure img').length,1);
  await enter(control('Findings from inspecting'), 'Armor, pose, framing and lighting checked by the director fixture.');
  await click('Save review');
  assert.match(document.querySelector('[role=status]').textContent,/Review saved/);
  if(targetId){
   await enter(control('Destination shot'),targetId);
   await click('Attach as video reference');
   assert.match(document.querySelector('[role=status]').textContent,/attached/);
  }
 }
 await act(async()=>root.unmount());
 dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close();});
