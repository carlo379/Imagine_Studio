// Exercise the actual dialog and workshop flow using local provider fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<button id="previous">Previous focus</button>',{url:'http://test.invalid/',runScripts:'outside-only',pretendToBeVisual:true}),win=dom.window;
const studioMarkup=new win.DOMParser().parseFromString(fs.readFileSync('index.html','utf8'),'text/html');
for(const id of ['imagePreparePrompt','videoPreparePrompt'])win.document.body.append(win.document.importNode(studioMarkup.getElementById(id),true));
win.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
win.HTMLDialogElement.prototype.close=function(){this.open=false;};
win.setTimeout=((native)=>((fn,ms,...args)=>native(fn,Math.min(ms,10),...args)))(win.setTimeout.bind(win));
const calls=[];let ready=false,stale=false,savedPrompt='Creative brief.',savedInstruction='';
const draft=()=>({id:'draft',revision:4,title:'A frame',settings:{model:'gpt-image-2',prompt:savedPrompt},prompt_preparation:{instruction:savedInstruction}});
const job=()=>({id:'job',revision:2,kind:'image',media_id:'draft',media_revision:4,provider:'grok',provider_requested:'auto',fallback_from:'codex',fallback_reason:'codex usage limit: fixture limit',status:'done',mock:false,
 result:{prompt:'AI-authored still frame.',notes:['Preserve the red cup.']},provenance:{guides:[{file:'gpt-image-2.0-2.5-prompting-guide.md',sha256:'a'.repeat(64)}]},
 writing_returned_model:'fixture-model',writing_usage:{cached_input_tokens:55},writing_duration_ms:12});
const response=(body,ok=true)=>({ok,json:async()=>structuredClone(body)});
win.fetch=global.fetch=async(url,options={})=>{
 const path=url.replace('/api/agent/',''),method=options.method||'GET',body=options.body?JSON.parse(options.body):null;
 calls.push({path,method,body,headers:options.headers});
 if(path==='image-studio/drafts/draft'&&method==='GET')return response(draft());
 if(path==='prompting/image/draft'&&method==='GET')return response({current:ready,model:'gpt-image-2',provenance:null,job:null});
 if(path==='prompting/image/draft'&&method==='POST'){savedInstruction=body.instruction;return response(job());}
 if(path==='prompting/image/draft/apply'){
  if(stale)return response({error:{code:'revision_conflict',message:'The draft changed; your newer work is preserved.'}},false);
  savedPrompt=body.prompt;ready=true;return response({job:{...job(),applied:true},draft:{...draft(),revision:5}});
 }
 if(path==='filmmaking/assets/view/prompt-draft')return response({current:ready,draft:draft()});
 throw Error('Unexpected request '+method+' '+path);
};
const dialogStyle=win.document.createElement('style');dialogStyle.textContent=fs.readFileSync('static/media-prompting.css','utf8');win.document.head.append(dialogStyle);
win.eval(fs.readFileSync('static/media-prompting.js','utf8'));
const settle=()=>new Promise(resolve=>setTimeout(resolve,15));
async function until(check){for(let i=0;i<100&&!check();i++)await settle();assert(check(),'Expected UI state');}
const button=text=>[...win.document.querySelectorAll('button')].find(b=>b.textContent===text);
async function review(edited,automatic=false){
 if(!automatic){await until(()=>button('Prepare prompt'));assert.equal(calls.filter(c=>c.method==='POST'&&c.path.startsWith('prompting/')).length,0);
 button('Prepare prompt').click();}
 else {await until(()=>calls.some(c=>c.path==='prompting/image/draft'&&c.method==='POST'));assert(win.document.querySelector('select').closest('label').hidden);assert.equal(win.getComputedStyle(win.document.querySelector('select').closest('label')).display,'none');assert(win.document.querySelector('[aria-label="Instructions for prompt AI"]').closest('label').hidden);assert(![...win.document.querySelectorAll('button')].some(b=>['Prepare prompt','Prepare again'].includes(b.textContent)&&!b.hidden));}
 await until(()=>button('Use reviewed prompt')&&!button('Use reviewed prompt').hidden);
 const area=win.document.querySelector('[aria-label="Prepared media prompt"]');assert.equal(area.value,'AI-authored still frame.');
 assert(win.document.querySelector('pre').textContent.includes('55'));assert(win.document.querySelector('pre').textContent.includes('codex usage limit: fixture limit'));assert(win.document.body.textContent.includes('No media has been generated.'));
 area.value=edited;
}
(async()=>{
 win.document.getElementById('previous').focus();
 const pending=win.MediaPrompting.prepare('image','draft',{instruction:'Keep the red cup.'});
 await review('AI-authored still frame. Keep the red cup in her right hand.');
 const writing=calls.find(c=>c.path==='prompting/image/draft'&&c.method==='POST');
 assert.equal(writing.body.expected_revision,4);assert.equal(writing.body.approved,true);assert.equal(writing.body.provider,undefined);
 assert.equal(writing.body.instruction,'Keep the red cup.');assert(writing.headers['Idempotency-Key']);
 stale=true;button('Use reviewed prompt').click();await until(()=>win.document.querySelector('[role=alert]').textContent.includes('newer work'));
 assert.equal(savedPrompt,'Creative brief.');assert.equal(win.document.querySelector('textarea[aria-label="Prepared media prompt"]').value,'AI-authored still frame. Keep the red cup in her right hand.');
 assert(win.document.querySelector('dialog').open);stale=false;button('Use reviewed prompt').click();
 const applied=await pending;assert.equal(applied.settings.prompt,savedPrompt);assert.equal(applied.revision,5);
 assert.equal(win.document.activeElement.id,'previous');assert.equal(win.document.querySelectorAll('dialog').length,0);

 const count=calls.length;const cancelled=win.MediaPrompting.prepare('image','draft');
 await until(()=>button('Close'));button('Close').click();assert.equal(await cancelled,null);
 assert(calls.slice(count).every(c=>c.method==='GET'),'Opening and closing a review never authorizes a writer or render');

 global.window=win;ready=false;calls.length=0;
 const compiled=buildSync({entryPoints:['ui/media-prompting.ts'],bundle:true,write:false,format:'cjs',platform:'node',external:['react','react-dom'],logLevel:'silent'}).outputFiles[0].text;
 const mod={exports:{}};new Function('require','module','exports',compiled)(require,mod,mod.exports);
 const views=[{id:'view',revision:2}];const first=mod.exports.workshopPrompts(views,'gpt-image-2',undefined,'Keep the warm lighting.');
 await review('Reviewed workshop still.',true);assert.equal(calls.find(c=>c.path==='prompting/image/draft'&&c.method==='POST').body.instruction,'Keep the warm lighting.');button('Use reviewed prompt').click();assert.equal(await first,false,'Preparing ends at review; the current click does not render');
 const authored=calls.filter(c=>c.path==='prompting/image/draft'&&c.method==='POST').length;
 assert.equal(await mod.exports.workshopPrompts(views,'gpt-image-2',undefined,'Keep the warm lighting.'),true,'A separate click can reuse current reviewed preparation');
 assert.equal(calls.filter(c=>c.path==='prompting/image/draft'&&c.method==='POST').length,authored);
 assert(mod.exports.viewPromptReady({draft:{settings:{model:'gpt-image-2',prompt:'Reviewed workshop still.'},prompt_preparation_current:true}},'gpt-image-2'));
 assert(!mod.exports.viewPromptReady({draft:{settings:{model:'gpt-image-2'},prompt_preparation_current:true,prompt_preparation:{instruction:'Old direction'}}},'gpt-image-2',undefined,'New direction'));
 ready=true;const changed=mod.exports.workshopPrompts(views,'gpt-image-2',undefined,'Make the light cooler.');await until(()=>button('Use reviewed prompt')&&!button('Use reviewed prompt').hidden);assert.equal(calls.filter(c=>c.path==='prompting/image/draft'&&c.method==='POST').at(-1).body.instruction,'Make the light cooler.');button('Use reviewed prompt').click();assert.equal(await changed,false,'Changed instructions require review before generation');
 assert(!calls.some(c=>c.path.includes('generate')||c.path==='/api/video'),'Prompt preparation never starts media generation');
 ready=false;const beforeGuard=calls.filter(c=>c.path==='prompting/image/draft'&&c.method==='POST').length;await assert.rejects(()=>mod.exports.workshopPrompts(views,'gpt-image-2',undefined,'New input',true),/Return to Prepare prompt/);assert.equal(calls.filter(c=>c.path==='prompting/image/draft'&&c.method==='POST').length,beforeGuard,'Generation preflight cannot open preparation or contact a writer');
 const style=win.document.createElement('style');style.textContent=fs.readFileSync('static/media-prompting.css','utf8');win.document.head.append(style);
 const videoButton=win.document.getElementById('videoPreparePrompt');
 win.document.body.dataset.productionGuided='true';
 assert.equal(win.getComputedStyle(videoButton).display,'none','Project shots use Video direction & timing only');
 assert.notEqual(win.getComputedStyle(win.document.getElementById('imagePreparePrompt')).display,'none','Image preparation remains available');
 const beforeHiddenClick=calls.length;await videoButton.onclick();assert.equal(calls.length,beforeHiddenClick,'Hidden project action cannot start another preparation flow');
 win.document.body.dataset.productionGuided='false';
 assert.notEqual(win.getComputedStyle(videoButton).display,'none','Standalone video retains generic preparation');
 assert.equal(videoButton.textContent,'Prepare video prompt with AI');
 console.log('Media prompting UI: explicit writer authorization, guide/cache evidence, review/edit/apply, preserved stale edits, cancel, focus restoration, separate workshop generation click and project/standalone preparation routing pass.');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
