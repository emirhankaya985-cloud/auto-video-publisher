# 3 Kasım 2026 — güvenli otomasyon iyileştirmeleri

## Kapsam ve güvenlik sınırı

- **Otomatik yayın telafisi:** `AUTO_BACKFILL_ENABLED=true` ayarı açıldığında yalnız normal zamanlanmış yayında, ilgili hesabın yerel saati 18:00 sonrası ve geçmişte doğrulanmış günlük kota açığı en az 2 olduğunda aynı çalışmada **en fazla iki** aday video planlanabilir. Zaten etkin olan günlük kota, yetki/hak, kaynak, Instagram belirsiz yayın ve seri sırası kilitleri aynen geçerlidir. ToonZone on dakikalık dört parça düzeni kesinlikle hızlandırılmaz. Varsayılan **kapalıdır**; açık hale getirmek için prod kabul gerekir.
- **Hesap arıza yalıtımı:** Bağımsız bir hesabın geçmiş API yanıtı bozulursa o rota `HELD` kalır, diğer rotaların geçmiş kontrolü sürer. Ortak Meta kimlik keşfi ve GitHub artifact yükleme hataları yine bütün koşumu bloklayabilir; bunlar hesap düzeyi arıza değildir.
- **Kaynak değişiklik alarmı:** MP4'ün indirilen **ham baytlarına** SHA-256 kaydı, herhangi bir API yüklemesinden önce intent/state içinde tutulur. Aynı dosya ID'siyle yeni yayın adayı hazırlanırken önceki mevcut digest farklıysa **tüm o klibe ait planlı platformlar** `held` olur, yeni gönderi yapılamaz. Eski teyitli postlar ve diğer dosyalar korunur. Eski yayınlanmış kaynakların tamamını her seferinde indirmediğimiz için bu kontrol **her Drive dosyasına 7/24 tam tarama garantisi vermez**. Önceki digest yoksa yalnız yeni baz değer oluşturulur, geçmiş içerik doğrulandı denmez.
- **İçerik sıralaması:** GET-only kabul raporu her hesap+platform için en yüksek üç doğrulanabilir video etkileşimini `like_count + comment_count` olarak sıralar; eksik iki metrikten herhangi biri olan içerik dışlanır. İzlenme bazlı etkileşim oranı veya genel platformlar-arası kalite sıralaması değildir.
- **Threads:** Altı hesap eşleştirme tablosu, kullanıcı adı ve beklenen hesap ID'siyle GET-only kimlik karşılaştırması mevcut olduğu gibi korunur. Penguen için hesaba özel secret varsa artık genel legacy tokenı **önceler**. Hiçbir secret okunmaz/değiştirilmez; yanlış/expired token hiçbir zaman otomatik onarılmaz.

## Güncel Threads canlı gözlem

[41539380193](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41539380193) / 2026-11-02 22:42 UTC: `tarladaki`, `gonle`, `daily_laugh`, `film`, `toonzone` kimlik GET kontrolleri PASS; `penguen` **HTTP 401**, yayın yok. Bu durum yeni PR'ın değil, kontrol edilen main'in kanıtıdır. Değişiklikten sonra aynı altı hesabı yeniden GET-only koşarak ayrı canlı kabul verilmeli. `401` devam ederse GitHub'daki Penguen'e özel token yetkisi/süresi doğru OAuth istemcisinde düzeltilmelidir; gizli değerleri sohbete taşımayın.

## Yayına alma ve geri dönüş

Kod değişiklikleri PR üzerinden, CI ve review sonrası. Yeni `AUTO_BACKFILL_ENABLED` değişkeni varsayılan kapalı bırakılır. İlk prod kabulde `link-state-intent`/`link-state-result` ve Meta post ID eşleşmeleri kontrol edilmeden ek yayın fonksiyonu açılmamalıdır. Kaynak bütünlüğü koruması ilk baseline'dan itibaren çalışır; sonradan aynı Drive ID ile farklı MP4 görüldüğünde eylem otomatik yeniden yüklemek değil **tut ve bildir** olur.

Geri dönüş: PR merge commit'i geri alınır ve telafi değişkeni `false` kalır; mevcut yayın geçmişi, kaynak SHA ve belirsiz intent artifact'ları kesinlikle silinmez.
