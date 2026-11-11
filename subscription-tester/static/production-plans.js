// Production plans: the agent proposes the shots, takes and budget; the human approves once here
// (or tells their agent, which relays the approval through the Agent API).
(function(){
  const $=id=>document.getElementById(id);
  const STATE={not_started:'Not started',in_progress:'In progress',awaiting_review:'Waiting for your review',retry:'Retry requested',
               rejected:'Rejected — needs a new idea',kept:'Kept ✓',takes_used_up:'Takes used up'};
  const pct=n=>n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:2})+'%';
  const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;};
  let last='';
  async function post(path,body,message){
    try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Tester':'local'},body:JSON.stringify(body)});
      const payload=await r.json();if(!r.ok)throw new Error(payload.error||'Request failed.');
      if(typeof window.toast==='function')window.toast(message);last='';await refresh();}
    catch(error){if(typeof window.toast==='function')window.toast(error.message);}
  }
  function card(plan){
    const c=el('article','plan-card'+(plan.approved?' approved':''));
    const head=el('div','plan-head');
    head.append(el('strong',null,plan.title),el('span','pill'+(plan.approved?'':' muted'),plan.approved?'Approved':plan.status==='closed'?'Closed':'Needs your approval'));
    c.append(head);
    if(plan.notes)c.append(el('p','hint',plan.notes));
    const t=plan.totals;
    const cap=t.usage_percent_cap!=null?` of ${pct(t.usage_percent_cap)} budget`:'';
    c.append(el('p','plan-totals',`${t.shots} shots · ${t.shots_kept} kept · ${t.takes_used} of ${t.max_takes} takes used · `
      +`estimated ${pct(t.estimate_percent_expected)} (worst case ${pct(t.estimate_percent_worst_case)}) · spent ${pct(t.usage_percent_spent)}${cap}`));
    if(t.shots_kit_ready!==undefined)c.append(el('p','hint',`Shot kits ready: ${t.shots_kit_ready} of ${t.shots}. Each shot needs 3D staging, approved first frame (and last frame when it has an end state) and a clean prompt before approval.`));
    if(t.shots_without_estimate)c.append(el('p','hint',`${t.shots_without_estimate} shot(s) have no cost estimate yet: Studio is still learning that resolution's cost.`));
    const list=el('ol','plan-items');
    for(const item of plan.items){
      const li=el('li');
      li.append(el('span','plan-item-label',item.label||item.title||item.scene_id),
        el('span','plan-item-meta',`${item.resolution||'?'} · ${item.duration||'?'} s · ${item.takes_used}/${item.max_takes} takes · ${item.estimate_percent_per_take==null?'no estimate yet':pct(item.estimate_percent_per_take)+' per take'}`),
        el('span','plan-item-state state-'+item.state,STATE[item.state]||item.state));
      const kit=item.kit||{checks:[]},failed=kit.checks.filter(c=>!c.ok);
      li.append(el('span','plan-kit '+(kit.ready?'ready':'missing'),kit.ready?'Shot kit ready ✓':'Shot kit missing: '+failed.map(c=>c.label.split(' (')[0]).join(' · ')));
      for(const hint of kit.hints||[])li.append(el('span','plan-kit hint-warn','⚠ '+hint));
      list.append(li);
    }
    c.append(list);
    const actions=el('div','human-review-actions');
    if(!plan.approved&&plan.status!=='closed'){
      const approve=el('button','primary','Approve plan');approve.type='button';
      if(t.shots_kit_ready!==undefined&&t.shots_kit_ready<t.shots){approve.disabled=true;approve.title='Every shot kit must be ready first.';}
      approve.onclick=()=>post(`/api/plans/${plan.id}/approve`,{expected_revision:plan.revision},'Plan approved. The agent may generate these shots.');
      actions.append(approve);
    }
    if(plan.status!=='closed'){
      const close=el('button','secondary','Close plan');close.type='button';
      close.onclick=()=>post(`/api/plans/${plan.id}/close`,{expected_revision:plan.revision},'Plan closed. No more generation under it.');
      actions.append(close);
    }
    c.append(actions);
    return c;
  }
  async function refresh(){
    const box=$('productionPlans');if(!box)return;
    try{
      const plans=(await fetch('/api/plans').then(r=>r.json())).filter(p=>p.status!=='closed');
      const signature=JSON.stringify(plans);if(signature===last)return;last=signature;
      const list=box.querySelector('[data-plans]');list.replaceChildren(...plans.map(card));
      box.hidden=!plans.length;
    }catch(_){/* the server may be restarting */}
  }
  function start(){refresh();setInterval(refresh,5000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
