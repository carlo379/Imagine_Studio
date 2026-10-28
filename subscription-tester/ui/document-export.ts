import {useEffect,useState} from 'react';
import {service} from './navigation';
export function useManuscript(document:any,title:string,plan:any,family:'series'|'story'){
 const [text,setText]=useState('Preparing manuscript…');
 const source=JSON.stringify({document,title,plan,family,format:'markdown'});
 useEffect(()=>{let active=true;setText('Preparing manuscript…');const timer=setTimeout(()=>{void service('documents/render','POST',JSON.parse(source)).then(result=>{if(active)setText(result.text);}).catch(error=>{if(active)setText('Manuscript unavailable: '+error.message);});},100);return()=>{active=false;clearTimeout(timer);};},[source]);
 return text;
}
