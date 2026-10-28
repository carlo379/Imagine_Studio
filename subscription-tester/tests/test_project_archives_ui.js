const assert=require('node:assert/strict'),path=require('node:path'),{buildSync}=require('esbuild'),{JSDOM}=require('jsdom');
const output=path.resolve('.validation/project-archives-ui.cjs');buildSync({entryPoints:['ui/project-archives.tsx'],bundle:true,platform:'node',external:['react','react-dom'],outfile:output,logLevel:'silent'});
const dom=new JSDOM('<div id="root"></div>',{url:'http://127.0.0.1:8765/'});global.window=dom.window;global.document=dom.window.document;global.navigator=dom.window.navigator;global.sessionStorage=dom.window.sessionStorage;global.IS_REACT_ACT_ENVIRONMENT=true;
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{ProjectExport,ProjectImport}=require(output);
const calls=[];let prepared=0,changed=0,opened='';const report={complete:false,missing_files:['videos/missing.mp4'],remote_references:[]};
global.fetch=async(url,options={})=>{calls.push({url,options});return {ok:true,json:async()=>url.endsWith('/export')?{id:'export-task',status:'working',progress:0,message:'Preparing project…'}:url.endsWith('/import')?{id:'import-task',status:'done',progress:100,message:'Imported',project_id:'new-project',report:{...report,complete:true,missing_files:[]}}:{id:'export-task',status:'done',progress:100,message:'Ready',download:'/api/project-archives/export-task/download',report}};};
(async()=>{const root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(ProjectExport,{projectId:'project',prepare:async()=>{prepared++;}})));
await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Export project…').click());assert.equal(prepared,1);assert(document.querySelector('a[download]'));assert(document.body.textContent.includes('Some media could not be included'));assert(document.body.textContent.includes('videos/missing.mp4'));
assert(calls.some(c=>c.url==='/api/agent/productions/project/export'));
// Browsers with a save picker stream bytes to the selected destination.
let selectedOptions=null,written=[],closed=0,aborted=0;
const baseFetch=global.fetch;
global.fetch=async(url,options)=>url.endsWith('/download')?new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([80,75]));c.enqueue(new Uint8Array([1,2,3]));c.close();}}),{headers:{'Content-Length':'5'}}):baseFetch(url,options);
window.showSaveFilePicker=async options=>{selectedOptions=options;return {name:'My chosen project.zip',createWritable:async()=>({write:async chunk=>written.push(...chunk),close:async()=>{closed++;},abort:async()=>{aborted++;}})};};
// Remount simulates reopening a completed export in a picker-capable browser.
await act(async()=>root.render(React.createElement(ProjectExport,{key:'picker',projectId:'project',prepare:async()=>{}})));
await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Save ZIP as…').click());
assert.deepEqual(written,[80,75,1,2,3]);assert.equal(closed,1);assert.equal(aborted,0);assert(selectedOptions.suggestedName.endsWith('.zip'));assert(document.body.textContent.includes('Saved My chosen project.zip to your chosen folder.'));
window.showSaveFilePicker=async()=>{throw new dom.window.DOMException('Cancelled','AbortError');};
await act(async()=>root.render(React.createElement(ProjectExport,{key:'cancel',projectId:'project',prepare:async()=>{}})));
await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Save ZIP as…').click());assert(!document.querySelector('[role=alert]'));assert.equal(closed,1);
window.showSaveFilePicker=async()=>({name:'failure.zip',createWritable:async()=>({write:async()=>{throw Error('Disk full');},close:async()=>{closed++;},abort:async()=>{aborted++;}})});
await act(async()=>root.render(React.createElement(ProjectExport,{key:'failure',projectId:'project',prepare:async()=>{}})));
await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Save ZIP as…').click());assert.equal(aborted,1);assert.equal(closed,1);assert(document.querySelector('[role=alert]').textContent.includes('Disk full'));delete window.showSaveFilePicker;
await act(async()=>root.render(React.createElement(ProjectImport,{prepare:async()=>{prepared++;},changed:async()=>{changed++;},open:async id=>{opened=id;}})));
const input=document.querySelector('input[type=file]'),file=new dom.window.File(['PK fake ZIP'], 'project.zip',{type:'application/zip'});Object.defineProperty(input,'files',{value:[file],configurable:true});await act(async()=>input.dispatchEvent(new dom.window.Event('change',{bubbles:true})));assert.equal(prepared,2);assert.equal(changed,1);const transfer=calls.find(c=>c.url==='/api/project-archives/import');assert.equal(transfer.options.body,file);assert.equal(transfer.options.headers['X-Tester'],'local');await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Open imported project').click());assert.equal(opened,'new-project');await act(async()=>root.unmount());dom.window.close();console.log('Project archives UI: saved export, progress/report/download, ZIP import and open copy passed.');})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close();});
