# 985 Üretim Olay Defteri ve Kurtarma Senaryoları
**Tarih:** 24 Ekim 2026 · **Aktif yayıncı:** `public_link_schedule.yml` · **Kaynak:** `main`

Bu dosya silinmeyecek bir teknik devir kaydıdır: geçmişte görülen hatalar,
hangi davranışın kabul edilebilir olduğu, otomatik kurtarma sınırı ve canlı
doğrulama şartları. Yeni ajanlar/Codex *önce bunu ve AGENTS.md'yi okumalıdır*.
Her arıza için son hata kodu, run bağlantısı ve mevcut koruma güncellenmelidir.
GitHub CI'nın yeşil olması gerçek video yayınlandığını kanıtlamaz.

## Temel kural

**Hedef her mümkün yayın slotunda video yayınlamak, ama çift gönderi
yaratmamak.** Token eksikliği, yayın yetkisi, Google Drive erişim engeli,
Meta API kesintisi, kötü/eksik video veya ToonZone kapağı hâlâ yayın
engelleyebilir. Bu engeller zorla aşılamaz; kullanıcıya somut nedene bağlı
uyarı verilir. İkinci yayıncı `AUTOMATION_ENABLED` etkinleştirilmez.

## Hata hafızası (gerçek eski kayıtlarla)

| Olay | Kanıt | Temel etki | Güncel strateji |
| --- | --- | --- | --- |
| Drive `FileURLRetrievalError` / videoyu indirememe | [23 Ekim prod #39906684586](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/39906684586) | Bazı hesaplar yayımladı, diğerleri indirilemeyen dosyada bekledi | MP4/TXT/PNG okuması 3 denemeli, parçalı dosya silinir. API yazımı başlamamışsa tekrar hazırlamak güvenlidir |
| Film IG kompakt transcode / ffmpeg hatası | [22 Ekim #39829354758](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/39829354758) | Instagram hazırlığı yayın öncesi başarısız | Instagram yerel dönüştürme hatasında yalnız IG `ready`; FB ayrı yayımlanabilir |
| Instagram HTTP 400 / Graph 100 / 2207009 benzeri | [API regresyonu](../test_instagram_binary_upload.py) | Video/parametre/container yükleme reddi | Aşama, HTTP ve Graph alt kodunu kaydet. Yayın öncesi IG binary/processing 400'ünde (Tarladaki/Penguen/Daily Laugh) uzaktan geçmiş kontrolünden sonra **en fazla 1 alternatif kompakt transcode** uygula; ikinci 400 veya herhangi bir media_publish belirsizliğinde dur. Kör POST tekrarı yasak |
| Graph rate limit 429, 4/17/32/613 | [Kod testi](../test_publisher_recovery.py) | İstek kotası dolabilir | Yalnız GET işlemlerinde 1s/2s bekleyerek 3 deneme; Meta upload/publish POST'u asla otomatik yineleme |
| Graph/GitHub geçici 5xx veya okuma bağlantı hatası | [Kod testi](../test_publisher_recovery.py) | Meta geçmişi/state bulunamayabilir | Salt-okunur isteği sınırlı yinele; geçmiş hâlâ okunamıyorsa yüklemeyi durdur, state sıfırlama |
| Üretim testinin saat bağımlılığı | [24 Ekim başarısız #40062876739](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40062876739) | Yayın iş akışı gerçek planlamaya geçemedi | ToonZone hedefini zamandan bağımsız mock eden test; yeniden oluşursa CI kırmızı |
| ToonZone TXT yokluğu | [TXT arşivi #40067669975](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40067669975) | Eski kaynakta 159 videonun TXT'si yoktu | Bölüm hikâyesine bağlı 159 TXT otomatik hazırlanır; gerçek olmayan sahne/diyalog uydurulmaz |
| Daily Laugh TXT eşleşmesi eksik | [TXT arşivi #40067669975](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40067669975) | 175 MP4'ten 117'sinin tam adlı TXT'si yok | 117 adla eşleşen İngilizce TXT üretilir; 58 mevcut TXT korunur; videodaki sahne uydurulmaz |
| ToonZone kapak yokluğu | [Canlı kaynak denetimi #40067576232](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40067576232) | 159 MP4'e karşı yalnız 48 eşleşen PNG (1. sezon) | 27 Ekim güncel: 48 doğrudan PNG eşleşiyor; diğer 111 part için `TOONZONE_AUTO_COVER_ENABLED=true` iken yalnız kendi MP4 karesinden bölüm/part etiketli PNG üretilip Meta POST'tan önce doğrulanır; üretim başarısızsa video HELD kalır. Drive'a elle 111 kapak eklemek zorunlu değildir |
| Eski Telegram token/bağlantı hatası | [Başarısız #40066950833](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40066950833) ve [başarılı smoke #40067496169](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40067496169) | Bildirim yok | Secret değerlerini kodda tutma; Telegram sonucu ayrı raporlanır, başarısız bildirim Meta postu tekrar ettirmez |
| Yeşil Actions ama sıfır video | [Başarılı no-op #40066720418](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40066720418) | Çalışma sağlığı yayın kanıtı değildir | `NOT DUE`, `NEXT`, `HELD` raporları; yeni post ID'si / gerçek hesabın geçmişi ayrıca görülmeli |
| S1/S2 ToonZone parti sırası / belirsiz Meta sonucu | [Kod güvenlik testleri](../test_public_link_runtime.py) | Çift paylaşım veya yanlış part riski | Önce intent artifact, sonra sonuç artifact; `uncertain` uzlaştırılmadan yeni aynı part denemesi yok |
| Instagram geçmişinde fotoğrafların kota sayılması | [Regresyon](../test_public_link_runtime.py) | Reel sayısı sahte yüksek gözükür | `media_type=VIDEO` şartı |
| Gün sonu izlenme raporu legacy toggle'a bağlı | [Workflow](../.github/workflows/daily_stats.yml) | Meta-only etkin olsa da 23:59 TRT raporu atlanabilir | **Taslak PR #5 kod/test düzeltmesi hazırlanıyor; canlı schedule ve teslim doğrulanmadı.** `META_REPORTING_ENABLED` kullanıcı onayıyla ayrıca açılmalı |

## Kurtarma karar matrisi (her GitHub planlı çalışmasında)

| Belirti | Yayın öncesi kanıt | Otomatik işlem | Durdurma ve alarm |
| --- | --- | --- | --- |
| TXT yok | ToonZone veya Daily Laugh'da eşleşen TXT yok | Bölüm / hesap kurallarına uygun, doğrulanabilir kısa TXT yaz. Var olan TXT'ye dokunma | Başka hesapta gerekli TXT eksikse o video beklesin |
| TXT bozuk / boş | Dosya indirildi ama okunmuyor | Drive indirme 3 deneme; sonra sonraki güvenli planlama | Hatalı metni paylaşma |
| Drive MP4/PNG 403, geçici erişim veya eksik bytes | Meta API çağrılmadı | 3 indirme denemesi ve parsiyel temizliği | 3 deneme sonrası o dosya `ready` |
| Video konteyneri / codec / ffmpeg hatası | Yerel medya hazırlığı ve hiç Meta POST yok | IG `ready` bırak; sonraki slotta yeniden hazırlanabilir; FB'yi engelleme | Tekrarlayan kaynak sorununu incident artifact'ına yaz |
| Meta GET 429 / 5xx | Yalnızca geçmiş/token kontrolü | 1s, 2s gecikme, en fazla 3 okuma | Geçmiş okunamadıysa upload yok |
| HTTP 400 IG media/binary/status | Yalnız binary/processing aşamasında `media_publish` henüz çağrılmadığı kodla kanıtlanabilir | Desteklenen üç rota için bir kez daha sıkı kompakt video hazırla; yeni koşumda önce Meta geçmişini oku | `media_publish` çağrısı belirsizse veya ikinci 400 olursa asla otomatik POST tekrarı yok |
| HTTP 401/403, yetki/secret | Meta istendi | Teknik hata raporu; diğer bağımsız hesabı koru | Credential olmadan atlatma yok |
| Meta publish timeout / 5xx | Platform isteği gitmiş olabilir | `uncertain`, caption hash ile Meta geçmişini uzlaştır | POST'a kör retry yok |
| GitHub state/artifact okunamadı | Daha önce yayın yapılmış olabilir | GET yeniden deneme | State sıfırlama ve yeni yayın yok |
| Kapak eşleşmiyor | ToonZone dosya adı / PNG tam eşleşmiyor | Bir sonraki doğru kapak eklendiğinde planla | Yanlış kapak kullanma |
| Hak onayı, duraklatma, günlük kota | Mevcut route gate ve gerçek geçmiş | Mevcut kuralı koru | İlke/izinleri aşarak gönderi yok |
| GitHub cron gecikti | Planlanan dakika geçti | Mevcut günlük hedef/gönderi geçmişini yeniden hesapla | Aynı gün tekrar-video yok |
| Telegram/ntfy başarısız | Meta sonucu kaydedildi | Ayrı uyarı/hata artifact'ı | Bildirim hatası yayıncıyı yeniden başlatmaz |

## Çalışma kanıtı / her yeni CI'ya kontrol listesi

1. **Kod:** `migration_ci.yml` `main` SHA'sında başarılı, yeni senaryo testleri mevcut.
2. **Gerçek kaynak:** Drive MP4/TXT/kapak envanteri; hangi klasörde kaç eksik?
3. **Durum:** `link-state-intent`, `link-state-result`, yeni `link-incident-report` artefaktları korunmuş mu?
4. **Gerçek yayın:** Hesap + platform + video adı + `post_id` kanıtı var mı? Sadece yeşil run yeterli değil.
5. **Çift gönderim:** Önceki `uncertain` uzlaşıyor mu; yeni aynı klip/part iki kere paylaşılmadı mı?
6. **Bildirim:** Telegram server ACK ayrı, Android teslimi ayrı. Yanlışlıkla paylaşım mesajı üretme.
7. **Bitiş kriteri:** Her rota için yayın hedefi, hata sayısı ve engeller ayrı raporlandı; eksik canlı delile **UNVERIFIED** yaz.

**Kapsam dışı kullanıcı işi:** NTFY Secret'ları, eski YouTube/Drive OAuth tokenları
ve `AUTOMATION_ENABLED` kullanıcı tarafından başka sohbette ele alınıyor.
Bu dosyaya bakarak legacy yayıncıyı açma. Sezon 2 kapaklarını kullanıcı ekleyecek.

## Yapılandırılmış tüm hata kayıtları (24 Ekim 2026)

Son yayıncının `publisher_error_journal.py` modülü her gerçek üretim
koşumunda oluşan Drive envanter, Meta hesap/geçmiş, TXT, kapak, kaynak video,
Instagram hazırlık, Facebook/Instagram API ve Telegram/ntfy teslim hata
olaylarını ayrı JSONL satırlarında yazar. Her olay şu alanları taşır:

- Zaman (UTC), ilgili GitHub Actions run ID ve çalışma linki.
- Kanal/hesap rotası, Facebook veya Instagram platformu, dosya adı.
- İşlemin aşaması, güvenli hata sınıfı, exception türü.
- Varsa HTTP durumu, Graph kodu ve alt kodu, `uncertain` durumu ve
  güvenli tekrar politikası.
- Bildirim verilemeyen durumlarda da aynı kayıt oluşturulur.
- GitHub Actions testlerinin kasıtlı mock hataları gerçek hata dosyasına
  **yazılmaz**, sahte telefon alarmı oluşturmaz.

Her yayın iş akışı sonunda iki artefakt tutulur: `link-error-journal`
(tüm yapılandırılmış olaylar, `errors.jsonl`) ve
`link-incident-report` (tüm olayları içeren `incidents.json`,
her adımın verify/plan/publish/notify sonucu). Dosyalar GitHub Actions
artefaktlarında **90 gün** tutulur. Bu kayıtların süresiz
arşivlendiği iddia edilmemelidir; kalıcı teknik nedenler, düzeltme ve
kanıt linkleri bu runbook'a eklenmeye devam edilmelidir. Ham loglar GitHub
Actions job loglarında ayrıca incelenebilir; bunları gizli token/özel URL
içerme ihtimaline karşı halka açık belgelerde aynen kopyalama.

**Gerçek olay:** [24 Ekim planlı yayın #40073539771](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40073539771)
yeni Instagram etiketleme testindeki modül patch hatası yüzünden
`Verify...` aşamasında durdu ve video paylaşamadı.
Kod, [düzeltme CI #40074189541](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40074189541)
ile doğrulandı. Gelecekte yeni testler gerçek yayın workflow'unda test
hatası üretirse `verify` adımının sonucunu ayrıca hata defterine
kaydet; GitHub Actions başarılı/başarısız ile gerçekten yeni post ID
üretildiğini karıştırma.

**Yeni hata kaydı sahibi**: AI/Codex bakımında her gerçek olayın
run linkini ve giderilen kök nedenini bu dosyaya ekle; olay dosyasını
ham metinle veya erişim tokenıyla hiçbir zaman birleştirme.

## 24 Ekim 2026 — Meta günlük raporu ve belirsiz yayın onarımı (taslak PR #5)

- **Başlangıç sorunu:** `daily_stats.yml` ve `daily_report_watch.yml` eski `AUTOMATION_ENABLED` anahtarını kontrol ediyordu. Böylece Meta-only yayıncı çalışırken 23:59 TRT günlük raporu atlanabiliyordu. Kaynak: eski `main` workflow'ları.
- **Güvenli hazırlık:** [PR #5](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/5) içinde `META_REPORTING_ENABLED == 'true'` bağımsız ve açık opt-in anahtarı eklendi. Eski yayıncı kesinlikle etkinleştirilmedi. Meta-only raporda YouTube ve Drive OAuth yükleme yolu kullanılmaz. `analytics_github_history.py` 90 gün tutulan GitHub `meta-daily-analytics-history` artefaktından önceki ölçümü getirir; ilk gün farkı `N/A`, eksik/erişilemeyen arşivde tarihsel kıyaslaması doğrulanmamış olarak bırakılır. Sahte `0` üretilmez.
- **Düzeltme ve güvenlik:** Bozuk Meta HTTP 200 yanıtları veri yokmuş gibi sıfıra düşmez. Rapor, Meta video görüntülenmelerinin toplamını bütün içerik türlerinin kesin ömür boyu hesap metriği olarak sunmaz; sahte yayın sayacı yerine `N/A` döndürür. Eşzamanlı çoklu açıklama eşleşmelerinde yayıncı rastgele gönderi seçmez; belirsiz geçmiş güvenli beklemeye alınır. Tekil ve kimliği/zamanı doğrulanmış uzlaştırmada İstanbul/New York gerçek yayın günü yazılır ve eski `run_id` korunur; uzlaştırma yapan run ayrıca kaydedilir. Açık MP4 okuma dosya yöneticisiyle kapatılır.
- **CI kod kanıtı:** İlk [PR rapor CI #40075587481](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40075587481) test-only ortamda eksik `PyYAML` yüzünden iki modülü import edemedi (uygulama hatası değil). Sabit PyYAML eklendikten sonra [CI #40075636728](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40075636728) **458 Python unittest** ve workflow koşul kontrolü ile başarılıydı; **bu, sonraki publisher uzlaştırma commit'inin CI kanıtı değildir**. Son commit için yeni CI ayrıca incelenmeli.
- **Henüz canlı kabul yok:** Draft PR birleştirilmedi, `META_REPORTING_ENABLED` ayarlanmadı, planlı 23:59 raporu ve 07:10 watcher gerçek koşumda doğrulanmadı; Telegram/ntfy sunucu ACK'si ve Android telefon teslimatı birbirinden ayrıdır. Hesap kimliklerinin tamamı, aynı paylaşım için kalıcı bildirim kuyruğu ve tüm rota/hedef blokajları hâlâ bağımsız çalışma ister. Üretim yayın workflow'u zorla tetiklenmedi.
- **Geri dönüş:** PR birleştirilmeden hiçbir üretim değişikliği yok. Birleşirse `META_REPORTING_ENABLED=false` ile rapor/watch salt-okunur işlerini kapat; kod geri alma için PR commit'lerini tersine al. Eski `AUTOMATION_ENABLED` anahtarını açma. GitHub istatistik/publisher intent/result artefaktlarını ve eski geçmişi silme.


## 25 Ekim 2026 — toplu canlı log denetimi ve yeni kurtarma politikası

[Kapsam, tam hata listesi ve GitHub run bağlantıları](META_LOG_AUDIT_2026-10-25.md)

- 610 GitHub Actions run durum kaydı indekslendi. Aktif Meta yayıncısında
  110 çalışma: 75 `success`, 35 `failure`; başarısızın bir kısmı eski
  dönem Drive/CI testleri, 24–25 Ekim yeni dönemi ağırlıkla Instagram
  `rupload` `ProcessingFailedError` / HTTP 400.
- Sadece `faststart` remux bazı 1080p 30/60fps videolarda yeterli olmadı;
  Tarladaki/Penguen/Daily Laugh için 30fps H.264/AAC normalize medya
  seçildi. Tam başarı yalnız yeni sürümün canlı yayınında kanıtlanabilir.
- Film `Yoksul_1986_Part_16.mp4` ve ToonZone
  `S01E03_Caffeinated_Concert_Tickets_Part3.mp4` önceki
  `HTTP400` sonrası `uncertain` durumuyla kilitlenmişti. Yeni kod,
  **yalnız daha önce `media_publish` çağrılmadığı stage, HTTP ve eski
  `caption_hash` ile kanıtlanan** vakayı uzaktan Meta geçmişi kontrol
  edildikten sonra bir kez yeniden kodlamaya alabilir. Eski hatalı
  kompakt bitstream'i tekrar kullanmaz. İkinci hata belirsiz durumunu
  temizlemez veya otomatik Meta POST tekrarlamaz.
- Başka `uncertain` intent'lerin sessiz kalmasına izin verme: Bir kez
  `previous_intent_hold` olayını hata jurnaline yaz ve telefon alarmı
  gönder; sonraki 30 dakikalık yoklamaları spam'e çevirme.
- [25 Ekim gerçek 5 gönderili yayın #40221619361](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40221619361)
  **eski SHA** üzerindedir: bu yeni kurtarma kodunun gerçek
  Instagram HTTP 400'ü düzelttiğini kanıtlamaz.
- **Gizlilik:** API yanıtındaki ham metin, Meta erişim tokenı ve imzalı
  Drive adresleri public kurtarma defterine yazılmaz. Tüm olaylar için
  `link-error-journal` ve `link-incident-report` 90 günlük
  artefaktları incelenir. GitHub run URL'leri kalıcı kanıttır.

## 25 Ekim 2026 — Film Part 16 / ToonZone Part 3 güvenli kurtarma ve kapak yedeği

**Canlı kaynak kanıtı:** [Film arızalı koşum #40107188749](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40107188749) içinde `Yoksul_1986_Part_16.mp4` iki Facebook sayfasında başarıyla yayımlanmıştı (post ID `1148295597775908` ve `1591935948833170`); Instagram ise `Instagram ikili video aktarımı` aşamasında HTTP 400 `ProcessingFailedError` verdi. [ToonZone arızalı koşum #40082286094](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40082286094) içinde `S01E03_Caffeinated_Concert_Tickets_Part3.mp4` Facebook'ta `2520090981810851` ID ile doğrulandı, Instagram sonucu doğrulanmadı. İki Facebook videosunu **yeniden paylaşmak yasak**.

**Kurtarma mantığı:** Meta'daki uzaktan gönderi geçmişi tamamen okunmadan hiçbir işlem başlatılmaz. Yalnız `media_publish` aşamasına ulaşmadığı kayıtla kanıtlanan HTTP 400 durumunda **bir defalık farklı yeniden kodlama**; birden fazla sonuç, belirsiz yayın veya ikinci başarısızlıkta `uncertain` kilidi korunur. Bu mantık mevcut `publisher_recovery.py` / `public_link_runtime.py` içinde uygulanmıştır. İlgili regresyonlar `test_film_toonzone_recovery.py` ile Facebook sonuç kimliklerinin değişmemesini ve IG-only seçimini sınar. Test geçmesi, gerçek IG Reel yayımlandığı anlamına gelmez.

**ToonZone sezon 2 kapak açığı:** 159 MP4'e karşı 48 eşleşen Drive PNG, 111 eksik. Doğru PNG varsa eski sabit kapak aynen kullanılır. Eksikse ve ToonZone rota/hak kapıları açıkken `toonzone_cover_fallback.py` o **MP4 dosyasının 1. saniye karesinden** 900×1200 PNG üretir; aynı video adını ve sezon/bölüm/part bilgisini kullanır; ilk 0,25 saniye kapağa işlenir. Başarısız FFmpeg, yanlış part veya geçersiz PNG **Meta POST öncesinde durdurulur**. Bu yedek tasarım, kullanıcının orijinal 48 kapağıyla birebir görsel eşleşme iddiası değildir. Eklenen kapaklar yalnız yerel Actions koşumunda üretilir; `toonzone-generated-part-covers` artefaktında 90 gün saklanır, Drive'daki 111 eksik dosya kendiliğinden yüklenmiş sayılmaz. Tam orijinal tasarım gerekirse özgün kapaklar ayrıca sağlanmalı. Acil kapatma: Actions repository variable `TOONZONE_AUTO_COVER_ENABLED=false`.

**Canlı kabul:** Yeni sürümün normal `schedule` koşumunda ayrı ayrı Film Instagram Part16 ve ToonZone Instagram Part3 için gerçek platform post ID ve ardından `link-state-result` / `link-incident-report` kanıtı görülmeden "bitti" yazılmaz. Eski `AUTOMATION_ENABLED` açılmaz, hak kapıları aşılmaz.


## 25 Ekim 2026 — Doğrulanmış canlı yayın, iki eski IG engeli ve bildirimler

- **Canlı gönderi kanıtı:** [Actions #40228042183](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40228042183) `dd866692b858` sürümünde commit tabanlı yetki kapısını `publish` olarak geçti. **Daily Laugh Lab `116.mp4` Facebook post ID `1428775802171798`, Instagram post ID `18159487741506813`** ile doğrulandı. Gerçek `link-state-intent` ve `link-state-result` arşivleri mevcut; `confirmed_new_posts=2`, `unverified_done_entries=0`.
- **Bildirim kanıtı:** Aynı koşum Telegram **3 server ACK**, ntfy **3 server ACK** kaydetti: iki ayrı yeni gönderi bildirimi ve birleşik hata/engel uyarısı. `delivery_failures=0`. Android telefonda görünür teslimat **UNVERIFIED**; server ACK telefonda açıldığını ispatlamaz.
- **Otomatik schedule kanıtı:** [#40228310735](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40228310735), `event=schedule`, `Publisher decision: publish`, başarıyla yürüdü; fakat `confirmed_new_posts=0`. Yeşil workflow yeni gönderi var demek değildir.
- **Kalıcı kuyruk engeli:** Mevcut 448 kayıttan 446 tanesi `done`, **iki Instagram kaydı `uncertain`** kaldı: `Yoksul_1986_Part_16.mp4` (Film) ve `S01E03_Caffeinated_Concert_Tickets_Part3.mp4` (ToonZone). Her ikisinde eski koşum `40224351466`, `Instagram ikili video aktarımı`, HTTP 400 ve **`prepublish_retry_count=1`** bulunuyor. Facebook eşleşmeleri zaten `done`; tekrar gönderme.
- **Meta konteyneri salt-okunur kanıt:** [#40228931969](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40228931969) iki eski IG konteynerinde `IN_PROGRESS` gösteriyor; `posts_sent=0`, `published=false` yalnız tanı kodunun hiç POST yapmadığını belirtir, Meta yayınının tamamlanmadığına tek başına evrensel delil değildir. Bu kontrol **yeni POST veya yeni oluşturulan video yayınlamadı**. Her iki konteyner için `FINISHED/PUBLISHED` durumundan ve uzak gerçek Reel kimliğinden bağımsız kanıt gelmeden intent temizleme veya otomatik medya yükleme yok.
- **Kod güvenliği:** `publisher_incident_report.py` artık yeni çalışmanın `uncertain_pending_reconciliation` sayacından bağımsız olarak eski `previous_unreconciled_intents` ve rota dağılımını raporlar. Böylece eski IG engelleri yeni yeşil koşumlarda görünmez olmaz. `REQUIRE_DUAL_NOTIFICATIONS=true` ile Telegram ve ntfy kanal eksikliği ayrıca hata olur, Meta POST tekrar tetiklenmez.
- **Kod regresyonu:** [CI #40228538977](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40228538977) 496 Python unittest, 57 fonksiyon assertion ve 15 JS testi başarılı. Sonraki runbook-only commit için ayrıca CI sonucu kontrol edilir.
- **ToonZone kapakları:** 48 exact Drive PNG ve 111 eksik korunuyor; yeni uygulamada açık yetki/rota koşulları altında aynı part MP4 karesinden geçici kapak üretme seçeneği var. Bu seçenek Drive'a 111 gerçek tasarım kapağı yüklendiği anlamına gelmez; fail-before-POST kontrolünü atlama.
- **Kabul kararı:** Mevcut Meta planlı yayın ve Daily Laugh iki platform canlı sonucu doğrulandı; fakat Film/ToonZone Instagram Part16/Part3 ve bütün hesapların tam günlük hedefleri **henüz tam kabul edilemez**. Güvenli ayrım: çalışan planlı motor, doğrulanmış gerçek paylaşımlar, bekleyen iki eski IG intent.



## 26 Ekim 2026 — Canlı yayın kanıtı, günlük IG hata uyarıları ve Facebook akışının ayrılması

- **Gerçek yeni gönderiler:** Planlı üretim [#40278112977](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40278112977) `event=schedule` çalışması Tarladaki Fasulye `130.mp4` için **Facebook `1127865563037111`** ve **Instagram `17864488035695158`** post ID'lerini kaydetti. Ayrı bildirimler Telegram 2 ACK ve ntfy 2 ACK döndürdü; telefon ekranında gösterim hâlâ ayrıca kanıtlanmalı.
- **Kalan Instagram engelleri:** [26 Ekim GET denetimi #40278175525](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40278175525) Film Part16 ile ToonZone Part3 konteynerlerini `IN_PROGRESS` olarak bildirdi. Bu kontrol hiçbir POST göndermedi; durumu `PUBLISHED` olarak yorumlamak veya eski kimlikleri silmek yasak. Her iki hesapta eski `uncertain` state ve yayın geçmişi korunmalı.
- **Artık günlük hatırlatma:** `previous_intent_alert_due` İstanbul takvim gününe göre aynı belirsiz intent için günde en fazla bir kez Telegram/ntfy hata uyarısı oluşturur; gün içindeki 30 dakikalık yoklamalar tekrar bildirim spam'i üretmez. Bu yalnız hata günlüğünü yeniler, Meta publish tekrarını başlatmaz. İlk gerçek uyarının kanal ACK'si yeni planlı koşumda ayrıca doğrulanmalıdır.
- **Bağımsız Facebook kurtarma:** Film/ToonZone'da IG pre-`media_publish` HTTP 400 kanıtı bulunup `prepublish_retry_count=1` ise IG önceki bölümde `uncertain` bırakılır. Sadece Facebook'un kendi dedupe ve sıra kuralları altında sonraki FB bölümü planlanabilir; IG sonraki bölümlere atlamaz. Genel `media_publish` belirsizliğinde bu geçiş yasaktır. Eksik ToonZone kapakları için ayrı mevcut fallback güvenlik kontrolü ve rights switch aynen geçerlidir.
- **CI kanıtı:** [#40278945534](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40278945534) üzerinde **500 Python unittest, 57 fonksiyon kontrolü, 15 JavaScript testi** başarılı. Üretim Film/ToonZone yeni Facebook bölümü bu commit ile henüz doğrulanmış sayılmaz.
- **24 saatlik takip:** Salt-okunur `ig_container_status_diagnostic.yml` günlük `06:18 UTC / 09:18 TRT` cron kontrolü eklendi (GitHub schedule gecikebilir); otomatik kontrol hiçbir medya upload, Graph write veya eski intent sıfırlaması yapmaz.


## 26 Ekim 2026 — Gerçek hata bildiriminin doğrulanması ve yayımlanmayan tanı testleri

- **10:00 TRT gerçek hata:** [Üretim run #40281812561](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40281812561) yalnız Film Part16 ve ToonZone Part3 IG kurtarma girişimlerini denedi; her ikisi de 180 saniye 720x1280 96 kbps AAC kaynağıyla ikili rupload aşamasında, tüm baytların aktarılmasından sonra `HTTP 400 ProcessingFailedError` aldı. `media_publish` çağrısına ulaşılmadı, yeni post ID yok. Telegram ve ntfy sunucu ACK'leri birer gerçek hata uyarısı için dönmüş; bunlar sahte uyarı değildi.
- **15 saniye karşı testi başarılı:** [Unpublished diagnostic run #40288506373](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40288506373) Film ve ToonZone exact MP4 içinden üretilen kısa video için `rupload HTTP 200`, ardından `FINISHED_NOT_PUBLISHED` döndürdü. **İki yeni IG medya konteyneri yayımlanmadı**; gönderi sayısı sıfır. Bağlı Page/IG kimliği, erişim ve temel rupload akışı çalışıyor.
- **Anlamı:** Sorun büyük/uzun tam video aktarımı veya full video medya yapısıyla bağlantılı; sadece AAC bitrate sorunu olduğu iddiası doğru değil. Kısa klibin başarısı 180 saniyelik orijinalin başarılı yayımlanacağını garanti etmez.
- **Bildirimin netliği:** Yeniden görülen aynı eski `previous_intent_hold/unreconciled_previous_intent` kayıtları artık yalnız günlük düşük öncelikli ℹ️ hatırlatma; yeni gerçek Meta POST hatası yüksek öncelikli 🚨 olarak kalır. Tüm hatalar yapılandırılmış GitHub arşivinde tutulur, eski FB post ID'leri değiştirilmez. [CI #40288446780](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40288446780) 520 Python, 57 fonksiyon, 15 JS testini geçti.
- **Tam uzunlukta düşük hacimli araştırma:** `ig_full_compact_uploadonly_diagnostic.py` ve `.github/workflows/ig_full_compact_uploadonly.yml` iki tam 180 saniyelik videoyu 360x640, H.264 Main, AAC-LC 112 kbps ile ayrıca **upload-only** doğrular; `media_publish` çağırmaz. Tek kullanımlık commit `f256f25f7f9e`; sonuç başarılı run ve `FINISHED_NOT_PUBLISHED` artifaktı görülmeden kabul edilmez. Yalnız dosyalar küçülürse Meta'nın aynı HTTP 400'ü verip vermediğine bakılır; sonuca göre üretim yayın yöntemine karar verilir.


## 26 Ekim 2026 — Film/ToonZone kesin yayın çözümü ve test logu ayrımı

- **Film Mağarası Instagram geri döndü:** [canlı üretim #40290059140](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40290059140) dosya `Yoksul_1986_Part_16.mp4`, gerçek Instagram post ID **17962599149999265**. Video 180 saniye boyunca test edilmiş 360x640 / H.264 Main / AAC-LC düşük boyutlu profille aktarıldı; IG binary HTTP 200, başarılı `media_publish`, doğrulanmış post ID. Önceki başarısız 720p kurtarma videoları ile karıştırma.
- **ToonZone Instagram geri döndü:** Aynı [#40290059140](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40290059140) dosya `S01E03_Caffeinated_Concert_Tickets_Part3.mp4`, gerçek IG post ID **18350065531269318**. Eski belirsiz kuyruğun sonu gerçek `post_id` ile doğrulandı. Telegram ve ntfy kanallarından **2'şer server ACK** alındı; telefonda fiziksel teslimat ayrıca doğrulanmadı.
- **Sonraki planlı çalışma:** [#40291610942](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40291610942) `Gönle Düşen` Facebook `116.mp4` post ID **2370030600201575** yayımladı; GitHub çalışma sonucu başarılı; Telegram ve ntfy **1'er server ACK** aldı; olay sayısı sıfır.
- **Gerçek regresyon nedeni:** 24–25 Ekim'de production `Verify...` adımı `test_public_link_runtime.py` ünittestlerinden gelen kasıtlı örnek `HELD failures: ...`, sahte `post_id`, `HTTP 400` satırlarını canlı Meta hata logu ile aynı stdout üzerinde gösteriyordu. Bu örnekler canlı Meta hatası değildi. 26 Ekim'deki değişiklik `test_public_link_runtime.py` içinde yalnız import edilen **mock runtime** nesnesinin `print` fonksiyonunu susturur; production runtime stdout'u ve gerçek hata olay kayıtları aynen çalışır. [CI #40294942353](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40294942353): **528 Python testi, 57 ek kontrol, 15 JavaScript testi PASS**.
- **Kritik workflow değişikliği geri alındı:** Başarılı test stdout'unu YAML üzerinden süzmek için yapılan değişiklik malformed/zero-job push hatası oluşturdu; doğrulanmış orijinal `.github/workflows/public_link_schedule.yml` blob SHA **0f3805e7f1ecb6044288a917a20880df040073b7** birebir restore edildi ([commit](https://github.com/emirhankaya985-cloud/auto-video-publisher/commit/e34008666c3174e732d6c0001c52662643a7174f)). Yalnız yeşil CI prod runtime kanıtı değildir; sıradaki gerçek planlı yayınların `verify`, `plan`, `publish`, `notify` adımları ayrıca kontrol edilmelidir.
- **Kalan açık konu:** ToonZone'un 159 MP4'üne karşı Drive'da eşleşen **48 gerçek kapak ve 111 eksik özel kapak** var; alternatif yerel kapak oluşması bunların Drive'da tamamlandığı anlamına gelmez. Daily Laugh Lab'da ayrı önceki Instagram `ProcessingFailedError` örnekleri bulunmaktadır; ilk başarısız aktarımdan sonra sadece kanıtlı pre-publish senaryoda mevcut kontrollü alternatif medya hazırlama tekrarına izin verilir. Çift paylaşım için kör POST tekrarını asla açma.

Yeni gerçek olayların sebeplerini, kaynak run linkini ve fix doğrulamasını önceki kayıtları silmeden bu dosyanın sonuna ekle.

## 26 October 2026 — RESOLVED: Film Part 16 + ToonZone Part 3 Instagram blockers

**Resolution (real Meta POSTs, verified IDs):** GitHub Actions [#40290059140](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40290059140) published Film Mağarası `Yoksul_1986_Part_16.mp4` Instagram post ID `17962599149999265` and ToonZone `S01E03_Caffeinated_Concert_Tickets_Part3.mp4` Instagram post ID `18350065531269318`. `confirmed_new_posts=2`, `uncertain_pending_reconciliation=0`, `previous_unreconciled_intents=0`, `error_event_count=0`; both Telegram and ntfy providers returned 2 server ACKs. Server ACK does not independently prove phone UI delivery.

**Root-cause isolation:** 720p/96k AAC 180s attempts returned HTTP 400 `ProcessingFailedError` at rupload (run #40281812561). Independent 15s tests succeeded and did not publish ([#40288506373](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40288506373)). Full 180s **360x640 compact** H264 Main AAC-LC 112k upload-only checks also succeeded (HTTP200, FINISHED, no media_publish) on [#40289310065](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40289310065). The one-time production compact release then published both successfully. The earlier 720p/large-file rejection mechanism was not independently proven, but lower-bandwidth compact encoding resolved this particular case.

**Post-fix schedule proof:** [#40317296332](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40317296332) on 26 Oct at ~14:46 TRT published Film Mağarası `Yoksul_1986_Part_19.mp4` to Facebook, post ID `890905460678274`; confirmed_new_posts=1, error_event_count=0, unresolved old intents=0, Telegram ACK=1, ntfy ACK=1. Normal scheduled engine still functions after the exact one-time rescue.

**Current acceptance:** Film Part16 and ToonZone Part3 **Instagram publishing incidents are RESOLVED**, and original Facebook published IDs were not replayed. The above is evidence for these specific posts and runs only, not a promise that every future Meta request will succeed. Notifications now differentiate known recurring holds (daily information) from fresh API failures (urgent).

**Automated CI verification:** [#40299351074](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40299351074) passed 528 Python unittest cases, 57 function assertions and 15 Node tests. Existing permanent evidence issue [#11](https://github.com/emirhankaya985-cloud/auto-video-publisher/issues/11) remains the latest verified dashboard.


## 27 Ekim 2026 — İki izlenen rotanın yayın sonrası hedef kontrolü

- [27 Ekim 10:25 TRT gerçek Meta yayın çalışması #40467048102](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40467048102): toplam 5 gerçek post ID, 0 hata olayı. Daily Laugh Lab ve ToonZone `NOT DUE` (slot başlamamış); yeşil job onların yayın yaptığı anlamına gelmez.
- `tracked_meta_routes.yml` ToonZone için 13:40 TRT'de mevcut günün 4 Facebook + 4 Instagram video hedefini; Daily Laugh Lab için 08:40 TRT'de önceki New York gününün 8+8 video hedefini *salt okunur* Meta geçmişinden ölçer. Yerel saat / yaz-kış DST dönüşümü doğrulanır.
- Eksik video yalnız **uyarı** üretir; kör Meta POST, ledger sıfırlama, Drive'a yazma veya kapalı/yetkisiz rotayı etkinleştirme yoktur. Hak/route devre dışıysa yanlış alarm üretmez.
- GitHub Actions'ın `success` sonucunu değil gerçek platformdaki video kimliklerini sayar. Meta GET erişimi başarısızsa `unknown` raporlar; asla sahte yeşil sonuç yazmaz. Telegram ve ntfy yalnız hedef açığı veya belirsizlik halinde sunucu onayıyla uyarılır; cihaz teslimatı ayrıca doğrulanamaz.
- Bu monitorün yeşil CI testi gelecekteki planlı yayın saatleri geçmeden Daily Laugh/ToonZone için canlı kabul yerine geçmez.

## 27 Ekim 2026 — Graph geçmiş okuma kurtarmasının güçlendirilmesi

- Güncel planlı [#40520730569](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40520730569) gerçek incident özeti: `confirmed_new_posts=3`, `error_event_count=0`, `uncertain_pending_reconciliation=0`, `previous_unreconciled_intents=0`. Bu, aşağıdaki yeni kodun canlı kabulü değildir.
- Kod incelemesi: `read_with_retry` yalnız HTTP 429/5xx üzerinden tekrar ediyordu; yukarıdaki politikada yer alan Graph 4/17/32/613 hata kodları HTTP 400 gövdesinde geldiğinde uygulanmıyordu. Şimdi yalnız açık `graph_read=True` geçmiş GET çağrısında bu dört sayısal kod için toplam üç okuma ve 1/2 saniye bekleme uygulanır. Son yanıt başarısızsa geçmiş kapısı kapalı kalır. GitHub GET veya Meta upload/publish POST yolu bu opt-in'i kullanmaz.
- Bozuk JSON şekli, HTTP 200 içinde `error` veya sayısal olmayan hata kodu geçmişte boş başarı sayılmaz; güvenli RuntimeError ile yayın durur. Ham hata gövdesi/token loglanmaz. Tüketilen ara retry yanıtları kapatılır; son yanıt çağırana bırakılır.
- Regresyonlar: Graph throttling sonrası başarı, üç denemede tükenme, normal HTTP 400/izin hatasını tekrar etmeme, yanlış JSON şekli ve hata gövdesini gizleme. Önceki Instagram kodlama profilleri ve belirsiz POST kilitleri korunur.
- Doğrulama: yerel 72 hedefli kurtarma/runtime testi geçti; tam paket sonucu PR açıklamasında kayıtlıdır. Yeni sürümle gerçek planlı çalışma henüz doğrulanmadı; test için yayın veya bildirim tetiklenmedi.
- Geri alma: ilgili commit'i geri al; intent/result arşivlerini silme ve legacy `AUTOMATION_ENABLED` anahtarını açma.

## 27 Ekim 2026 — Tam akış kod incelemesi ve sessiz yayın açıkları

[Kapsam, bulgular, testler ve işletim sınırları](CODE_RELIABILITY_AUDIT_2026-10-27.md).
135 Python dosyasının AST taraması ve 36 workflow'un YAML kontrolü yanında
aktif yayın yolu elle incelendi. Hesap keşfi ve IG container durum GET'lerine
sınırlı retry eklendi; hesap kaynaklı ağ/tarih hatası diğer hesapların planını
kesmez. Sayfalı geçmiş ve ledger aynı post ID'sini günlük kotaya iki kez saymaz.
Facebook açık `success:false` yanıtı başarılı gönderi olmaz. Hedefi eksik ama
uygun videosu kalmayan rota günde bir kez hata jurnali üzerinden bildirilir;
eski belirsiz intent hatırlatması çoğaltılmaz. Kapak FFmpeg beklemesi sınırlıdır.
`media_publish` belirsizliğinde otomatik POST tekrarı, geçmiş silme veya sıra
atlama eklenmedi. 564 unittest ve 57 ek kontrol yerelde geçti; 15 Node testi
başarılı. Yeni commit için GitHub CI ve sonraki gerçek schedule kabulü ayrı
izlenir; bu inceleme test amaçlı gerçek yayın tetiklemedi.

## 27 Ekim 2026 — Hesap bazlı günlük izlenme N/A kök nedeni

- Gerçek kanıt: [26 Ekim günlük rapor #40403278376](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40403278376) 27 Ekim **00:18 TRT**'de başladı, 00:25 civarında tamamlandı. Altı hesap ailesinde Facebook/Instagram erişilebilir video toplamları alınmıştı; günlük artışların tümü gece yarısı sonrasındaki ölçüm nedeniyle bilinçli olarak N/A idi. Bu run'da N/A'nın nedeni API erişim reddi değildi.
- Eski `cc7f2e7` run'ı daha sonraki 23:15 TRT cron düzeltmesini içermiyordu. Güncel `daily_stats.yml` `15 20 * * *` (23:15 TRT) çalışır; GitHub gecikmesi yine mümkündür. Bu saatin bir sonraki canlı raporunun sonucu ayrıca kontrol edilmelidir.
- Telefon özetinde ölçüm zamanı ve gecikmeli gün açıklaması artık korunur. Hesap/platform/genel günlük satırlar gecikmeyi `N/A (gecikmeli ölçüm)` olarak ayırır; gerçek API başarısızlığı `Veri alınamadı`, ilk baseline yokluğu ayrı kalır. Genel izlenmeler gecikmede de korunur; geçmişe sahte günlük sayı yazılmaz.
- Analitik GET okumalarına sınırlı 429/5xx/Graph kota retry eklendi; yetki hatası veya bozuk veri başarıya dönüştürülmez. Bildirim POST'u veya video yayını bu kontrol için tetiklenmedi.
- Günlük fark, erişilebilir videoların önceki başarılı gün sonu snapshot'ına göre sayaç farkıdır; tam takvim günü için doğrudan platform Insights metriği veya benzersiz izleyici ölçümü iddiası değildir. Genel toplam da erişilebilir video sayaçlarıdır.

## 27 Ekim 2026 — Telegram günlük/haftalık karşılaştırma tabloları

- Kullanıcı açıkça hesap bazlı 1 gün / 7 gün önceye göre yüzde, ayrıntılı tablo ve Telegram teslimi istedi. `views_comparison.py` mevcut arşivden kesin gün tabanlarını kullanır; ilave Meta yetkisi veya video yayını gerekmez.
- Üç Telegram HTML parçası: dünkü/şimdiki toplam, artış ve yüzde; 7 gün önceki toplam/artış/yüzde; ilk üç büyüyen hesap, hesap payları ve platform ayrıntısı. Ufak pozitif yüzdeler sıfırmış gibi yuvarlanmaz. Her parça gönderilmeden önce boyut sınırı kontrol edilir, etiketler HTML-escape edilir.
- Eksik platform/7 günlük kayıt, değişen video kapsamı, azalan sayaç ve sıfır tabanda sahte yüzde yoktur. Haftalık veri eksikse arşiv başlangıcı ve açık neden gösterilir. Yüzde toplam video sayacının büyümesidir, günlük izlenme hızlarının değişimi değildir.
- Ayrıntılı Telegram gönderimi kısmen başarısızsa iş başarısız olur; önceden kabul edilen parça tekrar gönderilmez. ntfy kompakt özeti korunur. JSON hesaplama kanıtı ayrı 90 günlük artifact'a kaydedilir.
- Yerel regresyon ve aynı head SHA'daki CI sonucu PR'da tutulur; gerçek üç Telegram server ACK görülmeden teslim edildi denmez. Kullanıcının açık isteğiyle yeni rapor gönderimi yapılacaktır. Kod/test başarısı Android görünür teslimatı değildir.

**Canlı teslim kanıtı:** [27 Ekim rapor #40533771493](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40533771493), ölçüm başlangıcı 18:43 TRT, gönderim yaklaşık 18:47 TRT: Telegram `telegram_report_parts=3`, `server_acks=3`; ntfy HTTP 200. `account-views-comparison` JSON artifact başarıyla yüklendi. Altı hesapta günlük yüzdeler hesaplandı; toplam 49.012.813, önceki rapor tabanına göre +3.268 / +%0,0067. Arşivin ilk günü 25 Ekim olduğundan 20 Ekim haftalık tabanı yok; bütün haftalık yüzdeler açıkça N/A gösterildi. Haftalık hesap için gerçek 7 gün önceki snapshot gerekir. Android ekranında görünür teslim ayrıca doğrulanmadı. Bu run hiçbir video yayını tetiklemedi.


## 28 Ekim 2026 — Sırasız kuyruklarda eski açıklama çakışması

- Gerçek [#40653567037](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40653567037) Gönle Düşen ve Filmmagrasi için eski açıklama eşleşmesinde durdu; aynı koşum Film Instagram Part26'yı yayımladı. Başarılı job bütün rotaların tamamlandığı anlamına gelmez.
- Gönle Düşen ve sırasız mizah kaynaklarında ledger kaydı olmayan, eski açıklamayla çakışan aday her iki platform için atlanır; sıradaki temiz aday aranır. Eski aday done yapılmaz, post ID uydurulmaz, metni değiştirilip yeniden gönderilmez.
- Gerçek uncertain/intent kayıtları ve Film/ToonZone bölüm sırası korunur. Filmmagrasi'nin eski kaynağı bu değişiklikle otomatik uzlaştırılmış sayılmaz; güvenilir dosya/platform kimliği kanıtı gerekir.
- Regresyonlar tekil/çoklu çakışma, tek platform çakışmasında tüm klibi bekletme, uncertain kilidi ve Film sıra korumasını sınar. Kod/test sonucu canlı yayın kabulü değildir.
- Geri alma: bu commit'i geri al; intent/result arşivlerini silme. Bu çalışma test yayını veya bildirim tetiklemez.


## 28 Ekim 2026 — Onaylı konu etiket havuzları

- Facebook üst sınırı 20, Instagram üst sınırı 5 hashtag. Bunlar doldurulacak kota değildir; yalnız hesap teması ve açık dosya/TXT ipuçlarıyla ilgili etiketler seçilir. Etiketlerin izlenmeyi artırdığı veya 20 Facebook etiketinin en iyi sonuç olduğu iddia edilmez.
- Daily Laugh İngilizce etiketler kullanır. Oyuncu/karakter etiketi için açık isim gerekir; kullanıcı adı ve yeni kişi etiketi tahmin edilmez. Mevcut video-specific kişi kuralları korunur.
- Eski TXT ile geçmiş eşleştirmesi önce yapılır. Yalnız yeni intent için etiketli açıklama oluşturulur; tam metin ve hash birlikte kaydedilir. Ready yeniden denemesi kayıtlı metni aynen kullanır; mevcut intent/uncertain metinleri politika değişikliğiyle yeniden yazılmaz. Eski sosyal medya gönderileri değiştirilmez.
- Caption uzunluğu sınırında ana metin kesilmez; isteğe bağlı etiketler azaltılır. Desteklenmeyen rota değiştirilmez. Canlı test yayını ve bildirim tetiklenmez. Geri alma: ilgili commit'i geri al; state/intent arşivini koru.

## 28 Ekim 2026 — Yayın adımı tekrarına karşı ledger doğrulaması

- Önceki kuyruk düzeltmesinin canlı kanıtı: [#40667349940](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40667349940) Gönle Düşen `125.mp4` Facebook `2037241066936803` dahil 4 post, 0 hata yayımladı. Filmmagrasi kaynak kimliği engeli sürüyor. Bu kanıt aşağıdaki yeni guard'ın canlı kabulü değildir.
- İnceleme bulgusu: `publish()` plan dosyasını kullanırken ledger'da zaten done olmuş platformları atlamıyordu. Aynı yayın adımının yerel planla yeniden çağrılması tekrar POST üretebilirdi; bu turda canlı çift paylaşım gözlenmiş olduğu iddia edilmez.
- Yeni preflight indirmenin öncesinde ledger kaydını kontrol eder. Kimliği doğrulanmış done atlanır; ready/uncertain, eksik intent, değişen kayıtlı açıklama/hash/dosya veya başka run kimliği bekletilir. Tekrarlanan platform girdileri kabul edilmez. Eski içe aktarım kayıtlarında bulunmayan isteğe bağlı kimlik alanları uydurulmaz; yeni planner alanlarının mevcut bağları doğrulanır.
- Meta POST'tan önce yerel ledger uncertain olarak kaydedilir. Kesinti sonrasında aynı publish çağrısı kör POST yinelemez. Normal planlama, geçmişi okuyup mevcut kontrollü kurtarma kurallarıyla yeni intent hazırlayabilir; bu koruma yeni retry yetkisi vermez.
- 594 Python testi, 57 ek kontrol, 15 Node testi yerelde başarılı. Yeni senaryolar: aynı planı iki kez çağırma, POST sırasında kesinti, yanlış caption/dosya/run, belirsiz durum ve kısmi platform başarısı. Tüm dış çağrılar mock; gerçek yayın/bildirim tetiklenmedi.
- Geri alma: ilgili commit'i geri al, state/intent/result arşivlerini koru. Yeşil CI yeni sürümün canlı yayın kanıtı değildir.
## 28 Ekim 2026 — Filmmagrasi aynı Part 3'ün iki kaynak kopyasında bekliyor

- [#40667349940](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40667349940) Gönle Düşen Facebook `125.mp4` ve Film Facebook yeni bölümünü yayımladı; Filmmagrasi açıklama eşleşmesinde bekledi. Aynı gün [#40659932893](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40659932893) Gönle `122.mp4` Facebook/Instagram post ID'lerini doğruladı; Gönle'nin eski kilidi açılmıştır.
- Filmmagrasi result ledger'ında `Avanak_Apti_Part_3 (1).mp4` kaynak `1UC7f7b1ouJasQ1IPTso0M1o0YG6Z4t08`, 27 Ekim [#40494529077](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40494529077) post ID `2174049343505147` ile done. Aynı klasördeki `Avanak_Apti_Part_3.mp4` kaynak `1jCESyKUFPIVisisJpe0LjXlkMSCvQBEy` başka ID ile aynı içeriği temsil ediyor.
- Salt-okunur iki gerçek MP4 indirmesi: her ikisi **15.549.424 bayt**, SHA-256 **69f3c5bc6ee730742d7a89e16138c8a2427d4479a3f35dd619616a33b5e3b829**. Dosya adına/aynı açıklamaya bakarak yapılmış bir çıkarım değildir.
- Yeni planlayıcı yalnız aynı film/part kopyası için mevcut done kaynak ID'sini, tam uzak post ID/açıklama/yayın gününü ve iki MP4'ün doğrulanmış tam byte hash'ini birlikte şart koşar. Herhangi bir kanıt yoksa eski hold korunur. Farklı byte içeren iki part dosyası asla atlanmaz. Kaynak veya platforma yazım yapılmaz.
- Kanıtlı kopya aynı eski post'a alias olur; orijinal `run_id` ve gün korunur. Günlük kota post ID'yi bir kez sayar; yeni gönderi/bildirim sayılmaz. Böylece tekrar Part 3 upload etmek yerine sıradaki Part 4 planlanabilir. Gerçek uncertain/intent, hak kapıları ve bölüm sırası değişmez.
- Yerel testler byte eşitliği/farkı, uzak ID/tarih/açıklama yokluğu, uncertain kilidi, geçersiz medya, tek quota sayımı ve POST yapmadan Part 4 planlanmasını sınar. Kod/CI, sonraki planlı Part 4 gönderi kimliği olmadan canlı yayın kabulü değildir.

## 28 Ekim 2026 — NVIDIA günlük yorum ve Telegram sohbet hazırlığı

- Kullanıcı NVIDIA API anahtarını kendisi ayarlayacak. Varsayılan model NVIDIA
  kataloğundaki `openai/gpt-oss-120b`; model değişkenle değiştirilebilir.
- `NVIDIA_AI_ENABLED=true` ve secret olmadan model çağrısı yok. Normal üç
  Telegram tablosu gönderildikten sonra ek AI özeti bağımsız çalışır. Model
  hatası tabloların yeniden gönderilmesine veya yayın retry'ına yol açmaz.
- Yeni owner/chat kontrollü long-poll worker sadece sabit production main
  rapor artifact'larını okur. Son ölçüm tarihi korunur, yayın kanıtı olmayan
  bağlamdan yayın başarısı üretilmemesi istenir. Hiçbir yayın aracı verilmez.
- SQLite offset API'den önce kalıcıdır; belirsiz Telegram teslimatı kör
  yinelemeye alınmaz. Aktif webhook silinmez. Tek sürekli süreç ve kalıcı
  disk gerekir; herhangi bir ücretli servis oluşturulmadı.
- Kurulum: `docs/TELEGRAM_NVIDIA_ASSISTANT.md`. Anahtar, izinli kullanıcı ID'si
  ve worker host'u eksik olduğundan canlı sohbet kabulü henüz yoktur.
- Mock testler: yetkisiz kullanıcı/chat, replay/restart, belirsiz send,
  API hata redaksiyonu, bounded conversation, reset, eski ölçüm tarihi,
  sabit repo/main kaynağı ve ZIP üye doğrulaması. Gerçek AI/Telegram/Meta
  mesajı bu testler için gönderilmedi. Kapatma: feature flag false + worker stop.

## 28 Ekim 2026 — Kullanıcının seçtiği Nemotron modeline uyum

- Kullanıcının NVIDIA API örneği tam model ID'sini doğruladı:
  `nvidia/nemotron-3.5-super-vl-120b-a12b`. Önceki gpt-oss varsayımı yerine
  uygulama ve gece workflow varsayılanı güncellendi; NVIDIA_MODEL override korunur.
- REST çağrısında SDK extra_body alanının içeriği doğrudan top-level'e verilir.
  Nemotron metin ayarları temperature=1/top_p=0.95, enable_thinking=false;
  reasoning metni, görsel örneği veya tool izni gönderilmez. Diğer model
  override'ına Nemotron'a özel alanlar eklenmez. API retry yoktur.
- API anahtarının eklendiği henüz doğrulanmadı; canlı model yanıtı veya
  sürekli Telegram sohbeti başarılı diye raporlanamaz. Feature flag kapısı korunur.

## 29 Ekim 2026 — Kısa Reels ilk deneme medya profili

- [#40906373670](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40906373670): Tarladaki `167.mp4` IG binary upload tüm 15.101.641 bayt sonrası HTTP400 ProcessingFailedError verdi. Facebook post ID `2132945614262874` dahil 6 gerçek paylaşım tamamlandı; yalnız IG ready ve retry_count=1. Meta'nın iç ret nedeni kanıtlanmadı; bitrate tek kesin neden olarak sunulmaz.
- Önceki 1080p/4Mbps ilk normalizasyonu kısa Tarladaki/Penguen/Daily Laugh rotalarında 720x1280 H264 Main 2.5Mbps / AAC-LC 112k ile değiştirildi. Kaynak süre kesilmez; ilk denemede zorunlu re-encode ve tam decode kontrolü yapılır. Film, ToonZone ve Gönle profilleri değişmedi. Sonraki kontrollü 360p ve 720p/1.8Mbps kurtarma profilleri ayrı kalır; POST retry sayısı genişletilmedi.
- 622 Python testi, 57 fonksiyon kontrolü ve 15 Node testi geçti. Gerçek yerel FFmpeg sentetik 4s 1080p kaynağı 720x1280, 4.083719s, 1.310.466 bayta dönüştürdü; metadata, atom ve full-decode kontrolleri başarılı. Bu Meta upload/publish kanıtı değildir; test için dış yayın/bildirim gönderilmedi.
- [#40864640363](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40864640363) ToonZone 3/4 uyarısından sonra #40906373670 uzak geçmişi FB4/IG4 ve daily target complete kaydetti. Eski alarm güncel açık arıza olarak sayılmaz.
- 167.mp4 gerçek IG post ID'si sonraki normal planlı koşumda doğrulanmalı. Başarılı FB postu yeniden gönderilmez, intent/state silinmez. Geri alma: ilgili commit'i geri al; mevcut kurtarma sayacı ve sonuç arşivlerini koru.

## 29 Ekim 2026 — 167.mp4 kurtarma kanıtı ve film etiketi ayrımı

- [#40916153838](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40916153838), güncel 1ebb8de sürümü: 167.mp4 Instagram post ID `18010043736003632`, 19:57 TRT; toplam 5 post, 0 hata, 0 eski/yeni belirsiz intent. Telegram/ntfy 5'er server ACK. Önceki Facebook 167 sonucu tekrar edilmedi.
- Aynı result ledger'ındaki publish_caption alanları etiketlerin gerçek yeni gönderilerde kullanıldığını doğruluyor: Tarladaki IG5, Daily Laugh FB9/IG5. Ancak Avanak Apti etiketlerine genel Yeşilçam kuralı yanlışlıkla Yoksul/Yoksul1986 da ekliyordu.
- Film adı kuralı tür kuralından ayrıldı: Yoksul etiketi yalnız Yoksul kaynak dosya adıyla eşleşir; eski TXT/hashtagler başka filmde bunu tetiklemez. Kaydedilmiş intent açıklamaları değiştirilmez; yeni intentler düzeltilmiş seçimi kullanır. Eski canlı gönderilere bu turda yazım yapılmadı.
- Son büyüme raporu #40766656150, 28 Ekim 23:49 TRT ölçümü: erişilebilir video sayaç toplamı 49.020.699; önceki snapshot'a göre +5.868. Bu takipçi artışı, etiket kaynaklı nedensel etki veya 29 Ekim anlık ölçümü değildir.
- Regresyonlar genel Yeşilçam ve eski yanlış etiketlerin başka filme başlık taşımamasını ve doğru Yoksul dosyasının kendi etiketlerini korumasını sınar. Geri alma: ilgili commit'i geri al; yayın state arşivini koru.

## 30 Ekim 2026 — Avanak Apti Part 10 ve büyüyen kurtarma çıktısı

- [11:04 TRT sonuç #41023661811](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41023661811): Film Instagram `Avanak_Apti_Part_10 (1).mp4` binary upload HTTP 400 ProcessingFailedError. Aynı koşumun Facebook Part14 postu `1827066738315496` ayrı videodur; Part10 IG başarısı olarak yorumlanmaz.
- [11:57 TRT ikinci sonuç #41029613650](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41029613650): 7.058.390 baytlık 360x640 kaynak, alternatif profil yolunda genel 1080p/4M kodlayıcıya düşerek 94.864.825 bayt oldu ve yeniden binary aşamasında reddedildi. Meta'nın iç ret nedeni kesinleşmedi; boyut artışının tek neden olduğu iddia edilmez. Son result artifact `12964848855` içinde tek açık uncertain kayıt bu Part10'dur, retry_count=1. Sağlık watchdog #41033231897 iki ardışık hata için ayrıca alarm verdi; bu üçüncü bağımsız medya arızası değildir.
- Film/ToonZone alternatif kodlaması artık mevcut kontrollü 720x1280/1.8Mbps, AAC-LC 96k profiline yönlenir. Süre kesilmez. İlk compact profili, eski exact V4 izinleri ve diğer hesapların retry sınırları korunur.
- Kullanıcının düzeltme yetkisiyle yalnız tam kaynak ID/ad, film+Instagram, run `41029613650`, retry_count=1 ve kesin binary HTTP400 kaydı için bir ek profil açılır. Planner önce Meta geçmişini ve aynı caption hash'ini doğrular; okunamayan geçmiş, değişen açıklama, farklı dosya/run, media_publish veya timeout buna uygun değildir. Başarısız yeni deneme count=2/uncertain kalır; bu kapı tekrar açılmaz. Facebook done kayıtları korunur, state sıfırlanmaz.
- Yerel doğrulama: 627 Python testi, 57 fonksiyon kontrolü ve 15 Node testi başarılı. 180 saniyelik sentetik gerçek FFmpeg testi: 720x1280, 180.067771 saniye, 42.936.417 bayt, ses 96.274bps; atom/metadata ve tam decode geçti. Bunlar Meta upload/publish kanıtı değildir.
- Canlı kabul: yeni main sürümünün normal schedule koşumunda Part10 için gerçek IG post ID ve result ledger görülmeli. Bu kaydın eklendiği anda canlı kurtarma doğrulanmadı. Sonraki bölümlerin sırası atlanmaz; sağlık alarmı sessize alınmaz. Geri alma: bu değişikliği revert et, bütün intent/result arşivlerini koru.

## 30 Ekim 2026 — Hesaplar arası etkileşim kodu (canlı varsayılan kapalı)

- Kullanıcının açık isteğiyle Facebook/Instagram beğenileri ve Facebook bağlantı paylaşımı için ayrı `meta_cross_engagement.py` ve `meta_cross_engagement.yml` eklendi. Resmi Meta User Likes belgesi ve 22 Nisan changelog'u Instagram `POST /{ig-user-id}/likes`, User tokenı ve `instagram_manage_engagement` iznini doğruluyor. Bu nedenle eski "Instagram beğenisi API'de yok" varsayımı kullanılmaz.
- Kaydetme ve Instagram yerel repost için doğrulanmış yazma API'si bulunmadı. Bu istekler açık unsupported raporudur; yeniden video yükleme veya private API ile taklit edilmez. Facebook paylaşımı gerçek video permalink'inin yeni bir bağlantı gönderisidir; sayaç artışı garantisi değildir.
- Yalnız tamamlanmış doğru repo/main yayın run'ının son 24 saatteki yeni native post ID'leri işlenir. Aliases/reconciliation ve etkileşimle yaratılmış paylaşımlar yeni kaynak sayılmaz. Aktör Page/User/IG kimlikleri ve canlı izin listeleri doğrulanır; mevcut rota duraklatma/hak onayı kapıları uygulanır. Secret'lar plan/ledger/rapora yazılmaz.
- Ayrı intent/result artifact'ları ve global concurrency çift işlemi engeller. İlk POST öncesi bütün intent kaydedilir; timeout/5xx/kesintide kör POST tekrarı yoktur. Başarılı video yayın state'ine dokunulmaz ve etkileşim arızası video yayınını yeniden tetiklemez.
- Varsayılan `dry_run`; canlı etkinleştirme değişkeni bu kod eklenirken açılmaz. Gerekli yeni IG izni mevcut tokenlarda doğrulanmış değildir. Mock test veya plan çıktısı canlı beğeni/kaydetme/paylaşım kanıtı sayılmaz.
- Yapılandırma, kesin API sınırları, geri alma ve birincil kaynaklar: `docs/META_CROSS_ENGAGEMENT.md`. Kapatma: `META_CROSS_ENGAGEMENT_ENABLED=false`; geçmiş intent/result kayıtlarını koru.
- Yerel kabul: 648 Python testi (21 yeni etkileşim senaryosu dahil), 57 fonksiyon kontrolü ve 15 Node testi başarılı. Workflow intent-before-execute sırası, main checkout, read-only GitHub yetkileri ve varsayılan kapalı bayrak ayrıca kontrol edildi. Canlı etkileşim POST'u gönderilmedi.

## 30 Ekim 2026 — 13:00 TRT günlük etkileşim ve ilk canlı batch yetkisi

- Kullanıcı ilk batch'in şimdi çalışmasını ve ardından her gün 13:00 TRT otomatik yürütmeyi açıkça istedi. Workflow `0 10 * * *` UTC cron'una taşındı; eski publisher-workflow_run tetikleyicisi kaldırıldı. GitHub cron başlangıcı gecikebilir. Yalnız tarihli başlangıç marker'ı ilk main push batch'ini tetikler; ilgisiz push'lar tetiklemez.
- Artık yalnız son run'ın birkaç videosu değil, en yeni tamamlanan yayın state'indeki son 24 saatin bütün doğrulanmış native postları işlenir. Her kaynak run'ın repo/main/iş akışı/zaman/sonuç kanıtı denetlenir; aliases/reconciliation ve eski run'lar seçilmez. Önceki bağımsız etkileşim ledger'ı tekrarları engeller.
- Kullanıcı isteğiyle workflow default enable/apply açıldı; `META_CROSS_ENGAGEMENT_ENABLED=false` kill switch'i korunur. UI manuel preview varsayılanı dry_run kalır. Secret veya OAuth izin değişikliği yapılmadı.
- Gerçek read-only kanıt: [önizleme #41044005387](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41044005387), 13 doğrulanmış aktör, 18 Facebook repost adayı, 21 FB like ve 6 IG like isteği `missing_permission`. `pages_manage_engagement` ve `instagram_manage_engagement` izinleri tokenlarda yok. Bu eksiklik aktivasyonla aşılamaz. Kaydetme ve Instagram repost hâlâ unsupported.
- Sonraki canlı batch sonucu gerçek share_post_id/API alındılarıyla ayrıca kontrol edilecek; bu belge ilk canlı batch tamamlandı iddiası değildir. Video yayın state'i ve başarılı videolar değiştirilmez.

## 30 Ekim 2026 — İlk etkileşim batch'inde Video/PagePost alan ayrımı

- [İlk canlı çalışma #41044986946](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41044986946): son 24 saatte 64 native post, 13 doğrulanmış aktör, 210 Facebook bağlantı paylaşımı planı. 245 FB like ve 174 IG like isteği eksik izinle engellendi. Bütün 210 paylaşım POST öncesi kaynak denetiminde durdu; gerçek paylaşım sayısı 0. Job success etkileşim başarısı değildir.
- Kaynak ledger Facebook Video ID tutar. Eski kaynak kontrolü belgelenmiş Video alanları dışında PagePost `permalink_url` alanını aynı istekte istiyordu. İlk hata kaydı ham Graph nedenini saklamadığından sunucunun kesin ret nedeni bu run için ayrıca kanıtlanmış değildir. Video için `id,from` sahiplik kontrolü ve doğrulanmış sayısal ID'den resmi Facebook Watch bağlantısı kullanılır. Bu API'den dönen permalink olduğu iddia edilmez. Composite PagePost ID varsa permalink ayrı sorgulanır. Sahiplik eşleşmesi olmadan POST yoktur.
- Yalnız bu exact batch'in `source_or_permission_unverified` durumundaki (POST yapılmamış) kayıtları düzeltilmiş preflight ile bir kez rezerve edilir. Yeni kayıt version=2 taşır; failed POST, accepted, reserved veya uncertain geri açılmaz. Kaynak kontrolleri batch içinde kaynak başına cache edilir; aktör POST'ları tekildir.
- Yeni preflight hataları yalnız güvenli HTTP/Graph kodu ve sabit sahiplik nedenleri taşır; token/ham yanıt yoktur. Uygulanabilir işlemlerin hepsi engellenir veya POST belirsiz kalırsa workflow artık failure olur; result/intent her durumda korunur. Yeni canlı sonuç ayrıca kontrol edilecek.

## 30 Ekim 2026 — Gerçek paylaşım alındıları ve Meta 368 durdurması

- [Düzeltilmiş ilk batch #41045806381](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41045806381), 14:08–14:18 TRT: 210 Facebook bağlantı paylaşımı denendi; **91 accepted, 119 rejected**. 7 Facebook sayfasının tamamında en az bir gerçek share_post_id var. 91 alındı tekildir ve her ID'nin Page öneki hedef aktörle eşleşir. Örnek: `1298191963387372_122110533495510558`, `1398347343353947_122116609815499964`. Result artifact `12972697763`.
- Reddedilenlerin 113'ü HTTP400 / Graph368, 6'sı HTTP400 / Graph200. [Meta'nın birincil hata kılavuzu](https://developers.facebook.com/docs/graph-api/guides/error-handling/) 368'i geçici politika ihlali engeli olarak tanımlar. Kesin içerik/hesap moderasyonu gerekçesi ham mesaj bu kayıtta olmadığından ayrıca kanıtlanmadı. 368 tek başına HTTP429 kota hatası gibi tekrar döngüsüne alınmaz.
- Önceki runner ilk 368 sonrasında devam ediyordu. Yeni koruma ilk 368'de ilgili platform/işlem kanalını bütün aktörler için durdurur ve bağımsız ledger'a provider_holds kaydeder. Önceki sonuçtaki 368 retleri de otomatik hold'a çevrilir; 48 saatlik eski-action budaması bu hold'u silmez. Başka sayfa/tokenla devam ederek engeli aşmaya çalışılmaz.
- Günlük **13:00 TRT cron korunur**, ancak Meta paylaşım engeli çözüldüğü doğrulanana kadar Facebook repost için yeni POST yapılmaz. Kontrol/izin raporu üretilebilir ve hold görünür failure olarak kalır. 91 başarılı paylaşım ve bütün ret kayıtları korunur; yeniden gönderim veya silme yapılmaz. Diğer normal video yayın işi bu etkileşim hold'uyla yeniden tetiklenmez veya durdurulmaz.
- Beğeniler için hâlâ `pages_manage_engagement` / `instagram_manage_engagement` yok; 245 FB ve 174 IG like adayı bu nedenle POST'a ulaşmadı. Kaydetme ve native IG repost unsupported; bunlar başarılı ilan edilmez.

## 30 Ekim 2026 — Drive oturum yedeği, IG container uzlaştırması ve olay bazlı alarm

- Canlı temel: [12:48 TRT #41035360834](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41035360834) Gönle/Film/Filmmagrasi/ToonZone Drive indirmelerinde FileURLRetrievalError; [14:46 TRT #41049898379](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41049898379) 3 başarılı FB videosuna karşı ToonZone S01E07 Part3 IG binary HTTP400. [12:58 TRT #41036563337](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41036563337) Film Avanak Apti Part10'un 720p denemesi de HTTP400 idi; önceki kodlama düzeltmesi canlı çözüm olmadı.
- Drive: aynı çerezli yolu 3 kez tekrarlamak yerine ilk deneme sonrası çerezsiz public-link oturumu, 2/8 saniyelik bounded backoff ve parsiyel temizliği. Bu eski çerezin kesin kök neden olduğu iddiası değildir; sağlayıcı kota/erişim engeli aşılamaz. Üç başarısız indirme hâlâ gerçek hata kaydıdır, Meta POST yapılmaz.
- IG: yalnız HTTP400, tam bayt aktarımı ve izin/politika hatası olmayan binary reddinde AYNI container'ın status_code/status alanı okunur. FINISHED ise mevcut akış ilk media_publish çağrısına devam edebilir; yeni container/binary POST tekrarı yok. ERROR/EXPIRED/PUBLISHED/okunamayan durum veya yarım aktarım publish edilmez. Container ID/durumu güvenli failure kaydında tutulur. PUBLISHED/FINISHED/UNVERIFIED/IN_PROGRESS eski hataları otomatik yeni medya denemesine yetki vermez.
- Teşhis: Film Part10 `17904577569599675` ve ToonZone S01E07 Part3 `17910279864580142` mevcut container'ları yalnız GET ile kontrol edilir. Sağlayıcının iç ret nedeni ancak bu okuma desteklerse sınıflandırılabilir; ham status mesajı veya token yayımlanmaz. Marker güncellemesi yalnız read-only teşhisi çalıştırır.
- Bildirim: video ledger'ından ayrı, main publisher kaynaklı link-alert-intent/result artifact geçmişi. Mesaj niyeti ilk Telegram/ntfy çağrısından önce saklanır. Aynı olay (hesap/platform/dosya/hata ailesi) tekrar çalışmada yeniden acil alarm değildir; 24 saatte bir bilgi hatırlatması olabilir. Gerçek yeni dosya/hata ailesi yeni uyarı üretir. Güncel gerçek post ID'si olayı çözer; GitHub success tek başına çözüm değildir. Başarılı post bildirimleri kendi post ID'siyle tekilleştirilir.
- Watchdog/hedef uyarısı yalnız bütün ilgili hata run'ları veya eksik platformlar yakın zamanda ACK alınmış ve hâlâ açık publisher olaylarıyla kapsanıyorsa yinelenmez. Yeni/açıklanamayan hata veya alert geçmişi okunamaması yeni uyarıyı susturmaz. Eksik hedefler/hatalı koşumlar log, verdict artifact ve failure sonucunda görünür kalır; phone delivery hâlâ doğrulanmaz.
- Bildirim geçmişi 7 gün artifact olarak tutulur, en geç 24 saatte yenilenir; devam eden koşumlar geçmişi taşır. Bozuk/erişilemeyen geçmiş otomatik sıfırlanmaz. Ambiguous bildirim gönderimi kör retry yapılmaz; kanal ACK'leri ve teslim hataları ayrı kaydedilir. Notify prepare/archive/send hataları final incident sonucuna failure olarak yansır.
- Meta 368 hesaplar arası paylaşım hold'u korunur. Bu değişiklik gerçek yeniden paylaşım başlatmaz, token/izin güncellemez, eski publisher veya YouTube yolunu açmaz.
- Geri alma: bu bakım değişikliğini revert et; video state, alert intent/result ve diğer incident arşivlerini silme. Canlı teşhis ve sonraki normal schedule sonucu ayrıca eklenmeli; test başarısı canlı HTTP400'ün çözüldüğü iddiası değildir.

### 30 Ekim 15:23 TRT — canlı GET kanıtı ve mevcut container'dan devam

- [Salt-okunur teşhis #41054900317](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41054900317): yeni Film Part10 container `17904577569599675` **IN_PROGRESS**, ToonZone S01E07 Part3 `17910279864580142` **FINISHED**. Eski iki 25 Ekim container'ı EXPIRED. Hiçbir POST/yayın yapılmadı. Bu kanıt binary HTTP400'ün her zaman terminal işleme reddi olmadığını doğruladı; FINISHED yayın post ID'si değildir.
- #40 `be5ac57c` main'e alındı; 675 Python testi, 57 fonksiyon assertion ve 15 scheduler testi geçti; bütün PR kontrolleri yeşildi. Yeni normal publisher koşumu henüz canlı doğrulanmadı.
- İki eski intent için kaynak Drive ID + dosya adı + orijinal run ID + caption hash + Page/IG kimliği + binary HTTP400 aşamasıyla sabit container bağı kuruldu. Eski `ready` ToonZone kaydının yeni video yüklemesine düşmesi engellendi. Sonraki normal yayın koşumu yalnız AYNI container'a GET yapar; FINISHED ise ilk media_publish çağrısını yapabilir. Film IN_PROGRESS kalırsa hiçbir POST yoktur.
- Resume plan/state ilk POST'tan önce mevcut link-state-intent artifact'ına girer. Yayın denemesi öncesi attempted marker yazılır; bir sonraki koşum eski intent artifact'ından veya belirsiz POST sonucundan tekrar yetki çıkaramaz. Yalnız GET'in FINISHED olmadığını kanıtladığı result kaydı sonraki GET kontrolüne yeniden izin verir. Yeni binary yükleme, kapak üretimi ve kaynak indirmesi yapılmaz; sıradaki bölüm atlanmaz. Uzak geçmiş eşleşmesi önce uzlaştırılır.
- Testler: exact kimlik/metin/kaynak bağları, arşiv intent'inin belirsiz publish'i yeniden açmaması, no-POST durumunun saklanması, marker'ın çağrıdan önce kalıcılaşması, yalnız FINISHED yayını ve planner resume bağının arşive taşınması. Canlı post ID'si ayrıca beklenir; bu ek kayıt başarı iddiası değildir.


### 31 Ekim 2026 — Meta User token 401/190 ve Daily Laugh read-only unknown

- [Canlı planlama #41157680575](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41157680575) ve [#41193557233](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41193557233) `Meta hesap erişimi reddedildi (HTTP 401, kod 190)` nedeniyle **plan** aşamasında durdu. Yayın atlandı; #41193557233 için `confirmed_new_posts=0`.
- [Daily Laugh read-only kontrolü #41175615837](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41175615837) `status=unknown`, `reason=meta_read_failed` raporladı. **8 eksik video kanıtı yok**; Meta geçmişi okunamadı.
- Güvenli kod değişikliği: Publisher ve salt-okunur hedef kontrolü önceden kayıtlı `META_AUTH_JSON` secret'ındaki Page tokenlarını kullanabilir; publisher önce `meta_page_token_health.py` ile **bütün** Page kimliklerini salt-okunur doğrular. Eksik/yanlış/geçersiz Page tokenında yayın başlatılmaz. JSON secret yoksa eski User token yolu ve gerçek HTTP401 hatası korunur. Secret, izin, otomatik yeniden upload, claim veya post değiştirilmedi.
- `unknown` uyarısı gerçek video açığı olarak sunulmaz. Test yeşili canlı yayının düzeldiği anlamına gelmez; sonraki planlı koşumda gerçek post ID + hesap geçmişi zorunludur. `META_AUTH_JSON` yoksa veya Page tokenları da geçersizse kullanıcı geçerli Meta tokenlarını üreterek GitHub Secrets'a güvenli şekilde kaydetmelidir.

### 31 Ekim 2026 — İkincil kök neden: GitHub workflow/secret yönlendirme farkı (doğrulandı)

- Aynı `main` commit `701952f530e1114b4b63499200b9e6a589f22ece` üzerinde, [00:57 UTC publisher #41152889256](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41152889256) **2 confirmed_new_posts** raporladı. [01:56 UTC publisher #41157680575](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41157680575) ise `meta_auth_loader.py:79` üzerinden `/v24.0/me/accounts` çağrısında **HTTP401 / Graph code190** aldı. Bu aralıkta kaynak commit değişmedi; kod regresyonu kanıtı yok. Secret değeri / yetki / tip durumu ayrıca doğrulanmalı.
- [10:36 UTC engagement #41193424640](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41193424640) logunda `META_AUTH_JSON:` **boş**, `META_ACCESS_TOKEN: ***` maskeli. Bu, 985 deposunda kayıtlı Page-token JSON yedeğinin o job'a **sağlanmadığını** gösterir. Secret değerlerinin içeriği GitHub'dan okunamaz; yanlış değer veya başka hesaba yazılmış secret olasılığı tek başına kesin kanıtlanamaz.
- `main` üzerindeki `.github/workflows/public_link_schedule.yml` ve `tracked_meta_routes.yml` yalnız `META_ACCESS_TOKEN` sağlarken `meta_connection_audit.yml` / `meta_cross_engagement.yml` ayrıca `META_AUTH_JSON` tanımlar. Bu **gerçek wiring uyumsuzluğu** PR #46'da ele alındı; ancak yedek JSON secret **boş kaldığı sürece** PR'ın bu yolu hiçbir credential sağlamaz ve tek başına üretimi kurtarmaz.
- Meta'nın resmi Postman Instagram API koleksiyonunda `/me/accounts` için **User Access Token** gerektiği belirtilir; Facebook Page Access Token, Instagram/Threads tokenı ile karıştırılmamalıdır. Doğru Meta hesabı mevcut olması, bu spesifik GitHub Actions secret'ının doğru **tipte**, doğru **985 repo** altında ve aynı uygulamaya ait olduğunun kanıtı değildir.
- Güvenli takip: yeni POST, manuel publish veya başarısız run'ı kör rerun yapma. Önce **985 repo** Secrets kapsamı ve isimleri denetlenir; Page JSON yapılandırılmışsa `Read-only Meta Page Token Health` ile Page kimlikleri test edilir; User token yolu gerekiyorsa `/me/accounts` kimlik doğrulaması salt-okunur doğrulanır. Gerçek yayın yalnız post ID + uzak platform geçmişi ile kabul edilir. Token değerleri asla loglanmaz veya sohbete kopyalanmaz.

### 31 Ekim 2026, 14:37–14:43 TRT — ilk başarılı PR #46 üretimi, kalan Drive GET arızaları

- [Planlı üretim #41197608372](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41197608372), main `0316bc19`: Meta kimlik ve plan aşaması **PASS**, dört gerçek yayın post ID'si: Tarladaki Fasulye FB `1440208974866285` / IG `18141310015623134` ve Beyinsiz Penguen FB `1143827128067446` / IG `17939939568122965`. IG gerçek bağlantıları `https://www.instagram.com/reel/DfKEgdZkuUa/` ve `https://www.instagram.com/reel/DfKEmwEFHwj/`. `confirmed_new_posts=4`; `OUTCOME_PUBLISH=failure` doğru kalmalı.
- Kalan HELD: Gönle Düşen, Filmmagrasi, ToonZone için üçer gdown `FileURLRetrievalError`; Film Mağarası IG için kayıtlı container `not FINISHED` (mevcut belirsiz container hiçbir koşulda tekrar binary upload edilmemeli). `uncertain_pending_reconciliation=1`.
- Bağlı Google Drive meta verisinde ToonZone klasörü ve dosyalar mevcut, en azından listelenen dosyalar `can_download=true`. Ancak GitHub runner public-link GET'in erişebildiği kanıtlanmamıştır. Google Drive 429/quota veya izin sınırlamasını kodla atlatmak garantili değildir.
- Güvenli yedek: Üç gdown URL çözümleme hatasından sonra, aynı envanterdeki ID için **tek** bağımsız, kimliksiz `drive.usercontent.google.com/download` GET'i denenir. Nihai HTTPS Google hostu, HTTP 200, dosya boyutu, HTML/JSON interstitial, tam içerik uzunluğu, MP4/PNG imzası doğrulanmazsa dosya **kullanılmaz**; kısmi dosya temizlenir. Hiçbir Meta POST, claim silme veya yeniden upload eklenmedi. Canlı kabul için yeni planlı yayın sonrasında gerçek gönderi ID'leri, hesap kimliği ve source state eşleşmesi gerekir.
- 31 Ekim `Meta cross-account engagement` kontrolü #41197491075 (sadece audit) ValueError ile HELD: operasyon yapıldığına dair kanıt yok. Bu hata hiçbir beğeni/yeniden paylaşım işini zorla açmak için gerekçe değildir.

### 31 Ekim 2026, 16:45–16:56 TRT — intermittent User token access; strict no-publish diagnosis

- [15:47 TRT publisher #41202675929](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41202675929) aynı `main` commit `94fe39d5` ile **10 confirmed_new_posts** raporladı. Gönle Düşen IG, Daily Laugh Lab FB/IG, Filmmagrasi FB ve ToonZone FB/IG dahil gerçek platform gönderi ID'leri kaydedildi. Drive Public GET kurtarması üretimde çalıştı. Eski Film Mağarası IG container'ı `not FINISHED` olarak HELD kaldı; `uncertain_pending_reconciliation=1`.
- [16:45 TRT publisher #41207013176](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41207013176) **aynı commit** ile plan adımında `/me/accounts` GET `HTTP 401 / Graph code 190` aldı; `confirmed_new_posts=0`. [16:56 TRT yeniden koşturulan salt-okunur container tanısı #41179970384](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41179970384) da `credential_or_read_failure` verdi. Salt-okunur denetim bile başarısız olduğundan sorun videonun MP4 biçimi veya Drive GET değil, mevcut kimlik doğrulama yolunun erişimi.
- `META_AUTH_JSON` önceki engagement loglarında **boş** olduğundan bunun yedek Page token sağladığı varsayılamaz. Bir User tokenının kısa ömürlü olması olasıdır ama **alt hata kodu olmadan süresinin dolduğu kesinleştirilemez**. `meta_auth_loader.py` yalnız sayısal `error_subcode` değerini (`alt_kod`) raporlayarak 190 nedeninin teşhis edilmesini sağlar; ham Meta mesajı, bearer, URL, app secret veya token günlüğe girmez.
- Eğer kod `190/463` ise sona ermiş tokenı hiçbir Python yeniden denemesi kurtaramaz; kullanıcıdan yeni token ister gibi sürekli mesaj atma. Kalıcı çözüm, 985 deposuna **Meta tarafından halen geçerli ve uygun uzun süreli erişimi olan** kimlik bilgilerinin güvenli yapılandırılmasıdır (var olan kullanıcıdan bağımsız Page tokenları varsa `META_AUTH_JSON` dahil). Eğer farklı alt kod çıkarsa ona göre izin ve uygulama yetkisi tekrar denetlenir; hiçbir token içerik olarak koda veya artifact'a yazılmaz.
- **Güvenlik:** Boş veya süresi geçmiş tokenla upload/publish/retry yok, Film Mağarası'nın belirsiz Instagram intent'i temizlenmez; `PUBLISHED` olmuş başka container yeniden yüklenmez. CI yeşili 100/100 canlı üretim kabulü değildir. Sonraki planlı workflow'da gerçek gönderi kanıtı + sıfır HELD + kaynak geçmişi kıyaslaması şarttır.

### 1 Kasım 2026 — N/A raporu ve bildirim/veri başarısının ayrılması

- Rapor #41240080841 (31 Ekim 23:41 TRT) bütün 13 Meta platformunda HTTP401/190/463 almasına rağmen success ve üç Telegram ACK kaydetti. Yeni planlı #41246812951 (1 Kasım 01:08 TRT) de aynı hata; job ortamında META_AUTH_JSON boş, META_ACCESS_TOKEN mevcut. Bu, kullanıcının başka yerde yenilediği tokenın geçersizliğini kanıtlamaz; bu job'a sağlanan credential reddedilmektedir. Secret değerleri okunmadı/taşınmadı.
- Düzeltme: karşılaştırma artifact'ı current platform kapsamasını ve güvenli toplama hatalarını taşır; Telegram ilk tabloda en çok iki neden gösterir. Eksik gün/hafta tabanı hata sayılmaz; güncel platform sayacı eksikse bildirim ACK sonrası job nonzero döner ve AI başarı özeti gönderilmez. Arşiv ve kısmi doğru veriler korunur.
- Meta POST, yeni token, secret değişimi, claim temizliği ve YouTube değişikliği yok. Bu düzeltme credential erişimini kurtardığı iddiası değildir. Geri alma: bu raporlama commitini revert et; geçmiş artifact'ları silme. Canlı veri kabulü hâlâ bütün FB/IG sayaçlarının GET ile alınmasını gerektirir.


### 1 Kasım 2026 — 12:36 TRT planlı yayın: tekrarlayan Meta preflight reddi

- Kanıt: https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41293857640 ; main 5d8eb1d1b62b53c4d2fed0da378c97d252ccfb61, job 124810489260. Gerçek runner çalıştı; sorun runner/kota veya MP4 hazırlığı değildir.
- Güvenli yapılandırılmış hata: status=blocked, reason=meta_auth_rejected, http_status=401, graph_code=190, graph_subcode=463, publishing_tested=false. Workflow'un kullandığı erişim bilgisi reddediliyor; başka yerde yenilenmiş bir tokenın bu job'a aktarıldığı varsayılmaz. Secret içeriği okunmadı.
- Mevcut koruma canlı kanıtı: preflight failure; media runtime, plan, intent ve publish adımları skipped. Sonuç, incident ve yapılandırılmış hata arşivleme adımları success. Salt-okunur kanıt makbuzunun success olması yayının success olması değildir.
- Tekrarı önleme kuralı: 190/463 credential arızasını video/Drive hatası gibi ele alma; aynı credential ile kör rerun, yeni upload, state/claim temizliği yapma. Secret değeri, token, signed URL veya ham HTTP gövdesi kaydetme. Yetkili erişim güvenli biçimde yapılandırıldıktan sonra önce yalnız GET kimlik/izin doğrulaması; ardından normal schedule'da post ID + uzak hesap geçmişiyle kabul.
- Kullanıcının kalıcı isteği: her yeni arıza için tarih + run + kök neden/henüz bilinmeyenler + önlem + test + canlı sonuç bu deftere eklenir; eski olaylar korunur. Aynı olay çözüldü sayılmadan önce sağlayıcı erişimi ve gerçek yayın sonucu ayrı doğrulanır.
- Bu müdahale yalnız olay kaydıdır. Yeni kod koruması veya credential onarımı yapılmadı; mevcut preflight koruması gözlendi. Üretim hâlâ BLOCKED. Sıfır arıza garantisi verilmez.

### 1 Kasım 2026 — YouTube main workflow entegrasyonu

- Kullanıcı ana yayın workflow'una YouTube entegrasyonunu açıkça istedi. Mevcut Meta planından Tarladaki/Penguen/Daily Laugh kaynağı seçilir; eski yayıncı açılmaz, tüm arşiv topluca yüklenmez. Daily Laugh tokenı yoksa missing_secret olay kaydı ve başarısız YouTube sonucu üretilir; diğer doğrulanmış kanallar devam eder.
- Kanal sabit ID ile GET doğrulanır. YouTube intent aynı link-state-intent arşivine POST öncesi girer; sonuç aynı link-state-result içinde youtube_entries olarak taşınır. Run ID + attempt bağı eski intent'in rerun ile yeniden POST'a dönmesini engeller. Uncertain ve eski intent kör yeniden denenmez.
- Her upload öncesi kanal uploads geçmişi okunur; source marker uzlaştırılır, aynı başlık belirsizliği upload'u durdurur. API ID sonrası kanal/status GET kontrolü yapılır. Public istense de sağlayıcı uygulama doğrulaması nedeniyle private kalabilir; dönen privacyStatus loglanır. Public + processed olmayan kabul accepted olarak tutulur; sonraki koşum yalnız GET ile uzlaştırır, yeni insert yapmaz.
- Kill switch: YOUTUBE_PUBLISHING_ENABLED=false. Normal Meta schedule/konkürensi kullanılır. Özel IG rescue ve audit upload yapmaz. YouTube hatası mevcut Meta POST'larını geri almaz; sonuç arşivi her durumda korunur.
- Geri alma: entegrasyon commitini revert et veya kill switch'i kapat; youtube_entries ve artifact'ları silme. Testler canlı upload/yayın kabulü değildir; gerçek video ID ve public status ayrıca doğrulanır.

### 1 Kasım 12:50 TRT — Bozuk JSON yedeği User tokenını gölgeliyor

- Page health #41294851275 job124813428489: META_AUTH_JSON artık dolu/maskeli; loader invalid_meta_configuration ile duruyor. Önceki başarılı rapor ve publisher'da JSON boştu. Bu yeni hata eski HTTP401/190/463 ile aynı değildir. Secret içeriği okunmadı.
- Loader artık documented pages şemasını doğrular ve tek ekstra JSON string katmanını açar. Sözdizimi/şema hatasında ayrı META_ACCESS_TOKEN mevcutsa yalnız güvenli GET keşfine geçer; yoksa redakte açık hata verir. Geçerli kayıtlı JSON önceliği korunur; canlı hesap uyuşmazlığı fallback ile aşılmaz.
- Fallback kendi başına süresi geçmiş User tokenını yenilemez. Canlı kabul, Page Health aynı yeni SHA ile başarılı olduğunda yapılır; mock test yeşili credential başarısı değildir.
- Geri alma: loader değişikliğini revert et; secret/state/artifact silme.

### 1 Kasım 2026 — Preflight başarısızken link-error-journal boş kalıyordu

- Kanıt: [planlı yayın #41294422455](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41294422455) Meta GET ön kontrolünde HTTP 401 / Graph 190 / alt kod 463 ile fail-closed durdu; `link-error-journal` için `No files were found` görüldü. Buna karşın `link-incident-report` arızayı kaydetti. Bu bir **olay kayıt açığıdır**, token çözümü değildir.
- [JSON loader yaması PR #58](https://github.com/emirhankaya985-cloud/auto-video-publisher/pull/58) sonrası [salt-okunur denetim #41295291756](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41295291756) geçersiz kayıtlı JSON'dan bağımsız User tokena yöneldi; User token da HTTP 401 / 190 / 463 ile reddedildi. Gerçek erişim düzelmedi.
- Güvenli düzeltme: Workflow preflight başarısız olursa `workflow_verify/workflow_step_failed` adlı sabit, sansürlenmiş olay `errors.jsonl` dosyasına yazılır; her zaman çalışan önceki artifact adımları kaydı saklar. Hatalı token, sağlayıcı mesajı ve ham JSON asla bu dosyaya yazılmaz. Meta POST tekrar denenmez; yayın kanıtı yokken "yayınlandı" denmez.
- Test: `test_meta_preflight_journal.py` olay yazımını, redaksiyonu ve workflow adım sırasını doğrular. Canlı 401/190/463 kaldırılmadı; yalnız Meta'dan geçerli Page yetkisi/kimliği sağlandığında GET-only denetimi geçebilir.
- Geri alma: bu workflow kayıt adımını revert et; yayıncı intent, claim, state, secret ve eski artefaktlara dokunma.


### 1 Kasım 2026 — JSON secret isteğe bağlı; sayfa sağlığı denetimi sabit

- [Meta Page Health #41295291756 (3. deneme)](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41295291756): Güncellenen `META_ACCESS_TOKEN` ile User token keşfi ve 7/7 sayfanın read-only kimlik GET'i başarılıdır. `META_AUTH_JSON` ise hâlâ bozuk biçimdeydi; loader'ın tanımlı fallback yolu kullanıldı. Başarılı kimlik GET'i **gerçek paylaşım veya publish izni doğrulaması değildir**.
- `META_AUTH_JSON` zorunlu değildir ve eski/bozuk secret GitHub'dan kaldırılabilir. `META_ACCESS_TOKEN` korunmalıdır. Kayıtlı Page JSON biçimiyle destek gelecekte isteğe bağlı yedek olarak kodda kalır.
- Önceden workflow JSON varsa 7 sayfa GET, yoksa daha zayıf keşif kontrolü yapıyordu. Şimdi her durumda aynı `meta_page_token_health.py` salt-okunur 7 sayfa denetimini yapar; video/POST, state sıfırlama, OAuth yenileme yoktur.
- Test: kullanıcı tokenı-only yoluyla read-only main kabulü ve workflow'un medya hazırlığından önce sabit denetimi; gerçek kodun CI'sı ayrıca görülmeli. Token gelecekte süresi dolarsa kod bunu otomatik aşamaz.

### 1 Kasım 2026 — Kullanıcı kararı: yalnız META_ACCESS_TOKEN, JSON yedeği kaldırıldı

- Kök neden: Önceki loader geçerli saved JSON'u User token'ın önüne alıyor, bozuk JSON'da da geri dönüş mantığı çalıştırıyordu. Ayrı secret'lar üretimde tutarsızlık yaratabiliyordu. Kullanıcı JSON girişi ve tekrar tekrar JSON düzeltme istemediğini açıkça belirtti.
- [13:40 TRT planlı yayın #41298523959](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41298523959) Meta GET ön kontrolünde 401 / 190 / 463 ile durdu; yeni yayın/POST yok. [Read-only Page Health #41295291756](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41295291756) güncellenen User token'ın 7/7 sayfa kimliğinde başarılı olduğunu gösterdi; farklı çalışma zamanı ve kimlik doğrulaması yayın izninin veya yeni planlı gönderinin kanıtı değildir.
- Yeni güvenlik kuralı: `META_ACCESS_TOKEN` tek kaynak, `/me/accounts` ile sayfa tokenlarını bellekte keşfet. `META_AUTH_JSON` secret'ını veya `meta_auth.json` yerel dosyasını **okuma veya önceliklendirme**. Eski secret GitHub'da kalsa bile işleyişi etkileyemez.
- Token yoksa, süresi dolmuşsa veya kimlik eşleşmiyorsa, medya hazırlığından önce dur; hata jurnalini sakla. Meta POST otomatik tekrar yok. Diğer YouTube/Drive/Threads OAuth ayarlarına dokunma.
- Kod kabulü: token-only ve eski JSON yok sayma regresyonları + secret'sız PR CI. Canlı kabul ayrı: güncel main SHA üzerinde planlı publisher, gerçek platform post ID ve dedupe state eşleşmesi.

### 1 Kasım 2026 — Ana YouTube yolunda gerçek hata günlüğü ve Gönle Düşen eşleştirmesi

- `publisher_error_journal.py` aşama/sebep allowlist'i ile `youtube_main_bridge.py` çağrıları uyuşmuyordu: `youtube_prepare/missing_secret`, `youtube_publish/youtube_publication_unverified`. Benzer biçimde `public_link_runtime.py` içindeki `publication_preflight/intent_validation_failed` ve `instagram_publish/existing_container_reconciliation_failed` kayıtları reddediliyordu. Bu, asıl hata sonrası ikinci bir `ValueError` üretebilirdi. Sadece sabit etiketler kabul edilir; özel token/sağlayıcı metni/journal sızıntısı yok, bilinmeyen etiketler hâlâ reddedilir.
- Gönle Düşen için daha önce tanımlanmış `TOKEN_GONLE_DUSEN_JSON` ve sabit YouTube kanal ID'si, ana seçilmiş Meta video planının YouTube köprüsüne eklendi. Yayın sadece kanal ID'si live GET ile tam eşleşirse, intent artifact'ı arşivlenirse ve normal `schedule` seçili plan üretirse mümkün; diğer hesapların yayın durumu korunur. Film, Filmmagrasi ve ToonZone için kanıtlanmamış YouTube rotası açılmadı.
- Bu değişiklik canlı OAuth yetki geçerliliği veya başarılı public video iddiası değildir. Gerçek kabul, sıradaki normal schedule koşumunda her kanal için `post_id`, `privacy_status=public`, `upload_status=processed` ve ilgili ledger kaydıyla yapılır. Önceki belirsiz upload/intent asla körlemesine yeniden gönderilmez.
- Regresyon: uydurma tokenla hiç dış yükleme yapmadan doğru/yanlış kanal kontrolü, eksik secret hold, Meta ve YouTube olaylarının güvenli kaydı.
- Geri alma: köprü/allowlist/workflow değişikliğini revert et veya `YOUTUBE_PUBLISHING_ENABLED=false` ile YouTube'u duraklat; saklanan intent/state/artifact kayıtlarını silme. Açık ve eski alternatif YouTube PR #56 kodunu bu ana yolun üzerine körlemesine birleştirme.


### 1 Kasım 2026 — Sahip onaylı toplu telafi ve kuyruk engelleri

- Kullanıcı bugün hedeflenen tüm videoların tamamlanmasını ve çoklu ajanla düzeltme yapılmasını açıkça istedi. Planlı yayın #41325257469 ikinci denemesinde erişim GET başarılı; 5 yeni Meta post ID doğrulandı. Yayın öncesinde eski deneme hiçbir upload yapmamıştı. Sonraki işlem geçmiş/intent uzlaştırması olmadan kör yeniden yükleme yapmaz.
- Gönle Düşen ve Daily Laugh yeni YouTube videoları, read-only #41325268149 job124917325053 ile public/processed doğrulandı; yeni insert yapılmadı.
- Canlı GET tanısı #41330068602 job124918096649: Tarladaki192 ve Penguen193 IN_PROGRESS; eski aynı kaynak/container yeniden yüklenmez. Film Avanak Apti Part10 EXPIRED; ToonZone S01E07Part3 PUBLISHED, tekrar yükleme yasak.
- Kanıtlanan planlama sorunları: tek IG belirsizliği bağımsız FB kuyruğunu kilitliyordu; Gönle TXT içindeki bağımsız yorum sayacı satırı gerçek metni de bloke ediyordu; ToonZone tamamlanmış bölümün son partından sonraki bölüme günlük kota içinde geçemiyordu. Yeni geçiş sadece önceki bölümün dört kaynak partının iki platformda da gerçek ID ile tamamlandığı ve açık intent bulunmadığı durumda mümkündür. Yalnız tanınan bağımsız arayüz satırı çıkarılır; gerçek metin korunur, boş/arayıüzden ibaret TXT bekler.
- Tam gün telafisi yalnız 2026-11-01 için etkinleştirilecek; ikinci Film sayfasının eski 23 Ekim geçişine ait fazladan partı bugünün 5 hedefini 6 yapamaz. Normal cron, hak anahtarları, kaynak sırası, günlük kota, mevcut done/uncertain kayıtları korunur. Bir video farklı platformda paylaşılmışsa platform başına ayrı sayılır.
- Film kurtarması genel kilit temizliği değildir: sadece tam source ID, caption hash, origin run, hiç media_publish çağrılmadığı kayıt ve canlı EXPIRED GET eşleşirse; uzak geçmişte tekil/belirsiz eşleşme yoksa bir sınırlı yeni hazırlık mümkündür. Eski container delili ve tüketilmiş deneme kalıcı state'te korunur.
- Test/CI başarısı yeni yayın başarısı değildir. Sonraki telafi için post ID, caption/source eşleşmesi ve kalan engeller ayrıca raporlanır. Geri alma: ilgili kod commitini revert et veya yayın anahtarını kapat; state/artifact/claim silme.

### 2 Kasım 2026 — Meta günlük raporunda yayın sayılarının N/A olması

- Kanıt: günlük rapor [41348216278](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41348216278) Meta izlenmelerini kaydetti ve bildirim sunucuları kabul etti; bütün yayın sayaçları N/A kaldı. Meta-only yolunda Drive oluşturulmadığı halde eski Drive sayacı çağrılıyordu.
- Düzeltme: raporlama için yalnız GET ile en yeni main `link-state-result`/daha yeni `link-state-intent` okunur. Done ve post ID bulunan kayıtlar platform başına tekilleştirilir. Eksik/bozuk arşiv sıfıra dönüştürülmez. Günlük kota tamamlanması platformların en düşük sayısından hesaplanır; aynı kaynak videosu eşleşmesi iddiası değildir. Meta toplam platform hedefi 69; video kota hedefi 32. Belirsiz kayıt başarı sayılmaz.
- Test: arşiv seçimi, tekilleştirme, Film'in üç hedefi, kaynak kimliği farkları, ID'siz/belirsiz kayıtlar ve rapor entegrasyonu. Gerçek 2 Kasım arşiviyle 1 Kasım platform sayıları 69/69 okunabildi; bu yeni kodun canlı günlük rapor çalışması değildir.
- Yayın, token, intent veya state değiştirilmez. Geri alma: bu raporlama değişikliğini revert et; artifact geçmişini silme. Son kabul: merge sonrası normal günlük raporun `publication-progress` artifact'ı ve bildirimdeki sayılar ayrıca doğrulanmalıdır.

### 2 Kasım 2026 — Rapor arşivi sayfalaması ve bağımsız bildirim hazırlığı

- Günlük arşiv okuyucu 100 artifact sınırında geçerli geçmişi reddediyordu. Sınırlı sayfalama eklendi; erişim/şema hatasında eski geçmiş yine korunur. 101. kayıttaki geçerli snapshot regresyonu eklendi.
- ntfy tablo/özet hazırlığı Telegram gönderiminden önce korumasız çalışıyordu. Artık ntfy biçimlendirme hatası Telegram tablo gönderimini durdurmaz. Telegram başarı alındısı varsa ntfy arızası açıkça loglanır; iki kanal da başarısızsa işlem başarısız kalır. Test gerçek bildirim göndermeden iki Telegram parçasının kabulünü denetler.
- Son yayın gözlemi: run 41425754467 Meta publish/notify başarılı, 4 doğrulanmış yeni post; üst workflow hatası YouTube accepted durumundaki RuntimeError. Yayın güvenlik kilitleri, belirsiz intent ve kaynak karantinası değiştirilmedi.
- Geri alma: bu raporlama commit'ini revert et. State veya geçmiş silme yok. Canlı günlük rapor alındıları ayrıca doğrulanmalıdır.

### 2 Kasım 2026 — YouTube kabul kimliğini doğrulamadan önce koru

- Canlı kanıt: 41425754467 Tarladaki upload accepted sonrası fail; salt-okunur 41429822977 job125225512745 aynı 6oPNuammOYU videosunu public/processed doğruladı, uploads_attempted=0. Normal işleme gecikmesi tek başına yeni upload gerektirmez.
- Kod açığı: upload dönen ID sonraki videos.list GET'inden önce kaydedilmiyordu. Şimdi accepted+post_id hemen diske yazılır. Sonraki çalışmada yalnız aynı ID GET ile uzlaştırılır; insert tekrar edilmez.
- Doğru video ID + kanal + public/uploaded durumunda accepted bekleyişi açıkça raporlanır; done sayılmaz ve normal işlem bekleyişi hata gibi gösterilmez. Processed/public olduktan sonra done olur. Yanlış ID/kanal, görünürlük sorunu ve GET hatası hâlâ başarısızdır.
- Test: GET kesildiğinde ID'nin önceden diskte bulunması ve ikinci publish çağrısının upload'u yinelememesi; normal pending ile yanlış video kimliğinin ayrılması. 793 unittest başarılı. Bu mock test yeni canlı upload kanıtı değildir.
- Geri alma: ilgili bridge commit'ini revert et; accepted/uncertain state veya artifact silme. Hak/kanal kontrolü, intent arşivi ve tekrar yükleme kilitleri korunur.


### 2 Kasım 2026 — Yeni bağımsız yedek ve kabul kontrolünün ilk koşumu

- Kanıt: https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41515910390 , main 368a42aa4935dd3e22ff12191d258d3c71793fc7.
- Backup job 125519306279: reason=missing_drive_credentials; bu job'a DRIVE_TOKEN_JSON sağlanmıyor. Secret değeri okunmadı; Drive dosyası yazılmadı. Kod hazır olması kalıcı yedek kabulü değildir.
- Acceptance job 125519306661: bağımlılıklar kuruldu ancak runner'da ffmpeg bulunmadığından kontrol başlamadı. Başarı diye raporlanmaz. FFmpeg/FFprobe normal yayıncının kullandığı apt yoluyla kurulacak; tekrar yalnız GET ve yerel kalite analizi yapacak.
- Yeni yayın, intent temizliği, Meta token değişimi veya kör POST tekrarı yok. Backup receipt artifact saklandı. Credential eksikliği bu kod yamasıyla çözülmez.
- Geri alma: publication_backup workflow'unu devre dışı bırak; mevcut state/artifact/Drive dosyalarını silme.

- Sonuç güncellemesi: 41516183167 acceptance job125520221690 gerçek GET/yerel kabulü VERIFIED: 13 stok satırı,43 mevcut post ID,4811 engagement kaydı,13 follower sayacı,180s gerçek kaynakta3 kalite örneği. Yayın denemesi yok. Aynı koşumun backup job'u ayrı credential eksikliği nedeniyle failure kaldı.
- Bağlı Drive alternatifinde owner-only klasör doğrulandı; 1CTqkOEYGFrMdQ_6pWBmU8eXFEIThh64N recovery ZIP yüklendi, Drive fetch ile tekrar indirildi, SHA256=1ddd55455fcbaea540c0c4abe75d3eba26b27409158bc0d6ff79b05ed12c4c04 eşleşti; izole restore1005 state kaydı+19537 analytics satırı. Bu ilk bağımsız yedek canlı kanıtıdır. Yeni görev5limitine takıldığı için mevcut Meta nöbetine salt yedek ek görevi eklendi; sonraki otomatik koşum henüz doğrulanmadı.
- Direct runner backup DURABLE_DRIVE_BACKUP_ENABLED=true ile opt-in oldu; bilinen eksik credential için her normal yayından sonra yeni kırmızı iş yaratılmaz. Meta/Drive tokenları taşınmadı veya değiştirilmedi.


### 3 Kasım 2026 — Operasyon özelliklerinin kademeli etkinleştirilmesi

- PR #79 birleştirildi: ef0ef9e8e414dcad52077933b114eae011117d1a. Aynı toplu planda aynı son açıklama hash'ini taşıyan ikinci Drive adayı bekletilir; bu bir kaynak bayt eşitliği iddiası değildir. Eski post ID/intent kayıtları korunur.
- Görsel koruma normal workflow'da varsayılan açık, ADVANCED_DEDUPE_ENABLED=false geri dönüş anahtarıdır. Üç kareli algoritma gerçek FFmpeg testinde yeniden kodlanmış kopyayı tuttu, farklı örneği geçirdi. Bu test yeni canlı sosyal medya gönderisi değildir; eski kayıtlarda fingerprint yoksa geçmiş kopyayı bulduğu iddia edilmez. HELD kayıtlar artık stokta kullanılabilir aday sayılmaz.
- Türkçe film altyazısı yerel hazırlık yoluna bağlandı. Açık AUTO_SUBTITLES_ENABLED gerekir; model ayrı kurulum adımında sabit Systran revision'ından indirilir. Orijinal Drive dosyası değiştirilmez. Model/ASR/render hatasında özgün video korunur ve redakte receipt arşivlenir. Dil doğrulanmamış rotaya Türkçe konuşma dayatılmaz.
- Yerel gerçek konuşma kabulünde PyAV 19.0.2, faster-whisper 1.2.1'in metadata_errors parametresini reddetti. PyAV 15.1.0 sabitlemesiyle aynı İngilizce konuşmadan SRT oluşturuldu. Bu, Türkçe filmde altyazı doğruluğu veya üretim kabulü değildir. FFmpeg Türkçe karakterli SRT işleme testi de başarılı.
- Akıllı saatler yalnız Tarladaki/Penguen/Gönle için, beş saatin her birinde her iki platformda dört post/üç gün kanıt olduğunda ertesi İstanbul gününe uygulanabilir. İlk plan veya fallback ledger'a sabitlenir. Seri saatleri, kota, hak ve belirsiz POST kuralları korunur. Yetersiz kanıtta eski saatler aynen sürer. ADAPTIVE_SCHEDULE_ENABLED=false geri dönüş anahtarıdır.
- Telegram tanısı getMe/getChat/getWebhookInfo GET'leriyle genişletildi; getUpdates tüketmez, webhook silmez, mesaj göndermez. Boş webhook aktif polling olmadığını kanıtlamaz. Sürekli bot kurulduğu varsayılmaz; tanı artifact'ı canlı kabulün yalnız bağlantı bölümüdür.
- Ücretli servis, Render değişikliği, yeni token, gerçek yayın denemesi, state/claim silme yok. CI ve merge sonrası gerçek tanı/normal schedule sonuçları ayrıca incelenmelidir.

## 3 Kasım 2026 — Threads Penguen kimlik kontrolü (salt-okunur)

- **Kanıt:** [985 Threads GET-only run #41539380193](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41539380193), job `readonly-api`: Tarladaki, Gönle, Daily Laugh, Film, ToonZone PASS; Beyinsiz Penguen **HTTP 401**. Altı mock test koşumu başarılı; canlı Threads paylaşımı yapılmadı.
- **Neden:** Penguen'in seçili erişim tokenı reddedildi. Gerçek secret değerini okuyamadığımız için tokenın süresi dolduğunu veya yanlış OAuth uygulamasına ait olduğunu **kanıtlamıyoruz**. Denetim workflow'unda legacy genel tokenın Penguen'e özel tokenı gölgelemesi için olası öncelik hatası görüldü.
- **Güvenli düzeltme:** [3 Kasım operasyon notu](../docs/operations-enhancements-2026-11-03.md) kapsamındaki PR #90 ile **Penguen'e özel secret varsa önce onu** kullan. Hata devam ederse yalnız ilgili tokenın kullanıcı tarafından güvenli biçimde yenilenmesi ve yeniden GET-only denetimi gerekir; başka beş tokenı değiştirme. Threads POST/yayın otomatik açılmaz.
- **Kabul:** PR no-publish CI ve yeni `readonly-api` run'ında altı bağımsız gerçek `/me` kimliği PASS görülene kadar Penguen **UNVERIFIED**.

## 4 Kasım 2026 — Tarladaki Fasulye `195.mp4` okunamayan Drive kaynağı

- [10:12–10:22 TRT yayın koşumu #371](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41790686639) `195.mp4` yerel FFprobe doğrulamasında durdu. Sonuç artifact 13303930571, Facebook ve Instagram için `ready`, `source_or_cover_preparation_failed` ve boş post ID kaydetti. Dosya için Meta POST yok. Diğer hesaplar 6 Meta post ID aldı; Film Mağarası Part 24 Instagram `17909879241333918` dahil. İki YouTube yüklemesi ayrı olarak accepted_processing_pending kaydedildi.
- Aynı Drive kimliği bağımsız bağlantıyla tam 18.612.272 bayt indirildi. SHA256 `d5f925c5af9ab97a8ab731beae3b40a049e6527e877315a5275bf2f4c408a960`. FFprobe `moov atom not found` döndürdü. Doğrulanan kaynak kopyası geçerli MP4 değil; yeniden yükleme veya Meta izinleri bu bozuk baytları düzeltmez.
- Sonraki planda mevcut yerel hata karantinası bu dosyayı aynı gün atlar. Yalnız doğrulanan Drive kimliği, dosya adı ve #371 yerel hata kaydı için sonraki günlerde de karantinayı koru. Farklı, sağlam Drive dosya kimliği normal seçim kurallarına tabidir. Seri rotaları ve belirsiz POST kayıtları karantina kapsamı dışındadır.
- İndirilen MP4 doğrulanmazsa hatalı geçici kopyayı kaldır ve mevcut alternatif salt-okunur Drive yolundan bir kez indirip yeniden doğrula. İkinci doğrulama da başarısızsa yayın niyeti mevcut yerel hata yolunda kalır. Kaynak hash ve hak kontrolleri yayın öncesi uygulanır. Yeni canlı sonuç normal schedule post ID ile doğrulanmalıdır.

### 5 Kasım 2026 — Gün sonu raporunda YouTube yayın sayacı

- Kanıt: [41911406151](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/41911406151) 00:09 TRT'de rapor oluştururken `KeyError: 'yt1'` ile durdu. Günlük ölçüm geçmişi arşivlendi, karşılaştırma artifact'ı oluşmadı ve Telegram'a hata bildirimi gitti.
- Neden: Çok platformlu izlenme raporu, YouTube verilerini Meta yayın arşiviyle birlikte işlerken Meta arşivinde YouTube yayın anahtarının bulunacağını varsaydı.
- Güvenli düzeltme: Yayın sayacını hesap rotasıyla eşleştir ve yoksa yalnızca sayacı eksik göster. İzlenme ve abone verisini koru. Regresyon testi Meta arşivinde YouTube anahtarı olmadan rapor üretimini denetler. Canlı kabul için sonraki çalışmada karşılaştırma artifact'ı ve Telegram sunucu alındıları kontrol edilmeli.

### 5 Kasım 2026 — ToonZone telif bildirimi

- Kullanıcının Meta bildiriminde 26 Ekim tarihli Regular Show S01E03, Part 3/4 işaretlendi. Bildirim metni telif gerekçesini gösteriyor. İddia sahibi, kararın kapsamı ve diğer kopyaların durumu henüz doğrulanmadı.
- ToonZone normal ve manuel yayın ile toplu yayın istisnasına kapatıldı. Durdurma, mevcut etkinleştirme bayraklarından bağımsızdır. Yayın geçmişini koru ve mevcut gönderiyi tekrar sıraya alma.
- Yeniden açmadan önce hak belgesini doğrula, diğer platformlardaki aynı kaynağı ve serinin kalan kuyruğunu incele. Yerel test, etkinleştirme ve toplu yayın bayraklarının durdurmayı aşamadığını kontrol eder.

### 5 Kasım 2026 — Kullanıcının izin beyanıyla Threads ilk sezon talebi

Kullanıcı hak sahibinden izni olduğunu belirtti ve ilk sezonu Threads'e sırasıyla yayımlamayı açıkça istedi. Belge ve Meta karar ayrıntısı bağımsız doğrulanmadı. Yalnızca bu talep için 48 parçalık ayrı kampanya hazırlandı. Normal ToonZone durdurması korunur. Kampanya kendi kalıcı intent/result kayıtlarını kullanır, Etsy bağlantısı eklemez, bir parça doğrulanmadan sonrakine geçmez ve belirsiz POST'u otomatik yinelemez. Canlı kabul için 48 doğrulanmış gönderi ID'si gerekir.


### 5 Kasım 2026 — Threads Telegram bildirim gecikmesi

- Kullanıcı Threads bildirimlerinin gelmediğini bildirdi. [42009147207](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42009147207) notify işi 13:15 TRT'de 4 Telegram sunucu alındısı, 0 gönderim hatası kaydetti; Penguen feed okuması HTTP 401 döndü. Sunucu alındısı cihaz teslimi değildir.
- Bildirim workflow'u yalnız yarım saatlik schedule/push ile çalışıyordu; normal Threads yayıncısı ve ayrı ToonZone sezon işi tamamlanmasıyla tetiklenmiyordu. Her iki yayın işinin main/aynı depo tamamlanma olayını ekle. Başarısız işte de doğrulanmış kısmi yayınları oku. PR kaynaklarını reddet, ortak concurrency ve mevcut kalıcı tekilleştirmeyi koru.
- Yarım saatlik schedule yedek olarak kalır. API kimlik GET, post ID ve timestamp doğrulaması korunur; sosyal medya yayını yeniden tetiklenmez. Penguen yetki sorunu bu zamanlama düzeltmesiyle çözülmez.
- Test: mevcut platform bildirim ve kalıcı geçmiş regresyonları. Canlı kabul: yeni main workflow'unda Telegram sunucu alındısı ve yayın sonrasındaki workflow_run tetiklenmesi ayrı kontrol edilir. Geri alma: yalnız bu workflow tetikleme değişikliğini geri al; geçmiş kayıtlarını silme.

### 5 Kasım 2026 — Instagram ilk sezon kampanyası ve Facebook kontrolü

Kullanıcı ilk sezon kampanyasını Instagram için de açıkça istedi, ardından Facebook'un kontrolünü istedi. Tek seferlik ayrı Instagram intent/result arşivi hazırlanır. ToonZone Page kimliği 1298191963387372 ile bağlı Instagram kimliği doğrulanır. 48 parça sırayla hazırlanır, her parçanın kendi kapağı ve mevcut Instagram uyumluluk işlemi kullanılır. Gönderi ID'si, açıklama, video türü ve kalıcı bağlantı doğrulanmadan sonraki parçaya geçilmez. Hata sonrası belirsiz POST otomatik tekrarlanmaz. Facebook'ta yalnızca sayfa ve görünen video geçmişi okunur. Telif kararının kaldırıldığı varsayılmaz.

Instagram run 42011620370 failed before upload on the first part with ValueError. The campaign supplied cover.png, while generate_part_cover requires the exact MP4 stem plus .png. No upload call was reached. Correct the destination filename and allow only this exact run's identity/source-matched reserved records to be re-bound, preserving an audited_prewrite_run receipt. Facebook audit in the same run succeeded: page published, 47 visible videos, 13 distinct first-season caption/part slots. This caption coverage is not a byte-level source mapping or proof that copyright restrictions are cleared.

### 5 Kasım 2026 — Kullanıcının sezon kampanyalarını iptali ve geri alma talebi

Kullanıcı kapak ve profil sırasını reddetti, yeni sezon yayınlarının hemen durmasını ve bu çalışmaların yayımladığı gönderilerin silinmesini istedi. İki sezon workflow'u kapatıldı, iki script'in normal komut satırı yayın girişi durduruldu. Normal ToonZone rotası zaten durdurulmuş durumda. Silme kapsamı iki kampanyanın kayıtlarındaki 11 doğrulanmış Instagram ve 48 Threads gönderisidir. Önceden var olan gönderileri bu kampanyaya dahil etme. Platformun DELETE kabulünü ve kalan profil kayıtlarını ayrı doğrula. Yayın geçmişini sıfırlama.

### 5 Kasım 2026 — İlk üç bölüm için doğru Drive kapakları

Kullanıcı ilk üç bölümün her birinde Part 1–4 sırasını açıkça istedi. Salt-okunur 42073054186 çalışması 48 birebir PNG eşleşmesini ve hâlâ görünen önceki 11 Instagram gönderisini doğruladı. Kapağın tam görseli 1086×1448, yani 3:4 oranında. Önceki genel kapak işlevi kapağı 9:16 kırpıp yatay videonun boyutundaki tuvale bindiriyordu. Bu, bölüm/part yazılarını kesebilir. İsteğe bağlı tam-kapak yolunda hem video hem kapak 1080×1920 tuvale sığdırılır ve kapağın bütünü korunur. Varsayılan eski çağrı davranışı korunur.

Kullanıcıya önceki 11 gönderinin hâlâ durduğu ve bu isteğin yeni kapaklı yeniden yayın olarak uygulanacağı söylendi. Yeni iş yalnız 12 parçaya sınırlıdır, gerçek PNG hash'lerini kaydeder ve ilk kare ile gerçek Instagram thumbnail sonucunu karşılaştırır. Her gönderi doğrulanmadan sonrakine geçmez. Eski 48 parçalık işler kapalı kalır. Yayın öncesinde tam regresyon ve gerçek FFmpeg ilk-kare testi gerekir. CI'daki gdown eksikliği ve yalnız pytest için eklenmiş assert bağımlılığı da test yolunda giderilir.

### 2026-11-05 first-three runner setup delay
Run 42098202220 timed out downloading Ubuntu resolute FFmpeg dependencies from azure.archive.ubuntu.com. Production run 42099396893 also remained before reservation/publication. Recovery pins only this batch to Ubuntu 24.04, reuses available FFmpeg, bounds setup, and cancels the prior worker only after confirming it is still before reservation. A fresh worker must observe cancellation complete and zero prior artifacts before it may proceed. Application code and twelve-part limit remain unchanged. Live publication evidence is still required.

### 2026-11-05 first-three actual binary rejection
Run 42101331359 stopped on S01E01 Part 1 before media_publish. Exact full Drive cover passed prepared-frame verification. Recovery-v3 upload SHA 2f29da25d05d1fb5177f55c0536fd34919c5598c5a077ce3d061f24592f1fa84, 42662976 bytes, container 17911372950580142 received binary HTTP400 and remained IN_PROGRESS. Actual owned media audit in the first-three live progress workflow at 20:21:59 UTC had no new matching posts. Preserve the attempted intent; no blind retry. An explicitly upload-only compact-profile diagnostic will preserve hashes and detailed sanitized Meta error, with publish=False hardcoded and no media_publish. Two probe safety tests plus three existing first-three tests passed. No publication success is claimed.

### 2026-11-05 compact alternate upload verified
Run 42103999147: full exact Drive cover plus compact profile created 13739862-byte SHA ba66c2e11e73f253b6abea68009ab5e1efd8ed4afb48c982e9ab16f314e039fb. Binary HTTP200 accepted all bytes; container 17911374060580142 reached FINISHED. publish=False; no media_publish. This establishes an accepted alternate bitstream, not the precise underlying Meta rejection reason. Resume binds source, caption, cover, distinct upload SHA and the exact prepared JPEG from this probe. Failed prior attempt stays nested in history; first publication resumes only the ready probe container; remaining untouched reservations use compact. Actual published thumbnails must match before proceeding. 29 focused tests passed, including no re-upload on resume and mismatched-probe rejection.

### 6 Kasım 2026 — Gece kurtarması ve doğrulanmış kuyruk tıkanmaları

- Kanıt: normal schedule [42107189260](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42107189260), job127524988967, Meta planından sonra YouTube accepted doğrulamasında RuntimeError. Arşiv 13452308015 Tarladaki `QrfyrpMibTM` kimliğini accepted/public/uploaded olarak koruyor. Son GET sonucu henüz bilinmiyor; tekrar upload yasak. YouTube GET doğrulama sebebini sabit etiketle kaydet; provider failed/rejected/deleted dönerse ID'yi held tut ve yeni insert yapma. Eksik/yanlış video kimliği hâlâ başarısızdır, başarı veya silinme kabul edilmez.
- Aynı koşumda Gönle eski açıklama eşleşmesi ve Daily Laugh `192.mp4` eski Instagram ikili yükleme HTTP400 kaydı tüm bağımsız adayları durdurdu. Sadece done açıklama çakışması, tam kimliği bağlı pre-media_publish HTTP400 veya external_post_attempted=false held kaynağı atlanabilir. Diğer gerçek belirsiz POST'lar kilitli kalır; önceki done/held/uncertain kayıtları ve post ID'leri korunur. Film/ToonZone bölüm sırası açılmaz. Altı kısmi kayıt senaryosu yeni regresyonda denetlenir.
- Görsel dedupe `held` üretiyor ancak incident writer bu durumu tanımadığından ikinci ValueError oluşabiliyordu. Held ve visual_duplicate_review artık açık bir kaynak inceleme engeli olarak sayılır; yeniden yayın izni değildir.
- Film Facebook iki hedefte `Bickin_Part_8 (1).mp4`, Part3 görsel izleriyle çakıştığından held; kaynak baytları karşılaştırılmadan kilit kaldırılmaz. Yeni salt-okunur audit mevcut container durumları, YouTube ve tam Drive kaynak hash'lerini raporlar; hiçbir platform yazımı veya state mutasyonu yapmaz.
- Önceden açık #93'ün salt-okunur post-history 5/15 saniye yeniden kontrolü bu kurtarmaya dahil edilir. Başarılı sonuçlar yeniden sorgulanmaz; POST veya ledger tekrarı yok. Olay raporu Meta son kontrolünü ve YouTube adımlarını ayrı kaydeder.
- [42105016955](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42105016955) job127517888709 ilk üç bölümü 12 gerçek ID ve ayrı kapak mesafeleriyle 20:59:15 UTC'de tamamladı. Önceki progress audit yalnız ilk dokuz paylaşım sırasında çalışmıştı; yeni audit tam 12 benzersiz slot, kronolojik sıra ve gerçek thumbnail eşleşmesini zorunlu tutar ve kampanya bitince otomatik tetiklenir. Eski 11 reddedilmiş Instagram gönderisinin silindiği iddia edilmez.
- Geri alma: bu kod değişikliklerini geri al; geçmiş, intent, kaynak ve post ID'leri silme. Test/CI ve yeni canlı audit sonuçları ayrı eklenecektir.

- Gece PR109 CI safety job127572997779 aynı ubuntu-latest FFmpeg kurulumunda gecikti. Aktif yayıncı, advanced CI ve gelecekteki backup acceptance ubuntu-24.04 sabitlenir; kurulum süre sınırı5dakika. Bu medya aktarımı401/400 hatasıyla aynı neden değildir.

### 6 Kasım 2026 — Gece canlı kanıtı ve dış kaynak engelleri

- PR109 bütün kontrol işleri geçtikten sonra `82c55735ddf025709fa6e9b17ce30b09ae9cdceb` ile birleştirildi. Main CI42121396220 başarılı. Yeni progress42121396013 tam12/12, doğru kronolojik sıra ve tüm gerçek kapaklar için cover_verified=true doğruladı. Yeni yayın yapılmadı.
- Salt-okunur audit42121396203: Tarladaki YouTube `QrfyrpMibTM` mevcut owner-authenticated videos.list yanıtında yok (`youtube_video_unavailable`); silindi/ret yedi varsayımı yoktur. Bu ID'yi held/video_unavailable tutup yalnız GET ile tekrar kontrol et. Aynı doğrulanmış unavailable sonucu her normal tick'te yeni hata bildirimi üretmez; ilk durum değişikliği hata olarak kalır. Wrong-ID/kanal/bozuk yanıt veya yeni auth hatası yine gerçek başarısızlıktır. ID tekrar public/processed görünürse yeniden insert olmadan done olur. Bağımsız YouTube audit held ID'yi de kontrol ederek eksik videoyu gizlemez.
- Aynı audit Daily Laugh192 container18153199159523437 IN_PROGRESS; Tarladaki192/194 ve Penguen193 eski container'ları EXPIRED gördü. Bunlar otomatik yayın/retry yetkisi değildir. Gönderi ve intent delilleri korunur.
- Film kaynaklarının tam baytları: Part3 ve `(1)` hash `dd025d4e163a467696fc55d7c4e1ed0f7d323ddb2e3ebd751c4c79ac30f4635d`, 11426135bayt; Part8 ve `(1)` hash `2366ca629ae0a41577e4f89b36f07f3367937971de969a846abea9702f273813`, 11434180bayt. Yerel FFmpeg ile15/60/120/165s kareleri görsel olarak karşılaştırıldı: aynı sahneler, yalnız Part3/Part8 üst yazısı farklı. Bu nedenle görsel koruma doğru bir kaynak tekrarını durduruyor; kod kilidini kaldırma. Katalogdaki iki Part8 sürümü aynı baytları taşıyor; bu katalogda doğru Part8 alternatifi doğrulanmadı. Doğru kaynak kullanıcı tarafından sağlanmadan bölüm atlama veya önceki sahneleri yeniden yayınlama yok.
- Penguen Threads401 ve önceki11 Instagram silme code10 engelleri önceki canlı kayıtlardan hâlâ ayrı çözüm gerektirir. Token değerleri okunmaz/değiştirilmez; kod başarılı diye bu hesap izinlerinin düzeldiği söylenmez.


### 6 Kasım 2026 06:53 TRT — sırasız yerel hazırlık hatası kuyruğu

- Yeni gerçek run42156394826/job127691459502 Daily Laugh195.mp4 için FFprobe CalledProcessError ile ilk Meta POST öncesinde durdu; incident iki ready kayıt,0 yeni post ve0 yeni uncertain kaydetti. Eski192/193/194 Instagram intentleri korunuyor.
- Kök kod açığı: aynı gün yerel-only ready hatasını atlayan mevcut yardımcı yalnız Tarladaki/Penguen kabul ediyordu; Daily Laugh/Gönle aynı dosyada her tick tekrar takılabiliyordu. Aynı dar kanıt koşulları bu iki sırasız feed için de uygulanır: tam kaynak ID/ad/route/platform eşleşmesi, önceki run, her aktif platform ready, aynı yerel gün, source_or_cover_preparation_failed ve safe_to_repost=true. Böylece başka temiz aday incelenebilir.
- Mevcut kayıt değiştirilmez; kesin bozuk kaynak iddiası veya kalıcı karantina yok. Ertesi yerel gün eski davranış korunur. Film/ToonZone ve belirsiz POST kapsam dışıdır. Normal schedule dışında yayın tetiklenmez.
- Güncel tüm-hesap engagement audit42159138525:11 aktör,36 kaynak,199 aday; dry_run/writes=0, save unsupported, repost disabled ve368hold korunuyor. Inbox42156714869 reserved_replies=0/server_acks=0; butona basıldı iddiası yok.
- Geri alma yalnız bu iki route eklemesini revert etmek; state/intent/claim/artifact silinmez. CI ve sonraki normal schedule kaynak/post kanıtı ayrı değerlendirilir.

### 6 Kasım 2026 09:50 TRT — Penguen 250.mp4 kaynak zaman çizgisi

- Gerçek normal schedule [42175366213](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42175366213), job127752476922, Penguen `250.mp4` için ilk Meta POST öncesinde `video_fingerprint_invalid_frame` ile durdu. Sonuç artifact13483640536 iki platformu da `ready / source_or_cover_preparation_failed / safe_to_repost=true` korur; yeni belirsiz POST yoktur. Önceki dokuz uzlaştırılmamış intent değiştirilmedi.
- Salt-okunur tam indirme kaynak kimliği `1lBoXFmmxvlfL6lUhxk4Qc_eZ6WHANb2I`, 6.917.600 bayt ve SHA256 `513d67961759f96a7e64196bf2adbe4d8ce01f0acb3b0257a5acce71a27ea1b0` ile üretim kaydını eşledi. FFprobe: varsayılan hareketli H264 akışı 540×960, 300 kare, 10s; AAC ses ve container 17,903991s. Uzun PNG akışı `attached_pic=1`, gerçek hareketli video değildir. Mevcut üç örneğin 15,218s konumundaki sonuncusu FFmpeg exit0 / sıfır bayt döndürdü. Dosyanın tümü bozuk veya Meta tarafından reddedilmiş denmez.
- Güvenli aksiyon: mevcut yerel-only karantinayı yalnız bu kesin kaynak/ad, üretim run'ı ve kayıtlı SHA için günler arasında koru; her aktif platformun yerel-only ready koşulları yine zorunlu. Böylece aynı kaynak her yeni gün tekrar denenmez ve başka bağımsız Penguen adayı incelenebilir. Yeni Drive kimlikli düzeltilmiş kaynak bu istisnaya girmez. Görsel dedupe algoritması/sürümü, ses, kapak, seri sırası, eski intent ve gönderi kimlikleri değiştirilmez. Aynı kimlik altındaki içerik değişimi bu karantinayı kaldırmaz; düzeltilmiş kaynak yeni kimlikle gelmelidir.
- Test: kesin artifact ve mevcut saf yardımcı ile aynı gün atlama ve state değişmezliği doğrulandı. Ek regresyon sonraki gün için exact SHA/run, iki platform, yanlış/eksik hash, değişmiş run/dosya/kimlik, belirsiz/yayımlanmış durum ve eksik platformu denetler. Yeni adayın gerçekten yayımlandığı ancak sonraki normal schedule ve post ID/history ile kabul edilebilir; zorla yayın tetiklenmez. Geri alma yalnız bu yeni kaynak istisnasını kaldırmaktır; geçmiş silinmez.
- Bu koşumun ayrı başarıları operations artifact13482584457, checked_at `2026-11-06T06:42:36+00:00` ile expected_account_video_history doğrulandı: Tarladaki274.mp4 Facebook2120720978870298; Gönle158.mp4 Facebook1430768149184951 ve Instagram18117256385466581. Telegram4ACK ve ntfy4ACK, cihaz teslimatı doğrulanmadı. Gönle YouTube `_EuyFuxGz-k` yalnız accepted_processing_pending; public/processed kabulü değildir. Threads takip koşumu42176184684 Gönle18113357834231316 doğruladı; bildirim42176293577 iki Telegram sunucu ACK/0delivery failure kaydetti. Bunlar genel FAIL sonucunu veya diğer hesap engellerini çözülmüş yapmaz.

### 6 Kasım 2026 11:35 TRT — YouTube kimliksiz belirsiz yükleme denetimi

- Yeni normal schedule [42183664070](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42183664070), job127778830588, Tarladaki275.mp4 YouTube yüklemesinde `ResumableUploadError` aldı. Result artifact13487390161 kaynağı `1Dd3zYf2Kd6S4n77wbMj28OB4DZuq_5ON`, kanal `UCrUF3mT4oF26JNBLcyKPcGQ`, durum `uncertain`, boş post ID olarak korur. Hata türü tek başına token/izin veya platform kota nedenini kanıtlamaz. Sonucun belirsizliği nedeniyle yeniden videos.insert yasak; eski QrfyrpMibTM held/unavailable kaydı da ayrı kalır.
- Kod açığı: bağımsız YouTube GET denetimi yalnız accepted/held durumlarını okuyordu; kimliksiz uncertain kaydı görünmüyordu. Salt-okunur ek denetim ledger anahtarı/route/source ve beklenen kanal bağını doğrulamalı, owner uploads listesinde tam kaynak işaretini tüm sınırlı sayfalar boyunca aramalı, yalnız tek eşleşen ID için videos.list ile hesap/işaret/işlenme/görünürlüğü kontrol etmelidir. Boş, çakışan, bozuk veya eksik sayfalama sonucu başarı sayılmaz. Kayıt rapora eklenir; yayın state'i, uncertain kilidi ve intent asla değiştirilmez. Yalnız rapor kanıtı bulunması otomatik yayın veya yeniden deneme yetkisi değildir.
- Aynı koşumda Penguen250 kaydı aynen korunarak276.mp4 seçildi. Operations artifact13485909819 checked_at `2026-11-06T08:01:42+00:00`, Penguen Facebook1102762669314744 ve Instagram18133218931878910 için expected_account_video_history doğruladı. Bu aynı-gün kuyruk ilerlemesidir; PR124'ün günler arası koşulunun canlı kabulü değildir. Tarladaki275 Instagram17996962430841116 ve Film Bickin Part6(1) Instagram18139222153730766 da ayrı doğrulandı. Meta4 yeni confirmed/0 yeni uncertain, Telegram5ACK+ntfy5ACK; telefon teslimatı doğrulanmadı. Penguen YouTube -PYZ9v0qvDQ o sırada accepted_processing_pending; yeni GET sonucu ayrıca gerekir.
- Önceki bağımsız YT audit42183761613/job127779231515, Gönle_EuyFuxGz-k public_processed_verified, TarladakiQrfyrpMibTM unavailable gördü; genel FAIL kısmi Gönle başarısını gizlemez. IG salt-okunur42182155549 eski container17910279864580142 için PUBLISHED gördü ancak yeni post ID/source/history uzlaştırması yoktur; kapaklı yeni kampanyanın parçası sayma ve yeniden yükleme yapma.
- Test ve kabul: kaynak/kanal bağları, tek/tam işaret, çakışma, eksik sayfalama, bozuk yanıt, gizli/bekleyen video ve state değişmezliği regresyonları; sıfır upload/write. Canlı arama sonucu ancak yeni GET-only workflow artifact'ından kabul edilir. Geri alma yalnız yeni bağımsız rapor yolunu kaldırır; yükleme kayıtları korunur.

### 6 Kasım 2026 — Medya kurulum aynası ve salt-okunur engagement kaynağı

- Normal publisher42191411659/job127804077643 FFmpeg kurulumu sırasında beş dakikalık sınırda durdu. Ubuntu24.04 Azure aynası codec2 indirmesinde uzun bekleme ve diğer paketlerde yavaş yanıt verdi; Meta preflight geçmişti fakat verify/plan/intent/publish adımları çalışmadı. Bu bir Meta POST veya hak/token hatası değildir. Normal yayın yolunda mevcut ToonZone işleriyle aynı resmi Ubuntu mirror listelerini, HTTP/HTTPS20s sınırını, tek paket indirme tekrarını ve no-install-recommends kurulumunu kullan. Beş dakikalık toplam step sınırı korunur ve iki medya aracı da kontrol edilir. Bu değişiklik yayını zorla tetiklemez; sonraki normal kurulum canlı kanıtı gerekir.
- Engagement42199268338/job127830332284 aynı önceki başarısız koşumda link-state-result bulamadı ve source_result_artifact_missing ile durdu; writes0/hiçbir POST yeniden denenmedi. Son tamamlanmış koşumu seçen salt-okunur güncel-pencere denetimi için dar fallback: yalnız schedule+dry_run+latest, kesin eksik result ve hiç intent yokken, aynı doğrulanmış publisher'ın tek meta job'ında medya-setup failure ve bütün state/intent/yayın adımlarının skipped kanıtı varsa önceki geçerli sonucu incele. Atlanan run ID'leri raporda kalır. Malformed/expired/duplicate artifact, auth/HTTP arızası, publish belirsizliği, explicit source, apply veya push bu istisnaya girmez.
- Ayrı normal koşum42198462083/job127827532269 SUCCESS: operations13492734201 checked_at2026-11-06T10:08:33Z,6 yeni Meta ID için expected_account_video_history verified. Tarladaki275 Facebook1893609838668439; Penguen277 Facebook1174559021571282+Instagram17907361233350571; Gönle159 Facebook4194249514206002+Instagram17916271842282127; Film Bickin Part7(1) Instagram18111308309617075. Incident0error/0newuncertain,9eski Meta intent korunur. Telegram6ACK+ntfy6ACK/0deliveryfailure; cihaz teslimatı bilinmiyor. PenguenwZqJe18vd58 ve GönleyBeSvHwt5n0 YouTube o anda accepted_processing_pending; henüz public/processed denmez.
- Test/kabul: kaynak seçimi regresyonları kesin pre-state job kanıtını ve apply/bozuk arşiv retlerini doğrular. Workflow YAML ve shell sözdizimi denetlenir; mevcut dedupe, hak, token, sıralama ve POST kilitleri değişmez. CI ile canlı kabul ayrıdır. Geri alma yalnız installer/fallback değişikliklerini kaldırır; state ve alındılar korunur.

### 6 Kasım 2026 — Yerel hazırlık engelinin YouTube fanout'a taşınması

- PR126 canlı kısmi kabul: normal42207238768/job127856838503 resmi archive.ubuntu.com üzerinden FFmpeg kurulumunu tamamladı ve plan/yayın adımlarına ulaştı. Engagement42206832287/job127855586177 kesin setup-failure42199558773 koşumunu raporda atlayıp başarılı kaynakla tamamlandı:11 aktör,37 kaynak,204 aday,all/dry_run/writes0;408save unsupported/repost disabled,368hold korunuyor. Bunlar yerel kurulum/kaynak seçimi düzeltmesini doğrular, gerçek beğeni veya tüm sistem başarısı değildir.
- Yeni gerçek hata: aynı42207238768 Tarladaki278.mp4, kaynak1T3nTIgRJwmgeQOkCwZrvezl61tic3aI2 için görsel fingerprint karesi alınamadı ve Meta POST öncesi durdu. Result13498090295 Instagram kaydını aynı run/file/source ile ready/source_or_cover_preparation_failed/safe_to_repost=true tutar; kaynakSHA dba86d78a9590d17c129d80b49c62d8f0441cd1839c1b2a8c105c05ea0f983dd. Dosyanın bütünü bozuk veya hata nedeninin Penguen250 ile aynı olduğu ayrıca kanıtlanmadı.
- YT intent'i Meta yerel hazırlığından önce oluşturulduğundan, sonraki YouTube adımı bu güncellenmiş yerel engeli kontrol etmeden aynı kaynağı videos.insert'a taşıdı; ResumableUploadError sonrasında yeni uncertain/noID korundu. Bu hata auth/kota veya dosyanın reddedilme nedenini tek başına kanıtlamaz. Eski ve bu yeni uncertain kayıtlarını tekrar yükleme veya hazır durumuna çevirme.
- Güvenli yeni kapı yalnız yeni current-run/attempt YT intent'ine uygulanır: kesin ledger key/route/source/file/kanal, aynı tek plan ve onun bütün aktif Meta platformlarında aynı-run local-only ready failure kanıtı varsa YouTube'u yüklemeden held/source_local_preparation_failed/external_post_attempted=false olarak kaydet. Kanıt makbuzu platformlarıyla korunur. Eski accepted/held ID'li GET uzlaştırması devam eder. Kaynak veya kapak hazırlığı engeli, bütün dosyanın bozuk olduğu iddiası değildir; kaynak incelemesi gerekir. Bu yerel held sınıfı bağımsız denetimde açık adla görünür ve başarılı yayın sayılmaz.
- Test/kabul: aynı kaynakta upload/download/Google istemcisi çağrılmadığı, ters kimlik/run/file/platform/durum/eksik-plan durumlarının yanlış kaynakla bağlanmadığı ve mevcut ID uzlaştırmasının korunduğu doğrulanır. Üretim state'i elle değiştirilmez; yeni kapının canlı kabulü sonraki normal koşumda ayrıca gerekir. Geri alma yalnız yeni pre-upload kapısı ve rapor sınıfını kaldırır; kayıtları silmez.
- Ayrı GET audit42204436506/job127847501188 2026-11-06T10:40:47Z PenguenwZqJe18vd58 ve GönleyBeSvHwt5n0 public_processed_verified; önceki7 uncertain marker yok ve QrfyrpMibTM unavailable. Sonraki278 belirsizliği bu audit'ten sonra oluştu; toplam belirsiz kayıt sayısını eski7 ile sınırlama. YeniToon4–8yayını/hak onayı veya gerçek Telegram buton basımı kanıtlanmadı.

### 6 Kasım 2026 — Platform alt kümesinde yerel hazırlık karantinası

- Yeni gerçek normal42213569368/job127877900340 yine Tarladaki278.mp4 Instagram-only planını seçti ve fingerprint karesi alınamadığı için Meta POST öncesinde durdu. Result13499403251 aynı kaynak1T3nTIgRJwmgeQOkCwZrvezl61tic3aI2 için yalnız Instagram ready/local-preparation-failure/safe_to_repost=true kaydı gösterir; Facebook için aynı kaynak anahtarında kayıt yoktur. Önceki278 uncertain YouTube kaydı korundu; bu koşumda yeni YouTube POST olmadığı, PR127'nin yeni yerel held kapısının canlıda çalıştığını tek başına kanıtlamaz (eski uncertain zaten yeniden gönderilmiyor).
- Kök seçim boşluğu: ilk karantina kontrolü route'un bütün available platformlarını kullanıyordu; platform başına geçmiş, kota ve diğer kontrollerden sonra gerçekte yalnız Instagram pending olabiliyordu. Olmayan Facebook ready-failure kaydı yüzünden erken kontrol false oluyor, aynı yerel hata tekrar seçiliyordu. Bu, önceki bütün-platform guard'ını gevşetme gerekçesi değildir.
- Güvenli düzeltme: mevcut erken kontrolü koru; tüm uzak geçmiş/uncertain/skip kararları ve gerçek pending listesi hesaplandıktan sonra, açıklama süslemesi veya yeni intent rezervasyonundan önce aynı dar yardımcıyı pending alt kümesi için bir kez daha uygula. Her gerçekten bekleyen platform kesin kaynak/ad/route/platform/önceki-run/yerel gün/ready/localfailure/safe kanıtını yine sağlamalıdır. Seri rotaları, eksik pending kanıtı, başka gün, current-run failure veya belirsiz POST bu istisnaya girmez. Done/uzak açıklama eşleşmesi tek başına yayın veya source eşitliği kanıtı sayılmaz; bütün mevcut geçmiş kontrolleri önce çalışır.
- Test/kabul: planner regresyonu Facebook'u normal kontrollerle dışarıda bırakıp başarısız Instagram kaynağını koruyarak sonraki temiz adayın seçimini kanıtlar; gerçek gönderim çağrısı yoktur. Eski kaynak kaydı değişmez, belirsiz intent ve seri sırası korunur. Canlı farklı kaynak/post ID kabulü sonraki normal schedule'da ayrıca gerekir; zorla yayın yok. Geri alma yalnız ikinci guard'ı kaldırır, state/claim/history silmez.
- Son engagement42213272919/job12787698766211actor/36source/199candidate,all/dryrun/writes0,398unsupported/disabled ve368hold. Son inbox42217048965/job1278895577350reserved/0ACK. Tracked42210591803/job127867985374 ToonZone2026-11-06 route_not_authorized/disabled; eski2026-10-27 healthy4/4 çıktısı bugünkü hak/yayın kabulü değildir. Yeni hata bildirimi gönderilmedi; yayıncı kendi mevcut tekrarlı alındısını bastırdı (0TelegramACK/0ntfyACK,duplicate_messages_suppressed1).

### 6 Kasım 2026 — Tarladaki278 tam kaynak incelemesi

- Önceki varsayım bağımsız doğrulandı:1T3nTIgRJwmgeQOkCwZrvezl61tic3aI2 kaynak GET'i6.032.519bayt ve üretimle aynı SHA256dba86d78a9590d17c129d80b49c62d8f0441cd1839c1b2a8c105c05ea0f983dd. H264720×1280/30fps/130kare hareketli akış4,333333s, AAC/container19,390s; uzun PNG attached_pic=1. Mevcut sampler2,909s→72bayt,9,695s→0bayt,16,482s→0bayt; üç FFmpeg çağrısı da exit0. Aynı zaman çizgisi hata sınıfı bu kaynak için artık kesin; bütün MP4 bozuk veya Meta tarafından reddedildi denmez. PNG'yi hareketli video yerine kullanma, sesi kesme veya dedupe algoritmasını gevşetme.
- Run42222196393/result13504173366 kaynak için hem Facebook hem Instagram'ı aynı run/day/file/SHA ile ready/source_or_cover_preparation_failed/safe_to_repost=true kaydetti. Mevcut independently-audited kaynak istisnasına yalnız bu exact kaynak/ad/run/SHA eklenir; sonraki günlerde de aynı yerel hatanın tekrar denenmesini önler. Bütün aktif/pending platform koşulları yine zorunlu, kayıtlar değiştirilmez. Aynı Drive kimliği altında sonradan değişen dosya bu eski kanıtı otomatik kaldırmaz; yeni kimlikli düzeltilmiş kaynak istisnaya girmez.
- Test: sonraki gün aynı iki platformun kesin kanıtıyla karantina ve değişmezlik; yanlış hash/run/dosya, uncertain, eksik platform veya yeni source ID retleri. Eski YouTube belirsizliği, seri sırası ve POST kilitleri korunur; canlı farklı kaynak seçimi/post ID kabulü ayrıca gerekir. Geri alma yalnız bu kaynak istisnasını kaldırmaktır. Yeni yayın veya state/claim değişikliği tetiklenmedi.


### 6 Kasım 2026 18:15 TRT — YouTube yükleme hata kanıtının ayrılması

- Normal [42232596827](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42232596827), job127941969528, Tarladaki280.mp4 / kaynak1EJQ1e7u8Hp_pXK1E-rhlDH_AFwUHlNhV için YouTube ResumableUploadError ve uncertain/noID bıraktı. Önceki sekiz kimliksiz uncertain korunur; toplam dokuzdur. Meta'nın aynı kaynakta başarı vermesi YouTube hatasının medya, token veya kota nedenini kanıtlamaz. Köprü yalnız exception türü ve genel read_or_auth_failed yazdığından upload aşamasının sağlayıcı neden kodu kayboluyordu.
- Dar tanı düzeltmesi yalnız yeni gerçek upload_video çağrısı hata verip kayıt uncertain/noID kaldığında sınırlı JSON'daki error.errors[].reason değerlerini kesin kanonik izin listesiyle ayıklar; HTTP durumu yalnız 400–599 gerçek int ise tutulur. Ham gövde, mesaj, URL, header, token ve bilinmeyen neden dizeleri kaydedilmez. Bozuk/büyük/karışık yanıt bilinmeyen kısmını korur. Bu kanıt tek başına kök neden teşhisi veya tekrar yükleme izni değildir. Kimlik/download hataları ile kabul edilmiş ID'nin GET uzlaştırması upload hatası olarak etiketlenmez.
- Aynı koşumun ayrı Meta sonucu operations13509128671 checked_at2026-11-06T14:24:15Z ile dört ID/history doğruladı: Tarladaki280 FB1508089217807025/IG17952734361341887, DailyLaugh197 FB2993579024350823/IG18149233588494426. Dört Telegram ve dört ntfy sunucu ACK,0deliveryfailure; cihaz teslimatı doğrulanmadı. Bu kuyruk ilerlemesi kullanıcıya daha önce bir kez bildirildi. PR128'in IG-only alt kümesi veya PR129'un günler arası kabulü diye sunulmaz. DailyLaugh YouTube5GkRtKqUUU4 accepted_processing_pending ayrı GET kanıtı bekler.
- Test: tanınan ve bilinmeyen API nedenleri, bozuk/büyük JSON, gizli metin redaksiyonu, geçersiz HTTP durumları, kimlik/download/GET ayrımı ve uncertain/noID sonrasında ikinci upload olmaması. Mevcut state/intent/claim/seri/hak/token/retry davranışı değiştirilmez. Geri alma yalnız tanı yardımcısı ve çıktı alanını kaldırır; eski belirsizlik kayıtları silinmez. Gerçek sağlayıcı neden kodu sonraki normal schedule'da ayrıca doğrulanmalı; yayın veya test mesajı zorla tetiklenmez.
- Son inbox42234582081/job127948785343 14:31:03Z reserved_replies0/server_acks0; butona basıldığı kanıtlanmadı. Notifier42238634307/job127962779866 14:58:26Z dokuz hesap/0newACK, Penguen Threads401. Yeni ToonZone4–8 hak/dispatch kanıtı yok; bilinen dış engeller için tekrar kullanıcı bildirimi gönderilmedi.


### 6 Kasım 2026 20:15 TRT — Upload tanısının ilk canlı kanıtı

- Normal [42252414672](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42252414672), job128010694506, main1141a970 ile Tarladaki282.mp4 / kaynak1aIDZZqM9KwnH7usB7nXBTX4xJIuGjRTx yüklemesinde16:34:45UTC ResumableUploadError aldı. Result13521268791 gerçek yeni uncertain/noID kaydında upload_error={http_status:403,reasons:[forbidden],unrecognized_reason:false} korur. PR130 tanısının ilk canlı kabulüdür; sağlayıcının reddi doğrulandı, kesin neden doğrulanmadı. Resmî videos.insert hata listesinde forbidden genel kodudur; insufficientPermissions, quotaExceeded ve uploadLimitExceeded ayrı nedenlerdir. Token yenileme, Studio kısıtı, kota veya medya teşhisi çıkarılmaz. On eski uncertain korunur; toplam11 uncertain ve ayrı QrfyrpMibTM held/unavailable vardır. Hiçbiri yeniden yüklenmez.
- Operations13520918995 checked_at2026-11-06T16:35:26.601151Z üç Meta ID'yi expected_account_video_history ile eşledi: Tarladaki282 Instagram18575264341074070; Penguen283 / kaynak1yAGqx21RJBONF-Dy91SmArK5jDWT1YIM Facebook1691117255924919 ve Instagram18414567661093237. Incident13520654183 üçconfirmed/0newMetauncertain,9eskiMetaintent ve1YTerror korur. Telegram3ACK+ntfy3ACK/0deliveryfailure, cihaz teslimatı bilinmiyor. Bu koşumda PR127 yerelheld, PR128 IG-only altküme veya PR124/129 günler arası pozitif kabulü görülmedi.
- Ayrı GET audit42252785759/job12801212721216:29:42UTC önceki10 uncertain işaretini bulamadı; kesin yokluk/silindi kanıtı değildir, state_modified=false/uploads0. GönleJkZNRKgKdXw ve DailyLaughNf4cp4qfipE public_processed_verified; genelFAIL bunları gizlemez. Bu audit282uncertain oluşmadan önceydi;11. kaydı kontrol etti denmez. Penguen_AM9pIBNCmY16:35UTC accepted_processing_pending; güncel public GET kanıtı ayrıca değerlendirilir.
- Engagement42256223321/job12802410814716:52:02UTC11aktör/38kaynak/209aday/all/dry_run/writes0;418saveunsupported/repostdisabled ve368hold sürüyor. Inbox42256315037/job12802433283216:52:10UTC0reserved/0ACK. Yeni ToonZone4–8 dispatch/hak onayı yok. Erişilebilir yeni kod arızası veya kesin zorunlu insan adımı saptanmadı; bilinen engeller tekrar bildirilmedi. Hak, secret, state/claim/ledger veya yayın kapıları değiştirilmedi; yeni yayın zorla tetiklenmedi.

### 7 Kasım 2026 — Üretilen TXT'lerin stok sayımında görünmemesi

- Normal publisher run [42295538387](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42295538387) 2026-11-07 00:18 TRT stok raporu ToonZone için 159 yerel TXT üretilmiş olmasına rağmen `remaining=0`, `missing_txt=113` gösterdi; Daily Laugh için 117 üretilen TXT'ye rağmen 20 eksik TXT sayıldı. `content_stock.build_stock` yalnız Drive kataloğundaki TXT'leri sayıyordu.
- Güvenli düzeltme: sadece aynı kaynak rotasına ait üretilmiş klasördeki MP4 ile tam aynı adlı TXT'yi say; dosya yoksa eksik tut. Sıra, uzak gönderi geçmişi, belirsiz intent ve kaynak/kapak kalite kontrolleri değişmez.
- PR #92 eski base'e dayandığı için güncel main'e doğrudan alınamadı. Düzeltme güncel main üzerine yeniden tabanlandı; yalnız yerel birim testleri ve GitHub CI geçerse kabul edilir. Kod değişikliği hak onayı veya yayın kapılarını açmaz; canlı stok kabulü sonraki normal koşumda doğrulanmalıdır.


### 7 Kasım 2026 — Değişmeyen engelin günlük bildirim tekrarı

- Normal42295538387/job128159685978 yeni günün state kanıtını geri yükledi ve DailyLaugh200.mp4 için iki Meta postu doğruladı; operations13541397839 checked_at2026-11-06T21:20:26.852096Z Facebook1630625012093000/Instagram18104424428546959. Bildirim sonucu3TelegramACK+3ntfyACK içerir: iki yayın ve bir engel özeti. Incident13541377745 içindeki üç olay yeni POST hataları değil, önceki Daily192/193/194 unresolved Instagram intentleridir. Eski9Metaintent ve12YTuncertain korunur.
- Kök bildirim davranışı: publisher_alert_history.reserve değişmemiş, uzlaştırılmamış olayları son intent'ten24saat sonra otomatik olarak yeniden gönderiyordu (günlük hatırlatma). Kullanıcı değişmeyen bilinen engeller için tekrar bildirim istemediğinden yalnız bu zaman tabanlı tekrar yolu kaldırılır. İlk yeni olay, farklı olay kimliği ve gerçek done/postID ile çözülüp tekrar oluşan olay bildirim yolları korunur. Yayın alındıları yine tekildir; geçmiş intent, ACK ve observed_runs alanları silinmez. Gönderimden önce intent arşivleme ve belirsiz gönderimi tekrar denememe davranışı değişmez.
- Test/kabul: aynı olay24saat,48saat ve çoklu gün boyunca tekrar rezervasyon üretmez; intent ve alındılar değişmez; ayrı yeni olay ve doğrulanmış çözüm sonrası tekrar bildirilebilir; post bildirimleri ve kanalların ACK akışı korunur. Gerçek bildirim veya yayın zorla tetiklenmez. Geri alma yalnız zaman tabanlı tekrar koşulunu geri getirmektir; arşiv veya yayın state'i değiştirilmez. Sonraki normal koşumda aynı olayın alındısız bastırılması ayrı canlı kabul gerektirir.
- Aynı gecenin günlük raporu42291910213/job128147196133 ölçüm2026-11-06T23:51:54+03:00, teslim2026-11-07T00:00:34TRT:23platformda21görüntülenme ve günlük artış,12haftalık artış,22takipçi/günlük değişim. Meta13/13, genel incomplete; TarladakiYouTubeeksik videolar ve PenguenThreads401/code190 N/A. Genel toplam/günlük/haftalık null; Telegram5/5sunucuACK ve ntfyHTTP200,telefon doğrulanmadı. Bu kısmi rapor tesliminin canlı kabulüdür;23/23istatistik kabulü değildir. Comparison13540268461/arşiv13540891757.


### 7 Kasım 2026 — ToonZone 4–8 kaynak önkontrolü ve ortak yayın kilidi

- Kaynak incelemesi, `toonzone_episodes_4_8.audit` içindeki “complete-source preflight” iddiasının yalnız katalog/kapak kontrolü olduğunu gösterdi: MP4 ilk kez her partın upload adımında doğrulanıyordu. Sonraki bir kaynak bozuksa önceki parçalar yayımlanmış olabilirdi; aynı Drive kimliği altındaki değişen baytlar önkontrolle bağlanmıyordu. Bu, gerçekleşmiş yanlış yayın iddiası değil, kaynak kodunda doğrulanmış bir güvenlik boşluğudur.
- Güvenli düzeltme bütün bekleyen MP4 kaynaklarını salt-okunur indirip mevcut MP4/video denetiminden geçirir; her birinin SHA256 değerini intent ve plana kaydeder. Bütün kaynaklar geçmeden rezervasyon oluşturulmaz. Yayın adımındaki yeni indirme aynı hash ile eşleşmezse kapak işleme ve Meta POST öncesinde durur; eski intent veya bilinmeyen POST sonucu yeniden denenmez. Geçici dosyalar sırayla temizlenir.
- Ayrı kampanya workflow kilidi normal yayıncıyı engellemiyordu. Yalnız `publish` işi, rezervasyondan sonuç arşivine kadar normal `public-drive-recovery` concurrency grubunu paylaşır; salt-okunur audit kendi grubunda kalır. Hak ve benzersiz release kapıları, ilk run-attempt şartı ve otomasyonların zamanlamaları korunur.
- Önceki gerçek audit [42134351087](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42134351087), job127618673760, 6 Kasım00:07:59UTC:20 bekleyen parça,20 tam adlı kapak,0 önceki doğrulanmış kampanya kaydı,0 yeni gönderi; publish işi skipped. Bu önceki audit yeni MP4 hash önkontrolünün canlı kabulü değildir. Son normal42353544044 ToonZone route/rights switch disabled tutar; hak onayı kanıtı yoksa yayın yapılmaz.
- Test: sonuncu kaynak hatasında bütün önkontrolün başarısız olması ve kataloğun değişmemesi; kaynak değişikliği/eksik hash reddi;20hash'in arşiv şemasıyla korunması; normal yayın kilidi ve hak kapılarının değişmemesi. Canlı MP4 önkontrolü yeni salt-okunur audit ile ayrıca doğrulanır. Geri alma yalnız hash önkontrolünü ve yeni job kilidini kaldırır; yayın geçmişini veya kapıları değiştirmez.

### 7 Kasım 2026 — Threads video etkileşimlerinin raporda eksik olması

- Mevcut Threads butonu ve günlük rapor yalnız video görüntülenmeleri/takipçi sayaçlarını sunuyordu; beğeni, yanıt, yeniden paylaşım, alıntı ve dış paylaşım kaydı yoktu. Mevcut buton yeniden yaratılmaz; bu alanlar arşiv, comparison ve günlük Telegram raporuna eklenir.
- Resmî Meta Postman `Get Post Insights` GET kontratı: https://www.postman.com/meta/threads/request/34203612-385abc7d-b3cc-4e5d-9937-ebbe7174e041 (`/{thread_id}/insights?metric={{metrics_post}}`). Meta developer insights sayfası bu oturumda 429 döndü; gerçek hesaplarda metrik erişimi canlı kabul gerektirir.
- Mevcut video kapsamı korunur. Opsiyonel etkileşim GET hatası doğrulanmış views değerini silmez; alan eksikse null/unavailable ve N/A kullanılır. Desteklenmeyen toplu parametre için yalnız HTTP400/code100 halinde sınırlı tekil GET fallback vardır. Auth/rate/transport hatasında istekler çoğaltılmaz. Kısmi sayaçlar tam toplam diye sunulmaz.
- Canlı kanıt (değişiklik öncesi): Threads run42353919231/job128347731818 Tarladaki post18102702257061909, https://www.threads.com/@tarladakifasulye_/post/DfbthcfKD02 verified; Penguen read_http_401_code_190. Notification42354001263/job128347972166 checked9/reserved1/Telegram serverACK1/failures0. Bu ACK telefon okuması değildir. Inbox42355358768 reserved0/ACK0; buton basımının canlı uçtan uca kanıtı bulunmuyor.
- Yerel kabul: 93 test ve17 subtest PASS; eksik değer, gerçek0, kısmi aggregation, opsiyonel GET arızası, desteklenmeyen batch fallback, platform izolasyonu ve mevcut notification dedup regresyonları. Yeni etkileşim sayaçları canlı ölçülene kadar UNVERIFIED; yayın state'i/secret/izin kapıları değiştirilmedi.


## 8 Kasım 2026 — Saatlik Meta etkileşim görevi yalnız deneme modundaydı

- Canlı kanıt: [42521067044](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42521067044): `ENGAGEMENT_MODE=dry_run`, 51 kaynak gönderi, 332 potansiyel desteklenen etkileşim, `writes=0`. Yeşil workflow, gerçek beğeni kanıtı değildir.
- Önceki tekil canlı kabul: [42424976420](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/42424976420): Instagram `like/accepted=1`, Telegram sunucu alındısı; bu yalnız bir adet başarılı API denemesidir.
- Kullanıcının 8 Kasım açık talebi: YouTube'yu sonraya bırakıp Meta beğenilerini deneme yerine çalıştırmak.
- Kontrollü düzeltme: `meta_cross_engagement.yml` planlı aralıkta `single_like` kullanır, en fazla **1 gerçek like / 15 dakikalık çalıştırma**; sadece doğrulanmış kaynak/actor eşleşmesi; ToonZone kaynak önceliği; GitHub intent önce, POST bir defa, belirsiz olayda tekrar yok. Kaydetme/yeniden paylaşma desteklenmediği veya kapalı olduğu için API yazısı yapılmaz.
- Canlı kabul: Workflow CI + merge yeterli değildir. `cross-engagement-result` içinde `accepted`, gerçek API ACK ve Telegram makbuzunu ayrıca kontrol et; hiç uygun gönderi yoksa sıfır yazım normaldir. Provider `368`, `401`, `403`, `429` korumaları kaldırılmaz.
