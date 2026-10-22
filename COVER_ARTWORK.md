# Kapak görseli altyapısı

Bu özellik production'da kapalıdır. Etkinleştirme için hem
`COVER_FEATURE_ENABLED=true` hem de `COVER_DRIVE_FOLDER_ID` gerekir.

`Video Kapakları` kök klasörü altında her kanal için ayrı bir alt klasör
kullanılır. Bir kapak, video ile aynı dosya gövdesine sahip olmalı ve Drive
`appProperties` alanlarında `cover_channel_key` ile
`cover_source_folder_id` değerlerini taşımalıdır. Böylece aynı adlı içerikler
kanallar arasında karışmaz. Eksik kapak videoyu engellemez; birden fazla eşleşme
ise kapak işlemini durdurur.

Destek durumu:

- YouTube: `thumbnails.set` ile video kimliği alındıktan sonra uygulanabilir.
- Instagram Reels: API `cover_url` destekler; ancak görselin Meta tarafından
  erişilebilen herkese açık URL'de olması gerekir. Özel Drive dosyaları için
  güvenli barındırma kararı verilene kadar kapalıdır.
- Facebook Reels: kullanılan Page `video_reels` yayın akışında doğrulanmış bir
  özel kapak parametresi bulunmadığından kapalıdır.

3:4 kaynak görseller arşivlenir ve doğrulanır. Platforma özgü kırpma/dönüşüm
bilinçli olarak otomatikleştirilmemiştir; kaynak görsel sessizce değiştirilmez.
