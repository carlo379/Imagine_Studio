const nodes=new WeakMap<HTMLMediaElement,{context:AudioContext;gain:GainNode;source:MediaElementAudioSourceNode}>();
let context:AudioContext|undefined;
export function mediaGain(element:HTMLMediaElement,value:number){
 try{context ||= new AudioContext();let node=nodes.get(element);if(!node){const source=context.createMediaElementSource(element),gain=context.createGain();source.connect(gain).connect(context.destination);node={context,gain,source};nodes.set(element,node);}if(context.state==='suspended')void context.resume();element.volume=1;node.gain.gain.setTargetAtTime(Math.max(0,value),context.currentTime,.008);}catch{element.volume=Math.max(0,Math.min(1,value));}
}
export function releaseMediaGain(element:HTMLMediaElement){const node=nodes.get(element);if(node){node.source.disconnect();node.gain.disconnect();nodes.delete(element);}element.pause();}
export function fadeGain(local:number,length:number,fadeIn=0,fadeOut=0){return Math.max(0,Math.min(1,fadeIn?local/fadeIn:1,fadeOut?(length-local)/fadeOut:1));}
