# Instagram kaynak videolarını alım sistemi

Bu özellik, etkin altı yayın rotası için isteğe bağlı bir alım hattı ekler. Film Second yeni toplama ve yayın matrislerinin dışında kalır; geçmiş kayıtları korunur. Sistem, Meta'nın resmi Instagram Business Discovery API'sini kullanır, kaynak ve yinelenen içerik kayıtlarını mevcut Neon veritabanında tutar, doğrulanmış videoları her rota için ayrı Google Drive alt klasörüne alır. Toplama kendi başına yayın yapmaz ve Instagram'ı kazımaz.

## Varsayılan durum ve etkinleştirme

`instagram_source_accounts.json` içindeki altı rota kapalıdır. `source_accounts` listeleri boş, `collection_folder_id` alanları boş. Toplama işi ayrıca GitHub Actions `IG_SOURCE_COLLECTION_ENABLED=true` değişkenini ister. Kaynak yayını için mevcut genel yayın anahtarına ek olarak `IG_SOURCE_PUBLISHING_ENABLED=true`, rota başına açık ayarlar ve izinli kaynak gerekir. Mevcut yayın saatleri aynen kullanılır. Üretim yapılandırması değiştirilmedi.

Kaynak eklerken aşağıdaki alanları doldurun:

```json
{
  "username": "public_creator_username",
  "enabled": true,
  "rights_approved": true,
  "rights_evidence": "license or permission reference",
  "official_api_download_allowed": true
}
```

Yalnız resmi API üzerinden erişilebilen herkese açık profesyonel Business veya Creator profilleri desteklenir. API erişimi veya herkese açık bir gönderi, yeniden yayın hakkı vermez. İndirmeyi açmadan önce izin/lisans kanıtını kaydedin. Meta bir medya URL'si döndürmezse sistem alternatif kaynaktan indirme veya kazıma denemeden içeriği beklemeye alır.

Her rota için `collection_folder_id`, mevcut `target_folder_id` klasörünün ayrı bir alt klasörü olmalıdır. Tarladaki Fasulye ve Beyinsiz Penguen aynı üst klasörü paylaşır, ancak alım alt klasörleri ayrı kalmalıdır. Yapılandırma parent ilişkisini doğrular ve farklı rotaların aynı alım klasörünü kullanmasını reddeder. Dosya adındaki rota öneki ortak üst klasörde içerik sahipliğini korur.

## Toplama ve seçim

Her 30 dakikada yapılandırılmış kaynakların tüm sayfaları taranır. Sistem, Europe/Istanbul gününde yayımlanmış video gönderilerini seçer; fotoğrafları eler, resmi CDN adresini, boyutu, MP4 imzasını ve video akışını doğrular, ardından SHA-256 ile kaynak metaverisini kaydeder. Kaynak hesap ID'leri, kategoriler, izin kanıtı ve tarama sonuçları Neon'da tutulur. Mevcut Drive dosyası ancak kaynak kimliği, bayt boyutu ve Drive checksum'u eşleşirse tekrar kullanılır; çakışma beklemeye alınır. Başlık ve API küçük resmi videonun yanında saklanır. Medya URL'leri ve erişim tokenları log veya Neon'a yazılmaz.

Neon; küresel medya hash'lerini, rota bazında envanteri, günlük planı ve Facebook/Instagram yayın durumlarını tutar. Yayımlanmamış uygun içerikler kalite ve mevcut herkese açık metriklere göre sıralanır. Her rota günlük en çok 3 yeni ve 3 arşiv videosu planlar; kaynak başına günlük üst sınır 2'dir. Havuz kısa kalırsa açık eksik olarak raporlanır; diğer havuzdan sessizce tamamlanmaz. Önceki gün seçilmeyen yeni videolar bir sonraki İstanbul gününde arşive geçer.

Mevcut public-link yayıncısı yalnızca o rotanın Neon planındaki kimlikleri ve izole alım klasörünü kullanır. Yayından önce indirilen baytları kayıtlı hash'le karşılaştırır, eşleşen başlık ve kapağı ister. Film Mağarası ve ToonZone'da seri sırasını korumak için yeni kaynakların otomatik yayını kapalıdır. Bu hat Facebook ve Instagram içindir; Threads veya YouTube rotalarına dokunmaz.

## Mevcut entegrasyon durumu

Altı alım klasörünü Drive'a ekleme denemesi `403 insufficientParentPermissions` ile reddedildi; tarayıcıda da üst klasör salt okunurdu. Bu yüzden klasör ID'leri yapılandırmaya eklenmedi. Drive listeleme yetkisi, GitHub Actions `DRIVE_TOKEN_JSON` kimliğinin yazma yetkisini kanıtlamaz. Google Drive'da alım klasörlerini oluşturup doğruladıktan sonra ID'leri ilgili rotalara ekleyin. Canlı kaynaklar, izinler ve klasörler doğrulanana kadar toplama/yayın anahtarlarını kapalı tutun.

## Gerekli GitHub ayarları

Mevcut secrets: `META_ACCESS_TOKEN`, `DRIVE_TOKEN_JSON`, `DASHBOARD_DATABASE_URL`. `IG_SOURCE_DISCOVERY_ACTOR_ID` değişkeni, resmi API keşfi için yetkili profesyonel hesap ID'sini almalıdır. Secret değerlerini repoya veya sohbete koymayın. `DASHBOARD_DATABASE_URL`, mevcut Neon üretim veritabanını göstermelidir; secret'ın gerçek hedefi GitHub ayarlarında gizli değeri açmadan doğrulanmalıdır.

Toplamayı etkinleştirmeden önce izinli kaynakları ekleyin, her alım klasörünü oluşturup parent ilişkisini ve üretim tokenını doğrulayın, sonra yerel testleri çalıştırın. Toplama ile yayın birbirinden bağımsız açılabilir; ikisini de tüm ön koşullar tamamlanana kadar kapalı tutun.
