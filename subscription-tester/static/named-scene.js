/* Local names compile to documented positional inputs; no named-object API fields. */
(function(root){
  const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const mentions = text => [...text.matchAll(/(^|[^A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]*)/g)].map(m=>m[2]);
  function expand(prompt, named, refs, voices, firstFrame){
    const errors=[], contexts=[];
    // Retire generated appearance rows from legacy preparations, not user prose.
    prompt=prompt.split('\n\n').flatMap(paragraph=>{
      const lines=paragraph.split(/\r?\n/),header=lines[0];
      if(!['Asset cues:','Reference context:','Reference identities:'].includes(header))return [paragraph];
      const kept=lines.slice(1).filter(line=>!named.some(binding=>{
        const imageBacked=refs.some(r=>binding.refIds.includes(r.id));
        const prefixes=header==='Asset cues:'?(imageBacked?[`@${binding.handle}:`,`${binding.title}:`]:[]):
          [`${binding.category}: ${binding.title} (`,`Preserve ${binding.title}'s exact appearance as shown in `,`Voice for ${binding.title}: `];
        return prefixes.some(prefix=>line.toLowerCase().startsWith(prefix.toLowerCase()));
      }));
      return kept.length?[[header,...kept].join('\n')]:[];
    }).join('\n\n').trim();
    for(const handle of mentions(prompt))if(!named.some(n=>n.handle.toLowerCase()===handle.toLowerCase()))errors.push(`@${handle} is not attached. Choose a saved reference or remove the mention.`);
    for(const binding of named){
      const tags=[];
      for(const id of binding.refIds){const index=refs.findIndex(r=>r.id===id);if(index<0)errors.push(`${binding.title} is missing an attached image. Restore or remove this scene reference.`);else tags.push(`<IMAGE_${index+(firstFrame?1:0)}>`);}
      const voiceIndex=voices.findIndex(v=>v.id===binding.voiceId);
      if(!tags.length&&voiceIndex<0)errors.push(`${binding.title} has no active image or voice for this model. Enable audio on 1.5 or remove this scene reference.`);
      prompt=prompt.replace(new RegExp(`(^|[^A-Za-z0-9_])@${escape(binding.handle)}(?![A-Za-z0-9_])`,'gi'),(_,prefix)=>prefix+binding.title);
      if(tags.length)contexts.push(binding.category==='Character'?
        `Preserve ${binding.title}'s exact appearance as shown in ${tags.join(' and ')} throughout the shot.`:
        `${binding.category}: ${binding.title} (${tags.join(', ')}).`);
      if(voiceIndex>=0){
        let description=tags.length?'':(binding.video_summary??binding.description);
        if(binding.video_summary&&prompt.includes(binding.video_summary))description='';
        contexts.push(`Voice for ${binding.title}: <AUDIO_${voiceIndex}>.${description?' '+description:''}`);
      }
    }
    return {prompt:(contexts.length?'Reference identities:\n'+contexts.join('\n')+(prompt?'\n\n'+prompt:''):prompt),errors:[...new Set(errors)]};
  }
  const api={expand,mentions};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.NamedScene=api;
})(typeof window!=='undefined'?window:this);
