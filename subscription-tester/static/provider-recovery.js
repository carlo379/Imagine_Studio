/* Provider recovery never switches workspaces or automatically retries generation. */
(()=>{
 function classify(message,model,kind){
  const text=String(message||'');
  const provider=/codex|chatgpt/i.test(text)?'codex':/grok|xai/i.test(text)||String(model).startsWith('grok')?'grok':'codex';
  if(/quota|allowance|rate.?limit|usage limit|exhausted|out of.*token|429|402/i.test(text))return {provider,kind:'usage'};
  if(provider==='grok'&&(kind==='upstream_auth_context'||/HTTP 5\d\d/i.test(text)))return {provider,kind:'other'};
  if(kind==='authentication_expired'||/auth(?:entication)? context|expired.*(?:auth|sign.in|token)|sign.in.*(?:required|before|with)|connect (?:grok|chatgpt)|reconnect|unauthorized|401|not logged in/i.test(text))return {provider,kind:'auth'};
  return {provider,kind:'other'};
 }
 async function request(path,method='GET'){
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),60000);
  try{const r=await fetch(path,{method,signal:controller.signal,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Tester':'local'},...(method==='POST'?{body:'{}'}:{})});const data=await r.json();if(!r.ok)throw Error(data.error?.message||'Connection check failed.');return data;}catch(e){if(e.name==='AbortError')throw Error('Connection check timed out. Try checking again; no generation was sent.');throw e;}finally{clearTimeout(timer);}
 }
 async function check(provider){
  if(provider==='grok'){const state=await request('/api/grok/check','POST');return state.signed_in===true;}
  const workspace=await request('/api/studio-account');
  if(workspace.auth?.kind==='codex'&&workspace.auth.status!=='connected')return false;
  const state=await request('/api/agent/image-studio/openai-account/refresh','POST');return state.subscription?.signed_in===true;
 }
 function mount(host,{message,model,kind,retry,disabled=false}){
  const failure=classify(message,model,kind);host.replaceChildren();host.hidden=failure.kind!=='auth';if(host.hidden)return;
  let verified=false;host.className='provider-recovery';
  const label=document.createElement('strong'),note=document.createElement('p'),actions=document.createElement('div'),reconnect=document.createElement('button'),verify=document.createElement('button'),again=document.createElement('button'),status=document.createElement('span');
  label.textContent='Reconnect '+(failure.provider==='grok'?'Grok':'ChatGPT')+' to continue';note.textContent='Your images, approvals and descriptions stay saved.';actions.className='provider-recovery-actions';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  reconnect.textContent='Reconnect '+(failure.provider==='grok'?'Grok':'ChatGPT')+' ↗';verify.textContent=failure.provider==='grok'?'Check model access':'Check connection';again.textContent='Retry this image · 1 request';again.hidden=true;
  reconnect.onclick=()=>{verified=false;again.hidden=true;verify.disabled=false;status.textContent='Finish sign-in, then check your connection here.';window.dispatchEvent(new CustomEvent('studio-reconnect-provider',{detail:{provider:failure.provider}}));};
  verify.onclick=async()=>{verify.disabled=true;status.textContent=failure.provider==='grok'?'Checking model access…':'Checking connection…';try{verified=await check(failure.provider);status.textContent=verified?(failure.provider==='grok'?'Model access verified. Image generation has not been verified.':'Connected. Retry when ready.'):'Not connected yet. Finish sign-in, then check again.';again.hidden=!verified||!retry;again.disabled=disabled;}catch(e){status.textContent=e.message;}finally{verify.disabled=false;}};
  again.onclick=async()=>{if(!verified||disabled)return;again.disabled=true;try{await retry();status.textContent='Retry requested. Check the generation status. No automatic retries.';}catch(e){status.textContent=e.message;}finally{again.disabled=disabled;}};
  reconnect.disabled=disabled;verify.disabled=true;actions.append(reconnect,verify,again);host.append(label,note,actions,status);
 }
 window.ProviderRecovery={classify,check,mount,request};
})();
