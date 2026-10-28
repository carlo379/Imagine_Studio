import React from 'react';

export function ScriptReviewStatus({request,busy,retry,draft}:{request:any;busy:boolean;retry:()=>void;draft:()=>void}){
 if(!request||request.status==='done')return null;
 const production=request.purpose==='production-details';
 if(request.status==='pending')return <div className="sw-review-status" role="status" aria-live="polite"><strong>{production?'Completing production details…':'Writing your script…'}</strong><p>Your result will appear here when processing finishes. Your current script is preserved.</p></div>;
 if(request.status!=='error')return null;
 return <div className="sw-review-status sw-error" role="alert"><strong>{production?'Production details could not be completed.':'Script writing could not be completed.'}</strong><p>{request.error||'The request failed. Your script is preserved.'}</p><p>No new result was saved. Any previous version shown below is still available.</p><div className="sw-review-status-actions">{production&&<button className="p-primary" disabled={busy} onClick={retry}>Retry production details</button>}<button className="sw-review-secondary" disabled={busy} onClick={draft}>Return to Draft</button></div></div>;
}
