const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="libraryImages"></div><p id="libraryError"></p>');
const record={url_id:'remembered-one',revision:1,archived:false,src:'https://example.invalid/view.png',name:'View'};
const calls=[],context={urls:[record],assets:[],console,JSON,structuredClone,document:dom.window.document,$:id=>dom.window.document.getElementById(id),persist:()=>{},dragSource:()=>{},choose:()=>{}};
context.el=(tag,cls='',text='')=>{const e=context.document.createElement(tag);e.className=cls;e.textContent=text;return e;};
context.button=(label,handler,cls='')=>{const e=context.el('button',cls,label);e.onclick=handler;return e;};
context.thumbnail=()=>context.el('img');
vm.createContext(context);vm.runInContext(fs.readFileSync('static/scenes.js','utf8'),context);
vm.runInContext(fs.readFileSync('static/studio.js','utf8').split('\n').find(line=>line.startsWith('function renderLibrary()')),context);
let archived=false;
context.sceneAPI=async(path,method,data)=>{calls.push({path,method,data});if(method==='POST'){assert.equal(path,'/urls/remembered-one/archive');assert.equal(data.expected_revision,1);assert.equal(data.archived,true);archived=true;return {...record,revision:2,archived:true};}return archived?[]:[record];};
(async()=>{
  context.renderLibrary();context.document.querySelector('button.text-button').click();await new Promise(r=>setImmediate(r));
  assert.equal(calls[0].path,'/urls/remembered-one/archive');assert.equal(context.urls.length,0);assert(!context.document.querySelector('button.text-button'));
  context.urls=[record];context.renderLibrary();context.sceneAPI=async(path,method)=>{if(method==='POST'){const e=Error('URL changed; reload first.');e.code='revision_conflict';throw e;}return [{...record,revision:3}];};
  context.document.querySelector('button.text-button').click();await new Promise(r=>setImmediate(r));
  assert.equal(context.urls[0].revision,3);assert.match(context.$('libraryError').textContent,/URL changed/);
  dom.window.close();console.log('Remembered URL UI: server archive, refreshed list and visible revision conflict passed.');
})().catch(e=>{console.error(e);process.exitCode=1;dom.window.close();});
