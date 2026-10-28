const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="recovery"></div>',{url:'http://localhost/',runScripts:'outside-only'}),win=dom.window;
let connected=false,retries=0,calls=[],events=[];
win.fetch=async(path,options)=>{calls.push([path,options.method]);return {ok:true,json:async()=>path==='/api/grok/check'?{signed_in:connected}:{subscription:{signed_in:connected}}};};
win.addEventListener('studio-reconnect-provider',e=>events.push(e.detail.provider));
win.eval(fs.readFileSync('static/provider-recovery.js','utf8'));const recovery=win.ProviderRecovery,host=win.document.getElementById('recovery');
assert.equal(recovery.classify('Codex returned an error','grok-imagine-image-2.0').provider,'codex');
for(const message of ['Codex timed out. Check usage','Codex returned an error','Grok moderation rejected image'])assert.equal(recovery.classify(message).kind,'other');
assert.equal(recovery.classify('Codex quota exhausted').kind,'usage');
assert.equal(recovery.classify('Grok Auth context expired (HTTP 500)','grok-imagine-image-2.0','authentication_expired').kind,'other');
(async()=>{for(const provider of ['grok','codex']){connected=false;recovery.mount(host,{message:provider==='grok'?'Grok expired authentication context':'Sign in with ChatGPT in Codex',retry:async()=>retries++});const [connect,check,retry]=host.querySelectorAll('button');assert.equal(retry.hidden,true);connect.click();assert.equal(events.at(-1),provider);assert.equal(retries,provider==='grok'?0:1,'Sign-in never generates');await check.onclick();assert.equal(retry.hidden,true,'Disconnected check does not enable retry');connected=true;await check.onclick();assert.equal(retry.hidden,false);await retry.onclick();assert.equal(retries,provider==='grok'?1:2);assert(calls.every(([path])=>!path.includes('generate')));}
const originalTimer=win.setTimeout.bind(win);win.setTimeout=fn=>originalTimer(fn,0);
win.fetch=(_path,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));
await assert.rejects(recovery.check('grok'),/timed out/);win.setTimeout=originalTimer;
recovery.mount(host,{message:'Codex allowance exhausted'});assert(host.hidden,'Usage failures do not offer misleading reconnect');dom.window.close();console.log('Recovery: both providers, auth vs quota/timeout, failed/successful verification, explicit single retry and no automatic generation pass.');})().catch(e=>{console.error(e);process.exitCode=1;});
