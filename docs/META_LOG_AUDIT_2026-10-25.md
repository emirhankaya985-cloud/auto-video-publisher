# Meta otomasyon log denetimi — 25 Ekim 2026

**Depo:** `emirhankaya985-cloud/auto-video-publisher`  
**Aktif canlı yol:** `.github/workflows/public_link_schedule.yml`  
**Denetlenen aralık:** GitHub Actions geçmişindeki 610 run kimliği/durum kaydı (23–25 Ekim çalışmalarını içerir).  
**Kapsam sınırı:** 610 koşumun meta verileri topluca tarandı; aktif yayıncının başarısız son koşumlarının temsilî job logları, başarılı yayın logları, kaynak kod, kurtarma defteri ve doğrulama testleri ayrıntılı olarak incelendi. 610 koşumun her job logunun satır satır incelendiği iddia edilmez.

## Genel tablo (denetim anı)

| Akış | İncelenen run | Success | Failure | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Aktif Public link Meta automation | 110 | 75 | 35 | 0 |
| Legacy 4-kanal yayıncı | 147 | 0 | 0 | 147 |
| Legacy backup yayıncı | 113 | 0 | 0 | 113 |
| 985 Migration CI | 134 | 116 | 17 | 0 |

Not: `skipped` eski yayıncıların kapalı kalması için beklenen, çift-post önleyici davranıştır. Tek başına arıza değildir. Aktif Meta run'larında `success` yeni video gönderildiğinin kanıtı değildir; gerçek `post_id` aranır.

## Kök nedenler ve kanıt

1. **Reels ikili medya aktarımı HTTP 400 / `ProcessingFailedError`.**
   Meta `rupload.facebook.com` üzerinden gönderilen dosyanın baytlarını alsa bile medya işlemesini reddedebiliyor. Başarısız örnekler:
   - [25 Ekim #40200170075](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40200170075): Daily Laugh `114.mp4` Facebook başarılı, Instagram binary HTTP 400.
   - [25 Ekim #40193720330](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40193720330): Tarladaki `124.mp4` Instagram HTTP 400; diğer hesaplarda 6 gerçek gönderi tamamlandı.
   - [24 Ekim #40107188749](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40107188749): Film `Yoksul_1986_Part_16.mp4` Instagram compact bitstream de HTTP 400; Facebook yayımlandı.
   - [24 Ekim #40082286094](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40082286094): Beyinsiz Penguen ve ToonZone Instagram binary 400.
   **Gözlem:** Bazı kaynaklar 1080×1920 H.264 High / 30 veya 60 fps + edit list ve `moov` sonda. `faststart` remux yerel kontrolden geçmesine rağmen Meta reddedebiliyor. Bazı 360×640/25fps compact dosyalar da reddedildi. Tek bir kesin Meta iç işleme sebebi kanıtlanamadı; videonun teknik parametreleri güçlü olası etkendir. 
   **Kod eylemi:** `tarladaki`, `penguen`, `daily_laugh` için salt yeniden paketlemeyle yetinmek yerine normalize H.264/30fps/AAC hazırlığı. `film` ve `toonzone` için kesin `media_publish` öncesi 400 kanıtı varsa uzak Meta geçmişi okunduktan sonra en fazla 1 zorunlu *farklı* bitstream kodlaması; ikinci başarısızlıkta dur.
2. **Sessiz, süresiz sıra kilidi.**
   - [25 Ekim #40218929042](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40218929042) başarılı iş akışında bile Film `Yoksul_1986_Part_16.mp4` ve ToonZone `S01E03_Caffeinated_Concert_Tickets_Part3.mp4` için `uncertain previous intent` raporlanırken hata bildirimi gitmemiş.
   - **Kök sebep:** Eski `prepublish HTTP400` durumları `uncertain` olarak bırakılıyordu; mevcut run'a ait olay oluşmadığından yeni hata günlüğü/bildirim bunu sessiz geçiyordu.
   - **Düzeltme:** Kanıtı tam olan yayın-öncesi 400 için `ready` ve bir kez alternatif encode; gerçekten sonuç belirsiz `media_publish` için durum korunur, yalnız ilk karşılaşmada Telegram/ntfy uyarısı gönderilir; sonraki yarım saatlik yoklamada tekrarlanan alarm yok.
3. **Drive `FileURLRetrievalError` (23 Ekim).** [#39992767030](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/39992767030), [#39906684586](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/39906684586). Paylaşım linki/Drive hız sınırlaması veya erişim sorunu; mevcut 3 denemeli dosya indirme/parçalı dosya temizliği korunuyor. Erişim hiçbir denemede açılmazsa yayın zorlanamaz.
4. **Testte saat/örnek veri varsayımı kaynaklı kırmızı CI.** [#40062876739](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40062876739) ve [#40073539771](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40073539771). Bunlar video yayın aşamasına ulaşmadan duran çalışmalardı; mock izolasyonu ve regresyon kontrolleri eklendi.
5. **ToonZone eksik 2. sezon kapakları.** Son kaynak denetiminde 159 videoya 48 doğru PNG, 111 eksik eşleşme vardı. Yanlış kapakla yayın yapmak yerine eksik part bekletilmeli.
6. **Bildirim / kanıt.** [25 Ekim gerçek yayın #40221619361](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40221619361) 5 yeni Facebook/Instagram gönderisi ve 5'er Telegram/ntfy sunucu ACK gösteriyor. Telefonun push gösterdiği bu logla ispatlanmaz.

## Güvenli kurtarma kabul kriteri

- Ağdan okuma/FFmpeg hazırlığı sınırla ve doğrula; **Meta `media_publish` POST belirsizse kör yeniden deneme yapma.**
- Her `HELD` hata olarak sınıflandırılmaz; ama işlem gereken eski `uncertain` durumu sessiz kalmamalı.
- Geçmiş `caption_hash` değişmişse eski belirsiz yayın kaydını otomatik onarma.
- Aynı başarısız Instagram bitstream'i yeniden yükleme; ikinci denemede zorlanmış farklı standard encode kullan.
- `link-error-journal`, `link-incident-report` ve `link-state-result` çıktılarını birlikte incele. Artifact saklama süresi 90 gündür.
- CI geçmesi = kod doğrulaması. **Gerçek canlı düzeltme kabulü** için yeni kodun çalıştığı scheduled Meta koşumu ve doğrulanmış `post_id` ayrıca gerekli.

## Değişen kod ve testler

- `public_link_runtime.py`: profil seçimi, state-only güvenli kurtarma, dedupe ve uyarı.
- `publisher_recovery.py`: prepublish kanıtı için bir kerelik Film/ToonZone alternatif profil.
- `instagram_media_compat.py`: önceki remux/direct sonucu döndürmeyen `force_transcode` seçeneği.
- `publisher_error_journal.py`: `previous_intent_hold` / `unreconciled_previous_intent` aşaması/sınıfı.
- `test_public_link_runtime.py`, `test_instagram_media_compat.py`, `test_publisher_recovery.py`: yeni senaryolar ve ikinci deneme güvenliği.

**Doğrulanan regresyon koşumu:** [#40222439413](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40222439413) — 466 Python / 57 fonksiyon / 15 JavaScript testi. Sonraki kod değişiklikleri varsa en güncel commit CI ayrıca kontrol edilmelidir.
