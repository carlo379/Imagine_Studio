const assert=require('node:assert/strict'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1/',pretendToBeVisual:true});
for(const key of ['window','document','HTMLElement','Event','CustomEvent','sessionStorage'])global[key]=dom.window[key];
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client');
const bundle=buildSync({entryPoints:['ui/browser-handoff.tsx'],bundle:true,write:false,platform:'node',format:'cjs',external:['react','react-dom'],logLevel:'silent'}).outputFiles[0].text;
const mod={exports:{}};new Function('require','module','exports',bundle)(require,mod,mod.exports);
const {AgentControls}=mod.exports,root=createRoot(document.getElementById('root'));
const timers=new Map(),nativeInterval=global.setInterval,nativeClear=global.clearInterval;
let timer=0,sharing=true,controls=false,pending=[],acks=[],route={page:'home'},navigations=[],views=[],draft='unsaved',saves=0,discards=0,identity=[];
global.setInterval=(fn)=>{timers.set(++timer,fn);return timer;};global.clearInterval=id=>timers.delete(id);
const capture=()=>({id:'asset',revision:2,dirty:true,data:{prompt:draft},actions:['save','discard']});
window.studioAgentEditors={precision:{capture,save:async()=>{saves++;draft='saved';},discard:async()=>{discards++;draft='';}}};
window.addEventListener('studio-identity-request',e=>identity.push(e.detail));
global.fetch=async(url,options={})=>{const data=options.body?JSON.parse(options.body):null;const reply=value=>({ok:true,json:async()=>structuredClone(value)});
 if(url==='/api/browser-handoff')return reply({sharing_enabled:sharing});
 if(url==='/api/browser-handoff/tabs')return reply({tab:{id:'tab',revision:1,state:data},controls_enabled:controls,requests:pending});
 if(url==='/api/browser-handoff/controls/consent'){controls=data.enabled;return reply({controls_enabled:controls});}
 if(url.endsWith('/ack')){acks.push(data);pending=pending.filter(r=>!url.includes('/'+r.id+'/'));return reply({status:data.status});}
 throw Error('Unexpected browser operation '+url);
};
let sequence=0;
function request(kind,payload){const r={id:'request-'+(++sequence),revision:1,kind,payload,expected_state:{route:structuredClone(route),editors:{precision:capture()}}};if(kind==='resolve')r.expected_editor=capture();pending=[r];return r;}
async function poll(){await act(async()=>{for(const fn of [...timers.values()])await fn();});}
async function click(text){const button=[...document.querySelectorAll('button')].find(b=>b.textContent===text);assert(button,text);await act(async()=>{button.click();await new Promise(r=>setTimeout(r,0));});}
(async()=>{
 await act(async()=>root.render(React.createElement(AgentControls,{route:()=>route,navigate:async value=>{navigations.push(value);route=value;},view:()=>({}),applyView:async value=>views.push(value)})));
 request('navigate',{route:{page:'library',collection:'images'},view:{query:'robot'}});await poll();assert.equal(navigations.length,0,'Read-only sharing never authorizes navigation');
 await click('Apply request');assert.deepEqual(navigations,[{page:'library',collection:'images'}]);assert.equal(acks.at(-1).status,'completed');assert.deepEqual(views.at(-1),{query:'robot'});
 request('resolve',{editor:'precision',action:'save'});await poll();draft='changed after request';await click('Apply request');assert.equal(saves,0);assert.equal(acks.at(-1).status,'failed');assert(acks.at(-1).error.includes('browser changed'));
 await click('Allow browser controls for two hours');request('resolve',{editor:'precision',action:'save'});await poll();assert.equal(saves,1);assert.equal(acks.at(-1).status,'completed');
 request('identity',{action:'logout'});await poll();assert.equal(identity.length,0,'Identity never executes under automatic browser control consent');await click('Apply request');assert.equal(identity.length,1);assert.equal(acks.at(-1).status,'awaiting_human');
 request('resolve',{editor:'precision',action:'discard'});sharing=false;await poll();assert.equal(discards,0);assert(!document.body.textContent.includes('Agent request:'));
 await act(async()=>root.unmount());assert.equal(timers.size,0);global.setInterval=nativeInterval;global.clearInterval=nativeClear;dom.window.close();console.log('Agent controls: separate consent, exact-tab navigation, view application, stale-draft rejection, acknowledged save, explicit identity handoff and revocation pass.');
})().catch(async error=>{console.error(error);await act(async()=>root.unmount());global.setInterval=nativeInterval;global.clearInterval=nativeClear;dom.window.close();process.exitCode=1;});
