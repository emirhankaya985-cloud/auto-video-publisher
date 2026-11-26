# Buffer X video entegrasyonu

## Güncel API ve ücretsiz plan

- API: GraphQL `POST https://api.buffer.com`, `Authorization: Bearer $BUFFER_API_KEY`.
- Video post: `createPost(input:)`, `assets: [{video: {url}}]`; zamanlı paylaşım `customScheduled` + ISO-8601 UTC `dueAt`.
- Medya URL'i Buffer'ın çekeceği anda herkese açık ve kimlik doğrulamasız olmalı. Google Drive özel dosyalarının `webViewLink` değeri medya URL'i değildir.
- Buffer Free: en çok 3 kanal; her kanalda aynı anda 10 queued/scheduled post; tek API key; 15 dakikada 150, 24 saatte 600 ve 30 günde kanal başına 1.000 (en çok 3.000) API isteği. Free queue kapasitesi 10 **kanal başına**, toplamda en çok 30.
- `RateLimit` response header'ları anlık kalan istek sayısını ve sıfırlanma saniyesini verir. `429` yanıtında `Retry-After` kullanılmalı. 429 güvenle yeniden zamanlanabilir; create isteğinde timeout/5xx/bozuk cevap sonucu belirsizse `uncertain` olarak tutulur ve otomatik yeniden gönderilmez.

Kaynaklar: [Buffer Quick Start](https://developers.buffer.com/guides/getting-started.html), [video post](https://developers.buffer.com/examples/create-video-post.html), [media hosting](https://developers.buffer.com/guides/hosting-media.html), [rate limits](https://developers.buffer.com/guides/api-limits.html), [Free plan](https://buffer.com/pricing).

## Kod ve aktivasyon durumu

`buffer_x.py` API istemcisi, X kanal keşfi, medya URL preflight, idempotency fingerprint'i ve Neon adapter/kuyruk durumlarını içerir. `migrations/20261126_buffer_x.sql` yeni tabloları ekler; mevcut publication kayıtlarını değiştirmez.

Yayın için gereken güvenlik koşulları:

1. Migration `DASHBOARD_DATABASE_URL` kullanan mevcut Neon yönetim süreciyle bir kez uygulanmalı.
2. `BUFFER_API_KEY` GitHub Secret olarak eklenmeli; log'a yazılmamalı.
3. Sahip hesabı Buffer'da X kanalını bağlamalı; API keşfi kimliği/bağlantıyı doğrulamalı. Aktif eşleme en fazla üç kanal olabilir. Yedi hesabın adları (Film Sahneleri ayrı dahil) kodda ayrıdır; Buffer Free hesabında yedisini bağlamaya çalışmaz.
4. İçerik hak onayı her kuyruk kaydında açıkça `rights_approved=true` olmalı.
5. Buffer'ın daha sonra çekebileceği, geçici yetkisiz erişimli, HTTPS MP4 URL'i doğrulanmalı. Drive klasörlerini herkese açık yapma.
6. Mevcut Drive seçici/yayın makbuzu ve hata/ntfy/Telegram sistemleriyle worker bağlantısı tamamlanıp CI ve güvenli gerçek olmayan operasyon kanıtı alınmadan `BUFFER_X_ENABLED` açılmamalı.

Şu an son madde ve güvenli, ücretsiz, geçici medya URL akışı bağlı değildir. Bu PR canlı yayın başlatmaz, yeni zamanlayıcı eklemez ve gerçek yayın iddiasında bulunmaz. `BUFFER_API_KEY` yoksa mevcut otomasyonlara etkisi yoktur.

## Test

`python -m unittest -v test_buffer_x.py` yalnızca mock yanıtları kullanır; Buffer'a bağlanmaz, video yüklemez ve sosyal paylaşım yapmaz.
