/* Recording controls use local APIs; fake responses do not prove provider support. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync('index.html','utf8'),{url:'http://localhost/'});
const calls=[],rows=[{id:'recording1',name:'Vocal.wav',duration:9}];
const ctx={window:dom.window,document:dom.window.document,Option:dom.window.Option,localStorage:dom.window.localStorage,
 TextEncoder,crypto:require('node:crypto').webcrypto,structuredClone,console,Map,Set,Promise,sceneRecord:null,
 setTimeout:()=>0,clearTimeout(){},setInterval:()=>0};
vm.createContext(ctx);const run=code=>vm.runInContext(code,ctx);
run(fs.readFileSync('static/studio.js','utf8').replace('\ninit();','\n'));
ctx.sceneAPI=async(path,method='GET',data)=>{calls.push({path,method,data});if(path==='/audio-references')return rows;
 if(path.endsWith('/excerpts'))return {id:'excerpt1',reference_id:'recording1',start_s:data.start_s,end_s:data.end_s,duration:data.end_s-data.start_s};throw Error('Unexpected '+path);};
ctx.change=fn=>fn();
const tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const findButton=text=>[...dom.window.document.querySelectorAll('#recordingPanel button')].find(b=>b.textContent===text);
(async()=>{
 run('project=blank();project.duration=9;renderRecording();');await tick();
 assert.equal(calls.length,1);assert.equal(calls[0].path,'/audio-references');
 const box=dom.window.document.getElementById('recordingPanel');
 assert(box.textContent.includes('audio reference after generation approval'));assert(box.textContent.includes('Singing synchronization is unverified'));
 let pick=box.querySelector('select[aria-label="Uploaded recording"]');pick.value='recording1';pick.onchange();
 let start=box.querySelector('[aria-label="Excerpt start seconds"]'),end=box.querySelector('[aria-label="Excerpt end seconds"]');
 assert.equal(start.value,'0');assert.equal(end.value,'9');
 assert(box.querySelector('audio').src.endsWith('/audio-references/recording1/download'));
 start.value='0.25';end.value='8.8';findButton('Prepare & attach excerpt').click();await tick();
 assert.equal(calls.at(-1).path,'/audio-references/recording1/excerpts');
 assert.equal(calls.at(-1).data.start_s,.25);assert.equal(calls.at(-1).data.end_s,8.8);
 assert.equal(run('project.recording.excerpt_id'),'excerpt1');assert.equal(run('project.duration'),9);
 ctx.namedExpansion=()=>({prompt:'Leo sings.',errors:[]});
 assert.equal(run('compile()._studio_audio_reference.excerpt_id'),'excerpt1');
 assert(run('compile().prompt').includes('<AUDIO_0>'));
 assert(box.textContent.includes('Duration mismatch'));assert(box.querySelector('audio').src.endsWith('/audio-excerpts/excerpt1/download'));
 run("project.voices=[{id:'preset',voice:'rex'}];project.audio=false;renderRecording();");
 assert(box.textContent.includes('Preset voices conflict'));assert(box.textContent.includes('Audio is off'));
 findButton('Remove recording').click();assert.equal(run('project.recording'),null);
 assert.equal(run('project.voices[0].voice'),'rex','Removing a recording preserves explicit preset assignments');
 // A completed async trim must never attach to a newly selected scene.
 run('project=blank();renderRecording();');pick=box.querySelector('select');pick.value='recording1';pick.onchange();
 let finish;ctx.sceneAPI=()=>new Promise(resolve=>{finish=resolve;});findButton('Prepare & attach excerpt').click();
 run('project=blank();');finish({id:'stale',start_s:0,end_s:9,duration:9});await tick();
 assert.equal(run('project.recording'),null);assert(box.textContent.includes('scene changed'));
 console.log('Recording UI: preview, trim, attachment, mismatch, preset conflict, removal and scene-switch race pass.');dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});
