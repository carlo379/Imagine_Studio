"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// ui/camera-renderer.ts
var camera_renderer_exports = {};
__export(camera_renderer_exports, {
  compositionPrompt: () => compositionPrompt,
  drawReference: () => drawReference,
  drawStage: () => drawStage,
  frameSize: () => frameSize,
  initialStaging: () => initialStaging,
  referencePNG: () => referencePNG
});
module.exports = __toCommonJS(camera_renderer_exports);

// static/camera-presets.json
var camera_presets_default = {
  version: 1,
  defaults: {
    camera: {
      yaw: 0,
      elevation: 8,
      distance: 5,
      target_x: 0,
      target_y: 1,
      target_z: 0,
      lens: 35
    },
    subjects: [
      {
        name: "Subject 1",
        asset_id: null,
        x: -0.6,
        z: 0,
        rotation: 0,
        pose: "stand",
        arms: 0,
        head: 0
      }
    ],
    ratio: "16:9",
    environment: "",
    style: "Cinematic natural light"
  },
  frame_sizes: {
    "16:9": {
      width: 1280,
      height: 720
    },
    "9:16": {
      width: 720,
      height: 1280
    },
    "1:1": {
      width: 1280,
      height: 1280
    }
  },
  camera: [
    {
      id: "wide",
      name: "Wide",
      patch: {
        distance: 7,
        lens: 28,
        elevation: 8
      }
    },
    {
      id: "medium",
      name: "Medium",
      patch: {
        distance: 4,
        lens: 50,
        elevation: 5
      }
    },
    {
      id: "close-up",
      name: "Close-up",
      patch: {
        distance: 2.1,
        lens: 85,
        target_y: 1.5,
        elevation: 0
      }
    },
    {
      id: "low-angle",
      name: "Low angle",
      patch: {
        distance: 4,
        lens: 35,
        target_y: 1,
        elevation: -8
      }
    },
    {
      id: "high-angle",
      name: "High angle",
      patch: {
        distance: 5,
        lens: 35,
        elevation: 40
      }
    },
    {
      id: "over-shoulder",
      name: "Over shoulder",
      patch: {
        distance: 3.5,
        lens: 50,
        yaw: 35,
        target_y: 1.4
      }
    },
    {
      id: "birds-eye",
      name: "Bird\u2019s eye",
      patch: {
        distance: 7,
        lens: 28,
        elevation: 80,
        target_y: 0.1
      }
    }
  ],
  movements: [
    {
      id: "static",
      name: "Locked off",
      group: "Essentials",
      effect: "Let the performance lead.",
      prompt: "A locked-off camera. Fixed framing throughout; no pan, tilt, zoom or drift."
    },
    {
      id: "push",
      name: "Slow push-in",
      group: "Essentials",
      effect: "Draw attention to a realization.",
      prompt: "A smooth, slow physical dolly-in toward the subject, maintaining the same lens and continuous focus. Gentle foreground parallax."
    },
    {
      id: "pull",
      name: "Pull back",
      group: "Essentials",
      effect: "Reveal the larger world.",
      prompt: "A smooth physical dolly-out from the subject to reveal the surroundings. Keep the subject anchored in frame as the environment opens up."
    },
    {
      id: "pan",
      name: "Pan right",
      group: "Essentials",
      effect: "Follow a reveal across the scene.",
      prompt: "A controlled pan to the right from a fixed camera position. Smooth constant speed; no lateral camera travel."
    },
    {
      id: "panleft",
      name: "Pan left",
      group: "Essentials",
      effect: "Reveal what lies beyond the frame.",
      prompt: "A controlled pan to the left from a fixed camera position. Smooth constant speed; no lateral camera travel."
    },
    {
      id: "tilt",
      name: "Tilt up",
      group: "Essentials",
      effect: "Reveal height or scale.",
      prompt: "A slow upward tilt from a fixed camera position, revealing the subject from lower details to the upper frame."
    },
    {
      id: "tiltdown",
      name: "Tilt down",
      group: "Essentials",
      effect: "Discover a detail below.",
      prompt: "A slow downward tilt from a fixed camera position, revealing the lower scene with steady smooth movement."
    },
    {
      id: "track",
      name: "Tracking shot",
      group: "Cinematic",
      effect: "Travel alongside the action.",
      prompt: "A smooth lateral tracking shot moving alongside the subject, matching their pace. Maintain consistent framing with clear background parallax."
    },
    {
      id: "orbit",
      name: "Orbit",
      group: "Cinematic",
      effect: "Show a subject from a new side.",
      prompt: "A smooth quarter-circle orbit around the subject, keeping them centered. Preserve the world geometry and reveal the changing background naturally."
    },
    {
      id: "crane",
      name: "Crane rise",
      group: "Cinematic",
      effect: "Open up the scene from above.",
      prompt: "A continuous crane rise upward and gently backward, transitioning from eye level to an elevated wide view. Keep the horizon stable."
    },
    {
      id: "handheld",
      name: "Handheld",
      group: "Expressive",
      effect: "Add a human sense of presence.",
      prompt: "Subtle handheld camera movement with natural micro-sway. Controlled and readable, without excessive shake or sudden reframing."
    },
    {
      id: "zoom",
      name: "Crash zoom",
      group: "Expressive",
      effect: "Land on an urgent detail.",
      prompt: "A rapid optical zoom-in toward the subject, then settle into a stable close-up. The camera remains in place; no physical dolly movement."
    },
    {
      id: "dollyzoom",
      name: "Dolly zoom",
      group: "Expressive",
      effect: "Create a moment of disorientation.",
      prompt: "A deliberate dolly zoom: move the camera backward while optically zooming in, keeping the subject the same size as background perspective compresses."
    },
    {
      id: "whip",
      name: "Whip pan",
      group: "Expressive",
      effect: "Move abruptly to a new focus.",
      prompt: "A fast whip pan to the right with brief natural motion blur, then settle smoothly on the new subject. One continuous shot."
    }
  ]
};

// ui/filmmaking-model.ts
var initialStaging = () => JSON.parse(JSON.stringify(camera_presets_default.defaults));
var presets = Object.fromEntries(camera_presets_default.camera.map((p) => [p.name, p.patch]));
function frameSize(ratio) {
  const size = camera_presets_default.frame_sizes[ratio];
  if (!size) throw Error("Choose a supported composition ratio.");
  return size;
}
var rad = (n) => n * Math.PI / 180;
var sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
var dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
var cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
var norm = (a) => {
  const d = Math.hypot(...a) || 1;
  return a.map((n) => n / d);
};
function cameraPosition(c) {
  return [c.target_x + Math.sin(rad(c.yaw)) * Math.cos(rad(c.elevation)) * c.distance, c.target_y + Math.sin(rad(c.elevation)) * c.distance, c.target_z + Math.cos(rad(c.yaw)) * Math.cos(rad(c.elevation)) * c.distance];
}
function projector(c, width, height) {
  const eye = cameraPosition(c), forward = norm(sub([c.target_x, c.target_y, c.target_z], eye)), right = norm(cross(forward, [0, 1, 0])), up = cross(right, forward), f = width * c.lens / 36;
  return (p) => {
    const v = sub(p, eye), depth = dot(v, forward);
    return depth > 0.12 ? { x: width / 2 + dot(v, right) * f / depth, y: height / 2 - dot(v, up) * f / depth, scale: f / depth, depth } : null;
  };
}
function body(s) {
  let hip = 1, shoulder = 1.5, head = 1.77;
  const sit = s.pose === "sit", crouch = s.pose === "crouch", legs = sit || crouch;
  if (sit) {
    hip = 0.75;
    shoulder = 1.25;
    head = 1.52;
  }
  if (crouch) {
    hip = 0.48;
    shoulder = 0.98;
    head = 1.25;
  }
  const reach = s.pose === "reach", fight = s.pose === "fight", walk = s.pose === "walk";
  const lift = Math.sin(rad(s.arms)) * 0.42, spread = Math.cos(rad(s.arms)) * 0.25;
  const joints = [[0, head, 0], [0, shoulder, 0], [0, hip, 0], [-0.23, shoulder, 0], [0.23, shoulder, 0], [-0.23 - spread, shoulder + (reach ? 0.22 : fight ? -0.15 : -0.28) + lift, reach ? 0.35 : fight ? 0.25 : 0], [0.23 + spread, shoulder + (reach ? 0.22 : fight ? -0.15 : -0.28) + lift, reach ? 0.35 : fight ? 0.25 : 0], [-0.28 - spread, shoulder + (reach ? 0.5 : fight ? 0.08 : -0.55) + lift * 2, reach ? 0.55 : fight ? 0.6 : 0], [0.28 + spread, shoulder + (reach ? 0.5 : fight ? 0.08 : -0.55) + lift * 2, reach ? 0.55 : fight ? 0.6 : 0], [-0.16, hip, 0], [0.16, hip, 0], [-0.18, sit ? 0.65 : crouch ? 0.28 : 0.5, sit ? 0.55 : crouch ? 0.25 : walk ? 0.35 : 0], [0.18, sit ? 0.65 : crouch ? 0.28 : 0.5, sit ? 0.55 : crouch ? 0.25 : walk ? -0.3 : 0], [-0.22, 0.08, sit ? 0.55 : crouch ? -0.1 : walk ? 0.5 : 0.05], [0.22, 0.08, sit ? 0.55 : crouch ? -0.1 : walk ? -0.45 : 0.05]];
  const rotation = rad(s.rotation);
  return joints.map(([x, y, z]) => [s.x + x * Math.cos(rotation) + z * Math.sin(rotation), y, s.z - x * Math.sin(rotation) + z * Math.cos(rotation)]);
}
function drawStage(canvas, stage, guide = true) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width, h = canvas.height, project = projector(stage.camera, w, h);
  ctx.clearRect(0, 0, w, h);
  const bg = ctx.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, "#192d2b");
  bg.addColorStop(1, "#071513");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  function line(a, b, color, size = 1) {
    const p = project(a), q = project(b);
    if (!p || !q) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = size;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(q.x, q.y);
    ctx.stroke();
  }
  for (let i = -8; i <= 8; i++) {
    line([i, 0, -8], [i, 0, 8], "#31514a");
    line([-8, 0, i], [8, 0, i], "#31514a");
  }
  const colors = ["#99e4c2", "#e7b58c", "#94b9ea", "#c7a5db"];
  const order = stage.subjects.map((s, i) => ({ s, i, depth: project([s.x, 1, s.z])?.depth || 0 })).sort((a, b) => b.depth - a.depth);
  for (const { s, i } of order) {
    const points = body(s), p = points.map(project), color = colors[i % 4];
    const center = project([s.x, 0, s.z]);
    if (center) {
      ctx.fillStyle = "#0007";
      ctx.beginPath();
      ctx.ellipse(center.x, center.y, center.scale * 0.4, center.scale * 0.12, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    const edges = [[1, 2], [1, 3], [1, 4], [3, 5], [5, 7], [4, 6], [6, 8], [2, 9], [2, 10], [9, 11], [11, 13], [10, 12], [12, 14]];
    for (const [a, b] of edges) {
      if (p[a] && p[b]) line(points[a], points[b], color, Math.max(3, Math.min(34, (p[a].scale + p[b].scale) * 0.065)));
    }
    const torso = [p[3], p[4], p[10], p[9]];
    if (torso.every(Boolean)) {
      ctx.fillStyle = color;
      ctx.beginPath();
      torso.forEach((q, j) => j ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y));
      ctx.closePath();
      ctx.fill();
    }
    if (p[0]) {
      const q = p[0], radius = q.scale * 0.14;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.ellipse(q.x, q.y, radius, radius * 1.18, rad(s.head) * 0.2, 0, Math.PI * 2);
      ctx.fill();
      const yaw = rad(s.rotation - stage.camera.yaw + s.head);
      ctx.fillStyle = "#19332d";
      ctx.beginPath();
      ctx.arc(q.x + Math.sin(yaw) * radius * 0.55, q.y - radius * 0.18, Math.max(2, radius * 0.13), 0, Math.PI * 2);
      ctx.fill();
      if (guide) {
        ctx.font = `500 ${Math.max(12, w / 60)}px system-ui`;
        ctx.textAlign = "center";
        ctx.fillStyle = color;
        ctx.fillText(s.name, q.x, q.y - radius * 1.8);
      }
    }
  }
  if (guide) {
    ctx.strokeStyle = "#bddacc20";
    ctx.lineWidth = 1;
    for (const x of [w / 3, w * 2 / 3]) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (const y of [h / 3, h * 2 / 3]) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
  }
}
function drawReference(canvas, stage) {
  const { width, height } = frameSize(stage.ratio);
  canvas.width = width;
  canvas.height = height;
  if (!canvas.getContext("2d", { willReadFrequently: true })) throw Error("Canvas rendering is unavailable.");
  drawStage(canvas, stage, false);
}
function referencePNG(stage) {
  const canvas = document.createElement("canvas");
  drawReference(canvas, stage);
  return canvas.toDataURL("image/png");
}
function compositionPrompt(s) {
  const c = s.camera, angle = c.elevation > 60 ? "overhead" : c.elevation > 20 ? "high angle" : c.elevation < 0 ? "low angle" : "eye level";
  const cast = s.subjects.map((p, i) => `${p.asset_id ? "@" + p.name : p.name}: ${p.pose} pose, subject ${i + 1} in the composition reference`).join("; ");
  return `Create a finished cinematic image using the supplied composition reference for framing, subject positions, poses and camera angle. Replace the simple mannequins with the supplied character identities; do not reproduce mannequin materials, grid lines or labels. ${c.lens}mm lens, ${angle}, camera bearing ${Math.round(c.yaw)} degrees. ${cast}. ${s.environment ? `Setting: ${s.environment}. ` : ""}Look: ${s.style}. Preserve each identity, scale, wardrobe and spatial relationship.`;
}
var movements = camera_presets_default.movements;
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  compositionPrompt,
  drawReference,
  drawStage,
  frameSize,
  initialStaging,
  referencePNG
});
