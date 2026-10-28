if(window.opener){window.opener.postMessage({type:'imagine-account-connected'},location.origin);window.close();}else location.replace('/');
