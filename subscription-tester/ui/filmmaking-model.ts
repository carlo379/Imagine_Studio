import catalog from "../static/camera-presets.json";
export type Subject={name:string;asset_id:string|null;x:number;z:number;rotation:number;pose:string;arms:number;head:number};
export type Camera={yaw:number;elevation:number;distance:number;target_x:number;target_y:number;target_z:number;lens:number};
export type Staging={camera:Camera;subjects:Subject[];ratio:string;environment:string;style:string};
export const newSubject=(index=0):Subject=>({...catalog.defaults.subjects[0],name:`Subject ${index+1}`,...(index?{x:.8,z:.4,rotation:-25}:{})});
export const initialStaging=():Staging=>JSON.parse(JSON.stringify(catalog.defaults));
export const presets:Record<string,Partial<Camera>>=Object.fromEntries(catalog.camera.map(p=>[p.name,p.patch]));
export function frameSize(ratio:string){const size=catalog.frame_sizes[ratio as keyof typeof catalog.frame_sizes];if(!size)throw Error("Choose a supported composition ratio.");return size;}
type V=[number,number,number];const rad=(n:number)=>n*Math.PI/180;
const sub=(a:V,b:V):V=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const dot=(a:V,b:V)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross=(a:V,b:V):V=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const norm=(a:V):V=>{const d=Math.hypot(...a)||1;return a.map(n=>n/d) as V;};
export function cameraPosition(c:Camera):V {return [c.target_x+Math.sin(rad(c.yaw))*Math.cos(rad(c.elevation))*c.distance,c.target_y+Math.sin(rad(c.elevation))*c.distance,c.target_z+Math.cos(rad(c.yaw))*Math.cos(rad(c.elevation))*c.distance];}
export function projector(c:Camera,width:number,height:number){const eye=cameraPosition(c),forward=norm(sub([c.target_x,c.target_y,c.target_z],eye)),right=norm(cross(forward,[0,1,0])),up=cross(right,forward),f=width*c.lens/36;return (p:V)=>{const v=sub(p,eye),depth=dot(v,forward);return depth>.12?{x:width/2+dot(v,right)*f/depth,y:height/2-dot(v,up)*f/depth,scale:f/depth,depth}:null;};}
function body(s:Subject):V[]{
 let hip=1,shoulder=1.5,head=1.77;const sit=s.pose==='sit',crouch=s.pose==='crouch',legs=sit||crouch;if(sit){hip=.75;shoulder=1.25;head=1.52;}if(crouch){hip=.48;shoulder=.98;head=1.25;}
 const reach=s.pose==='reach',fight=s.pose==='fight',walk=s.pose==='walk';const lift=Math.sin(rad(s.arms))*.42,spread=Math.cos(rad(s.arms))*.25;
 const joints:V[]=[[0,head,0],[0,shoulder,0],[0,hip,0],[-.23,shoulder,0],[.23,shoulder,0],[-.23-spread,shoulder+(reach?.22:fight?-.15:-.28)+lift,reach?.35:fight?.25:0],[.23+spread,shoulder+(reach?.22:fight?-.15:-.28)+lift,reach?.35:fight?.25:0],[-.28-spread,shoulder+(reach?.5:fight?.08:-.55)+lift*2,reach?.55:fight?.6:0],[.28+spread,shoulder+(reach?.5:fight?.08:-.55)+lift*2,reach?.55:fight?.6:0],[-.16,hip,0],[.16,hip,0],[-.18,sit?.65:crouch?.28:.5,sit?.55:crouch?.25:walk?.35:0],[.18,sit?.65:crouch?.28:.5,sit?.55:crouch?.25:walk?-.3:0],[-.22,.08,sit?.55:crouch?-.1:walk?.5:.05],[.22,.08,sit?.55:crouch?-.1:walk?-.45:.05]];
 const rotation=rad(s.rotation);return joints.map(([x,y,z])=>[s.x+x*Math.cos(rotation)+z*Math.sin(rotation),y,s.z-x*Math.sin(rotation)+z*Math.cos(rotation)] as V);
}
// A structural Canvas surface keeps the drawing code independent of the DOM.
export type CanvasSurface=Pick<HTMLCanvasElement,'width'|'height'|'getContext'>;
export function drawStage(canvas:CanvasSurface,stage:Staging,guide=true){
 const ctx=canvas.getContext('2d');if(!ctx)return;const w=canvas.width,h=canvas.height,project=projector(stage.camera,w,h);
 ctx.clearRect(0,0,w,h);const bg=ctx.createLinearGradient(0,0,0,h);bg.addColorStop(0,'#192d2b');bg.addColorStop(1,'#071513');ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);
 function line(a:V,b:V,color:string,size=1){const p=project(a),q=project(b);if(!p||!q)return;ctx!.strokeStyle=color;ctx!.lineWidth=size;ctx!.lineCap='round';ctx!.beginPath();ctx!.moveTo(p.x,p.y);ctx!.lineTo(q.x,q.y);ctx!.stroke();}
 for(let i=-8;i<=8;i++){line([i,0,-8],[i,0,8],'#31514a');line([-8,0,i],[8,0,i],'#31514a');}
 const colors=['#99e4c2','#e7b58c','#94b9ea','#c7a5db'];const order=stage.subjects.map((s,i)=>({s,i,depth:project([s.x,1,s.z])?.depth||0})).sort((a,b)=>b.depth-a.depth);
 for(const {s,i} of order){const points=body(s),p=points.map(project),color=colors[i%4];
 const center=project([s.x,0,s.z]);if(center){ctx.fillStyle='#0007';ctx.beginPath();ctx.ellipse(center.x,center.y,center.scale*.4,center.scale*.12,0,0,Math.PI*2);ctx.fill();}
 const edges=[[1,2],[1,3],[1,4],[3,5],[5,7],[4,6],[6,8],[2,9],[2,10],[9,11],[11,13],[10,12],[12,14]];
 for(const [a,b] of edges){if(p[a]&&p[b])line(points[a],points[b],color,Math.max(3,Math.min(34,(p[a]!.scale+p[b]!.scale)*.065)));}
 const torso=[p[3],p[4],p[10],p[9]];if(torso.every(Boolean)){ctx.fillStyle=color;ctx.beginPath();torso.forEach((q,j)=>j?ctx.lineTo(q!.x,q!.y):ctx.moveTo(q!.x,q!.y));ctx.closePath();ctx.fill();}
 if(p[0]){const q=p[0]!,radius=q.scale*.14;ctx.fillStyle=color;ctx.beginPath();ctx.ellipse(q.x,q.y,radius,radius*1.18,rad(s.head)*.2,0,Math.PI*2);ctx.fill();const yaw=rad(s.rotation-stage.camera.yaw+s.head);ctx.fillStyle='#19332d';ctx.beginPath();ctx.arc(q.x+Math.sin(yaw)*radius*.55,q.y-radius*.18,Math.max(2,radius*.13),0,Math.PI*2);ctx.fill();if(guide){ctx.font=`500 ${Math.max(12,w/60)}px system-ui`;ctx.textAlign='center';ctx.fillStyle=color;ctx.fillText(s.name,q.x,q.y-radius*1.8);}}
 }
 if(guide){ctx.strokeStyle='#bddacc20';ctx.lineWidth=1;for(const x of [w/3,w*2/3]){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}for(const y of [h/3,h*2/3]){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}}
}
// Both runtimes prepare and draw references here. Exports contain no text and
// therefore need no installed fonts; preview-only labels stay in the browser.
export function drawReference(canvas:CanvasSurface,stage:Staging):void {
 const {width,height}=frameSize(stage.ratio);canvas.width=width;canvas.height=height;
 // Reference exports use the same CPU raster path even when the preview is GPU accelerated.
 if(!canvas.getContext('2d',{willReadFrequently:true}))throw Error('Canvas rendering is unavailable.');
 drawStage(canvas,stage,false);
}
export function referencePNG(stage:Staging):string {
 const canvas=document.createElement('canvas');drawReference(canvas,stage);return canvas.toDataURL('image/png');
}
export function compositionPrompt(s:Staging){const c=s.camera,angle=c.elevation>60?'overhead':c.elevation>20?'high angle':c.elevation<0?'low angle':'eye level';const cast=s.subjects.map((p,i)=>`${p.asset_id?'@'+p.name:p.name}: ${p.pose} pose, subject ${i+1} in the composition reference`).join('; ');return `Create a finished cinematic image using the supplied composition reference for framing, subject positions, poses and camera angle. Replace the simple mannequins with the supplied character identities; do not reproduce mannequin materials, grid lines or labels. ${c.lens}mm lens, ${angle}, camera bearing ${Math.round(c.yaw)} degrees. ${cast}. ${s.environment?`Setting: ${s.environment}. `:''}Look: ${s.style}. Preserve each identity, scale, wardrobe and spatial relationship.`;}
export const movements=catalog.movements;
function aimFromEye(c:Camera,eye:V,target:V):Camera {const d=sub(eye,target),distance=Math.hypot(...d);return {...c,target_x:target[0],target_y:target[1],target_z:target[2],distance,yaw:Math.atan2(d[0],d[2])*180/Math.PI,elevation:Math.asin(d[1]/distance)*180/Math.PI};}
export function animatedCamera(id:string,t:number):Camera {
 let c={...initialStaging().camera,distance:6,lens:35};const fixed=cameraPosition(c);
 if(id==='push')c.distance=7-t*3;if(id==='pull')c.distance=4+t*3;if(id==='orbit')c.yaw=-35+t*80;
 if(id==='pan'||id==='panleft')c=aimFromEye(c,fixed,[(t-.5)*4*(id==='pan'?1:-1),1,0]);
 if(id==='tilt'||id==='tiltdown')c=aimFromEye(c,fixed,[0,.1+t*2*(id==='tilt'?1:-1)+(id==='tiltdown'?2:0),0]);
 if(id==='track'){c.target_x=(t-.5)*3;c.yaw=-15;}if(id==='crane'){c.elevation=8+t*40;c.distance=5+t*3;}
 if(id==='handheld')c=aimFromEye(c,[fixed[0]+Math.sin(t*22)*.045,fixed[1]+Math.cos(t*19)*.035,fixed[2]],[0,1,0]);
 if(id==='zoom')c.lens=28+Math.min(1,t*3)*60;if(id==='dollyzoom'){c.distance=4+t*4;c.lens=28*c.distance/4;}
 if(id==='whip')c=aimFromEye(c,fixed,[Math.tanh((t-.5)*18)*3,1,0]);return c;
}
