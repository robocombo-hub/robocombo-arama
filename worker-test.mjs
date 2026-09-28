import fs from 'node:fs'; import http from 'node:http';
import {sahteVektor} from './sahte-ai.mjs';
const SITE=new URL('../site/',import.meta.url).pathname;
const meta=JSON.parse(fs.readFileSync(SITE+'meta.json'));
// Workers ortamini taklit et
const srv=http.createServer((q,r)=>{ const f=SITE+q.url.split('?')[0].slice(1); if(!fs.existsSync(f)){r.writeHead(404);return r.end();} r.writeHead(200); r.end(fs.readFileSync(f)); }).listen(8790);
const onb=new Map(); globalThis.caches={default:{match:async k=>onb.get(k.url)?.clone(), put:async(k,r)=>{onb.set(k.url,r);} }};
const {default:W}=await import('../worker/worker.js');
let aiCagri=0;
const env={VERI_URL:'http://127.0.0.1:8790', AI:{run:async(m,{text})=>{aiCagri++; return {shape:[text.length,1024],data:text.map(sahteVektor)};}}};
const ctx={waitUntil:p=>p};
async function sor(q,origin='https://l0v8l-robocombo.myikas.com'){ const r=await W.fetch(new Request(`https://w.dev/embed?v=${meta.surum}&q=${encodeURIComponent(q)}`,{headers:{Origin:origin}}),env,ctx); return [r.status,r.headers.get('access-control-allow-origin'),await r.json()]; }
let [d,o,j]=await sor('arduino uno'); console.log('durum',d,'cors',o,'boyut',j.k,j.e.length,'norm',Math.hypot(...j.e).toFixed(3));
// Tarayicidaki hesabin aynisi: urun vektorleriyle benzerlik
const dz=JSON.parse(fs.readFileSync(SITE+'dizin.json')); const V=new Int8Array(fs.readFileSync(SITE+'vektor.bin').buffer.slice(0));
function enYakin(e,n=5){ const s=[]; for(let i=0;i<dz.u.length;i++){ let t=0; for(let k=0;k<dz.k;k++) t+=e[k]*V[i*dz.k+k]; s.push([t/127,dz.u[i][0]]); } return s.sort((a,b)=>b[0]-a[0]).slice(0,n); }
for(const q of ['arduino uno','ultrasonik mesafe sensoru','servo motor mg996r']){ const [,,x]=await sor(q); console.log('\n'+q); enYakin(x.e).forEach(([c,a])=>console.log('  ',c.toFixed(3),a)); }
await sor('arduino uno'); console.log('\nAI çağrısı (önbellek sonrası):',aiCagri, '| yanlış sürüm →', (await W.fetch(new Request('https://w.dev/embed?v=x&q=deneme'),env,ctx)).status, '| kök →', (await W.fetch(new Request('https://w.dev/'),env,ctx)).status, '| yabancı origin cors →', (await sor('led','https://kotu.site'))[1]);
srv.close();
