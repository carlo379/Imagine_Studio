// No server or provider: the human prompt must never initiate verification on its own.
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<dialog id="develop" open><input id="draft" value="Unsaved prop details"></dialog>',{url:'http://localhost/',runScripts:'outside-only',pretendToBeVisual:true});
const win=dom.window,doc=win.document,calls=[],timers=[];
win.studioWorkspaceId='synthetic-workspace';
win.setInterval=callback=>{timers.push(callback);return timers.length;};win.clearInterval=()=>{};
win.HTMLDialogElement.prototype.showModal=function(){this.open=true;};win.HTMLDialogElement.prototype.close=function(){this.open=false;};
let state={id:'request-1',status:'pending',step:'human_start',human_action_required:true,error:null};
win.fetch=async(url,options={})=>{
 calls.push({url,...options});
 if(url==='/api/studio-account/codex'&&options.method==='POST')return {ok:true,json:async()=>({id:'native-job',kind:'codex',status:'waiting',url:'https://auth.openai.com/synthetic',code:'TEST-ABCDE'})};
 return {ok:true,json:async()=>url==='/api/studio-account/codex'?state:{auth:{kind:'codex',status:'waiting'}}};
};
win.eval(fs.readFileSync('static/account-ui.js','utf8'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 doc.getElementById('draft').focus();win.initCodexReconnectRequests();await flush();
 const notice=doc.getElementById('codexReconnectRequest');
 assert(!notice.hidden);assert.equal(notice.parentElement.id,'develop','Prompt is available inside an open sheet');
 assert.equal(doc.activeElement.id,'draft','Polling must preserve focus and draft context');
 assert.equal(calls.filter(call=>call.method==='POST').length,0,'Agent request only shows a prompt');
 assert(calls.every(call=>call.headers['X-Workspace-ID']==='synthetic-workspace'));
 notice.querySelector('button').click();await flush();
 const posts=calls.filter(call=>call.method==='POST');assert.equal(posts.length,1);
 assert.equal(posts[0].url,'/api/studio-account/codex');assert.deepEqual(JSON.parse(posts[0].body),{request_id:'request-1'});
 assert.equal(posts[0].credentials,'same-origin');assert.equal(posts[0].headers['X-Tester'],'local');
 assert.equal(doc.querySelector('#chatGPTImageConnection [data-code]').textContent,'TEST-ABCDE','Device code stays in the human dialog');
 assert.equal(doc.getElementById('draft').value,'Unsaved prop details');assert.equal(doc.getElementById('develop').open,true);
 doc.getElementById('chatGPTImageConnection').close();
 state={...state,status:'connected',step:'complete',human_action_required:false};await timers[0]();assert(notice.hidden);
 state={...state,status:'error',step:'error',error:'Sign-in did not finish.'};await timers[0]();assert(!notice.hidden);assert(notice.textContent.includes('Try sign-in again'));
 state={...state,status:'idle',step:'none',id:null};await timers[0]();assert(notice.hidden);
 win.fetch=async()=>({ok:false});await timers[0]();assert(notice.hidden,'Expired or changed workspace hides the stale request');
 assert.equal(calls.filter(call=>call.method==='POST').length,1,'Polling never retries sign-in or generates');
 assert(calls.every(call=>call.url.startsWith('/api/studio-account')));
 dom.window.close();console.log('ChatGPT reconnect request: explicit human start, scoped polling, safe status and preserved development context pass.');
})().catch(error=>{dom.window.close();console.error(error);process.exitCode=1;});
