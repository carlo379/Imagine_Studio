// Previz: a deterministic three.js stage driven by a JSON spec on the song clock.
// setTime(t) always produces the same frame, so a browser preview and the headless video render agree.
import * as THREE from './vendor/three/three.module.min.js';

const POSES = {
  // Joint angles in radians. s=shoulder (x swing, z out), e=elbow bend, h=hip swing, k=knee bend, lean/tilt on torso/head.
  stand: { lean: 0, tilt: 0, sLx: 0, sLz: .15, sRx: 0, sRz: .15, eL: .1, eR: .1, hL: 0, hR: 0, kL: 0, kR: 0, drop: 0 },
  sit: { lean: .1, tilt: .05, sLx: -.6, sLz: .1, sRx: -.6, sRz: .1, eL: .9, eR: .9, hL: -1.45, hR: -1.45, kL: 1.45, kR: 1.45, drop: .5 },
  lean_in: { lean: .45, tilt: .2, sLx: -1.0, sLz: .1, sRx: -1.0, sRz: .1, eL: .7, eR: .7, hL: -1.45, hR: -1.45, kL: 1.45, kR: 1.45, drop: .5 },
  reach: { lean: .3, tilt: .1, sLx: -1.5, sLz: .05, sRx: -.3, sRz: .1, eL: .1, eR: .6, hL: -1.45, hR: -1.45, kL: 1.45, kR: 1.45, drop: .5 },
  rock: { lean: .15, tilt: -.15, sLx: -1.1, sLz: .3, sRx: -1.1, sRz: -.1, eL: 1.2, eR: 1.2, hL: -1.45, hR: -1.45, kL: 1.45, kR: 1.45, drop: .5 },
  tuck: { lean: .35, tilt: .15, sLx: -1.2, sLz: .35, sRx: -.9, sRz: -.05, eL: .5, eR: .9, hL: -1.45, hR: -1.45, kL: 1.45, kR: 1.45, drop: .5 },
  lie: { lean: 0, tilt: 0, sLx: 0, sLz: .2, sRx: 0, sRz: .2, eL: .1, eR: .1, hL: 0, hR: 0, kL: 0, kR: 0, drop: 0 },
  wave: { lean: 0, tilt: .1, sLx: 0, sLz: .15, sRx: -2.6, sRz: -.3, eL: .1, eR: .5, hL: 0, hR: 0, kL: 0, kR: 0, drop: 0 },
};
const EASE = {
  linear: (u) => u,
  in: (u) => u * u,
  out: (u) => 1 - (1 - u) * (1 - u),
  inOut: (u) => (u < .5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2),
};
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const lerp = (a, b, u) => a + (b - a) * u;
const lerpVec = (a, b, u) => a.map((v, i) => lerp(v, b[i], u));

function sampleKeys(keys, t, kind) {
  // keys: [[time, value], ...] sorted; value is a number, a vec, or a pose name.
  if (!keys || !keys.length) return undefined;
  const hold = (v) => (kind === 'pose' ? { a: v, b: v, u: 0 } : v);
  if (t <= keys[0][0]) return hold(keys[0][1]);
  if (t >= keys[keys.length - 1][0]) return hold(keys[keys.length - 1][1]);
  let i = 0;
  while (keys[i + 1][0] < t) i++;
  const [t0, v0] = keys[i], [t1, v1] = keys[i + 1];
  const u = EASE.inOut((t - t0) / Math.max(1e-6, t1 - t0));
  if (kind === 'pose') return { a: v0, b: v1, u };
  if (Array.isArray(v0)) return lerpVec(v0, v1, u);
  return lerp(v0, v1, u);
}

function mat(color, emissive = 0x000000, ei = 0, rough = .85) {
  return new THREE.MeshStandardMaterial({ color, emissive, emissiveIntensity: ei, roughness: rough, metalness: .05 });
}

function limb(len, r, material) {
  const g = new THREE.Group();
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 10), material);
  m.position.y = -len / 2;
  g.add(m);
  return g;
}

function buildStickHuman(color) {
  const root = new THREE.Group();
  const material = mat(color);
  const body = new THREE.Group();
  const pelvis = new THREE.Group();
  pelvis.position.y = 1.0;
  body.add(pelvis);
  const torso = new THREE.Group();
  pelvis.add(torso);
  const spine = new THREE.Mesh(new THREE.CylinderGeometry(.09, .11, .62, 10), material);
  spine.position.y = .31;
  torso.add(spine);
  const neck = new THREE.Group();
  neck.position.y = .66;
  torso.add(neck);
  const head = new THREE.Mesh(new THREE.SphereGeometry(.15, 20, 16), material);
  head.position.y = .13;
  neck.add(head);
  const arms = {};
  for (const side of ['L', 'R']) {
    const shoulder = new THREE.Group();
    shoulder.position.set(side === 'L' ? -.2 : .2, .58, 0);
    const upper = limb(.3, .04, material);
    shoulder.add(upper);
    const elbow = new THREE.Group();
    elbow.position.y = -.3;
    upper.add(elbow);
    elbow.add(limb(.28, .035, material));
    torso.add(shoulder);
    arms[side] = { shoulder, elbow };
  }
  const legs = {};
  for (const side of ['L', 'R']) {
    const hip = new THREE.Group();
    hip.position.set(side === 'L' ? -.09 : .09, 0, 0);
    const upper = limb(.45, .05, material);
    hip.add(upper);
    const knee = new THREE.Group();
    knee.position.y = -.45;
    upper.add(knee);
    knee.add(limb(.45, .04, material));
    pelvis.add(hip);
    legs[side] = { hip, knee };
  }
  root.add(body);
  root.userData = { kind: 'stick_human', body, pelvis, torso, neck, arms, legs };
  return root;
}

function applyPose(actor, p) {
  const u = actor.userData;
  u.pelvis.position.y = 1.0 - (p.drop || 0) * .5;
  u.torso.rotation.x = p.lean;
  u.neck.rotation.z = p.tilt;
  u.arms.L.shoulder.rotation.set(p.sLx, 0, p.sLz);
  u.arms.R.shoulder.rotation.set(p.sRx, 0, -p.sRz);
  u.arms.L.elbow.rotation.x = -p.eL;
  u.arms.R.elbow.rotation.x = -p.eR;
  u.legs.L.hip.rotation.x = p.hL;
  u.legs.R.hip.rotation.x = p.hR;
  u.legs.L.knee.rotation.x = p.kL;
  u.legs.R.knee.rotation.x = p.kR;
}

function mixPose(a, b, u) {
  const out = {};
  for (const k of Object.keys(POSES.stand)) out[k] = lerp(POSES[a][k], POSES[b][k], u);
  return out;
}

function buildOrbMachine(color) {
  const root = new THREE.Group();
  const body = new THREE.Mesh(new THREE.SphereGeometry(.32, 32, 24), mat(color, color, .25, .35));
  body.position.y = .32;
  root.add(body);
  const eyes = [];
  for (const x of [-.11, .11]) {
    const eye = new THREE.Mesh(new THREE.CircleGeometry(.055, 24), new THREE.MeshBasicMaterial({ color: 0xffffff }));
    eye.position.set(x, .05, .3);
    body.add(eye);
    eyes.push(eye);
  }
  const light = new THREE.PointLight(color, 1, 6, 1.6);
  light.position.set(0, .4, 0);
  root.add(light);
  root.userData = { kind: 'orb_machine', body, eyes, light, material: body.material };
  return root;
}

function buildActor(def) {
  const color = parseInt((def.color || '#cccccc').replace('#', ''), 16);
  let obj;
  if (def.type === 'stick_human') obj = buildStickHuman(color);
  else if (def.type === 'orb_machine') obj = buildOrbMachine(color);
  else if (def.type === 'lamp') {
    obj = new THREE.Group();
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(.09, 16, 12), new THREE.MeshBasicMaterial({ color }));
    const light = new THREE.PointLight(color, 1.2, 8, 1.5);
    obj.add(bulb, light);
    obj.userData = { kind: 'lamp', light };
  } else {
    obj = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat(color));
    obj.userData = { kind: 'box' };
  }
  obj.position.set(...(def.position || [0, 0, 0]));
  obj.rotation.set(...(def.rotation || [0, 0, 0]));
  obj.scale.set(...(def.scale || [1, 1, 1]));
  obj.userData.base = { position: obj.position.toArray(), rotation: [obj.rotation.x, obj.rotation.y, obj.rotation.z], scale: obj.scale.toArray() };
  obj.userData.id = def.id;
  return obj;
}

function buildSet(scene, set) {
  const bg = new THREE.Color(set.background || '#0b0d18');
  scene.background = bg;
  if (set.fog) scene.fog = new THREE.Fog(bg, set.fog[0], set.fog[1]);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), mat(set.floor || '#1a1c2c', 0, 0, 1));
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);
  if (set.preset === 'bedroom') {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(14, 6), mat('#232640'));
    wall.position.set(0, 3, -3.2);
    scene.add(wall);
    const win = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.6), new THREE.MeshBasicMaterial({ color: 0x24305e }));
    win.position.set(2.4, 2.4, -3.18);
    scene.add(win);
    const bed = new THREE.Mesh(new THREE.BoxGeometry(2.2, .5, 1.3), mat('#34385a'));
    bed.position.set(-.8, .3, -1.6);
    scene.add(bed);
    const pillow = new THREE.Mesh(new THREE.BoxGeometry(.6, .16, .8), mat('#4b4f78'));
    pillow.position.set(-1.6, .63, -1.6);
    scene.add(pillow);
    const stand = new THREE.Mesh(new THREE.BoxGeometry(.6, .7, .6), mat('#2b2e4a'));
    stand.position.set(.9, .35, -2.6);
    scene.add(stand);
  } else if (set.preset === 'street') {
    for (let i = 0; i < 14; i++) {
      const h = 2 + ((i * 37) % 7);
      const b = new THREE.Mesh(new THREE.BoxGeometry(1.6, h, 1.6), mat('#1c1f33'));
      b.position.set((i - 7) * 2.2, h / 2, -6 - (i % 3));
      scene.add(b);
    }
  } else {
    const grid = new THREE.GridHelper(60, 60, 0x303660, 0x1d2040);
    scene.add(grid);
  }
  scene.add(new THREE.AmbientLight(new THREE.Color(set.ambient || '#8088c0'), .5));
  const key = new THREE.DirectionalLight(new THREE.Color(set.key || '#b8c4ff'), .9);
  key.position.set(3, 6, 4);
  scene.add(key);
  return { key };
}

export async function boot(spec, canvasParent) {
  const W = spec.width, H = spec.height;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  const scene = new THREE.Scene();
  const rig = buildSet(scene, spec.set || {});
  const camera = new THREE.PerspectiveCamera(40, W / H, .05, 100);
  const actors = {};
  for (const def of spec.actors || []) {
    actors[def.id] = buildActor(def);
    scene.add(actors[def.id]);
  }
  const frame = document.createElement('canvas');
  frame.width = W;
  frame.height = H;
  const ctx = frame.getContext('2d');
  const shots = (spec.shots || []).slice().sort((a, b) => a.start - b.start);
  const lyrics = spec.lyrics || [];

  function shotAt(t) {
    let found = shots[0];
    for (const s of shots) if (t >= s.start) found = s;
    return found;
  }

  function applyCamera(shot, t) {
    const dur = Math.max(1e-3, shot.end - shot.start);
    const u = clamp((t - shot.start) / dur, 0, 1);
    const c = shot.camera || {};
    const e = (EASE[c.ease] || EASE.inOut)(u);
    const from = c.from || [0, 1.5, 5];
    const pos = lerpVec(from, c.to || from, e);
    const look = lerpVec(c.look || [0, 1, 0], c.look_to || c.look || [0, 1, 0], e);
    camera.position.set(...pos);
    camera.lookAt(...look);
    camera.fov = lerp(c.fov || 40, c.fov_to || c.fov || 40, e);
    camera.updateProjectionMatrix();
    return u;
  }

  function applyActors(t) {
    for (const [id, actor] of Object.entries(actors)) {
      const base = actor.userData.base;
      actor.position.set(...base.position);
      actor.rotation.set(...base.rotation);
      actor.scale.set(...base.scale);
      actor.visible = true;
      if (actor.userData.kind === 'stick_human') applyPose(actor, POSES.stand);
      if (actor.userData.kind === 'orb_machine') {
        actor.userData.light.intensity = 1;
        actor.userData.material.emissiveIntensity = .25;
        for (const eye of actor.userData.eyes) eye.scale.set(1, 0.02, 1);
      }
      for (const tr of (spec.tracks || []).filter((x) => x.actor === id)) {
        if (!tr.keys.length || t < tr.keys[0][0]) continue;   // a track takes effect from its first key
        const v = sampleKeys(tr.keys, t, tr.prop);
        if (v === undefined) continue;
        if (tr.prop === 'pos') actor.position.set(...v);
        else if (tr.prop === 'rot') actor.rotation.set(...v);
        else if (tr.prop === 'scale') actor.scale.set(...(Array.isArray(v) ? v : [v, v, v]));
        else if (tr.prop === 'visible') actor.visible = v >= .5;
        else if (tr.prop === 'pose' && actor.userData.kind === 'stick_human') applyPose(actor, mixPose(v.a, v.b, v.u));
        else if (tr.prop === 'glow' && actor.userData.light) {
          actor.userData.light.intensity = v * 2;
          if (actor.userData.material) actor.userData.material.emissiveIntensity = .1 + v * .8;
        } else if (tr.prop === 'eyes' && actor.userData.eyes) for (const eye of actor.userData.eyes) eye.scale.set(1, Math.max(.02, v), 1);
      }
    }
  }

  function overlay(t, shot) {
    ctx.drawImage(renderer.domElement, 0, 0, W, H);
    const px = Math.round(W / 36);
    ctx.font = `600 ${px}px -apple-system, Helvetica, Arial, sans-serif`;
    ctx.textBaseline = 'top';
    ctx.fillStyle = 'rgba(0,0,0,.55)';
    ctx.fillRect(0, 0, W, px * 2.1);
    ctx.fillStyle = '#ffd84a';
    const label = `PREVIZ  ${shot ? shot.id : ''}  ${shot && shot.kind ? shot.kind : ''}`;
    ctx.fillText(label, px * .6, px * .5);
    const tc = `${t.toFixed(2)}s`;
    ctx.fillStyle = '#ffffff';
    ctx.fillText(tc, W - ctx.measureText(tc).width - px * .6, px * .5);
    const line = lyrics.find((l) => t >= l.start && t <= l.end + .25);
    if (line) {
      const words = line.text.split(/\s+/);
      const per = (line.end - line.start) / words.length;
      const size = Math.round(W / 15);
      ctx.font = `700 ${size}px -apple-system, Helvetica, Arial, sans-serif`;
      ctx.textBaseline = 'alphabetic';
      const rows = [];
      let row = [];
      for (const w of words) {
        const trial = [...row, w].join(' ');
        if (row.length && ctx.measureText(trial).width > W * .86) { rows.push(row); row = [w]; } else row.push(w);
      }
      rows.push(row);
      let index = 0;
      const y0 = H - size * 1.4 * rows.length - H * .05;
      rows.forEach((r, ri) => {
        let x = (W - ctx.measureText(r.join(' ')).width) / 2;
        for (const w of r) {
          const lit = t >= line.start + index * per;
          ctx.lineWidth = size / 8;
          ctx.strokeStyle = 'rgba(0,0,0,.9)';
          ctx.strokeText(w, x, y0 + ri * size * 1.3 + size);
          ctx.fillStyle = lit ? '#ffd84a' : '#ffffff';
          ctx.fillText(w, x, y0 + ri * size * 1.3 + size);
          x += ctx.measureText(w + ' ').width;
          index++;
        }
      });
    }
  }

  function setTime(t) {
    const shot = shotAt(t);
    if (shot) applyCamera(shot, t);
    applyActors(t);
    renderer.render(scene, camera);
    overlay(t, shot);
    return shot ? shot.id : null;
  }

  canvasParent && canvasParent.appendChild(frame);
  const api = {
    ready: true, duration: spec.duration, fps: spec.fps, width: W, height: H, shots, frame, setTime,
    jpeg: (t, q = .9) => { setTime(t); return frame.toDataURL('image/jpeg', q).split(',')[1]; },
    // A clean video frame (no label, timecode or lyrics) for a code-made shot in the final cut.
    cleanJpeg: (t, q = .92) => {
      setTime(t);
      const c = document.createElement('canvas');
      c.width = W; c.height = H;
      c.getContext('2d').drawImage(renderer.domElement, 0, 0, W, H);
      return c.toDataURL('image/jpeg', q).split(',')[1];
    },
    // A clean still for composition reference: the 3D stage only, no PREVIZ label, timecode or lyric text, so no
    // words can leak into an image request.
    still: (t) => {
      setTime(t);
      const c = document.createElement('canvas');
      c.width = W; c.height = H;
      c.getContext('2d').drawImage(renderer.domElement, 0, 0, W, H);
      return c.toDataURL('image/png').split(',')[1];
    },
    gl: renderer.getContext().getParameter(renderer.getContext().VERSION),
  };
  window.previz = api;
  return api;
}
