// Script for /prop-placement (external: the page CSP allows only same-origin scripts).
const api = (path, opts={}) => fetch('/api/agent/image-studio/prop-placement'+path, {credentials:'same-origin', ...opts,
  headers:{'Content-Type':'application/json','X-Tester':'local', ...(opts.headers||{})}}).then(async r => {
    const v = await r.json(); if (!r.ok) throw Error(v.error?.message || 'Request failed.'); return v; });
const $ = id => document.getElementById(id);
let current = null, timer = null;
function show(run) {
  current = run; $('ppRun').hidden = false; $('ppRunTitle').textContent = `${run.title} · ${run.status}`;
  $('ppSteps').textContent = run.steps.map(s => `Step ${s.step} (${s.kind}): ${s.output ? 'done' : 'running'}`).join(' · ')
    + (run.true_ratio ? ` · true width/height of the product: ${run.true_ratio}` : '') + (run.error ? ' · ' + run.error : '') + (run.waiting ? ' · ' + run.waiting : '');
  $('ppImages').replaceChildren(...run.steps.filter(s => s.output).map(s => { const i = new Image(); i.src = '/api/assets/' + s.output; i.alt = s.kind; return i; }));
  clearTimeout(timer); if (run.status.endsWith('running')) timer = setTimeout(advance, 5000);
}
async function advance() { try { show(await api('/' + current.id + '/advance', {method: 'POST', body: '{}'})); list(); } catch (e) { $('ppStatus').textContent = e.message; } }
async function list() {
  try { const runs = await api(''); const el = $('ppList'); el.replaceChildren(); if (!runs.length) el.textContent = 'No runs yet.';
    runs.forEach(r => { const b = document.createElement('button'); b.textContent = `${r.title} · ${r.status}`; b.onclick = () => show(r); el.append(b); });
  } catch (e) { $('ppList').textContent = e.message; }
}
$('ppAdvance').onclick = advance;
$('ppStart').onclick = async () => {
  $('ppStatus').textContent = 'Starting…'; $('ppStatus').className = 'muted';
  try { const body = {title: $('ppTitle').value, base: {asset_id: $('ppBase').value.trim()}, reference: {asset_id: $('ppRef').value.trim()},
      target: $('ppTarget').value, product: $('ppProduct').value, approved: $('ppApprove').checked};
    if ($('ppKeep').value.trim()) body.keep = $('ppKeep').value.trim();
    show(await api('', {method: 'POST', body: JSON.stringify(body)})); $('ppStatus').textContent = ''; list();
  } catch (e) { $('ppStatus').textContent = e.message; $('ppStatus').className = 'error'; }
};
list();
