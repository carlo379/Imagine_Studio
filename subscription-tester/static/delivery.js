// Script for /delivery (external: the page CSP allows only same-origin scripts).
const api = (path, opts={}) => fetch('/api/agent/delivery'+path, {credentials:'same-origin', ...opts,
  headers:{'Content-Type':'application/json','X-Tester':'local', ...(opts.headers||{})}}).then(async r => {
    const v = await r.json(); if (!r.ok) throw Error(v.error?.message || 'Request failed.'); return v; });
const $ = id => document.getElementById(id);
let current = null;
function cell(tr, text, cls) { const td = document.createElement('td'); td.textContent = text == null ? '—' : String(text); if (cls) td.className = cls; tr.append(td); }
function show(check) {
  current = check; $('results').hidden = false;
  $('verdict').textContent = check.verdict === 'ready' ? 'Ready' : 'Needs fixing'; $('verdict').className = 'verdict ' + (check.verdict === 'ready' ? 'ok' : 'bad');
  const i = check.info, a = i.audio || {};
  $('summary').textContent = `${check.title}: ${i.video.codec} ${i.video.width}×${i.video.height} at ${i.video.fps} fps, ${i.video.frames} frames, ${i.duration_s} s; `
    + (i.audio ? `${a.codec} ${a.sample_rate} Hz ${a.bitrate_kbps} kbps, ${a.duration_s} s` : 'no sound')
    + (check.loudness ? `; ${check.loudness.integrated_lufs} LUFS, true peak ${check.loudness.true_peak_db} dBTP.` : '.')
    + (check.fix ? ` Fixed copy: ${check.fix.output_path}` : '');
  $('rows').replaceChildren(...check.checks.map(r => { const tr = document.createElement('tr');
    cell(tr, r.rule); cell(tr, r.expected); cell(tr, r.found); cell(tr, r.ok ? '✓' : '✗', r.ok ? 'ok' : 'bad'); return tr; }));
  $('loudest').textContent = check.loudness && check.loudness.loudest_moments.length
    ? 'Loudest 3-second stretches: ' + check.loudness.loudest_moments.map(m => `${m.time_s} s (${m.short_term_lufs} LUFS)`).join(', ') + '.' : '';
  $('fixArea').hidden = !check.fixable.length;
  if (check.contact_sheet) { $('sheet').src = check.contact_sheet.replace('/agent/v1/', '/api/agent/'); $('sheet').hidden = false; } else $('sheet').hidden = true;
}
async function refresh() {
  try { const list = await api('/checks'); const el = $('checks'); el.replaceChildren(); if (!list.length) el.textContent = 'No checks yet.';
    list.forEach(c => { const b = document.createElement('button'); b.textContent = `${c.title} · ${c.verdict}`; b.onclick = async () => show(await api('/checks/' + c.id)); el.append(b); });
  } catch (e) { $('checks').textContent = e.message; }
}
(async () => {
  const presets = await api('/presets');
  $('preset').replaceChildren(...Object.entries(presets).map(([id, p]) => { const o = document.createElement('option'); o.value = id; o.textContent = p.label; return o; }));
})().catch(e => { $('status').textContent = e.message; $('status').className = 'error'; });
$('run').onclick = async () => {
  $('status').textContent = 'Measuring… (a few seconds for a short ad)'; $('status').className = 'muted'; $('run').disabled = true;
  try { show(await api('/checks', {method: 'POST', body: JSON.stringify({path: $('path').value.trim(), preset: $('preset').value})})); $('status').textContent = ''; refresh(); }
  catch (e) { $('status').textContent = e.message; $('status').className = 'error'; } finally { $('run').disabled = false; }
};
$('fix').onclick = async () => {
  $('fixStatus').textContent = 'Writing the fixed copy…'; $('fix').disabled = true;
  const body = {}; if ($('output').value.trim()) body.output_path = $('output').value.trim();
  try { show(await api('/checks/' + current.id + '/fix', {method: 'POST', body: JSON.stringify(body)})); $('fixStatus').textContent = ''; refresh(); }
  catch (e) { $('fixStatus').textContent = e.message; } finally { $('fix').disabled = false; }
};
refresh();
