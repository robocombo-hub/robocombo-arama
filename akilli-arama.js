/* [akilli-arama] v2 — Robocombo akilli arama
 * - Yazim hatasi, Turkce karakter, bitisik model kodu, es anlamli kelime (kelime motoru, tarayicida)
 * - Anlam arama: yapay zeka vektorleri (bge-m3, Cloudflare Worker) ile "niyet" eslestirme
 * - Yazarken acilan sonuc kutusu (% eslesme), "Bunu mu demek istediniz", son/populer aramalar
 * - /pages/arama?q=... sonuc sayfasi: filtre, siralama, "daha fazla"
 * - Ekranda gorunen urunlerin fiyat/stok bilgisi Worker (/canli) uzerinden ikas'tan ANLIK dogrulanir
 * Ayarlar: window.RC_ARAMA = { veri, worker, sayfa, stil, populer }
 */
(function(){
  var V='[akilli-arama] v2.5';
  if(window.__rcAra && window.__rcAra.dur) window.__rcAra.dur();
  var AYAR=Object.assign({
    veri:'',                       // https://<kullanici>.github.io/robocombo-arama
    worker:'',                     // https://robocombo-arama.<hesap>.workers.dev
    sayfa:'/pages/arama',
    stil:'liste',                  // 'liste' | 'izgara' (acilir kutu gorunumu)
    populer:['Arduino Uno','Raspberry Pi 5','ESP32','Servo motor','Lipo pil','Sensör seti','Robot kiti','Jumper kablo'],
    whatsapp:'https://wa.me/905525507626'
  }, window.RC_ARAMA||{});
  AYAR.veri=String(AYAR.veri||'').replace(/\/$/,''); AYAR.worker=String(AYAR.worker||'').replace(/\/$/,'');

  /* =============================== MOTOR =============================== */
  var TR={'ç':'c','ğ':'g','ı':'i','ö':'o','ş':'s','ü':'u','â':'a','î':'i','û':'u'};
  function fold(s){
    return String(s==null?'':s).toLocaleLowerCase('tr').replace(/[çğıöşüâîû]/g,function(c){return TR[c];})
      .normalize('NFD').replace(/[̀-ͯ]/g,'');
  }
  function kompakt(s){ return fold(s).replace(/[^a-z0-9]/g,''); }
  var DUR={ve:1,ile:1,icin:1,bir:1,en:1,de:1,da:1,mi:1,ne:1,the:1,for:1,and:1,adet:1,lazim:1,gerek:1,gerekli:1,
           istiyorum:1,ariyorum:1,bana:1,cok:1,iyi:1,uygun:1,nasil:1,hangi:1,olan:1,yapmak:1,yapimi:1,urun:1,urunu:1};
  function tokenlar(s,durKullan){
    return fold(s).split(/[^a-z0-9]+/).filter(function(t){ return t && !(durKullan && DUR[t]); });
  }
  var ES={
    ardiuno:['arduino'], ardunio:['arduino'], arduno:['arduino'], arudino:['arduino'],
    pil:['batarya','lipo','pili'], batarya:['pil','lipo'], aku:['pil','batarya'],
    mesafe:['ultrasonik','hcsr04','lidar','vl53l0x','tof'], ultrasonik:['mesafe','hcsr04'],
    sicaklik:['dht11','dht22','ds18b20','lm35','termal','isi'], isi:['sicaklik','termal'],
    nem:['dht11','dht22','nemi'], toprak:['nem','soil'],
    wifi:['esp8266','esp32','nodemcu'], kablosuz:['wifi','bluetooth','rf','nrf24l01'],
    bluetooth:['hc05','hc06','ble'], rfid:['rc522','pn532','nfc','mifare'], nfc:['rfid','pn532'],
    ekran:['lcd','oled','display','tft'], lcd:['ekran','display'], oled:['ekran','display'], display:['ekran','lcd'],
    role:['relay','roleli'], relay:['role'], step:['stepper','nema'], stepper:['step'], nema:['step'],
    kamera:['camera','cam'], camera:['kamera','cam'], cam:['kamera','camera'],
    gps:['neo6m','konum'], jiroskop:['gyro','mpu6050','ivmeolcer'], gyro:['jiroskop','mpu6050','ivmeolcer'],
    ivme:['ivmeolcer','mpu6050','adxl345'], breadboard:['breadbord'], breadbord:['breadboard'],
    jumper:['kablo'], kablo:['jumper'], havya:['lehim','lehimleme'], lehim:['havya','lehimleme'],
    pervane:['prop','propeller','pervaneleri'], prop:['pervane'], propeller:['pervane'],
    sarj:['charger'], charger:['sarj'], adaptor:['adapter','adaptoru'], adapter:['adaptor'],
    dron:['drone'], drone:['dron'], kumanda:['verici','transmitter','radiolink','flysky'],
    robot:['robotik'], kit:['set','seti','kiti'], set:['kit','seti','kiti'], seti:['kit','set','kiti'],
    klon:['ch340','uyumlu'], orijinal:['original','orjinal'], orjinal:['orijinal','original'],
    motor:['motoru','motorlar'], surucu:['driver','l298n','drv8825','a4988','esc'], driver:['surucu'],
    buzzer:['buzer'], hoparlor:['speaker'], potansiyometre:['pot','trimpot'], direnc:['resistor','ohm'],
    kondansator:['kapasitor','capacitor'], kizilotesi:['ir','infrared'], ir:['kizilotesi'], ldr:['isik'],
    rasberry:['raspberry'], raspbery:['raspberry'], raspberi:['raspberry'],
    esp:['esp8266','esp32','nodemcu'], nodemcu:['esp8266'], mikrobit:['microbit'], microbit:['mikrobit']
  };

  /* ---- Urun turu ("drone motoru" arayana once MOTORLAR, sonra motor surucusu/pervane gibi yan urunler) ----
     Turkcede urunun ne oldugunu isim tamlamasinin SON kelimesi soyler: "Drone Motor Surucusu" bir surucudur,
     "Drone Motoru" bir motordur. Tur kelimeleri magazanin kendi kategori adlarindan (Drone Motorlari,
     Piller, Sensorler...) ve asagidaki genel listeden cikarilir. */
  var TUR_GENEL=('motor surucu sensor pil batarya aku kablo kamera ekran display lcd oled tft pervane kumanda alici verici anten '+
    'role modul kart kit set shield direnc entegre diyot bobin kondansator transistor mosfet led buzzer filament klemens rulman '+
    'somun vida pul multimetre osiloskop tornavida pense havya ucu header kaplin trafo plaket cihaz aparat tutucu braket koruyucu '+
    'kutu kasa kapak soket konnektor adaptor sase govde tekerlek kayis kasnak disli lamba buton anahtar regulator jumper '+
    'breadboard breadbord lehim sogutucu fan kiskac pompa istasyon sehpa matkap mengene tabla nozzle extruder hotend levha bant '+
    'kelepce sigorta gozluk kilif stand yuva programlayici kontrolcu denetleyici alet').split(' ');
  var TUR_ZAYIF={modul:1,kart:1,board:1,set:1,kit:1,paket:1,parca:1};          /* "Kamera Modulu" -> tur: kamera */
  var TUR_ES={pil:['batarya','lipo','aku'], surucu:['driver','esc'], ekran:['lcd','oled','display','tft'], kamera:['camera','cam'],
    kit:['set'], role:['relay'], pervane:['prop','propeller'], adaptor:['adapter'], direnc:['resistor'], kondansator:['kapasitor','capacitor'],
    kumanda:['verici','transmitter'], sarj:['charger'], robot:['robotik'], alet:['cihaz'], kablo:['jumper']};   /* ayni tur sayilan kelimeler */
  var TUR_DEGIL=Object.create(null);
  function kok(t){                                  /* kaba Turkce govde: motoru/motorlari -> motor, pervanesi -> pervane */
    if(t.length<4 || /\d/.test(t)) return t;
    var r=t.replace(/(lari|leri|lar|ler)$/,''); if(r!==t && r.length>=3) return r;
    if(t.length>=5){ r=t.replace(/(si|su)$/,''); if(r!==t && r.length>=3) return r; }
    if(/[^aeiou][iu]$/.test(t)) return t.slice(0,-1);
    return t;
  }
  'urun diger hazir elektronik tabanli yardimci yeni cok satan model renk mat seffaf'.split(' ').forEach(function(t){ TUR_DEGIL[t]=1; TUR_DEGIL[kok(t)]=1; });
  function kokEsit(a,b){
    if(a===b) return true;
    var k=a.length<b.length?a:b, u=a.length<b.length?b:a;
    return k.length>=3 && u.length-k.length<=1 && u.indexOf(k)===0;          /* surucu ~ suruc */
  }

  var M=(function(){
    var P=[], IDX=Object.create(null), VOC=Object.create(null), VLIST=[], KAT=[], VEK=null, K=0, hazir=false, ONB=Object.create(null);
    var TUR=Object.create(null), SYN=Object.create(null), ALT=Object.create(null), KU=Object.create(null), UYUM=Object.create(null);   /* ALT.motor = {drone:[kategoriler], servo:[...]} */
    /* iki alt tur uyumlu mu: "Fircasiz Motorlar"in %93'u "Drone Motorlari"nda da -> uyumlu; servo motorlarin cogu degil -> uyumsuz */
    function uyumlu(h, q, on){
      var key=h+'|'+q+'|'+on; if(key in UYUM) return UYUM[key];
      var A=altAl(h), a=new Set(), b=new Set(), ort=0;
      (A[on]||[]).forEach(function(c){ (KU[c]||[]).forEach(function(i){ a.add(i); }); });
      (A[q]||[]).forEach(function(c){ (KU[c]||[]).forEach(function(i){ b.add(i); }); });
      a.forEach(function(i){ if(b.has(i)) ort++; });
      return (UYUM[key] = a.size>0 && ort/a.size>=0.75);
    }
    function ekle(t,pi,w){ var m=VOC[t]; if(!m) m=VOC[t]=new Map(); if((m.get(pi)||0)<w) m.set(pi,w); }
    function turMu(s){ return !!(s && !TUR_DEGIL[s] && (TUR[s] || TUR[s+'u'] || TUR[s+'i'] || (s.length>=5 && TUR[s.slice(0,-1)]))); }
    function synAl(s){ return SYN[s] || (s.length>=5 && SYN[s.slice(0,-1)]) || SYN[s+'u'] || []; }
    function turEsit(a,b){
      if(kokEsit(a,b)) return true;
      return synAl(a).some(function(x){ return kokEsit(x,b); }) || synAl(b).some(function(x){ return kokEsit(a,x); });
    }
    /* bir ad parcasindan tur kelimesi: sondan geriye, zayif kelimeleri (modul, kart, set) atlayarak */
    function sondakiTur(tk, bas){
      for(var i=tk.length-1;i>=(bas||0);i--){
        if(/\d/.test(tk[i])) continue;
        var s=kok(tk[i]); if(turMu(s) && !TUR_ZAYIF[s]) return {s:s, on:(i>(bas||0) && !/\d/.test(tk[i-1]))?kok(tk[i-1]):''};
      }
      return null;
    }
    function altAl(h){ return ALT[h] || ALT[h+'u'] || ALT[h+'i'] || (h.length>=5 && ALT[h.slice(0,-1)]) || null; }
    function katBas(c){                              /* "Drone Motor Suruculeri (ESC)" -> surucu */
      var tk=tokenlar(c.replace(/\(.*?\)/g,' ')).filter(function(t){ return !/\d/.test(t); });
      if(!tk.length) return null;
      var s=kok(tk[tk.length-1]);
      if((TUR_ZAYIF[s] || s==='model' || s==='urun') && tk.length>=2) s=kok(tk[tk.length-2]);   /* Raspberry Pi Modelleri -> pi */
      return TUR_DEGIL[s]?null:s;
    }
    function urunTur(p){
      if(p.tur!==undefined) return p.tur;
      /* parantez ici atilir; " - " ile ayrilmis parcalara sirayla bakilir; "X icin Y" -> Y'nin turu */
      var parca=p.ad.replace(/\(.*?(\)|$)/g,' ').split(/\s[-–|]\s/), bt=tokenlar(p.marka), s=null;
      for(var i=0;i<parca.length && !s;i++){
        var tk=tokenlar(parca[i]), bas=0, ic=tk.lastIndexOf('icin');
        if(i===0) while(bas<bt.length && bas<tk.length-1 && tk[bas]===bt[bas]) bas++;   /* "T-Motor ..." markasindaki motor sayilmaz */
        if(ic>=0) bas=Math.max(bas,ic+1);
        s=sondakiTur(tk,bas);
      }
      if(s) return (p.tur={ad:true, t:[s.s], on:s.on});      /* on: turden hemen onceki kelime ("Servo" Motor) */
      var kt=[]; p.kat.split('|').forEach(function(c){ var h=c&&katBas(c); if(h && kt.indexOf(h)<0) kt.push(h); });
      return (p.tur={ad:false, t:kt});
    }
    function sorguTur(tk){                           /* aranan seyin turu: "drone motoru" -> motor; "arduino uno" -> arduino */
      var zayif=null;
      for(var i=tk.length-1;i>=0;i--){
        if(/\d/.test(tk[i])) continue;
        var s=kok(tk[i]); if(!turMu(s)) continue;
        if(TUR_ZAYIF[s]){ zayif=zayif||s; continue; }
        return s;
      }
      return null;                                   /* sadece "kart", "modul" gibi genel kelime: tur ayrimi yapma */
    }
    /* 2 = aranan turun kendisi, 1 = belirsiz, 0 = baska tur (yan urun) */
    function turSinifi(p,H){
      var u=urunTur(p);
      if(!u.t.length) return 1;
      if(u.t.some(function(h){ return turEsit(h,H); })) return 2;
      return u.ad?0:1;
    }
    function kur(dizin,vekBuf){
      var u=dizin.u||[]; P=[]; IDX=Object.create(null); VOC=Object.create(null); ONB=Object.create(null);
      for(var i=0;i<u.length;i++){
        var r=u[i];
        var p={i:i,ad:r[0],sku:String(r[1]),marka:r[2]||'',kat:r[3]||'',slug:r[4],img:r[5],fiyat:+r[6]||0,eski:+r[7]||0,stok:r[8]?1:0,satis:r[9]||0,id:r[10]||''};
        if(p.id) IDX[p.id]=p;
        p.fAd=fold(p.ad); p.kAd=kompakt(p.ad+' '+p.marka);
        p.boost=(1+0.2*Math.log10(1+p.satis))*(p.stok?1:0.55);
        P.push(p);
        tokenlar(p.ad).forEach(function(t,ti){ ekle(t,i,ti<3?3:2.2); var n=t.match(/\d{2,}/g); if(n&&n[0]!==t) n.forEach(function(x){ekle(x,i,1.5);}); });
        tokenlar(p.marka).forEach(function(t){ ekle(t,i,2); });
        tokenlar(p.kat.replace(/\|/g,' ')).forEach(function(t){ ekle(t,i,1.5); });
      }
      VLIST=Object.keys(VOC);
      /* tur sozlugu: cogul kategori adlarinin son kelimesi (Drone Motorlari -> motor) + genel liste + es anlamlilar */
      TUR=Object.create(null); SYN=Object.create(null); ALT=Object.create(null); KU=Object.create(null); UYUM=Object.create(null);
      P.forEach(function(p){ p.kat.split('|').forEach(function(c){ if(c) (KU[c]=KU[c]||[]).push(p.i); }); });
      TUR_GENEL.forEach(function(t){ TUR[kok(t)]=1; });
      var gorulen=Object.create(null);
      P.forEach(function(p){ p.kat.split('|').forEach(function(c){
        if(!c || gorulen[c]) return; gorulen[c]=1;
        var tk=tokenlar(c.replace(/\(.*?\)/g,' ')).filter(function(t){ return !/\d/.test(t); });
        if(!tk.length) return;
        var son=tk[tk.length-1]; if(!/(lar|ler|lari|leri)$/.test(son)) return;          /* cogul = urun turu */
        var s=kok(son); if(TUR_DEGIL[s]) return; TUR[s]=1;
        if(TUR_ZAYIF[s] && tk.length>=2){ var o=kok(tk[tk.length-2]); if(!TUR_DEGIL[o]) TUR[o]=1; }
        else if(tk.length>=2){ var m=kok(tk[tk.length-2]); if(!TUR_DEGIL[m]){ var A=(ALT[s]=ALT[s]||Object.create(null)); (A[m]=A[m]||[]).push(c); } }   /* Servo Motorlar -> motor'un alt turu: servo */
      }); });
      Object.keys(TUR_ES).forEach(function(k){
        var ks=kok(k);
        TUR_ES[k].forEach(function(v){ var vs=kok(v);
          (SYN[ks]=SYN[ks]||[]).push(vs); (SYN[vs]=SYN[vs]||[]).push(ks);
          if(TUR[ks] && !TUR[vs]) TUR[vs]=1; });
      });
      K=dizin.k||0; VEK=null;
      if(vekBuf && K && vekBuf.byteLength===P.length*K) VEK=new Int8Array(vekBuf);
      KAT=[]; var A=window.__rcKatAgaci;
      if(A){
        for(var ana in A.ana) KAT.push({ad:ana,slug:A.ana[ana].s,tk:tokenlar(ana,true)});
        for(var a2 in A.alt) A.alt[a2].forEach(function(x){ KAT.push({ad:x.a,slug:x.s,ust:a2,tk:tokenlar(x.a,true)}); });
      }
      hazir=true; return P.length;
    }
    function dl(a,b,max){
      var la=a.length, lb=b.length; if(Math.abs(la-lb)>max) return max+1;
      var d=[],i,j; for(i=0;i<=la;i++) d[i]=[i]; for(j=0;j<=lb;j++) d[0][j]=j;
      for(i=1;i<=la;i++){ var enk=99;
        for(j=1;j<=lb;j++){
          var c=a[i-1]===b[j-1]?0:1, v=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+c);
          if(i>1&&j>1&&a[i-1]===b[j-2]&&a[i-2]===b[j-1]) v=Math.min(v,d[i-2][j-2]+1);
          d[i][j]=v; if(v<enk) enk=v;
        }
        if(enk>max) return max+1;
      }
      return d[la][lb];
    }
    function benzer(a,v){
      if(v===a) return 1;
      if(a.length>=2 && v.indexOf(a)===0) return a.length>=3?0.85:0.6;
      if(v.length>=4 && a.indexOf(v)===0 && a.length-v.length<=4) return 0.8;
      if(a.length>=4 && !/^\d+$/.test(a)){
        var max=a.length>=7?2:1;
        if(dl(a,v,max)<=max) return 0.7;
        if(v.length>a.length && dl(a,v.slice(0,a.length),max)<=max) return 0.6;
      }
      return 0;
    }
    function benzerSiki(a,v){
      if(v===a) return 1;
      if(a.length>=5 && v.indexOf(a)===0) return 0.85;
      if(v.length>=4 && a.indexOf(v)===0 && a.length-v.length<=3) return 0.8;
      return 0;
    }
    function eslesen(a,siki){
      var key=(siki?'!':'')+a; if(ONB[key]) return ONB[key];
      var s=new Map();
      for(var k=0;k<VLIST.length;k++){
        var v=VLIST[k], b=siki?benzerSiki(a,v):benzer(a,v); if(!b) continue;
        VOC[v].forEach(function(w,pi){ var x=b*w; if((s.get(pi)||0)<x) s.set(pi,x); });
      }
      return (ONB[key]=s);
    }
    /* "Bunu mu demek istediniz": sozlukte karsiligi olmayan kelimeyi en yaygin benzer kelimeyle degistir */
    function duzelt(tk){
      var degisti=false;
      var yeni=tk.map(function(t){
        if(t.length<4 || /\d/.test(t)) return t;
        if(VOC[t]) return t;                                   /* magazada gecen kelime duzeltilmez (drone -> dron, kablo -> jumper olmasin) */
        if(ES[t] && ES[t].length===1 && VOC[ES[t][0]]){ degisti=true; return ES[t][0]; }
        for(var k=0;k<VLIST.length;k++){ if(benzer(t,VLIST[k])>=0.8) return t; }
        var enIyi=null, enSay=0, max=t.length>=7?2:1;
        for(var j=0;j<VLIST.length;j++){ var v=VLIST[j];
          if(Math.abs(v.length-t.length)>max) continue;
          if(dl(t,v,max)<=max && VOC[v].size>enSay){ enIyi=v; enSay=VOC[v].size; } }
        if(enIyi){ degisti=true; return enIyi; }
        return t;
      });
      return degisti?yeni:null;
    }
    function kelimeAra(tk,q){
      var fq=fold(q).trim(), kq=kompakt(q), puan=new Map(), kapsam=new Map();
      tk.forEach(function(t){
        var alt=[t].concat(ES[t]||[]), enIyi=new Map();
        alt.forEach(function(a,ix){ eslesen(a,ix>0).forEach(function(s,pi){ s=ix?s*0.85:s; if((enIyi.get(pi)||0)<s) enIyi.set(pi,s); }); });
        enIyi.forEach(function(s,pi){ puan.set(pi,(puan.get(pi)||0)+s); kapsam.set(pi,(kapsam.get(pi)||0)+1); });
      });
      var kod=new Set(), sku=new Set();
      if(kq.length>=3 && (/\d/.test(kq)||kq.length>=5)){
        for(var i=0;i<P.length;i++) if(P[i].kAd.indexOf(kq)>=0){ puan.set(i,(puan.get(i)||0)+4); kapsam.set(i,tk.length); kod.add(i); }
      }
      if(/^\d{4,}$/.test(kq)){
        for(var j=0;j<P.length;j++) if(P[j].sku.indexOf(kq)===0){ puan.set(j,(puan.get(j)||0)+20); kapsam.set(j,tk.length); kod.add(j); sku.add(j); }
      }
      /* model kodu: harf+rakam karisik bir kelime (mg996, hcsr04, sr04) -> ayri ust grup; "raspberry pi 5" gibi aramalar degil */
      var modelKod=tk.some(function(t){ return /[a-z]/.test(t) && /\d/.test(t); });
      var n=tk.length, esik=n, aday=[];
      kapsam.forEach(function(c,pi){ if(c>=esik) aday.push(pi); });
      if(aday.length<3 && n>=2){ esik=n-1; aday=[]; kapsam.forEach(function(c,pi){ if(c>=esik) aday.push(pi); }); }
      var sonuc=new Map();
      aday.forEach(function(pi){
        var p=P[pi], s=puan.get(pi), tam=kapsam.get(pi)>=n||kod.has(pi);
        if(p.fAd.indexOf(fq)>=0) s+=2; if(p.fAd.indexOf(fq)===0) s+=0.5;
        s+=(tam?1:0);
        sonuc.set(pi,{s:s,tam:tam,kod:sku.has(pi) || (kod.has(pi) && modelKod)});      /* ham alaka puani; kod: model/stok kodu birebir */
      });
      return sonuc;
    }
    function ara(q,e){
      var bos={liste:[],kelimeler:[],duzeltme:null,kategoriler:[],semantik:false};
      if(!hazir) return bos;
      var fq=fold(q).trim(); if(!fq) return bos;
      var tk=tokenlar(q,true); if(!tk.length) tk=tokenlar(q);
      if(!tk.length) return bos;
      var dz=duzelt(tk), kt=dz||tk, sorgu=dz?dz.join(' '):q;
      var kel=kelimeAra(kt,sorgu);
      if(dz && !kel.size){ kel=kelimeAra(tk,q); }
      var kMax=0, tamSay=0; kel.forEach(function(x){ if(x.s>kMax) kMax=x.s; if(x.tam) tamSay++; });
      var sem=null, semTop=0, semLo=0, aday=new Set(kel.keys());
      if(e && VEK){
        sem=new Float32Array(P.length);
        for(var i=0,o=0;i<P.length;i++,o+=K){ var s=0; for(var j=0;j<K;j++) s+=e[j]*VEK[o+j]; sem[i]=s/127; }
        var sirali=Array.from(sem.keys()).sort(function(a,b){ return sem[b]-sem[a]; });
        semTop=sem[sirali[0]]; var alt=sem[sirali[Math.min(59,sirali.length-1)]];
        semLo=Math.min(Math.max(alt, semTop-0.3), sem[sirali[Math.min(11,sirali.length-1)]]);   /* en az 12 anlam adayi */
        sirali.slice(0,60).forEach(function(pi){ if(sem[pi]>=semLo) aday.add(pi); });
      }
      /* Siralama (v2.5): once GRUP, grup icinde SATIS.
         Gruplar (A = aranan kelimelerin hepsi var):
           0  rakamli model/stok kodu birebir ("mg996", "hcsr04")
           1  aranan turun kendisi, adinda ya da tam o kategoride ("Drone Motorlari" kategorisindeki F30 dahil)
           2  aranan tur ama baglanti zayif (kelime sadece genis bir kategoride gecer)
           3  ayni turun baska alt turu ("drone motoru" ararken servo motor)
           4  turu belirsiz        5  baska tur, yan urun (motor surucusu, pervane)
           9  kelimelerin bir kismi / sadece anlamca yakin (kendi icinde alaka sirasi)
         Grup icinde: once stoktakiler, sonra ciro (satis adedi x fiyat) buyukten kucuge. Cok satan ama tukenmis urun
         grubun basina cikmaz; az satan urun baska gruba dusmez, kendi grubunda asagi iner. */
      /* tam eslesme varsa anlam aramasi sadece cok yakin urunleri ekler ("velox" gibi marka/model aramalari kirlenmesin) */
      var semEsik = (tamSay>=3 || (kt.length===1 && tamSay>=1)) ? 2 : (tamSay>=1 ? 0.6 : 0);   /* 2 = anlam-yalniz urun ekleme */
      var H=sorguTur(kt), HA=H?altAl(H):null;
      var qm=H?kt.filter(function(t){ return !/\d/.test(t) && !kokEsit(kok(t),H); }).map(kok):[];   /* "drone" motoru */
      var qHarf=kt.filter(function(t){ return !/\d/.test(t); }).map(function(t){ return [kok(t)].concat((ES[t]||[]).map(kok)); });
      var qRakam=kt.filter(function(t){ return /\d/.test(t); });
      function katTamMi(p){                                 /* aranan harfli kelimelerin hepsi TEK bir kategorinin adinda */
        if(!qHarf.length) return false;
        if(!qRakam.every(function(t){ return p.kAd.indexOf(t)>=0; })) return false;
        var kk=p.katK||(p.katK=p.kat.split('|').filter(Boolean).map(function(c){ return tokenlar(c.replace(/\(.*?\)/g,' ')).map(kok); }));
        return kk.some(function(ks){ return qHarf.every(function(al){ return al.some(function(q){ return ks.some(function(v){ return kokEsit(v,q); }); }); }); });
      }
      var BANT={0:[99,0],1:[95,4],2:[90,4],3:[84,4],4:[78,5],5:[70,7],9:[40,29]};   /* grup -> [taban, genislik] eslesme % */
      var liste=[];
      aday.forEach(function(pi){
        var p=P[pi], k=kel.get(pi), kN=k&&kMax?k.s/kMax:0, sN=0;
        if(sem) sN=Math.max(0,Math.min(1,(sem[pi]-semLo)/Math.max(1e-6,semTop-semLo)));
        if(!k && sN<semEsik) return;                         /* kelime eslesmesi yoksa sadece guclu anlam yakinligi */
        var tam=!!(k&&k.tam), alaka, sinif=H?turSinifi(p,H):-1, g, f=0;
        alaka = tam ? (sem?0.8*kN+0.2*sN:kN) : (sem?(k?0.55*kN+0.45*sN:0.8*sN):kN*0.8);
        /* aranan kelimelerin hepsi urunun ADINDA geciyor mu */
        var adTam=tam && kt.every(function(t){ var k=kok(t); return k.length>=2 && (p.fAd.indexOf(k)>=0 || (ES[t]||[]).some(function(a){ return p.fAd.indexOf(kok(a))>=0; })); });
        /* ayni turun BASKA alt turu: "drone motoru" aranirken adi "... Servo Motor" olan (adinda drone gecmeyen) urun */
        var altCel=false;
        if(tam && sinif===2 && HA && qm.length && !adTam){ var on=urunTur(p).on;
          altCel=!!(on && HA[on] && qm.some(function(q){ return HA[q]; })
            && !qm.some(function(m){ return kokEsit(m,on) || p.fAd.indexOf(m)>=0; })
            && !qm.some(function(q){ return HA[q] && uyumlu(H,q,on); })
            /* adinda uyumlu bir alt tur de geciyorsa ("Firçasiz DC Motor") eleme */
            && !(p.adK||(p.adK=tokenlar(p.ad).map(kok))).some(function(m){ return HA[m] && qm.some(function(q){ return HA[q] && uyumlu(H,q,m); }); })); }
        if(!tam){ g=9; f=alaka*(1+0.05*Math.log10(1+p.satis))*(p.stok?1:0.8)*(sinif===2?1.15:sinif===0?0.85:1); }
        else if(k.kod) g=0;
        else if(H){
          if(sinif===2) g = altCel ? 3 : (adTam||katTamMi(p)) ? 1 : 2;
          else g = sinif===1 ? 4 : 5;
        }
        else g = (adTam||katTamMi(p)) ? 1 : 2;
        var B=BANT[g];
        liste.push({p:p, g:g, f:f, al:alaka, eslesme:Math.min(99,B[0]+Math.round(B[1]*alaka))});
      });
      liste.sort(function(a,b){
        if(a.g!==b.g) return a.g-b.g;
        if(a.g===9) return b.f-a.f;
        return (b.p.stok-a.p.stok) || (b.p.satis*b.p.fiyat - a.p.satis*a.p.fiyat) || (b.al-a.al);
      });
      /* yuzde asagi dogru hic artmasin: ustteki urunun yuzdesi alttakinden dusuk gorunmesin */
      for(var y=1;y<liste.length;y++) if(liste[y].eslesme>liste[y-1].eslesme) liste[y].eslesme=liste[y-1].eslesme;
      var kat=[];
      if(KAT.length && liste.length){
        var say=Object.create(null);
        liste.slice(0,60).forEach(function(x){ x.p.kat.split('|').forEach(function(c){ if(c){ var f=fold(c); say[f]=(say[f]||0)+1; } }); });
        KAT.forEach(function(k){
          var adEs=kt.every(function(t){ var al=[t].concat(ES[t]||[]); return k.tk.some(function(v){ return al.some(function(a,ix){ return (ix?benzerSiki(a,v):benzer(a,v))>=0.8; }); }); });
          var c=say[fold(k.ad)]||0;
          if(c>=1 && (adEs || c>=Math.max(3,0.3*Math.min(60,liste.length)))) kat.push({ad:k.ad,slug:k.slug,s:c+(adEs?100:0)});
        });
        kat.sort(function(a,b){ return b.s-a.s; });
      }
      return {liste:liste, kelimeler:kt, duzeltme:dz?dz.join(' '):null, kategoriler:kat.slice(0,3), semantik:!!sem};
    }
    function cokSatan(n){
      /* ciroya gore (adet x fiyat): 0,50 TL'lik direncler yerine asil satis yapan urunler */
      return P.filter(function(p){ return p.stok && p.fiyat>0; }).sort(function(a,b){ return b.satis*b.fiyat-a.satis*a.fiyat; }).slice(0,n);
    }
    return {kur:kur, ara:ara, cokSatan:cokSatan, _tur:function(){ return {TUR:TUR,SYN:SYN,ALT:ALT,KU:KU,uyumlu:uyumlu,altAl:altAl,urunTur:urunTur,sorguTur:sorguTur,P:P}; }, urun:function(id){ return IDX[id]; }, hazir:function(){return hazir;}, semHazir:function(){return !!VEK;}};
  })();

  /* =============================== VERI =============================== */
  var DIZIN=null, SURUM='', yukleme=null, EMB=new Map();
  function veriYukle(){
    if(yukleme) return yukleme;
    if(window.__rcAraDizin){                           /* test: dizin elle verildi */
      DIZIN=window.__rcAraDizin; SURUM=DIZIN.surum||'test';
      M.kur(DIZIN, window.__rcAraVektor||null);
      return (yukleme=Promise.resolve());
    }
    if(!AYAR.veri){                                     /* kurulum oncesi deneme: dizin.json dosyasini bilgisayardan sec */
      yukleme=new Promise(function(coz){
        var y=document.createElement('div');
        y.style.cssText='position:fixed;right:16px;bottom:16px;z-index:2147483001;background:#fff;border:2px solid #ff5f00;border-radius:10px;padding:14px 16px;box-shadow:0 8px 24px rgba(0,0,0,.18);font:14px/1.5 sans-serif;color:#031c37;max-width:320px';
        y.innerHTML='<b>Akıllı arama denemesi</b><br>dizin.json dosyasını seçin (anlam arama bu modda kapalı):<br><br><input type="file" accept=".json">';
        y.querySelector('input').addEventListener('change',function(ev){
          var f=ev.target.files[0]; if(!f) return; var rd=new FileReader();
          rd.onload=function(){ DIZIN=JSON.parse(rd.result); SURUM=DIZIN.surum||'yerel'; M.kur(DIZIN,null); y.remove(); console.log(V+': dizin hazır ('+DIZIN.u.length+' ürün, deneme modu)'); coz(); };
          rd.readAsText(f,'utf-8');
        });
        document.body.appendChild(y);
      });
      return yukleme;
    }
    var saat=Math.floor(Date.now()/36e5);
    yukleme=fetch(AYAR.veri+'/meta.json?h='+saat).then(function(r){ return r.json(); }).then(function(meta){
      SURUM=meta.surum;
      var d=fetch(AYAR.veri+'/dizin.json?v='+SURUM).then(function(r){ return r.json(); });
      var v=meta.k>0?fetch(AYAR.veri+'/vektor.bin?v='+SURUM).then(function(r){ return r.ok?r.arrayBuffer():null; }).catch(function(){ return null; }):Promise.resolve(null);
      return Promise.all([d,v]);
    }).then(function(x){
      DIZIN=x[0]; M.kur(DIZIN,x[1]);
      console.log(V+': dizin hazır ('+DIZIN.u.length+' ürün, anlam arama '+(M.semHazir()?'açık':'kapalı')+', sürüm '+SURUM+')');
    }).catch(function(err){ console.warn(V+': veri yüklenemedi',err); yukleme=null; throw err; });
    return yukleme;
  }
  function anlamVektoru(q){
    var key=fold(q).trim();
    if(!AYAR.worker || !M.semHazir() || key.length<2) return Promise.resolve(null);
    if(EMB.has(key)) return EMB.get(key);
    var ac=new AbortController(), zam=setTimeout(function(){ ac.abort(); },3000);
    var p=fetch(AYAR.worker+'/embed?v='+encodeURIComponent(SURUM)+'&q='+encodeURIComponent(q.trim()),{signal:ac.signal})
      .then(function(r){ if(r.status===409){ yukleme=null; veriYukle().catch(function(){}); } return r.ok?r.json():null; })
      .then(function(j){ return j&&j.e&&j.v===SURUM?Float32Array.from(j.e):null; })
      .catch(function(){ return null; })
      .then(function(x){ clearTimeout(zam); if(!x) EMB.delete(key); return x; });
    EMB.set(key,p); return p;
  }

  /* ======================= ANLIK FIYAT / STOK DOGRULAMA =======================
     Dizin saatte bir guncellenir. Ekranda gosterilen urunlerin fiyat ve stogu ayrica
     Worker uzerinden ikas'tan anlik sorulur; dogrulanana kadar fiyat soluk gosterilir. */
  var CANLI_T=new Map(), canliKapali=0, canliUcus=new Set();
  function canliTaze(p){
    if(!AYAR.worker || !p.id || Date.now()<canliKapali) return true;
    var t=CANLI_T.get(p.id); return !!t && Date.now()-t<90000;
  }
  function canliDogrula(urunler, yeniden){
    if(!AYAR.worker || Date.now()<canliKapali) return;
    var ids=[]; urunler.forEach(function(p){ if(p && p.id && !canliTaze(p) && ids.indexOf(p.id)<0) ids.push(p.id); });
    if(!ids.length) return;
    ids=ids.slice(0,50); var key=ids.join(',');
    if(canliUcus.has(key)) return; canliUcus.add(key);
    fetch(AYAR.worker+'/canli?ids='+key).then(function(r){ if(!r.ok) throw r.status; return r.json(); })
      .then(function(j){
        if(!j || !j.u) throw 'canli yok';                              /* Worker henuz eski surum: dizin verisiyle devam */
        var t=Date.now();
        ids.forEach(function(id){
          var p=M.urun(id), v=j.u[id]; if(!p) return;
          CANLI_T.set(id,t); if(v===undefined) return;
          if(v){ p.fiyat=v[0]; p.eski=v[1]; p.stok=v[2]; } else { p.stok=0; }   /* yayindan kalkmis: tukendi */
        });
      })
      .catch(function(){ canliKapali=Date.now()+60000; })           /* Worker/ikas cevap vermezse 1 dk dizin verisiyle devam */
      .then(function(){ canliUcus.delete(key); try{ yeniden(); }catch(e){} });
  }

  /* =============================== ORTAK =============================== */
  function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function fiyat(x){ return '₺ '+Number(x||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
  function gorsel(p,boy){ return p.img&&DIZIN?DIZIN.gorselKok+p.img+'/image_'+boy+'.webp':''; }
  function vurgula(ad,tk){
    return ad.split(/(\s+)/).map(function(w){
      var f=kompakt(w); if(!f) return esc(w);
      var ok=tk.some(function(t){ return f.indexOf(t)===0 || (t.length>=4 && f.length>=3 && t.indexOf(f)===0); });
      return ok?'<mark>'+esc(w)+'</mark>':esc(w);
    }).join('');
  }
  function yol(q){ return AYAR.sayfa+'?q='+encodeURIComponent(q.trim()); }
  function git(adres){
    kapat(); if(aktifInput) aktifInput.blur();
    try{ if(window.next&&window.next.router){ window.next.router.push(adres); return; } }catch(e){}
    location.href=adres;
  }
  var GKEY='rc-ara-gecmis';
  function gecmis(){ try{ return JSON.parse(localStorage.getItem(GKEY)||'[]'); }catch(e){ return []; } }
  function gecmiseEkle(q){
    q=q.trim(); if(q.length<2) return;
    try{ var g=gecmis().filter(function(x){ return fold(x)!==fold(q); }); g.unshift(q); localStorage.setItem(GKEY,JSON.stringify(g.slice(0,6))); }catch(e){}
  }
  function aramaSayfasinaGit(q){ q=(q||'').trim(); if(q.length<1) return; gecmiseEkle(q); git(yol(q)); }

  /* =============================== STIL =============================== */
  var st=document.createElement('style'); st.id='rc-ara-css';
  st.textContent=`
#rc-ara-kutu{position:fixed;z-index:2147483000;background:#fff;border:1px solid #e6e8ec;border-radius:12px;box-shadow:0 16px 40px rgba(3,28,55,.16);overflow:hidden;display:none;font-size:14px;color:#031c37;box-sizing:border-box}
#rc-ara-kutu.acik{display:block}
#rc-ara-kutu *,#rc-sonuc *{box-sizing:border-box}
.rc-ara-ic{max-height:min(72vh,600px);overflow-y:auto;overscroll-behavior:contain}
.rc-ara-bolum{padding:12px 14px 4px}
.rc-ara-baslik{font-size:12px;font-weight:600;color:#8a93a3;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px}
.rc-ara-cipler{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.rc-ara-cip{padding:5px 12px;border:1px solid #d9dde4;border-radius:999px;font-size:13px;color:#031c37;text-decoration:none;background:#fff;cursor:pointer;font-family:inherit;transition:.15s}
.rc-ara-cip:hover{border-color:#ff5f00;color:#ff5f00}
.rc-ara-cip.kat{background:#f4f6f9;border-color:transparent}
.rc-ara-duz{padding:10px 14px;background:#fff6f0;font-size:13px;color:#4a5565;border-bottom:1px solid #fde3d2}
.rc-ara-duz b{color:#031c37}
.rc-ara-urun{display:grid;grid-template-columns:56px 1fr auto;gap:12px;align-items:center;padding:9px 14px;text-decoration:none;color:#031c37;border-top:1px solid #f4f5f7;cursor:pointer}
.rc-ara-urun.sec,.rc-ara-urun:hover{background:#fff6f0}
.rc-ara-urun img,.rc-ara-bos-g{width:56px;height:56px;object-fit:contain;background:#f6f7f9;border-radius:6px;display:block}
.rc-ara-ad{font-size:14px;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rc-ara-ad mark,.rc-kart-ad mark{background:none;color:#ff5f00;font-weight:600}
.rc-ara-alt{font-size:12px;color:#8a93a3;margin-top:3px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.rc-es{display:inline-block;padding:1px 7px;border-radius:999px;background:#e8f7ee;color:#127a3a;font-size:11px;font-weight:600;white-space:nowrap}
.rc-tuk{display:inline-block;padding:1px 6px;border-radius:4px;background:#eef0f3;color:#5b6576;font-size:11px}
.rc-ara-fiyat{text-align:right;white-space:nowrap;font-weight:600;font-size:14px}
.rc-ara-fiyat s{display:block;font-weight:400;font-size:12px;color:#8a93a3}
.rc-bekle{opacity:.35;transition:opacity .2s}
.rc-ara-urun.tukendi img,.rc-ara-urun.tukendi .rc-ara-fiyat{opacity:.55}
.rc-ara-alt-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 14px;border-top:1px solid #ececef;background:#fafbfc}
.rc-ara-ai{font-size:12px;color:#8a93a3;display:flex;align-items:center;gap:6px}
.rc-ara-ai i{width:8px;height:8px;border-radius:50%;background:#c9d2de;display:inline-block}
.rc-ara-ai.acik i{background:#23a55a}
.rc-ara-ai.bekle i{background:#ff7b00;animation:rcNabiz 1s infinite}
@keyframes rcNabiz{50%{opacity:.3}}
.rc-ara-hepsi{border:none;background:none;color:#ff5f00;font:inherit;font-weight:600;font-size:14px;cursor:pointer;padding:0}
.rc-ara-yok{padding:20px 16px 12px;text-align:center;color:#4a5565;line-height:1.6}
.rc-ara-yok a{color:#ff5f00;font-weight:600;text-decoration:none}
#rc-ara-kutu.izgara .rc-ara-liste{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding:10px 14px}
#rc-ara-kutu.izgara .rc-ara-urun{grid-template-columns:1fr;border:1px solid #ececef;border-radius:10px;padding:10px;align-items:start}
#rc-ara-kutu.izgara .rc-ara-urun img,#rc-ara-kutu.izgara .rc-ara-bos-g{width:100%;height:auto;aspect-ratio:1}
#rc-ara-kutu.izgara .rc-ara-fiyat{text-align:left}
@media(max-width:767px){.rc-ara-urun{grid-template-columns:48px 1fr auto;gap:10px;padding:8px 12px}.rc-ara-urun img,.rc-ara-bos-g{width:48px;height:48px}.rc-ara-ad{font-size:13px}#rc-ara-kutu.izgara .rc-ara-liste{grid-template-columns:repeat(2,1fr)}}

body.rc-arama-sayfasi main > :not(#rc-sonuc){display:none!important}
#rc-sonuc{max-width:1400px;margin:0 auto;padding:24px 16px 48px;color:#031c37;font-size:14px}
.rc-s-ust{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:14px}
.rc-s-ust h1{font-size:26px;font-weight:500;margin:0;line-height:1.3}
.rc-s-ust h1 small{font-size:13px;color:#8a93a3;margin-left:8px;font-weight:400}
.rc-s-form{display:flex;gap:8px;flex:1 1 380px;max-width:520px}
.rc-s-form input{flex:1;height:44px;border:1px solid #d9dde4;border-radius:8px;padding:0 14px;font:inherit;font-size:15px;color:#031c37;outline:none}
.rc-s-form input:focus{border-color:#ff5f00}
.rc-s-form button{height:44px;padding:0 20px;border:none;border-radius:8px;background:#ff5f00;color:#fff;font:inherit;font-weight:600;cursor:pointer}
.rc-s-duz{margin:0 0 14px;padding:10px 14px;background:#fff6f0;border-left:3px solid #ff5f00;border-radius:4px;color:#4a5565}
.rc-s-duz a{color:#ff5f00;font-weight:600;cursor:pointer}
.rc-s-filtre{border:1px solid #e6e8ec;border-radius:10px;padding:4px 16px;margin-bottom:18px;background:#fff}
.rc-s-satir{display:flex;align-items:center;gap:14px;padding:10px 0}
.rc-s-satir+.rc-s-satir{border-top:1px dashed #e6e8ec}
.rc-s-etiket{flex:0 0 90px;font-weight:600;font-size:13px}
.rc-s-cipler{display:flex;flex-wrap:wrap;gap:6px;flex:1;min-width:0}
.rc-s-cip{padding:6px 12px;border:1px solid #d9dde4;border-radius:999px;background:#fff;color:#031c37;font:inherit;font-size:13px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.rc-s-cip em{font-style:normal;color:#8a93a3;font-size:12px}
.rc-s-cip.aktif{background:#031c37;border-color:#031c37;color:#fff}
.rc-s-cip.aktif em{color:#c9d2de}
.rc-s-sag{display:flex;align-items:center;gap:12px;margin-left:auto}
.rc-s-sag label{display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;white-space:nowrap}
.rc-s-sag select{height:36px;border:1px solid #d9dde4;border-radius:6px;padding:0 10px;font:inherit;font-size:13px;color:#031c37;background:#fff}
.rc-s-izgara{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:16px}
.rc-kart{display:flex;flex-direction:column;text-decoration:none;color:#031c37;background:#fff;border:1px solid #eef0f3;border-radius:10px;overflow:hidden;transition:box-shadow .2s,transform .2s}
.rc-kart:hover{box-shadow:0 8px 22px rgba(3,28,55,.1);transform:translateY(-2px)}
.rc-kart-g{position:relative;aspect-ratio:1;background:#f5f6f8;display:flex;align-items:center;justify-content:center}
.rc-kart-g img{width:100%;height:100%;object-fit:contain;padding:10px}
.rc-kart-g .rc-es{position:absolute;left:8px;top:8px}
.rc-kart-g .rc-kart-tuk{position:absolute;right:8px;top:8px;background:#000;color:#fff;font-size:12px;padding:3px 7px;border-radius:3px}
.rc-kart.tukendi img{opacity:.55}
.rc-kart-b{padding:10px 12px 14px;display:flex;flex-direction:column;gap:4px;flex:1}
.rc-kart-marka{font-weight:600;font-size:14px}
.rc-kart-ad{font-size:13px;color:#4a5565;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.7em}
.rc-kart-f{display:flex;align-items:center;gap:8px;margin-top:auto;padding-top:6px}
.rc-kart-ind{background:#000;color:#fff;font-size:12px;font-weight:600;padding:6px 7px;border-radius:3px}
.rc-kart-f s{display:block;color:#8a93a3;font-size:12px}
.rc-kart-f b{font-size:16px}
.rc-s-daha{display:block;margin:26px auto 0;padding:12px 28px;border:1px solid #031c37;border-radius:8px;background:#fff;color:#031c37;font:inherit;font-weight:600;cursor:pointer}
.rc-s-daha:hover{background:#031c37;color:#fff}
.rc-s-bos{padding:40px 16px;text-align:center;color:#4a5565;line-height:1.7}
.rc-s-bos a{color:#ff5f00;font-weight:600;text-decoration:none}
.rc-s-yuk{padding:60px 0;text-align:center;color:#8a93a3}
@media(max-width:1439px){.rc-s-izgara{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:991px){.rc-s-izgara{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:767px){
  #rc-sonuc{padding:14px 12px 36px}.rc-s-ust h1{font-size:20px}
  .rc-s-izgara{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .rc-s-filtre{padding:4px 10px}.rc-s-satir{flex-wrap:wrap;gap:8px}.rc-s-etiket{flex:0 0 100%}
  .rc-s-cipler{flex-wrap:nowrap;overflow-x:auto;padding-bottom:4px}.rc-s-cip{flex:0 0 auto;white-space:nowrap}
  .rc-s-sag{margin-left:0;width:100%;justify-content:space-between}
}`;
  document.head.appendChild(st);

  /* =============================== ACILIR KUTU =============================== */
  var kutu=null, aktifInput=null, secili=-1, zam=null, sonQ='', enterAtla=false, sonE={q:null,e:undefined};
  function aramaInputu(el){
    return el && el.tagName==='INPUT' && !!el.closest('header') && /^(text|search|)$/.test(el.type||'') && !el.closest('#rc-ara-kutu');
  }
  function kutuHazirla(){
    if(kutu&&kutu.isConnected) return kutu;
    kutu=document.createElement('div'); kutu.id='rc-ara-kutu';
    if(AYAR.stil==='izgara') kutu.classList.add('izgara');
    kutu.addEventListener('mousedown',function(e){ e.preventDefault(); });
    kutu.addEventListener('click',function(e){
      var a=e.target.closest('[data-yol]'); if(a){ e.preventDefault(); if(sonQ) gecmiseEkle(sonQ); git(a.getAttribute('data-yol')); return; }
      var c=e.target.closest('[data-q]'); if(c){ e.preventDefault(); var q=c.getAttribute('data-q'); if(aktifInput){ degerYaz(aktifInput,q); } ciz(q); return; }
      if(e.target.closest('.rc-ara-hepsi')){ e.preventDefault(); aramaSayfasinaGit(sonQ); }
    });
    document.body.appendChild(kutu); return kutu;
  }
  function degerYaz(inp,v){
    var set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
    set.call(inp,v); inp.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function konumla(){
    if(!kutu||!aktifInput||!kutu.classList.contains('acik')) return;
    var r=aktifInput.getBoundingClientRect(), vw=window.innerWidth;
    if(r.width===0){ kapat(); return; }
    if(vw<768){ kutu.style.left='8px'; kutu.style.width=(vw-16)+'px'; }
    else{ var w=Math.min(Math.max(r.width,560),AYAR.stil==='izgara'?860:760); w=Math.min(w,vw-16); kutu.style.left=Math.min(Math.max(8,r.left),vw-w-8)+'px'; kutu.style.width=w+'px'; }
    kutu.style.top=(r.bottom+6)+'px';
  }
  function kapat(){ if(kutu) kutu.classList.remove('acik'); secili=-1; }
  function ac(h){ kutuHazirla().innerHTML=h; kutu.classList.add('acik'); secili=-1; konumla(); }
  function urunSatiri(x,tk){
    var p=x.p||x, g=gorsel(p,180);
    return '<a class="rc-ara-urun'+(p.stok?'':' tukendi')+'" href="/'+esc(p.slug)+'" data-yol="/'+esc(p.slug)+'">'+
      (g?'<img src="'+g+'" alt="" loading="lazy">':'<div class="rc-ara-bos-g"></div>')+
      '<div><div class="rc-ara-ad">'+(tk?vurgula(p.ad,tk):esc(p.ad))+'</div><div class="rc-ara-alt">'+
      (x.eslesme?'<span class="rc-es">%'+x.eslesme+' eşleşme</span>':'')+esc(p.marka||'')+(p.stok?'':'<span class="rc-tuk">Tükendi</span>')+'</div></div>'+
      '<div class="rc-ara-fiyat'+(canliTaze(p)?'':' rc-bekle')+'">'+(p.eski?'<s>'+fiyat(p.eski)+'</s>':'')+fiyat(p.fiyat)+'</div></a>';
  }
  function aiDurum(s){ return '<span class="rc-ara-ai '+(s==='acik'?'acik':s==='bekle'?'bekle':'')+'"><i></i>'+(s==='acik'?'Akıllı arama':s==='bekle'?'Anlam aranıyor…':'Kelime araması')+'</span>'; }
  function bosCiz(){
    if(!M.hazir()){ return; }
    var g=gecmis(), h='<div class="rc-ara-ic">';
    if(g.length) h+='<div class="rc-ara-bolum"><div class="rc-ara-baslik">Son aramalarınız</div><div class="rc-ara-cipler">'+g.map(function(q){ return '<button class="rc-ara-cip" data-q="'+esc(q)+'">'+esc(q)+'</button>'; }).join('')+'</div></div>';
    h+='<div class="rc-ara-bolum"><div class="rc-ara-baslik">Popüler aramalar</div><div class="rc-ara-cipler">'+AYAR.populer.map(function(q){ return '<button class="rc-ara-cip" data-q="'+esc(q)+'">'+esc(q)+'</button>'; }).join('')+'</div></div>';
    var cs=M.cokSatan(4);
    h+='<div class="rc-ara-bolum" style="padding-bottom:0"><div class="rc-ara-baslik">Çok satanlar</div></div><div class="rc-ara-liste">'+cs.map(function(p){ return urunSatiri({p:p}); }).join('')+'</div></div>';
    ac(h);
    canliDogrula(cs, function(){ if(kutu&&kutu.classList.contains('acik')&&sonQ.length<2) bosCiz(); });
  }
  function ciz(q,sonucHazir){
    q=(q||'').trim(); sonQ=q;
    if(!M.hazir()) return;
    if(q.length<2){ bosCiz(); return; }
    var e=sonucHazir===undefined?null:sonucHazir;
    if(sonucHazir!==undefined) sonE={q:q,e:sonucHazir};
    var gosterilen=[];
    var s=M.ara(q,e), durum=s.semantik?'acik':(AYAR.worker&&M.semHazir()&&sonucHazir===undefined?'bekle':'kelime');
    var h='<div class="rc-ara-ic">';
    if(s.duzeltme) h+='<div class="rc-ara-duz">Şunun sonuçları gösteriliyor: <b>'+esc(s.duzeltme)+'</b></div>';
    if(s.kategoriler.length) h+='<div class="rc-ara-bolum"><div class="rc-ara-cipler" style="margin:0">'+s.kategoriler.map(function(k){ return '<a class="rc-ara-cip kat" href="/'+esc(k.slug)+'" data-yol="/'+esc(k.slug)+'">'+esc(k.ad)+'</a>'; }).join('')+'</div></div>';
    if(s.liste.length){
      var ilk=s.liste.slice(0,AYAR.stil==='izgara'?8:7); gosterilen=ilk.map(function(x){ return x.p; });
      h+='<div class="rc-ara-liste">'+ilk.map(function(x){ return urunSatiri(x,s.kelimeler); }).join('')+'</div>';
    }else{
      h+='<div class="rc-ara-yok">“'+esc(q)+'” için birebir sonuç bulamadık.<br>Aradığınızı <a href="'+AYAR.whatsapp+'" target="_blank" rel="noopener">WhatsApp</a> hattımızdan sorabilirsiniz.</div>';
      gosterilen=M.cokSatan(4);
      h+='<div class="rc-ara-bolum" style="padding-bottom:0"><div class="rc-ara-baslik">Çok satanlar</div></div><div class="rc-ara-liste">'+gosterilen.map(function(p){ return urunSatiri({p:p}); }).join('')+'</div>';
    }
    h+='</div><div class="rc-ara-alt-bar">'+aiDurum(durum)+(s.liste.length?'<button type="button" class="rc-ara-hepsi">Tüm sonuçlar ('+s.liste.length+') →</button>':'')+'</div>';
    ac(h);
    if(sonucHazir===undefined && AYAR.worker && M.semHazir()){
      anlamVektoru(q).then(function(e){ if(sonQ===q && kutu && kutu.classList.contains('acik')) ciz(q,e); });
    }
    canliDogrula(gosterilen, function(){ if(sonQ===q && kutu && kutu.classList.contains('acik')) ciz(q, sonE.q===q?sonE.e:undefined); });
  }
  function isaretle(yon){
    if(!kutu) return; var o=kutu.querySelectorAll('.rc-ara-urun'); if(!o.length) return;
    var n=o.length+1; secili=((secili+1+yon)%n+n)%n-1;
    o.forEach(function(x,i){ x.classList.toggle('sec',i===secili); });
    if(secili>=0) o[secili].scrollIntoView({block:'nearest'});
  }

  /* =============================== SONUC SAYFASI =============================== */
  var SAY={q:null,s:null,kat:new Set(),marka:new Set(),stok:false,sira:'onerilen',adet:40,kok:null};
  function sonucSayfasiMi(){ return location.pathname.replace(/\/$/,'')===AYAR.sayfa.replace(/\/$/,''); }
  function sayfaKok(){
    var main=document.querySelector('main'); if(!main) return null;
    if(!SAY.kok){ SAY.kok=document.createElement('div'); SAY.kok.id='rc-sonuc'; }
    if(SAY.kok.parentNode!==main) main.insertBefore(SAY.kok,main.firstChild);
    document.body.classList.add('rc-arama-sayfasi');
    return SAY.kok;
  }
  function sayfaCiz(){
    var kok=sayfaKok(); if(!kok) return;
    var q=new URLSearchParams(location.search).get('q')||'';
    document.title='“'+q+'” araması - Robocombo';
    if(!M.hazir()){
      kok.innerHTML=ustHtml(q,null)+'<div class="rc-s-yuk">Aranıyor…</div>';
      veriYukle().then(sayfaCiz,function(){ kok.innerHTML=ustHtml(q,null)+'<div class="rc-s-bos">Arama şu an kullanılamıyor.</div>'; });
      return;
    }
    if(SAY.q!==q){
      SAY.q=q; SAY.kat=new Set(); SAY.marka=new Set(); SAY.stok=false; SAY.sira='onerilen'; SAY.adet=40;
      SAY.s=M.ara(q,null); sayfaIcerik();
      if(AYAR.worker && M.semHazir() && q.trim().length>=2){
        anlamVektoru(q).then(function(e){ if(e && SAY.q===q){ SAY.s=M.ara(q,e); sayfaIcerik(); } });
      }
    }else sayfaIcerik();
  }
  function ustHtml(q,s){
    return '<div class="rc-s-ust"><h1>“'+esc(q)+'”'+(s?'<small>'+s.liste.length+' ürün</small>':'')+'</h1>'+
      '<form class="rc-s-form"><input type="search" value="'+esc(q)+'" placeholder="Ne aramıştınız?" aria-label="Ara"><button type="submit">Ara</button></form></div>';
  }
  function filtreli(){
    var l=SAY.s.liste.filter(function(x){
      if(SAY.stok && !x.p.stok) return false;
      if(SAY.marka.size && !SAY.marka.has(x.p.marka)) return false;
      if(SAY.kat.size && !x.p.kat.split('|').some(function(c){ return SAY.kat.has(c); })) return false;
      return true;
    });
    if(SAY.sira==='satis') l=l.slice().sort(function(a,b){ return b.p.satis-a.p.satis; });
    else if(SAY.sira==='artan') l=l.slice().sort(function(a,b){ return a.p.fiyat-b.p.fiyat; });
    else if(SAY.sira==='azalan') l=l.slice().sort(function(a,b){ return b.p.fiyat-a.p.fiyat; });
    return l;
  }
  function sayac(liste,al){
    var m=new Map(); liste.forEach(function(x){ al(x.p).forEach(function(v){ if(v) m.set(v,(m.get(v)||0)+1); }); });
    return Array.from(m.entries()).sort(function(a,b){ return b[1]-a[1]; }).slice(0,10);
  }
  function kart(x,tk){
    var p=x.p, g=gorsel(p,540), ind=p.eski?Math.round((p.eski-p.fiyat)/p.eski*100):0;
    return '<a class="rc-kart'+(p.stok?'':' tukendi')+'" href="/'+esc(p.slug)+'" data-yol="/'+esc(p.slug)+'">'+
      '<div class="rc-kart-g">'+(g?'<img src="'+g+'" alt="" loading="lazy">':'')+
        (x.eslesme?'<span class="rc-es">%'+x.eslesme+' eşleşme</span>':'')+(p.stok?'':'<span class="rc-kart-tuk">Tükendi</span>')+'</div>'+
      '<div class="rc-kart-b"><div class="rc-kart-marka">'+esc(p.marka||'')+'</div><div class="rc-kart-ad">'+vurgula(p.ad,tk)+'</div>'+
      '<div class="rc-kart-f'+(canliTaze(p)?'':' rc-bekle')+'">'+(ind>0?'<span class="rc-kart-ind">%'+ind+'</span>':'')+'<div>'+(p.eski?'<s>'+fiyat(p.eski)+'</s>':'')+'<b>'+fiyat(p.fiyat)+'</b></div></div></div></a>';
  }
  function sayfaIcerik(){
    var kok=sayfaKok(), s=SAY.s, q=SAY.q; if(!kok||!s) return;
    var h=ustHtml(q,s);
    if(s.duzeltme) h+='<div class="rc-s-duz">Şunun sonuçları gösteriliyor: <a data-q="'+esc(s.duzeltme)+'">'+esc(s.duzeltme)+'</a></div>';
    if(!s.liste.length){
      h+='<div class="rc-s-bos">“'+esc(q)+'” için sonuç bulamadık.<br>Farklı bir kelimeyle aramayı deneyin ya da aradığınızı <a href="'+AYAR.whatsapp+'" target="_blank" rel="noopener">WhatsApp</a> hattımızdan sorun.</div>';
      var cs=M.cokSatan(10);
      h+='<h2 style="font-size:18px;font-weight:600;margin:10px 0 14px">Çok satanlar</h2><div class="rc-s-izgara">'+cs.map(function(p){ return kart({p:p},[]); }).join('')+'</div>';
      kok.innerHTML=h;
      canliDogrula(cs, function(){ if(SAY.kok&&SAY.kok.isConnected&&SAY.q===q) sayfaIcerik(); });
      return;
    }
    var katlar=sayac(s.liste,function(p){ return p.kat.split('|'); }), markalar=sayac(s.liste,function(p){ return [p.marka]; });
    var cip=function(tur,d,c){ var akt=(tur==='kat'?SAY.kat:SAY.marka).has(d); return '<button type="button" class="rc-s-cip'+(akt?' aktif':'')+'" data-f="'+tur+'" data-d="'+esc(d)+'">'+esc(d)+'<em>'+c+'</em></button>'; };
    h+='<div class="rc-s-filtre">';
    if(katlar.length>1) h+='<div class="rc-s-satir"><div class="rc-s-etiket">Kategori</div><div class="rc-s-cipler">'+katlar.map(function(k){ return cip('kat',k[0],k[1]); }).join('')+'</div></div>';
    if(markalar.length>1) h+='<div class="rc-s-satir"><div class="rc-s-etiket">Marka</div><div class="rc-s-cipler">'+markalar.map(function(k){ return cip('marka',k[0],k[1]); }).join('')+'</div></div>';
    h+='<div class="rc-s-satir"><div class="rc-s-sag"><label><input type="checkbox" data-f="stok"'+(SAY.stok?' checked':'')+'> Sadece stoktakiler</label>'+
       '<select data-f="sira"><option value="onerilen">Önerilen</option><option value="satis">Çok satanlar</option><option value="artan">Fiyat: artan</option><option value="azalan">Fiyat: azalan</option></select></div></div></div>';
    var l=filtreli();
    h+=l.length?'<div class="rc-s-izgara">'+l.slice(0,SAY.adet).map(function(x){ return kart(x,s.kelimeler); }).join('')+'</div>':'<div class="rc-s-bos">Seçtiğiniz filtrelere uygun ürün yok.</div>';
    if(l.length>SAY.adet) h+='<button type="button" class="rc-s-daha">Daha fazla göster ('+(l.length-SAY.adet)+')</button>';
    kok.innerHTML=h;
    var sel=kok.querySelector('select[data-f="sira"]'); if(sel) sel.value=SAY.sira;
    canliDogrula(l.slice(0,SAY.adet).map(function(x){ return x.p; }), function(){ if(SAY.kok&&SAY.kok.isConnected&&SAY.q===q) sayfaIcerik(); });
  }
  function sayfaOlaylari(e){
    var kok=SAY.kok; if(!kok||!kok.contains(e.target)) return;
    var t=e.target;
    if(e.type==='submit'){ e.preventDefault(); var v=kok.querySelector('.rc-s-form input').value.trim(); if(v){ gecmiseEkle(v); sayfaAdres(v); } return; }
    if(e.type==='change'){
      if(t.matches('[data-f="stok"]')){ SAY.stok=t.checked; SAY.adet=40; sayfaIcerik(); }
      if(t.matches('[data-f="sira"]')){ SAY.sira=t.value; sayfaIcerik(); }
      return;
    }
    var c=t.closest('.rc-s-cip'); if(c){ var set=c.getAttribute('data-f')==='kat'?SAY.kat:SAY.marka, d=c.getAttribute('data-d'); set.has(d)?set.delete(d):set.add(d); SAY.adet=40; sayfaIcerik(); return; }
    if(t.closest('.rc-s-daha')){ SAY.adet+=40; sayfaIcerik(); return; }
    var dq=t.closest('[data-q]'); if(dq){ sayfaAdres(dq.getAttribute('data-q')); return; }
    var y=t.closest('[data-yol]'); if(y){ e.preventDefault(); git(y.getAttribute('data-yol')); }
  }
  function sayfaAdres(q){
    var adres=yol(q);
    try{ if(window.next&&window.next.router){ window.next.router.replace(adres,undefined,{shallow:true}); setTimeout(sayfaCiz,30); return; } }catch(e){}
    history.replaceState(history.state,'',adres); sayfaCiz();
  }

  /* =============================== OLAYLAR =============================== */
  var sonAdres='';
  function adresKontrol(){
    if(location.href===sonAdres) { if(sonucSayfasiMi()) sayfaKok(); return; }
    sonAdres=location.href;
    if(sonucSayfasiMi()) sayfaCiz();
    else { document.body.classList.remove('rc-arama-sayfasi'); if(SAY.kok&&SAY.kok.parentNode) SAY.kok.parentNode.removeChild(SAY.kok); SAY.q=null; }
  }
  var gozcu=new MutationObserver(function(){ clearTimeout(gozcu.z); gozcu.z=setTimeout(adresKontrol,60); });
  var olaylar=[
    [document,'focusin',function(e){ if(!aramaInputu(e.target)) return; aktifInput=e.target;
      veriYukle().then(function(){ if(document.activeElement===aktifInput) ciz(aktifInput.value); },function(){}); },true],
    [document,'input',function(e){ if(!aramaInputu(e.target)) return; aktifInput=e.target; clearTimeout(zam); var v=e.target.value;
      zam=setTimeout(function(){ veriYukle().then(function(){ ciz(v); },function(){}); },90); },true],
    [document,'keydown',function(e){
      if(enterAtla||!aramaInputu(e.target)) return;
      var acik=kutu&&kutu.classList.contains('acik');
      if(e.key==='ArrowDown'&&acik){ e.preventDefault(); isaretle(1); }
      else if(e.key==='ArrowUp'&&acik){ e.preventDefault(); isaretle(-1); }
      else if(e.key==='Escape'){ kapat(); }
      else if(e.key==='Enter'){
        e.preventDefault(); e.stopImmediatePropagation();
        var o=acik?kutu.querySelectorAll('.rc-ara-urun'):[];
        if(secili>=0&&o[secili]){ gecmiseEkle(e.target.value); git(o[secili].getAttribute('data-yol')); }
        else aramaSayfasinaGit(e.target.value);
      }
    },true],
    [document,'keypress',function(e){ if(e.key==='Enter'&&aramaInputu(e.target)){ e.preventDefault(); e.stopImmediatePropagation(); } },true],
    [document,'click',function(e){                       /* header'daki arama dugmesi */
      var t=e.target; if(!t.closest||t.closest('#rc-ara-kutu')) return;
      var h=t.closest('header'); if(!h||aramaInputu(t)) return;
      var alan=t.closest('[class*="search"]'); if(!alan) return;
      var inp=alan.querySelector('input')||(alan.parentElement&&alan.parentElement.querySelector('input'));
      if(!aramaInputu(inp)||!inp.value.trim()) return;
      e.preventDefault(); e.stopImmediatePropagation(); aramaSayfasinaGit(inp.value);
    },true],
    [document,'mousedown',function(e){ if(kutu&&!kutu.contains(e.target)&&!aramaInputu(e.target)) kapat(); },true],
    [document,'click',sayfaOlaylari,false],
    [document,'change',sayfaOlaylari,false],
    [document,'submit',sayfaOlaylari,true],
    [window,'resize',konumla,false],
    [window,'scroll',konumla,true]
  ];
  olaylar.forEach(function(o){ o[0].addEventListener(o[1],o[2],o[3]); });
  gozcu.observe(document.body,{childList:true,subtree:true});
  adresKontrol();

  window.__rcAra={motor:M, ayar:AYAR, ara:function(q){ return veriYukle().then(function(){ return anlamVektoru(q); }).then(function(e){ return M.ara(q,e); }); },
    dur:function(){
      olaylar.forEach(function(o){ o[0].removeEventListener(o[1],o[2],o[3]); }); gozcu.disconnect();
      if(kutu) kutu.remove(); if(SAY.kok) SAY.kok.remove(); document.body.classList.remove('rc-arama-sayfasi'); st.remove(); delete window.__rcAra;
    }};
  console.log(V+' yüklendi');
})();
