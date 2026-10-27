# Sosyal medya yayın güvenilirliği incelemesi — 27 Ekim 2026

## Kapsam ve yöntemin sınırı

Başlangıç main: `181e292c6d188b5ba4c740296fa5fac1e0b3526f`.
PR: [#24](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/24).
Depodaki 135 Python dosyası AST/sözdizimi taramasından, 36 GitHub Actions
workflow'u YAML/yapı kontrolünden geçirildi. Bu otomatik tarama her satırın
elle incelendiği veya tüm eski entegrasyonların canlı çalıştığı iddiası değildir.

Elle incelenen aktif yol: `public_link_schedule.yml`, yayın yetki kapısı,
`public_link_runtime.py`, Graph hesap keşfi, kaynak/TXT/kapak seçimi,
Film/ToonZone sırası, Instagram medya profilleri ve binary/status/publish,
Facebook start/upload/finish, intent/result geri yükleme, hata jurnali,
bildirimler ve incident raporu. Raporlama, sağlık/rota izleme ve Cloudflare
fallback yapılandırmaları da yayın akışıyla ilişkileri açısından kontrol edildi.
Eski OAuth/YouTube yayın yolu açılmadı.

## Düzeltilen kod sorunları

| Sorun | Yeni davranış | Kanıt türü |
| --- | --- | --- |
| HTTP 400 içindeki Graph kota kodları okuma retry'ına girmiyordu | Yalnız Graph GET opt-in ile 4/17/32/613 için toplam üç okuma, 1/2 saniye bekleme | Hata enjeksiyonu |
| Hesap keşfinde tek geçici bağlantı/503 tüm yayını durdurabiliyordu | Keşif GET'i sınırlı retry kullanır; kimlik/izin hatası yine durur | Hata enjeksiyonu |
| IG container durumunu okurken tek geçici hata akışı kesiyordu | Aynı container için GET tekrarlanır; binary/container/media_publish POST'u tekrarlanmaz | Tam uploader mock testi |
| Bir hesabın ağ/tarih hatası diğer hesapların planını kesebiliyordu | Ağ hatası güvenli RuntimeError'a çevrilir; tarih doğrulaması hesap hata sınırına alınır | İki hesaplı plan testi |
| Sayfalı geçmişte tekrarlanan ID kotayı yanlış doldurabiliyordu | Aynı platform videosu bir kez sayılır; bozuk ID/tarih/sayfalama durdurulur | Çok sayfalı test |
| Ledger'da aynı post ID'sinin iki eşlemesi hedefi şişirebiliyordu | Günlük ledger sayacı tekil, kimliği olan tamamlanmış gönderileri sayar | Ledger alias testi |
| Facebook açık `success:false` yanıtı hata sayılmayabiliyordu | Upload/finish başarısız yanıtı MetaAPIError olur; yayımlandı ID'si döndürülmez | Her iki aşamada hata enjeksiyonu |
| Günlük hedef eksikken boş/uygunsuz kuyruk sessiz kalabiliyordu | Rota başına yerel takvim gününde bir kez `no_eligible_content` olayı; mevcut belirsiz intent uyarısı çoğaltılmaz | Aynı gün iki tick, audit ve NOT DUE testleri |
| Önceki kurtarma kanıtından alt hata kodu aktarılmıyordu | `graph_subcode` yeniden değerlendirmeye taşınır | Mevcut kurtarma regresyonları |
| Kapak birleştirme işlemi sınırsız bekleyebiliyordu | FFmpeg kapak işlemi 900 saniyede durur; mevcut pre-upload hata yolu kaydı ready tutar | Kod incelemesi + mevcut kaynak hazırlık regresyonları |

## Test sonucu ve canlı kanıt

- Yerel tam paket: **564 unittest, 57 fonksiyon kontrolü, 15 Node testi**.
- Yeni hata enjeksiyonları gerçek token/API/bildirim kullanmaz. Test stdout'undaki örnek gönderiler canlı yayın kanıtı değildir.
- GitHub CI sonucu, tam commit SHA ve çalıştırma bağlantıları PR checks bölümündedir. İlk PR sürümünün yeşil CI'sı bu genişletilmiş sürümün yerine geçmez.
- Son incelenen eski-main üretim [#40520730569](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40520730569): 3 yeni gönderi, 0 hata, 0 belirsiz yeni/eski intent. Bu sonuç yeni kodun üretim doğrulaması değildir.
- Yeni kodun gerçek kabulü: normal planlı run, platform post ID'leri, intent/result ve incident arşivi birlikte görülmeli. Bu çalışma sırasında test amaçlı yayın veya telefon mesajı tetiklenmedi.

## Korunan kurallar ve kalan işletim sınırları

- Film/ToonZone sıra, hak onayı ve duraklatma kapıları korunur. Çözülmemiş publish belirsizliği silinmez; uzaktan doğrulama gerektirir.
- Kaynak tükendiyse veya geçersizse kod yeni gerçek video yaratamaz. Hedef eksikliği artık sessiz bırakılmaz.
- Meta/Drive erişim engeli, token süresi, platform kesintisi ve GitHub cron gecikmesi sıfır hata garantisine izin vermez. Güvenli olmayan POST tekrarı çözüm sayılmaz.
- Harici Cloudflare fallback eski yayın yolu/slot ayarları içerir; güncel Meta-only yol için canlı dağıtım ve dispatch modu kanıtı olmadan çalışıyor kabul edilmez. Bu inceleme onu etkinleştirmedi.
- GitHub artifact retention 90 gün; süresiz bağımsız arşiv değildir. Telegram/ntfy ACK telefonda görünür teslimi kanıtlamaz.
- Geri alma: bu PR commit'lerini geri al; ledger, Drive içeriği ve platform gönderilerini silme. `AUTOMATION_ENABLED` açılmaz.
