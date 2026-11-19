// Script for /continuity (external: the page CSP allows only same-origin scripts).
const api = (path, opts={}) => fetch('/api/agent/image-studio/continuity'+path, {credentials:'same-origin', ...opts,
  headers:{'Content-Type':'application/json','X-Tester':'local', ...(opts.headers||{})}}).then(async r => {
    const v = await r.json(); if (!r.ok) throw Error(v.error?.message || 'Request failed.'); return v; });
const $ = id => document.getElementById(id);
let regions = [], current = null;

function setFrame(el, id) {
  el.querySelectorAll('img,.box').forEach(n => n.remove());
  if (!id) return;
  const img = new Image(); img.src = '/api/assets/' + encodeURIComponent(id); img.alt = 'frame'; el.prepend(img);
  if (el.id === 'firstFrame') img.onload = drawBoxes;
}
function drawBoxes() {
  const el = $('firstFrame'), img = el.querySelector('img'); el.querySelectorAll('.box').forEach(n => n.remove());
  if (!img) return;
  regions.forEach(r => { const b = document.createElement('div'); b.className = 'box';
    Object.assign(b.style, {left: r.box[0]*100+'%', top: r.box[1]*100+'%', width: (r.box[2]-r.box[0])*100+'%', height: (r.box[3]-r.box[1])*100+'%'});
    const s = document.createElement('span'); s.textContent = r.name; b.append(s); el.append(b); });
  const tbody = $('regionTable').querySelector('tbody'); tbody.innerHTML = '';
  regions.forEach((r, i) => { const tr = document.createElement('tr');
    tr.innerHTML = `<td></td><td class="muted">${r.box.map(v => v.toFixed(2)).join(', ')}</td><td><button class="secondary">Remove</button></td>`;
    tr.firstChild.textContent = r.name; tr.querySelector('button').onclick = () => { regions.splice(i, 1); drawBoxes(); }; tbody.append(tr); });
}
(function dragBoxes() {
  const el = $('firstFrame'); let start = null, ghost = null;
  const pos = e => { const r = el.querySelector('img').getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
  el.addEventListener('pointerdown', e => { if (!el.querySelector('img')) return; start = pos(e); ghost = document.createElement('div'); ghost.className = 'box'; el.append(ghost); el.setPointerCapture(e.pointerId); });
  el.addEventListener('pointermove', e => { if (!start) return; const p = pos(e);
    Object.assign(ghost.style, {left: Math.min(start[0], p[0])*100+'%', top: Math.min(start[1], p[1])*100+'%', width: Math.abs(p[0]-start[0])*100+'%', height: Math.abs(p[1]-start[1])*100+'%'}); });
  el.addEventListener('pointerup', e => { if (!start) return; const p = pos(e); ghost.remove();
    const box = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])]; start = null;
    if (box[2] - box[0] < 0.01 || box[3] - box[1] < 0.01) return;
    const name = prompt('Name this fixed object (for example: dish, door, lantern):'); if (!name) return;
    regions.push({name: name.trim().slice(0, 80), box}); drawBoxes(); });
})();

function show(check) {
  current = check; $('results').hidden = false;
  $('verdict').textContent = check.verdict + (check.accepted ? ' · accepted' : ''); $('verdict').className = 'verdict ' + ({pass:'held', fail:'moved', review:'changed'}[check.verdict] || '');
  $('reasons').textContent = check.reasons.join(' ') + ` Tolerance ${check.tolerance_px}px` + (check.scale_tolerance_percent != null ? `, size ±${check.scale_tolerance_percent}%.` : '.') + (check.accepted ? ` Accepted: “${check.accepted.human_words}”` : '');
  const rows = check.regions.length ? check.regions : [];
  $('resultRows').innerHTML = '';
  rows.forEach(r => { const tr = document.createElement('tr');
    tr.innerHTML = `<td></td><td class="${r.status}">${r.status}</td><td>${r.shift_px}px (${r.dx_px}, ${r.dy_px})</td><td>${r.scale_percent == null ? '—' : r.scale_percent + '%'}</td><td>${r.match ?? '—'}</td>`;
    tr.firstChild.textContent = r.name; $('resultRows').append(tr); });
  if (!rows.length) $('resultRows').innerHTML = `<tr><td colspan="5" class="muted">No fixed objects marked. Tiles: ${Object.entries(check.counts).map(([k, v]) => k + ' ' + v).join(', ')}.</td></tr>`;
  showImage('map'); $('acceptArea').hidden = check.verdict === 'pass' || !!check.accepted;
}
function showImage(kind) { if (current) $('resultImage').src = '/api/assets/' + current.images[kind]; }
document.querySelectorAll('[data-img]').forEach(b => b.onclick = () => showImage(b.dataset.img));

async function refresh() {
  try { const list = await api(''); const el = $('checks'); el.innerHTML = list.length ? '' : 'No checks yet.';
    list.forEach(c => { const b = document.createElement('button'); b.textContent = `${c.title} · ${c.verdict}${c.accepted ? ' · accepted' : ''}`;
      b.onclick = async () => { const full = await api('/' + c.id); $('first').value = full.first; $('last').value = full.last; regions = full.regions.slice();
        setFrame($('firstFrame'), full.first); setFrame($('lastFrame'), full.last); show(full); }; el.append(b); });
  } catch (e) { $('checks').textContent = e.message; }
}
['first', 'last'].forEach(k => $(k).addEventListener('change', () => setFrame($(k + 'Frame'), $(k).value.trim())));
$('clear').onclick = () => { regions = []; drawBoxes(); };
$('run').onclick = async () => {
  $('status').textContent = 'Checking…'; $('status').className = 'muted'; $('run').disabled = true;
  try { const check = await api('', {method: 'POST', body: JSON.stringify({first: {asset_id: $('first').value.trim()}, last: {asset_id: $('last').value.trim()},
      regions, tolerance_percent: Number($('tolerance').value), scale_tolerance_percent: Number($('scaleTolerance').value), title: $('title').value.trim() || undefined})});
    show(check); $('status').textContent = ''; refresh();
  } catch (e) { $('status').textContent = e.message; $('status').className = 'error'; } finally { $('run').disabled = false; }
};
$('lock').onclick = async () => {
  if (!regions.length) { $('status').textContent = 'Mark the fixed objects first.'; $('status').className = 'error'; return; }
  $('status').textContent = 'Copying fixed objects…'; $('status').className = 'muted';
  try { const out = await api('/lock', {method: 'POST', body: JSON.stringify({first: {asset_id: $('first').value.trim()}, last: {asset_id: $('last').value.trim()}, regions})});
    $('last').value = out.asset.id; setFrame($('lastFrame'), out.asset.id);
    $('status').textContent = `New last frame ${out.asset.id}. Next: ${out.next_steps.join(' ')}`;
  } catch (e) { $('status').textContent = e.message; $('status').className = 'error'; }
};
$('accept').onclick = async () => {
  try { show(await api('/' + current.id + '/accept', {method: 'POST', body: JSON.stringify({human_words: $('words').value})})); refresh(); }
  catch (e) { alert(e.message); }
};
const params = new URLSearchParams(location.search);
if (params.get('first')) { $('first').value = params.get('first'); setFrame($('firstFrame'), params.get('first')); }
if (params.get('last')) { $('last').value = params.get('last'); setFrame($('lastFrame'), params.get('last')); }
refresh();
