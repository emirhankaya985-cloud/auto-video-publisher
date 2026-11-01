# Kullanıcı onaylı 1 Kasım 2026 güvenli telafi yayını

Kullanıcı, 1 Kasım sabahı aksayan veya eksik kalan videoların şimdi tamamlanmasını ve normal otomatik programın sürmesini açıkça istedi.

Bu işaret yalnız `publisher_one_shot_gate.py` ile **1 Kasım 2026 Türkiye saatinde**, ana dalda, tam commit başlığı `ops: owner-authorized-catchup-2026-11-01` ve ilk çalıştırma denemesi halinde bir kerelik `publish` modunu seçtirir. Başka tarihte, PR koşumunda, başka başlıkta veya yeniden koşumda `audit` modunda kalır.

Bu bir toplu arşiv yükleme talimatı değildir. Mevcut yayıncı yalnız günü gelmiş hesap/platform ve hedef sayısını seçer; önceki `done`/`intent`/`uncertain` kayıtları, platform geçmişi, hak ve rota anahtarları, günlük sınırlar, seri/parça sırası ve kaynaktaki dosya doğrulaması korunur. Yalnız doğrulanmış eksikler paylaşılır; hiçbir kilit aşılmaz ve Meta POST körlemesine tekrarlanmaz.

Yayın başarısı için `link-state-result` artefaktında ilgili gerçek `post_id` ve sağlayıcının uzak geçmişi; YouTube için `public`/`processed` sonucu aranacaktır. Başarısız/atlanan çalışma asla başarı diye bildirilmez.

Secret, token, kaynak video, eski state, claim ve GitHub geçmişi silinmez. Normal cron değiştirilmez; başka yayıncı açılmaz. Yeni ücretli servis kullanılmaz.
