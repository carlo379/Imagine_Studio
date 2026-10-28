const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('static/studio.js','utf8');
function between(start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));}
const nodes=new Map();let state,loads=0,pauses=0,guided=false;
function $(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,readyState:2,attrs:{},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return k==='src'?this.src||null:this.attrs[k]||null;},removeAttribute(k){delete this.attrs[k];},pause(){pauses++;},load(){loads++;this.readyState=0;}});return nodes.get(id);}
const sandbox={$ ,JSON,api:async()=>state,window:{productionBridge:{guided:()=>guided}},renderAccount(){},refreshHistory:async()=>{},render(){},gate(){},imageGate(){}};
vm.createContext(sandbox);
vm.runInContext("let frameJob=null,shownVideo='',observedServerVideo=undefined,account,previousPhase='',history=[],sceneRecord={id:'scene-a'},requestValid=true;"+between('function showVideo(', 'async function refreshHistory(')+between('async function pollOnce(', 'async function demo('),sandbox);
function job(id,url='shared-url',scene='scene-a'){return {id,settings:{_studio_video_id:scene},video:url};}
async function poll(id,url='shared-url'){state={video:url,job_id:id,phase:'done',progress:null,mock:true};await vm.runInContext('pollOnce()',sandbox);}
function select(id){vm.runInContext(`showVideo('shared-url',${JSON.stringify(id)})`,sandbox);}
(async()=>{
 sandbox.jobs=[job('latest'),job('older'),job('next'),job('other','shared-url','scene-b')];vm.runInContext('history=jobs',sandbox);
 await poll('latest');assert.equal($('video').src,'/api/video-media/latest');
 select('older');$('video').readyState=2;await poll('latest');await poll('latest');assert.equal($('video').src,'/api/video-media/older');assert.equal($('download').href,'/api/download/older');assert.equal(vm.runInContext('frameJob',sandbox),'older');
 const before=loads;select('older');assert.equal(loads,before);assert.equal($('captureFrame').disabled,false);
 await poll('next');assert.equal($('video').src,'/api/video-media/next','New render with the same URL must update by job ID');
 guided=true;select('older');await poll('other');assert.equal($('video').src,'/api/video-media/older','Another shot must not replace selected playback');
 vm.runInContext('observedServerVideo=undefined',sandbox);await poll('latest');assert.equal($('video').src,'/api/video-media/older','Initial poll must preserve the selected saved take');
 sandbox.newJobs=[job('fresh')];sandbox.refreshHistory=async()=>vm.runInContext('history=[...history,...newJobs]',sandbox);await poll('fresh');assert.equal($('video').src,'/api/video-media/fresh','A newly completed scoped render must refresh history before matching its shot');
 assert(pauses>=3);console.log('Video playback: history selection survives polling; new renders, scoped shots, download/capture and loaded-player reuse pass.');
})().catch(e=>{console.error(e);process.exitCode=1;});
