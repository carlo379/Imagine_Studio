const assert=require('node:assert/strict'),path=require('node:path'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const compiled=path.resolve('.validation/library-ui.cjs');buildSync({entryPoints:['ui/world-workshop.tsx'],bundle:true,platform:'node',external:['react','react-dom'],outfile:compiled,logLevel:'silent'});
const dom=new JSDOM('<div id="root"></div>',{url:'http://test.invalid/',pretendToBeVisual:true}),win=dom.window;
for(const key of ['window','document','HTMLElement','HTMLInputElement','HTMLTextAreaElement','Event','MouseEvent','CustomEvent','navigator'])global[key]=win[key];
global.IS_REACT_ACT_ENVIRONMENT=true;global.requestAnimationFrame=win.requestAnimationFrame.bind(win);global.cancelAnimationFrame=win.cancelAnimationFrame.bind(win);
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{VisualEntity}=require(compiled),root=createRoot(document.getElementById('root'));
let entity,view,calls=[],fail=false,fileClicks=0;win.HTMLInputElement.prototype.click=function(){if(this.type==='file')fileClicks++;};
const reply=body=>({ok:true,json:async()=>structuredClone(body)});
const render=()=>root.render(React.createElement(VisualEntity,{key:entity.id,entity,views:[view],busy:false,rendering:false,model:'gpt-image-2',run:async fn=>fn(),refresh:async()=>{render();return {entities:[entity],views:[view]};},generate:async()=>{throw Error('Unexpected generation');},reference:async()=>{throw Error('Unexpected upload');}}));
global.fetch=async(url,opts={})=>{const method=opts.method||'GET',body=opts.body?JSON.parse(opts.body):null;calls.push({url,method,body});
 if(url==='/api/config')return reply({voices:[]});
 if(url.endsWith('/assets'))return reply([{id:'studio',name:'output.png',mime:'image/png',generated:true,approved:true},{id:'unapproved',name:'Unapproved',mime:'image/png',generated:true,approved:false},{id:'rejected',name:'Rejected',mime:'image/png',approved:true,review_state:'rejected'},{id:'video',name:'Video',mime:'video/mp4'},...Array.from({length:6},(_,i)=>({id:'upload'+i,name:'Upload '+i,mime:'image/jpeg'}))]);
 if(url.endsWith('/references'))return reply([{title:"SampleHero's Cowboy Tech Studio",images:[{asset_id:'studio'}]}]);
 if(url.endsWith('/image-studio/jobs'))return reply([{draft:{title:'Studio draft'},outputs:[{id:'studio'}]}]);
 if(url.endsWith('/filmmaking/entities/'+entity.id)&&method==='PUT'){if(fail)return {ok:false,json:async()=>({error:{message:'Revision conflict. Try again.'}})};entity={...entity,profile:body.profile,description:body.description,revision:entity.revision+1};return reply(entity);}
 if(url.endsWith('/image-studio/drafts/draft'))return reply(view.draft);
 if(url.endsWith('/prompting/image/draft'))return reply({current:false});
 throw Error('Unexpected '+method+' '+url);
};
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
async function click(text){const b=button(text);assert(b,'Missing '+text);await act(async()=>b.click());}
async function select(title){const b=document.querySelector('[aria-label="Select '+title+'"]');assert(b,'Missing image '+title);await act(async()=>b.click());}
(async()=>{for(const category of ['Location','Character','Prop']){
 entity={id:category,name:'Test '+category,category,revision:1,profile:{description:'Saved details',reference_ids:[]},description:'A room',identity_asset_id:'identity',suggested_views:[]};view={id:'main',kind:category==='Character'?'portrait':category.toLowerCase(),revision:1,outputs:[],draft:{id:'draft',revision:1,settings:{model:'gpt-image-2',prompt:'Saved direction'}}};calls=[];await act(async()=>render());
 await click('02Add inspiration');assert(document.querySelector('.wb-active-workspace .wb-inspiration-library'),'Add inspiration immediately displays Library on the left');assert(!document.querySelector('.wb-image-workspace'),'Choose candidates do not occupy the inspiration workspace');await click('＋Add images ▾');assert.equal(fileClicks,0);assert(button('From computer'));assert(button('From Library'));assert(button('Paste image'));
 await click('From computer');assert.equal(fileClicks,1);fileClicks=0;
 await click('＋Add images ▾');await click('Paste image');assert(document.querySelector('.inspiration-tray-message').textContent.includes('Ctrl+V'));
 await click('＋Add images ▾');await click('From Library');assert(document.querySelector('.wb-active-workspace .wb-inspiration-library'),'Library uses left column');assert(!document.querySelector('dialog'));
 assert(!document.querySelector('[aria-label="Select Unapproved"]'));assert(!document.querySelector('[aria-label="Select Rejected"]'));assert(!document.querySelector('[aria-label="Select Video"]'));
 const search=document.querySelector('input[type=search]');await act(async()=>{Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype,'value').set.call(search,'Cowboy');search.dispatchEvent(new win.Event('input',{bubbles:true}));});assert.equal(document.querySelectorAll('.wb-library-image').length,1);
 await select("SampleHero's Cowboy Tech Studio");fail=true;await click('Add 1 selected image');assert(document.querySelector('.wb-inspiration-library [role=alert]').textContent.includes('conflict'));assert.deepEqual(entity.profile.reference_ids,[]);assert.equal(document.querySelector('[aria-label="Select SampleHero\'s Cowboy Tech Studio"]').getAttribute('aria-pressed'),'true');assert.equal(document.querySelectorAll('.inspiration-tray-tile').length,0,'Failed save cannot leave an attached thumbnail');
 fail=false;await click('Add 1 selected image');assert.deepEqual(entity.profile.reference_ids,['studio']);assert.equal(entity.identity_asset_id,'identity');assert.equal(document.querySelectorAll('.inspiration-tray-tile').length,1);assert(document.querySelector('[aria-label="Select SampleHero\'s Cowboy Tech Studio"]').disabled);
 await act(async()=>{Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype,'value').set.call(search,'');search.dispatchEvent(new win.Event('input',{bubbles:true}));});
 for(let i=0;i<4;i++)await select('Upload '+i);assert(document.querySelector('[aria-label="Select Upload 4"]').disabled,'Selection stops at five total');await click('Add 4 selected images');assert.equal(entity.profile.reference_ids.length,5);
 assert(!calls.some(c=>c.method==='POST'),'Library attachment creates no uploads, jobs or approvals');
 await click('Continue → Prepare prompt');assert(!document.querySelector('.wb-inspiration-library'));assert(document.querySelector('.wb-preparation-panel'));assert.equal(document.querySelector('[aria-current=step]').textContent,'03Prepare prompt');
 }
 await act(async()=>root.unmount());dom.window.close();console.log('Library inspiration: all categories, left-column browsing, sources/search/filtering, existing asset reuse, conflict retry, identity preservation, five-image limit and five-step continuation pass.');
})().catch(async e=>{console.error(e);await act(async()=>root.unmount());dom.window.close();process.exitCode=1;});
