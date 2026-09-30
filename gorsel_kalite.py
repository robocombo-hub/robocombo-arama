#!/usr/bin/env python3
"""gorsel_kalite.py - Ticimax <-> ikas urun gorseli kalite kontrolu, yedek, aktarim ve geri alma.

Modlar
  kesif          : 30 urunde tum olasiliklari dener (ikas CDN boyutlari, Ticimax klasorleri, sitemap eslesmesi)
                   ve ikas semasini okur. Magazada HICBIR SEY degistirmez.
  rapor          : tum urunlerde Ticimax orijinali ile ikas gorselini karsilastirir; Excel + HTML rapor.
  rapor-ve-yedek : rapor + Ticimax orijinal gorsellerinin (ve aciklamalardaki Ticimax gorsellerinin) tam yedegi.
  aktar-deneme   : "Duzeltilmeli" cikan ilk 3 urunde (ya da --sku ile verilenlerde) aktarimi yapar, her adimi dogrular.
  aktar          : "Duzeltilmeli" cikan tum urunlerde aktarim.
  geri-al        : aktarim oncesi kayittan (aktar-oncesi/) urunlerin eski gorsel listesini geri yukler.

Aktarim (urun basina):
  1. Urun ikas'tan tam okunur; degistirmeden kaydedilip tekrar okunur -> hicbir alan degismiyorsa devam
     (degisiyorsa TUM calisma durur, hicbir gorsel yuklenmez).
  2. Aktarim oncesi hali aktar-oncesi/<urunId>.json olarak saklanir (geri-al icin).
  3. Sadece bozuk/eksik Ticimax gorselleri, Ticimax'taki HAM orijinal dosyadan ikas'a yuklenir
     (once adresle - ikas kendisi ceker; olmazsa dosyanin kendisi gonderilir).
  4. Yeni gorsel ikas CDN'den indirilip Ticimax orijinaliyle olculur; gecmezse eski gorsel yerinde kalir.
  5. Gorsel listesi Ticimax sirasina gore kaydedilir; ikas'ta fazladan olan gorseller korunur.
  6. Kayittan sonra urun tekrar okunur; gorseller disinda bir alan degistiyse calisma durur.
"""
import os, re, io, sys, json, time, copy, base64, zipfile, argparse, threading, html as htmlmod
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlsplit
import requests
import numpy as np
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 80_000_000

TICI_SITE = os.environ.get('TICIMAX_SITE', 'https://www.robocombo.com').rstrip('/')
TICI_STATIC = os.environ.get('TICIMAX_STATIC', 'https://static.ticimax.cloud/7051/uploads/urunresimleri/')
TICI_KLASOR = os.environ.get('TICIMAX_KLASOR', 'buyuk')          # kesif daha buyuk bir klasor bulursa buradan degistirilir
TICI_KLASORLER = ['buyuk', 'orjinal', 'orijinal', 'original', 'max', 'zoom', 'big', 'kucuk']   # kesifte denenecekler
IKAS_KOK = os.environ.get('IKAS_GORSEL_KOK', 'https://cdn.myikas.com/images/8851261a-8af5-44a0-aeb8-a7b66210823d/')
IKAS_TOKEN_URL = os.environ.get('IKAS_TOKEN_URL', '')
IKAS_GQL = os.environ.get('IKAS_GQL', 'https://api.myikas.com/api/v1/admin/graphql')
IKAS_UPLOAD = os.environ.get('IKAS_UPLOAD', 'https://api.myikas.com/api/v1/admin/product/upload/image')
ONYUZ = os.environ.get('MAGAZA_ONYUZ', 'https://l0v8l-robocombo.myikas.com').rstrip('/')
IKAS_BOYUTLAR = [180, 360, 540, 720, 900, 1080, 1296, 1512, 1728, 2560, 3840]   # kesif: digerleri 404
CIKTI = os.environ.get('CIKTI', 'cikti')
YEDEK_DIR = os.environ.get('YEDEK_DIR', 'yedek')
AKTAR_ONCESI = os.environ.get('AKTAR_ONCESI_DIR', 'aktar-oncesi')
BEKLE = float(os.environ.get('AKTAR_BEKLE', '3'))
FAZLA_SIL = os.environ.get('FAZLA_SIL', '') == '1'
# ikas ayni gorseli buyuk boyut istenince daha az sikistirarak veriyor (kesif: 380 px gorsel image_540'ta 9 KB, image_2560'ta 18 KB).
# Kayitli gorselin kendisini olcmek icin en az sikistirilmis surum istenir; teslim (tema) kalitesi ayrica olculur.
OLCUM_BOYUT = int(os.environ.get('IKAS_OLCUM_BOYUT', '2560'))
UA = {'User-Agent': 'Mozilla/5.0 (robocombo-gorsel-kontrol)'}

# esikler (kesif / ilk rapor sonucuna gore ayarlanabilir)
ESIK_KESKINLIK = float(os.environ.get('ESIK_KESKINLIK', '0.55'))   # ikas keskinligi / Ticimax keskinligi
ESIK_SSIM = float(os.environ.get('ESIK_SSIM', '0.80'))
ESIK_COZUNURLUK = float(os.environ.get('ESIK_COZUNURLUK', '0.75'))  # ikas uzun kenar / Ticimax uzun kenar
ESIK_ESLESME = int(os.environ.get('ESIK_ESLESME', '60'))            # pHash mesafesi (255 bit)
KAYNAK_MIN = int(os.environ.get('KAYNAK_MIN', '800'))              # Ticimax gorseli bundan kucukse "kaynak da kucuk"
ESIK_RENK = float(os.environ.get('ESIK_RENK', '10'))               # urun bolgesinde ortalama renk farki (0-255)
ESIK_AYNI = float(os.environ.get('ESIK_AYNI', '0.45'))              # urun bolgesi benzerligi bunun altindaysa baska gorsel sayilir


def log(*a):
    print('[gorsel]', *a, flush=True)


# ------------------------------------------------------------------ HTTP
_S = requests.Session()
_S.headers.update(UA)
_A = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=0)
_S.mount('https://', _A); _S.mount('http://', _A)


def al(url, deneme=3, zaman=45, engel_bekle=False):
    """engel_bekle: 403/429/503'te (Cloudflare hiz siniri) bekleyip tekrar dener - Ticimax sayfalari icin"""
    r = None
    for i in range(deneme):
        try:
            r = _S.get(url, timeout=zaman, allow_redirects=True)
            if r.status_code == 200 and r.content:
                return r
            if r.status_code in (400, 404, 410):
                return r
            if r.status_code in (403, 429, 503):
                if not engel_bekle:
                    return r
                time.sleep(min(60, 5 * 3 ** i)); continue
        except requests.RequestException:
            r = None
        time.sleep(1.5 * (i + 1))
    return r


# ------------------------------------------------------------------ ikas Admin API
_TREF = 'kind name ofType{ kind name ofType{ kind name ofType{ kind name } } }'


def _tur(t):
    """GraphQL tip referansi -> (tur, ad, imza)  ornek: ('INPUT_OBJECT', 'ProductInput', 'ProductInput!')"""
    def imza(x):
        if x['kind'] == 'NON_NULL':
            return imza(x['ofType']) + '!'
        if x['kind'] == 'LIST':
            return '[' + imza(x['ofType']) + ']'
        return x['name']
    i = imza(t)
    while t and t.get('name') is None:
        t = t.get('ofType')
    return (t['kind'], t['name'], i) if t else (None, None, i)


class Ikas:
    def __init__(self, magaza, cid, csec):
        self._g = (magaza, cid, csec)
        self.token = None
        self._t = {}
        self.kilit = threading.Lock()
        self._yetki()

    def _yetki(self):
        magaza, cid, csec = self._g
        urls = [IKAS_TOKEN_URL] if IKAS_TOKEN_URL else [f'https://{magaza}.myikas.com/api/admin/oauth/token', 'https://api.myikas.com/api/admin/oauth/token']
        for u in urls:
            try:
                r = requests.post(u, data={'grant_type': 'client_credentials', 'client_id': cid, 'client_secret': csec}, timeout=30)
                if r.ok and r.json().get('access_token'):
                    self.token = r.json()['access_token']; return
            except Exception as e:
                log('token hatası', u, e)
        sys.exit('ikas erişim anahtarı alınamadı (IKAS_MAGAZA / IKAS_CLIENT_ID / IKAS_CLIENT_SECRET)')

    def baslik(self):
        return {'Authorization': 'Bearer ' + self.token}

    def sorgu(self, q, v=None):
        for d in range(7):
            try:
                r = requests.post(IKAS_GQL, json={'query': q, 'variables': v or {}}, headers=self.baslik(), timeout=120)
            except requests.RequestException:
                time.sleep(2 ** d); continue
            if r.status_code == 401:
                with self.kilit:
                    self._yetki()
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(60, 2 ** d)); continue
            r.raise_for_status()
            j = r.json()
            if j.get('errors'):
                raise RuntimeError(json.dumps(j['errors'], ensure_ascii=False)[:800])
            return j['data']
        raise RuntimeError('ikas: tekrarlayan hata')

    def tip(self, ad):
        if ad not in self._t:
            q = ('query($n:String!){ __type(name:$n){ kind fields{ name args{ name type{ T } } type{ T } } inputFields{ name type{ T } } } }'
                 .replace('T }', _TREF + ' }'))
            d = self.sorgu(q, {'n': ad}).get('__type') or {}
            self._t[ad] = {'tur': d.get('kind'),
                           'alan': {f['name']: _tur(f['type']) for f in d.get('fields') or []},
                           'arg': {f['name']: {a['name']: _tur(a['type']) for a in f.get('args') or []} for f in d.get('fields') or []},
                           'girdi': {f['name']: _tur(f['type']) for f in d.get('inputFields') or []}}
        return self._t[ad]

    def alanlar(self, tip):
        return {k: v[1] for k, v in self.tip(tip)['alan'].items()}

    def girdiler(self, tip):
        try:
            return {k: v[2] for k, v in self.tip(tip)['girdi'].items()}
        except Exception as e:
            return {'_hata': str(e)}

    def secim(self, tip, aday):
        m = self.alanlar(tip); p = []
        for ad, alt in aday.items():
            if ad not in m:
                continue
            if alt is None:
                p.append(ad)
            else:
                ic = self.secim(m[ad], alt)
                if ic:
                    p.append(ad + '{ ' + ic + ' }')
        return ' '.join(p)


URUN_ADAY = {'id': None, 'name': None, 'deleted': None, 'description': None, 'metaData': {'slug': None},
             'variants': {'id': None, 'sku': None, 'deleted': None, 'images': {'imageId': None, 'isMain': None, 'order': None}}}


def ikas_urunleri(ikas):
    lp = ikas.alanlar('Query')['listProduct']
    cev = ikas.alanlar(lp)
    sec = ikas.secim(cev.get('data') or 'Product', URUN_ADAY)
    q = 'query($p:PaginationInput){ listProduct(pagination:$p){ ' + ' '.join(a for a in ('count', 'hasNext') if a in cev) + ' data{ ' + sec + ' } } }'
    out, s = [], 1
    while True:
        d = ikas.sorgu(q, {'p': {'page': s, 'limit': 100}})['listProduct']
        v = d.get('data') or []
        out.extend(v)
        log(f'ikas sayfa {s}: {len(out)}/{d.get("count", "?")}')
        if not v or ('hasNext' in d and not d['hasNext']) or len(v) < 100:
            break
        s += 1
    return out


ACIKLAMA_RE = re.compile(r'''(?:src|href|data-src)\s*=\s*["']([^"']+?\.(?:jpe?g|png|gif|webp|svg|bmp)(?:\?[^"']*)?)["']''', re.I)


def aciklama_gorselleri(h):
    """urun aciklamasinda Ticimax'a bagli gorseller (Ticimax kapaninca kirilacaklar)"""
    out = []
    for u in ACIKLAMA_RE.findall(h or ''):
        u = htmlmod.unescape(u).strip()
        if u.lower().startswith('about:'):
            u = u[6:]
        if u.startswith('//'):
            u = 'https:' + u
        elif u.startswith('/'):
            u = TICI_SITE + u
        if re.search(r'ticimax|robocombo\.com/uploads|/uploads/', u, re.I) and 'myikas' not in u and u not in out:
            out.append(u)
    return out


def urun_ozeti(p):
    """ikas urununden: sku, ad, slug, variantIds, gorseller (sirali, tekrarsiz)"""
    vs = [v for v in (p.get('variants') or []) if not v.get('deleted')]
    gor, gordum = [], set()
    for v in vs:
        for g in sorted(v.get('images') or [], key=lambda x: (not x.get('isMain'), x.get('order') or 0)):
            if g.get('imageId') and g['imageId'] not in gordum:
                gordum.add(g['imageId']); gor.append(g['imageId'])
    setler = {tuple(sorted(g['imageId'] for g in (v.get('images') or []) if g.get('imageId'))) for v in vs}
    return {'id': p.get('id'), 'ad': p.get('name') or '', 'slug': ((p.get('metaData') or {}).get('slug') or '').strip('/'),
            'sku': next((v.get('sku') for v in vs if v.get('sku')), '') or '', 'varyantlar': [v['id'] for v in vs if v.get('id')], 'ikas': gor,
            'varyant_farkli': len(setler) > 1, 'aciklama_tici': aciklama_gorselleri(p.get('description'))}


# ------------------------------------------------------------------ Ticimax sayfa eslestirme (sitemap)
_TR = str.maketrans('çğıöşüâîûÇĞİÖŞÜÂÎÛ', 'cgiosuaiuCGIOSUAIU')


def norm(s):
    s = unquote(s or '').translate(_TR).lower()
    s = re.sub(r'\.(html?|aspx)$', '', s)
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def _loclar(metin):
    return [htmlmod.unescape(x) for x in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', metin or '')]


def tici_sitemap():
    """Ticimax sitemap'inden tum urun adresleri"""
    r = al(TICI_SITE + '/sitemap.xml', engel_bekle=True)
    if r is None or r.status_code != 200:
        return []
    locs = _loclar(r.text)
    alt = [l for l in locs if re.search(r'\.xml(\?|$)', l, re.I)]
    if not alt:
        return locs
    kuyruk = [l for l in alt if re.search(r'product|urun', l, re.I)] or alt
    out, gorulen = [], set()
    while kuyruk:
        sm = kuyruk.pop(0)
        if sm in gorulen:
            continue
        gorulen.add(sm)
        rr = al(sm, engel_bekle=True)
        if rr is None or rr.status_code != 200:
            continue
        for l in _loclar(rr.text):
            (kuyruk if re.search(r'\.xml(\?|$)', l, re.I) else out).append(l)
    return list(dict.fromkeys(out))


class TiciHarita:
    """ikas slug'i -> Ticimax urun adresi. Buyuk/kucuk harf, cift tire, eski ',PR-170.html' adresleri ve
    kisaltilmis adlar icin: birebir -> yazim farki -> urun adi -> kelime benzerligi"""
    def __init__(self, urls):
        self.tam, self.nrm, self.tok, self.df = {}, {}, {}, {}
        self.adet = len(urls)
        for u in urls:
            yol = self.yol(u)
            if not yol:
                continue
            self.tam.setdefault(yol.lower(), u)
            n = norm(yol)
            self.nrm.setdefault(n, u)
            n2 = re.sub(r'-pr-\d+$', '', n)          # eski Ticimax adresi: Urun-Adi,PR-123.html
            if n2 != n:
                self.nrm.setdefault(n2, u)
                n = n2
            t = frozenset(x for x in n.split('-') if x)
            self.tok[u] = t
            for x in t:
                self.df.setdefault(x, []).append(u)

    @staticmethod
    def yol(u):
        if u.startswith(TICI_SITE + '/'):
            return unquote(u[len(TICI_SITE) + 1:]).strip('/')
        return unquote(urlsplit(u).path).strip('/')

    def bul(self, slug, ad=''):
        if not self.adet:
            return None, 'sitemap-yok'
        if slug and slug.lower() in self.tam:
            return self.tam[slug.lower()], 'birebir'
        n = norm(slug)
        if n and n in self.nrm:
            return self.nrm[n], 'yazim-farki'
        n3 = re.sub(r'-\d{6,}$', '', n)               # ikas'in eklemis oldugu uzun sayi eki
        if n3 != n and n3 in self.nrm:
            return self.nrm[n3], 'yazim-farki'
        na = norm(ad)
        if na and na in self.nrm:
            return self.nrm[na], 'urun-adi'
        a = frozenset(x for x in (n or na).split('-') if x)
        if not a:
            return None, 'yok'
        aday = set()
        for x in a:
            l = self.df.get(x, [])
            if len(l) <= 300:
                aday.update(l)
        puan = sorted(((len(a & self.tok[u]) / len(a | self.tok[u]), u) for u in aday), reverse=True)
        if puan and puan[0][0] >= 0.7 and (len(puan) == 1 or puan[0][0] - puan[1][0] >= 0.08):
            return puan[0][1], f'benzer-%{round(puan[0][0] * 100)}'
        return None, 'yok'


# ------------------------------------------------------------------ Ticimax galeri
IMG_RE = re.compile(r'urunresimleri/(?:buyuk|kucuk|orta|thumb)/([A-Za-z0-9._%~\-]+?\.(?:jpe?g|png|webp|gif))', re.I)
OG_RE = re.compile(r'<meta[^>]*(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)|<meta[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']', re.I)


def ad_kok(dosya):
    """Ticimax dosya adi = urun adindan (en fazla 38 harf) + '-' + 6 karakterlik rastgele ek.
    Ayni urunun butun gorsellerinde kok aynidir; benzer urunlerin gorselleri ayiklanir."""
    b = dosya.rsplit('.', 1)[0]
    return b[:-7] if len(b) > 8 else b


def tici_galeri(sayfa):
    adlar = []
    for m in IMG_RE.finditer(sayfa):
        a = unquote(m.group(1))
        if a not in adlar:
            adlar.append(a)
    og = OG_RE.search(sayfa)
    ana = None
    if og:
        mm = IMG_RE.search(og.group(1) or og.group(2) or '')
        if mm:
            ana = unquote(mm.group(1))
    if not ana and adlar:
        ana = adlar[0]
    if not ana:
        return []
    kok = ad_kok(ana)
    sec = [a for a in adlar if ad_kok(a) == kok]
    if ana in sec:
        sec.remove(ana)
    return [ana] + sec


def tici_url(dosya, klasor=None):
    return TICI_STATIC + (klasor or TICI_KLASOR) + '/' + dosya


# ------------------------------------------------------------------ olcum
def ac(b):
    try:
        im = Image.open(io.BytesIO(b)); im.load()
        if im.mode in ('RGBA', 'LA', 'P'):
            im = im.convert('RGBA'); zem = Image.new('RGBA', im.size, (255, 255, 255, 255)); zem.alpha_composite(im); im = zem
        return im.convert('RGB')
    except Exception:
        return None


_DCT = {}


def phash(im):
    """256 bitlik algisal ozet (64x64 gri, DCT'nin sol ust 16x16'si)"""
    n = 64
    if n not in _DCT:
        _DCT[n] = np.cos(np.pi * (2 * np.arange(n)[:, None] + 1) * np.arange(n)[None, :] / (2 * n))
    k = _DCT[n]
    g = np.asarray(im.convert('L').resize((n, n), Image.LANCZOS), dtype=np.float64)
    blok = (k.T @ g @ k)[:16, :16].flatten()[1:]
    return (blok > np.median(blok)).astype(np.uint8)


def hmesafe(a, b):
    return int(np.count_nonzero(a != b))


def _lap(g):
    return (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])


def _ssim(a, b):
    try:
        from skimage.metrics import structural_similarity
        return float(structural_similarity(a, b, data_range=255.0))
    except Exception:
        ma, mb = a.mean(), b.mean(); va, vb = a.var(), b.var(); cov = ((a - ma) * (b - mb)).mean()
        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        return float(((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2)))


def _urun_maskesi(g):
    """Beyaz/duz arka plani disarida birakir: sadece urunun ayrintili bolgesi (kenarlar + cevresi)"""
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]; gy[1:-1, :] = g[2:, :] - g[:-2, :]
    m = np.hypot(gx, gy) > 12
    for _ in range(3):      # 3 piksel genislet
        m2 = m.copy(); m2[1:, :] |= m[:-1, :]; m2[:-1, :] |= m[1:, :]; m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]; m = m2
    return m


def karsilastir(tici_im, ikas_im):
    """ikas gorselini Ticimax orijinalinin boyutuna (en fazla 1200 px) getirir; keskinlik orani, urun bolgesinde
    yapisal benzerlik (SSIM) ve renk farki olcer. Beyaz arka plan benzerligi sisirmesin diye sadece urun bolgesi sayilir."""
    w, h = tici_im.size
    o = min(1.0, 1200.0 / max(w, h))
    hedef = (max(16, round(w * o)), max(16, round(h * o)))
    # Adil karsilastirma: Ticimax orijinali de ikas gorseliyle ayni boyut yolculugundan gecirilir
    # (ikas gorseli Ticimax'tan kucuk geldiyse bu normallestirme yapilmaz: o fark zaten dusuk cozunurluktur)
    cozunurluk = max(ikas_im.size) / float(max(tici_im.size))
    tr = tici_im.resize(ikas_im.size, Image.LANCZOS).resize(hedef, Image.LANCZOS) if cozunurluk >= 0.98 and ikas_im.size != tici_im.size else tici_im.resize(hedef, Image.LANCZOS)
    ir = ikas_im.resize(hedef, Image.LANCZOS)
    t = np.asarray(tr.convert('L'), dtype=np.float64); i = np.asarray(ir.convert('L'), dtype=np.float64)
    lt, li = _lap(t).var(), _lap(i).var()
    maske = _urun_maskesi(t)
    try:
        from skimage.metrics import structural_similarity
        _, harita = structural_similarity(t, i, data_range=255.0, full=True)
        ssim = float(harita[maske].mean()) if maske.sum() > 200 else float(harita.mean())
    except Exception:
        ssim = _ssim(t[maske] if maske.sum() > 200 else t, i[maske] if maske.sum() > 200 else i)
    renk = float(np.abs(np.asarray(tr, dtype=np.float64) - np.asarray(ir, dtype=np.float64))[maske].mean()) if maske.sum() > 200 else 0.0
    # 128 px'te karsilastirma: bulaniklik/sikistirma/dusuk cozunurluk kaybolur, farkli gorsel farkli kalir -> "ayni gorsel mi?"
    ks = (max(8, round(w * 128.0 / max(w, h))), max(8, round(h * 128.0 / max(w, h))))
    ka, kb = tici_im.resize(ks, Image.LANCZOS), ikas_im.resize(ks, Image.LANCZOS)
    kssim = _ssim(np.asarray(ka.convert('L'), dtype=np.float64), np.asarray(kb.convert('L'), dtype=np.float64))
    krenk = float(np.abs(np.asarray(ka, dtype=np.float64) - np.asarray(kb, dtype=np.float64)).mean())
    return {'ayni': bool(kssim >= 0.9 and krenk <= 12), 'keskinlik': round(float(li / lt), 3) if lt > 1e-6 else 1.0, 'ssim': round(ssim, 3), 'renk': round(renk, 1), 'cozunurluk': round(min(cozunurluk, 9.99), 3)}


def kotu_mu(e):
    return e['ikas'] is None or e['keskinlik'] < ESIK_KESKINLIK or e['ssim'] < ESIK_SSIM or e['renk'] > ESIK_RENK or e['cozunurluk'] < ESIK_COZUNURLUK


def ikas_url(img_id, boy):
    return IKAS_KOK + img_id + '/image_' + str(boy) + '.webp'


_BOYUT_HATA = {}     # ikas'in desteklemedigi boyutlari ogrenir (baska boyut calisirken 3 kez hata verdiyse atlanir)


def ikas_indir(img_id, istenen):
    """Ticimax genisligine en yakin (>=) ikas boyutunu indir; yoksa en buyugunu dene"""
    gecerli = [b for b in IKAS_BOYUTLAR if _BOYUT_HATA.get(b, 0) < 3]
    adaylar = [b for b in gecerli if b >= istenen] or gecerli[-1:]
    hatali = []
    for b in list(dict.fromkeys(adaylar[:3] + gecerli[-1:])):
        r = al(ikas_url(img_id, b), deneme=2)
        if r is not None and r.status_code == 200:
            im = ac(r.content)
            if im:
                for x in hatali:
                    _BOYUT_HATA[x] = _BOYUT_HATA.get(x, 0) + 1
                return im, b, len(r.content)
        hatali.append(b)
    return None, None, 0


def ikas_indir_bekle(img_id, istenen, deneme=6):
    """yeni yuklenen gorsel CDN'e birkac saniyede duser"""
    for d in range(deneme):
        im, b, n = ikas_indir(img_id, istenen)
        if im is not None:
            return im, b, n
        time.sleep(BEKLE * (1 + d))
    return None, None, 0


# ------------------------------------------------------------------ yedek
class Yedek:
    """Ticimax orijinallerini parca parca zip'e yazar (her parca en fazla ~1.8 GB)"""
    def __init__(self, klasor, sinir=1_800_000_000):
        self.k, self.sinir, self.no, self.z, self.boy = klasor, sinir, 0, None, 0
        os.makedirs(klasor, exist_ok=True)
        self.kilit = threading.Lock()

    def yaz(self, yol, veri):
        with self.kilit:
            if self.z is None or self.boy + len(veri) > self.sinir:
                if self.z: self.z.close()
                self.no += 1; self.boy = 0
                self.z = zipfile.ZipFile(os.path.join(self.k, f'ticimax-gorsel-yedek-{self.no:02d}.zip'), 'w', zipfile.ZIP_STORED)
            self.z.writestr(yol, veri); self.boy += len(veri)

    def kapat(self):
        with self.kilit:
            if self.z: self.z.close(); self.z = None


def guvenli_ad(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s or '')[:80] or 'urun'


# ------------------------------------------------------------------ tek urun kontrolu
def urun_isle(u, yedek=None, sakla=False):
    s = {'sku': u['sku'], 'ad': u['ad'], 'slug': u['slug'], 'id': u['id'], 'varyantlar': u['varyantlar'],
         'ikas_sayi': len(u['ikas']), 'tici': [], 'ikas': [], 'esler': [], 'durum': '', 'neden': [],
         'tici_sayfa': u.get('tici_sayfa') or (TICI_SITE + '/' + u['slug'] if u['slug'] else ''), 'sayfa_esleme': u.get('sayfa_esleme', ''),
         'varyant_farkli': u.get('varyant_farkli', False), 'aciklama_tici': u.get('aciklama_tici', [])}
    if s['aciklama_tici']:
        s['neden'].append(f'açıklamada Ticimax\'a bağlı {len(s["aciklama_tici"])} görsel var (Ticimax kapanınca kırılır)')
        if yedek is not None:
            for a in s['aciklama_tici']:
                rr = al(a)
                if rr is not None and rr.status_code == 200:
                    yedek.yaz(f'_aciklama/{guvenli_ad(u["sku"])}/{guvenli_ad(unquote(a.rsplit("/", 1)[-1].split("?")[0]))}', rr.content)
    if not s['tici_sayfa']:
        s['durum'] = 'SLUG_YOK'; return s
    r = al(s['tici_sayfa'], zaman=40, engel_bekle=True)
    if r is None or r.status_code != 200:
        s['durum'] = 'TICIMAX_SAYFA_YOK'; s['neden'].insert(0, f'Ticimax sayfası açılmadı ({getattr(r, "status_code", "bağlantı yok")})'); return s
    galeri = tici_galeri(r.text)
    if not galeri:
        s['durum'] = 'TICIMAX_GORSEL_YOK'; return s
    # Ticimax orijinalleri
    tici_im, tici_b = [], []
    for n, dosya in enumerate(galeri):
        rr = al(tici_url(dosya))
        if rr is None or rr.status_code != 200:
            s['tici'].append({'dosya': dosya, 'url': tici_url(dosya), 'hata': getattr(rr, 'status_code', 'yok')}); tici_im.append(None); tici_b.append(None); continue
        im = ac(rr.content)
        s['tici'].append({'dosya': dosya, 'url': tici_url(dosya), 'en': im.size[0] if im else 0, 'boy': im.size[1] if im else 0, 'bayt': len(rr.content)})
        tici_im.append(im); tici_b.append(rr.content if im else None)
        if yedek is not None:
            yedek.yaz(f'{guvenli_ad(u["sku"])}__{guvenli_ad(u["slug"])[:50]}/{n + 1:02d}_{dosya}', rr.content)
    if sakla:
        s['_tici_im'], s['_tici_bayt'] = tici_im, tici_b
    # ikas gorselleri (Ticimax ana gorselinin genisligine gore)
    hedef_en = max([t['en'] for t in s['tici'] if t.get('en')] or [1080])
    ikas_im = []
    for img_id in u['ikas']:
        im, boy, bayt = ikas_indir(img_id, max(hedef_en, OLCUM_BOYUT))
        s['ikas'].append({'imageId': img_id, 'istenen': boy, 'en': im.size[0] if im else 0, 'boy': im.size[1] if im else 0, 'bayt': bayt})
        ikas_im.append(im)
    if not u['ikas']:
        s['durum'] = 'DUZELT'; s['neden'].insert(0, 'ikas\'ta hiç görsel yok')
        s['esler'] = [{'tici': ti, 'ikas': None, 'mesafe': None, 'yakin_ssim': None} for ti in range(len(tici_im)) if tici_im[ti] is not None]
        return s
    # esleme (pHash) ve olcum
    th = [phash(i) if i else None for i in tici_im]
    ih = [phash(i) if i else None for i in ikas_im]
    kullanildi = set()
    for ti, t in enumerate(tici_im):
        if t is None or th[ti] is None:
            continue
        en_iyi, mes = None, 99
        for ii, h in enumerate(ih):
            if h is None or ii in kullanildi:
                continue
            d = hmesafe(th[ti], h)
            if d < mes:
                en_iyi, mes = ii, d
        k = karsilastir(t, ikas_im[en_iyi]) if en_iyi is not None and mes <= ESIK_ESLESME else None
        if k and (k['ssim'] >= ESIK_AYNI or k['ayni']):
            kullanildi.add(en_iyi)
            s['esler'].append({'tici': ti, 'ikas': en_iyi, 'mesafe': mes, **k})
        else:
            s['esler'].append({'tici': ti, 'ikas': None, 'mesafe': mes, 'yakin_ssim': k['ssim'] if k else None})
    eksik = [e for e in s['esler'] if e['ikas'] is None]
    kotu = [e for e in s['esler'] if e['ikas'] is not None and kotu_mu(e)]
    ned = []
    if eksik:
        ned.append(f'{len(eksik)} Ticimax görseli ikas\'ta yok')
    if kotu:
        en_kotu = min(kotu, key=lambda e: e['keskinlik'])
        ned.append(f'{len(kotu)} görsel bulanık/düşük kalite (keskinlik %{round(en_kotu["keskinlik"] * 100)}, benzerlik %{round(en_kotu["ssim"] * 100)})')
        kucuk = [e for e in kotu if e['cozunurluk'] < ESIK_COZUNURLUK]
        if kucuk:
            e = min(kucuk, key=lambda x: x['cozunurluk'])
            ned.append(f'ikas\'taki görsel küçük: Ticimax boyutunun %{round(e["cozunurluk"] * 100)}\'i')
        if any(e['ssim'] >= ESIK_SSIM and e['renk'] > ESIK_RENK for e in kotu):
            ned.append('renkler farklı: başka bir görsel olabilir, elle bakın')
    ana = next((e for e in s['esler'] if e['tici'] == 0), None)
    if ana and ana['ikas'] not in (0, None):
        ned.append('ana görsel farklı sırada')
    fazla = len(u['ikas']) - len(kullanildi)
    if fazla > 0 and (eksik or kotu):
        ned.append(f'ikas\'ta Ticimax\'ta olmayan {fazla} görsel daha var (korunur)')
    if s['varyant_farkli'] and (eksik or kotu):
        ned.append('varyantların görselleri farklı: otomatik aktarılmaz, elle bakılmalı')
    s['neden'] = ned + s['neden']
    s['durum'] = 'DUZELT' if (eksik or kotu) else 'TAMAM'
    t0 = s['tici'][0] if s['tici'] else {}
    if t0.get('en') and max(t0['en'], t0['boy']) < KAYNAK_MIN:
        s['neden'].append(f'Ticimax\'taki ana görsel de küçük ({t0["en"]}x{t0["boy"]}): yeni fotoğraf gerekir')
        if s['durum'] == 'TAMAM':
            s['durum'] = 'KAYNAK_KUCUK'
    ks = [e['keskinlik'] for e in s['esler'] if e.get('keskinlik') is not None]
    s['min_keskinlik'] = min(ks) if ks else None
    return s


# ------------------------------------------------------------------ aktarim
class Durdur(Exception):
    pass


class Aktarim:
    """Semadan otomatik uretilen tam urun girdisiyle (saveProduct) guvenli gorsel degisimi"""
    def __init__(self, ikas):
        self.ikas = ikas
        self.dur = None
        self.tercih = 'url'
        self.kilit = threading.Lock()
        q = ikas.tip('Query')
        lp = q['alan']['listProduct'][1]
        self.urun_cikti = ikas.tip(lp)['alan']['data'][1]
        self.id_arg = q['arg'].get('listProduct', {}).get('id')
        m = ikas.tip('Mutation')['arg'].get('saveProduct') or {}
        if not m or not self.id_arg:
            raise RuntimeError('ikas şemasında saveProduct ya da listProduct(id) yok')
        self.kayit_arg, (_, self.urun_girdi, self.kayit_imza) = next(iter(m.items()))
        ug = ikas.tip(self.urun_girdi)['girdi']
        self.varyant_girdi = ug['variants'][1]
        self.gorsel_girdi = ikas.tip(self.varyant_girdi)['girdi']['images'][1]
        self.varyant_cikti = ikas.tip(self.urun_cikti)['alan']['variants'][1]
        self.sec = self._secim(self.urun_girdi, self.urun_cikti)
        self.silinmis_ayikla = 'deleted' in ikas.tip(self.varyant_cikti)['alan'] and 'deleted' not in ikas.tip(self.varyant_girdi)['girdi']
        if self.silinmis_ayikla:
            self.sec += ' variants{ id deleted }'
        fg = ikas.tip(self.id_arg[1])['girdi']
        self.id_filtre = 'eq' if 'eq' in fg else 'in'

    def _secim(self, gtip, otip, d=0):
        g = self.ikas.tip(gtip)['girdi']; o = self.ikas.tip(otip)['alan']; p = []
        for ad, (gk, gt, _) in g.items():
            if ad not in o:
                continue
            ok, ot, _ = o[ad]
            if gk == 'INPUT_OBJECT':
                if ok == 'OBJECT' and d < 6:
                    ic = self._secim(gt, ot, d + 1)
                    if ic:
                        p.append(ad + '{ ' + ic + ' }')
            elif ok in ('SCALAR', 'ENUM'):
                p.append(ad)
        return ' '.join(p)

    def eslenmeyen(self):
        """girdide olup okunamayan alanlar (kesif raporu icin)"""
        out = {}
        for gt, ot in ((self.urun_girdi, self.urun_cikti), (self.varyant_girdi, self.varyant_cikti)):
            o = self.ikas.tip(ot)['alan']
            out[gt] = [k for k in self.ikas.tip(gt)['girdi'] if k not in o]
        return out

    def getir(self, pid):
        q = 'query($i:%s){ listProduct(id:$i){ data{ %s } } }' % (self.id_arg[2], self.sec)
        d = self.ikas.sorgu(q, {'i': {'eq': pid} if self.id_filtre == 'eq' else {'in': [pid]}})['listProduct']['data'] or []
        return next((x for x in d if x.get('id') == pid), None)

    def aktif(self, urun):
        return [v for v in (urun.get('variants') or []) if not v.get('deleted')]

    def girdiye(self, deger, gtip=None):
        gtip = gtip or self.urun_girdi
        g = self.ikas.tip(gtip)['girdi']
        out = {}
        for k, v in deger.items():
            if k not in g or v is None:
                continue
            gk, gt, _ = g[k]
            if gk == 'INPUT_OBJECT':
                if isinstance(v, list):
                    liste = [x for x in v if isinstance(x, dict)]
                    if k == 'variants' and gtip == self.urun_girdi and self.silinmis_ayikla:
                        liste = [x for x in liste if not x.get('deleted')]
                    out[k] = [self.girdiye(x, gt) for x in liste]
                elif isinstance(v, dict):
                    out[k] = self.girdiye(v, gt)
            else:
                out[k] = v
        return out

    def kaydet(self, girdi):
        q = 'mutation($g:%s){ saveProduct(%s:$g){ id } }' % (self.kayit_imza, self.kayit_arg)
        return self.ikas.sorgu(q, {'g': girdi})

    @staticmethod
    def _duz(x, yol, out, gorsel_haric):
        if isinstance(x, dict):
            for k in sorted(x):
                if gorsel_haric and k == 'images':
                    continue
                Aktarim._duz(x[k], yol + '.' + k, out, gorsel_haric)
        elif isinstance(x, list):
            if x and all(isinstance(i, dict) and 'id' in i for i in x):
                for i in sorted(x, key=lambda i: str(i['id'])):
                    Aktarim._duz(i, f'{yol}[{i["id"]}]', out, gorsel_haric)
            elif all(not isinstance(i, (dict, list)) for i in x):
                out[yol] = sorted(map(str, x))
            else:
                for n, i in enumerate(x):
                    Aktarim._duz(i, f'{yol}[{n}]', out, gorsel_haric)
        else:
            out[yol] = x

    def fark(self, a, b, gorsel_haric=False):
        da, db = {}, {}
        self._duz(a, '', da, gorsel_haric); self._duz(b, '', db, gorsel_haric)
        return [k.lstrip('.') for k in sorted(set(da) | set(db)) if da.get(k) != db.get(k)]

    def gorsel_girdisi(self, liste, urun):
        gi = self.ikas.tip(self.gorsel_girdi)['girdi']
        mevcut = {g['imageId']: g for v in self.aktif(urun) for g in (v.get('images') or []) if g.get('imageId')}
        out = []
        for i, iid in enumerate(liste):
            d = {k: v for k, v in (mevcut.get(iid) or {}).items() if k in gi and v is not None}
            d['imageId'] = iid
            if 'isMain' in gi:
                d['isMain'] = i == 0
            if 'order' in gi:
                d['order'] = i
            out.append(d)
        return out

    def yedekle(self, urun, girdi):
        os.makedirs(AKTAR_ONCESI, exist_ok=True)
        p = os.path.join(AKTAR_ONCESI, guvenli_ad(urun['id']) + '.json')
        if not os.path.exists(p):      # ilk (en eski) hal korunur
            with open(p, 'w', encoding='utf-8') as f:
                json.dump({'zaman': time.strftime('%Y-%m-%d %H:%M:%S'), 'urun': urun, 'girdi': girdi}, f, ensure_ascii=False)

    @staticmethod
    def _mime(veri):
        return 'image/png' if veri[:8] == b'\x89PNG\r\n\x1a\n' else 'image/webp' if veri[8:12] == b'WEBP' else 'image/gif' if veri[:3] == b'GIF' else 'image/jpeg'

    @staticmethod
    def _sigdir(veri, sinir=9_000_000):
        if len(veri) <= sinir:
            return veri
        im = Image.open(io.BytesIO(veri)); b = io.BytesIO()
        if im.mode in ('RGBA', 'LA', 'P'):
            im.convert('RGBA').save(b, 'PNG', optimize=True)
        else:
            im.convert('RGB').save(b, 'JPEG', quality=93, subsampling=0, optimize=True)
        return b.getvalue()

    def yukle(self, vids, url, veri, sira):
        """once adresle (ikas sunucusu Ticimax'tan kendisi ceker - hizli), olmazsa dosyayi gonder"""
        hatalar = []
        yollar = ['url', 'base64', 'base64-uri']
        yollar.sort(key=lambda y: y != self.tercih)
        for yol in yollar:
            if yol == 'url':
                ek = {'url': url}
            else:
                v = self._sigdir(veri); b64 = base64.b64encode(v).decode()
                ek = {'base64': b64 if yol == 'base64' else f'data:{self._mime(v)};base64,{b64}'}
            govde = {'productImage': {'variantIds': vids, 'order': sira, 'isMain': False, **ek}}
            r = None
            for d in range(5):
                try:
                    r = requests.post(IKAS_UPLOAD, json=govde, headers=self.ikas.baslik(), timeout=180)
                except requests.RequestException as e:
                    hatalar.append(f'{yol}: {e}'); time.sleep(2 * (d + 1)); continue
                if r.status_code == 401:
                    with self.ikas.kilit:
                        self.ikas._yetki()
                    continue
                if r.status_code == 429 or r.status_code >= 502:
                    time.sleep(min(60, 2 ** d * 2)); continue
                break
            if r is not None and r.ok:
                self.tercih = yol
                return yol, None
            if r is not None:
                hatalar.append(f'{yol}: {r.status_code} {r.text[:160]}')
        return None, ' | '.join(hatalar)[:400]

    def yeni_esle(self, yeni, yuklendi, tici_im):
        bekl = {1000 + ti: ti for ti in yuklendi}
        m = {}
        for g in yeni:
            o = g.get('order')
            if o is not None and int(round(o)) in bekl and bekl[int(round(o))] not in m:
                m[bekl[int(round(o))]] = g['imageId']
        if len(m) == len(yeni) == len(yuklendi):
            return m
        m, kalan = {}, {ti: phash(tici_im[ti]) for ti in yuklendi}
        for g in yeni:
            im, _, _ = ikas_indir_bekle(g['imageId'], 360)
            if im is None or not kalan:
                continue
            h = phash(im)
            ti = min(kalan, key=lambda t: hmesafe(kalan[t], h))
            if hmesafe(kalan[ti], h) <= ESIK_ESLESME:
                m[ti] = g['imageId']; del kalan[ti]
        return m

    def dogrula(self, nid, t_im):
        im, boy, _ = ikas_indir_bekle(nid, max(t_im.size[0], OLCUM_BOYUT))
        if im is None:
            return False, 'ikas CDN görseli vermedi'
        k = karsilastir(t_im, im)
        hedef = min(max(t_im.size), 1600) * 0.95
        ok = max(im.size) >= hedef and k['keskinlik'] >= max(ESIK_KESKINLIK, 0.7) and k['ssim'] >= ESIK_SSIM and k['renk'] <= ESIK_RENK
        return ok, f'{im.size[0]}x{im.size[1]} keskinlik %{round(k["keskinlik"] * 100)} benzerlik %{round(k["ssim"] * 100)}'

    def urun(self, s):
        r = {'sku': s['sku'], 'ad': s['ad'], 'id': s['id'], 'slug': s['slug'], 'sonuc': '', 'not': [], 'yuklenen': 0, 'yontem': '', 'fark': [], 'once': [], 'sonra': []}
        if self.dur:
            r['sonuc'] = 'DURDURULDU'; r['not'].append(self.dur); return r
        try:
            return self._urun(s, r)
        except Durdur as e:
            with self.kilit:
                self.dur = self.dur or f'{s["sku"]}: {e}'
            r['sonuc'] = 'DURDURULDU'; r['not'].append(str(e)); return r
        except Exception as e:
            r['sonuc'] = 'HATA'; r['not'].append(str(e)[:300]); return r

    def _urun(self, s, r):
        if s['durum'] != 'DUZELT':
            r['sonuc'] = 'ATLANDI'; r['not'].append('düzeltme gerekmiyor'); return r
        if s.get('varyant_farkli'):
            r['sonuc'] = 'ELLE'; r['not'].append('varyantların görselleri farklı; elle bakılmalı'); return r
        tici_im, tici_b = s.get('_tici_im') or [], s.get('_tici_bayt') or []
        once = self.getir(s['id'])
        if not once:
            r['sonuc'] = 'HATA'; r['not'].append('ürün ikas\'tan okunamadı'); return r
        aktif = self.aktif(once)
        if not aktif:
            r['sonuc'] = 'ELLE'; r['not'].append('aktif varyant yok'); return r
        setler = {tuple(sorted(g['imageId'] for g in (v.get('images') or []) if g.get('imageId'))) for v in aktif}
        if len(setler) > 1:
            r['sonuc'] = 'ELLE'; r['not'].append('varyantların görselleri farklı; elle bakılmalı'); return r
        once_ids = [g['imageId'] for g in sorted(aktif[0].get('images') or [], key=lambda g: (not g.get('isMain'), g.get('order') or 0)) if g.get('imageId')]
        r['once'] = once_ids
        if set(once_ids) != set(x['imageId'] for x in s['ikas']):
            r['sonuc'] = 'ATLANDI'; r['not'].append('görseller kontrolden sonra değişmiş; tekrar çalıştırın'); return r
        eski, bozuk = {}, set()
        for e in s['esler']:
            if e['ikas'] is not None:
                eski[e['tici']] = s['ikas'][e['ikas']]['imageId']
            if kotu_mu(e):
                bozuk.add(e['tici'])
        yap = [ti for ti in sorted(bozuk) if ti < len(tici_im) and tici_im[ti] is not None and tici_b[ti]]
        if not yap:
            r['sonuc'] = 'ATLANDI'; r['not'].append('Ticimax orijinali indirilemedi'); return r
        # 1) aktarim oncesi hali sakla (her yazmadan once)
        g0 = self.girdiye(once)
        self.yedekle(once, g0)
        # 2) degistirmeden kaydet -> tekrar oku -> hicbir alan degismemeli (sema gidis-donus guvencesi)
        self.kaydet(g0)
        kontrol = self.getir(s['id'])
        f0 = self.fark(g0, self.girdiye(kontrol)) if kontrol else ['ürün okunamadı']
        if f0:
            raise Durdur('değiştirmeden kaydetme denemesinde ürün bilgisi değişti (' + ', '.join(f0[:6]) + '); hiçbir görsel yüklenmedi')
        # 3) yukle
        vids = [v['id'] for v in aktif]
        yuklendi = {}
        for ti in yap:
            yol, hata = self.yukle(vids, s['tici'][ti]['url'], tici_b[ti], 1000 + ti)
            if yol:
                yuklendi[ti] = yol
            else:
                r['not'].append(f'{ti + 1}. görsel yüklenemedi: {hata}')
        if not yuklendi:
            r['sonuc'] = 'HATA'; return r
        r['yontem'] = ','.join(sorted(set(yuklendi.values())))
        # 4) yeni gorselleri bul
        once_set, son, yeni = set(once_ids), None, []
        for d in range(10):
            son = self.getir(s['id'])
            yeni = [g for g in (self.aktif(son)[0].get('images') or []) if g.get('imageId') and g['imageId'] not in once_set] if son and self.aktif(son) else []
            if len(yeni) >= len(yuklendi):
                break
            time.sleep(BEKLE)
        eslem = self.yeni_esle(yeni, yuklendi, tici_im)
        # 5) dogrula: yeni gorsel gercekten Ticimax orijinali kalitesinde mi?
        iyi = {}
        for ti, nid in sorted(eslem.items()):
            ok, bilgi = self.dogrula(nid, tici_im[ti])
            if ok:
                iyi[ti] = nid
            else:
                r['not'].append(f'{ti + 1}. görsel doğrulanamadı ({bilgi}); eskisi korundu')
        # 6) son liste: Ticimax sirasi; iyi yeni > eski; ikas'taki fazlalar sona
        liste = []
        for ti in range(len(s['tici'])):
            if ti in iyi:
                liste.append(iyi[ti])
            elif ti in eski:
                liste.append(eski[ti])
        fazla = [i for i in once_ids if i not in set(eski.values())]
        if fazla and not FAZLA_SIL:
            liste += fazla
            r['not'].append(f'ikas\'taki {len(fazla)} fazla görsel korundu')
        liste = list(dict.fromkeys(liste))
        # 7) kaydet (en guncel hal uzerinden, sadece gorsel listesi degisir)
        g1 = self.girdiye(son)
        for v in g1.get('variants') or []:
            if v.get('id') in vids:
                v['images'] = self.gorsel_girdisi(liste, son)
        self.kaydet(g1)
        sonra = self.getir(s['id'])
        # 8) kontrol
        ids = [g['imageId'] for g in sorted(self.aktif(sonra)[0].get('images') or [], key=lambda g: (not g.get('isMain'), g.get('order') or 0))] if sonra else []
        r['sonra'] = ids
        if ids != liste:
            r['not'].append('kayıttan sonra görsel listesi beklenenden farklı')
        r['fark'] = self.fark(g0, self.girdiye(sonra), gorsel_haric=True) if sonra else ['ürün okunamadı']
        r['yuklenen'] = len(iyi)
        r['sonuc'] = 'AKTARILDI' if len(iyi) == len(yap) and ids == liste else ('KISMEN' if iyi else 'HATA')
        if r['fark']:
            raise Durdur('görsel dışında alan değişti: ' + ', '.join(r['fark'][:6]) + ' (aktar-oncesi kaydından geri alınabilir)')
        return r

    def geri_al(self, u):
        r = {'sku': u['sku'], 'ad': u['ad'], 'id': u['id'], 'slug': u['slug'], 'sonuc': '', 'not': [], 'yuklenen': 0, 'yontem': 'geri-al', 'fark': [], 'once': [], 'sonra': []}
        p = os.path.join(AKTAR_ONCESI, guvenli_ad(u['id']) + '.json')
        if not os.path.exists(p):
            r['sonuc'] = 'ATLANDI'; r['not'].append('aktarım öncesi kaydı yok'); return r
        kayit = json.load(open(p, encoding='utf-8'))
        y = kayit['urun']
        son = self.getir(u['id'])
        gi = self.ikas.tip(self.gorsel_girdi)['girdi']
        yv = {v['id']: v for v in self.aktif(y)}
        if os.environ.get('GERI_AL_TAM') == '1':      # tum urun bilgisi (fiyat, aciklama...) aktarim oncesine doner
            self.kaydet(kayit['girdi'])
            yv = {}
        g = self.girdiye(son)
        for v in ([] if not yv else g.get('variants') or []):
            if v.get('id') in yv:
                v['images'] = [{k: x for k, x in img.items() if k in gi and x is not None}
                               for img in sorted(yv[v['id']].get('images') or [], key=lambda i: (not i.get('isMain'), i.get('order') or 0))]
        if yv:
            self.kaydet(g)
        sonra = self.getir(u['id'])
        bekl = [i['imageId'] for i in sorted(self.aktif(y)[0].get('images') or [], key=lambda i: (not i.get('isMain'), i.get('order') or 0))]
        ids = [i['imageId'] for i in sorted(self.aktif(sonra)[0].get('images') or [], key=lambda i: (not i.get('isMain'), i.get('order') or 0))]
        r['once'], r['sonra'] = bekl, ids
        r['sonuc'] = 'GERI_ALINDI' if ids == bekl else 'HATA'
        return r


# ------------------------------------------------------------------ buyutme denemesi
MODEL_URL = {
    'yapay-zeka-foto': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
    'yapay-zeka-genel': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth',
}
HEDEF_UZUN = int(os.environ.get('BUYUT_HEDEF', '1600'))     # buyutulmus gorselin uzun kenari
EKRAN = int(os.environ.get('EKRAN_BOYU', '700'))            # urun sayfasinda gorselin gosterildigi genislik (karsilastirma icin)


def _beyaz_zemin(im):
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA'); z = Image.new('RGBA', im.size, (255, 255, 255, 255)); z.alpha_composite(im); im = z
    return im.convert('RGB')


def _klasik(im, hedef):
    """yapay zekasiz: Lanczos buyutme + hafif keskinlestirme (uydurma ayrinti eklemez)"""
    from PIL import ImageFilter
    o = hedef / max(im.size)
    b = im.resize((round(im.size[0] * o), round(im.size[1] * o)), Image.LANCZOS)
    return b.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))


_MODEL = {}


def _model(ad):
    if ad not in _MODEL:
        import torch
        from spandrel import ModelLoader
        yol = os.path.join(os.path.expanduser('~'), '.cache', ad + '.pth')
        if not os.path.exists(yol):
            os.makedirs(os.path.dirname(yol), exist_ok=True)
            r = requests.get(MODEL_URL[ad], timeout=300); r.raise_for_status()
            open(yol, 'wb').write(r.content)
        m = ModelLoader().load_from_file(yol)
        try:
            m.model.eval()
        except Exception:
            pass
        torch.set_num_threads(max(1, os.cpu_count() or 2))
        _MODEL[ad] = m
    return _MODEL[ad]


def _yapay_zeka(ad, im, hedef, parca=192, pay=12):
    import torch
    m = _model(ad)
    x = torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0)
    _, _, h, w = x.shape
    k = int(getattr(m, 'scale', 4) or 4)
    cikis = torch.zeros((1, 3, h * k, w * k))
    for y0 in range(0, h, parca):
        for x0 in range(0, w, parca):
            y1, x1 = min(y0 + parca, h), min(x0 + parca, w)
            ya, xa, yb, xb = max(0, y0 - pay), max(0, x0 - pay), min(h, y1 + pay), min(w, x1 + pay)
            with torch.inference_mode():
                o = m(x[:, :, ya:yb, xa:xb])
            cikis[:, :, y0 * k:y1 * k, x0 * k:x1 * k] = o[:, :, (y0 - ya) * k:(y1 - ya) * k, (x0 - xa) * k:(x1 - xa) * k]
    a = (cikis.clamp(0, 1)[0].permute(1, 2, 0).numpy() * 255.0).round().astype(np.uint8)
    b = Image.fromarray(a)
    o = hedef / max(b.size)
    return b.resize((round(b.size[0] * o), round(b.size[1] * o)), Image.LANCZOS) if o < 1 else b


def buyut_deneme(urunler, cikti_dir):
    """Secilen urunlerin Ticimax orijinallerini birkac yontemle buyutur; urun sayfasindaki gibi yan yana gosterir.
    Magazada hicbir sey degistirmez."""
    from PIL import ImageDraw
    kl = os.path.join(cikti_dir, 'buyut'); os.makedirs(kl, exist_ok=True)
    yontemler = ['klasik'] + list(MODEL_URL)
    notlar, sayfa, sure = [], [], {}
    for u in urunler:
        r = al(u.get('tici_sayfa') or TICI_SITE + '/' + u['slug'], engel_bekle=True)
        gal = tici_galeri(r.text) if r is not None and r.status_code == 200 else []
        if not gal:
            notlar.append(f'{u["sku"]}: Ticimax sayfası/görseli bulunamadı'); continue
        for n, dosya in enumerate(gal[:4], 1):
            rr = al(tici_url(dosya))
            if rr is None or rr.status_code != 200:
                continue
            ham = Image.open(io.BytesIO(rr.content)); ham.load()
            im = _beyaz_zemin(ham)
            ad = f'{guvenli_ad(u["sku"])}_{n}'
            im.save(os.path.join(kl, ad + '_0-ticimax.png'))
            sonuc = {'ticimax (geriliyor)': im}
            for y in yontemler:
                t0 = time.time()
                try:
                    b = _klasik(im, HEDEF_UZUN) if y == 'klasik' else _yapay_zeka(y, im, HEDEF_UZUN)
                except Exception as e:
                    notlar.append(f'{y}: {str(e)[:200]}'); continue
                sure.setdefault(y, []).append(round(time.time() - t0, 1))
                b.save(os.path.join(kl, f'{ad}_{y}.jpg'), 'JPEG', quality=95, subsampling=0)
                sonuc[y] = b
            # yan yana: ustte urun sayfasindaki boyut (EKRAN px), altta en ayrintili bolge yakin plan
            kutu = _detay_penceresi(im, max(48, min(im.size) // 4))
            tuval = Image.new('RGB', (len(sonuc) * (EKRAN + 12) + 12, 24 + EKRAN + 8 + EKRAN + 30), 'white')
            d = ImageDraw.Draw(tuval)
            d.text((12, 6), f'{u["sku"]} - gorsel {n} (Ticimax {im.size[0]}x{im.size[1]})', fill=(3, 28, 55))
            for i, (etiket, b) in enumerate(sonuc.items()):
                x = 12 + i * (EKRAN + 12)
                o = EKRAN / max(b.size)
                g = b.resize((max(1, round(b.size[0] * o)), max(1, round(b.size[1] * o))), Image.BICUBIC)   # tarayicinin yaptigi gibi
                tuval.paste(g, (x + (EKRAN - g.size[0]) // 2, 24 + (EKRAN - g.size[1]) // 2))
                oo = b.size[0] / im.size[0]
                kr = b.crop(tuple(round(v * oo) for v in kutu)).resize((EKRAN, EKRAN), Image.LANCZOS)
                tuval.paste(kr, (x, 24 + EKRAN + 8))
                d.text((x, tuval.size[1] - 22), etiket, fill=(3, 28, 55))
            yol = f'karsilastir_{ad}.jpg'
            tuval.save(os.path.join(kl, yol), 'JPEG', quality=92)
            sayfa.append(f'<section><h2>{htmlmod.escape(u["ad"])} <small>{htmlmod.escape(u["sku"])} · görsel {n} · Ticimax {im.size[0]}×{im.size[1]}</small></h2>'
                         f'<img src="{yol}" alt=""></section>')
    with open(os.path.join(kl, 'buyutme-karsilastirma.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Büyütme karşılaştırması</title><style>body{font-family:system-ui;margin:0;background:#f5f6f8;color:#031c37}'
                'header{background:#031c37;color:#fff;padding:16px 24px}section{background:#fff;margin:16px;padding:16px;border-radius:12px}img{max-width:100%}h2{font-size:16px}small{color:#5b6474;font-weight:400}</style></head><body>'
                '<header><b>Büyütme karşılaştırması</b> · üstte ürün sayfasındaki boyut, altta ayrıntı yakın plan · soldan: Ticimax (tarayıcı geriyor), klasik, yapay zekâ (foto), yapay zekâ (genel)</header>'
                + ''.join(sayfa) + '</body></html>')
    return {'notlar': notlar, 'sure_sn': sure, 'gorsel': len(sayfa)}


# ------------------------------------------------------------------ kesif
KALITE_BOYUTLAR = [540, 720, 1080, 1296, 1728, 2560]


def _detay_penceresi(im, k=96):
    """en ayrintili (keskinlik farkini en iyi gosteren) k x k bolge"""
    g = np.asarray(im.convert('L'), dtype=np.float64)
    h, w = g.shape
    if h < k or w < k:
        return (0, 0, w, h)
    en, yer = -1, (0, 0)
    adim = max(8, k // 3)
    for y in range(0, h - k + 1, adim):
        for x in range(0, w - k + 1, adim):
            v = _lap(g[y:y + k, x:x + k]).var()
            if v > en:
                en, yer = v, (x, y)
    return (yer[0], yer[1], yer[0] + k, yer[1] + k)


def _karsilastirma_resmi(ad, tici_im, surumler, dosya):
    """ayni bolge, 4 kat buyutulmus: Ticimax orijinali | Ticimax sitesinde | ikas boyutlari"""
    from PIL import ImageDraw
    kutu = _detay_penceresi(tici_im)
    kare = 4 * (kutu[2] - kutu[0])
    parca = [('Ticimax orijinal', tici_im)] + surumler
    tuval = Image.new('RGB', (len(parca) * (kare + 10) + 10, kare + 60), 'white')
    d = ImageDraw.Draw(tuval)
    d.text((10, 6), ad[:120], fill=(3, 28, 55))
    for n, (etiket, im) in enumerate(parca):
        if im.size != tici_im.size:
            im = im.resize(tici_im.size, Image.LANCZOS)
        tuval.paste(im.crop(kutu).resize((kare, kare), Image.NEAREST), (10 + n * (kare + 10), 26))
        d.text((10 + n * (kare + 10), kare + 32), etiket, fill=(3, 28, 55))
    tuval.save(dosya)


def kalite_boyut(ornek, cikti_dir):
    """ikas ayni gorseli istenen boyuta gore farkli sikistirmayla veriyor mu? Her boyutu Ticimax orijinaliyle olc."""
    ozet, detay, resim = {}, [], 0
    for u in ornek:
        r = al(u.get('tici_sayfa') or TICI_SITE + '/' + u['slug'], engel_bekle=True)
        gal = tici_galeri(r.text) if r is not None and r.status_code == 200 else []
        if not gal or not u['ikas']:
            continue
        rr = al(tici_url(gal[0]))
        t = ac(rr.content) if rr is not None and rr.status_code == 200 else None
        if t is None:
            continue
        satir = {'sku': u['sku'], 'ticimax': f'{t.size[0]}x{t.size[1]}:{len(rr.content) // 1024}KB', 'boyut': {}}
        surumler = []
        if 'static.ticimax.cloud/' in tici_url(gal[0]):
            cu = 'https://static.ticimax.cloud/cdn-cgi/image/width=' + str(t.size[0]) + ',quality=85,format=webp/' + tici_url(gal[0]).split('static.ticimax.cloud/', 1)[1]
            cr = al(cu, deneme=2)
            ci = ac(cr.content) if cr is not None and cr.status_code == 200 else None
            if ci is not None:
                k = karsilastir(t, ci)
                satir['boyut']['ticimax_sitesi_q85'] = {'kb': round(len(cr.content) / 1024, 1), 'px': f'{ci.size[0]}x{ci.size[1]}', **k}
                ozet.setdefault('ticimax_sitesi_q85', []).append((len(cr.content), k))
                surumler.append(('Ticimax sitesinde', ci))
        ilk = None
        for b in KALITE_BOYUTLAR:
            ir = al(ikas_url(u['ikas'][0], b), deneme=2)
            im = ac(ir.content) if ir is not None and ir.status_code == 200 else None
            if im is None:
                continue
            if ilk is None:
                ilk = im
                if hmesafe(phash(t), phash(im)) > ESIK_ESLESME:
                    satir['not'] = 'ikas ana görseli Ticimax ana görseliyle eşleşmedi'
                    break
            k = karsilastir(t, im)
            satir['boyut'][f'ikas_{b}'] = {'kb': round(len(ir.content) / 1024, 1), 'px': f'{im.size[0]}x{im.size[1]}', **k}
            ozet.setdefault(f'ikas_{b}', []).append((len(ir.content), k))
            if b in (540, 1296, 2560):
                surumler.append((f'ikas image_{b}', im))
        detay.append(satir)
        if resim < 6 and len(surumler) >= 3:
            resim += 1
            try:
                _karsilastirma_resmi(f'{u["sku"]} {u["ad"]}', t, surumler, os.path.join(cikti_dir, f'kalite-karsilastirma-{resim}.png'))
            except Exception as e:
                satir['resim_hata'] = str(e)[:200]
    ort = {}
    for ad, l in ozet.items():
        ort[ad] = {'ornek': len(l), 'ort_kb': round(sum(b for b, _ in l) / len(l) / 1024, 1),
                   'ort_keskinlik': round(sum(k['keskinlik'] for _, k in l) / len(l), 3),
                   'ort_benzerlik': round(sum(k['ssim'] for _, k in l) / len(l), 3),
                   'ort_renk': round(sum(k['renk'] for _, k in l) / len(l), 2)}
    return {'ortalama': ort, 'urunler': detay}


def kesif(ikas, urunler, n=30, harita=None):
    sonuc = {'ikas_boyutlari': {}, 'ticimax_klasorleri': {}, 'sema': {}, 'ticimax_eslesme': {}}
    if harita is not None:
        say = {}
        for u in urunler:
            k = (u.get('sayfa_esleme') or 'yok').split('-%')[0]
            say[k] = say.get(k, 0) + 1
        sonuc['ticimax_eslesme'] = {'sitemap_adres_sayisi': harita.adet, 'ikas_urun': len(urunler), 'eslesme': say,
                                   'ornek_eslesmeyen': [u['slug'] for u in urunler if (u.get('sayfa_esleme') or 'yok') == 'yok'][:15],
                                   'ornek_benzer': [(u['slug'], u.get('tici_sayfa')) for u in urunler if (u.get('sayfa_esleme') or '').startswith('benzer')][:15]}
    sonuc['aciklama'] = {'ticimax_gorselli_urun': sum(1 for u in urunler if u.get('aciklama_tici')),
                         'toplam_gorsel': sum(len(u.get('aciklama_tici') or []) for u in urunler),
                         'ornek': [x for u in urunler for x in (u.get('aciklama_tici') or [])][:10]}
    ornek = [u for u in urunler if u['ikas'] and u['slug']][:n]
    for u in ornek[:12]:
        img = u['ikas'][0]
        for b in IKAS_BOYUTLAR:
            r = al(ikas_url(img, b), deneme=1)
            im = ac(r.content) if r is not None and r.status_code == 200 else None
            sonuc['ikas_boyutlari'].setdefault(str(b), []).append(f'{r.status_code if r is not None else "yok"}:{im.size[0]}x{im.size[1]}:{len(r.content) // 1024}KB' if im else f'{r.status_code if r is not None else "yok"}')
    try:
        os.makedirs(CIKTI, exist_ok=True)
        sonuc['kalite_boyut'] = kalite_boyut(ornek[:12], CIKTI)
    except Exception as e:
        sonuc['kalite_boyut'] = {'hata': str(e)[:300]}
    for u in ornek[:10]:
        r = al(u.get('tici_sayfa') or TICI_SITE + '/' + u['slug'], engel_bekle=True)
        gal = tici_galeri(r.text) if r is not None and r.status_code == 200 else []
        if not gal:
            continue
        for k in TICI_KLASORLER:
            rr = al(tici_url(gal[0], k), deneme=1)
            im = ac(rr.content) if rr is not None and rr.status_code == 200 else None
            sonuc['ticimax_klasorleri'].setdefault(k, []).append(f'{rr.status_code if rr is not None else "yok"}:{im.size[0]}x{im.size[1]}:{len(rr.content) // 1024}KB' if im else f'{rr.status_code if rr is not None else "yok"}')
    if ikas is not None:
        try:
            muts = ikas.alanlar('Mutation')
            sonuc['sema']['gorsel_mutasyonlari'] = sorted(k for k in muts if re.search(r'image|product', k, re.I))
            for t in ('ProductInput', 'VariantInput', 'ProductImageInput', 'VariantImageInput', 'ProductVariantInput'):
                sonuc['sema'][t] = ikas.girdiler(t)
            a = Aktarim(ikas)
            sonuc['sema']['aktarim'] = {'urun_girdi': a.urun_girdi, 'varyant_girdi': a.varyant_girdi, 'gorsel_girdi': a.gorsel_girdi,
                                        'okunamayan_girdi_alanlari': a.eslenmeyen(), 'silinmis_varyant_ayiklama': a.silinmis_ayikla,
                                        'secim_uzunlugu': len(a.sec)}
            if ornek:
                p = a.getir(ornek[0]['id'])
                sonuc['sema']['ornek_girdi_anahtarlari'] = sorted(a.girdiye(p).keys()) if p else 'okunamadı'
        except Exception as e:
            sonuc['sema']['hata'] = str(e)[:600]
    return sonuc


# ------------------------------------------------------------------ rapor
DURUM_TR = {'DUZELT': 'Düzeltilmeli', 'TAMAM': 'Tamam', 'KAYNAK_KUCUK': 'Ticimax\'ta da küçük', 'TICIMAX_SAYFA_YOK': 'Ticimax sayfası bulunamadı',
            'TICIMAX_GORSEL_YOK': 'Ticimax\'ta görsel yok', 'SLUG_YOK': 'ikas\'ta ürün adresi (slug) yok', 'HATA': 'Kontrol hatası'}
AKTAR_TR = {'AKTARILDI': 'Aktarıldı', 'KISMEN': 'Kısmen aktarıldı', 'HATA': 'Hata', 'ELLE': 'Elle bakılmalı', 'ATLANDI': 'Atlandı',
            'DURDURULDU': 'Durduruldu', 'GERI_ALINDI': 'Geri alındı'}


def _temiz(s):
    return {k: v for k, v in s.items() if not k.startswith('_')}


def _dilim(deger, sinirlar):
    for a, b, ad in sinirlar:
        if a <= deger < b:
            return ad
    return sinirlar[-1][2]


def rapor_yaz(sonuclar, kesif_sonuc=None, aktarim=None):
    os.makedirs(CIKTI, exist_ok=True)
    with open(os.path.join(CIKTI, 'gorsel-sonuc.json'), 'w', encoding='utf-8') as f:
        json.dump({'kesif': kesif_sonuc, 'urunler': [_temiz(s) for s in sonuclar], 'aktarim': aktarim}, f, ensure_ascii=False, indent=1)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    def baslik(ws):
        for c in ws[1]:
            c.font = Font(bold=True, color='FFFFFF'); c.fill = PatternFill('solid', fgColor='031C37')
        ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions

    wb = Workbook(); ws = wb.active; ws.title = 'Görsel kontrol'
    ws.append(['Durum', 'Neden', 'Stok kodu', 'Ürün', 'Ticimax görsel', 'ikas görsel', 'Ticimax ana görsel (px)', 'ikas ana görsel (px)',
               'En düşük keskinlik %', 'Ticimax sayfası', 'Sayfa nasıl bulundu', 'ikas sayfası', 'Açıklamada Ticimax görseli'])
    sira = {'DUZELT': 0, 'KAYNAK_KUCUK': 1, 'TICIMAX_SAYFA_YOK': 2, 'TICIMAX_GORSEL_YOK': 3, 'SLUG_YOK': 4, 'HATA': 5, 'TAMAM': 6}
    for s in sorted(sonuclar, key=lambda x: (sira.get(x['durum'], 9), x.get('min_keskinlik') if x.get('min_keskinlik') is not None else 9)):
        t0 = s['tici'][0] if s['tici'] else {}
        i0 = s['ikas'][0] if s['ikas'] else {}
        ws.append([DURUM_TR.get(s['durum'], s['durum']), '; '.join(s['neden']), s['sku'], s['ad'], len(s['tici']), s['ikas_sayi'],
                   f'{t0.get("en", "")}x{t0.get("boy", "")}' if t0.get('en') else '', f'{i0.get("en", "")}x{i0.get("boy", "")}' if i0.get('en') else '',
                   round(s['min_keskinlik'] * 100) if s.get('min_keskinlik') is not None else '', s.get('tici_sayfa', ''), s.get('sayfa_esleme', ''),
                   ONYUZ + '/' + s['slug'], len(s.get('aciklama_tici') or []) or ''])
        if s['durum'] == 'DUZELT':
            ws.cell(ws.max_row, 1).fill = PatternFill('solid', fgColor='FFE3D1')
    for col, g in zip('ABCDEFGHIJKLM', (18, 55, 16, 50, 9, 9, 14, 14, 12, 40, 14, 40, 12)):
        ws.column_dimensions[col].width = g
    baslik(ws)
    # gorsel detay (esik ayari icin)
    wd = wb.create_sheet('Görsel detay')
    wd.append(['Stok kodu', 'Sıra', 'Ticimax dosya', 'Ticimax px', 'Ticimax KB', 'ikas imageId', 'ikas px', 'Keskinlik %', 'Benzerlik %', 'Renk farkı', 'Çözünürlük %', 'Sonuç'])
    hist = {'keskinlik': {}, 'benzerlik': {}}
    for s in sonuclar:
        for e in s['esler']:
            t = s['tici'][e['tici']] if e['tici'] < len(s['tici']) else {}
            i = s['ikas'][e['ikas']] if e['ikas'] is not None else {}
            if e['ikas'] is not None:
                hist['keskinlik'][_dilim(e['keskinlik'], [(-9, .3, '<%30'), (.3, .55, '%30-55'), (.55, .8, '%55-80'), (.8, 1.0, '%80-100'), (1.0, 99, '>%100')])] = \
                    hist['keskinlik'].get(_dilim(e['keskinlik'], [(-9, .3, '<%30'), (.3, .55, '%30-55'), (.55, .8, '%55-80'), (.8, 1.0, '%80-100'), (1.0, 99, '>%100')]), 0) + 1
                d = _dilim(e['ssim'], [(-9, .6, '<%60'), (.6, .8, '%60-80'), (.8, .9, '%80-90'), (.9, .97, '%90-97'), (.97, 9, '>%97')])
                hist['benzerlik'][d] = hist['benzerlik'].get(d, 0) + 1
            wd.append([s['sku'], e['tici'] + 1, t.get('dosya', ''), f'{t.get("en", "")}x{t.get("boy", "")}', round((t.get('bayt') or 0) / 1024),
                       i.get('imageId', ''), f'{i.get("en", "")}x{i.get("boy", "")}' if i else '',
                       round(e['keskinlik'] * 100) if e.get('keskinlik') is not None else '', round(e['ssim'] * 100) if e.get('ssim') is not None else '',
                       e.get('renk', ''), round(e['cozunurluk'] * 100) if e.get('cozunurluk') is not None else '',
                       'ikas\'ta yok' if e['ikas'] is None else ('kötü' if kotu_mu(e) else 'iyi')])
    for col, g in zip('ABCDEFGHIJKL', (16, 6, 50, 12, 10, 38, 12, 11, 11, 10, 12, 10)):
        wd.column_dimensions[col].width = g
    baslik(wd)
    # aktarim
    if aktarim:
        wa = wb.create_sheet('Aktarım', 0)
        wa.append(['Sonuç', 'Stok kodu', 'Ürün', 'Yüklenen görsel', 'Yöntem', 'Not', 'Başka alan değişti mi', 'ikas sayfası'])
        for a in aktarim:
            wa.append([AKTAR_TR.get(a['sonuc'], a['sonuc']), a['sku'], a['ad'], a['yuklenen'], a['yontem'], '; '.join(a['not']),
                       ', '.join(a['fark']) if a['fark'] else 'hayır', ONYUZ + '/' + (a.get('slug') or '')])
        for col, g in zip('ABCDEFGH', (16, 16, 50, 10, 12, 70, 20, 40)):
            wa.column_dimensions[col].width = g
        baslik(wa)
    # ozet
    ozet = wb.create_sheet('Özet')
    say = {}
    for s in sonuclar:
        say[s['durum']] = say.get(s['durum'], 0) + 1
    ozet.append(['Durum', 'Ürün sayısı'])
    for k, v in sorted(say.items(), key=lambda kv: sira.get(kv[0], 9)):
        ozet.append([DURUM_TR.get(k, k), v])
    ozet.append([]); ozet.append(['Açıklamasında Ticimax görseli olan ürün', sum(1 for s in sonuclar if s.get('aciklama_tici'))])
    ozet.append(['Varyant görselleri farklı (elle)', sum(1 for s in sonuclar if s.get('varyant_farkli') and s['durum'] == 'DUZELT')])
    if aktarim:
        ozet.append([])
        asay = {}
        for a in aktarim:
            asay[a['sonuc']] = asay.get(a['sonuc'], 0) + 1
        for k, v in asay.items():
            ozet.append(['Aktarım: ' + AKTAR_TR.get(k, k), v])
    ozet.append([]); ozet.append(['Keskinlik dağılımı (eşleşen görseller)', ''])
    for k in ('<%30', '%30-55', '%55-80', '%80-100', '>%100'):
        ozet.append([k, hist['keskinlik'].get(k, 0)])
    ozet.append([]); ozet.append(['Benzerlik dağılımı', ''])
    for k in ('<%60', '%60-80', '%80-90', '%90-97', '>%97'):
        ozet.append([k, hist['benzerlik'].get(k, 0)])
    ozet.column_dimensions['A'].width = 42
    wb.save(os.path.join(CIKTI, 'gorsel-rapor.xlsx'))
    # HTML: duzeltilecekler yan yana
    satir = []
    for s in [x for x in sonuclar if x['durum'] == 'DUZELT'][:1500]:
        hucre = []
        for e in s['esler'][:4]:
            t = s['tici'][e['tici']]
            tu = 'https://static.ticimax.cloud/cdn-cgi/image/width=360,quality=90/' + t['url'].split('static.ticimax.cloud/', 1)[-1] if 'static.ticimax.cloud/' in t['url'] else t['url']
            iu = ikas_url(s['ikas'][e['ikas']]['imageId'], 540) if e['ikas'] is not None else ''
            etk = 'YOK' if e['ikas'] is None else f'keskinlik %{round(e["keskinlik"] * 100)} · benzerlik %{round(e["ssim"] * 100)} · renk farkı {e["renk"]}'
            hucre.append(f'<div class="c"><div class="p"><figure><img loading="lazy" src="{htmlmod.escape(tu)}"><figcaption>Ticimax {t.get("en", "?")}×{t.get("boy", "?")}</figcaption></figure>'
                         f'<figure>{"<img loading=lazy src=" + chr(34) + htmlmod.escape(iu) + chr(34) + ">" if iu else "<div class=yok>ikas&#39;ta yok</div>"}<figcaption>ikas · {etk}</figcaption></figure></div></div>')
        satir.append(f'<section><h2>{htmlmod.escape(s["ad"])} <small>{htmlmod.escape(s["sku"])}</small></h2><p>{htmlmod.escape("; ".join(s["neden"]))}</p>'
                     f'<p><a href="{htmlmod.escape(s.get("tici_sayfa") or "")}" target="_blank">Ticimax sayfası</a> · <a href="{ONYUZ}/{s["slug"]}" target="_blank">ikas sayfası</a></p><div class="g">{"".join(hucre)}</div></section>')
    with open(os.path.join(CIKTI, 'gorsel-rapor.html'), 'w', encoding='utf-8') as f:
        f.write('<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Görsel kalite raporu</title><style>'
                'body{font-family:system-ui,sans-serif;margin:0;background:#f5f6f8;color:#031c37}header{background:#031c37;color:#fff;padding:18px 24px}section{background:#fff;margin:16px;padding:16px;border-radius:12px;border:1px solid #e5e7eb}'
                'h2{font-size:17px;margin:0 0 4px}h2 small{color:#5b6474;font-weight:400}p{margin:4px 0;font-size:14px}a{color:#b84400}.g{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px}'
                '.c{border:1px solid #e5e7eb;border-radius:10px;padding:8px}.p{display:flex;gap:8px}figure{margin:0;width:220px}img{width:220px;height:220px;object-fit:contain;background:#fafafa;border-radius:6px}'
                '.yok{width:220px;height:220px;display:flex;align-items:center;justify-content:center;background:#fff1e8;color:#8f3500;border-radius:6px}figcaption{font-size:12px;color:#5b6474;margin-top:4px}'
                '</style></head><body><header><b>Görsel kalite raporu</b> · düzeltilmesi gereken ürünler: ' + str(len(satir)) + '</header>' + ''.join(satir) + '</body></html>')
    return say


# ------------------------------------------------------------------ ana
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--mod', default='rapor', choices=['kesif', 'rapor', 'rapor-ve-yedek', 'aktar-deneme', 'aktar', 'geri-al', 'buyut-deneme'])
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sku', default='')
    ap.add_argument('--is', dest='isci', type=int, default=int(os.environ.get('ISCI', '10')))
    a = ap.parse_args(argv)
    ikas = Ikas(os.environ['IKAS_MAGAZA'], os.environ['IKAS_CLIENT_ID'], os.environ['IKAS_CLIENT_SECRET'])
    ham = [p for p in ikas_urunleri(ikas) if not p.get('deleted')]
    urunler = [urun_ozeti(p) for p in ham]
    if a.sku.strip():
        istek = set(x.strip() for x in a.sku.split(',') if x.strip())
        urunler = [u for u in urunler if u['sku'] in istek]
    log(f'{len(urunler)} ürün')
    os.makedirs(CIKTI, exist_ok=True)

    if a.mod == 'geri-al':
        if not a.sku.strip():
            sys.exit('geri-al için stok kodu (sku) yazın')
        akt = Aktarim(ikas)
        sonuc = [akt.geri_al(u) for u in urunler]
        for r in sonuc:
            log(r['sku'], r['sonuc'], '; '.join(r['not']))
        rapor_yaz([], None, sonuc)
        return sonuc

    harita = TiciHarita(tici_sitemap())
    for u in urunler:
        u['tici_sayfa'], u['sayfa_esleme'] = harita.bul(u['slug'], u['ad'])
    log(f'Ticimax sitemap: {harita.adet} adres; eşleşen ürün: {sum(1 for u in urunler if u["tici_sayfa"])}/{len(urunler)}')

    if a.mod == 'buyut-deneme':
        if not a.sku.strip():
            sys.exit('buyut-deneme için stok kodu (sku) yazın')
        b = buyut_deneme(urunler[:10], CIKTI)
        log('BÜYÜTME:', json.dumps(b, ensure_ascii=False))
        return b
    k = None
    if a.mod == 'kesif':
        k = kesif(ikas, urunler, harita=harita)
        with open(os.path.join(CIKTI, 'kesif.json'), 'w', encoding='utf-8') as f:
            json.dump(k, f, ensure_ascii=False, indent=1)
        log(json.dumps(k, ensure_ascii=False, indent=1)[:8000])
        urunler = urunler[:30]
    if a.limit:
        urunler = urunler[:a.limit]
    yedek = Yedek(YEDEK_DIR) if a.mod == 'rapor-ve-yedek' else None
    aktar = a.mod in ('aktar', 'aktar-deneme')
    akt = Aktarim(ikas) if aktar else None
    sonuclar, aktarim, t0 = [], [], time.time()

    def isle(u):
        try:
            s = urun_isle(u, yedek, sakla=aktar)
        except Exception as e:
            return {'sku': u['sku'], 'ad': u['ad'], 'slug': u['slug'], 'id': u['id'], 'varyantlar': u['varyantlar'], 'ikas_sayi': len(u['ikas']),
                    'tici': [], 'ikas': [], 'esler': [], 'durum': 'HATA', 'neden': [str(e)[:200]], 'tici_sayfa': u.get('tici_sayfa') or '',
                    'sayfa_esleme': u.get('sayfa_esleme', ''), 'aciklama_tici': u.get('aciklama_tici', [])}, None
        ar = akt.urun(s) if aktar and s['durum'] == 'DUZELT' else None
        s.pop('_tici_im', None); s.pop('_tici_bayt', None)
        return s, ar

    if a.mod == 'aktar-deneme':
        hedef = 3 if not a.sku.strip() else len(urunler)
        for u in urunler:
            s, ar = isle(u)
            sonuclar.append(s)
            if ar:
                aktarim.append(ar)
                log('AKTAR', ar['sku'], ar['sonuc'], ar['yontem'], '; '.join(ar['not']), '| önce', ar['once'], '| sonra', ar['sonra'])
            if akt.dur or sum(1 for x in aktarim if x['sonuc'] in ('AKTARILDI', 'KISMEN', 'HATA', 'DURDURULDU')) >= hedef:
                break
    else:
        with ThreadPoolExecutor(max_workers=min(a.isci, 5) if aktar else a.isci) as ex:
            for n, (s, ar) in enumerate(ex.map(isle, urunler), 1):
                sonuclar.append(s)
                if ar:
                    aktarim.append(ar)
                if n % 100 == 0 or n == len(urunler):
                    log(f'{n}/{len(urunler)} ürün · {round(time.time() - t0)} sn' + (f' · aktarılan {sum(1 for x in aktarim if x["sonuc"] == "AKTARILDI")}' if aktar else ''))
    if yedek:
        yedek.kapat()
    say = rapor_yaz(sonuclar, k, aktarim if aktar else None)
    log('ÖZET:', json.dumps({DURUM_TR.get(x, x): v for x, v in say.items()}, ensure_ascii=False))
    if aktar:
        asay = {}
        for x in aktarim:
            asay[x['sonuc']] = asay.get(x['sonuc'], 0) + 1
        log('AKTARIM:', json.dumps({AKTAR_TR.get(x, x): v for x, v in asay.items()}, ensure_ascii=False))
        if akt.dur:
            log('DURDURULDU:', akt.dur)
            sys.exit(2)
    return sonuclar, aktarim


if __name__ == '__main__':
    main()
