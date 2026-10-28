async function accountFetch(url,options={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{return await fetch(url,{...options,signal:controller.signal});}
 catch(e){if(e.name==='AbortError')throw Error('Connection check timed out. Try again; no generation was sent.');throw e;}
 finally{clearTimeout(timer);}
}
let accountFeedback=null,accountReturnFocus=null,videoRecoveryKey='';
function renderAccount(state,offline=false){
 const failure=state?.phase==='error'?(state.message||state.auth_error||''):'';
 const recoveryKey=failure+'|'+(typeof studioView==='string'?studioView:'');
 if(window.ProviderRecovery&&document.getElementById('statusText')&&recoveryKey!==videoRecoveryKey){
  videoRecoveryKey=recoveryKey;let host=document.getElementById('videoProviderRecovery');
  if(!host){host=document.createElement('div');host.id='videoProviderRecovery';document.getElementById('statusText').parentElement.after(host);}
  window.ProviderRecovery.mount(host,{message:failure,model:'grok-imagine-image-2.0'});
  if(typeof studioView==='string'&&studioView!=='video')host.hidden=true;
 }
 window.studioGrokConnection={connected:state?.signed_in===true&&!offline,pending:['connecting','waiting'].includes(state?.auth_status),offline};
 window.dispatchEvent(new CustomEvent('studio-grok-connection',{detail:window.studioGrokConnection}));
  const v=AccountFlow.view(state,offline);accountFeedback=v;
  $('accountFeedback').dataset.state=v.kind;$('accountStatus').textContent=v.title;$('accountNextStep').textContent=v.message;
  $('accountIndicator').textContent=v.connected?'✓':v.pending?'↻':v.kind==='error'||v.kind==='offline'?'!':'✦';
  $('accountContinue').hidden=!v.canContinue;$('login').hidden=v.connected;
  $('login').disabled=!v.canLogin||['generating','pending'].includes(state?.phase);
  $('login').textContent=v.pending?'Waiting for sign-in…':v.kind==='error'?'Try sign-in again':state?.mock?'Connect mock account':'Sign in with Grok via Hermes';
  $('accountReconnect').hidden=!v.connected;$('accountReconnect').disabled=['generating','pending'].includes(state?.phase);
  $('accountCheck').disabled=false;$('accountCheck').textContent=v.pending?'Check approval status':'Check model access';
  $('accountSteps').hidden=!v.pending;
  const link=state?.verification_url,code=state?.user_code;let validURL;
  try{const url=new URL(link);if(url.protocol==='https:'&&['accounts.x.ai','auth.x.ai'].includes(url.hostname))validURL=url.href;}catch{}
  $('authbox').hidden=!v.pending||!validURL||!code;
  $('userCode').textContent=v.pending&&code?code:'';
  if(v.pending&&validURL)$('authLink').href=validURL;else $('authLink').removeAttribute('href');
  const left=Math.max(0,Math.ceil((state?.auth_expires_at||0)-Date.now()/1000));
  $('accountExpiry').textContent=v.pending&&left?'Approval window: '+Math.ceil(left/60)+' minute'+(left>60?'s':'')+' remaining.':'';
  $('accountOpen').textContent=v.connected?'Grok sign-in saved':'Account';
  $('accountOpen').dataset.connected=String(v.connected);$('accountOpen').setAttribute('aria-label',v.connected?'Grok sign-in saved · Manage account':'Account');
}
function closeAccountFlow(){
 $('account').close();
 if(accountReturnFocus?.isConnected){accountReturnFocus.focus({preventScroll:true});accountReturnFocus=null;return;}
  const input=studioView==='image'?$('imagePrompt'):studioView==='story'?($('storySceneEditor').hidden?$('storyEpisodeTitle'):$('storySceneText')):$('prompt');
  input?.focus({preventScroll:true});
}
async function startAccountLogin(){
  $('accountActionError').textContent='';renderAccount({...account,signed_in:false,auth_status:'connecting'});
  try{await api('/api/login',{});await poll();}catch(e){$('accountActionError').textContent=e.message;await poll();}
}
function initAccountFlow(){
 initCodexReconnectRequests();
 window.addEventListener('studio-reconnect-provider',event=>{
  if(event.detail?.provider==='grok'){accountReturnFocus=document.activeElement;$('account').showModal();void startAccountLogin();}
  else void openChatGPTImageConnection();
 });
 window.addEventListener('studio-manage-image-provider',event=>{if(event.detail?.provider==='grok'){accountReturnFocus=document.activeElement;$('account').showModal();poll();}else void openChatGPTImageConnection(false);});
 window.addEventListener('studio-manage-grok',()=>{accountReturnFocus=document.activeElement;$('account').showModal();poll();});
  $('accountOpen').onclick=()=>{$('account').showModal();poll();};
  $('closeAccount').onclick=closeAccountFlow;$('accountContinue').onclick=closeAccountFlow;
  $('login').onclick=startAccountLogin;$('accountReconnect').onclick=startAccountLogin;
  $('accountCheck').onclick=async()=>{$('accountCheck').disabled=true;$('accountActionError').textContent='';try{if(!accountFeedback?.pending){const verified=await window.ProviderRecovery.check('grok');await poll();$('accountNextStep').textContent=verified?'Model access verified. Image generation has not been verified.':'Model access was not verified. Finish sign-in, then check again.';}else await poll();}catch(e){$('accountActionError').textContent=e.message;}finally{$('accountCheck').disabled=false;}};
  window.addEventListener('focus',()=>poll());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
}
async function openChatGPTImageConnection(startSignIn=true,reconnectRequestId=null){
 let dialog=document.getElementById('chatGPTImageConnection');
 if(!dialog){dialog=document.createElement('dialog');dialog.id='chatGPTImageConnection';dialog.className='account-dialog';dialog.setAttribute('aria-labelledby','chatGPTImageConnectionTitle');dialog.innerHTML='<div class="heading-row"><h2 id="chatGPTImageConnectionTitle">ChatGPT image connection</h2><button type="button" data-close aria-label="Close ChatGPT connection">×</button></div><p>Reconnect the ChatGPT account used for Image 2. Your Studio workspace and saved work stay here.</p><p class="hint">Personal mode uses this Mac’s shared Codex login. Private workspaces keep a separate connection.</p><div data-state role="status" aria-live="polite"></div><p><a data-link target="_blank" rel="noopener noreferrer" hidden>Open ChatGPT sign-in ↗</a></p><code data-code hidden></code><div class="provider-recovery-actions"><button data-start>Start sign-in ↗</button><button data-check>Check connection</button><button data-close>Return to image</button></div>';document.body.append(dialog);}
 dialog.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>dialog.close());
 const status=dialog.querySelector('[data-state]'),link=dialog.querySelector('[data-link]'),code=dialog.querySelector('[data-code]'),start=dialog.querySelector('[data-start]'),check=dialog.querySelector('[data-check]');
 async function fetchAccount(method='GET',path=''){const r=await accountFetch('/api/studio-account'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-Tester':'local',...(window.studioWorkspaceId?{'X-Workspace-ID':window.studioWorkspaceId}:{})},...(method==='POST'?{body:JSON.stringify(reconnectRequestId?{request_id:reconnectRequestId}:{})}:{})});const value=await r.json();if(!r.ok)throw Error(value.error?.message||'Sign-in unavailable.');return value;}
 function render(auth){link.hidden=true;code.hidden=true;const waiting=['connecting','waiting'].includes(auth?.status);start.disabled=waiting;start.textContent=waiting?'Waiting for sign-in…':'Start sign-in ↗';if(auth?.url){try{const url=new URL(auth.url);if(url.protocol==='https:'&&url.hostname==='auth.openai.com'){link.href=url.href;link.hidden=false;}}catch{}}
  if(auth?.code){code.textContent=auth.code;code.hidden=false;}status.textContent=auth?.status==='connected'?'Sign-in complete. Return to the image and check the connection before retrying.':auth?.error|| (waiting?'Open ChatGPT sign-in and enter the code shown here.':'Start sign-in to renew your image connection.');}
 start.onclick=async()=>{start.disabled=true;status.textContent='Starting sign-in…';try{render(await fetchAccount('POST','/codex'));}catch(e){status.textContent=e.message;start.disabled=false;}};
 check.onclick=async()=>{check.disabled=true;status.textContent='Checking connection…';try{const value=await fetchAccount();render(value.auth?.kind==='codex'?value.auth:null);const connected=await window.ProviderRecovery.check('codex');status.textContent=connected?'ChatGPT connected. Return to your image to retry when ready.':'ChatGPT connection could not be verified. Finish sign-in, then check again.';}catch(e){status.textContent=e.message;}finally{check.disabled=false;}};
 dialog.showModal();render(null);
 const timer=setInterval(async()=>{if(!dialog.open){clearInterval(timer);return;}try{const state=await fetchAccount();if(state.auth?.kind==='codex')render(state.auth);}catch{}},1500);
 if(startSignIn)await start.onclick();else{try{const value=await fetchAccount();render(value.auth?.kind==='codex'?value.auth:null);const state=await accountFetch('/api/agent/image-studio/openai-account',{credentials:'same-origin'}).then(r=>r.json());status.textContent=state.subscription?.signed_in?'ChatGPT sign-in saved. Image generation and available quota are not verified.':'Sign in to connect ChatGPT images. Your saved work stays here.';}catch{status.textContent='Connection status unavailable. Try Check connection.';}}
}

function initCodexReconnectRequests(){
 if(document.getElementById('codexReconnectRequest'))return;
 const notice=document.createElement('aside');notice.id='codexReconnectRequest';notice.className='provider-recovery codex-reconnect-request';notice.hidden=true;notice.setAttribute('aria-label','ChatGPT reconnect request');
 notice.innerHTML='<strong>ChatGPT reconnection requested</strong><p data-message role="status" aria-live="polite"></p><button type="button">Start sign-in ↗</button>';
 document.body.append(notice);let pending=null,loading=false;
 notice.querySelector('button').onclick=async()=>{if(!pending)return;notice.hidden=true;await openChatGPTImageConnection(true,pending.id);await refresh();};
 async function refresh(){
  if(loading||document.hidden)return;loading=true;
  try{
   const response=await accountFetch('/api/studio-account/codex',{credentials:'same-origin',headers:window.studioWorkspaceId?{'X-Workspace-ID':window.studioWorkspaceId}:{}});
   if(!response.ok)throw Error('Request unavailable');
   pending=await response.json();
   const visible=(pending.status==='pending'&&pending.step==='human_start')||pending.status==='error';
   notice.hidden=!visible||!!document.querySelector('#chatGPTImageConnection[open]');
   notice.querySelector('[data-message]').textContent=pending.status==='error'?pending.error:'Your agent is waiting for you to reconnect ChatGPT. Your work stays saved.';
   notice.querySelector('button').textContent=pending.status==='error'?'Try sign-in again ↗':'Start sign-in ↗';
   const host=document.querySelector('dialog[open]:not(#chatGPTImageConnection)')||document.body;if(notice.parentElement!==host)host.append(notice);
  }catch{pending=null;notice.hidden=true;}finally{loading=false;}
 }
 window.addEventListener('focus',refresh);document.addEventListener('visibilitychange',refresh);
 const timer=setInterval(refresh,3000);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});void refresh();
}

// Reconnect requests remain visible even when no media studio was initialized.
window.addEventListener('DOMContentLoaded',initCodexReconnectRequests,{once:true});
