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

## 24 Ekim 2026 güvenilirlik güncellemesi

- Mevcut 07/37 UTC yarım saatlik Meta kontrolüne ek olarak ToonZone'un
  12:00, 12:10, 12:20 ve 12:30 TRT video slotlarında da kontrol yapılır.
  `public-drive-recovery` concurrency grubu çakışan yüklemeleri sıraya alır.
  GitHub cron dakikası garantili değildir; günlük hedef kontrolü kalıcı niyet
  kaydı ve geçmiş denetimiyle korunur.
- `public_link_health.py` ve
  `.github/workflows/public_link_health.yml` her gün saat
  11:40 TRT'de son üç saatin gerçek planlanmış yayın işlerini denetler.
  Üst üste iki başarısız çalışma, son üç saatte başarı bulunmaması veya
  planlı çalışma görünmemesi kırmızı sağlık sonucu üretir.
  NTFY topic ayarlıysa ayrıca uyarı gönderir; değilse GitHub işi başarısız
  olur ve sessizce yeşil kabul edilmez.
- Bu watchdog yalnız GitHub Actions çalışma sağlığını ölçer. Yeşil sonuç
  tek başına video yayınlandığı, bütün hedeflere ulaşıldığı veya izlenme
  sayılarına erişildiği anlamına gelmez. Platform geçmişi ayrı doğrulanır.
- 985'in Meta-only modunda `LINK_AUTOMATION_ENABLED=true` ve
  `META_ACCESS_TOKEN` gerekir. `AUTOMATION_ENABLED` eski
  Drive OAuth/YouTube işlerine ait ayrı anahtardır; yeni sistemi açmak
  amacıyla etkinleştirilmemelidir.
- Geçiş CI'sındaki yapılandırılmış secret sayısı, eski/opsiyonel
  entegrasyonların eksiklerini de kapsar. Tüm bu secretların eksikliği Meta-only
  yayını otomatik olarak engellemez; ancak YouTube, Drive geçmiş arşivi ve
  klasik gün sonu izlenme raporunun çalıştığını göstermez.
- Gece raporu ve analytics job'ları `AUTOMATION_ENABLED` ile
  kapalı kalabildiğinden bu işler Meta-only operasyonlarda ayrıca
  güncellenmedikçe telefon istatistiği üretildiği varsayılmamalıdır.

## TXT kuralları ve doğrulanmış eşleşmeler (24 Ekim 2026)

- ToonZone'da kaynak TXT yoktur: mevcut 159 MP4 dosyasının her biri için
  `toonzone_txt_text` / `generate_toonzone_txts` tam adlı UTF-8 TXT üretir.
  Yayıncı bu metinleri otomatik kullanır. Video görüntüsü incelenmediği için
  sahne/diyalog iddiası eklenmez; yalnızca dosya adındaki sezon, bölüm, part
  ve başlık kullanılır. İşletim amaçlı TXT arşivi,
  `Generate ToonZone TXT archive` workflow artifact'ından alınabilir.
  Public Drive klasörüne otomatik TXT **yüklenmez**; okuma erişimi vardır.
- Diğer hesaplarda MP4 adına **tam eşleşen, dolu ve okunabilir TXT** zorunludur.
  TXT yoksa veya Drive erişimi hata verirse yanlış/genel açıklamayla
  yayın yapılmaz; ilgili içerik HELD raporlanır.
- Canlı ad eşleşmesi denetiminde ortak mizah 851/851, Gönle 314/314,
  Film 877/877 doğrulandı. Daily Laugh'ta 175 MP4'ün yalnızca 58'inin
  aynı adlı TXT'si vardı; **117 tanesi eşleşmedi**. Klasörde 561 TXT
  olması yeterli değildir; 101.mp4 gibi videolara 101.txt eşlenemiyor.
  Bunlar otomatik olarak rastgele başka TXT'lerle eşleştirilmemelidir.
- ToonZone görselleri için aynı denetimde 159 MP4'ün 48'inin tam adlı
  kapağı bulundu; 111 kapak eksik. Eksik kapaklar ayrı bir yayın engelidir.
- Doğrulama: 24 Ekim CI 365 unittest + 57 fonksiyon kontrolü başarılı;
  TXT arşivi canlı GitHub Actions işinde 159/159 oluşturuldu.
