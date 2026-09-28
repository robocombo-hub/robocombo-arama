/**
 * Robocombo akilli arama - Cloudflare Worker
 *
 * Tek gorevi: aranan cumlenin anlam vektorunu cikarmak.
 *   GET /embed?q=<arama>&v=<dizin surumu>
 *   -> Workers AI (bge-m3) ile 1024 boyutlu vektor
 *   -> gece senkronunun urettigi PCA ile 256 boyuta indirilir
 *   -> { v, k, e:[...] }  (tarayici urun vektorleriyle karsilastirir)
 *
 * Kurulum (Cloudflare panelinde):
 *   Ayarlar > Baglamalar: Workers AI, degisken adi "AI"
 *   Ayarlar > Degiskenler: VERI_URL = https://<github-kullanici>.github.io/robocombo-arama
 */

const MODEL = '@cf/baai/bge-m3';
const IZINLI = [/^https:\/\/(www\.)?robocombo\.com$/, /^https:\/\/[a-z0-9-]+\.myikas\.com$/, /^https:\/\/robocombo\.ikas\.shop$/];

let PCA = null;           // { v, D, k, ort: Float32Array, W: Float32Array }
let PCA_YUKLENIYOR = null;

function corsBasliklari(req) {
  const o = req.headers.get('Origin') || '';
  const izin = IZINLI.some((r) => r.test(o));
  return {
    'Access-Control-Allow-Origin': izin ? o : 'https://www.robocombo.com',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function json(veri, durum, basliklar) {
  return new Response(JSON.stringify(veri), {
    status: durum,
    headers: { ...basliklar, 'Content-Type': 'application/json; charset=utf-8' },
  });
}

async function pcaYukle(env, v) {
  if (PCA && PCA.v === v) return PCA;
  if (PCA_YUKLENIYOR && PCA_YUKLENIYOR.v === v) return PCA_YUKLENIYOR.p;
  const p = (async () => {
    const taban = String(env.VERI_URL || '').replace(/\/$/, '');
    const r = await fetch(`${taban}/pca.bin?v=${encodeURIComponent(v)}`, { cf: { cacheTtl: 3600 } });
    if (!r.ok) throw new Error('pca.bin alınamadı: ' + r.status);
    const buf = await r.arrayBuffer();
    const bas = new DataView(buf);
    const D = bas.getInt32(0, true), k = bas.getInt32(4, true);
    const dosyaSurum = new TextDecoder().decode(new Uint8Array(buf, 8, 16)).replace(/\0+$/, '');
    const ort = new Float32Array(buf, 24, D);
    const W = new Float32Array(buf, 24 + D * 4, D * k);
    PCA = { v: dosyaSurum, D, k, ort, W };
    return PCA;
  })();
  PCA_YUKLENIYOR = { v, p };
  try { return await p; } finally { PCA_YUKLENIYOR = null; }
}

function indir(x, pca) {
  const { D, k, ort, W } = pca;
  let n = 0;
  for (let i = 0; i < D; i++) n += x[i] * x[i];
  n = Math.sqrt(n) || 1;
  const y = new Float32Array(k);
  for (let i = 0; i < D; i++) {
    const xi = x[i] / n - ort[i];
    if (xi === 0) continue;
    const s = i * k;
    for (let j = 0; j < k; j++) y[j] += xi * W[s + j];
  }
  let m = 0;
  for (let j = 0; j < k; j++) m += y[j] * y[j];
  m = Math.sqrt(m) || 1;
  const e = new Array(k);
  for (let j = 0; j < k; j++) e[j] = Math.round((y[j] / m) * 10000) / 10000;
  return e;
}

export default {
  async fetch(req, env, ctx) {
    const cors = corsBasliklari(req);
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
    const url = new URL(req.url);
    if (url.pathname !== '/embed') return json({ servis: 'robocombo-arama', durum: 'çalışıyor' }, 200, cors);

    const q = (url.searchParams.get('q') || '').trim().replace(/\s+/g, ' ').slice(0, 200);
    const v = (url.searchParams.get('v') || '').slice(0, 40);
    if (q.length < 2 || !v) return json({ hata: 'q ve v gerekli' }, 400, cors);

    const anahtar = new Request(`https://onbellek.robocombo-arama/embed?v=${encodeURIComponent(v)}&q=${encodeURIComponent(q.toLocaleLowerCase('tr'))}`);
    const onbellek = caches.default;
    const kayitli = await onbellek.match(anahtar);
    if (kayitli) {
      const r = new Response(kayitli.body, kayitli);
      for (const [a, b] of Object.entries(cors)) r.headers.set(a, b);
      return r;
    }

    try {
      const pca = await pcaYukle(env, v);
      if (pca.v !== v) return json({ hata: 'sürüm', guncel: pca.v }, 409, cors);   // tarayici eski dizinle calisiyor
      const sonuc = await env.AI.run(MODEL, { text: [q] });
      const x = (sonuc && (sonuc.data || (sonuc.result && sonuc.result.data)) || [])[0];
      if (!x || x.length !== pca.D) throw new Error('beklenmeyen model cevabı');
      const govde = JSON.stringify({ v, k: pca.k, e: indir(x, pca) });
      const cevap = new Response(govde, {
        headers: { ...cors, 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=86400' },
      });
      ctx.waitUntil(onbellek.put(anahtar, cevap.clone()));
      return cevap;
    } catch (err) {
      // Tarayici bu durumda sadece kelime aramasiyla devam eder
      return json({ hata: String((err && err.message) || err) }, 503, cors);
    }
  },
};
