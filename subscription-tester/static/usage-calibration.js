// Learn what Grok video costs: the human reads Settings → Usage before and after each take
// until Studio has a stable % per second for each resolution. Same data as the Agent API.
(function(){
  const $=id=>document.getElementById(id);
  const dismissed=new Set();let calibration=null,pending=null;
  const pct=n=>Number(n).toLocaleString(undefined,{maximumFractionDigits:3});
  function describe(){
    const note=$('usageCalibrationNote');if(!note||!calibration)return;
    const parts=Object.entries(calibration.resolutions).map(([res,c])=>c.established
      ?`${res}: ~${pct(c.percent_per_second)}% per second (~${pct(c.estimate_percent['5'])}% for 5 s)`
      :`${res}: learning, ${c.clean_samples} of ${c.clean_samples+c.samples_needed} samples`);
    note.textContent='Grok cost per take, from your Usage readings. '+parts.join(' · ');
    const resolution=$('resolution')?.value,input=$('usageBefore');
    if(input){const needed=resolution&&calibration.resolutions[resolution]&&!calibration.resolutions[resolution].established;
      input.placeholder=needed?'Needed':'Optional';}
  }
  function renderAfter(){
    const box=$('usageAfter');if(!box)return;
    if(!pending){box.hidden=true;return;}
    box.querySelector('[data-ua-text]').textContent=`Your last ${pending.settings?.resolution||''} take (${pending.settings?.duration||'?'} s) has finished. `
      +`Open Grok Settings → Usage and enter the % now, so Studio learns what it cost (it was ${pct(pending.usage.before)}% before).`;
    box.hidden=false;
  }
  async function refresh(){
    try{
      const [jobs,cal]=await Promise.all([fetch('/api/history').then(r=>r.json()),fetch('/api/usage-calibration').then(r=>r.json())]);
      calibration=cal;describe();
      // Agent takes waiting for a verdict collect the after reading in the review banner instead.
      pending=jobs.find(j=>j.usage&&j.usage.before!=null&&j.usage.after==null&&!j.usage.unavailable&&j.status!=='pending'
        &&(j.human_review||{}).status!=='pending'&&!dismissed.has(j.id))||null;
      renderAfter();
    }catch(_){/* the server may be restarting */}
  }
  async function save(){
    const box=$('usageAfter'),value=box.querySelector('[data-ua-value]').value.trim();
    if(!pending||value==='')return;
    try{
      const response=await fetch('/api/video/usage',{method:'POST',headers:{'Content-Type':'application/json','X-Tester':'local'},body:JSON.stringify({id:pending.id,usage_after_percent:Number(value)})});
      const payload=await response.json();if(!response.ok)throw new Error(payload.error||'Could not save the reading.');
      box.querySelector('[data-ua-value]').value='';if(typeof window.toast==='function')window.toast('Usage reading saved.');
      await refresh();
    }catch(error){if(typeof window.toast==='function')window.toast(error.message);}
  }
  window.UsageCalibration={
    takeBeforeReading(){const input=$('usageBefore');if(!input||input.value.trim()==='')return null;
      const value=Number(input.value);input.value='';return {usage_before_percent:value};},
    refresh};
  function start(){
    const box=$('usageAfter');if(box){box.querySelector('[data-ua-save]').onclick=save;
      box.querySelector('[data-ua-dismiss]').onclick=()=>{if(pending)dismissed.add(pending.id);pending=null;renderAfter();};}
    $('resolution')?.addEventListener('change',describe);
    refresh();setInterval(refresh,5000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
