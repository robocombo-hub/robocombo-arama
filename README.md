# Robocombo Akıllı Arama

ikas mağazası için yapay zekâ destekli ürün araması. Kabile Akıllı Arama'nın yaptığının aynısını yapar, aylık ücreti yoktur:

- **Yazım hatalarını anlar:** "ardunio uno" yazılınca "Şunun sonuçları gösteriliyor: arduino uno" der.
- **Türkçe karakter ve ekleri tanır:** "sensörü", "sensoru" ve "sensör" aynı sonucu verir.
- **Bitişik model kodlarını bulur:** "hcsr04" HC-SR04'ü, "mg996" MG996R'yi, stok kodu da ürünü getirir.
- **Anlamı anlar:** "engelden kaçan robot için ne lazım" gibi cümleleri ürünlerle anlamına göre eşleştirir ve her sonuçta **% eşleşme** gösterir.
- **Hiçbir aramayı sonuçsuz bırakmaz:** Birebir sonuç yoksa en yakın ürünleri ve çok satanları gösterir.
- **Yazarken açılan kutu:** Son aramalar, popüler aramalar, kategori kısayolları, görsel ve fiyatlı ürünler.
- **Sonuç sayfası (`/pages/arama?q=`):** Kategori ve marka filtresi, "sadece stoktakiler", sıralama, "daha fazla göster".
- **Kendini günceller:** ikas'taki ürün, fiyat ve stoklar her gece otomatik alınır.

## Nasıl çalışır

```
 ikas Admin API ──(her gece 03:30)──► GitHub Actions: sync/sync.py
                                        │  ürünleri çeker, bge-m3 ile anlam vektörü çıkarır (Cloudflare Workers AI)
                                        ▼
                               GitHub Pages: dizin.json, vektor.bin, pca.bin, akilli-arama.js
                                        │
 Ziyaretçinin tarayıcısı ◄──────────────┘  kelime araması tarayıcıda, anında
        │
        └── aranan cümle ──► Cloudflare Worker (/embed) ──► anlam vektörü ──► tarayıcıda ürünlerle karşılaştırılır
```

| Parça | Nerede | Ücret |
|---|---|---|
| Gece senkronu | GitHub Actions (herkese açık depo) | Ücretsiz |
| Veri dosyaları + mağaza scripti | GitHub Pages | Ücretsiz |
| Anlam vektörü (sorgu başına bir kez, sonuçlar 1 gün önbellekte) | Cloudflare Worker + Workers AI | Ücretsiz kota (günlük 100.000 istek, 10.000 nöron) |

Worker ya da Workers AI bir sebeple yanıt vermezse arama, kelime araması olarak çalışmaya devam eder.

---

## Kurulum

Toplam 30–45 dakika sürer. Sıra önemli.

### 1. ikas: özel uygulama (API anahtarı)
1. ikas panelinde **Uygulamalar → Uygulamalarım** sayfasına gidin, **Daha Fazla → Özel Uygulama Oluştur**'a tıklayın.
2. Ad: `Akıllı Arama`. İzinlerden **ürünleri okuma** (Products – read) yeterli.
3. Oluşturulan **Client ID** ve **Client Secret** değerlerini bir kenara not edin.

### 2. Cloudflare: hesap ve API anahtarı
1. cloudflare.com'da ücretsiz hesap açın. robocombo.com zaten Cloudflare'deyse aynı hesabı kullanın.
2. **Account ID:** panelde **Workers & Pages** sayfasının sağ tarafında yazar. Kopyalayın.
3. **API anahtarı:** Sağ üstte profil → **My Profile → API Tokens → Create Token** yolunu izleyin, **Workers AI** şablonunu seçin, **Create** deyin. Çıkan anahtarı kopyalayın, bir daha gösterilmez.

### 3. GitHub: depo, gizli anahtarlar, Pages
1. github.com'da ücretsiz hesap açın.
2. **New repository** ile yeni depo oluşturun. Adı `robocombo-arama`, görünürlüğü **Public** olsun. Ücretsiz Pages için herkese açık olması gerekiyor. Anahtarlar kodda değil gizli ayarlarda durduğu için bu güvenli.
3. **Add file → Upload files** ile bu klasördeki her şeyi sürükleyip bırakın, `.github` klasörü dahil. Ardından **Commit changes** deyin.
4. **Settings → Pages → Build and deployment → Source: GitHub Actions** seçin.
5. **Settings → Secrets and variables → Actions → New repository secret** ile şu 5 değeri ekleyin:

| Ad | Değer |
|---|---|
| `IKAS_MAGAZA` | `robocombo` (panel adresinizdeki `robocombo.myikas.com` kısmı) |
| `IKAS_CLIENT_ID` | 1. adımdaki Client ID |
| `IKAS_CLIENT_SECRET` | 1. adımdaki Client Secret |
| `CF_ACCOUNT_ID` | 2. adımdaki Account ID |
| `CF_API_TOKEN` | 2. adımdaki API anahtarı |

6. **Actions → Arama dizinini güncelle → Run workflow** ile ilk çalıştırmayı başlatın. İlk sefer tüm ürünlerin vektörü çıkarıldığı için 5–10 dakika sürer, sonraki gecelerde sadece değişen ürünler işlenir.
7. Bittiğinde tarayıcıda `https://KULLANICI-ADINIZ.github.io/robocombo-arama/meta.json` adresini açın. `"semantik":true` ve ürün sayısı görünmeli.

### 4. Cloudflare Worker
1. **Workers & Pages → Create → Create Worker** yolunu izleyin, adı `robocombo-arama` olsun, **Deploy** deyin.
2. **Edit code** ile açılan editördeki her şeyi silin, `worker/worker.js` dosyasının içeriğini yapıştırıp **Deploy** deyin.
3. **Settings → Bindings → Add → Workers AI** ile bir bağlama ekleyin. Variable name tam olarak `AI` olmalı.
4. **Settings → Variables and Secrets → Add** ile bir değişken ekleyin: `VERI_URL` = `https://KULLANICI-ADINIZ.github.io/robocombo-arama`.
5. Worker adresini not edin: `https://robocombo-arama.HESAP-ADINIZ.workers.dev`. Tarayıcıda açınca `"durum":"çalışıyor"` yazmalı.

### 5. ikas: arama sonuç sayfası
Tema editöründe sayfa menüsünden **Yeni Sayfa Oluştur → Özel Sayfa** ile yeni bir sayfa açın. Adı **Arama**, adresi **arama** olsun, yani sayfa `/pages/arama` adresinde çıkmalı. İçine boş bir Zengin Metin Alanı koyup kaydedin. Script bu sayfanın içeriğini sonuçlarla dolduracak.

### 6. ikas: scripti ekleme
**Tema → Özel kod** bölümüne yeni bir script ekleyin. İçeriği `magaza/panel-yukleyici.html` dosyasından alın, iki adresi kendi adreslerinizle değiştirin. Canlı test adresinde sayfayı yenileyince Console'da şu satırlar görünmeli:
```
[akilli-arama] v2 yüklendi
[akilli-arama] v2: dizin hazır (3837 ürün, anlam arama açık, sürüm ...)
```

---

## Kullanım ve bakım

- **Günlük güncelleme otomatik:** Her gece 03:30'da çalışır. Hemen güncellemek isterseniz **Actions → Run workflow** deyin.
- **Popüler aramalar, görünüm, eş anlamlılar:** Hepsi `magaza/akilli-arama.js` dosyasında. GitHub'da dosyayı açıp kalem simgesiyle düzenleyin ve kaydedin, birkaç dakika içinde siteye yansır.
  - `populer:[...]` popüler arama listesi. Panel yükleyicisinde `window.RC_ARAMA.populer` ile de değiştirilebilir.
  - `stil:'izgara'` açılır kutuyu kart ızgarası olarak gösterir. Varsayılanı `'liste'`.
  - `var ES={...}` eş anlamlı kelimeler (örneğin `mesafe:['ultrasonik','hcsr04']`).
- **Satış sıralaması:** Şimdilik `sync/satis.json`'daki Ticimax satış verisi kullanılıyor (1 Nisan – 25 Eylül 2026).
- **Sorun giderme:**
  - Console'da `veri yüklenemedi` görünüyorsa 3.7'deki `meta.json` adresini kontrol edin.
  - "Kelime araması" yazıp anlam araması hiç açılmıyorsa Worker adresini ve `AI` bağlamasını kontrol edin.
  - Gece çalışması kırmızıysa Actions'taki kayda bakın. Eksik ya da hatalı gizli anahtar mesajı orada açıkça yazar.

## Dosyalar
```
.github/workflows/gece.yml   gece senkronu + GitHub Pages yayını
sync/sync.py                 ikas → dizin + anlam vektörleri (PCA 256 boyut, int8)
sync/satis.json              SKU başına satış adedi (sıralama için)
worker/worker.js             Cloudflare Worker: sorgu vektörü
magaza/akilli-arama.js       sitede çalışan arama (açılır kutu + sonuç sayfası)
magaza/panel-yukleyici.html  ikas paneline eklenecek kısa kod
test/                        sahte ikas/AI ile uçtan uca deneme araçları (geliştirme için)
```

Yerel deneme (ikas ve Cloudflare olmadan): `python sync/sync.py --excel ikas-urunler.xlsx`
