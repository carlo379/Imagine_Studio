import {build,transform} from 'esbuild';
import {mkdir,writeFile,readFile,readdir,rename,unlink} from 'node:fs/promises';
import path from 'node:path';

// Content-addressed chunks allow long-lived caching without stale app updates.
// Compile legacy entry scripts too; their shared global names stay unchanged.
await Promise.all((await readdir('static')).filter(name=>name.endsWith('.js')&&name!=='production.js').map(async name=>transform(await readFile('static/'+name,'utf8'),{loader:'js',target:'es2022'})));
const result=await build({entryPoints:['ui/production.tsx'],bundle:true,minify:true,
 target:'es2022',format:'esm',splitting:true,outdir:'static/build',entryNames:'[name]-[hash]',
 chunkNames:'chunks/[name]-[hash]',metafile:true});
const entry=Object.entries(result.metafile.outputs).find(([,info])=>info.entryPoint==='ui/production.tsx')?.[0];
if(!entry)throw Error('Production entry point missing from build.');
await mkdir('static/build',{recursive:true});
await writeFile('static/build/manifest.tmp',JSON.stringify({entry:'/'+entry,files:Object.keys(result.metafile.outputs).map(file=>'/'+file)},null,2)+'\n');
await rename('static/build/manifest.tmp','static/build/manifest.json');
await writeFile('static/production.js',`// Compatibility entry; index.html selects the hashed build.\nimport './${path.relative('static',entry).split(path.sep).join('/')}';\n`);

// Do not distribute retired bundles that may contain removed example content.
const keep=new Set(Object.keys(result.metafile.outputs).map(file=>path.resolve(file)));
for(const dir of ['static/build','static/build/chunks']){
 for(const name of await readdir(dir)){
  const file=path.join(dir,name);
  if(name.endsWith('.js')&&!keep.has(path.resolve(file)))await unlink(file);
 }
}
