// Headless previz render: serves static/, drives a browser over the DevTools protocol, captures one JPEG per frame
// from the deterministic three.js stage, and pipes them to FFmpeg with the song. Local only; no network, no provider.
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith('--') ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.resolve(here, '../static');
const spec = JSON.parse(fs.readFileSync(args.spec, 'utf8'));
const fps = spec.fps, start = Number(args.start || 0), end = Math.min(Number(args.end || spec.duration), spec.duration);
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json' };

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  if (url.pathname === '/spec.json') { res.writeHead(200, { 'content-type': 'application/json' }); return res.end(JSON.stringify(spec)); }
  const file = path.resolve(staticDir, '.' + decodeURIComponent(url.pathname).replace(/^\/static\//, '/'));
  if (!file.startsWith(staticDir + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': mime[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'previz-'));
const browser = spawn(args.browser, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--disable-sync', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
  `--window-size=${spec.width},${spec.height}`, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
let cleaned = false;
const removeProfile = () => { try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 8, retryDelay: 100 }); } catch { /* a leftover temp folder must never fail a render */ } };
const cleanup = () => { if (cleaned) return; cleaned = true; try { browser.kill('SIGKILL'); } catch {} server.close(); removeProfile(); };
const stopBrowser = async () => { cleaned = true; const gone = new Promise((r) => browser.once('exit', r)); try { browser.kill('SIGKILL'); } catch {} await Promise.race([gone, new Promise((r) => setTimeout(r, 3000))]); server.close(); removeProfile(); };
process.on('exit', cleanup);
const fail = (m) => { console.error(m); cleanup(); process.exit(1); };

async function devtoolsPort() {
  const f = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100; i++) { if (fs.existsSync(f)) return Number(fs.readFileSync(f, 'utf8').split('\n')[0]); await new Promise((r) => setTimeout(r, 100)); }
  fail('The browser did not start its debugging port.');
}
const dport = await devtoolsPort();
const targets = await (await fetch(`http://127.0.0.1:${dport}/json/list`)).json();
let page = targets.find((t) => t.type === 'page');
if (!page) page = await (await fetch(`http://127.0.0.1:${dport}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = () => j(new Error('devtools socket')); });
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}) => new Promise((r) => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
const evalJs = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) fail('Page error: ' + JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
  return r.result?.result?.value;
};

await send('Page.enable');

if (args.svg) {
  // Plate mode: rasterise an SVG through <img> (scripts and external resources never run or load there).
  const svg = fs.readFileSync(args.svg, 'utf8');
  const html = `<!doctype html><body style="margin:0;background:#000"><canvas id=c width=${spec.width} height=${spec.height}></canvas><script>
    const img = new Image();
    img.onload = () => { document.getElementById('c').getContext('2d').drawImage(img, 0, 0, ${spec.width}, ${spec.height}); window.done = document.getElementById('c').toDataURL('image/png').split(',')[1]; };
    img.onerror = () => { window.done = 'ERROR'; };
    img.src = 'data:image/svg+xml;base64,' + ${JSON.stringify(Buffer.from(svg).toString('base64'))};
  </script>`;
  await send('Page.navigate', { url: 'data:text/html;base64,' + Buffer.from(html).toString('base64') });
  let png = null;
  for (let i = 0; i < 200 && !png; i++) { await new Promise((r) => setTimeout(r, 100)); png = await evalJs('window.done || null'); }
  if (!png || png === 'ERROR') fail('The SVG plate did not render.');
  fs.writeFileSync(args.out, Buffer.from(png, 'base64'));
  console.log('done plate');
  await stopBrowser();
  process.exit(0);
}
await send('Page.navigate', { url: `http://127.0.0.1:${port}/previz.html?spec=/spec.json` });
let ready = false;
for (let i = 0; i < 200 && !ready; i++) { await new Promise((r) => setTimeout(r, 100)); ready = await evalJs('!!(window.previz && window.previz.ready)'); }
if (!ready) fail('The previz stage did not start (WebGL may be unavailable in this browser).');

if (args.stills) {
  // Still mode: one clean PNG per requested {name, t}; no video, no audio.
  const wanted = JSON.parse(fs.readFileSync(args.stills, 'utf8'));
  fs.mkdirSync(args['out-dir'], { recursive: true });
  for (const s of wanted) {
    if (!/^[a-z0-9_-]{1,40}$/i.test(s.name)) fail('Bad still name: ' + s.name);
    const b64 = await evalJs(`window.previz.still(${Number(s.t).toFixed(5)})`);
    fs.writeFileSync(path.join(args['out-dir'], s.name + '.png'), Buffer.from(b64, 'base64'));
  }
  console.log(`done ${wanted.length} stills`);
  await stopBrowser();
  process.exit(0);
}

const frames = Math.max(1, Math.round((end - start) * fps));
const ff = ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-'];
if (args.audio) ff.push('-ss', String(start), '-t', String(end - start), '-i', args.audio);
ff.push('-map', '0:v', ...(args.audio ? ['-map', '1:a'] : []), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-r', String(fps));
if (args.audio) ff.push('-c:a', 'aac', '-b:a', '192k', '-shortest');
ff.push('-movflags', '+faststart', args.out);
const enc = spawn(args.ffmpeg || 'ffmpeg', ff, { stdio: ['pipe', 'ignore', 'pipe'] });
let ffErr = ''; enc.stderr.on('data', (d) => (ffErr += d));
const done = new Promise((r) => enc.on('close', r));
for (let i = 0; i < frames; i++) {
  const b64 = await evalJs(`window.previz.${args.clean ? 'cleanJpeg' : 'jpeg'}(${(start + i / fps).toFixed(5)}, 0.92)`);
  if (!enc.stdin.write(Buffer.from(b64, 'base64'))) await new Promise((r) => enc.stdin.once('drain', r));
  if (i % 120 === 0) console.log(`frame ${i}/${frames}`);
}
enc.stdin.end();
const code = await done;
if (code) fail('FFmpeg failed: ' + ffErr.slice(-300));
console.log(`done ${frames} frames`);
await stopBrowser();
process.exit(0);
