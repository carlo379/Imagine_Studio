const assert=require('node:assert/strict'),esbuild=require('esbuild'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="root"></div>',{url:'http://studio.invalid'}),w=dom.window;
for(const name of ['window','document','HTMLElement','sessionStorage','Event','FileReader'])global[name]=name==='window'?w:w[name];
global.IS_REACT_ACT_ENVIRONMENT=true;global.fetch=async()=>({ok:false});w.HTMLMediaElement.prototype.pause=function(){};w.HTMLMediaElement.prototype.play=function(){return Promise.resolve();};
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client');
const master={source:{kind:'upload',id:'master'},duration:2,samples:32000,sample_rate:16000,channels:1};
const review={id:'review',revision:1,song_shot_id:'shot',song_anchor:0,clip_anchor:.25,stale:false,comparisons:[],source_metadata:{source:{kind:'upload',id:'video'},duration:2.5,width:160,height:90,fps:'24/1',frames:'60'},intervals:[{start:.25,end:2.25,state:'usable'}],method:'sampled_frames',reviewer:'Fixture author',notes:''};
const shot={id:'shot',revision:1,title:'Coverage',order:0,start:0,end:2,duration:3,leading_handle:.25,trailing_handle:.25,mode:'dance_only',draft_id:null,production_shot_id:null,stale:false,poses:[],reference_handles:[],cue_ids:[],reviews:[review]};
let project={id:'project',revision:1,title:'Fixture song',production_id:'production',episode_id:null,story_scene_id:null,master_version:1,cue_revision:1,lyrics:'retry',master,stems:{},stem_alignment:{},analysis:{result:{waveform:{values:[.2,.6,.1]},notes:['Measured beats need review.']}},cues:[{id:'cue',kind:'word',start:.5,end:1,text:'retry',method:'manual',source:'human',review_state:'reviewed'}],shots:[shot],working_timeline_id:null};
let all=[project],calls=[];
const clone=x=>structuredClone(x);
global.mockSongService=async(path,method='GET',data={},key)=>{
 calls.push({path,method,data:clone(data),key});
 if(path==='song-performance/projects'&&method==='GET')return clone(all);
 if(path==='song-performance/schema')return{recording_generation:{evidence:'Caller-supplied URLs in reference_audios are not enabled for this team.'},local_analysis:{transcription:{message:'No local transcription. No models downloaded.'}}};
 if(path==='assets')return[{id:'pose',name:'Approved pose'}];
 if(path==='productions/production')return{shots:[]};
 if(path==='editing/sources')return{takes:[],images:[],assets:[],uploads:[{source:{kind:'upload',id:'video'},name:'Fixture take',video:true}]};
 if(path==='song-performance/projects/project'&&method==='GET')return clone(project);
 if(path==='song-performance/projects/project'&&method==='PATCH'){project={...project,...data,revision:project.revision+1};delete project.expected_revision;all=[project];return clone(project);}
 if(path==='song-performance/projects/project/shots'&&method==='POST')return{...clone(shot),...data.shot};
 if(path==='song-performance/shots/shot/prepare')return{scene:{prompt:'Keep mouth closed.',audio:false,model:'grok-imagine-video-1.5',resolution:'480p'},request:{prompt:'Keep mouth closed.',generate_audio:false},shot_revision:1,project_revision:project.revision,draft_revision:null,analysis_revision:0,cue_revision:1,song_anchor:0,clip_anchor:.25,anchors:[],note:'No generation.'};
 if(path==='song-performance/shots/shot/apply-draft')return{shot,draft:{id:'draft',revision:1}};
 if(path==='song-performance/shots/shot/take-reviews/review'&&method==='PATCH'){Object.assign(review,data,{revision:review.revision+1});return clone(review);}
 if(path==='song-performance/shots/shot/comparisons')return{id:'comparison',review_revision:review.revision,clip_start:.25,song_start:0,snapshot:{review:clone(review)},export:{id:'compare-export',status:'done',progress:1}};
 if(path==='song-performance/projects/project/assemble'){
  const coverage={selected_singing_seconds:0,missing_spans:[],placements:[{mode:'dance_only',song_start:0,song_end:2,start_frame:0,end_frame:48}],unchecked_reviews:[],plans_without_footage:[]};
  if(data.apply){project.working_timeline_id='working';return{timeline_id:'working',timeline_revision:1,coverage};}return{can_apply:true,coverage};
 }
 if(path==='editing/timelines/working')return{id:'working',revision:1};
 if(path==='editing/exports')return{id:'export',status:'done',progress:1};
 if(path==='editing/media')return{id:'uploaded-master'};
 if(path==='song-performance/projects'&&method==='POST'){project={...project,id:'new-project',title:data.title,master:{...master,source:data.master},lyrics:data.lyrics,shots:[]};all=[project];return clone(project);}
 if(path==='song-performance/projects/new-project')return clone(project);
 throw Error('Unexpected service '+path+' '+method);
};
function button(text){return Array.from(document.querySelectorAll('button')).find(b=>b.textContent===text);}
async function click(text){const b=button(text);assert(b,'Missing button '+text);await act(async()=>{b.click();await new Promise(r=>setTimeout(r,0));});}
async function input(selector,value){const element=document.querySelector(selector);assert(element,selector);await act(async()=>{const proto=element.tagName==='TEXTAREA'?w.HTMLTextAreaElement.prototype:element.tagName==='SELECT'?w.HTMLSelectElement.prototype:w.HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(element,value);element.dispatchEvent(new w.Event(element.tagName==='SELECT'?'change':'input',{bubbles:true}));});}
(async()=>{
 const bundle=await esbuild.build({entryPoints:['ui/song-performance.tsx'],bundle:true,write:false,platform:'node',format:'cjs',external:['react'],plugins:[{name:'mock-services',setup(build){build.onResolve({filter:/^\.\/(studio-service|editing)$/},args=>({path:args.path,namespace:'mock'}));build.onLoad({filter:/.*/,namespace:'mock'},args=>({resolveDir:process.cwd(),contents:args.path.endsWith('studio-service')?'export const service=(...args)=>globalThis.mockSongService(...args);export const useDialog=()=>{};':"import React from 'react';export const EditStudio=({initialTimelineId})=>React.createElement('div',{'data-edit-id':initialTimelineId},'Existing editor');"}));}}]});
 const m={exports:{}};new Function('require','module','exports',bundle.outputFiles[0].text)(require,m,m.exports);const root=createRoot(document.getElementById('root'));
 await act(async()=>{root.render(React.createElement(m.exports.SongPerformance,{productionId:'production',episodeId:null,close:()=>{}}));await new Promise(r=>setTimeout(r,20));});
 assert(document.querySelector('[aria-label="Song Performance"]'));assert(document.body.textContent.includes('HTTP 403'));assert(document.body.textContent.includes('No local transcription.'));
 assert(document.querySelector('[aria-label="Song waveform and cues"]'));assert.equal(document.querySelector('[aria-label="Cue text"]').value,'retry');
 await input('[aria-label="Cue song start"]','.6');await click('Save timing and lyrics');
 const saved=calls.find(c=>c.method==='PATCH'&&c.path.endsWith('/projects/project'));assert.equal(saved.data.cues[0].start,.6);assert.equal(saved.data.cues[0].source,'human');
 await click('Add performance shot');assert(document.querySelector('[aria-label="Performance shot editor"]'));
 await input('[aria-label="Performance mode"]','singing');await input('[aria-label="Shot lyric_text"]','retry');await click('Add interior pose');
 assert(document.body.textContent.includes('snapped'));assert(document.body.textContent.includes('phonemes'));await click('Save plan');
 const plan=calls.find(c=>c.path.endsWith('/shots')&&c.method==='POST');assert.equal(plan.data.shot.mode,'singing');assert.equal(plan.data.shot.lyric_text,'retry');
 await click('Prepare draft locally');assert(document.body.textContent.includes('Review exact final request'));assert(document.body.textContent.includes('generate_audio'));
 assert(!calls.some(c=>c.path.endsWith('/apply-draft')));await click('Apply reviewed proposal to draft · no generation');assert(calls.some(c=>c.path.endsWith('/apply-draft')));
 await click('sampled_frames · 2.500s · 1 usable windows');assert(document.querySelector('[aria-label="Take comparison review"]'));assert.equal(document.querySelector('[aria-label="Comparison soundtrack"]').value,'master');
 await click('Render original-song comparison');assert(document.querySelector('video').getAttribute('src').includes('compare-export'));
 assert(document.querySelector('[aria-label="Review song waveform and beats"]'));await click('Next frame');assert(document.body.textContent.includes('Song 0:00.042'));
 await input('[aria-label="Review method"]','human_continuous_playback');await click('Save take review');assert(calls.some(c=>c.method==='PATCH'&&c.path.includes('take-reviews')&&c.data.method==='human_continuous_playback'));
 await click('Choose usable windows from plans');await click('Inspect coverage proposal');assert(button('Create separate song working edit'));
 await click('Create separate song working edit');await click('Render song working edit');assert(document.querySelector('a[href="/api/exports/export/download"]'));
 await click('Open song working edit in Edit');assert.equal(document.querySelector('[data-edit-id]').getAttribute('data-edit-id'),'working');await click('Back to song');
 assert(!calls.some(c=>c.path.endsWith('/generate')||c.path.startsWith('audio-references')||c.path.includes('recording-transport')));
 // The same UI imports a private master without requiring optional stems or raw JSON.
 await input('[aria-label="Song project"]','');const file=new w.File([new Uint8Array([1,2,3])],'fixture.wav',{type:'audio/wav'});const picker=document.querySelector('[aria-label="Import master"]');
 await act(async()=>{Object.defineProperty(picker,'files',{value:[file],configurable:true});picker.dispatchEvent(new w.Event('change',{bubbles:true}));});
 await act(async()=>{button('Import song').click();await new Promise(r=>setTimeout(r,40));});assert(calls.some(c=>c.path==='editing/media'&&c.data.name==='fixture.wav'));
 assert(calls.some(c=>c.path==='song-performance/projects'&&c.method==='POST'&&c.data.master.id==='uploaded-master'&&Object.keys(c.data.stems).length===0));
 await act(async()=>root.unmount());dom.window.close();console.log('Song import, editable timing, plans/poses, reviewed preparation, comparisons, intervals and working-edit UI pass.');
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});
