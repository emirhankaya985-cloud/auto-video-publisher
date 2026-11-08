# Sosyal medya — 2–8 Kasım 2026 merkezi olay ve sessiz bildirim kaydı

Bu belge sorunun **tespit edildiğini** belgeler; tek başına çözüldüğünü, hak onayını veya platformda yeni yayın oluştuğunu iddia etmez. Platformun gerçek gönderi ID'si ve doğru hesaptaki GET tarihi canlı kabuldür. GitHub yeşil CI tek başına yayın kanıtı değildir.

## Kullanıcı tercihi (8 Kasım)
- TikTok bu onarım ve bildirim kapsamı **dışında**. TikTok için otomatik POST veya onarım yapılmayacak.
- Kullanıcı **hata bildirimlerini görmek istemiyor**. GitHub incident JSON / errors JSONL, yayın ledger, CI ve yedekler korunacak; Telegram/ntfy'ye tekrarlayan hata / engel / eksik rapor alarmı **gitmeyecek**.
- Gerçek post ID ile doğrulanmış yeni gönderi bildirimleri, `/durum` isteğine yanıt ve günlük 23:59 TRT istatistik raporu korunacak. Hata sessizliği başarılı yayın uydurmak veya güvenlik kapılarını kaldırmak değildir.
- Canlı sonuç / gönderi ID'leri sahte doldurulmayacak; başka hesapların yayınları engellenmeyecek.

## Olay defteri ve çözüme kabul şartları

| Konu | Tespit / kaynak | Kanıtlı çözümün kabul ölçütü |
|---|---|---|
| ToonZone S01E04–S01E12 kapak, sıralama, izin ve 4 part | #135, #172, #174, #178–#180, #195; kısmi arşiv ve tekil Graph GET belirsizlikleri | Her part için birebir medya/kapak/izin, doğru sırada ayrı FB+IG post_id, uzak geçmiş; belirsiz/eski ID için otomatik repost yasak |
| Film Mağarası Bıçkın Part 8 / daha önce paylaşılan Part 3'e görsel benzerlik | #188, #190, #191, #194; 8 Kasım owner kaynak doğrulama | Part 8 doğru özgün MP4 SHA256, Part 3'ten ayrıştırma, FB sayfalarına ayrı gerçek ID; Part 8 doğrulanmadan Part 9'a geçilmez |
| Daily Laugh Lab bozuk/eksik MP4, visual duplicate | #159, #161, #163, run 42521169732 | Hatalı MP4 karantinada, başka özgün içerik sıradaki güvenli slotta; koruma kendi başına tüm job'ı kırmızı göstermesin |
| Meta geçmişinde belirsiz intent, mükerrer POST riski | #141, #143, #145–#146, #167 | Ledger `intent/uncertain` sonuçları tam ve uzaktan kontrolle uzlaşmadan tekrar POST yok |
| Diğer FB/IG slotları, yayın kotası ve state | #155, #162, #164, #165 | Gerçek günlük 7-hesap × uygun platform kotası + gerçek son ID, yanlış video tekrar yayını yok |
| Threads hesap/token 401/190, görünürlük | #138, #142, #147, #160, #166, #175 | Her yetkili hesapta read-only identity/permission GET ve ayrı post ID/metric kanıtı; yetkisiz token yazımı yok |
| YouTube 403 / OAuth kanal kimliği | #148, #153, #156–#158, #170, #184, #196; 8 Kasım run 42521169732 daily_laugh identity failure | Doğrulanmış kanal bazlı yetki ve gerçek upload acceptance; bağımsız YT hatası Meta'ya geçmesin |
| Drive credential, yedek ve kaynak doğrulaması | #173, #176, #177, #179, #183 ve 2 Kasım backup kabul dokümanı | Owner-only dosya, indirilen SHA256, izole restore, kayıpsız güncel yayın ledger; credential eksikse sahte success yok |
| Telegram/ntfy hata spamı, Threads buton ve istatistik | #132, #150–#151, #181–#182, owner sessiz modu PR | Hata push mesajı 0, `/durum` doğru gerçek bilgi, başarılı gönderi bildirimleri ve 23:59 raporu korunmuş |
| Meta hesaplar arası beğeni / 15 dakikalık sırayla kontrol | #186, #187, #189, #192, #193 | Doğrulanabilir yerel testler ve açık desteklenen API kapsamı; toplu sahte etkileşim/izin dışı POST yok |

### 8 Kasım gerçek teknik kanıt

- [Scheduled Meta yayın run 42521169732](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42521169732): 1 yeni doğrulanmış Instagram gönderisi (Tarladaki Fasulye `306.mp4`, ID `18138987529634112`). İş akışı `failure`; Daily Laugh `visual_duplicate_review` kaynaklı yerel durdurma; YT daily_laugh kimliği hazırlık hatası; ledger eski 7 uzaktan uzlaşma gerektiren kayıt, 6 kanıtlı yerel görsel tutma. Bir `visual_duplicate_review` Meta tarafından yapılmış başarısız POST değildir.
- [Main mock CI 42521547732](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42521547732) başarılı, ancak canlı Meta yayın sağlamlığının kanıtı değildir.
- Geçmiş backup doğrulaması: [publication-backup-acceptance-2026-11-02.md](publication-backup-acceptance-2026-11-02.md) sürüm anlık görüntüsünü doğrular; takip eden her günün otomatik yedek başarı garantisi değildir.

### Sessiz mod uygulanma yüzeyleri

- `public_link_schedule.yml`: `PUBLISH_QUIET_FAILURES=true`. `telegram_publish_report.py` hataları toplamdan ve ledger'dan silmez; yalnız onaylı yeni postlara bildirim hazırlar. Beklenen yerel görsel kopya koruması tüm run'ın genel hata sınıfına sayılmaz.
- `daily_stats.yml`: `QUIET_FAILURE_NOTIFICATIONS=true` ile başarısız rapor push alarmı sessiz.
- `daily_report_watch.yml`: eksik gün sonu raporu algılama ve workflow başarısızlık kanıtı devam eder, telefon alarmı sessiz.
- Kullanıcının istediği süreklilik için mevcut otomasyon nöbeti korunur; sohbet tarafındaki bildirimler de ayrı olarak sessizleştirilmelidir. Bu kod, GitHub'ın hesap seviyesindeki bildirim tercihlerini kontrol etmez.
- `link-error-journal` ve `link-incident-report` artifact'ları 90 gün tutulan teknik kayıt olabilir. Süresiz arşiv var denemez.

## Süregelen güvenlik politikası
1. GitHub'da `success` dışında `done + post_id + doğru uzak platform kimliği` zorunlu.
2. `uncertain`, `intent`, copyright/rights eksikliği, bozuk MP4 veya duplicate-source için kör tekrar ve başlık değiştirerek yeniden yükleme yok.
3. Bildirimler susturulurken gözlem kayıtları, test/CI başarısızlıkları ve bağımsız kanıtlar asla silinmeyecek.
4. Yeni bir hata geldiğinde bu tabloya tarih, run, kök neden, fix PR ve canlı kabul bağı yazılacak. Kanıtsız çözülmüş yazılmayacak.
