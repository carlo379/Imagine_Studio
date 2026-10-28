const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
// Render the real shell without its automatic root, alongside the real poller
// and bridge selection hooks. Endpoints and media painting are local fixtures.
const source=fs.readFileSync('ui/production.tsx','utf8').replace("createRoot(document.getElementById('productionRoot')!).render(<Studio/>);","export {Studio};");
const compiled=path.resolve('.validation/series-books/inspiration-navigation-ui.cjs');
buildSync({stdin:{contents:source,resolveDir:path.resolve('ui'),sourcefile:'production.tsx',loader:'tsx'},bundle:true,platform:'node',external:['react','react-dom'],outfile:compiled,logLevel:'silent'});
const dom=new JSDOM('<div id="productionRoot"></div><main id="videoStudio"></main><main id="imageStudio"><input id="imageTitle"></main><main id="storyStudio"></main><div id="storyContextBar"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const k of ['window','document','navigator','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','MouseEvent','CustomEvent','sessionStorage','localStorage','location','MutationObserver','File','FileReader'])Object.defineProperty(global,k,{value:win[k],configurable:true,writable:true});
global.IS_REACT_ACT_ENVIRONMENT=true;global.requestAnimationFrame=win.requestAnimationFrame.bind(win);global.cancelAnimationFrame=win.cancelAnimationFrame.bind(win);global.ResizeObserver=class{observe(){}disconnect(){}};
win.matchMedia=()=>({matches:true});win.scrollTo=()=>{};Object.defineProperty(win.HTMLElement.prototype,'clientWidth',{get:()=>1080});
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{Studio}=require(compiled);
const bridge=fs.readFileSync('static/production-bridge.js','utf8'),selectionStart=bridge.indexOf('function productionSelectionOrigin('),selectionEnd=bridge.indexOf('const productionSetStudio=',selectionStart);
assert(selectionStart>=0&&selectionEnd>selectionStart);
const frameTools=fs.readFileSync('static/frame-tools.js','utf8'),frameStart=frameTools.indexOf("document.addEventListener('paste',event=>{"),frameEnd=frameTools.indexOf("$('closeFrameReuse').onclick",frameStart);
const wait=()=>new Promise(resolve=>setTimeout(resolve,60));
async function settle(){await act(async()=>wait());await act(async()=>wait());}
async function paste(target,type='image/png'){
 const event=new win.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(event,'clipboardData',{value:{items:[{kind:'file',type,getAsFile:()=>new win.File(['clipboard fixture'],'copy.png',{type})}],getData:()=>''}});
 await act(async()=>{target.dispatchEvent(event);await wait();});await settle();return event;
}
let root;
(async()=>{
 for(const scope of ['series/p','episodes/ep'])for(const category of ['Character','Location','Prop']){
  const legacyNodes=['videoStudio','imageStudio','storyStudio','storyContextBar'].map(id=>document.getElementById(id));
  sessionStorage.clear();localStorage.clear();
  const page=category==='Character'?1:scope.startsWith('episodes/')?2:category==='Location'?2:3;
  sessionStorage.setItem('imagine-series-tab-p',scope.startsWith('series/')?'bible':'episodes');sessionStorage.setItem('episode-book-open-p','1');
  sessionStorage.setItem('imagine-development-return-'+scope,JSON.stringify({entity_id:'entity',page,visual:{activeStep:3,expanded:[false,false,false,true],heroChoice:'',scrollTop:220}}));
  win.history.replaceState({},'','/#/project?production_id=p&episode_id=ep&stage=develop&board_view=board');
  let workspace={production_id:'p',episode_id:'ep',shot_id:null,story_scene_id:null,stage:'develop',board_view:'board'},calls=[],framePastes=0,result=null,flows=[];
  const production={id:'p',title:'Example Series',kind:'story',revision:1,brief:'',item_type:'story',last_updated:1791400000};
  const episode={id:'ep',title:'First adventure',revision:1,scenes:[]};
  const guide={cast:[{id:'hero',name:'Hero',description:'A robot.'}],places:[{id:'lab',name:'Lab',description:'A workshop.'}],props:[{id:'charger',name:'Charging Station',description:'An upright charging dock.'}],acts:[],script:''};
  const bible={id:'bible-p',production_id:'p',revision:1,answers:{style:'3D'},guide},book={id:'book-ep',production_id:'p',episode_id:'ep',revision:1,answers:{title:episode.title,style:'3D'},guide,episode};
  let entity={id:'entity',name:category==='Prop'?'Charging Station':category==='Location'?'Lab':'Hero',category,production_id:'p',revision:1,description:'Saved description',profile:{reference_ids:['first','second']},identity_asset_id:null,suggested_views:[]};
  let draft={id:'draft',revision:1,title:entity.name,settings:{prompt:'Saved direction',model:'gpt-image-2',base:null,edit_region:null,bindings:[],extras:[{asset_id:'first'},{asset_id:'second'}]}};
  const view={id:'main',entity_id:'entity',kind:category==='Character'?'portrait':category==='Location'?'location':'prop',view:'Main reference',revision:1,selected:null,outputs:[],draft};
  const snapshot=()=>({job:{id:'world',result:{visual_style:'3D'}},entities:[entity],views:[{...view,draft}],batches:[]});
  const response=data=>({ok:true,json:async()=>structuredClone(data)});
  global.fetch=async(url,options={})=>{
   const endpoint=url.replace('/api/agent/',''),data=options.body?JSON.parse(options.body):null;calls.push({endpoint,method:options.method||'GET',data});
   if(url==='/api/browser-handoff')return response({flows:flows.filter(f=>f.status!=='finished'),sharing_enabled:false});
   if(url==='/api/browser-handoff/flows'){const flow={id:'flow-'+category,revision:1,status:'open',value:data};flows=[flow];return response(flow);}
   if(endpoint.startsWith('handoff/flows/')){
    const flow=flows[0];assert(flow);if(endpoint.endsWith('/finish')){assert.equal(data.expected_revision,flow.revision);assert.equal(flow.status,'returned');flow.status='finished';flow.revision++;}return response(flow);
   }
   if(url.startsWith('/api/browser-handoff/flows/')&&url.endsWith('/returned')){const flow=flows[0];assert.equal(data.expected_revision,flow.revision);flow.status='returned';flow.revision++;return response(flow);}
   if(endpoint==='productions/workspace'){if(data)workspace={...workspace,...data};return response(workspace);}
   if(endpoint==='productions/p'||endpoint==='productions/p/summary')return response({production,episodes:[episode],shots:[]});
   if(endpoint==='productions/recent')return response({items:[production],total:1,production_total:1,has_more:false});
   if(endpoint==='filmmaking/series/p/bible')return response(bible);
   if(endpoint==='filmmaking/episodes/ep/book')return response(book);
   if(endpoint.endsWith('/library'))return response([entity]);
   if(endpoint.endsWith('/jobs'))return response([]);
   if(endpoint==='filmmaking/entities/entity/workshop')return response(snapshot());
   if(endpoint==='filmmaking/worlds/p/reference'){assert.equal(data.name,'copy.png');assert(data.data_url.startsWith('data:image/png;base64,'));return response({asset:{id:'clipboard',name:data.name},palette:[]});}
   if(endpoint==='filmmaking/entities/entity'&&options.method==='PUT'){
    assert.equal(data.expected_revision,entity.revision);entity={...entity,profile:data.profile,description:data.description,revision:entity.revision+1};
    draft={...draft,revision:draft.revision+1,settings:{...draft.settings,extras:entity.profile.reference_ids.map(asset_id=>({asset_id}))}};return response(entity);
   }
   if(endpoint==='filmmaking/assets/main/return-image'){
    assert.deepEqual(data,{expected_revision:1,job_id:'edited-job',asset_id:'edited'});entity={...entity,identity_asset_id:'edited',revision:entity.revision+1};view.selected='edited';view.outputs=[{id:'edited',job_id:'edited-job',draft_id:'edited-draft',approved:true}];return response(snapshot());
   }
   if(url==='/api/config')return response({voices:[]});
   if(endpoint==='account')return response({signed_in:true});
   if(endpoint==='image-studio/openai-account'||endpoint==='openai/account')return response({subscription:{signed_in:true}});
   throw Error('Unexpected endpoint '+url);
  };
  const elements={imageTitle:document.getElementById('imageTitle'),imageSync:{textContent:''},imageApproved:{checked:false},imageStatus:{textContent:''},library:{open:false},frameReuse:{open:false}};
  elements.imageTitle.value=draft.title;
  const ctx={window:win,document,CustomEvent:win.CustomEvent,structuredClone,JSON,Promise,Set,setTimeout:()=>0,clearTimeout(){},$:id=>document.getElementById(id)||elements[id],toast(){},api:async()=>[]};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/image-studio.js','utf8'),ctx);
  ctx.imageGate=()=>{};ctx.imageHistory=async()=>{};
  vm.runInContext('imageDraft='+JSON.stringify(draft)+';imageSettings=structuredClone(imageDraft.settings);imageSchema={};imageJobs=[];imageActiveJob=null;',ctx);
  ctx.imageLoad=async record=>{ctx.record=record;vm.runInContext('imageDraft=record;imageSettings=structuredClone(record.settings);imageVersion++;',ctx);elements.imageTitle.value=record.title;};
  ctx.sceneAPI=async(endpoint,method,data)=>endpoint==='/image-studio/workspace'?draft:[];
  ctx.selectScene=async()=>{};ctx.createScene=async()=>{};ctx.sceneRecord=null;
  win.productionBridge={
   ready:()=>true,dirty:()=>false,saveDialogs:async()=>{},flush:async()=>{},show:async()=>{},selected:()=>({image:'draft'}),loading:false,
   guided:()=>document.body.dataset.productionGuided==='true',
   openTool:tool=>{for(const name of ['image','video','story'])document.getElementById(name+'Studio').hidden=name!==tool;},
   openMedia:async(kind,id)=>{win.productionBridge.loading=true;try{await ctx.imageSelect({...draft,id});}finally{win.productionBridge.loading=false;}},imageResult:()=>result,showImageJob:async()=>{}
  };
  vm.runInContext(bridge.slice(selectionStart,selectionEnd),ctx);
  vm.runInContext(fs.readFileSync('static/frame-tools.js','utf8'),ctx);ctx.pasteFrameFiles=async()=>{framePastes++;};
  const frameListener=frameTools.slice(frameStart,frameEnd).trim().replace("document.addEventListener('paste',event=>{","framePasteListener=event=>{").replace(/\}\);$/,'};');
  vm.runInContext(frameListener,ctx);document.addEventListener('paste',ctx.framePasteListener);
  root=createRoot(document.getElementById('productionRoot'));await act(async()=>{root.render(React.createElement(Studio));await wait();});await settle();
  const firstChoice=[...document.querySelectorAll('dialog[aria-label="Choose your image model"] button')].find(button=>button.textContent==='ChatGPT · Image 2');if(firstChoice){await act(async()=>firstChoice.click());await settle();}
  const modal=()=>document.querySelector('.sw-asset-modal');assert(modal(),category+' '+scope+' development restored');
  const close=modal().querySelector('header button');close.focus();
  const route=location.hash;
  const accepted=await paste(document.activeElement);assert(accepted.defaultPrevented);assert.deepEqual(entity.profile.reference_ids,['first','second','clipboard']);assert.equal(draft.revision,2);
  assert.equal(framePastes,0,'Video clipboard handler must not claim development images');assert(modal());assert.equal(location.hash,route);assert(!modal().querySelector('[data-development-step="1"] .wb-section-body').hidden,'Pasting reveals inspiration');
  const textarea=modal().querySelector('textarea');textarea.focus();const untouched=await paste(textarea);assert(!untouched.defaultPrevented);assert.equal(entity.profile.reference_ids.length,3,'Text editing retains its own clipboard behavior');
  await act(async()=>{await ctx.imagePoll();await wait();});await settle();
  assert.equal(vm.runInContext('imageDraft.revision',ctx),2,'Background Image Studio still receives refreshed settings');assert(modal());assert.equal(location.hash,route);assert(!calls.some(c=>c.endpoint==='productions/locate'),'A passive poll must not locate or navigate media');
  // The shell also rejects old or accidentally flagged events while the studio is hidden.
  for(const selection of [undefined,true])await act(async()=>{win.dispatchEvent(new win.CustomEvent('production-media-selected',{detail:{kind:'image',id:'draft',selection}}));await wait();});
  assert(modal());assert.equal(location.hash,route);assert(!calls.some(c=>c.endpoint==='productions/locate'));
  await act(async()=>{modal().querySelectorAll('.wb-development-steps button')[4].click();await wait();});await settle();
  const body=modal().querySelector('.sw-modal-body');body.scrollTop=380;const expanded=[0,1,4].map(i=>modal().querySelectorAll('.wb-development-steps button')[i].getAttribute('aria-expanded')==='true');
  const open=[...modal().querySelectorAll('button')].find(button=>button.textContent==='Open in Image Studio →');await act(async()=>{open.click();await wait();});await settle();
  assert(location.hash.startsWith('#/tool/image'),'Deliberate Image Studio opening still works');const saved=JSON.parse(sessionStorage.getItem('imagine-image-return'));assert.equal(saved.context.scope,scope);assert.equal(saved.context.page,page);assert.equal(saved.context.visual.scrollTop,380);assert.equal(saved.context.visual.expanded.length,5);assert.deepEqual([0,1,4].map(i=>saved.context.visual.expanded[i]),expanded);assert.equal(saved.flow_id,'flow-'+category);assert.equal(flows[0].value.draft_id,'draft');assert.deepEqual(flows[0].value.context.visual,saved.context.visual);
  result={job_id:'edited-job',asset_id:'edited'};
  const back=[...document.querySelectorAll('button')].find(button=>button.textContent.startsWith('← Return to '+entity.name));assert(back);
  if(scope==='series/p'&&category==='Prop'){
   // Simulate an agent request and loss of the old browser-local context.
   flows[0].status='return_requested';flows[0].revision++;sessionStorage.removeItem('imagine-image-return');
   await act(async()=>new Promise(resolve=>setTimeout(resolve,2100)));
  }else await act(async()=>{back.click();await wait();});await settle();
  assert(location.hash.startsWith('#/project?production_id=p'),'Return reopens the original project, not Projects');assert(modal());assert.equal(modal().querySelector('.sw-modal-body').scrollTop,380);assert.equal(modal().querySelector('.wb-focused-candidate .wb-review-image img').getAttribute('src'),'/api/assets/edited');assert.deepEqual([0,1,4].map(i=>modal().querySelectorAll('.wb-development-steps button')[i].getAttribute('aria-expanded')==='true'),expanded);assert(!sessionStorage.getItem('imagine-image-return'));assert.equal(flows[0].status,'finished','Flow finishes only after the development window restores');assert.equal(entity.profile.reference_ids.length,3);
  assert(!calls.some(c=>c.endpoint.endsWith('/generate')),'No generation during upload, poll or return');assert(!document.querySelector('.sw-error'));
  await act(async()=>root.unmount());root=null;document.removeEventListener('paste',ctx.framePasteListener);legacyNodes.forEach(node=>document.body.append(node));
  // Explicit visible selections retain their intent; delayed selections lose it
  // when the user navigates away before their request completes.
  const host=document.createElement('div');host.id='productionToolHost';host.append(document.getElementById('imageStudio'));document.body.append(host);host.hidden=false;document.getElementById('imageStudio').hidden=false;document.body.dataset.productionGuided='true';
  let events=[];const selected=event=>events.push(event.detail);win.addEventListener('production-media-selected',selected);
  ctx.sceneAPI=async()=>draft;await ctx.imageSelect(draft);assert.deepEqual(JSON.parse(JSON.stringify(events)),[{kind:'image',id:'draft',selection:true}]);
  events=[];let release;ctx.sceneAPI=async()=>new Promise(resolve=>{release=resolve;});const delayed=ctx.imageSelect(draft);await wait();assert(release);win.history.replaceState({},'','/#/projects');release(draft);await delayed;assert.equal(events.length,0,'A delayed selection cannot navigate after leaving its origin');win.removeEventListener('production-media-selected',selected);
  document.body.append(document.getElementById('imageStudio'));host.remove();for(const id of ['videoStudio','storyStudio','storyContextBar']){const node=document.getElementById(id);if(node)document.body.append(node);}
 }
 dom.window.close();console.log('Inspiration navigation: paste/save/passive polling stays in every Bible and episode development window; exact edited-image return and explicit selection intent are preserved.');
})().catch(async error=>{console.error(error);if(root)await act(async()=>root.unmount());dom.window.close();process.exitCode=1;});
