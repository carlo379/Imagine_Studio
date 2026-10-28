// Actual review dialog with local evidence and API fixtures; no provider calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<button id="generate">Generate video</button><button id="previous">Previous</button><video id="video"></video><button id="reviewVideoPrompt">Review against prompt</button>',{url:'http://test.invalid/',runScripts:'outside-only',pretendToBeVisual:true}),win=dom.window;
win.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
win.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new win.Event('close'));};
win.HTMLMediaElement.prototype.pause=function(){};
win.HTMLMediaElement.prototype.load=function(){};
win.structuredClone=structuredClone;
const model='grok-imagine-video-1.5',sceneId='s'.repeat(32),jobId='a'.repeat(32),reviewId='b'.repeat(32),lessonId='c'.repeat(32),childId='d'.repeat(32),originId='e'.repeat(32);
const take={id:jobId,status:'done',video:'https://fixture.invalid/video',settings:{model,duration:5,resolution:'720p',_studio_video_id:sceneId}};
let scene={id:sceneId,title:'Reveal',revision:2,scene:{prompt:'Original direction.'}},reviews=[],lessons=[],version=0,stale=false,suggested=null;
const report=()=>({id:reviewId,revision:2,status:'done',created_at:1,video_job_id:jobId,scene_id:sceneId,model,
 snapshot:{source:'exact',draft_prompt:'Original direction.',request:{model,prompt:'Submitted expanded prompt.'}},
 evidence:{duration:5,audio_present:true,frames:[{id:'frame-0',time_seconds:0,src:'/api/video-review/evidence/'+reviewId+'/frame-0'}],references:[],limitations:['Sampled stills; speech unverified.']},
 result:{summary:'Visible mismatch.',overall:'failed',requirements:[{id:'identity',category:'identity',requirement:'Reference body',status:'failed',observation:'Wrong silhouette.',evidence_ids:['frame-0'],timestamps:[0],confidence:'high'}],hypotheses:[],revised_prompt:'Proposed direction.',changes:[{finding_ids:['identity'],before:'Original',after:'Proposed',reason:'Bind identity.'}],comparison:{summary:'',improved_ids:[],regressed_ids:[],uncertain_ids:[]},lesson_candidates:[]}});
const calls=[],response=(body,ok=true)=>({ok,json:async()=>structuredClone(body)});
win.fetch=async(url,options={})=>{
 const method=options.method||'GET',body=options.body?JSON.parse(options.body):null;calls.push({url,method,body,headers:options.headers});
 if(url==='/api/video-review/schema')return response({ffmpeg_available:true});
 if(url.startsWith('/api/video-review?'))return response({reviews,suggested_previous_review_id:suggested});
 if(url==='/api/video-review/lessons/model/'+model)return response({lessons,guide_version:version});
 if(url==='/api/video-review'&&method==='POST'){reviews=[report()];return response(reviews[0]);}
 if(url==='/api/video-review/'+reviewId+'/apply'){
  if(stale)return response({error:{message:'The video draft changed. Newer edits preserved.'}},false);
  scene={...scene,revision:3,scene:{prompt:body.prompt}};reviews[0]={...reviews[0],revision:3,applied_scene_revision:3};return response({scene,review:reviews[0]});
 }
 if(url==='/api/video-review/'+reviewId+'/outcome'){
  reviews[0]={...reviews[0],revision:4,outcome:{assessment:body.assessment,successful:body.assessment==='successful',confirmed_finding_ids:body.confirmed_finding_ids},lesson_proposal_id:lessonId};
  lessons=[{id:lessonId,revision:1,status:'proposed',model,guidance:'A concise observed lesson.',rationale:'Human confirmed.',evidence:[{review_id:reviewId,video_job_id:jobId}],confidence:'tentative'}];return response(reviews[0]);
 }
 if(url==='/api/video-review/'+reviewId+'/refine'){
  const child={...structuredClone(reviews.find(r=>r.id===reviewId)),id:childId,revision:1,created_at:3,kind:'refinement',parent_review_id:reviewId,preserve_finding_ids:body.preserve_finding_ids,outcome:null,lesson_proposal_id:null};
  child.result.revised_prompt='Focused revised direction.';reviews.unshift(child);return response({...child,status:'pending',stage:'refining',result:null,evidence:null});
 }
 if(url==='/api/video-review/'+childId&&method==='GET')return response(reviews.find(r=>r.id===childId));
 if(url==='/api/video-review/lessons/'+lessonId+'/approve'){
  lessons=[{...lessons[0],revision:2,status:'active'}];version=1;return response({lesson:lessons[0],guide_version:version});
 }
 throw Error('Unexpected request '+method+' '+url);
};
win.fixtureTake=take;win.fixtureScene=scene;

win.sceneAPI=async()=>structuredClone(scene);win.applyScene=value=>{win.fixtureApply(value);};win.toast=()=>{};
win.eval('let history=[fixtureTake],frameJob=fixtureTake.id,sceneRecord=fixtureScene,project=fixtureScene.scene,sceneDirty=false,sceneSaving=false,sceneConflict=false; window.fixtureApply=value=>{sceneRecord=value;project=value.scene;};\n'+fs.readFileSync('static/video-review.js','utf8'));
const button=text=>{const names={'Next prompt':'3 · Review prompt','Use this prompt for the shot':'Save prompt & return to Generate →'};if(text==='Learnings')return {click:()=>{win.document.querySelector('[data-section=learning]').open=true;}};return [...win.document.querySelectorAll('button')].find(b=>text==='Refine these issues'?b.textContent.startsWith('Prepare prompt for'):b.textContent===(names[text]||text));};
async function until(check){for(let i=0;i<300&&!check();i++)await new Promise(r=>setTimeout(r,10));assert(check(),'Expected review UI state');}
(async()=>{
 win.VideoReview.sync();assert.equal(win.document.getElementById('reviewVideoPrompt').hidden,false);
 win.document.getElementById('previous').focus();await win.VideoReview.open(jobId);
 assert(calls.every(c=>c.method==='GET'),'Opening never authorizes review');
 button('Review this video').click();await until(()=>win.document.body.textContent.includes('Visible mismatch.'));
 const start=calls.find(c=>c.url==='/api/video-review'&&c.method==='POST');
 assert.equal(start.body.approved,true);assert.equal(start.body.previous_review_id,null);assert(start.headers['Idempotency-Key']);
 assert([...win.document.querySelectorAll('img')].some(i=>i.src.includes('/api/video-review/evidence/')));
 assert(win.document.body.textContent.includes('speech unverified'));
 assert.equal(win.document.querySelector('#videoReviewPanel-fixes').hidden,false,'Completed review advances to Choose fixes');
 assert.equal(win.document.querySelector('#videoReviewPanel-watch').hidden,true);
 assert.equal(win.document.querySelector('[data-section=history]').open,false,'History stays secondary');
 const fix=win.document.querySelector('.vr-fix-choices input');fix.click();assert.equal(button('Refine these issues').disabled,true,'No selected fix or extra instruction');fix.click();
 const writingCalls=calls.filter(c=>c.method==='POST').length;button('Refine these issues').click();await until(()=>!button('Next prompt').disabled);assert.equal(calls.filter(c=>c.method==='POST').length,writingCalls,'Default selections reuse the prepared proposal without another AI request');
 button('Next prompt').click();const prompt=win.document.querySelector('[aria-label="Revised video prompt"]');
 assert.equal(prompt.value,'Proposed direction.');prompt.value='Edited proposed direction.';prompt.dispatchEvent(new win.Event('input'));
 stale=true;button('Use this prompt for the shot').click();await until(()=>win.document.body.textContent.includes('Newer edits preserved'));
 assert.equal(scene.scene.prompt,'Original direction.');assert.equal(prompt.value,'Edited proposed direction.');
 stale=false;button('Use this prompt for the shot').click();await until(()=>scene.revision===3&&!win.document.querySelector('.video-review-dialog'));assert.equal(win.document.activeElement.id,'generate');
 const apply=calls.find(c=>c.url.endsWith('/apply'));assert.equal(apply.body.expected_scene_revision,2);assert.equal(apply.body.expected_review_revision,2);assert.equal(apply.body.expected_scene_prompt,'Original direction.');
 // Supply a result with one met finding and one remaining failure.
 reviews[0].result.requirements.push({id:'door',category:'action',requirement:'Hinged door at reveal',status:'met',observation:'Correctly open in sampled frame.',evidence_ids:['frame-0'],timestamps:[0],confidence:'high'});
 reviews[0].result.lesson_candidates=[{finding_ids:['door'],guidance:'Keep the hinge action.',rationale:'Visible improvement.'}];
 await win.VideoReview.open(jobId);
 button('Learnings').click();assert.equal(button('Improved, but needs work').disabled,true);
 const confirm=win.document.querySelector('#videoReviewPanel-learning .vr-finding-choice input');
 assert(confirm);assert.equal(confirm.value,'door');assert.equal(confirm.checked,false);
 confirm.click();assert.equal(button('Improved, but needs work').disabled,false);
 button('Improved, but needs work').click();await until(()=>button('Add to prompting guide'));
 const outcome=calls.find(c=>c.url.endsWith('/outcome'));assert.equal(outcome.body.assessment,'improved');assert.deepEqual(outcome.body.confirmed_finding_ids,['door']);assert.equal(outcome.body.candidate_index,0);
 assert.equal(version,0,'Success confirmation does not change the guide');
 const guidance=win.document.querySelector('[aria-label="Lesson guidance to approve"]');assert.equal(guidance.maxLength,1200);
 button('Add to prompting guide').click();await until(()=>version===1&&!button('This take is successful').disabled);
 const approve=calls.find(c=>c.url.endsWith('/approve'));assert.equal(approve.body.expected_guide_version,0);assert.equal(approve.body.approved,true);
 assert.equal(button('Next prompt').disabled,true);assert.equal(button('Refine these issues').disabled,false,'Selected fixes can prepare without extra typing');
 const preserved=win.document.querySelector('.vr-refinement input[type="checkbox"]');assert.equal(preserved.value,'door');assert.equal(preserved.checked,true);
 const remaining=win.document.querySelector('[aria-label="Remaining video issues to refine"]');remaining.value='Fix the final glance at 0:04.';remaining.dispatchEvent(new win.Event('input'));
 button('Refine these issues').click();await until(()=>win.document.querySelector('[aria-label="Revised video prompt"]')?.value==='Focused revised direction.');
 const refinement=calls.find(c=>c.url.endsWith('/refine'));assert.equal(refinement.body.approved,true);assert(refinement.body.notes.includes('Fix the final glance at 0:04.'));assert(refinement.body.notes.includes('identity: Reference body'));assert.deepEqual(refinement.body.preserve_finding_ids,['door']);assert(refinement.headers['Idempotency-Key']);
 assert.equal(scene.scene.prompt,'Edited proposed direction.','Refinement is not applied automatically');assert.equal(version,1);
 assert.equal(win.document.querySelector('.vr-refinement input[type="checkbox"]').checked,true,'Child retains preservation choices');
 assert(!calls.some(c=>c.url==='/api/video'||c.url.includes('/generate')),'No review action generates media');
 win.document.querySelector('[aria-label="Close video review"]').click();assert.equal(win.document.activeElement.id,'generate');
 reviews=[{...report(),id:originId,video_job_id:'f'.repeat(32),created_at:0}];suggested=originId;
 await win.VideoReview.open(jobId);
 const previous=win.document.querySelector('[aria-label="Previous video review"]');
 assert(previous,'Comparison selector available');assert.equal(previous.value,originId);
 previous.value='';previous.dispatchEvent(new win.Event('change'));
 button('Review this video').click();await until(()=>calls.filter(c=>c.url==='/api/video-review'&&c.method==='POST').length===2);
 assert.equal(calls.filter(c=>c.url==='/api/video-review'&&c.method==='POST')[1].body.previous_review_id,null);
 win.document.querySelector('[aria-label="Close video review"]').click();
 console.log('Video review UI: guarded apply, partial improvement confirmation, lesson approval, focused refinement with preserved findings, originating review suggestion, standalone override and no automatic generation pass.');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
