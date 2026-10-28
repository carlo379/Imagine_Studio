const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('tester.html','utf8'),dom=new JSDOM(html,{runScripts:'outside-only',url:'http://localhost:8876/'}),calls=[];
const state={phase:'ready',message:'Mock connected',mock:true,signed_in:true,image:null};
const context={document:dom.window.document,console,JSON,Error,setInterval:()=>{},crypto:{randomUUID:()=> 'tester-controlled-key'},fetch:async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>state};}};
vm.createContext(context);vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
(async()=>{
  await new Promise(r=>setImmediate(r));const approved=context.document.getElementById('approved');approved.checked=true;approved.onchange();
  context.document.getElementById('generate').click();await new Promise(r=>setImmediate(r));
  const request=calls.find(c=>c.path==='/api/generate');assert(request);assert.equal(request.options.headers['Idempotency-Key'],'tester-controlled-key');
  assert.equal(JSON.parse(request.options.body).approved,true);assert.equal(approved.checked,false);
  dom.window.close();console.log('Tester UI: approved diagnostic sends an Idempotency-Key and clears approval passed.');
})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close();});
