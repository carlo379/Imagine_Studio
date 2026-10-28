const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),vm=require('node:vm'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const compiled=path.resolve('.validation/series-books/browser-handoff-ui.cjs');
buildSync({entryPoints:['ui/browser-handoff.tsx'],bundle:true,platform:'node',external:['react','react-dom'],outfile:compiled,logLevel:'silent'});
const dom=new JSDOM('<div id="root"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const key of ['window','document','navigator','HTMLElement','Event','sessionStorage'])Object.defineProperty(global,key,{value:win[key],writable:true,configurable:true});
global.IS_REACT_ACT_ENVIRONMENT=true;win.studioWorkspaceId='workspace-fixture';
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client');
const {browserTab,createReturnFlow,completeReturnFlow,DraftHandoff}=require(compiled);
let calls=[],consent=false,flow=null,snapshot=null,expireConsent=false;
const timers=new Map(),nativeInterval=global.setInterval,nativeClear=global.clearInterval;let timerId=0;
global.setInterval=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;};global.clearInterval=id=>timers.delete(id);
const wait=()=>new Promise(resolve=>setTimeout(resolve,30));
global.fetch=async(url,options={})=>{
 const data=options.body?JSON.parse(options.body):null;calls.push({url,method:options.method||'GET',data,headers:options.headers});
 const reply=(value,ok=true)=>({ok,json:async()=>structuredClone(value)});
 if(url==='/api/browser-handoff')return reply({sharing_enabled:consent,flows:flow?[flow]:[]});
 if(url==='/api/browser-handoff/flows'){flow={id:'opaque-flow',revision:1,status:'open',value:data};return reply(flow);}
 if(url==='/api/browser-handoff/drafts/consent'){consent=data.enabled;if(!consent)snapshot=null;return reply({sharing_enabled:consent});}
 if(url==='/api/browser-handoff/drafts'){
  if(expireConsent){consent=false;return reply({error:{code:'consent_required',message:'Sharing expired.'}},false);}
  assert(consent);snapshot={id:'opaque-snapshot',revision:(snapshot?.revision||0)+1,read_only:true,drafts:data};return reply(snapshot);
 }
 if(url==='/api/agent/handoff/flows/opaque-flow')return reply(flow);
 if(url==='/api/browser-handoff/flows/opaque-flow/returned'){
  assert.equal(data.expected_revision,flow.revision);flow={...flow,revision:flow.revision+1,status:'returned'};return reply(flow);
 }
 if(url==='/api/agent/handoff/flows/opaque-flow/finish'){
  assert.equal(flow.status,'returned');assert.equal(data.expected_revision,flow.revision);flow={...flow,revision:flow.revision+1,status:'finished'};return reply(flow);
 }
 throw Error('Unexpected endpoint '+url);
};
let root;
(async()=>{
 const tab=browserTab();assert.equal(browserTab(),tab);assert.equal(sessionStorage.getItem('imagine-handoff-tab'),tab);
 const value={route:{page:'project',workspace:{production_id:'p',stage:'develop'}},title:'Back to Bible',draft_id:'image',context:{scope:'series/p',entity_id:'prop',view_id:'view',expected_revision:9,page:3,visual:{activeStep:3,expanded:[false,true,false,true],heroChoice:'candidate',scrollTop:380}}};
 await createReturnFlow(value);assert.deepEqual(flow.value,value);
 const sent=calls.at(-1);assert.equal(sent.headers['X-Workspace-ID'],'workspace-fixture');assert.equal(sent.headers['X-Browser-Tab'],tab);
 flow={...flow,status:'return_requested',revision:2};await completeReturnFlow({id:flow.id,revision:1});
 assert.equal(flow.status,'finished');assert.equal(flow.revision,4);
 assert.deepEqual(calls.slice(-3).map(c=>c.url),['/api/agent/handoff/flows/opaque-flow','/api/browser-handoff/flows/opaque-flow/returned','/api/agent/handoff/flows/opaque-flow/finish']);
 await completeReturnFlow({id:flow.id});assert.equal(calls.at(-1).method,'GET','Completion is idempotent after finish');
 // Execute the actual legacy bridge collector, without starting either editor.
 const bridgeSource=fs.readFileSync('static/production-bridge.js','utf8');
 const captureSource=bridgeSource.match(/draftSnapshot\(\)\{return structuredClone\(.+?;\}/)[0].replace('draftSnapshot()','function capture()');
 const context={structuredClone,imageDraft:{id:'image',revision:2},imageDirty:true,imageSettings:{prompt:'Unsaved image'},sceneRecord:{id:'video',revision:3},sceneDirty:true,project:{prompt:'Unsaved video'},$:id=>({value:id})};
 vm.createContext(context);vm.runInContext(captureSource,context);const captured=JSON.parse(JSON.stringify(context.capture()));
 assert.equal(captured.image.data.settings.prompt,'Unsaved image');assert.equal(captured.video.data.scene.prompt,'Unsaved video');
 captured.image.data.settings.prompt='Copy only';assert.equal(context.imageSettings.prompt,'Unsaved image','Snapshot cannot mutate the editor');
 context.imageDirty=false;context.sceneDirty=false;assert.equal(context.capture().image,null);assert.equal(context.capture().video,null);
 let data=Object.fromEntries(['book','image','video','timeline'].map(kind=>[kind,{id:kind,revision:2,dirty:true,data:{title:'Pending '+kind}}]));
 const collect=()=>structuredClone(data);root=createRoot(document.getElementById('root'));
 await act(async()=>{root.render(React.createElement(DraftHandoff,{collect}));await wait();});
 assert.equal(snapshot,null,'Drafts stay private before explicit consent');assert.equal(timers.size,0);
 const toggle=()=>document.querySelector('button');assert.equal(toggle().textContent,'Share pending drafts');
 await act(async()=>{toggle().click();await wait();});await act(async()=>wait());
 assert(consent);assert.deepEqual(snapshot.drafts,data);assert(snapshot.read_only);assert.equal(timers.size,1);
 const timer=[...timers.values()][0];assert.equal(timer.ms,5000);
 data={...data,image:{...data.image,data:{title:'New unsaved text'}}};
 await act(async()=>{root.render(React.createElement(DraftHandoff,{collect:()=>structuredClone(data)}));await wait();});
 assert.equal([...timers.values()][0],timer,'Renders update the collector without restarting publication');
 await act(async()=>{await timer.fn();await wait();});assert.equal(snapshot.drafts.image.data.title,'New unsaved text');
 await act(async()=>{toggle().click();await wait();});assert(!consent);assert.equal(snapshot,null);assert.equal(timers.size,0);
 await act(async()=>{toggle().click();await wait();});expireConsent=true;
 await act(async()=>{await [...timers.values()][0].fn();await wait();});assert.equal(toggle().getAttribute('aria-pressed'),'false');assert.equal(timers.size,0);assert(document.querySelector('[role="alert"]').textContent.includes('expired'));
 assert(calls.every(c=>c.url.startsWith('/api/browser-handoff')||c.url.startsWith('/api/agent/handoff')),'No saved book/image/video/timeline, provider, approval or generation route was called');
 await act(async()=>root.unmount());root=null;dom.window.close();global.setInterval=nativeInterval;global.clearInterval=nativeClear;
 console.log('Browser handoff: scoped flow acknowledgement, human opt-in, all four read-only drafts, revocation, consent expiry and no saved-data writes.');
})().catch(async error=>{console.error(error);if(root)await act(async()=>root.unmount());global.setInterval=nativeInterval;global.clearInterval=nativeClear;dom.window.close();process.exitCode=1;});
