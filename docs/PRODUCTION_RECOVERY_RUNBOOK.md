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
