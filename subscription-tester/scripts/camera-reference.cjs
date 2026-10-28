'use strict';
// No DOM, browser, font discovery, asset loading or provider transport.
const {violation} = require('./camera-isolation.cjs').install();
process.env.DISABLE_SYSTEM_FONTS_LOAD = '1';

function fail(code) {
  process.stderr.write(JSON.stringify({code}));
  process.exitCode = 1;
}
try {
  if (Number(process.versions.node.split('.')[0]) < 22) throw Object.assign(new Error(), {code:'camera_renderer_unavailable'});
  let canvas;
  try { canvas = require('@napi-rs/canvas'); }
  catch (_) { throw Object.assign(new Error(), {code:'camera_renderer_unavailable'}); }
  // Future accidental text imports must fail rather than consult OS fonts.
  for (const name of ['loadSystemFonts','loadFontsFromDir','registerFromPath']) canvas.GlobalFonts[name] = violation;
  canvas.CanvasElement.prototype.fillText = violation;
  canvas.CanvasElement.prototype.strokeText = violation;
  const {drawReference,frameSize} = require('../static/camera-renderer.cjs');
  let chunks=[],length=0;
  process.stdin.on('data',chunk => {
    length += chunk.length;
    if (length > 65536) { fail('camera_renderer_failed'); process.stdin.destroy(); }
    else chunks.push(chunk);
  });
  process.stdin.on('end',() => {
    if (process.exitCode) return;
    try {
      const staging = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      const {width,height} = frameSize(staging.ratio);
      const surface = canvas.createCanvas(width,height);
      drawReference(surface,staging);
      const png = surface.toBuffer('image/png');
      if (png.length > 3 * 1024 * 1024) throw new Error();
      process.stdout.write(png);
    } catch (error) { fail(error.code === 'camera_renderer_isolation' ? error.code : 'camera_renderer_failed'); }
  });
  process.stdin.on('error',() => fail('camera_renderer_failed'));
} catch (error) {
  fail(['camera_renderer_unavailable','camera_renderer_isolation'].includes(error.code) ? error.code : 'camera_renderer_failed');
}
