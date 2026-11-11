// Human review pause: an agent-started video waits here until a person gives a verdict.
// The same verdict can arrive through the Agent API when the human works only through an agent.
(function(){
  const TAGS=[['bad_anatomy','Bad hands / face'],['off_model','Off-model'],['wrong_action','Wrong action'],
              ['flat_acting','Flat acting'],['continuity','Continuity'],['great','Great']];
  const box=()=>document.getElementById('humanReview');
  let current=null;
  function render(job){
    const el=box();if(!el)return;
    if(!job){current=null;el.hidden=true;return;}
    const changed=!current||current.id!==job.id;current=job;
    const failed=job.status!=='done';
    el.querySelector('[data-hr-text]').textContent=failed
      ?'The agent is paused: its last video generation failed. Read the error, then record your verdict.'
      :'The agent is paused until you review its latest video.';
    el.querySelector('[data-hr-error]').textContent=failed?(job.message||''):'';
    el.querySelector('[data-hr-show]').hidden=failed||!job.video;
    el.querySelector('[data-verdict="keep"]').disabled=failed;
    renderAI(el.querySelector('[data-hr-ai]'),job);
    if(changed){el.querySelector('[data-hr-notes]').value='';el.querySelector('[data-hr-usage]').value='';
      el.querySelectorAll('[data-hr-tag]').forEach(t=>t.setAttribute('aria-pressed','false'));}
    el.hidden=false;
  }
  const VERDICT={keep:'✓ Keep',retry:'↻ Retry',reject:'✗ Reject'};
  function renderAI(box,job){
    if(!box)return;const ai=job.ai_review;
    if(!ai){box.hidden=true;box.replaceChildren();return;}
    const add=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;e.textContent=text;return e;};
    const parts=[];
    if(ai.status==='unavailable'){parts.push(add('p','hint','AI reviewer could not run: '+ai.reason));}
    else{
      parts.push(add('p','hr-ai-head',`AI reviewer (${ai.reviewer.model}) suggests ${VERDICT[ai.suggestion]}`));
      parts.push(add('p','hint',Object.entries(ai.scores).map(([k,v])=>`${k} ${v}`).join(' · ')+(ai.summary?' — '+ai.summary:'')));
      const list=document.createElement('ul');
      for(const issue of [...ai.issues].sort((a,b)=>(a.severity==='blocking'?0:1)-(b.severity==='blocking'?0:1)))
        list.append(add('li','hr-issue '+issue.severity,`${issue.severity==='blocking'?'Blocking':'Polish'}${issue.time_s!=null?' at '+issue.time_s+' s':''}: ${issue.problem}${issue.fix?' → '+issue.fix:''}`));
      if(ai.issues.length)parts.push(list);
      const sheet=add('a','text-button','Open contact sheet');sheet.href=`/api/jobs/${job.id}/review-frames/contact-sheet.jpg`;sheet.target='_blank';sheet.rel='noopener';
      parts.push(sheet);
    }
    box.replaceChildren(...parts);box.hidden=false;
  }
  async function refresh(){
    try{
      const response=await fetch('/api/history');if(!response.ok)return;
      const jobs=await response.json();
      render(jobs.find(j=>(j.human_review||{}).status==='pending')||null);
    }catch(_){/* the server may be restarting; try again on the next tick */}
  }
  async function submit(verdict){
    if(!current)return;
    const el=box(),notes=el.querySelector('[data-hr-notes]').value.trim(),usageText=el.querySelector('[data-hr-usage]').value.trim();
    if(verdict!=='keep'&&!notes){toast?.(verdict==='retry'?'Say what to fix in the notes.':'Say why the shot does not work in the notes.');el.querySelector('[data-hr-notes]').focus();return;}
    const body={id:current.id,verdict,notes,tags:[...el.querySelectorAll('[data-hr-tag][aria-pressed="true"]')].map(t=>t.dataset.hrTag)};
    if(usageText)body.usage_after_percent=Number(usageText);
    const buttons=el.querySelectorAll('[data-verdict]');buttons.forEach(b=>b.disabled=true);
    try{
      const response=await fetch('/api/video/human-review',{method:'POST',headers:{'Content-Type':'application/json','X-Tester':'local'},body:JSON.stringify(body)});
      const payload=await response.json();
      if(!response.ok)throw new Error(payload.error||'Could not record the review.');
      toast?.({keep:'Kept. The agent may continue.',retry:'Retry noted. The agent may make one more take.',reject:'Rejected. The agent must rethink this shot.'}[verdict]);
      current=null;await refresh();
    }catch(error){toast?.(error.message);}
    finally{buttons.forEach(b=>b.disabled=false);if(current)render(current);}
  }
  function start(){
    const el=box();if(!el)return;
    const tags=el.querySelector('[data-hr-tags]');
    for(const [id,label] of TAGS){const b=document.createElement('button');b.type='button';b.className='hr-tag';b.dataset.hrTag=id;b.textContent=label;
      b.setAttribute('aria-pressed','false');b.onclick=()=>b.setAttribute('aria-pressed',b.getAttribute('aria-pressed')==='true'?'false':'true');tags.append(b);}
    el.querySelectorAll('[data-verdict]').forEach(b=>b.onclick=()=>submit(b.dataset.verdict));
    el.querySelector('[data-hr-show]').onclick=()=>{if(current&&current.video&&typeof showVideo==='function')showVideo(current.video,current.id);};
    refresh();setInterval(refresh,5000);
  }
  function toast(message){if(typeof window.toast==='function')window.toast(message);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
