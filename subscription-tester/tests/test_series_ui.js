const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {buildSync}=require('esbuild');
const {JSDOM}=require('jsdom');
const compiled=path.resolve('.validation/series-books/series-ui.cjs');
fs.mkdirSync(path.dirname(compiled),{recursive:true});
buildSync({entryPoints:['ui/series-workspace.tsx'],bundle:true,platform:'node',external:['react','react-dom'],outfile:compiled,logLevel:'silent'});
const dom=new JSDOM('<div id="root"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const k of ['window','document','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','MouseEvent','CustomEvent','sessionStorage','localStorage','FileReader'])global[k]=win[k];
global.IS_REACT_ACT_ENVIRONMENT=true;
win.matchMedia=query=>({matches:query.includes('prefers-reduced-motion'),addEventListener(){},removeEventListener(){}});
global.ResizeObserver=class{observe(){}disconnect(){}};
Object.defineProperty(win.HTMLElement.prototype,'clientWidth',{get:()=>1080});
const nativeTimeout=global.setTimeout,nativeInterval=global.setInterval;
global.setTimeout=(fn,ms,...args)=>nativeTimeout(fn,Math.min(ms,30),...args);
global.setInterval=(fn,ms,...args)=>nativeInterval(fn,Math.max(ms,1000),...args);
global.requestAnimationFrame=fn=>nativeTimeout(()=>fn(performance.now()),1);global.cancelAnimationFrame=clearTimeout;
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{SeriesWorkspace}=require(compiled);
const root=createRoot(document.getElementById('root'));
let bible={id:'bible-p',production_id:'p',revision:0,answers:{title:'Example Series',idea:'',genre:'Sci-Fi',tone:'Hopeful',style:'Illustrated'},guide:{cast:[],places:[],props:[],acts:[],script:''}},books={},episodes=[{id:'ep1',title:'Episode 1',revision:1,scenes:[]}],writes=[],jobs=[],latestJob;
const foundation={id:'hero',name:'SampleHero',category:'Character',scope:'series',status:'ready',identity_asset_id:'portrait',reference_id:'ref-hero',reference:{id:'ref-hero',title:'SampleHero',handle:'SampleHero',category:'Character',images:[{asset_id:'portrait'}]},profile:{voice:'Warm and curious'}};
const production={id:'p',title:'Example Series',kind:'story',revision:1};
let selected='ep1',prepared=0;
const createBook=id=>({id:'book-'+id,episode_id:id,production_id:'p',revision:0,answers:{title:episodes.find(e=>e.id===id).title,idea:''},guide:{cast:[],places:[],props:[],acts:[],script:''},selected_asset_ids:[],inheritance:null,episode:structuredClone(episodes.find(e=>e.id===id))});
const response=data=>Promise.resolve({ok:true,json:async()=>structuredClone(data)});
global.fetch=async(url,opts={})=>{
 if(url==='/api/config')return response({voices:['eve','rex']});
 const endpoint=url.replace('/api/agent/',''),data=opts.body?JSON.parse(opts.body):{},method=opts.method||'GET';
 if(endpoint==='documents/render')return response({text:JSON.stringify(data.document)});
 if(method!=='GET')writes.push({endpoint,data,method});
 if(endpoint==='productions/p')return response({production,episodes,shots:[]});
 if(endpoint==='filmmaking/series/p/library')return response([foundation]);
 if(endpoint==='filmmaking/series/p/bible'){
  if(method==='PUT')bible={...bible,...data,revision:bible.revision+1};return response(bible);
 }
 if(endpoint==='filmmaking/worlds/p/import-preview'){
  assert.equal(data.text,'INT. WORKSHOP - DAY\nSampleHero hears a signal.');
  return response({answers:{title:'Uploaded story',idea:'Imported premise'},guide:{cast:[{id:'imported',name:'Unrequested hero'}],places:[{id:'new-place',name:'Unrequested location'}],props:[],acts:[{id:'new-arc',title:'Unrequested story beat',text:'Replace the arc'}],script:data.text}});
 }
 if(endpoint==='filmmaking/episodes/ep1/upload-preview')return response({source:data.text,comparisons:[{id:'local-detail'}],review_token:'local-review'});
 if(endpoint==='filmmaking/episodes/ep1/upload-ai-review')return response({id:'upload-review',status:'done',result:{source:data.text,comparisons:[],mode:'ai',review_token:'ai-review',review_job_id:'upload-review'}});
 if(endpoint==='filmmaking/episodes/ep1/upload-apply'){
  assert.equal(data.expected_revision,books.ep1.revision);
  assert.equal(data.expected_episode_revision,books.ep1.episode.revision);
  if(data.review_job_id){assert.equal(data.review_job_id,'upload-review');assert.deepEqual(data.choices,{});}else {assert.equal(data.review_token,'local-review');assert.deepEqual(data.choices,{'local-detail':'both'});}
  books.ep1={...books.ep1,revision:books.ep1.revision+1,guide:{...books.ep1.guide,script:data.source}};
  return response(books.ep1);
 }
 if(endpoint==='productions/p/episodes'){
  const e={id:'ep'+(episodes.length+1),title:data.title,revision:1,scenes:[]};episodes.push(e);return response(e);
 }
 const match=endpoint.match(/^filmmaking\/episodes\/([^/]+)\/(book|jobs|plan|library|trash-script)$/);
 if(match){const [,id,route]=match;if(!books[id])books[id]=createBook(id);
  if(route==='book'){
   if(method==='PUT'){
    assert.equal(data.expected_episode_revision,books[id].episode.revision);
    books[id]={...books[id],...data,revision:books[id].revision+1,inheritance:books[id].inheritance||{answers:bible.answers,guide:bible.guide,assets:[]}};
    if(data.answers.title!==books[id].episode.title){books[id].episode.title=data.answers.title;books[id].episode.revision++;episodes.find(e=>e.id===id).title=data.answers.title;}
   }return response(books[id]);
  }
  if(route==='trash-script'){
   assert.equal(data.expected_revision,books[id].revision);
   assert.deepEqual(data.expected_job_revisions,Object.fromEntries(jobs.map(j=>[j.id,j.revision])));
   const before=structuredClone(books[id]);
   books[id].script_drafts=[...(books[id].script_drafts||[]),{id:'draft-history',label:'Draft saved before trash',script:books[id].guide.script}];
   books[id].guide.script='';books[id].episode.scenes=[];books[id].episode.revision++;books[id].revision++;
   jobs=jobs.map(j=>({...j,script_inactive:true,revision:j.revision+1}));
   assert.deepEqual(books[id].answers,before.answers);
   for(const k of ['cast','places','props','acts'])assert.deepEqual(books[id].guide[k],before.guide[k]);
   return response({book:books[id],jobs});
  }
  if(route==='library')return response([foundation]);
  if(route==='jobs')return response(jobs);
  if(route==='plan'){
   assert.equal(data.expected_episode_revision,books[id].episode.revision,'Writing must target the actual episode revision');
   latestJob={id:'plan-one',revision:1,status:'done',result:{reply:'Draft',logline:'The signal',synopsis:'SampleHero discovers a signal.',visual_style:'3D',assets:[],scenes:[{title:'Discovery',text:'SampleHero hears a signal.',shots:[{title:'Opening',image_prompt:'SampleHero in the workshop.',video_prompt:'SampleHero discovers the signal.'}]}]}};jobs.push(latestJob);return response(latestJob);
  }
 }
 throw Error('Unexpected UI API request: '+method+' '+endpoint);
};
const render=()=>root.render(React.createElement(SeriesWorkspace,{production,episodeId:selected,prepare:async()=>{prepared++;},changed:async()=>{},openEpisode:async id=>{selected=id;render();},continueProduction:async()=>{},openAsset:async()=>{}}));
// BookFrame uses elapsed animation-frame time, independent of the compressed autosave timer.
const settle=()=>new Promise(r=>nativeTimeout(r,250));
async function click(text){const button=[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===text||b.textContent.trim()===text);assert(button,'Missing button '+text);assert(!button.disabled,'Disabled button '+text);await act(async()=>{button.dispatchEvent(new win.MouseEvent('click',{bubbles:true}));await settle();});}
async function input(label,value){const el=[...document.querySelectorAll('label')].find(x=>x.firstChild?.textContent===label)?.querySelector('input,textarea');assert(el,'Missing field '+label);await act(async()=>{const proto=el.tagName==='TEXTAREA'?win.HTMLTextAreaElement.prototype:win.HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);el.dispatchEvent(new win.Event('input',{bubbles:true}));await settle();});return el;}
async function chapter(name){const b=[...document.querySelectorAll('.sw-chapters button')].find(b=>b.textContent.endsWith(name));assert(b,'Missing chapter '+name);await act(async()=>{b.click();await settle();});}
(async()=>{
 await act(async()=>{render();await settle();});
 assert(document.querySelector('[aria-label="Open Series Bible"]'),'Distinct Bible cover');
 await click('Open Series Bible');
 const style=document.querySelector('input[aria-label="Visual style custom entry"]');assert(style,'Visual style is available on the first Bible spread, before character development');assert.equal(style.value,'Illustrated','Moving the field preserves an existing saved style');
 await click('Cinematic stylized 3D animation');assert.equal(bible.answers.style,'Cinematic stylized 3D animation','The first-spread preset saves the same series style field');
 await input('Series premise','SampleHero explores ');
 assert.equal(document.querySelector('textarea').value,'SampleHero explores ','A paused trailing space must survive saving');
 assert.equal(bible.answers.idea,'SampleHero explores ');assert(bible.revision>0);
 await click('Read manuscript');assert(document.querySelector('.sb-manuscript').textContent.includes('SampleHero explores '));await click('Return to book');
 await chapter('Look & rules');assert(!document.querySelector('input[aria-label="Visual style custom entry"]'),'Visual style no longer waits behind character creation');
 await chapter('Characters');assert.equal(bible.answers.style,'Cinematic stylized 3D animation');await input('Character name','Mark');
 const longPersonality='Mark is curious and optimistic. '.repeat(70)+'END OF FULL DESCRIPTION';
 const personality=await input('Personality',longPersonality);assert.equal(personality.maxLength,10000);assert.equal(bible.guide.cast[0].personality,longPersonality,'The complete long description survives autosave');
 const oversizedPaste=new win.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(oversizedPaste,'clipboardData',{value:{getData:()=> 'x'.repeat(10001)}});await act(async()=>{personality.dispatchEvent(oversizedPaste);await settle();});assert(oversizedPaste.defaultPrevented,'Oversized paste must be rejected visibly, not silently clipped');assert.equal(personality.value,longPersonality);
 await click('Expand Personality');const expanded=document.querySelector('[aria-label="Personality expanded editor"]');assert.equal(expanded.value,longPersonality);await click('Return to book');
 await act(async()=>{document.querySelectorAll('.sw-main-nav button')[1].click();await settle();});
 await click('Open storybook Episode 1');await click('Open Episode Book');await input('Episode premise','A mysterious signal.');
 const beforeUpload=structuredClone(books.ep1);
 await click('↑ Upload script');await input('Or paste your text','INT. WORKSHOP - DAY\nSampleHero hears a signal.');await click('Review story →');assert(!writes.some(w=>w.endpoint.endsWith('/upload-ai-review')),'Selecting an upload does not call AI');assert(!document.querySelector('[aria-label="Duplicate information review"]'),'Default import does not require comparison choices');assert(![...document.querySelectorAll('label')].some(l=>l.textContent.includes('Use AI to find duplicate')));await input('Imported script','INT. WORKSHOP - DAY\nSampleHero hears a signal.\nA carefully reviewed ending.');await click('Import script →');
 assert.deepEqual(books.ep1.answers,beforeUpload.answers,'Episode upload cannot change any earlier answer, even an empty one');
 for(const k of ['cast','places','props','acts'])assert.deepEqual(books.ep1.guide[k],beforeUpload.guide[k],'Upload preserves earlier '+k);
 assert(document.querySelector('[role=tab][aria-selected=true]').textContent==='Draft');
 assert.equal(books.ep1.guide.script,'INT. WORKSHOP - DAY\nSampleHero hears a signal.\nA carefully reviewed ending.','Edited uploads import unchanged without AI');assert.equal(books.ep1.answers.idea,'A mysterious signal.','Upload keeps filled fields unless replacement is selected');
 // AI comparison is available only after reviewing an upload and clicking its action.
 await click('Upload script');await input('Or paste your text','INT. WORKSHOP - DAY\nSampleHero hears a signal.');await click('Review story →');assert(!writes.some(w=>w.endpoint.endsWith('/upload-ai-review')));await click('Compare with saved details using AI');assert.equal(writes.filter(w=>w.endpoint.endsWith('/upload-ai-review')).length,1);assert(document.querySelector('[aria-label="Duplicate information review"]'));const replaceInput=[...document.querySelectorAll('label')].find(l=>l.textContent.includes('Replace the current Script draft')).querySelector('input');await act(async()=>replaceInput.click());await click('Apply upload choices →');

 assert(books.ep1.inheritance,'First episode edit captures the foundation');assert.equal(books.ep1.inheritance.answers.style,'Cinematic stylized 3D animation','Episodes inherit the style saved on the first Bible spread');
 await chapter('Cast');assert([...document.querySelectorAll('.sw-reuse-list button')].some(b=>b.textContent.includes('SampleHero')),'Available Bible assets stay visible after an empty initial selection');
 const select=document.querySelector('.sw-reuse-list button');await act(async()=>{select.click();await settle();});assert.deepEqual(books.ep1.selected_asset_ids,['hero']);
 await chapter('Script');await click('Develop script with AI ↗');assert(writes.some(w=>w.endpoint==='filmmaking/episodes/ep1/plan'));
 assert.equal(document.querySelector('[role=tab][aria-selected=true]').textContent,'Review');
 assert(![...document.querySelectorAll('button')].some(b=>b.textContent==='Create storyboard →'),'Creation action is isolated to Storyboard');
 await click('Continue to storyboard →');assert.equal(document.querySelector('[role=tab][aria-selected=true]').textContent,'Storyboard');
 assert([...document.querySelectorAll('button')].some(b=>b.textContent==='Create storyboard →'));
 await click('Trash current script');await click('Keep script');assert(books.ep1.guide.script,'Cancel keeps the script');
 const beforeTrash=structuredClone(books.ep1);await click('Trash current script');await click('Trash script');
 assert.equal(books.ep1.guide.script,'');assert.equal(document.querySelector('[role=tab][aria-selected=true]').textContent,'Draft');
 assert.equal(document.querySelector('[aria-label="Script workflow"] [role=tab]:last-child').disabled,true,'Storyboard is unavailable after trash');
 assert.deepEqual(books.ep1.answers,beforeTrash.answers);
 await click('Version history · 2');
 const draftVersion=[...document.querySelectorAll('.sb-version')].find(v=>v.textContent.includes('Draft saved before trash'));assert(draftVersion,'Manual draft is recoverable');
 await act(async()=>{draftVersion.querySelector('button').click();await settle();});
 assert.equal(books.ep1.guide.script,beforeTrash.guide.script);assert.deepEqual(books.ep1.answers,beforeTrash.answers);

 await chapter('The idea');await input('Episode title','The Lost Signal ');assert.equal(books.ep1.episode.title,'The Lost Signal ');assert.equal(selected,'ep1');
 await click('← All episodes');
 const createButton=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='＋ New episode');await act(async()=>{createButton.click();await settle();});
 await input('Episode title','Trouble at the Lab');await click('Create storybook →');assert.equal(selected,'ep2');assert.equal(episodes.length,2);assert.equal(bible.answers.idea,'SampleHero explores ','Creating an episode does not rewrite the Bible');assert(prepared>0,'Tool/tab transitions prepare saved work');
 assert(document.querySelector('[aria-label="Open Episode Book"]'),'Second episode has its own closed cover state');
 await act(async()=>{root.unmount();});dom.window.close();
 console.log('Series UI: separate books, paused typing, save-before-switch, episode naming/create, reusable cast after initial save, and episode-targeted AI request passed.');
})().catch(async e=>{console.error(e);await act(async()=>root.unmount());dom.window.close();process.exitCode=1;});
