# Kullanıcı onaylı 1 Kasım 2026 güvenli telafi yayını

Kullanıcı, 1 Kasım sabahı aksayan veya eksik kalan videoların şimdi tamamlanmasını ve normal otomatik programın sürmesini açıkça istedi.

Bu işaret yalnız `publisher_one_shot_gate.py` ile **1 Kasım 2026 Türkiye saatinde**, ana dalda, tam commit başlığı `ops: owner-authorized-catchup-2026-11-01` ve ilk çalıştırma denemesi halinde bir kerelik `publish` modunu seçtirir. Başka tarihte, PR koşumunda, başka başlıkta veya yeniden koşumda `audit` modunda kalır.

Bu bir toplu arşiv yükleme talimatı değildir. Mevcut yayıncı yalnız günü gelmiş hesap/platform ve hedef sayısını seçer; önceki `done`/`intent`/`uncertain` kayıtları, platform geçmişi, hak ve rota anahtarları, günlük sınırlar, seri/parça sırası ve kaynaktaki dosya doğrulaması korunur. Yalnız doğrulanmış eksikler paylaşılır; hiçbir kilit aşılmaz ve Meta POST körlemesine tekrarlanmaz.

Yayın başarısı için `link-state-result` artefaktında ilgili gerçek `post_id` ve sağlayıcının uzak geçmişi; YouTube için `public`/`processed` sonucu aranacaktır. Başarısız/atlanan çalışma asla başarı diye bildirilmez.

Secret, token, kaynak video, eski state, claim ve GitHub geçmişi silinmez. Normal cron değiştirilmez; başka yayıncı açılmaz. Yeni ücretli servis kullanılmaz.


## 1 Kasım ikinci güvenli telafi tetiklemesi

Önceki canlı schedule devam ederken PR #68 kapsamında seri parçalar için öncül-post-ID doğrulama koruması 2424ad8a7746558d8234f8e3d25353f9bb97d704 commit'iyle ana dala alındı. Sahip talebi değişmedi: kalan ve gerçekten yayımlanmamış günlük hedefleri güvenli şekilde tamamla. Önceki çalışma sonlanmadan ikinci yayıncı aynı anda çalışmaz; workflow concurrency, uzak tarihçe uzlaştırması, intent/uncertain/done geçmişi, günlük kota ve geçerli tek META_ACCESS_TOKEN yolu korunur. Aynı kaynak için doğrulanamayan önceki girişler yeniden gönderilmez.


## 21:45 TRT — pre-upload güvenli kaynak telafisi

Önceki run #41331077663 34, run #41334846816 1 gerçek benzersiz Meta gönderisi kaydetti; 1 Kasım toplamı 64/69 (yeni run başlamadan). Kullanıcının mevcut telafi yetkisi hâlâ geçerlidir. PR #71 (e14c0a5c589a52e86f45f449c7f75bfb4072db0c) ile yalnız daha önce tamamen yerel MP4 doğrulamasında başarısız olmuş, exact aynı gün/source/platform kayıtları yeniden indirilmeden atlanabilir. Meta POST'su belirsiz kaynaklar tekrar yüklenmez. Film ve ToonZone sırası, günlük kota, geçmiş ID'ler, YouTube dedupe ve tek META_ACCESS_TOKEN korunur. Bu yalnız ilk run denemesiyle gün sonuna kadar çalışan mevcut publisher içindir. Önceki workflow koşumları tamamlandı ve eşzamanlı bir yayıncı yokken tetiklenmiştir.
