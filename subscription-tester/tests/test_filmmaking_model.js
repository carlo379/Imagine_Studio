const assert=require('node:assert/strict'),esbuild=require('esbuild');
const out=esbuild.buildSync({entryPoints:['ui/filmmaking-model.ts'],bundle:true,write:false,platform:'node',format:'cjs'}).outputFiles[0].text;
const mod={exports:{}};new Function('module','exports',out)(mod,mod.exports);
const {projector,initialStaging,cameraPosition,animatedCamera,movements,compositionPrompt,presets,frameSize,referencePNG}=mod.exports;
const catalog=require('../static/camera-presets.json');
assert.deepEqual(initialStaging(),catalog.defaults);assert.deepEqual(movements,catalog.movements);
assert.deepEqual(presets,Object.fromEntries(catalog.camera.map(p=>[p.name,p.patch])));
for(const [ratio,size] of Object.entries(catalog.frame_sizes))assert.deepEqual(frameSize(ratio),size);
assert.throws(()=>frameSize('4:3'),/supported/);
const original=initialStaging();original.camera.lens=120;assert.equal(initialStaging().camera.lens,35);
let labels=0,thirds=0,options=null,exported=null;
const ctx=new Proxy({createLinearGradient:()=>({addColorStop(){}}),fillText(){labels++;},get strokeStyle(){return '';},set strokeStyle(value){if(value==='#bddacc20')thirds++;}}, {get:(o,k)=>k in o?o[k]:()=>{}});
global.document={createElement:()=>({width:0,height:0,getContext(kind,opt){if(opt)options=opt;return ctx;},toDataURL(mime){exported={width:this.width,height:this.height,mime};return 'data:image/png;base64,fixture';}})};
for(const ratio of Object.keys(catalog.frame_sizes)){const stage=initialStaging();stage.ratio=ratio;assert.equal(referencePNG(stage),'data:image/png;base64,fixture');assert.deepEqual(exported,{...catalog.frame_sizes[ratio],mime:'image/png'});}
assert.deepEqual(options,{willReadFrequently:true});assert.equal(labels,0);assert.equal(thirds,0);
delete global.document;
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8);
const c=initialStaging().camera,project=projector(c,1280,720),center=project([c.target_x,c.target_y,c.target_z]);near(center.x,640);near(center.y,360);assert.equal(project(cameraPosition(c)),null);
for(const id of ['pan','panleft','tilt','tiltdown','whip']){const a=cameraPosition(animatedCamera(id,0)),b=cameraPosition(animatedCamera(id,1));a.forEach((n,i)=>near(n,b[i]));assert.notDeepEqual(animatedCamera(id,0),animatedCamera(id,1));}
const pushStart=animatedCamera('push',0),pushEnd=animatedCamera('push',1);assert.equal(pushStart.lens,pushEnd.lens);assert.ok(pushEnd.distance<pushStart.distance);
const zoomStart=animatedCamera('zoom',0),zoomEnd=animatedCamera('zoom',1);assert.deepEqual(cameraPosition(zoomStart),cameraPosition(zoomEnd));assert.ok(zoomEnd.lens>zoomStart.lens);
const dollyStart=animatedCamera('dollyzoom',0),dollyEnd=animatedCamera('dollyzoom',1);near(dollyStart.lens/dollyStart.distance,dollyEnd.lens/dollyEnd.distance);
for(const m of movements)for(const t of [0,.5,1])assert.ok(Object.values(animatedCamera(m.id,t)).every(Number.isFinite));
assert.equal(new Set(movements.map(m=>m.id)).size,14);
const s=initialStaging();s.subjects[0].asset_id='asset';s.subjects[0].name='SampleHero';assert.match(compositionPrompt(s),/@SampleHero/);
console.log('Perspective, fixed-position pans/tilts, dolly/zoom differences, finite motion and identity prompts pass.');
