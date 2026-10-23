# Link tabanlı Meta otomasyonu

23 Ekim 2026 geçişi: `Public link Meta automation` iş akışı,
`public_link_runtime.py` üzerinden paylaşılan Drive klasörlerini okur.
Drive OAuth veya kullanıcı tarafından hazırlanmış bir JSON dosyası gerekmez.
Meta anahtarı yalnız `META_ACCESS_TOKEN` GitHub Secret'ındadır.

## Çalıştırma ve durdurma

- Yeni otomasyonun anahtarı: `LINK_AUTOMATION_ENABLED=true`.
- Her saatin 07. ve 37. dakikasında kontrol planlanır. GitHub zamanlayıcısı gecikebilir.
- `Run workflow → audit` yalnız klasör, TXT, hesap ve geçmiş denetimi yapar.
- `Run workflow → publish` eksik yayınları gerçek platformlara gönderir.
- Durdurma: `LINK_AUTOMATION_ENABLED=false`. Devam eden işi ayrıca inceleyin.
- Eski `AUTOMATION_ENABLED` anahtarı kapalı kalmalıdır; eski yol Drive OAuth gerektirir.
- AFK deposundaki `omnichannel-upload` işi, 985 geçişi nedeniyle `false` koşuluyla durduruldu.
- YouTube bu iş akışında kapalıdır. Yalnız mevcut Meta hesap izinleri kullanılır.

## İçerik ve zamanlama

- Tarladaki, Penguen ve Gönle: mevcut beş günlük slot.
- Film: mevcut beş günlük slot; aktif Yoksul serisi önce tamamlanır.
- Daily Laugh: New York saatine göre mevcut sekiz slot.
- ToonZone: bölümün dört parçası, Türkiye saatiyle 12:00/12:10/12:20/12:30.
- Yalnız 23 Ekim için günün tüm hedefleri erken telafi modundadır; her turda
  hesap başına en fazla bir video seçilir. İkinci Film sayfasının eksik Part6'sı
  ayrıca telafi edilir. Sonraki tarihlerde normal saatler otomatik uygulanır.
- ToonZone klasöründe denetlenen 159 MP4'ün yanında TXT yoktur. Başlık ve
  açıklamalar bölüm/Part metadata şablonundan hazırlanır. Eşleşen TXT eklenirse
  açıklamada o dosya tercih edilir. Tam adlı PNG kapak zorunludur.
- Diğer hesaplarda tam adlı TXT eşleşmesi zorunludur. Daily Laugh'ta aynı adlı
  belirsiz kopyalar dışlanır; tekrar kullanılan TXT gövdesi korunarak başına video
  numarası eklenir.

## Geçmiş ve tekrar paylaşmama

`migration_verified_publications.json`, eski AFK işlerinin gerçek platform
gönderi kimliklerinden doğrulanan 269 kaydı içerir. Başarısız bir işin içinde
başarıyla yayımlanmış platform sonuçları da korunmuştur. Bu dosya kimlik
bilgisi veya token dosyası değildir.

Her turun yayın niyeti, medya yüklenmeden önce `link-state-intent` artifact'ına
kaydedilir. Gerçek sonuçlar, kısmi hatalar dahil `link-state-result` artifact'ında
korunur. Bir sonraki tur en güncel sonucu veya sonuç yoksa en güncel niyeti okur.
Belirsiz gerçek yayın sonucu otomatik tekrar edilmez. Yükleme başlamadan oluşan
indirme hataları yeniden seçilebilir. Durum kayıtları hatalı veya süresi dolmuşsa
geçmiş otomatik sıfırlanmaz. Artifact saklama süresi 90 gündür.

`public-drive-recovery` concurrency grubu, yeni zamanlayıcıyı ve eski tek-video
kurtarma yolunu aynı depoda sıralar. Normal işletimde yeni zamanlayıcı kullanılmalıdır.

Bir işin yeşil olması tek başına bütün hesapların günlük hedefe ulaştığını
göstermez. Hesap bazlı `published_today`, `NEXT`, `HELD` satırları ve gerçek
platform gönderi kimlikleri kontrol edilmelidir.
