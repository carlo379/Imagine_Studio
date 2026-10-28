(() => {
  const prefix=window.studioStoragePrefix||'';
  for (const method of ['getItem','setItem','removeItem']) {
    const original=Storage.prototype[method];
    Storage.prototype[method]=function(key,...args){return original.call(this,String(key).startsWith('imagine-')?prefix+key:key,...args);};
  }
  const original=window.fetch.bind(window);
  window.fetch=(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input instanceof Request?input.url:String(input),location.href);
    if(url.origin===location.origin&&url.pathname.startsWith('/api/')){
      const headers=new Headers(input instanceof Request?input.headers:options.headers);headers.set('X-Workspace-ID',window.studioWorkspaceId);options={...options,headers};
    }
    return original(input,options);
  };
})();
