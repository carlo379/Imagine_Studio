const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="imageHistory"></div>'),document=dom.window.document;
const lines=fs.readFileSync('static/image-studio.js','utf8').split('\n');
const job={id:'recoverable',request_id:'saved-request',recoverable:true,status:'error',message:'Download failed',model:'grok-imagine-image-2.0',created_at:1,outputs:[],draft:{id:'draft',title:'Original request',settings:{model:'grok-imagine-image-2.0',resolution:'1k',quality:'auto'}}};
let consent=false,calls=[],history=0,gates=0,shown;
const context={document,window:dom.window,$:id=>document.getElementById(id),imageJobs:[job],imageDraft:{id:'draft'},imageSchema:{models:{'grok-imagine-image-2.0':{label:'Grok'}}},localHistoryJobs:(kind,jobs)=>jobs,
 el:(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text)n.textContent=text;return n;},
 button:(text,action,cls)=>{const b=document.createElement('button');b.textContent=text;b.className=cls||'';b.onclick=action;return b;},
 imageAPI:async(path,method,body)=>{calls.push({path,method,body});return {...job,status:'discarded',recoverable:false};},imageShowJob:j=>{shown=j;},imageHistory:async()=>{history++;},imageGate:()=>{gates++;},toast:message=>{throw Error(message);},resumeImage:()=>{},imageWorkspaceTab:()=>{}};
dom.window.confirm=message=>{assert.match(message,/does not cancel/);assert.match(message,/usage/);return consent;};
vm.createContext(context);
for(const name of ['discardRecoverableImage','renderImageHistory'])vm.runInContext(lines.find(line=>line.startsWith((name==='discardRecoverableImage'?'async ':'')+'function '+name+'(')),context);
(async()=>{
 context.renderImageHistory();assert([...document.querySelectorAll('button')].some(b=>b.textContent==='Discard recovery'));
 await context.discardRecoverableImage(job);assert.equal(calls.length,0,'Cancelling confirmation sends no request');
 consent=true;await context.discardRecoverableImage(job);
 assert.equal(calls.length,1);assert.equal(calls[0].path,'/jobs/recoverable/discard');assert.equal(calls[0].method,'POST');
 assert.equal(calls[0].body.confirmed,true);assert.equal(calls[0].body.request_id,'saved-request');
 assert.equal(shown.status,'discarded');assert.equal(history,1);assert.equal(gates,1);
 dom.window.close();console.log('Confirmed image recovery disposal, retained history and generation-gate refresh pass.');
})().catch(error=>{console.error(error);process.exitCode=1;});
