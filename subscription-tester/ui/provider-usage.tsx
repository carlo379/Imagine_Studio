import React,{useEffect,useState} from 'react';
import {service} from './studio-service';
export function ProviderUsage(){
 const [usage,setUsage]=useState<any>(null),[error,setError]=useState(false);
 useEffect(()=>{let alive=true;const load=()=>service('usage').then(value=>{if(alive){setUsage(value);setError(false);}}).catch(()=>{if(alive)setError(true);});void load();const timer=setInterval(load,30000);return()=>{alive=false;clearInterval(timer);};},[]);
 return <div className="ft-note" aria-label="Grok usage"><p>Grok subscription balance: {usage?.providers?.grok_image?.balance_available?usage.providers.grok_image.remaining:'unavailable'}. Rate limits are separate from your subscription balance.</p>{error&&<p>Usage information could not be refreshed.</p>}{usage&&['grok_image','grok_video'].map(scope=>{const observation=usage.providers?.[scope]?.rate_limit_observation;return observation?<details key={scope}><summary>{scope==='grok_image'?'Image':'Video'} rate limits · observed {new Date(observation.observed_at*1000).toLocaleString()}</summary><p>Source: {observation.source}; scope: {observation.scope}. Last observed values may have changed.</p><dl>{Object.entries(observation.rate_limits).map(([k,v])=><React.Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></React.Fragment>)}</dl></details>:null;})}</div>;
}
