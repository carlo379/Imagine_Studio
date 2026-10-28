const assert=require('node:assert/strict'),path=require('node:path'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const compiled=path.resolve('.validation/series-books/develop-rejected-ui.cjs');
buildSync({entryPoints:['ui/series-workspace.tsx'],bundle:true,platform:'node',external:['react','react-dom'],outfile:compiled,logLevel:'silent'});
const dom=new JSDOM('<div id="root"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const k of ['window','document','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','MouseEvent','CustomEvent','sessionStorage','localStorage'])global[k]=win[k];
global.IS_REACT_ACT_ENVIRONMENT=true;global.requestAnimationFrame=win.requestAnimationFrame.bind(win);global.cancelAnimationFrame=win.cancelAnimationFrame.bind(win);global.ResizeObserver=class{observe(){}disconnect(){}};win.matchMedia=()=>({matches:true});Object.defineProperty(win.HTMLElement.prototype,'clientWidth',{get:()=>1080});
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{SeriesWorkspace}=require(compiled);
const production={id:'p',title:'Example Series',kind:'story'};
const guide={cast:[{id:'hero',name:'Hero',description:'A robot.'}],places:[{id:'lab',name:'Lab',description:'A workshop.'}],props:[{id:'charger',name:'Charging Station',description:'A charging dock.'}],acts:[],script:''};
const bible={id:'bible-p',production_id:'p',revision:159,answers:{style:'3D'},guide};
let category='Prop',failed=false,calls=[];
const message='Could not open development for prop Charging Station: An inspiration image file is missing.';
global.fetch=async(url,options={})=>{
 const endpoint=url.replace('/api/agent/','');calls.push({endpoint,method:options.method||'GET',data:options.body?JSON.parse(options.body):null});
 const response=data=>({ok:true,json:async()=>structuredClone(data)});
 if(endpoint==='filmmaking/series/p/bible')return response(bible);
 if(endpoint==='productions/p')return response({production,episodes:[],shots:[]});
 if(endpoint.endsWith('/library'))return response([]);
 if(endpoint==='filmmaking/series/p/workshop'){
  if(failed)return {ok:false,status:409,json:async()=>({error:{code:'missing_asset',message}})};
  const entry=(category==='Character'?guide.cast:category==='Location'?guide.places:guide.props)[0];
  return response({job:{id:'world',result:{visual_style:'3D'}},entities:[{...entry,category,revision:2,production_id:'p',profile:{reference_ids:[]},identity_asset_id:null,suggested_views:[]}],views:[{id:'main',entity_id:entry.id,kind:category==='Character'?'portrait':category==='Location'?'location':'prop',view:'Main reference',revision:3,selected:null,outputs:[{id:'original',review_state:'rejected'},{id:'refined',review_state:'rejected'}],draft:{id:'draft',revision:4,settings:{prompt:'Fresh direction',base:null,edit_region:null,extras:[],bindings:[]}}}],batches:[]});
 }
 if(url==='/api/config')return response({voices:[]});
 if(endpoint==='account')return response({signed_in:true});
 if(endpoint==='openai/account')return response({subscription:{signed_in:true}});
 throw Error('Unexpected request '+url);
};
const wait=()=>new Promise(r=>setTimeout(r,70));
(async()=>{
 for(const scenario of [{category:'Character',page:1,label:'Develop appearance →'},{category:'Location',page:2,label:'Develop location →'},{category:'Prop',page:3,label:'Develop prop →'},{category:'Prop',page:3,label:'Develop prop →',failed:true}]){
  category=scenario.category;failed=!!scenario.failed;calls=[];sessionStorage.clear();sessionStorage.setItem('imagine-series-book-bible-bible-p-page',String(scenario.page));
  const root=createRoot(document.getElementById('root'));
  await act(async()=>{root.render(React.createElement(SeriesWorkspace,{production,prepare:async()=>{},changed:async()=>{},openEpisode:async()=>{},continueProduction:async()=>{}}));await wait();});await act(async()=>wait());
  const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===scenario.label);assert(button);
  await act(async()=>{button.click();await wait();});
  const request=calls.find(c=>c.endpoint==='filmmaking/series/p/workshop');assert.equal(request.method,'POST');assert.equal(request.data.expected_revision,159);
  if(failed){assert(!document.querySelector('.sw-asset-modal'));assert(document.querySelector('.sw-error').textContent.includes(message));}
  else{assert(document.querySelector('.sw-asset-modal'),'Rejected candidates must not prevent opening '+category);assert(!document.querySelector('.sw-error'),'Rejected history is not a page error');assert(document.querySelector('.wb-review-gallery').textContent.includes('Rejected'));}
  assert(!calls.some(c=>c.endpoint.endsWith('/generate')),'Opening the editor never generates images');
  await act(async()=>root.unmount());
 }
 dom.window.close();console.log('Develop opening: all categories open with rejected history; actual failures remain clear and no generation occurs.');
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
