import http from 'node:http'; import {sahteVektor} from './sahte-ai.mjs';
let say=0;
http.createServer((req,res)=>{ let b=''; req.on('data',d=>b+=d); req.on('end',()=>{
  if(!/\/accounts\/[^/]+\/ai\/run\/@cf\/baai\/bge-m3$/.test(req.url) || req.headers.authorization!=='Bearer test-anahtar'){ res.writeHead(404); return res.end('{}'); }
  const {text}=JSON.parse(b); say+=text.length;
  res.writeHead(200,{'content-type':'application/json'}); res.end(JSON.stringify({success:true,result:{shape:[text.length,1024],data:text.map(sahteVektor)}}));
}); }).listen(8787,()=>console.log('sahte AI 8787'));
process.on('SIGTERM',()=>{ console.log('toplam metin',say); process.exit(0); });
