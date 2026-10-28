const assert=require('node:assert/strict'),path=require('node:path'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const compiled=path.resolve('.validation/five-step-ui.cjs');buildSync({entryPoints:['ui/world-workshop.tsx'],bundle:true,platform:'node',external:['react','react-dom'],outfile:compiled,logLevel:'silent'});
const dom=new JSDOM('<div id="root"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const key of ['window','document','HTMLElement','HTMLInputElement','HTMLTextAreaElement','Event','MouseEvent','CustomEvent'])global[key]=win[key];
global.IS_REACT_ACT_ENVIRONMENT=true;global.requestAnimationFrame=win.requestAnimationFrame.bind(win);global.cancelAnimationFrame=win.cancelAnimationFrame.bind(win);
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{VisualEntity}=require(compiled),root=createRoot(document.getElementById('root'));
let entity,view,job,calls=[],renders=[],conflict=false,selectedModel='gpt-image-2';
const reply=body=>({ok:true,json:async()=>structuredClone(body)});
const render=()=>root.render(React.createElement(VisualEntity,{key:entity.id,entity,views:[view],busy:false,rendering:false,model:selectedModel,run:async fn=>fn(),refresh:async()=>{render();return {entities:[entity],views:[view]};},generate:async(...args)=>renders.push(args),reference:async()=>{throw Error('Unexpected upload');}}));
global.fetch=async(url,opts={})=>{const method=opts.method||'GET',body=opts.body?JSON.parse(opts.body):null;calls.push({url,method,body});
 if(url==='/api/config')return reply({voices:[]});
 if(url.endsWith('/image-studio/drafts/draft'))return reply(view.draft);
 if(url.endsWith('/prompting/image/draft')&&method==='GET')return reply({current:!!view.draft.prompt_preparation_current,job});
 if(url.endsWith('/assets/main/prompt-draft'))return reply({current:!!view.draft.prompt_preparation_current,draft:view.draft});
 if(url.endsWith('/prompting/image/draft')&&method==='POST'){job={id:'job',revision:1,media_revision:view.draft.revision,status:entity.category==='Location'?'pending':'done',provider:'codex',instruction:body.instruction,brief:view.draft.settings.prompt,result:{prompt:'AI prepared location prompt.',notes:['Keep the adjoining studio visible.']},provenance:{guides:[]}};return reply(job);}
 if(url.endsWith('/prompting/jobs/job')){job={...job,status:'done'};return reply(job);}
 if(url.endsWith('/prompting/image/draft/apply')){if(conflict)return {ok:false,json:async()=>({error:{message:'The draft changed; edits preserved.'}})};
  view={...view,draft:{...view.draft,revision:view.draft.revision+1,settings:{...view.draft.settings,prompt:body.prompt},prompt_preparation_current:true,prompt_preparation:{instruction:job.instruction}}};job={...job,applied:true};return reply({draft:view.draft,job});}
 throw Error('Unexpected '+method+' '+url);
};
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
async function click(text){const b=button(text);assert(b,'Missing '+text);await act(async()=>b.click());}
async function input(area,value){await act(async()=>{Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype,'value').set.call(area,value);area.dispatchEvent(new win.Event('input',{bubbles:true}));});}
(async()=>{for(const category of ['Location','Character','Prop']){
 entity={id:category,name:'Test '+category,category,revision:1,profile:{description:'Saved details',reference_ids:[]},description:'A room',suggested_views:[]};view={id:'main',kind:category==='Character'?'portrait':category.toLowerCase(),revision:1,outputs:[],draft:{id:'draft',revision:1,settings:{model:'gpt-image-2',prompt:'Saved direction'}}};job=null;calls=[];renders=[];win.localStorage.clear();await act(async()=>render());
 assert.deepEqual([...document.querySelectorAll('.wb-development-steps button')].map(b=>b.textContent),['01Describe','02Add inspiration','03Prepare prompt','04Generate','05Choose']);
 await click('04Generate');assert(document.querySelector('.wb-generate-main').disabled,'Unreviewed prompt cannot generate');
 await click('03Prepare prompt');assert(document.querySelector('.wb-preparation-panel'));assert(!document.querySelector('dialog'));
 await input(document.querySelector('[aria-label="Additional instruction (Optional)"]'),'Keep the studio visible.');
 await click('Prepare image prompt with AI');assert.equal(renders.length,0);assert.equal(calls.find(c=>c.url.endsWith('/prompting/image/draft')&&c.method==='POST').body.instruction,'Keep the studio visible.');
 if(category==='Location'){assert(document.querySelector('[role=status]').textContent.includes('Preparing'));await act(async()=>new Promise(resolve=>setTimeout(resolve,1450)));}
 const area=document.querySelector('[aria-label="Prepared image prompt"]');assert.equal(area.value,'AI prepared location prompt.');await input(area,'Reviewed and edited prompt.');
 conflict=true;await click('Use prompt & continue →');assert(document.querySelector('[role=alert]').textContent.includes('edits preserved'));assert.equal(area.value,'Reviewed and edited prompt.');conflict=false;
 await click('Use prompt & continue →');assert(document.querySelector('.wb-generation-panel'));assert.equal(renders.length,0,'Review never renders');assert.equal(view.draft.settings.prompt,'Reviewed and edited prompt.');
 const preparedCalls=calls.filter(c=>c.method==='POST').length;for(const model of ['grok-imagine-image-2.0','gpt-image-2']){selectedModel=model;await act(async()=>render());assert(!document.querySelector('.wb-generate-main').disabled,'Model switch retains review');assert.equal(view.draft.settings.prompt,'Reviewed and edited prompt.');await click('03Prepare prompt');assert.equal(document.querySelector('[aria-label="Prepared image prompt"]').value,'Reviewed and edited prompt.');await click('04Generate');}assert.equal(calls.filter(c=>c.method==='POST').length,preparedCalls,'Model switch performs no AI writing');
 await click(category==='Character'?'Generate character sheet ↗':category==='Prop'?'Generate prop ↗':'Generate location ↗');assert.equal(renders.length,1);assert.equal(document.querySelector('[aria-current=step]').textContent,'05Choose');
 await click('03Prepare prompt');await input(document.querySelector('[aria-label="Additional instruction (Optional)"]'),'New guidance');await click('04Generate');assert(document.querySelector('.wb-generate-main').disabled,'New instructions require fresh review');assert(!document.querySelector('dialog'));
 }
 await act(async()=>root.unmount());dom.window.close();console.log('Five-step UI: all categories, inline preparation/edit/review, conflict preservation, no dialog, separate generation and changed instruction guards pass.');
})().catch(async e=>{console.error(e);await act(async()=>root.unmount());dom.window.close();process.exitCode=1;});
