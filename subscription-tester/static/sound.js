// Script for /sound (external: the page CSP allows only same-origin scripts).
const api = (path, opts={}) => fetch('/api/agent/'+path, {credentials:'same-origin', ...opts,
  headers:{'Content-Type':'application/json','X-Tester':'local', ...(opts.headers||{})}}).then(async r => {
    const v = await r.json(); if (!r.ok) throw Error(v.error?.message || 'Request failed.'); return v; });
const $ = id => document.getElementById(id);
const post = (path, body) => api(path, {method:'POST', body: JSON.stringify(body)});
async function run(statusId, work) {
  const el = $(statusId); el.textContent = 'Working…'; el.className = 'muted';
  try { el.textContent = await work() || 'Done.'; } catch (e) { el.textContent = e.message; el.className = 'error'; }
}
async function stems() {
  try { const list = await api('sound/stems'); const el = $('stems'); el.replaceChildren(); if (!list.length) el.textContent = 'No stems yet.';
    for (const s of list) { const d = document.createElement('div'); d.style.marginBottom = '12px';
      const t = document.createElement('div'); t.textContent = `${s.name} · ${s.kind} · ${s.duration_s} s`;
      const id = document.createElement('div'); id.className = 'muted'; id.textContent = s.id;
      const a = document.createElement('audio'); a.controls = true; a.preload = 'none'; a.src = s.audio.replace('/agent/v1/', '/api/agent/');
      d.append(t, id, a); el.append(d); }
  } catch (e) { $('stems').textContent = e.message; }
}
api('sound/presets').then(p => $('voiceGuide').textContent = p.voice_guide).catch(() => {});
$('vlCreate').onclick = () => run('vlStatus', async () => {
  const lines = $('vlLines').value.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
    const m = l.match(/^([\d.]+)\s*\|\s*(.+)$/); return m ? {at_s: Number(m[1]), text: m[2]} : {text: l}; });
  const out = await post('sound/voice-lines', {title: $('vlTitle').value, voice: $('vlVoice').value, lines});
  return `Scene “${out.scene.title}” created (${out.scene.id}).`; });
$('stSave').onclick = () => run('stStatus', async () => {
  const v = $('stSource').value.trim(), body = v.startsWith('/') ? {path: v} : {job_id: v};
  if ($('stName').value.trim()) body.name = $('stName').value.trim();
  const s = await post('sound/stems', body); stems(); return `Saved ${s.name} (${s.id})` + (s.words ? `, ${s.words.length} words timed.` : s.words_note ? `. ${s.words_note}` : '.'); });
$('plBuild').onclick = () => run('plStatus', async () => {
  const s = await post('sound/place', {name: $('plName').value, length_s: Number($('plLength').value), pieces: JSON.parse($('plPieces').value)});
  stems(); return `Built ${s.name} (${s.id}), ${s.duration_s} s.`; });
$('muFit').onclick = () => run('muStatus', async () => {
  const body = {stem_id: $('muSong').value.trim(), hit_s: Number($('muHit').value), length_s: Number($('muLength').value)};
  if ($('muEvent').value) body.song_event_s = Number($('muEvent').value);
  const fit = await post('sound/music-fit', body);
  $('muOptions').replaceChildren(...fit.options.map(o => { const tr = document.createElement('tr');
    for (const v of [o.song_event_s + ' s', o.kind, o.offset_s + ' s', `${o.silence.head_s} / ${o.silence.tail_s} s`]) { const td = document.createElement('td'); td.textContent = v; tr.append(td); }
    const td = document.createElement('td'), b = document.createElement('button'); b.className = 'secondary'; b.textContent = 'Use';
    b.onclick = () => { $('muOffset').value = o.offset_s; }; td.append(b); tr.append(td); return tr; }));
  return fit.advice; });
$('muWrite').onclick = () => run('muStatus', async () => {
  const s = await post('sound/music', {stem_id: $('muSong').value.trim(), name: $('muName').value || 'Music', offset_s: Number($('muOffset').value),
    length_s: Number($('muLength').value), keyframes: JSON.parse($('muKeys').value || '[]')});
  stems(); return `Wrote ${s.name} (${s.id}).`; });
$('rxExport').onclick = () => run('rxStatus', async () => {
  const body = {title: $('rxTitle').value || undefined, audio: JSON.parse($('rxAudio').value || '[]')};
  const video = $('rxVideo').value.split('\n').map(l => l.trim()).filter(Boolean).map(path => ({path}));
  if (video.length) body.video = video; if ($('rxFolder').value.trim()) body.output_folder = $('rxFolder').value.trim();
  const out = await post('resolve/exports', body); return `FCPXML: ${out.fcpxml}` + (out.lua ? ` · Lua: ${out.lua}` : '') + ' · ' + out.how_to.join(' '); });
stems();
