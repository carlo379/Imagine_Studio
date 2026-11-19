// Warn when this Studio server runs older code than the files on disk (restart it to update).
(function(){
  async function check(){
    try{
      const response=await fetch('/api/agent/');if(!response.ok)return;
      const code=(await response.json()).code;
      let bar=document.getElementById('codeStatus');
      if(!code||!code.stale){if(bar)bar.hidden=true;return;}
      if(!bar){
        bar=document.createElement('div');bar.id='codeStatus';bar.setAttribute('role','status');
        bar.style.cssText='position:fixed;bottom:12px;left:50%;transform:translateX(-50%);max-width:min(720px,calc(100% - 32px));z-index:9999;padding:8px 14px;border-radius:8px;background:#7a4b00;color:#fff;font:13px system-ui;text-align:center;box-shadow:0 4px 16px #0006';
        document.body.append(bar);
      }
      bar.textContent=code.message;bar.hidden=false;
    }catch(_){/* the server may be restarting */}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',check);else check();
  setInterval(check,60000);
})();
