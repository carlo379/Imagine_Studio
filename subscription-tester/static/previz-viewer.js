// Previz viewer page logic (kept out of the HTML so Studio's content security policy allows it).
import { boot } from './previz.js';
const $ = (id) => document.getElementById(id);
const audio = new Audio();
let api = null, playing = false, raf = 0, t0 = 0, base = 0, useAudio = false;
const params = new URLSearchParams(location.search);

function say(text) { $('msg').textContent = text || ''; }
async function load(spec) {
  $('stage').innerHTML = '';
  try { api = await boot(spec, $('stage')); } catch (e) { say('This browser could not start WebGL: ' + e.message); return; }
  $('scrub').max = api.duration;
  $('shots').innerHTML = '';
  for (const s of api.shots) {
    const d = document.createElement('div');
    d.className = 'shot'; d.dataset.id = s.id;
    d.innerHTML = `<span>${s.id} ${s.kind || ''}</span><span>${s.start.toFixed(1)}s</span>`;
    d.onclick = () => seek(s.start);
    $('shots').appendChild(d);
  }
  seek(0);
  if (spec.audio_url) { audio.src = spec.audio_url; useAudio = true; }
  $('hint').style.display = 'none';
}
function now() { return useAudio && audio.src && !audio.paused ? audio.currentTime : base + (performance.now() - t0) / 1000; }
function seek(t) {
  if (!api) return;
  t = Math.max(0, Math.min(api.duration, t));
  base = t; t0 = performance.now();
  if (audio.src) audio.currentTime = t;
  draw(t);
}
function draw(t) {
  const id = api.setTime(t);
  $('scrub').value = t;
  $('clock').textContent = `${t.toFixed(2)} / ${api.duration.toFixed(2)} s`;
  for (const el of $('shots').children) el.classList.toggle('on', el.dataset.id === id);
}
function tick() {
  if (!playing) return;
  const t = now();
  if (t >= api.duration) { playing = false; $('play').textContent = 'Play'; audio.pause(); return; }
  draw(t);
  raf = requestAnimationFrame(tick);
}
$('play').onclick = () => {
  if (!api) return;
  playing = !playing;
  $('play').textContent = playing ? 'Pause' : 'Play';
  if (playing) { base = parseFloat($('scrub').value); t0 = performance.now(); if (audio.src) { audio.currentTime = base; audio.play().catch(() => { useAudio = false; }); } tick(); }
  else { audio.pause(); cancelAnimationFrame(raf); }
};
$('still').onclick = () => {
  if (!api) return;
  const t = parseFloat($('scrub').value), id = api.setTime(t);
  const link = document.createElement('a');
  link.href = 'data:image/png;base64,' + api.still(t);
  link.download = `${id || 'previz'}-${t.toFixed(2)}s.png`;
  link.click();
  draw(t);
  say('Still saved: composition reference for stills only, never for the video model.');
};
$('scrub').oninput = (e) => seek(parseFloat(e.target.value));
$('specfile').onchange = async (e) => { const f = e.target.files[0]; if (f) await load(JSON.parse(await f.text())); };
$('audiofile').onchange = (e) => { const f = e.target.files[0]; if (f) { audio.src = URL.createObjectURL(f); useAudio = true; say('Song loaded.'); } };
if (params.get('spec')) { fetch(params.get('spec')).then((r) => r.json()).then(load).catch((e) => say('Could not load the spec: ' + e.message)); }
window.addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body) { e.preventDefault(); $('play').click(); } });
