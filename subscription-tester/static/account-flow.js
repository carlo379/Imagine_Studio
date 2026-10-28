/* Shared, testable account feedback. Authentication and credentials stay on the server. */
(function(root){
  function view(state={},offline=false){
    const connected=state.signed_in===true;
    const phase=state.auth_status||(connected?'connected':['connecting','waiting'].includes(state.phase)?state.phase:'disconnected');
    const pending=!connected&&['connecting','waiting'].includes(phase);
    if(offline)return {kind:'offline',title:'Connection status unavailable',message:'The local server could not be reached. Check again before generating.',connected:false,pending:false,canLogin:false,canContinue:false};
    if(connected)return {kind:'connected',title:state.mock?'Mock account connected':'Grok sign-in saved',message:'Your sign-in is saved. Check model access to verify it with Grok. This does not verify image generation.',connected:true,pending:false,canLogin:true,canContinue:true};
    if(pending)return {kind:phase,title:phase==='waiting'?'Waiting for xAI approval':'Starting Grok sign-in…',message:phase==='waiting'?'Finish signing in and approving Hermes access on the xAI page. This dialog updates automatically when approval is received.':'Preparing the secure xAI sign-in page. Keep this dialog open, or return to it later.',connected:false,pending:true,canLogin:false,canContinue:false};
    if(phase==='error')return {kind:'error',title:'Sign-in did not complete',message:state.auth_error||'Approval may have expired or been denied. Try signing in again.',connected:false,pending:false,canLogin:true,canContinue:false};
    return {kind:'disconnected',title:'Connect your Grok subscription',message:'Sign in on xAI’s page, then return here. We’ll confirm the connection and guide you back to creating.',connected:false,pending:false,canLogin:true,canContinue:false};
  }
  root.AccountFlow={view};if(typeof module!=='undefined')module.exports=root.AccountFlow;
})(typeof window!=='undefined'?window:globalThis);
