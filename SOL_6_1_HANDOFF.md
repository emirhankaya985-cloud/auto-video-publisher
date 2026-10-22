# GPT‑6.1 Sol — Bağımsız Devralma ve Üretim Denetimi

> **Yeni ve daha güncel operasyonel devir:** [SOL_6_1_ONE_SHOT.md](SOL_6_1_ONE_SHOT.md). Önce onu oku; bu belge arka plan mimari açıklamasıdır. Sonraki 20 Ekim Actions runner blokajı ve Film Part 6 kurtarma taslağı yeni belgede kanıtlarıyla yer alır.

**Depo:** `emirhankaya-AFK/auto-video-publisher` (**private**)  
**Tarih:** 20 Ekim 2026, Türkiye saati  
**Devir hazırlanırken gözlenen master:** `a90c5ef66b450308232c6a824cbd71d385cf7121`  
**Önemli:** Bu SHA bir anlık fotoğraftır. Çalışmaya başlamadan önce güncel `master`, açık PR'lar ve Actions durumunu yeniden oku; bu dosyayı değişmez gerçek sanma.

## 1. Görevin ve sahiplik sınırı

Projeyi sıfırdan yazmak değil, **mevcut gerçek yayın sistemini bozmadan** daha güvenilir hale getirmek. Kullanıcı tekrar eden arızaları ve gereksiz PR yığınını istemiyor; aynı hata her gün insan müdahalesi gerektirmemeli. Hız önemli, ancak **yalnızca doğrulanmış işlere 'bitti' de**.

Başka bir ajan/Codex **Film Mağarası, sosyal medya yayın cron'u ve Cloudflare dış watchdog** üzerinde çalışıyor olabilir. İlk adımda açık PR/branch/SHA karşılaştırması yap, aynı dosyalara eşzamanlı yazma. Özellikle `scheduled_multi_publisher.py`, `cloud_omnichannel_publisher.py`, `.github/workflows/omnichannel_schedule.yml`, `scheduler_watchdog/**` ve Film claim durumlarına dokunmadan önce sahipliği netleştir. Çakışma varsa bağımsız alanlarda ilerle.

**Bu devir değişikliği sadece dokümandır.** Yeni yayını, test bildirimini, secret rotasyonunu veya deploy'u kendiliğinden tetiklememelidir.

## 2. Master'daki mevcut bileşenler — doğrulanmış kod var, canlı sonuç ayrı

| Alan | Master'da kod | Henüz ayrı doğrulanması gereken |
| --- | --- | --- |
| Zamanlı çoklu yayın | Drive claim/intent, güvenli yeniden deneme ve batch sınırlamaları | Yeni master'da planlı gerçek yayın ID'leri, doğru part sırası, çift paylaşım yokluğu |
| NTFY | Doğru JSON endpoint, server ACK, telefon özeti, hata uyarısı | Son gerçek `daily_stats` çalışması, mesaj alındısı ve Android telefon teslimatı |
| Günlük metrik arşivi | JSONL/CSV, eksik veri için N/A, geçici API hatasında önceki sağlam kayıtları koruma | Gerçek kaynak kapsaması, yanlış hesap eşleştirme ve Drive'a yeni tam snapshot |
| Rapor zamanlaması | 23:59 TRT normal rapor; yaklaşık 07:10 TRT önceki gecenin GitHub watchdog'u | GitHub schedule çalışıp çalışmadı; iki schedule'ın da atlanması halinde dış bağımsız alarm yok |
| Meta bağlantıları | Sayfa tokenlarını global token dışında ayrı kontrol eden salt-okunur tanılama | Önceden görülen 401 / OAuth 190 / subcode 463 hatasının güncel durumu, hesap bazlı izinler |
| Google Sheets | Yazmadan önce şema/anahtar kontrolü, eksik veri durumunda yazma engeli, idempotent upsert | `ANALYTICS_SHEET_ID` ve `ANALYTICS_SHEETS_CREDENTIALS_JSON` ile canlı bağlantı/yazım |
| Threads | Taslak entegrasyonlar; hesap bazlı opt-in tasarımı | Güncel kimlik ve yetki, gerekli secret'lar, medya hostu ve gerçek yayın doğrulaması |
| Film | Upload-only ve claim uzlaştırma test mekanizmaları | Instagram `media_publish` ve iki Facebook sayfası için gerçek gönderi ID'si |

**Kod/test kanıtı ile canlı API kanıtını kesinlikle karıştırma.** Eski bir yüklemenin `FINISHED` olması yayın yapıldığı anlamına gelmez. Server HTTP 200 veya ACK, Android cihaz teslimatı değildir. Günlük izlenmenin `0` olması ile `N/A` olması birbirinden farklıdır.

## 3. 20 Ekim 2026 itibarıyla açık PR'lar

Açık PR'ların sayısını ilk çalışmada **yeniden sorgula**; bu satırlar devir anındaki anlık görüntüdür.

| PR | Durum (devir anında) | Değişiklik | Önemli sınır |
| --- | --- | --- | --- |
| [#54](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/54) | Açık, draft değil | Cloudflare dış cron watchdog | Deploy edilmedi; kullanıcıya ait Cloudflare token/Worker secret ihtiyacı olabilir. Codex sahip olabilir. |
| [#46](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/46) | Açık, **draft**, merge çatışması riski | NTFY V3 metrikleri + Threads yardımcı dosyaları | Eski `stats_reporter.py` / `ntfy_notifications.py` değişikliklerini güncel master üzerine körlemesine taşıma. |
| [#45](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/45) | Açık, **draft** | 6 hesap için opt-in Threads | #46 ile `threads_accounts.py` ve yayın workflow'unda örtüşebilir. Yetkiler olmadan aktivasyon yok. |
| [#18](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/18) | Açık, draft değil, çatışma riski | Türkçe mizah hesaplarında içerik inceleme/gate | İçerik güvenliğini düşüren bir merge/yeniden açma yapılmamalı. Gerçek kullanıcı onayı ayrı. |

**PR hijyeni:** Eski/duplicate işleri tek tek ve kanıtla değerlendir. İlgili çalışmanın bir devamı varsa yeni numara üretmek yerine aynı PR'ı güncelle. Kullanıcının istemediği eski PR'ları, claim kayıtlarını veya inceleme öncesi güvenlik korumalarını körlemesine kapatma/silme. İlgisiz kapsamları tek dev PR'da birleştirme.

## 4. Sol'un ilk çalışma turu — yazmadan önce

1. `AGENTS.md` talimatlarını oku: **kullanıcı açık izin vermeden grafik tarayıcı/Playwright/Selenium kullanma**. API, terminal, kaynak kodu ve Actions logları öncelikli.
2. `master` SHA, açık PR head/base, branch farkları ve son Actions sonuçlarını topla. Özellikle `workflow_dispatch` ile `schedule` olayını ayır.
3. Gizli anahtarsız çalışan testleri taze checkout'ta çalıştır. Referans komut: `python -m unittest discover -p 'test*.py'`. Ek olarak `.github/workflows/daily_laugh_schedule_ci.yml` içindeki **fonksiyon tarzı testleri**, NTFY ve Sheets CI'larını çalıştır/incele.
4. Şüpheli alanları 3 sınıfa ayır: **a) kod hatası**, **b) secret/API yetkisi**, **c) canlı kanıt yokluğu**. Bunları tek 'çalışmıyor' başlığı altında ezme.
5. Her sorun için kanıtlanan **son sağlıklı commit**, hatalı run/job, güvenli yeniden üretim, düzeltme, regresyon testi ve geri alma yolu yaz. Secret ve özel konu isimlerini göstermeden yalnızca durum/kod paylaş.
6. Önce başkasının dokunmadığı kritik veri güvenliği sorunlarını düzelt. Codex kapsamındaki cron/Film işlerini, kullanıcıya gereksiz çatışma çıkarmadan inceleme notu ile işaretle.

## 5. İnceleme öncelikleri ve 'bitti' koşulları

### P0 — Mükerrer veya yanlış canlı gönderi olmaması

- Drive `done/intent/failure/claim` durumlarını ve uzak platform sonuçlarını eşleştir; belirsiz `media_publish` sonrası otomatik tekrar olmasın.
- Film Facebook 1/2 kimlikleri ve Instagram part sırası, ToonZone bölüm/part sırası, Daily Laugh Lab günlük 8 hedefinin **gerçek etkin/pasif ayarlarını** doğrula.
- Ana cron ve yedek cron aynı slotu tetiklerse çift yayın olmamalı.
- **Kabul:** Test + platformun gerçek post ID'si + aynı slotun tekrar çalıştırılmasında yeni ID üretmeme kanıtı. Canlı deneme veya geçmiş claim silme için açık kullanıcı izni iste.

### P1 — Her gece doğru NTFY raporu

- `daily_stats.yml` (20:59 UTC = 23:59 TRT) ve `daily_report_watch.yml` (04:10 UTC = 07:10 TRT) ayrı izlenmeli. GitHub cron gecikebilir veya çalışmayabilir.
- Her hesap için tüm zamanlar görüntülenmesi ve o gün gelen görüntülenme ayrı olmalı. Platform kapsamı eksikse `N/A/Kısmi`; YouTube eksik `viewCount` hata sayılmalı.
- Gece yarısı sonrasına sarkan planlı çalışma yanlış gün olarak kaydedilmemeli; `measured_at` gerçek zaman olmalı.
- Drive arşiv indirme başarısızsa eski geçmiş silinmemeli; aynı günkü başarılı ölçüm geçici hatayla ezilmemeli.
- NTFY sunucu ACK'si doğru konu/id ile eşleşmeli; 4 KB üzerine çıkan özet gizlice dosya eki gibi algılanmamalı.
- **Kabul:** Başarılı gerçek `schedule` run ve sunucu alındısı; Android cihaz alımı ayrı kullanıcı doğrulaması. Yoksa **'telefon teslimi doğrulanmadı'** de.

### P1 — Token/API sağlık raporu

- Global Meta token hatasının **en son gerçek** durumunu salt-okunur workflow/API ile kontrol et. Daha önce görülen HTTP 401 / OAuth 190 / 463 sonucunu yeni master'a veya tüm sayfa tokenlarına otomatik yayma.
- Meta uygulama kimliği, sayfa ID'si, Instagram profesyonel hesap ID'si ve scopes birbirinden ayrı denetlensin.
- Doğrudan token alma/yenileme, Cloudflare deploy veya sosyal hesaba giriş gerekiyorsa **yalnızca kullanıcı tarafında yapılması zorunlu adımı** göster; secret'ı mesaja, Actions logs'a veya markdown'a isteme.

### P2 — Threads ve Sheets (kullanıcının ertelediği bağlantılar)

- Kod/test boşluklarını düzeltmek serbest; Threads yayını, Google Sheet canlı yazımı ve yetki genişletmesi kullanıcı onayı olmadan başlatılmamalı.
- Threads için #45/#46 çatışmalarını bağımsız gözden geçir; haklı sebeple tek entegrasyon yolunu belirle.
- Google Sheets kurulumu için [ANALYTICS_SHEETS_SETUP.md](ANALYTICS_SHEETS_SETUP.md) belgesindeki secret/var/Sheets API yetkileri tamamlanmadan 'canlı' deme.
- Veri alınamadığında kısmi değerleri `0` sayma; başka platformların metrik tanımlarını aynı tekil izleyici metriği gibi toplama.

## 6. Test ve dağıtım emniyeti

```bash
python -m pip install --require-hashes -r requirements.txt
python -m unittest discover -p 'test*.py'
```

Yalnızca bunlarla yetinme; mevcut repo CI dosyalarındaki ekstra test komutlarını da kullan. `pytest` özel testlerini ilgili test dosyasına göre çalıştır. Mock testleri **gerçek HTTP POST** yapmamalı. CI başarıları sadece aynı SHA üzerinde geçerlidir.

Aşağıdaki eylemleri **otomatik yapma**: gerçek sosyal medya yayını, Drive claim/intent temizleme, üretim geçmişini sıfırlama, kullanıcı verisi taşıma, secret rotasyonu, Google Sheets `--write`, dış watchdog deploy, korumalı mizah kanallarını yeniden açma.

Güvenli kod değişikliklerini kendi branch'inde yap, test kanıtını kontrol et, Codex'in PR'larını ezme. Master'a merge edilecekse kapsamı, testleri, üretim yan etkisini ve rollback'i doğrula. Riskli işlerde kullanıcıdan açık onay olmadan canlı dış sistem değişikliği yapma.

## 7. İstenen çıktı formatı — kısa, ölçülebilir ve kanıtlı

Türkçe konuş; gereksiz soru veya onlarca PR listesi üretme. Her turda:

- **✅ Gerçekten tamamlandı:** Dosya/SHA, geçen test ve bağlantı (varsa).
- **🟡 Kod hazır, canlı kanıt eksik:** Test geçmiş fakat üretim gözlenmemiş.
- **🔴 Çalışmayı engelleyen şey:** Son gerçek hata ve kaynağı.
- **🔑 Kullanıcıdan zorunlu tek işlem:** Sadece hesap yetkisi / erişim gerçekten gerekiyorsa.
- **⏭ Sonraki bağımsız iş:** Codex'le çakışmadan nereye ilerleniyor?

**En önemli ilke:** Projeyi '100/100' veya 'her şey tamam' diye etiketlemek için GitHub CI, geçerli platform post ID'leri, API/secret durumu, mobil teslimat ve fail-safe davranış ayrı ayrı kanıtlanmış olmalı. Kanıt yoksa 'doğrulanmadı' yaz.
