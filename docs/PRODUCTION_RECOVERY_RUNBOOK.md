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
| ToonZone kapak yokluğu | [Canlı kaynak denetimi #40067576232](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40067576232) | 159 MP4'e karşı yalnız 48 eşleşen PNG (1. sezon) | 111 adet 2. sezon kapağı kullanıcı tarafından Drive'a eklenecek; kapaksız partı yanlış kapakla gönderme |
| Eski Telegram token/bağlantı hatası | [Başarısız #40066950833](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40066950833) ve [başarılı smoke #40067496169](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40067496169) | Bildirim yok | Secret değerlerini kodda tutma; Telegram sonucu ayrı raporlanır, başarısız bildirim Meta postu tekrar ettirmez |
| Yeşil Actions ama sıfır video | [Başarılı no-op #40066720418](https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/40066720418) | Çalışma sağlığı yayın kanıtı değildir | `NOT DUE`, `NEXT`, `HELD` raporları; yeni post ID'si / gerçek hesabın geçmişi ayrıca görülmeli |
| S1/S2 ToonZone parti sırası / belirsiz Meta sonucu | [Kod güvenlik testleri](../test_public_link_runtime.py) | Çift paylaşım veya yanlış part riski | Önce intent artifact, sonra sonuç artifact; `uncertain` uzlaştırılmadan yeni aynı part denemesi yok |
| Instagram geçmişinde fotoğrafların kota sayılması | [Regresyon](../test_public_link_runtime.py) | Reel sayısı sahte yüksek gözükür | `media_type=VIDEO` şartı |
| Gün sonu izlenme raporu legacy toggle'a bağlı | [Workflow](../.github/workflows/daily_stats.yml) | Meta-only etkin olsa da 23:59 TRT raporu atlanabilir | **Henüz çözülmedi**. `AUTOMATION_ENABLED` açılmadan ayrı Meta-only gerçek izlenme raporu kurulmalı |

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
