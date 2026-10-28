/* Evidence-based video reviews. Rendering media and adopting guide lessons are
   always separate user actions; this module never starts a video generation. */
(() => {
  'use strict';
  let active = null;
  const text = (tag, value = '', className = '') => {
    const element = document.createElement(tag);
    element.textContent = value == null ? '' : String(value);
    if (className) element.className = className;
    return element;
  };
  const action = (label, handler, className = 'secondary') => {
    const element = text('button', label, className);
    element.type = 'button';
    element.onclick = handler;
    return element;
  };
  const request = async (path = '', method = 'GET', body) => {
    const response = await fetch('/api/video-review' + path, {
      method, headers: {'Content-Type': 'application/json', 'X-Tester': 'local',
        ...(method !== 'GET' ? {'Idempotency-Key': crypto.randomUUID()} : {})},
      body: method === 'GET' ? undefined : JSON.stringify(body || {})
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error?.message || result.error || 'The video review could not be completed.');
    return result;
  };
  const labels = {met: 'Met', partial: 'Partly met', failed: 'Failed', uncertain: 'Uncertain'};
  const normalizeStatus = value => Object.hasOwn(labels, value) ? value : 'uncertain';
  const time = seconds => {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return 'Time unknown';
    return Math.floor(value / 60) + ':' + (value % 60).toFixed(2).padStart(5, '0');
  };
  const date = timestamp => timestamp ? new Date(Number(timestamp) * 1000).toLocaleString() : 'Saved review';
  const localSource = (value, prefix) => typeof value === 'string' && value.startsWith(prefix) && !value.includes('\\') ? value : '';
  const currentTake = identity => (typeof history !== 'undefined' ? history : []).find(item => item.id === identity)
    || window.productionBridge?.historyShot?.video_takes?.find(item => item.id === identity);

  function sync() {
    const button = document.getElementById('reviewVideoPrompt');
    const player = document.getElementById('video');
    if (!button || !player) return;
    const identity = typeof frameJob !== 'undefined' ? frameJob : null;
    const take = currentTake(identity);
    const available = !take?.imported_media_id && !!identity && !player.hidden && take?.status === 'done' && !!take.video;
    button.hidden = !available;
    button.disabled = !!active || !!window.productionBridge?.loading;
    button.title = 'Compare this take with its submitted prompt and reference images.';
  }

  async function open(identity, options = {}) {
    if (active) {active.dialog.focus(); return;}
    identity = identity || (typeof frameJob !== 'undefined' ? frameJob : null);
    if (!identity) throw Error('Choose a completed video to review.');
    const take = currentTake(identity);
    if (take?.imported_media_id) throw Error('This uploaded video has no recorded generation request to compare. Review it by watching the take.');
    if (!take || take.status !== 'done' || !take.video) throw Error('This video is not ready for review.');
    const sceneId = take.settings?._studio_video_id || (typeof sceneRecord !== 'undefined' ? sceneRecord?.id : null);
    const model = take.requested_model || take.settings?.model || '';
    const previousFocus = document.activeElement;
    const state = {dialog: null, job: null, reviews: [], lessons: [], closed: false, running: false, available: false,
      timer: null, tab: 'watch', fixIds: new Set(), fixTouched: false, promptReady: false, proposedPrompt: '', promptTouched: false, currentDirection: null,
      initialSceneId: sceneId, lessonVersion: 0, actionMessage: '', previousTouched: false,
      selections: new Map(), confirmedFindings: new Set(), preservedFindings: new Set(), preserveTouched: false};
    const dialog = text('dialog', '', 'video-review-dialog');
    state.dialog = dialog; active = state; sync();
    dialog.setAttribute('aria-labelledby', 'videoReviewTitle');
    const heading = text('header', '', 'vr-header');
    const headingCopy = text('div');
    headingCopy.append(text('span', 'VIDEO REVIEW', 'vr-eyebrow'));
    const title = text('h2', 'Improve this take'); title.id = 'videoReviewTitle';
    const subtitle = text('p', (typeof sceneRecord !== 'undefined' && sceneRecord?.id === sceneId ? sceneRecord.title + ' · ' : '')
      + (take.settings?.duration || '') + 's · ' + (take.settings?.resolution || '') + ' · ' + (model || 'Saved take'));
    headingCopy.append(title, subtitle);
    const close = action('← Back to Video', () => finish(), 'vr-close'); close.setAttribute('aria-label', 'Close video review');
    heading.append(headingCopy, close);
    const tabs = text('nav', '', 'vr-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Video refinement steps');
    const tabButtons = new Map();
    const panels = new Map();
    const layout = text('div', '', 'vr-layout');
    const media = text('aside', '', 'vr-media');
    const mediaHeading = text('div', '', 'vr-media-heading');
    mediaHeading.append(text('strong', 'The generated take'), text('span', 'Saved video', 'vr-subtle'));
    const player = text('video', '', 'vr-player'); player.controls = true; player.playsInline = true;
    player.preload = 'metadata'; player.src = '/api/video-media/' + encodeURIComponent(identity);
    player.setAttribute('aria-label', 'Video under review');
    const sourceNote = text('p', 'The comparison uses this take’s submitted request, even if you have edited the scene since.', 'vr-subtle');
    const evidenceBox = text('section', '', 'vr-evidence-box'); evidenceBox.hidden = true;
    const evidenceLabel = text('p', '', 'vr-evidence-label');
    const selectedFrame = text('img', '', 'vr-selected-frame'); selectedFrame.alt = 'Selected evidence frame';
    const evidenceCaption = text('p', '', 'vr-subtle');
    evidenceBox.append(evidenceLabel, selectedFrame, evidenceCaption);
    const frameStrip = text('div', '', 'vr-frame-strip'); frameStrip.setAttribute('aria-label', 'Sampled evidence frames');
    const referenceBox = text('section', '', 'vr-reference-box'); referenceBox.hidden = true;
    referenceBox.append(text('h4', 'References inspected for this take'));
    const referenceStrip = text('div', '', 'vr-reference-strip');
    referenceStrip.setAttribute('aria-label', 'Submitted reference images'); referenceBox.append(referenceStrip);
    const capability = text('p', 'Visual review uses sampled frames. Audio review checks whether an audio track exists; speech, sound quality and lip sync need your listening review.', 'vr-capability');
    media.append(mediaHeading, player, sourceNote, evidenceBox, frameStrip, referenceBox, capability);
    const main = text('div', '', 'vr-main');
    for (const [key, label] of [['watch', '1 · Watch & review'], ['fixes', '2 · Choose fixes'], ['prompt', '3 · Review prompt'], ['generate', '4 · Generate'], ['learning', 'Guide lessons'], ['history', 'Review history']]) {
      const button = action(label, () => showTab(key), 'vr-tab');
      button.id = 'videoReviewTab-' + key; button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', 'videoReviewPanel-' + key);
      button.onkeydown = event => {
        const keys = [...tabButtons.keys()].filter(name => !['learning', 'history'].includes(name) && !tabButtons.get(name).disabled), index = keys.indexOf(key);
        if (['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) {
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1
            : (index + (event.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length;
          showTab(keys[next]); tabButtons.get(keys[next]).focus();
        }
      };
      const panel = text('section', '', 'vr-panel'); panel.id = 'videoReviewPanel-' + key;
      panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', button.id);
      if (!['learning', 'history'].includes(key)) tabs.append(button); else {panel.removeAttribute('role'); panel.removeAttribute('aria-labelledby'); panel.setAttribute('aria-label', label);}
      main.append(panel); tabButtons.set(key, button); panels.set(key, panel);
    }
    const reportPanel = panels.get('watch');
    const fixesPanel = panels.get('fixes');
    const fixesHeading = text('h3', 'Choose what to fix');
    const fixChoices = text('div', '', 'vr-fix-choices');
    fixesPanel.append(fixesHeading, text('p', 'Select the issues to address in your next take. Inspect evidence when you need it.', 'vr-copy'), fixChoices);
    const setup = text('section', '', 'vr-setup');
    setup.append(text('h3', 'Watch the take. Tell us what went wrong.'), text('p', 'Find the mismatches, inspect the evidence, then choose what to change. Review uses your writing connection; generating the next video is a separate action.', 'vr-copy'));
    const setupRow = text('div', '', 'vr-setup-row');
    const writerLabel = text('label', 'Writing connection');
    const writer = text('select'); writer.setAttribute('aria-label', 'Video review writing connection');
    writer.append(new Option('ChatGPT', 'codex'), new Option('Grok', 'grok'));
    writer.value = document.querySelector('[aria-label="Video direction writing connection"]')?.value || 'codex';
    writerLabel.append(writer);
    const previousLabel = text('label', 'Compare with a previous review (optional)');
    const previous = text('select'); previous.setAttribute('aria-label', 'Previous video review');
    previous.append(new Option('Review this take on its own', '')); previousLabel.append(previous);
    const previousHint = text('p', '', 'vr-subtle'); previousHint.hidden = true;
    previous.onchange = () => {state.previousTouched = true; previousHint.hidden = true;};
    setupRow.append(writerLabel, previousLabel);
    const notesLabel = text('label', 'What should we look closely at? (optional)');
    const notes = text('textarea'); notes.rows = 2; notes.maxLength = 2000;
    notes.placeholder = 'Example: SampleHero’s legs change after the reveal. Check the door opening and each character’s eyeline.';
    notes.setAttribute('aria-label', 'Concerns for this video review'); notesLabel.append(notes);
    const startRow = text('div', '', 'vr-start-row');
    const allowance = text('p', 'Uses the selected writing allowance. No video is generated by this review.', 'vr-subtle');
    const start = action('Review this video', () => run(startReview), 'primary');
    start.disabled = true; startRow.append(allowance, start); const reviewSettings = text('details', '', 'vr-review-settings');
    reviewSettings.append(text('summary', 'Review settings'), setupRow, previousHint);
    setup.append(notesLabel, reviewSettings, startRow);
    const status = text('div', '', 'vr-progress'); status.hidden = true;
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const report = text('section', '', 'vr-report');
    reportPanel.append(setup, status);
    const fullReport = text('details', '', 'vr-full-report');
    fullReport.append(text('summary', 'Full report, uncertain findings and possible causes'), report);
    const promptPanel = panels.get('prompt');
    const refinement = text('section', '', 'vr-refinement'); refinement.hidden = true;
    refinement.append(text('h3', 'Prepare the next prompt'), text('p', 'Keep the improvements and address only the problems you identify. This uses the saved review and evidence; it does not render another video.', 'vr-copy'));
    const remainingLabel = text('label', 'Anything else to fix? (optional)');
    const remaining = text('textarea'); remaining.rows = 3; remaining.maxLength = 2000;
    remaining.placeholder = 'Example: At 0:06 Elena looks into the lens. At 0:10 SampleHero’s hat changes shape. Fix these while preserving the improved appearance and door action.';
    remaining.setAttribute('aria-label', 'Remaining video issues to refine'); remainingLabel.append(remaining);
    const preserveBox = text('fieldset', '', 'vr-finding-selection');
    preserveBox.append(text('legend', 'Keep what worked'));
    const preserveChoices = text('div', '', 'vr-finding-choices');
    const preserveHint = text('p', 'Confirmed improvements are selected here. You can adjust what this revision must preserve.', 'vr-subtle');
    preserveBox.append(preserveHint, preserveChoices);
    const refineRow = text('div', '', 'vr-start-row');
    const refineAllowance = text('p', 'Uses the selected writing allowance. Your existing proposal remains available in History.', 'vr-subtle');
    const refine = action('Prepare revised prompt →', () => run(prepareSelected), 'primary');
    remaining.oninput = () => {state.promptReady = false; syncActions();};
    refineRow.append(refineAllowance, refine); const keepDetails = text('details', '', 'vr-keep-details');
    keepDetails.append(text('summary', 'Keep what worked'), preserveBox);
    refinement.append(keepDetails, remainingLabel, refineRow);
    const promptIntro = text('div', '', 'vr-section-heading');
    promptIntro.append(text('h3', 'Review the revised prompt'), text('p', 'Review the proposed changes before replacing your scene direction. Your references, duration and audio settings stay under your control.', 'vr-copy'));
    const changeList = text('div', '', 'vr-changes');
    const promptLabel = text('label', 'Proposed direction · review and edit');
    const prompt = text('textarea', '', 'vr-prompt'); prompt.rows = 12;
    prompt.setAttribute('aria-label', 'Revised video prompt'); promptLabel.append(prompt);
    prompt.oninput = () => {state.promptTouched = true; state.proposedPrompt = prompt.value; syncActions();};
    const currentDirectionDetails = text('details', '', 'vr-current-direction');
    currentDirectionDetails.append(text('summary', 'Compare with the direction currently saved for this scene'));
    const currentDirection = text('pre'); currentDirectionDetails.append(currentDirection);
    const promptActions = text('div', '', 'vr-prompt-actions');
    const copy = action('Copy proposed prompt', () => run(async () => {
      await navigator.clipboard.writeText(prompt.value); announce('Proposed prompt copied.');
    }));
    const apply = action('Save prompt & return to Generate →', () => run(applyPrompt), 'primary');
    promptActions.append(copy, apply);
    const promptNote = text('p', 'A revised prompt addresses observed problems; model compliance still needs to be checked in the next result.', 'vr-subtle');
    const promptEmpty = text('p', 'Review a video to see a proposed revision tied to its findings.', 'vr-empty');
    const promptContent = text('div'); promptContent.hidden = true;
    const changesDetails = text('details', '', 'vr-changes-details');
    changesDetails.append(text('summary', 'What will change'), changeList);
    promptContent.append(promptIntro, changesDetails, promptLabel, currentDirectionDetails, promptActions, promptNote);
    fixesPanel.append(refinement, fullReport);
    const backToFixes = action('← Choose fixes', () => showTab('fixes'));
    promptActions.prepend(backToFixes);
    promptPanel.append(promptEmpty, promptContent);
    const generatePanel = panels.get('generate');
    const returnToGenerate = action('Return to Generate →', () => finish(true), 'primary');
    generatePanel.append(text('h3', 'Ready for the next take'), text('p', 'Your revised prompt is saved. Review your generation settings and generate when you are ready. The previous video stays available.', 'vr-copy'), returnToGenerate);
    const learningPanel = panels.get('learning');
    const outcomeBox = text('section', '', 'vr-outcome');
    outcomeBox.append(text('h3', 'What improved in this take?'), text('p', 'You can learn from improvements while the take still needs work. Confirm the findings you checked, record your assessment, then review any lesson before adding it to the guide. This assessment is separate from selecting the video for your shot.', 'vr-copy'));
    const confirmationBox = text('fieldset', '', 'vr-finding-selection');
    confirmationBox.append(text('legend', 'Confirm the improvements you checked'));
    const confirmationHint = text('p', 'Complete a review to see findings you can confirm.', 'vr-subtle');
    const confirmedChoices = text('div', '', 'vr-finding-choices');
    confirmationBox.append(confirmationHint, confirmedChoices);
    const outcomeLabel = text('label', 'Your assessment notes (optional)');
    const outcomeNotes = text('textarea'); outcomeNotes.rows = 2; outcomeNotes.maxLength = 2000;
    outcomeNotes.placeholder = 'What worked, what still failed, or what you checked by listening.';
    outcomeNotes.setAttribute('aria-label', 'Your assessment of the video result'); outcomeLabel.append(outcomeNotes);
    const outcomeActions = text('div', '', 'vr-outcome-actions');
    const unsuccessful = action('Still needs work', () => run(() => setOutcome('needs_work')));
    const improved = action('Improved, but needs work', () => run(() => setOutcome('improved')));
    const successful = action('This take is successful', () => run(() => setOutcome('successful')), 'primary');
    outcomeActions.append(unsuccessful, improved, successful);
    const outcomeStatus = text('p', '', 'vr-subtle');
    const candidateLabel = text('label', 'Learning to propose from confirmed improvements'); candidateLabel.hidden = true;
    const candidate = text('select'); candidate.setAttribute('aria-label', 'Proposed learning to consider');
    candidate.onchange = () => {state.candidateTouched = true;};
    candidateLabel.append(candidate);
    const nextAfterAssessment = action('Refine remaining issues →', () => {showTab('prompt'); remaining.focus();}, 'secondary vr-next'); nextAfterAssessment.hidden = true;
    outcomeBox.append(confirmationBox, outcomeLabel, candidateLabel, outcomeActions, outcomeStatus, nextAfterAssessment);
    const lessonList = text('div', '', 'vr-lessons');
    learningPanel.append(outcomeBox, text('h3', 'Lessons for this model'), text('p', 'Approved lessons guide future AI prompt preparation in this workspace. One improvement stays tentative; repeated evidence can strengthen it. You can use the current prompt proposal after approving a lesson, or request a focused refinement in Choose fixes.', 'vr-copy'), lessonList);
    const historyPanel = panels.get('history');
    const historyHeading = text('div', '', 'vr-section-heading');
    const refresh = action('Refresh history', () => run(loadHistory));
    historyHeading.append(text('h3', 'Review and guide history'), refresh);
    const reviewHistory = text('div', '', 'vr-history');
    const guideHistory = text('div', '', 'vr-history');
    const guideVersion = text('p', '', 'vr-subtle');
    historyPanel.append(historyHeading, text('h4', 'Video reviews'), reviewHistory, text('h4', 'Prompting guide lessons'), guideVersion, guideHistory);
    const secondary = text('div', '', 'vr-secondary-sections');
    for (const [key, label] of [['learning', 'Guide lessons (optional)'], ['history', 'Review history']]) {
      const details = text('details', '', 'vr-secondary-section');
      details.dataset.section = key;
      details.append(text('summary', label), panels.get(key)); secondary.append(details);
    }
    const framesDetails = text('details', '', 'vr-media-details');
    framesDetails.append(text('summary', 'Sampled evidence frames'), frameStrip);
    media.insertBefore(framesDetails, referenceBox);
    const referencesDetails = text('details', '', 'vr-media-details');
    referencesDetails.append(text('summary', 'Reference images used'), referenceBox);
    media.insertBefore(referencesDetails, capability);
    layout.append(media, main);
    const footer = text('footer', '', 'vr-footer');
    const error = text('p', '', 'vr-error'); error.setAttribute('role', 'alert');
    const message = text('p', '', 'vr-feedback'); message.setAttribute('role', 'status'); message.setAttribute('aria-live', 'polite');
    footer.append(error, message, action('Close review', () => finish()));
    const pageScroll = text('div', '', 'vr-page-scroll'); pageScroll.append(layout, secondary);
    const brand = text('div', '✦  IMAGINE STUDIO · VIDEO', 'vr-brand');
    dialog.append(brand, heading, tabs, pageScroll, footer); document.body.append(dialog); dialog.showModal();
    dialog.addEventListener('cancel', event => {event.preventDefault(); finish();});
    player.addEventListener('error', () => {sourceNote.textContent = 'The saved video could not load. You can still inspect extracted evidence and the submitted request.';});
    writer.onchange = () => syncActions();
    showTab('watch');

    function finish(generation = false) {
      if (state.closed) return;
      state.closed = true; clearTimeout(state.timer); player.pause();
      player.removeAttribute('src'); player.load(); dialog.close(); dialog.remove(); active = null; sync();
      if (generation) {
        if (typeof toast === 'function') toast('Revised prompt saved. Ready to generate the next take.');
        const generate = document.getElementById('generate');
        generate?.scrollIntoView?.({block: 'center'}); generate?.focus();
      } else if (previousFocus?.isConnected) previousFocus.focus();
    }
    function announce(value) {state.actionMessage = value; message.textContent = value;}
    function showTab(key) {
      if (key === 'findings') key = state.job?.status === 'done' ? 'fixes' : 'watch';
      if (['learning', 'history'].includes(key)) {
        const details = secondary.querySelector('[data-section="' + key + '"]');
        details.open = true; details.scrollIntoView?.({block: 'nearest'}); return;
      }
      state.tab = key;
      for (const [name, panel] of panels) {
        if (['learning', 'history'].includes(name)) {panel.hidden = false; continue;}
        const selected = name === key; panel.hidden = !selected;
        tabButtons.get(name).setAttribute('aria-selected', String(selected));
        tabButtons.get(name).setAttribute('aria-current', selected ? 'step' : 'false');
      }
    }
    function syncActions() {
      if (state.closed) return;
      const pending = state.job?.status === 'pending', done = state.job?.status === 'done';
      start.disabled = !state.available || state.running || pending;
      writer.disabled = state.running || pending; notes.disabled = state.running || pending;
      previous.disabled = state.running || pending;
      start.textContent = pending ? 'Reviewing…' : state.job ? 'Review again' : 'Review this video';
      copy.disabled = state.running || !prompt.value.trim();
      apply.disabled = state.running || !done || !prompt.value.trim() || !sceneId;
      successful.disabled = unsuccessful.disabled = state.running || !done;
      improved.disabled = state.running || !done || !state.confirmedFindings.size;
      improved.title = state.confirmedFindings.size ? 'Record partial improvement and propose learning from the findings you confirmed.' : 'Confirm at least one met finding above to record an improvement.';
      candidate.disabled = state.running || !done;
      outcomeNotes.disabled = state.running || !done;
      remaining.disabled = state.running || pending || !done;
      refine.disabled = state.running || pending || !done || (!state.fixIds.size && !remaining.value.trim());
      for (const input of fixChoices.querySelectorAll('input')) input.disabled = state.running || pending || !done;
      tabButtons.get('fixes').disabled = !done || state.running;
      tabButtons.get('prompt').disabled = !done || !state.promptReady || !prompt.value.trim() || state.running;
      tabButtons.get('generate').disabled = !state.job?.applied_scene_revision || state.running;
      returnToGenerate.disabled = !state.job?.applied_scene_revision;
      refine.textContent = 'Prepare prompt for ' + state.fixIds.size + ' selected fixes →';
      for (const input of [...confirmedChoices.querySelectorAll('input'), ...preserveChoices.querySelectorAll('input')]) input.disabled = state.running || !done;
      refresh.disabled = state.running;
      prompt.disabled = state.running || pending;
      for (const button of [...lessonList.querySelectorAll('button'), ...guideHistory.querySelectorAll('button'), ...reviewHistory.querySelectorAll('button')]) button.disabled = state.running || pending;
      const assessment = currentAssessment();
      outcomeStatus.textContent = assessment === 'successful'
        ? 'Recorded: this take is successful. Review any proposed lesson below.'
        : assessment === 'improved' ? 'Recorded: improved, but still needs work. Learn from the confirmed improvements, then refine the remaining issues.'
        : assessment === 'needs_work' ? 'Recorded: still needs work. You can request a focused revision in Choose fixes.' : '';
      nextAfterAssessment.hidden = !done || !state.job?.outcome;
      nextAfterAssessment.disabled = state.running;
      successful.setAttribute('aria-pressed', String(assessment === 'successful'));
      improved.setAttribute('aria-pressed', String(assessment === 'improved'));
      unsuccessful.setAttribute('aria-pressed', String(assessment === 'needs_work'));
      refineAllowance.textContent = 'Reuses the existing proposal when your selections are unchanged. Additional changes use the ' + (writer.value === 'grok' ? 'Grok' : 'ChatGPT') + ' writing allowance; no video is generated.';
    }
    function currentAssessment() {
      const outcome = state.job?.outcome;
      return outcome?.assessment || (outcome?.successful === true ? 'successful' : outcome?.successful === false ? 'needs_work' : '');
    }
    function saveSelections() {
      if (!state.job) return;
      state.selections.set(state.job.id, {confirmed: [...state.confirmedFindings], preserved: [...state.preservedFindings], preserveTouched: state.preserveTouched, fixes: [...state.fixIds], fixTouched: state.fixTouched});
    }
    function metFindings() {return (state.job?.result?.requirements || []).filter(item => item.status === 'met');}
    function findingChoice(item, checked, onChange) {
      const label = text('label', '', 'vr-finding-choice');
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = checked;
      checkbox.value = item.id; checkbox.onchange = () => onChange(checkbox.checked);
      const copy = text('span'); copy.append(text('strong', item.requirement), text('small', 'Finding ' + item.id + (item.observation ? ' · ' + item.observation : '')));
      label.append(checkbox, copy); return label;
    }
    function renderPreserveChoices() {
      preserveChoices.replaceChildren();
      const findings = metFindings();
      preserveHint.textContent = findings.length ? 'Confirmed improvements are selected here. Adjust what this revision must preserve.' : 'There are no met findings to select. Describe anything to preserve with your remaining issues.';
      for (const item of findings) preserveChoices.append(findingChoice(item, state.preservedFindings.has(item.id), checked => {
        state.preserveTouched = true; state.promptReady = false;
        if (checked) state.preservedFindings.add(item.id); else state.preservedFindings.delete(item.id);
        saveSelections(); syncActions();
      }));
    }
    function renderLearningCandidates() {
      const selected = candidate.value;
      const candidates = state.job?.result?.lesson_candidates || [];
      candidate.replaceChildren(new Option('Record assessment only · no lesson proposal', ''));
      let firstEligible = null;
      candidates.forEach((item, index) => {
        const eligible = item.finding_ids?.length && item.finding_ids.every(id => state.confirmedFindings.has(id));
        if (!eligible) return;
        candidate.append(new Option(item.guidance, String(index)));
        if (firstEligible === null) firstEligible = String(index);
      });
      candidate.value = [...candidate.options].some(option => option.value === selected) ? selected : '';
      if (!state.candidateTouched && firstEligible !== null) candidate.value = firstEligible;
      candidateLabel.hidden = candidate.options.length <= 1;
      confirmationHint.textContent = !state.job || state.job.status !== 'done'
        ? 'Complete a review to see findings you can confirm.'
        : !metFindings().length ? 'This review has no met findings to confirm. Uncertain, partial and failed findings cannot become learned successes.'
        : !state.confirmedFindings.size ? 'Check only improvements you personally verified. Findings marked uncertain, partial or failed are excluded.'
        : firstEligible === null ? 'Your confirmed improvements can be recorded. This review has no eligible lesson proposal for those findings.'
        : 'Only lessons supported by the findings you confirmed can be proposed. Adding one to the guide remains a separate approval.';
    }
    function renderConfirmedChoices() {
      confirmedChoices.replaceChildren();
      for (const item of metFindings()) confirmedChoices.append(findingChoice(item, state.confirmedFindings.has(item.id), checked => {
        if (checked) state.confirmedFindings.add(item.id); else state.confirmedFindings.delete(item.id);
        // Guide confirmation is independent of the prompt's preservation choices.
        saveSelections(); renderLearningCandidates(); syncActions();
      }));
      renderLearningCandidates(); renderPreserveChoices();
    }
    async function run(task) {
      if (state.running || state.closed) return;
      state.running = true; error.textContent = ''; message.textContent = ''; syncActions();
      try {await task();} catch (failure) {if (!state.closed) error.textContent = failure.message;}
      finally {state.running = false; syncActions();}
    }
    function displayFrame(frame) {
      const source = localSource(frame?.src, '/api/video-review/evidence/');
      if (!source) return;
      evidenceBox.hidden = false; selectedFrame.src = source;
      selectedFrame.alt = 'Video evidence at ' + time(frame.time_seconds);
      evidenceLabel.textContent = 'EVIDENCE · ' + time(frame.time_seconds);
      evidenceCaption.textContent = 'Extracted from this take. Use the video player to check the surrounding motion.';
      player.pause();
      const seconds = Number(frame.time_seconds);
      if (Number.isFinite(seconds) && seconds >= 0 && player.readyState >= 1) player.currentTime = Math.min(seconds, Number.isFinite(player.duration) ? player.duration : seconds);
      for (const item of frameStrip.children) item.setAttribute('aria-pressed', String(item.dataset.frameId === frame.id));
    }
    function frameButton(frame, compact = false) {
      const source = localSource(frame?.src, '/api/video-review/evidence/');
      const button = action(time(frame.time_seconds), () => displayFrame(frame), compact ? 'vr-time-chip' : 'vr-frame');
      button.setAttribute('aria-label', 'Inspect evidence at ' + time(frame.time_seconds));
      if (!compact && source) {const image = text('img'); image.src = source; image.alt = ''; image.loading = 'lazy'; button.prepend(image);}
      button.dataset.frameId = frame.id; button.setAttribute('aria-pressed', 'false'); button.disabled = !source;
      return button;
    }
    function referenceButton(reference, compact = false) {
      const source = localSource(reference?.src, '/api/video-review/references/');
      const label = (reference.prompt_tag || reference.role || 'Reference') + (reference.attached === false ? ' · unavailable' : '');
      const button = action(label, () => {
        if (!source) return;
        player.pause(); evidenceBox.hidden = false; selectedFrame.src = source;
        selectedFrame.alt = 'Submitted ' + (reference.role || 'reference image');
        evidenceLabel.textContent = 'SUBMITTED REFERENCE · ' + (reference.prompt_tag || reference.role || 'Image');
        evidenceCaption.textContent = reference.exact_pixels ? 'The frozen image recorded with this request.' : 'Recovered historical reference; review the provenance limitations.';
        for (const item of frameStrip.children) item.setAttribute('aria-pressed', 'false');
      }, compact ? 'vr-time-chip' : 'vr-reference');
      button.disabled = !source;
      if (!compact && source) {const image = text('img'); image.src = source; image.alt = ''; image.loading = 'lazy'; button.prepend(image);}
      button.setAttribute('aria-label', 'Inspect submitted ' + label);
      return button;
    }
    function showJob(value) {
      if (state.closed) return;
      const newJob = state.job?.id !== value.id;
      const finishedRefinement = !newJob && state.job?.status === 'pending' && value.status === 'done' && !!value.parent_review_id;
      saveSelections();
      state.job = value;
      if (newJob) {
        state.fixTouched = false; state.promptReady = value.status === 'done' && !!value.parent_review_id; state.fixIds = new Set();
        state.promptTouched = false; state.currentDirection = null; evidenceBox.hidden = true; state.candidateTouched = false;
        const selection = state.selections.get(value.id);
        state.fixTouched = selection?.fixTouched || false; state.fixIds = new Set(selection?.fixes || []);
        const confirmed = selection?.confirmed || value.outcome?.confirmed_finding_ids || [];
        state.confirmedFindings = new Set(confirmed);
        state.preservedFindings = new Set(selection?.preserved || value.preserve_finding_ids || confirmed);
        state.preserveTouched = selection?.preserveTouched || false;
        outcomeNotes.value = value.outcome?.notes || ''; remaining.value = '';
      }
      const eligibleIds = new Set(metFindings().map(item => item.id));
      state.confirmedFindings = new Set([...state.confirmedFindings].filter(id => eligibleIds.has(id)));
      if (value.status === 'done') {
        if (!state.preserveTouched && !state.preservedFindings.size && value.parent_review_id) state.preservedFindings = new Set(value.preserve_finding_ids || []);
        state.preservedFindings = new Set([...state.preservedFindings].filter(id => eligibleIds.has(id)));
      }
      clearTimeout(state.timer);
      status.hidden = value.status !== 'pending';
      reportPanel.setAttribute('aria-busy', String(value.status === 'pending'));
      status.replaceChildren();
      if (value.status === 'pending') {const spinner = text('span', '', 'vr-spinner'); spinner.setAttribute('aria-hidden', 'true'); status.append(spinner, text('span', stageLabel(value.stage)));}
      if (value.status === 'error') error.textContent = value.error || 'Review failed. Your prompt and video are preserved.';
      report.replaceChildren(); frameStrip.replaceChildren();
      const frames = value.evidence?.frames || [];
      frames.forEach(frame => frameStrip.append(frameButton(frame)));
      referenceStrip.replaceChildren();
      const references = value.evidence?.references || [];
      references.forEach(reference => referenceStrip.append(referenceButton(reference)));
      referenceBox.hidden = !references.length;
      const limitations = value.evidence?.limitations || [];
      capability.textContent = limitations.length ? limitations.join(' ') : 'Visual review uses sampled frames. Audio review checks track presence; speech, sound quality and lip sync need your listening review.';
      sourceNote.textContent = value.snapshot?.source === 'reconstructed'
        ? 'This historical take has a reconstructed request. The report identifies what could not be recovered.'
        : 'Reviewing the submitted request saved with this take. Later scene edits are excluded from the comparison.';
      if (value.status === 'done' && value.result) {renderReport(value, frames); renderFixes(value, frames);}
      promptEmpty.hidden = value.status === 'done' && !!value.result?.revised_prompt;
      promptContent.hidden = !promptEmpty.hidden;
      if (value.result && !state.promptTouched) {
        state.proposedPrompt = value.result.revised_prompt || ''; prompt.value = state.proposedPrompt;
      }
      refinement.hidden = value.status !== 'done';
      renderConfirmedChoices();
      changeList.replaceChildren();
      for (const item of value.result?.changes || []) {
        const card = text('article', '', 'vr-change');
        card.append(text('p', item.reason, 'vr-change-reason'));
        const sections = text('div', '', 'vr-change-pair');
        const before = text('div'); before.append(text('small', 'Before'), text('p', item.before || 'No specific instruction'));
        const after = text('div'); after.append(text('small', 'Proposed'), text('p', item.after));
        sections.append(before, after); card.append(sections);
        if (item.finding_ids?.length) card.append(text('small', 'Addresses findings ' + item.finding_ids.join(', '), 'vr-subtle'));
        changeList.append(card);
      }
      if (value.status === 'done') {
        if (state.currentDirection === null) state.currentDirection = typeof sceneRecord !== 'undefined' && sceneRecord?.id === sceneId
          ? project.prompt : value.snapshot?.draft_prompt || '';
        currentDirection.textContent = state.currentDirection || 'No saved direction';
        promptNote.textContent = value.applied_scene_revision
          ? 'This review’s proposed direction was applied at scene revision ' + value.applied_scene_revision + '. You can inspect or edit it again; generating remains a separate action.'
          : 'Inspect the changes before applying. The next generation remains a separate action.';
      }
      if (finishedRefinement) state.promptReady = true;
      renderLessons(); renderHistory(); syncActions();
      if (value.status === 'done' && !finishedRefinement && (state.tab === 'watch' || newJob)) showTab(value.parent_review_id ? 'prompt' : 'fixes');
      if (value.status === 'pending') showTab('watch');
      if (value.status === 'pending') state.timer = setTimeout(poll, 1800);
      if (finishedRefinement) {
        showTab('prompt');
        announce('Focused proposal ready. Inspect the changes and preserved findings before using the prompt.');
      }
    }
    function stageLabel(stage) {
      const stages = {queued: 'Review queued…', capturing: 'Preparing this take’s saved request and reference evidence…',
        inspecting: 'Extracting frames and checking the audio track…', reviewing: 'Comparing video evidence and preparing a targeted revision…',
        reusing_evidence: 'Reusing saved frames, references and findings for this focused revision…',
        refining: 'Refining the remaining issues while preserving your selected improvements…',
        extracting: 'Extracting frames and checking the audio track…',
        preparing: 'Reading the submitted prompt and its reference images…', analyzing: 'Comparing the video evidence with your requirements…',
        writing: 'Comparing the evidence and preparing a targeted revision…'};
      return stages[stage] || 'Reviewing this take… Your saved prompt and video are preserved.';
    }
    function renderReport(value, frames) {
      const result = value.result, summary = text('div', '', 'vr-summary');
      const verdict = normalizeStatus(result.overall);
      summary.append(text('span', labels[verdict], 'vr-verdict vr-status-' + verdict), text('h3', 'What the result shows'), text('p', result.summary, 'vr-copy'));
      if (value.parent_review_id) {
        summary.append(text('p', 'Focused prompt revision using this same take’s saved evidence. Assess the next generated video separately.', 'vr-subtle'));
        const preserved = (value.preserve_finding_ids || []).map(id => (result.requirements || []).find(item => item.id === id)?.requirement || 'Finding ' + id);
        if (preserved.length) summary.append(text('p', 'Requested to preserve: ' + preserved.join('; '), 'vr-copy'));
      }
      const counts = text('div', '', 'vr-counts');
      for (const key of Object.keys(labels)) counts.append(text('span', (result.requirements || []).filter(item => normalizeStatus(item.status) === key).length + ' ' + labels[key].toLowerCase(), 'vr-count vr-status-' + key));
      summary.append(counts);
      const source = text('details', '', 'vr-source');
      source.append(text('summary', value.snapshot?.source === 'exact' ? 'Submitted prompt and reference mapping' : 'Recovered prompt and request details'));
      source.append(text('pre', value.snapshot?.request?.prompt || 'No text prompt was submitted.'));
      const bindings = text('ul');
      for (const binding of value.snapshot?.bindings || []) bindings.append(text('li', (binding.prompt_tags?.join(', ') || binding.tag || binding.image_tag || binding.api_tag || '') + ' · ' + (binding.title || binding.name || 'Saved reference') + (binding.handle ? ' · @' + binding.handle.replace(/^@/, '') : '')));
      if (bindings.children.length) source.append(bindings);
      source.append(text('p', (value.snapshot?.request?.generate_audio === false ? 'Audio was disabled.' : 'Audio was enabled.')
        + ' Review is based on sampled frames; uncertain requirements need closer inspection.', 'vr-subtle'));
      report.append(summary, source);
      const requirements = text('section', '', 'vr-requirements'); requirements.append(text('h3', 'Prompt requirements'));
      for (const item of result.requirements || []) {
        const statusValue = normalizeStatus(item.status), card = text('article', '', 'vr-requirement vr-status-' + statusValue);
        const top = text('div', '', 'vr-requirement-heading');
        top.append(text('span', labels[statusValue], 'vr-status-badge vr-status-' + statusValue), text('small', (item.category || 'Requirement') + ' · ' + (item.confidence || 'low') + ' confidence', 'vr-subtle'));
        card.append(top, text('h4', item.requirement), text('p', item.observation, 'vr-copy'));
        const evidence = text('div', '', 'vr-evidence-links');
        for (const frameId of item.evidence_ids || []) {
          const frame = frames.find(candidate => candidate.id === frameId);
          const reference = value.evidence?.references?.find(candidate => candidate.id === frameId);
          if (frame) evidence.append(frameButton(frame, true));
          else if (reference) evidence.append(referenceButton(reference, true));
        }
        for (const seconds of item.timestamps || []) {
          if ((item.evidence_ids || []).some(frameId => frames.find(candidate => candidate.id === frameId)?.time_seconds === seconds)) continue;
          evidence.append(action(time(seconds) + ' · Play here', () => {player.pause(); if (player.readyState >= 1) player.currentTime = Number(seconds);}, 'vr-time-chip'));
        }
        card.append(evidence, text('small', 'Finding ' + item.id, 'vr-finding-id')); requirements.append(card);
      }
      report.append(requirements);
      if (result.hypotheses?.length) {
        const hypotheses = text('section', '', 'vr-hypotheses');
        hypotheses.append(text('h3', 'Possible causes'), text('p', 'These are explanations to investigate. The evidence does not establish why the model behaved this way.', 'vr-copy'));
        for (const item of result.hypotheses) {
          const hypothesis = text('article'); hypothesis.append(text('p', item.explanation), text('small', (item.finding_id ? 'Finding ' + item.finding_id + ' · ' : '') + (item.confidence || 'low') + ' confidence', 'vr-subtle')); hypotheses.append(hypothesis);
        }
        report.append(hypotheses);
      }
      if (result.comparison?.summary) {
        const comparison = text('section', '', 'vr-comparison');
        comparison.append(text('h3', value.parent_review_id ? 'Focused revision of this review' : 'Compared with the previous attempt'), text('p', result.comparison.summary), text('small', value.parent_review_id ? 'This refinement reuses evidence from the same video. It does not verify a new result.' : 'A difference between takes does not prove which prompt change caused it.', 'vr-subtle'));
        report.append(comparison);
      }
    }
    function renderFixes(value, frames) {
      fixChoices.replaceChildren();
      const findings = (value.result?.requirements || []).filter(item => ['failed', 'partial', 'uncertain'].includes(item.status));
      if (!state.fixTouched) state.fixIds = new Set(findings.filter(item => item.status !== 'uncertain').map(item => item.id));
      if (!state.preserveTouched) state.preservedFindings = new Set(metFindings().map(item => item.id));
      if (!findings.length) fixChoices.append(text('p', 'No specific mismatches were found. You can add a change below or review the existing proposal.', 'vr-copy'));
      const uncertain = text('details', '', 'vr-uncertain-fixes');
      uncertain.append(text('summary', 'Uncertain findings · inspect before selecting'));
      for (const item of findings) {
        const card = text('article', '', 'vr-fix-card');
        card.append(findingChoice(item, state.fixIds.has(item.id), checked => {
          state.fixTouched = true; state.promptReady = false;
          if (checked) state.fixIds.add(item.id); else state.fixIds.delete(item.id);
          syncActions();
        }));
        card.append(text('p', item.observation, 'vr-fix-summary'));
        const details = text('details', '', 'vr-fix-evidence');
        details.append(text('summary', 'See evidence and intended result'), text('p', item.observation, 'vr-copy'));
        const links = text('div', '', 'vr-evidence-links');
        for (const id of item.evidence_ids || []) {
          const frame = frames.find(frame => frame.id === id);
          const reference = value.evidence?.references?.find(reference => reference.id === id);
          if (frame) links.append(frameButton(frame, true));
          else if (reference) links.append(referenceButton(reference, true));
        }
        details.append(links); card.append(details);
        (item.status === 'uncertain' ? uncertain : fixChoices).append(card);
      }
      if (uncertain.children.length > 1) fixChoices.append(uncertain);
    }
    async function prepareSelected() {
      if (!state.job || state.job.status !== 'done') return;
      const issues = (state.job.result?.requirements || []).filter(item => state.fixIds.has(item.id));
      const allIssues = (state.job.result?.requirements || []).filter(item => ['failed', 'partial'].includes(item.status));
      const defaultKeep = new Set(metFindings().map(item => item.id));
      const unchangedKeep = defaultKeep.size === state.preservedFindings.size && [...defaultKeep].every(id => state.preservedFindings.has(id));
      if (!remaining.value.trim() && unchangedKeep && issues.length === allIssues.length && allIssues.every(item => state.fixIds.has(item.id)) && state.job.result?.revised_prompt && (state.job.result.changes || []).every(change => (change.finding_ids || []).every(id => state.fixIds.has(id)))) {
        state.promptReady = true; syncActions(); showTab('prompt'); prompt.focus(); return;
      }
      await refineRemaining(issues);
    }
    async function poll() {
      if (state.closed || !state.job) return;
      try {const value = await request('/' + state.job.id); if (!state.closed) showJob(value);}
      catch (failure) {
        if (state.closed) return;
        error.textContent = failure.message + ' The saved review will resume when the connection returns.';
        state.timer = setTimeout(poll, 4000);
      }
    }
    async function loadHistory() {
      const query = sceneId ? '?scene_id=' + encodeURIComponent(sceneId) + '&target_video_job_id=' + encodeURIComponent(identity) : '?video_job_id=' + encodeURIComponent(identity);
      const [saved, learning] = await Promise.all([request(query), request('/lessons/model/' + encodeURIComponent(model))]);
      if (state.closed) return;
      state.reviews = (saved.reviews || []).sort((a, b) => Number(b.created_at) - Number(a.created_at));
      state.lessons = learning.lessons || saved.lessons || []; state.lessonVersion = learning.guide_version ?? 0;
      const selected = previous.value; previous.replaceChildren(new Option('Review this take on its own', ''));
      for (const item of state.reviews.filter(item => item.status === 'done' && item.video_job_id !== identity)) {
        if (item.snapshot?.request?.model && item.snapshot.request.model !== model) continue;
        previous.append(new Option(date(item.created_at) + ' · ' + labels[normalizeStatus(item.result?.overall)], item.id));
      }
      const proposedPrevious = saved.suggested_previous_review_id || take.settings?._studio_scene?.video_review_origin?.review_id;
      const preferred = state.previousTouched ? selected : state.job ? state.job.previous_review_id || '' : proposedPrevious || selected;
      const eligible = [...previous.options].some(option => option.value === preferred);
      previous.value = eligible ? preferred : '';
      previousHint.hidden = !previous.value || state.previousTouched || previous.value !== proposedPrevious;
      previousHint.textContent = 'The review that led to this take is selected for comparison. You can choose another review or review this take on its own.';
      renderLessons(); renderHistory();
    }
    function lessonCard(lesson, withActions = true) {
      const card = text('article', '', 'vr-lesson');
      const heading = text('div', '', 'vr-lesson-heading');
      heading.append(text('span', lesson.status === 'active' ? 'In your guide' : lesson.status === 'proposed' ? 'Proposed lesson' : lesson.status === 'inactive' ? 'Removed from guide' : lesson.status === 'merged' ? 'Evidence combined with existing lesson' : 'Dismissed', 'vr-lesson-status'), text('small', lesson.confidence === 'supported' ? 'Repeated supporting evidence' : 'Tentative · one result is not proof', 'vr-subtle'));
      const guidance = text(lesson.status === 'proposed' ? 'textarea' : 'p', lesson.guidance, 'vr-lesson-guidance');
      if (lesson.status === 'proposed') {guidance.value = lesson.guidance; guidance.rows = 3; guidance.maxLength = 1200; guidance.setAttribute('aria-label', 'Lesson guidance to approve');}
      card.append(heading, guidance, text('p', lesson.rationale, 'vr-copy'));
      const facts = text('p', 'Applies to ' + (lesson.model || model) + (lesson.scope ? ' · ' + lesson.scope : ''), 'vr-subtle'); card.append(facts);
      const limitations = Array.isArray(lesson.limitations) ? lesson.limitations : lesson.limitations ? [lesson.limitations] : [];
      if (limitations.length) card.append(text('p', limitations.join(' '), 'vr-subtle'));
      if (lesson.evidence?.length) {
        const details = text('details'); details.append(text('summary', lesson.evidence.length + ' supporting record' + (lesson.evidence.length === 1 ? '' : 's')));
        const evidence = text('ul');
        for (const item of lesson.evidence) {
          const entry = text('li', (item.outcome || 'Successful take') + ' · ' + (item.confidence || 'tentative'));
          const supportingReview = state.reviews.find(saved => saved.id === item.review_id);
          if (supportingReview && currentTake(item.video_job_id)) entry.append(action('Inspect supporting review', () => {
            if (item.video_job_id === identity) {showJob(supportingReview); showTab('fixes');}
            else {finish(); open(item.video_job_id, {reviewId: item.review_id}).catch(failure => toast(failure.message));}
          }, 'vr-time-chip'));
          evidence.append(entry);
        }
        details.append(evidence); card.append(details);
      }
      if (withActions && ['proposed', 'active', 'inactive'].includes(lesson.status)) {
        const actions = text('div', '', 'vr-lesson-actions');
        if (lesson.status === 'proposed') {
          actions.append(action('Dismiss lesson', () => run(() => updateLesson(lesson, 'dismiss'))), action('Add to prompting guide', () => run(() => updateLesson(lesson, 'approve', guidance.value)), 'primary'));
        } else if (lesson.status === 'inactive') actions.append(action('Restore lesson to guide', () => run(() => updateLesson(lesson, 'approve')), 'primary'));
        else actions.append(action('Remove from future guidance', () => run(() => updateLesson(lesson, 'deactivate'))));
        card.append(actions);
      }
      return card;
    }
    function renderLessons() {
      lessonList.replaceChildren();
      const proposed = state.lessons.filter(lesson => lesson.status === 'proposed' && (lesson.id === state.job?.lesson_proposal_id || lesson.evidence?.some(item => item.review_id === state.job?.id)));
      const activeLessons = state.lessons.filter(lesson => lesson.status === 'active');
      for (const lesson of [...proposed, ...activeLessons]) lessonList.append(lessonCard(lesson));
      if (!lessonList.children.length) lessonList.append(text('p', ['successful', 'improved'].includes(currentAssessment())
        ? 'Your assessment is recorded. No eligible lesson was proposed for the confirmed findings; you can still refine the remaining issues.'
        : 'No active lessons for this model yet. Confirm the improvements you checked to propose a learning.', 'vr-empty'));
    }
    function renderHistory() {
      reviewHistory.replaceChildren(); guideHistory.replaceChildren();
      for (const item of state.reviews) {
        const card = text('article', '', 'vr-history-card');
        card.append(text('strong', item.status === 'done' ? labels[normalizeStatus(item.result?.overall)] : item.status === 'error' ? 'Review failed' : 'Review in progress'), text('small', date(item.created_at), 'vr-subtle'));
        if (item.result?.summary) card.append(text('p', item.result.summary, 'vr-copy'));
        if (item.parent_review_id) card.append(text('small', 'Focused refinement · same video evidence', 'vr-subtle'));
        if (item.outcome) {
          const assessment = item.outcome.assessment || (item.outcome.successful ? 'successful' : 'needs_work');
          card.append(text('small', assessment === 'improved' ? 'Your assessment: improved, but needs work' : assessment === 'successful' ? 'Your assessment: successful' : 'Your assessment: still needs work', 'vr-subtle'));
        }
        if (item.applied_scene_revision) card.append(text('small', 'Prompt applied at scene revision ' + item.applied_scene_revision, 'vr-subtle'));
        if (item.video_job_id === identity) card.append(action(state.job?.id === item.id ? 'Current review' : 'Open review', () => {error.textContent = ''; showJob(item); showTab(item.status === 'done' ? 'fixes' : 'watch');}));
        else card.append(text('small', 'Previous take · available in comparison selector', 'vr-subtle'));
        reviewHistory.append(card);
      }
      if (!reviewHistory.children.length) reviewHistory.append(text('p', 'Reviews will appear here after your first comparison.', 'vr-empty'));
      guideVersion.textContent = state.lessonVersion ? 'Current guide version: ' + state.lessonVersion : 'No approved lesson version yet.';
      for (const lesson of state.lessons) {
        const card = lessonCard(lesson); card.append(text('small', 'Lesson revision ' + lesson.revision + (lesson.guide_version ? ' · guide ' + lesson.guide_version : '') + ' · ' + date(lesson.created_at), 'vr-subtle')); guideHistory.append(card);
      }
      if (!guideHistory.children.length) guideHistory.append(text('p', 'Approved and dismissed lessons retain their evidence here.', 'vr-empty'));
    }
    async function startReview() {
      const value = await request('', 'POST', {video_job_id: identity, scene_id: sceneId || undefined,
        provider: writer.value, approved: true, notes: notes.value.trim(), previous_review_id: previous.value || null});
      if (state.closed) return;
      state.reviews = [value, ...state.reviews.filter(item => item.id !== value.id)];
      showJob(value);
    }
    async function applyPrompt() {
      if (!state.job || !sceneId) return;
      if (typeof sceneRecord === 'undefined' || sceneRecord?.id !== sceneId) throw Error('Open the shot associated with this take before applying its revised prompt.');
      const deadline = Date.now() + 5000;
      while (sceneSaving && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
      if (sceneDirty && !sceneConflict) await saveScene();
      if (sceneSaving || sceneDirty || sceneConflict) throw Error('Your scene edits need attention before applying this prompt. Your proposed revision is preserved here.');
      const saved = await sceneAPI('/scenes/' + sceneId);
      if (state.closed) return;
      if (sceneRecord?.id !== sceneId || project.prompt !== saved.scene.prompt) throw Error('The shot changed while its prompt was loading. Review the saved direction before applying.');
      if (state.currentDirection !== saved.scene.prompt) {
        state.currentDirection = saved.scene.prompt; currentDirection.textContent = saved.scene.prompt;
        currentDirectionDetails.open = true;
        throw Error('The saved direction changed since this review opened. Compare the updated direction below, then choose Save prompt again if you want to replace it.');
      }
      const result = await request('/' + state.job.id + '/apply', 'POST', {expected_scene_revision: saved.revision,
        expected_scene_prompt: saved.scene.prompt, expected_review_revision: state.job.revision, approved: true, prompt: prompt.value});
      if (state.closed) return;
      if (sceneRecord?.id === sceneId && !sceneDirty && !sceneSaving) {
        applyScene(result.scene); window.dispatchEvent(new Event('media-prompt-applied'));
        window.dispatchEvent(new CustomEvent('production-media-renamed', {detail: {kind: 'video', id: sceneId}}));
      }
      state.currentDirection = result.scene.scene.prompt;
      state.proposedPrompt = prompt.value;
      if (result.review) showJob(result.review);
      announce('Revised direction saved. Review your settings, then generate the next take when you are ready.');
      await loadHistory();
      finish(true);
    }
    async function setOutcome(assessment) {
      if (!state.job) return;
      const value = await request('/' + state.job.id + '/outcome', 'POST', {expected_revision: state.job.revision,
        assessment, confirmed_finding_ids: [...state.confirmedFindings], notes: outcomeNotes.value.trim(),
        candidate_index: candidate.value === '' ? null : Number(candidate.value), approved: true});
      if (state.closed) return;
      showJob(value.review || value);
      await loadHistory();
      const recorded = assessment === 'improved' ? 'Partial improvement recorded.' : assessment === 'successful' ? 'Successful result recorded.' : 'Assessment recorded.';
      announce(recorded + (value.lesson_reason ? ' ' + value.lesson_reason : value.lesson_proposal
        ? ' Review the proposed lesson below before adding it to the guide.' : ' No guide lesson was added. You can refine the remaining issues in Choose fixes.'));
    }
    async function refineRemaining(issues = []) {
      if (!state.job) return;
      if (!issues.length && !remaining.value.trim()) throw Error('Select a fix or describe a change before preparing a prompt.');
      const selectedNotes = 'Address only these selected issues; leave other instructions unchanged:\n' + issues.map(item => item.id + ': ' + item.requirement + ' — ' + item.observation).join('\n') + (remaining.value.trim() ? '\nAdditional instruction: ' + remaining.value.trim() : '');
      if (selectedNotes.length > 4000) throw Error('Select fewer fixes or shorten your additional instruction before preparing the prompt.');
      const value = await request('/' + state.job.id + '/refine', 'POST', {expected_revision: state.job.revision,
        approved: true, provider: writer.value, notes: selectedNotes, preserve_finding_ids: [...state.preservedFindings]});
      if (state.closed) return;
      const review = value.review || value;
      state.selections.set(review.id, {confirmed: [...state.confirmedFindings], preserved: [...state.preservedFindings], preserveTouched: true, fixes: [...state.fixIds], fixTouched: true});
      state.reviews = [review, ...state.reviews.filter(item => item.id !== review.id)];
      showJob(review); showTab('watch');
      announce('Focused refinement started using the saved evidence. Your earlier review and proposal remain in History.');
    }
    async function updateLesson(lesson, operation, guidance) {
      await request('/lessons/' + lesson.id + '/' + operation, 'POST', {expected_revision: lesson.revision, approved: true,
        ...(operation === 'approve' ? {expected_guide_version: state.lessonVersion, ...(guidance !== undefined ? {guidance} : {})} : {})});
      if (state.closed) return;
      await loadHistory();
      announce(operation === 'approve' ? 'Lesson added to this model’s prompting guide for future AI preparation.'
        : operation === 'deactivate' ? 'Lesson removed from future guidance. Its evidence remains in history.' : 'Proposed lesson dismissed. Its history is preserved.');
    }
    try {
      const [schema] = await Promise.all([request('/schema'), loadHistory()]);
      if (state.closed) return;
      state.available = schema.ffmpeg_available !== false;
      if (schema.ffmpeg_available === false) {
        start.disabled = true; error.textContent = 'Video review needs FFmpeg to extract evidence frames. Install or configure it before starting a review.';
      } else start.disabled = false;
      const recent = state.reviews.find(item => item.video_job_id === identity && item.id === options.reviewId)
        || state.reviews.find(item => item.video_job_id === identity);
      if (recent) {
        if (!state.previousTouched) {previous.value = recent.previous_review_id || ''; previousHint.hidden = true;}
        showJob(recent);
      }
      else {renderLessons(); renderHistory(); syncActions();}
      if (schema.ffmpeg_available === false) start.disabled = true;
      (state.job?.status === 'done' ? fixChoices.querySelector('input') || tabButtons.get('fixes') : notes).focus();
    } catch (failure) {if (!state.closed) error.textContent = failure.message;}
  }
  window.VideoReview = {open, sync};
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('reviewVideoPrompt');
    if (button) button.onclick = () => open().catch(error => toast(error.message));
    const preview = document.getElementById('video');
    if (preview) new MutationObserver(sync).observe(preview, {attributes: true, attributeFilter: ['hidden', 'src']});
    sync();
  });
  window.addEventListener('studio-ready', sync);
})();
