// Test icin sahte "bge-m3": harf uclulerini 1024 boyuta hash'leyen, normalize vektor.
// Anlamsal degil ama urun ve sorgu icin ayni fonksiyon kullanildigi icin boru hattini uctan uca sinar.
export function sahteVektor(metin){
  const t=String(metin).toLocaleLowerCase('tr').normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/ı/g,'i');
  const v=new Float64Array(1024);
  const kel=t.split(/[^a-z0-9]+/).filter(Boolean);
  for(const k of kel){ const w=` ${k} `; for(let i=0;i<w.length-2;i++){ let h=2166136261; for(const c of w.slice(i,i+3)){ h^=c.charCodeAt(0); h=Math.imul(h,16777619)>>>0; } v[h%1024]+=((h>>10)&1)?1:-1; } }
  let n=0; for(const x of v) n+=x*x; n=Math.sqrt(n)||1; return Array.from(v,x=>x/n);
}
