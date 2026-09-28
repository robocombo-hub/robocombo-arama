#!/usr/bin/env python3
"""
Robocombo akilli arama - gece senkronu.

1. ikas Admin API'den urunleri ceker (ad, marka, kategori, adres, gorsel, fiyat, stok).
2. Her urun icin kisa bir metin olusturur ve Cloudflare Workers AI (bge-m3) ile anlam vektorunu cikarir.
   Degismeyen urunlerin vektorleri onbellekten gelir, sadece yeni/degisen urunler yeniden hesaplanir.
3. Vektorleri PCA ile 256 boyuta indirir ve int8 olarak paketler (tarayici ~1 MB indirir).
4. site/ klasorune yazar: dizin.json, vektor.bin, pca.bin, meta.json (+ magaza scripti).

Ortam degiskenleri (GitHub Secrets):
  IKAS_MAGAZA          ornek: robocombo  (robocombo.myikas.com)
  IKAS_CLIENT_ID       ikas ozel uygulama bilgileri
  IKAS_CLIENT_SECRET
  CF_ACCOUNT_ID        Cloudflare hesap kimligi
  CF_API_TOKEN         Workers AI yetkili API anahtari
Istege bagli:
  IKAS_GORSEL_KOK      urun gorsellerinin CDN klasoru
  CF_API_BASE          test icin (varsayilan https://api.cloudflare.com/client/v4)

Yerel deneme (ikas yerine Excel disa aktarimi ile):
  python sync/sync.py --excel ikas-urunler.xlsx
"""
import os, sys, json, re, time, html, hashlib, struct, argparse, shutil, datetime
import numpy as np
import requests

MODEL = '@cf/baai/bge-m3'
K_HEDEF = 256
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIKTI = os.path.join(KOK, 'site')
ONBELLEK = os.path.join(KOK, 'onbellek')
VARSAYILAN_GORSEL_KOK = 'https://cdn.myikas.com/images/8851261a-8af5-44a0-aeb8-a7b66210823d/'


def log(*a):
    print('[sync]', *a, flush=True)


# ------------------------------------------------------------------ ikas Admin API
class Ikas:
    GQL = 'https://api.myikas.com/api/v1/admin/graphql'

    def __init__(self, magaza, cid, csec):
        self.token = self._token(magaza, cid, csec)
        self._tipler = {}

    def _token(self, magaza, cid, csec):
        adresler = [f'https://{magaza}.myikas.com/api/admin/oauth/token', 'https://api.myikas.com/api/admin/oauth/token']
        for u in adresler:
            try:
                r = requests.post(u, data={'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}, timeout=30)
                if r.ok and r.json().get('access_token'):
                    log('ikas erişim anahtarı alındı')
                    return r.json()['access_token']
                log('token denemesi başarısız', u, r.status_code, r.text[:200])
            except Exception as e:
                log('token hatası', u, e)
        sys.exit('ikas erişim anahtarı alınamadı: IKAS_MAGAZA / IKAS_CLIENT_ID / IKAS_CLIENT_SECRET kontrol edin')

    def sorgu(self, q, degisken=None):
        for deneme in range(6):
            r = requests.post(self.GQL, json={'query': q, 'variables': degisken or {}},
                              headers={'Authorization': 'Bearer ' + self.token}, timeout=90)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** deneme)
                continue
            r.raise_for_status()
            j = r.json()
            if j.get('errors'):
                raise RuntimeError('ikas GraphQL hatası: ' + json.dumps(j['errors'], ensure_ascii=False)[:800])
            return j['data']
        raise RuntimeError('ikas: tekrar tekrar hata/limit')

    # Sema sorgusu: sadece gercekten var olan alanlari istemek icin (alan adi degisse de senkron kirilmaz)
    def alanlar(self, tip):
        if tip not in self._tipler:
            q = '''query($n:String!){ __type(name:$n){ fields{ name type{ kind name ofType{ kind name ofType{ kind name ofType{ kind name }}}}}}}'''
            d = self.sorgu(q, {'n': tip}).get('__type') or {}
            m = {}
            for f in d.get('fields') or []:
                t = f['type']
                while t and t.get('name') is None:
                    t = t.get('ofType')
                m[f['name']] = t['name'] if t else None
            self._tipler[tip] = m
        return self._tipler[tip]

    def girdiler(self, tip):
        try:
            d = self.sorgu('query($n:String!){ __type(name:$n){ inputFields{ name } } }', {'n': tip}).get('__type') or {}
            return [f['name'] for f in d.get('inputFields') or []]
        except Exception as e:
            log('girdi tipi okunamadı', tip, e)
            return []

    def secim(self, tip, aday):
        mevcut = self.alanlar(tip)
        parca = []
        for ad, alt in aday.items():
            if ad not in mevcut:
                continue
            if alt is None:
                parca.append(ad)
            else:
                ic = self.secim(mevcut[ad], alt)
                if ic:
                    parca.append(ad + '{ ' + ic + ' }')
        return ' '.join(parca)


URUN_ADAY = {
    'id': None, 'name': None, 'description': None, 'deleted': None,
    'brand': {'name': None},
    'categories': {'id': None, 'name': None},
    'metaData': {'slug': None},
    'salesChannels': {'id': None, 'status': None},
    'variants': {
        'id': None, 'sku': None, 'isActive': None, 'deleted': None, 'sellIfOutOfStock': None,
        'images': {'imageId': None, 'isMain': None, 'order': None},
        'prices': {'sellPrice': None, 'discountPrice': None, 'priceListId': None},
        'stocks': {'stockCount': None, 'stockLocationId': None},
    },
}


def ikas_urunleri(ikas):
    sorgu_tipleri = ikas.alanlar('Query')
    if 'listProduct' not in sorgu_tipleri:
        sys.exit('ikas şemasında listProduct bulunamadı')
    cevap_tip = sorgu_tipleri['listProduct']
    cevap_alan = ikas.alanlar(cevap_tip)
    urun_tip = cevap_alan.get('data') or 'Product'
    sec = ikas.secim(urun_tip, URUN_ADAY)
    sayfa_alan = ' '.join(a for a in ('count', 'hasNext', 'page', 'limit') if a in cevap_alan)
    log('ürün alanları:', sec[:300], '...')
    q = 'query($p:PaginationInput){ listProduct(pagination:$p){ ' + sayfa_alan + ' data{ ' + sec + ' } } }'
    urunler, sayfa, limit = [], 1, 100
    while True:
        d = ikas.sorgu(q, {'p': {'page': sayfa, 'limit': limit}})['listProduct']
        veri = d.get('data') or []
        urunler.extend(veri)
        log(f'sayfa {sayfa}: {len(veri)} ürün (toplam {len(urunler)}/{d.get("count", "?")})')
        if not veri or ('hasNext' in d and not d['hasNext']) or len(veri) < limit:
            break
        sayfa += 1
    filtre = 'in' if 'in' in ikas.girdiler('StringFilterInput') else 'eq'
    return urunler, sec, filtre


def duz_metin(h):
    if not h:
        return ''
    h = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', h, flags=re.S | re.I)
    h = re.sub(r'<br\s*/?>|</p>|</li>|</div>', '. ', h, flags=re.I)
    h = re.sub(r'<[^>]+>', ' ', h)
    h = html.unescape(h).replace('\xa0', ' ')
    h = re.sub(r'\s+', ' ', h).strip()
    h = re.sub(r'(\.\s*){2,}', '. ', h)
    return h


def ikas_satiri(p, satis):
    if p.get('deleted'):
        return None
    kanallar = p.get('salesChannels')
    if kanallar is not None and not any((c or {}).get('status') == 'VISIBLE' for c in kanallar):
        return None
    varyantlar = [v for v in (p.get('variants') or []) if not v.get('deleted') and v.get('isActive', True) is not False]
    if not varyantlar:
        return None
    v = varyantlar[0]
    gorseller = []
    for vv in varyantlar:
        gorseller.extend(vv.get('images') or [])
    gorseller.sort(key=lambda g: (0 if g.get('isMain') else 1, g.get('order') or 0))
    gorsel = gorseller[0]['imageId'] if gorseller else ''
    fiyatlar = v.get('prices') or []
    fiyat = next((f for f in fiyatlar if not f.get('priceListId')), fiyatlar[0] if fiyatlar else {})
    sat, ind = fiyat.get('sellPrice') or 0, fiyat.get('discountPrice')
    if ind and 0 < ind < sat:
        f, eski = ind, sat
    else:
        f, eski = sat, 0
    if 'stocks' in v:
        stok = 1 if (sum((s or {}).get('stockCount') or 0 for vv in varyantlar for s in (vv.get('stocks') or [])) > 0 or v.get('sellIfOutOfStock')) else 0
    else:
        stok = 1
    sku = str(v.get('sku') or '')
    kats = []
    for c in p.get('categories') or []:
        ad = (c or {}).get('name')
        if ad and ad not in kats:
            kats.append(ad)
    return {
        'id': p['id'], 'ad': (p.get('name') or '').strip(), 'sku': sku,
        'marka': ((p.get('brand') or {}).get('name') or '').strip(),
        'kat': kats, 'slug': (p.get('metaData') or {}).get('slug') or '',
        'gorsel': gorsel, 'fiyat': round(float(f), 2), 'eski': round(float(eski), 2), 'stok': stok,
        'satis': int(satis.get(sku, 0)), 'aciklama': duz_metin(p.get('description'))[:400],
    }


# ------------------------------------------------------------------ Excel (yerel deneme)
def excel_urunleri(yol, satis):
    import pandas as pd
    k = pd.read_excel(yol)
    kok = VARSAYILAN_GORSEL_KOK
    sonuc = []
    for _, r in k.iterrows():
        if str(r.get('Satış Kanalı:robocombo')) != 'VISIBLE':
            continue
        img = str(r['Resim URL']).split(';')[0].strip() if pd.notna(r['Resim URL']) else ''
        m = re.match(re.escape(kok) + r'([0-9a-f-]{36})/', img)
        kats = []
        for c in str(r['Kategoriler']).split(';'):
            c = c.strip()
            if c and c != 'nan':
                yaprak = c.split('>')[-1].strip()
                if yaprak not in kats:
                    kats.append(yaprak)
        sat, ind = r['Satış Fiyatı'], r['İndirimli Fiyatı']
        if pd.notna(ind) and pd.notna(sat) and 0 < float(ind) < float(sat):
            f, eski = float(ind), float(sat)
        else:
            f, eski = (float(sat) if pd.notna(sat) else 0.0), 0.0
        stok = 1 if ((pd.notna(r['Stok:Ana Depo']) and r['Stok:Ana Depo'] > 0) or bool(r['Stoğu Tükenince Satmaya Devam Et']) is True) else 0
        sku = str(r['SKU'])
        sonuc.append({
            'id': str(r['Ürün Grup ID']), 'ad': str(r['İsim']).strip(), 'sku': sku,
            'marka': str(r['Marka']).strip() if pd.notna(r['Marka']) else '', 'kat': kats, 'slug': str(r['Slug']),
            'gorsel': m.group(1) if m else '', 'fiyat': round(f, 2), 'eski': round(eski, 2), 'stok': stok,
            'satis': int(satis.get(sku, 0)),
            'aciklama': duz_metin(str(r['Açıklama']) if pd.notna(r['Açıklama']) else '')[:400],
        })
    return sonuc


# ------------------------------------------------------------------ Anlam vektorleri
def urun_metni(u):
    parca = [u['ad']]
    if u['marka']:
        parca.append('Marka: ' + u['marka'])
    if u['kat']:
        parca.append('Kategori: ' + ', '.join(u['kat']))
    if u['aciklama']:
        parca.append(u['aciklama'][:300])
    return '. '.join(parca)


def vektorler(urunler, hesap, anahtar, taban):
    os.makedirs(ONBELLEK, exist_ok=True)
    yol = os.path.join(ONBELLEK, 'vektor-onbellek.npz')
    eski = {}
    if os.path.exists(yol):
        z = np.load(yol, allow_pickle=False)
        for i, h, v in zip(z['idler'], z['ozetler'], z['vek']):
            eski[str(i)] = (str(h), v)
        log(f'önbellekte {len(eski)} vektör')
    ozet = [hashlib.sha1((MODEL + '|' + urun_metni(u)).encode('utf-8')).hexdigest() for u in urunler]
    sonuc = [None] * len(urunler)
    yeni = []
    for i, u in enumerate(urunler):
        e = eski.get(u['id'])
        if e and e[0] == ozet[i]:
            sonuc[i] = e[1].astype(np.float32)
        else:
            yeni.append(i)
    log(f'{len(yeni)} ürün için yeni vektör hesaplanacak')
    url = f'{taban}/accounts/{hesap}/ai/run/{MODEL}'
    for b in range(0, len(yeni), 50):
        parti = yeni[b:b + 50]
        metin = [urun_metni(urunler[i]) for i in parti]
        for deneme in range(6):
            r = requests.post(url, json={'text': metin}, headers={'Authorization': 'Bearer ' + anahtar}, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** deneme)
                continue
            if not r.ok:
                sys.exit(f'Workers AI hatası {r.status_code}: {r.text[:300]}')
            break
        j = r.json()
        veri = (j.get('result') or {}).get('data') or j.get('data')
        if not veri or len(veri) != len(parti):
            sys.exit('Workers AI beklenmeyen cevap: ' + json.dumps(j)[:300])
        for i, vv in zip(parti, veri):
            sonuc[i] = np.asarray(vv, dtype=np.float32)
        log(f'  vektör {min(b + 50, len(yeni))}/{len(yeni)}')
    X = np.vstack(sonuc).astype(np.float32)
    np.savez_compressed(yol, idler=np.array([u['id'] for u in urunler]), ozetler=np.array(ozet), vek=X.astype(np.float16))
    return X


def pca_paketle(X, k_hedef, surum):
    X = X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
    ort = X.mean(axis=0)
    Xm = X - ort
    k = int(min(k_hedef, Xm.shape[0] - 1, Xm.shape[1]))
    _, S, Vt = np.linalg.svd(Xm, full_matrices=False)
    W = Vt[:k].T.astype(np.float32)                      # D x k
    acik = float((S[:k] ** 2).sum() / (S ** 2).sum())
    P = Xm @ W
    P /= np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
    q = np.clip(np.round(P * 127), -127, 127).astype(np.int8)
    # baslik: D, k, surum (16 bayt) | ortalama (D float32) | W (D x k float32)
    pca = struct.pack('<ii16s', X.shape[1], k, surum.encode('ascii')[:16]) + ort.astype('<f4').tobytes() + W.astype('<f4').tobytes()
    return q, pca, k, acik


# ------------------------------------------------------------------ Ana akis
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--excel', help='ikas ürün dışa aktarımı (.xlsx) ile yerel deneme')
    ap.add_argument('--cikti', default=CIKTI)
    a = ap.parse_args()

    satis = json.load(open(os.path.join(KOK, 'sync', 'satis.json'), encoding='utf-8'))['satis']
    if a.excel:
        urunler = excel_urunleri(a.excel, satis)
        kaynak = 'excel'
    else:
        eksik = [x for x in ('IKAS_MAGAZA', 'IKAS_CLIENT_ID', 'IKAS_CLIENT_SECRET') if not os.environ.get(x)]
        if eksik:
            sys.exit('Eksik GitHub Secret: ' + ', '.join(eksik) + ' (Settings > Secrets and variables > Actions)')
        ikas = Ikas(os.environ['IKAS_MAGAZA'].strip(), os.environ['IKAS_CLIENT_ID'].strip(), os.environ['IKAS_CLIENT_SECRET'].strip())
        ham, sec, filtre = ikas_urunleri(ikas)
        urunler = [x for x in (ikas_satiri(p, satis) for p in ham) if x]
        kaynak = 'ikas'
    urunler = [u for u in urunler if u['ad'] and u['slug']]
    log(f'{len(urunler)} yayında ürün ({kaynak})')
    if len(urunler) < 50:
        sys.exit('Çok az ürün geldi, yayın iptal (önceki dizin yerinde kalır)')

    hesap, anahtar = os.environ.get('CF_ACCOUNT_ID'), os.environ.get('CF_API_TOKEN')
    taban = os.environ.get('CF_API_BASE', 'https://api.cloudflare.com/client/v4').rstrip('/')
    k = 0
    os.makedirs(a.cikti, exist_ok=True)
    surum = datetime.datetime.utcnow().strftime('%Y%m%d%H%M')
    if hesap and anahtar:
        X = vektorler(urunler, hesap, anahtar, taban)
        q, pca, k, acik = pca_paketle(X, K_HEDEF, surum)
        open(os.path.join(a.cikti, 'vektor.bin'), 'wb').write(q.tobytes())
        open(os.path.join(a.cikti, 'pca.bin'), 'wb').write(pca)
        log(f'anlam vektörleri: {X.shape[1]} → {k} boyut (bilginin %{acik * 100:.1f}\'i korunuyor)')
    else:
        log('CF_ACCOUNT_ID / CF_API_TOKEN yok: sadece kelime araması için dizin üretiliyor')

    satirlar = [[u['ad'], u['sku'], u['marka'], '|'.join(u['kat']), u['slug'], u['gorsel'],
                 u['fiyat'], u['eski'], u['stok'], u['satis'], u['id']] for u in urunler]
    dizin = {'v': 2, 'surum': surum, 'k': k,
             'gorselKok': os.environ.get('IKAS_GORSEL_KOK', VARSAYILAN_GORSEL_KOK),
             'alanlar': ['ad', 'sku', 'marka', 'kategoriler', 'slug', 'gorsel', 'fiyat', 'eskiFiyat', 'stokta', 'satis', 'id'],
             'u': satirlar}
    json.dump(dizin, open(os.path.join(a.cikti, 'dizin.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    if kaynak == 'ikas':   # Worker'in anlik fiyat/stok sorgusu icin (ayni alan secimi)
        json.dump({'sec': sec, 'filtre': filtre}, open(os.path.join(a.cikti, 'ikas-sorgu.json'), 'w'), separators=(',', ':'))
    json.dump({'surum': surum, 'urun': len(satirlar), 'k': k, 'semantik': k > 0, 'kaynak': kaynak},
              open(os.path.join(a.cikti, 'meta.json'), 'w'), separators=(',', ':'))
    betik = os.path.join(KOK, 'magaza', 'akilli-arama.js')
    if os.path.exists(betik):
        shutil.copy(betik, os.path.join(a.cikti, 'akilli-arama.js'))
    open(os.path.join(a.cikti, 'index.html'), 'w').write('<!doctype html><meta charset="utf-8"><title>robocombo-arama</title><p>Robocombo akilli arama verisi. Surum ' + surum + '</p>')
    log(f'hazır: sürüm {surum}, {len(satirlar)} ürün, semantik={"açık" if k else "kapalı"}')


if __name__ == '__main__':
    main()
