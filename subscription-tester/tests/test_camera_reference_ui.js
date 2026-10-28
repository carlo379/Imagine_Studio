// Mounted Camera Control exports/transfers the shared PNG helper. No network/server.
const assert=require('node:assert/strict'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const compiled=buildSync({entryPoints:['ui/filmmaking.tsx'],bundle:true,write:false,format:'cjs',platform:'node',external:['react','react-dom'],logLevel:'silent'}).outputFiles[0].text;
const dom=new JSDOM('<div id="root"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const k of ['window','document','HTMLElement','HTMLCanvasElement','HTMLSelectElement','Event','MouseEvent','sessionStorage'])global[k]=win[k];
global.IS_REACT_ACT_ENVIRONMENT=true;
const exportsSeen=[],downloads=[],calls=[];
win.HTMLCanvasElement.prototype.getContext=function(kind,options){
 if(options)this.cpu=options.willReadFrequently;
 if(this.ctx)return this.ctx;const canvas=this;
 this.ctx=new Proxy({createLinearGradient:()=>({addColorStop(){}}),fillText(){canvas.labels=(canvas.labels||0)+1;}},{get:(o,k)=>k in o?o[k]:()=>{}});return this.ctx;
};
win.HTMLCanvasElement.prototype.toDataURL=function(mime){exportsSeen.push({width:this.width,height:this.height,mime,cpu:this.cpu,labels:this.labels||0});return 'data:image/png;base64,local-canvas-fixture';};
win.HTMLAnchorElement.prototype.click=function(){downloads.push({href:this.href,download:this.download});};
const mod={exports:{}};new Function('require','module','exports',compiled)(require,mod,mod.exports);
const {CameraControl}=mod.exports,React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),catalog=require('../static/camera-presets.json');
let direction={id:'direction-shot',shot_id:'shot',revision:3,staging:structuredClone(catalog.defaults)},prepared=0,transferred=0,closed=0;
global.fetch=async(url,options={})=>{
 const route=url.replace('/api/agent/',''),method=options.method||'GET',data=options.body?JSON.parse(options.body):null;
 calls.push({route,method,data});let result;
 if(route==='filmmaking/shots/shot'&&method==='GET')result=direction;
 else if(route==='asset-studio')result=[];
 else if(route==='filmmaking/shots/shot'&&method==='PUT'){
  assert.equal(data.expected_revision,direction.revision);direction={...direction,revision:direction.revision+1,staging:data.staging};result=direction;
 }else if(route==='productions/shots/shot')result={id:'shot',image:{id:'image',revision:7}};
 else if(route==='filmmaking/shots/shot/compose'){
  assert.equal(data.expected_revision,direction.revision);assert.equal(data.expected_image_revision,7);
  assert.equal(data.data_url,'data:image/png;base64,local-canvas-fixture');assert(data.prompt.includes('cinematic image'));result={draft:{id:'image'}};
 }else throw Error('Unexpected route '+route);
 return {ok:true,json:async()=>structuredClone(result)};
};
win.MediaPrompting={prepare:async(kind,id)=>{assert.equal(kind,'image');assert.equal(id,'image');return {id};}};
const wait=()=>new Promise(r=>setTimeout(r,25));
const click=async(button)=>act(async()=>{assert(button);button.click();await wait();});
(async()=>{
 const root=createRoot(document.getElementById('root'));
 await act(async()=>{root.render(React.createElement(CameraControl,{shotId:'shot',close:()=>closed++,prepare:async()=>prepared++,transferred:async()=>transferred++}));await wait();});
 assert.equal(document.querySelectorAll('.ft-presets button').length,catalog.camera.length);
 for(const [identity,ratio] of [['wide','16:9'],['close-up','9:16'],['birds-eye','1:1']]){
  const preset=catalog.camera.find(p=>p.id===identity);await click([...document.querySelectorAll('.ft-presets button')].find(b=>b.textContent===preset.name));
  const frame=document.querySelector('.ft-map-row select');await act(async()=>{frame.value=ratio;frame.dispatchEvent(new win.Event('change',{bubbles:true}));await wait();});
  await click([...document.querySelectorAll('button')].find(b=>b.textContent.includes('Reference PNG')));
  assert.deepEqual(exportsSeen.at(-1),{...catalog.frame_sizes[ratio],mime:'image/png',cpu:true,labels:0});
  assert.equal(downloads.at(-1).download,'composition.png');assert.equal(calls.filter(c=>c.method!=='GET').length,0);
 }
 await click([...document.querySelectorAll('button')].find(b=>b.textContent.includes('Prepare composition with AI')));
 const save=calls.find(c=>c.method==='PUT'),transfer=calls.find(c=>c.route.endsWith('/compose'));
 assert(save&&transfer);assert.deepEqual(save.data.staging.camera,{...catalog.defaults.camera,...catalog.camera.at(-1).patch});assert.equal(save.data.staging.ratio,'1:1');
 assert.deepEqual(exportsSeen.at(-1),{...catalog.frame_sizes['1:1'],mime:'image/png',cpu:true,labels:0});
 assert.equal(prepared,1);assert.equal(transferred,1);assert.equal(closed,1);
 assert(!calls.some(c=>c.route.includes('generate')||c.route==='filmmaking/shots/shot/reference.png'));
 await act(async()=>root.unmount());dom.window.close();
 console.log('Camera Control shared presets/export dimensions, label-free CPU PNG, revision-checked transfer and no implicit generation pass.');
})().catch(error=>{console.error(error);process.exitCode=1;dom.window.close();});
