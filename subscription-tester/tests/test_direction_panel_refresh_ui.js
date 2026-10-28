const assert=require('node:assert/strict'),fs=require('fs'),{JSDOM}=require('jsdom'),{buildSync}=require('esbuild');
const source=fs.readFileSync('ui/production.tsx','utf8');
const keyFor=component=>Function('selected','return '+source.match(new RegExp('<'+component+' key=\\{([^}]+)\\}'))[1]);
const editorKey=keyFor('ShotDirection'),videoKey=keyFor('VideoDirection');
fs.mkdirSync('.validation',{recursive:true});buildSync({entryPoints:['ui/shot-direction.tsx'],bundle:true,platform:'node',format:'cjs',external:['react'],outfile:'.validation/direction-refresh.cjs'});
const dom=new JSDOM('<div id="root"></div>');global.window=dom.window;global.document=window.document;global.navigator=window.navigator;global.IS_REACT_ACT_ENVIRONMENT=true;
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{ShotDirection}=require('../.validation/direction-refresh.cjs');
const root=createRoot(document.getElementById('root'));const VideoDirection=()=>React.createElement('div',{className:'video-direction-panel'},'Video direction');
const render=shot=>root.render(React.createElement('section',null,[React.createElement(ShotDirection,{key:editorKey(shot),shot,save:async()=>{}}),React.createElement('div',{key:'context',className:'p-context'},shot.title),React.createElement(VideoDirection,{key:videoKey(shot)}),React.createElement('div',{key:'host',id:'productionToolHost'})]));
(async()=>{let shot={id:'shot-one',revision:3,title:'Door',story_direction:'Start with the door open.',story_direction_updated_at:1};
 assert.notEqual(editorKey(shot),videoKey(shot),'Sibling panels need distinct identities');
 await act(()=>render(shot));await act(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Edit shot direction').click());
 const editor=document.querySelector('.p-shot-direction'),input=document.querySelector('textarea');
 for(let i=0;i<60;i++){await act(()=>render({...shot,revision:4+i}));assert.equal(document.querySelectorAll('.p-shot-direction').length,1,'Exactly one editor after polling');assert.equal(document.querySelectorAll('.video-direction-panel').length,1);assert.equal(document.querySelector('.p-shot-direction'),editor,'Refresh preserves editor node');assert.equal(document.querySelector('textarea'),input,'Refresh preserves editing state');}
 await act(()=>render({...shot,id:'shot-two',title:'Next shot',story_direction:'Next direction.'}));assert.equal(document.querySelectorAll('.p-shot-direction').length,1);assert(document.querySelector('.p-shot-direction').textContent.includes('Next direction.'));
 await act(()=>root.unmount());dom.window.close();console.log('Direction panels: distinct keys; 60 refreshes retain one editor and one video panel; editor state retained; shot switching replaces cleanly.');
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1;});
