const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function fixture(){
 const timers=new Map(),events={},document={hidden:false,addEventListener:(name,fn)=>events[name]=fn,getElementById:()=>null};let next=0;
 const window={studioWorkspaceId:'fixture-owner',addEventListener:(name,fn)=>events[name]=fn};
 const calls=[];let handler=async()=>({revision:'same',areas:{productions:'one'}});
 const context={window,document,structuredClone,setTimeout:(fn)=>{timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id),fetch:async(url)=>{calls.push(url);const value=await handler(url);return{ok:true,json:async()=>value};}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/performance.js'),'utf8'),context);
 return{runtime:window.StudioRuntime,calls,document,events,timers,setHandler:fn=>handler=fn,step:async()=>{const entry=timers.entries().next().value;assert.ok(entry,'Expected scheduled check');timers.delete(entry[0]);await entry[1]();}};
}

(async()=>{
 const f=fixture();let release;
 f.setHandler(()=>new Promise(resolve=>release=resolve));
 const first=f.runtime.json('/api/example'),second=f.runtime.json('/api/example');
 assert.equal(f.calls.length,1,'Concurrent GETs should share one request');
 release({draft:{title:'Saved'}});
 const [a,b]=await Promise.all([first,second]);a.draft.title='Local edit';assert.equal(b.draft.title,'Saved','Draft objects must not be shared');
 f.calls.length=0;let changes=0,state='one';
 f.setHandler(async()=>({revision:state,areas:{productions:state}}));
 const stop=f.runtime.watch(async()=>{changes++;},{areas:['productions']});
 await f.step();assert.equal(changes,1);await f.step();assert.equal(changes,1,'Unchanged revisions must not reload project data');
 state='two';await f.step();assert.equal(changes,2);
 f.document.hidden=true;const before=f.calls.length;await f.step();assert.equal(f.calls.length,before,'Hidden tabs must not poll');
 f.document.hidden=false;stop();assert.equal(f.timers.size,0);
 const g=fixture();let finish;
 g.setHandler(async()=>({revision:'one',areas:{productions:'one'}}));
 g.runtime.watch(()=>new Promise(resolve=>finish=resolve),{areas:['productions']});
 const running=g.step();for(let n=0;!finish&&n<20;n++)await Promise.resolve();assert.ok(finish);
 await g.runtime.wake();assert.equal(g.calls.length,1,'An unfinished change check must not overlap');
 finish();await running;
 assert.ok(g.runtime.thumbnail('/api/assets/abc',160).includes('workspace=fixture-owner'));
 assert.equal(g.runtime.thumbnail('https://example.invalid/image.png'),'https://example.invalid/image.png');
 console.log('Performance runtime regressions passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
