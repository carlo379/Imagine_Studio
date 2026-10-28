/* One owner-scoped change monitor; hidden tools never start their own poll loop. */
(() => {
  const reads=new Map(), subscribers=new Set();
  let timer=null, checking=false, retry=2500, lastStatus=null;
  async function json(url, options={}) {
    const method=(options.method||'GET').toUpperCase();
    if(method!=='GET')return read(url,options);
    const key=url;
    if(!reads.has(key))reads.set(key,read(url,options).finally(()=>reads.delete(key)));
    // Draft consumers may edit their copy; never share a mutable response object.
    return structuredClone(await reads.get(key));
  }
  async function read(url,options) {
    const response=await fetch(url,options),value=await response.json();
    if(!response.ok){const error=Error(value.error?.message||value.error||'Studio request failed.');error.code=value.error?.code;error.status=response.status;throw error;}
    return value;
  }
  function schedule(delay=2500){clearTimeout(timer);if(subscribers.size)timer=setTimeout(check,delay);}
  async function check(force=false){
    if(checking)return;
    if(document.hidden||![...subscribers].some(s=>s.active())){schedule();return;}
    checking=true;
    try{
      lastStatus=await json('/api/agent/workspace/status');retry=2500;
      await Promise.allSettled([...subscribers].map(async s=>{
        if(s.running||!s.active())return;
        const stamp=JSON.stringify(s.areas.map(k=>lastStatus.areas[k]));
        if(!force&&s.seen===stamp)return;
        if(s.seen===undefined&&!s.initial&&!force){s.seen=stamp;return;}
        s.running=true;
        try{await s.task(lastStatus);s.seen=stamp;}finally{s.running=false;}
      }));
    }catch{retry=Math.min(30000,retry*2);}
    finally{checking=false;schedule(retry);}
  }
  function watch(task,{areas=['productions'],active=()=>true,initial=true}={}){
    const entry={task,areas,active,initial,seen:undefined,running:false};subscribers.add(entry);schedule(0);
    return()=>{subscribers.delete(entry);if(!subscribers.size)clearTimeout(timer);};
  }
  function wake(){if(!document.hidden){clearTimeout(timer);void check(true);}}
  document.addEventListener('visibilitychange',wake);window.addEventListener('focus',wake);
  window.addEventListener('studio-view-changed',wake);
  function visible(id){const node=document.getElementById(id);return !!node?.getClientRects().length;}
  function preview(kind,id,width=320){return '/api/previews/'+kind+'/'+encodeURIComponent(id)+'/'+width+'?workspace='+encodeURIComponent(window.studioWorkspaceId||'local-owner');}
  function thumbnail(url,width=320){const match=typeof url==='string'&&url.match(/^\/api\/assets\/([A-Za-z0-9_-]+)$/);return match?preview('image',match[1],width):url;}
  window.StudioRuntime={json,watch,wake,visible,preview,thumbnail};
})();
