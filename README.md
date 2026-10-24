> **Aktif 985 üretimi:** Meta-only yayıncı `.github/workflows/public_link_schedule.yml` üzerinden çalışır. **Eski OAuth/YouTube yayıncısı kapalıdır; `AUTOMATION_ENABLED` değerini açma.** Daha önce yaşanan HTTP 400, Drive, ffmpeg, TXT, kapak ve durum kaydı hataları için [**Üretim Kurtarma Defteri**](docs/PRODUCTION_RECOVERY_RUNBOOK.md) zorunlu ilk okumadır. Token/OAuth eksiklerini kullanıcı ayrı sohbette yönetecek. Kurulum: [MIGRATION_985.md](MIGRATION_985.md).

# Auto Video Publisher

GitHub Actions tabanlı çok hesaplı sosyal medya video yayınlama ve performans raporlama sistemi. Bu depo **public** kaynak kodu deposudur; kimlik bilgileri yalnız GitHub Actions Secrets içinde tutulur; otomatik yayın, Google Drive üzerindeki içerik ve durum kayıtları, Meta/YouTube entegrasyonları, NTFY bildirimleri ve isteğe bağlı analitik entegrasyonları bulunur.

> **Yeni devralacak mühendis veya yapay zekâ ajanı:** Önce [SOL_6_1_ONE_SHOT.md](SOL_6_1_ONE_SHOT.md), ardından [SOL_6_1_HANDOFF.md](SOL_6_1_HANDOFF.md) ve [AGENTS.md](AGENTS.md) dosyalarını oku. Kodun testlerden geçmesi, canlı yayın veya telefon teslimatının kanıtlandığı anlamına gelmez.

## Ana bileşenler

| Alan | Kaynak | Sorumluluk |
| --- | --- | --- |
| Otomatik yayın | `scheduled_multi_publisher.py`, `.github/workflows/omnichannel_schedule.yml` | Zamanlama, Drive durum/claim kayıtları ve platform yönlendirmesi |
| Meta ve YouTube API | `cloud_omnichannel_publisher.py`, `meta_connection_audit.py` | Yetki, kimlik eşleştirme, medya hazırlama ve salt-okunur denetim |
| Gün sonu raporu | `stats_reporter.py`, `.github/workflows/daily_stats.yml` | Her hesabın günlük ve toplam izlenmesi; eksik veri için N/A |
| Telefon bildirimleri | `ntfy_notifications.py`, `ntfy_phone_report.py` | NTFY sunucu alındısı, 4 KB sınırı ve gizli konu güvenliği |
| Eksik rapor uyarısı | `.github/workflows/daily_report_watch.yml` | Bir önceki gecenin planlı raporunu ertesi sabah kontrol eder |
| Geçmiş arşivi | `analytics_archive.py`, `analytics_drive_store.py` | JSONL/CSV anlık ölçümler ve tekrar güvenli güncelleme |
| Sheets aktarımı | `analytics_sheets.py`, `.github/workflows/analytics_sheets_sync.yml` | İsteğe bağlı; yalnızca yetkilendirmeden sonra gerçek tabloya yazabilir |

Hesap aileleri: Tarladaki Fasulye, Beyinsiz Penguen, Gönle Düşen, Daily Laugh Lab, Film Mağarası/Filmmagrasi ve ToonZone. Platform erişimi, yayın sayısı ve aktif/pasif durumu hesaplar arasında farklıdır; bunları belleğe dayanarak değil güncel kod, yapılandırma ve API kanıtıyla doğrula.

## Güvenlik sınırları

- **Üretimde video veya test mesajı yayımlama, claim/intent silme, Drive içeriği değiştirme ya da yeni secret girme işlemlerini örtük izin sayma.** Önce salt-okunur denetim yap.
- Facebook/Instagram yayın sonucu belirsizse aynı partı tekrar gönderme; önce platform gönderi ID'si ve Drive durumunu uzlaştır.
- Şifre, token, OAuth JSON, gizli NTFY konusu, servis hesabı anahtarı veya özel hesap URL'sini loglara, belgelere ya da sohbetlere kopyalama.
- İçerik onayı/hesap duraklatma kurallarını atlama. Ayrı açık değişiklikler birlikte değerlendirilmeden master'a körlemesine alınmamalı.
- Başarısız veya eksik API ölçümünü `0` yerine `N/A` ya da `Kısmi` olarak bildir.
- Sunucudan NTFY mesaj alındısı almak, Android cihazın bildirimi aldığı anlamına gelmez.

## Başlangıç ve testsiz canlı müdahaleden kaçınma

Python 3.12 kullan. Kilitlenmiş bağımlılıklar mevcut:

```bash
python -m pip install --require-hashes -r requirements.txt
python -m unittest discover -p 'test*.py'
```

Depoda ayrıca parametresiz fonksiyonlardan oluşan testler var; sadece `unittest discover` çalıştırmak hepsini kapsamaz. Doğrulama için mevcut GitHub Actions testlerini de incele:

- [Yayın regresyon testleri](.github/workflows/daily_laugh_schedule_ci.yml)
- [NTFY bildirim/rapor testleri](.github/workflows/ntfy_delivery_ci.yml)
- [Sheets veri güvenliği testleri](.github/workflows/analytics_sheets_ci.yml)

**Testlerde üretim secret'ları olmamalı; yeni bir işte gerçek paylaşım veya gerçek bildirim gönderme.** Birleştirmeden önce ilgili PR'ın CI sonucunu ve master'daki en güncel SHA'yı kontrol et.

## İşletim belgeleri

- [**GPT‑6.1 Sol tek seferlik kurtarma görevi**](SOL_6_1_ONE_SHOT.md) — güncel GitHub Actions runner kanıtları, Film Part 6 güvenlik kilidi ve kod/üretim kabul şartları
- [GPT‑6.1 Sol devir ve denetim planı](SOL_6_1_HANDOFF.md) — devralma sırası, açık işler ve kabul ölçütleri
- [Gün sonu NTFY raporunun sınırlamaları](NTFY_DAILY_PHONE_REPORT.md)
- [Google Sheets kurulum ve veri güvenliği](ANALYTICS_SHEETS_SETUP.md)
- [Meta bağlantı salt-okunur denetimi](.github/workflows/meta_connection_audit.yml)
- [Açık GitHub değişiklikleri](https://github.com/emirhankaya-AFK/auto-video-publisher/pulls)

## Canlı doğrulama durumunu nasıl okumalı?

- **Kod uygulandı:** Değişiklik `master` dalında bulunuyor.
- **CI başarılı:** Belirli SHA üzerinde sahte veri/izole testler geçti.
- **API doğrulandı:** Yetkili sunucudan salt-okunur ve güncel sonuç alındı.
- **Üretim doğrulandı:** Planlı (manuel olmayan) çalışmanın gerçek platform gönderi ID'si ve tekrar-gönderim koruması kanıtlandı.
- **Telefon doğrulandı:** NTFY sunucu ACK'sine ek olarak Android cihaz üzerinde bildirim gözlendi.

Bu aşamalar birbirinin yerine geçmez. Canlı doğrulama yapılmadıysa **'tamam'** yazma.
