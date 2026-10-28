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
