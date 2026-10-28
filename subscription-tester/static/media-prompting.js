/* Explicit preparation and review. This module never submits a media render. */
(() => {
  let open = false;
  const request = async (path, method = 'GET', body, key) => {
    const response = await fetch('/api/agent/' + path, {
      method, headers: {'Content-Type': 'application/json', 'X-Tester': 'local', ...(key ? {'Idempotency-Key': key} : {})},
      body: method === 'GET' ? undefined : JSON.stringify(body || {})
    });
    const result = await response.json();
    if (!response.ok) throw Object.assign(Error(result.error?.message || 'Prompt preparation failed.'), {code: result.error?.code});
    return result;
  };
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const recordPath = (kind, id) => (kind === 'image' ? 'image-studio/drafts/' : 'scenes/') + id;

  async function prepare(kind, identity, options = {}) {
    if (open) throw Error('Finish the current prompt review first.');
    open = true;
    let dialog, timer, closed = false, job = null, inFlight = false, editorControl = null;
    const previous = document.activeElement;
    try {
      const [draft, status] = await Promise.all([request(recordPath(kind, identity)), request('prompting/' + kind + '/' + identity)]);
      dialog = node('dialog', '', 'media-prompt-dialog');
      dialog.setAttribute('aria-label', 'Prepare ' + kind + ' prompt');
      const title = node('h2', options.autoStart ? 'Review ' + kind + ' prompt' : 'Prepare ' + kind + ' prompt with AI');
      const intro = node('p', 'AI uses the selected model’s prompting guide and your saved scene and references. Review the result before generating media.');
      const writerLabel = node('label', 'Writing connection');
      const writer = node('select'); writer.setAttribute('aria-label', 'Prompt writing connection');
      writer.append(new Option('ChatGPT first · Grok fallback', 'auto'), new Option('ChatGPT only', 'codex'), new Option('Grok only', 'grok'));
      writer.value = options.provider || 'auto';
      writerLabel.append(writer);
      const instructionsLabel = node('label', 'Instructions for AI (optional)');
      const instructions = node('textarea'); instructions.rows = 3; instructions.maxLength = 2000;
      const instructionKey=(window.studioStoragePrefix||'')+'imagine-prompt-instructions-'+kind+'-'+identity;
      instructions.setAttribute('aria-label', 'Instructions for prompt AI'); instructions.value = options.instruction ?? localStorage.getItem(instructionKey) ?? '';
      instructions.addEventListener('input',()=>localStorage.setItem(instructionKey,instructions.value));
      instructionsLabel.append(instructions);
      const progress = node('p'); progress.setAttribute('role', 'status');
      const error = node('p', '', 'error'); error.setAttribute('role', 'alert');
      const review = node('section'); review.hidden = true;
      const promptLabel = node('label', 'Prepared prompt · review and edit');
      const prompt = node('textarea'); prompt.rows = 12; prompt.maxLength = 50000;
      prompt.setAttribute('aria-label', 'Prepared media prompt'); promptLabel.append(prompt);
      const notes = node('ul'); const details = node('details'); details.append(node('summary', 'Preparation details'));
      const evidence = node('pre'); details.append(evidence); review.append(promptLabel, notes, details);
      const footer = node('footer'); const cancel = node('button', 'Close'); const start = node('button', 'Prepare prompt', 'secondary');
      const use = node('button', 'Use reviewed prompt', 'primary'); use.hidden = true;
      footer.append(cancel, start, use); dialog.append(title, intro, writerLabel, instructionsLabel, progress, error, review, footer);
      if (options.autoStart) {
        writerLabel.hidden = true; instructionsLabel.hidden = true; start.hidden = true;
        progress.textContent = 'Preparing the prompt…';
      }
      document.body.append(dialog); dialog.showModal();

      return await new Promise(resolve => {
        const finish = value => {
          if (closed) return;
          closed = true;if(window.studioAgentEditors?.['prompt-review']===editorControl)delete window.studioAgentEditors['prompt-review']; clearTimeout(timer); dialog.close(); dialog.remove(); open = false;
          if (previous?.isConnected) previous.focus();
          resolve(value);
        };
        cancel.onclick = () => finish(null);
        dialog.addEventListener('cancel', event => {event.preventDefault(); finish(null);});
        const show = value => {
          job = value; review.hidden = value.status !== 'done'; use.hidden = value.status !== 'done' || !!value.applied;
          start.disabled = value.status === 'pending'; writer.disabled = start.disabled; instructions.disabled = start.disabled;
          progress.textContent = value.status === 'pending' ? 'Preparing the prompt… Your saved draft is preserved.' : value.mock ? 'Local mock placeholder; no AI provider was contacted.' : value.status === 'done' ? 'Prompt ready for review. No media has been generated.' : '';
          if (value.status === 'error') error.textContent = value.error;
          if (value.result) {
            prompt.value = value.result.prompt; notes.replaceChildren(...(value.result.starting_frame_observations||[]).map(note=>node('li','Starting frame — '+note)),...value.result.notes.map(note => node('li', note)));
            evidence.textContent = JSON.stringify({writer: value.provider, provider_requested: value.provider_requested,
              fallback_from: value.fallback_from, fallback_reason: value.fallback_reason, guides: value.provenance?.guides,
              returned_model: value.writing_returned_model, usage: value.writing_usage, preparation_ms: value.writing_duration_ms}, null, 2);
          }
          start.textContent = value.status === 'pending' ? 'Preparing…' : 'Prepare again';
          if (options.autoStart) start.hidden = value.status !== 'error';
          if (value.status === 'pending') timer = setTimeout(poll, 1400);
        };
        const poll = async () => {
          if (closed) return;
          try {const value = await request('prompting/jobs/' + job.id); if (!closed) show(value);}
          catch (e) {if (!closed) {error.textContent = e.message; timer = setTimeout(poll, 2500);}}
        };
        start.onclick = async () => {
          if (inFlight) return; inFlight = true; start.disabled = true; error.textContent = ''; use.hidden = true;
          try {
            // Capture the displayed draft revision, not a newer agent edit.
            const value = await request('prompting/' + kind + '/' + identity, 'POST', {
              expected_revision: draft.revision, approved: true, ...(writer.value === 'auto' ? {} : {provider: writer.value}),
              instruction: instructions.value, ...(options.brief !== undefined ? {brief: options.brief} : {}), force: !!job
            }, crypto.randomUUID());
            if (!closed) show(value);
          } catch (e) {if (!closed) {error.textContent = e.message; start.disabled = false; start.hidden = false;}}
          finally {inFlight = false;}
        };
        use.onclick = async () => {
          if (inFlight || !job) return; inFlight = true; use.disabled = true; error.textContent = '';
          try {
            const result = await request('prompting/' + kind + '/' + identity + '/apply', 'POST', {
              job_id: job.id, expected_revision: job.revision, expected_media_revision: draft.revision, prompt: prompt.value
            });
            finish(result.draft);
          } catch (e) {if (!closed) {error.textContent = e.message; use.disabled = false;}}
          finally {inFlight = false;}
        };
        editorControl={capture:()=>({id:identity,revision:draft.revision,dirty:true,data:{kind,provider:writer.value,instruction:instructions.value,prompt:prompt.value,job_id:job?.id||null},actions:job?.status==='done'&&!job.applied?['save','discard']:['discard']}),discard:async()=>finish(null),save:async()=>{if(inFlight||!job||job.status!=='done'||job.applied)throw Error('Wait for the prepared prompt.');const result=await request('prompting/'+kind+'/'+identity+'/apply','POST',{job_id:job.id,expected_revision:job.revision,expected_media_revision:draft.revision,prompt:prompt.value});finish(result.draft);}};
        (window.studioAgentEditors||={})['prompt-review']=editorControl;
        if (!options.autoStart && status.job && !status.job.applied) show(status.job);
        if (status.current) progress.textContent = 'This draft already has a current reviewed prompt. You can prepare a revision here.';
        if (options.autoStart) cancel.focus(); else writer.focus();
        if(options.autoStart)void start.onclick();
      });
    } catch (error) {
      if(window.studioAgentEditors?.['prompt-review']===editorControl)delete window.studioAgentEditors['prompt-review'];if (dialog?.isConnected) dialog.remove(); clearTimeout(timer); open = false; throw error;
    }
  }
  window.MediaPrompting = {prepare};
  document.addEventListener('DOMContentLoaded', () => {
    const imageButton = document.getElementById('imagePreparePrompt');
    if (imageButton) imageButton.onclick = async () => {
      imageButton.disabled = true;
      try {
        await window.productionBridge?.flush(); await imageFlush();
        const identity = imageDraft.id;
        const draft = await prepare('image', identity, {instruction:document.getElementById('imageInstructions')?.value || '', autoStart:!!document.getElementById('imageInstructions'),provider:document.getElementById('imageWriter')?.value});
        if (draft && imageDraft.id === identity) {await imageLoad(draft); if(typeof imageWorkspaceTab==='function')imageWorkspaceTab('compose');const editor=document.getElementById('imagePromptEditor');if(editor)editor.open=true; window.dispatchEvent(new Event('media-prompt-applied'));}
      } catch (error) {toast(error.message);}
      finally {imageButton.disabled = false;}
    };
    const videoButton = document.getElementById('videoPreparePrompt');
    if (videoButton) videoButton.onclick = async () => {
      if (document.body.dataset.productionGuided === 'true') return;
      videoButton.disabled = true;
      try {
        await window.productionBridge?.flush(); await saveScene();
        if (!sceneRecord || sceneDirty || sceneConflict || sceneSaving) throw Error('Save the current video draft before preparing its prompt.');
        const identity = sceneRecord.id;
        const draft = await prepare('video', identity);
        if (draft && sceneRecord.id === identity) {applyScene(draft); window.dispatchEvent(new Event('media-prompt-applied'));}
      } catch (error) {toast(error.message);}
      finally {videoButton.disabled = false;}
    };
  });
})();
