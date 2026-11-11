// The human chooses the director and reviewer models; agents must use them (see AGENT_API.md).
(function(){
  const box=()=>document.getElementById('agentRoles');
  async function load(){
    const el=box();if(!el)return;
    try{
      const [roles,agreement]=await Promise.all([fetch('/api/roles').then(r=>r.json()),fetch('/api/reviewer-agreement').then(r=>r.json())]);
      for(const input of el.querySelectorAll('[data-role]')){
        const [role,key]=input.dataset.role.split('.');
        if(document.activeElement!==input)input.value=(roles[role]||{})[key]||'';
      }
      const name=r=>roles[r]?roles[r].model:'not chosen';
      el.querySelector('[data-roles-summary]').textContent=`· director ${name('director')} · reviewer ${name('reviewer')}`;
      el.querySelector('[data-agreement]').textContent=agreement.compared
        ?`The AI reviewer agreed with you on ${agreement.agreed} of ${agreement.compared} takes (stricter ${agreement.ai_stricter}, looser ${agreement.ai_looser}).`
        :'No takes compared yet.';
    }catch(_){/* the server may be restarting */}
  }
  async function save(){
    const el=box(),body={};
    for(const role of ['director','reviewer']){
      const model=el.querySelector(`[data-role="${role}.model"]`).value.trim(),product=el.querySelector(`[data-role="${role}.product"]`).value.trim();
      body[role]=model?{model,...(product?{product}:{})}:null;
    }
    try{
      const r=await fetch('/api/roles',{method:'POST',headers:{'Content-Type':'application/json','X-Tester':'local'},body:JSON.stringify(body)});
      const payload=await r.json();if(!r.ok)throw new Error(payload.error||'Could not save the models.');
      if(typeof window.toast==='function')window.toast('Models saved. Agents must use them from now on.');
      await load();
    }catch(error){if(typeof window.toast==='function')window.toast(error.message);}
  }
  function start(){const el=box();if(!el)return;el.querySelector('[data-roles-save]').onclick=save;load();setInterval(load,15000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
