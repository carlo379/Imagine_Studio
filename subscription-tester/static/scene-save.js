/* Three-way merge: never silently choose between competing edits. */
(function(root){
 function mergeSceneSave(base,local,remote){
  const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b), conflicts=[];
  function merge(a,b,c,path){const same=path==='title'?(x,y)=>x.trim()===y.trim():equal;if(same(b,c)||same(a,c))return structuredClone(b);if(same(a,b))return structuredClone(c);conflicts.push(path);return structuredClone(b);}
  const result={title:merge(base.title,local.title,remote.title,'title'),scene:{}};
  for(const key of Object.keys(base.scene))result.scene[key]=merge(base.scene[key],local.scene[key],remote.scene[key],key);
  // Image/voice ordering and prompt tags are related; do not combine parallel changes.
  const groups=[['prompt','first','refs','voices','audio','model','named'],['duration','keys']];
  for(const group of groups){const left=group.filter(k=>!equal(base.scene[k],local.scene[k])),right=group.filter(k=>!equal(base.scene[k],remote.scene[k]));
   if(left.length&&right.length&&group.some(k=>!equal(local.scene[k],remote.scene[k])))conflicts.push(group.join('/'));
  }
  return {result,conflicts:[...new Set(conflicts)]};
 }
 root.mergeSceneSave=mergeSceneSave;
 if(typeof module!=='undefined')module.exports={mergeSceneSave};
})(typeof window==='undefined'?globalThis:window);
