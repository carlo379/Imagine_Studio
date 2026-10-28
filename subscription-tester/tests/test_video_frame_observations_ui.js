const assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),{buildSync}=require('esbuild');
const dom=new JSDOM('<div id="root"></div><div id="videoDirectionPanel"></div><small id="videoDurationSuggestion"></small><textarea id="prompt">Saved generation direction.</textarea>',{url:'http://localhost/'});
Object.assign(global,{window:dom.window,document:dom.window.document,sessionStorage:dom.window.sessionStorage,Event:dom.window.Event});
window.productionBridge={videoState:()=>({model:'grok-imagine-video-1.5',duration:12})};
const job={id:'job',revision:2,video_id:'video',video_revision:3,status:'done',provider:'codex',video_model:'grok-imagine-video-1.5',auto_apply:false,applied:true,previous_duration:10,result:{direction:'Open the right door.',asset_summaries:[],duration_seconds:12,duration_reason:'Allow door movement.',notes:['Keep the left door closed.'],starting_frame_observations:['Visible: closed hinged doors.','Uncertain: left handle is obscured.']}};
global.fetch=async()=>({ok:true,json:async()=>({job,provider:'codex',video_model:job.video_model,duration:12,prompt_limit_chars:4096,instruction_limit_chars:2000})});
const compiled=buildSync({entryPoints:['ui/video-direction.tsx'],bundle:true,write:false,format:'cjs',platform:'node',external:['react','react-dom'],logLevel:'silent'}).outputFiles[0].text;
const mod={exports:{}};new Function('require','module','exports',compiled)(require,mod,mod.exports);
const React=require('react'),{createRoot}=require('react-dom/client'),root=createRoot(document.getElementById('root'));
(async()=>{
 root.render(React.createElement(mod.exports.VideoDirection,{shotId:'shot',prepare:async()=>{},changed:async()=>{}}));
 for(let i=0;i<50&&!document.body.textContent.includes('Visible:');i++)await new Promise(resolve=>setTimeout(resolve,10));
 assert(document.body.textContent.includes('Starting-frame observations'));
 assert(document.body.textContent.includes('Visible: closed hinged doors.'));assert(document.body.textContent.includes('Uncertain: left handle is obscured.'));
 assert.equal(document.getElementById('prompt').value,'Saved generation direction.','Observation display never modifies the generation prompt');
 assert(document.body.textContent.includes('Keep the left door closed.'));
 root.unmount();dom.window.close();console.log('Frame observations UI: visible facts, uncertainty, separate conflict notes and preserved generation prompt pass.');
})().catch(error=>{console.error(error);root.unmount();dom.window.close();process.exitCode=1;});
