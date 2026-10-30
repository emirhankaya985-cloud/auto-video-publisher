# Hesaplar arası Meta etkileşim kodu

30 Ekim 2026. Günlük 13:00 TRT çalışması ve ilk manuel batch kullanıcı tarafından onaylanmıştır;
aktivasyon gerçek etkileşim veya büyüme kanıtı değildir. Ücretsiz mevcut GitHub Actions/Meta API altyapısını kullanır.

| İstek | Kodun davranışı |
| --- | --- |
| Facebook beğeni | Her doğrulanmış sayfa, kendi ve diğer yönetilen sayfaların yeni gönderilerini resmi `POST /{object-id}/likes` ile beğenebilir. Gereken izin: `pages_manage_engagement`. |
| Instagram beğeni | Her doğrulanmış profesyonel hesap, kendi ve diğer yönetilen hesapların yeni medyasını resmi `POST /{ig-user-id}/likes` ve `media_id` ile beğenebilir. Facebook Login User tokenı, `instagram_basic` ve `instagram_manage_engagement` gerekir. Page tokenı bu işlemde kullanılmaz. |
| Facebook yeniden paylaşım | Diğer sayfaların doğrulanmış Facebook video bağlantısını `POST /{page-id}/feed` ile paylaşır. İzin: `pages_manage_posts`. Bu yeni bir bağlantı gönderisidir; videonun tekrar yüklenmesi veya paylaşım sayacının artması garantisi değildir. Kendi paylaşımını tekrar paylaşmak uygulanmaz. |
| Facebook/Instagram kaydetme | Doğrulanmış resmi yazma uç noktası yok: `unsupported_by_verified_api`, API çağrısı veya sahte başarı yok. |
| Instagram yerel yeniden paylaşım | Doğrulanmış resmi yazma uç noktası yok: `unsupported_by_verified_api`. Video yeniden yükleme bunun yerine geçirilmez. |

## Yapılandırma ve çalışma

`.github/workflows/meta_cross_engagement.yml` her gün `0 10 * * *` UTC ile
13:00 Türkiye saatinde planlanır; GitHub cron gecikebilir. Yayın tamamlanınca
çalışan eski workflow_run tetikleyicisi kaldırılmıştır. 30 Ekim başlangıç marker'ı
birleştiğinde ilk canlı batch başlar; sonraki ilgisiz push'lar bunu çalıştırmaz.
Kaynak `latest`: en son tamamlanan ana yayın run'ının ledger'ı okunur; son 24
saatteki bütün native gönderilerin kaynak run'ları tek tek doğrulanır. Yalnız son
run'ın birkaç videosuyla sınırlı değildir. Geçmiş ledger kayıtları tekrar işlemi önler.

Kullanıcı isteğiyle workflow'un boş variable varsayılanı artık enabled/apply'dır.
`META_CROSS_ENGAGEMENT_ENABLED=false` bütün canlı işlemleri kapatır. UI manuel
workflow_dispatch varsayılanı dry_run kalır; apply açıkça seçilebilir. Bu değişiklik
token yetkisi kazandırmaz. İlk read-only raporda FB/IG beğeni izinleri eksiktir.

Mevcut `META_ACCESS_TOKEN` User tokenı kullanılır. Ayrı User tokenına sahip
sayfalar `META_AUTH_JSON.pages[]` içinde `user_token` ile yapılandırılabilir;
yalnız Secrets içinde tutulur. Kod canlı `/me/permissions`, `/me/accounts` ve
Page tokenı `/me` kimliklerini kontrol eder. Mevcut rota duraklatma ve hak onayı kapıları aktörlere de uygulanır. Yeni Instagram izni tokena daha önce
verilmediyse hesap `missing_permission` olur; uygulama yetki onayı gerekiyorsa kod
bunu aşamaz. Instagram Login tokenı veya Page tokenı User tokenı yerine taklit edilmez.

Her çalışmada son 24 saatte doğrulanmış kaynak run'ların gerçek native post ID'leri seçilir.
Eski gönderiler, reconciliation/alias kayıtları, başka repo/dal/iş akışı ve 24
saatten eski run'lar kabul edilmez. Aynı gönderi bir kez seçilir; aynı aktörün aynı
platform/gönderi/işlem birleşimi kalıcı ledger anahtarıdır. Böylece yeniden
paylaşımlar yeniden kaynak olup sonsuz döngü oluşturmaz.

Gönderinin sahipliği, bağlantı alanı ve aktör yetkileri POST öncesinde doğrulanır.
İlk API reddinde başarısızlık ayrı kaydedilir; izin/kota hatasında aktörün kalan
istekleri durur. Her POST öncesi bir saniye aralık uygulanır. Otomatik POST retry
veya timeout/5xx sonucunu başarı sayma yoktur. Beğenide `success=true`, Facebook
bağlantı paylaşımında gerçek yeni `id` gerekir; `accepted` API alındısıdır,
görüntülenme/beğeni sayacı artışı iddiası değildir.

Bütün batch intent'i ilk POST'tan önce artifact'a kaydedilir. Kesinti/yeniden
çalıştırmada reserved/uncertain/accepted kayıtları otomatik tekrar edilmez;
bu güvenlik nedeniyle henüz denenmemiş rezerve işler de durabilir. Sonuç ledger'ı
video yayın state'inden tamamen ayrıdır. Etkileşim hatası yayın job'ını veya başarılı
video upload'unu tekrar tetiklemez. Artifact'lar 90 gün, dry-run raporları 30 gün
saklanır. Kaynak replay 24 saatle sınırlı olduğundan ledger içeriği 48 saat sonra
budanabilir. Bozuk/okunamayan eski ledger kendiliğinden sıfırlanmaz.

Üretim aktivasyonu ve gerçek post/beğeni alındıları bu PR'ın testleri değildir.
Kapatma: `META_CROSS_ENGAGEMENT_ENABLED=false`. Yayın veya eski etkileşim kayıtları
silinmez. Doğrulanmamış API'ler, mobil private API, çerez/şifre veya tarayıcı botu kullanılmaz.

## Birincil kaynaklar

- [Meta Instagram changelog, 22 Nisan 2026 — Like Media and Comments API](https://developers.facebook.com/docs/instagram-platform/changelog/)
- [Meta User Likes: uç nokta, User tokenı, izinler ve burst sınırı](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/user-likes/)
- [Meta Object Likes: Page tokenı ve pages_manage_engagement](https://developers.facebook.com/docs/graph-api/reference/object/likes/)
- [Meta Page Feed: bağlantı gönderisi ve pages_manage_posts](https://developers.facebook.com/docs/graph-api/reference/page/feed/)

Resmi kaynaklar 30 Ekim 2026'da doğrudan HTTP üzerinden okunmuştur. Like API
changelog'a göre bütün sürümlerde geçerlidir; mevcut üretim Graph v24.0 korunur.
