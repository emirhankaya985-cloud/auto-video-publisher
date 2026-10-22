# GPT‑6.1 Sol — Tek Seferlik Üretim Kabul ve Kurtarma Görevi

> **Kullanıcı hedefi:** Bir defalık kapsamlı teknik devralma; aynı sorunlar için tekrar tekrar soru, PR veya başarısız test döngüsü istemiyor. Erişilebilen güvenli işleri gerçekten tamamla; eksik üçüncü taraf hesap yetkisini **bir tek zorunlu kullanıcı eylemi** olarak bildir.
>
> **Bu belge salt-okunur devirdir:** Bunu okumak hiçbir sosyal medya gönderisini, Drive yazımını, Google Sheets senkronunu, NTFY testini veya Cloudflare deploy'unu tetiklememeli.

**Özel depo:** `emirhankaya-AFK/auto-video-publisher`  
**Gözlem tarihi:** 20 Ekim 2026, TRT  
**Başlangıç master:** `d38843ebfcebd220917e64d1f0cad403e9eb16e6`  
**Zorunlu ilk adım:** Kendi oturumundaki güncel `master` SHA'sını, açık PR'ları, workflow sonuçlarını ve PR head SHA'larını tekrar sorgula. Bu dosyadaki başlık/numara/SHA'lar devir anındaki anlık kanıttır. Önce `AGENTS.md`, `README.md`, `SOL_6_1_HANDOFF.md` ve bu belgeyi oku. Önceki ajanların başarı iddialarına güvenme.

## 0. Şu anda asıl bloke eden nedir? (Öncelik P0)

**GitHub Actions runner tahsis sorunu** 20 Ekim günü oluşmuş. Bu, Meta API HTTP 400 veya test kodunun exception'ı ile aynı hata değildir.

| Kanıt | Gerçek gözlem |
| --- | --- |
| [21:15 TRT publisher](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39473234170) | GitHub-hosted runner **atanmış**; 9 adım çalışmış. Job yayın/claim mantığında ayrıca başarısız olmuş. |
| [21:45 TRT publisher](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39477514888) | `runner_id=0`, `steps=[]`, yaklaşık 3 saniyede failure. |
| [22:45 TRT publisher](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39486228780) | `runner_id=0`, `steps=[]`, job başlatılamadı. |
| [22:56 TRT analytics CI](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39487769317) | `no-publish-tests`, `runner_id=0`, `steps=[]`; testler **hiç çalışmadı**. |
| [22:58 TRT yeni analytics CI](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39488048609) | `runner_id=0`, `steps=[]`. Bu **kimlik bilgisiz** CI için önceki asistanın yaptığı **tek kontrollü rerun, deneme #2**, aynı şekilde başarısız. |
| [Film CI](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39488494006) | Alakasız başka PR da `runner_id=0`, `steps=[]` fail. Etki tek PR'a özgü değil. |

Son gerçek çalışabilen akşam publisher işinde görülen **ayrı hata**: `Yoksul_1986_Part_6.mp4` videosu, `manual-2026-10-18-0617-film` eski claim'i nedeniyle güvenli biçimde durdurulmuş. Claim'i otomatik silme, Part 6'yı sıradan zorla gönderme veya video sırasını değiştirme.

**GitHub check-run API'si** aynı SHA için 3 başarısız check ve her birinde **2 annotation** olduğunu gösteriyor. Ancak bağlı GitHub aracında annotation gövdelerine erişim yok; log endpoint'i `BlobNotFound` dönüyor. **Kesin kök neden saptanmadı.** En güçlü araştırma adayları: özel deponun GitHub Actions kullanım kotası, `Stop usage` bütçesi, ödeme yöntemi/hak ediş engeli, GitHub Actions politika/izin kısıtlaması veya runner sağlama arızası. Bunlar kanıtlanmadan 'billing kesin bozuk' deme.

**GitHub'ın resmi kullanıcı hesabı kontrolü:**
1. [GitHub Billing](https://github.com/settings/billing) → `Usage` bölümünde **Actions** kullanımını incele.
2. `Budgets and alerts` bölümünde Actions için `Stop usage when budget limit is reached` ile engellenen bütçe/limit var mı incele. Hiçbir bütçeyi otomatik artırma ve ödeme onayı verme.
3. `Settings → Actions → General` altında repo/hesap Actions iznini ve varsa onay engelini denetle.
4. [Başarısız analytics CI](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39488048609) → **Annotations** bölümünün **yalnızca hata metnini** oku. Token/ödeme bilgisi paylaşılmasın.
5. Yukarıdakiler açık değilse [GitHub Support](https://support.github.com/) üzerinden job ID, zaman ve `runner_id=0, steps=[]` kanıtıyla destek iste.

**Önemli:** Bu engel repo Python koduyla düzelmeyebilir. Üretim publisher'ını, Film recovery'yi, Drive kuyruğunu veya watchdog dispatch'lerini **runner denemesi amaçlı tetikleme**. Gereksiz rerun döngüsünü durdur. Önce izin/hesap engelini çöz; erişim yoksa diğer güvenli işleri ilerlet, son aşamada yalnızca bu tek zorunlu engeli açıkça belirt.

## 1. Çalışan kanıtları ve bunların sınırları

- [20 Ekim 09:24 TRT master NTFY CI](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39380199783): **success**, `a90c5ef6` SHA'sı. Bu, yeni #74/#75 kodunu kapsamaz.
- [20 Ekim 09:24 TRT master Sheets CI](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39380199773): **success**, `a90c5ef6` SHA'sı; **57 analitik assertion**.
- [20 Ekim 08:49 TRT NTFY canlı smoke](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39376906465): iş **success** ve logda `http_status=200`, `server_ack=true`, `phone_delivery_verified=false`. Yani **NTFY sunucusu kabul etti**, **Android telefon teslimatı bilinmiyor**.
- [Salt-okunur Film/Meta denetimi](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39379915316): iş başarılıydı; bu **Film Part 6'nın yayımlandığı veya sayfa tokenlarının bugün geçerli olduğu anlamına gelmez**.
- `stats_reporter.py` hesap başına toplam video görüntülenmesi ve günlük artışı gönderir; `N/A/Kısmi` eksik ölçümleri korur. Sonraki kullanıcıya NTFY bildirimine düşen **gerçek günlük üretim run'ının** kanıtı gösterilmeden 'tamam' denemez.
- Google Sheets'e gerçek yazım **yetkilendirme bekliyor**; uygulama ve kullanıcı hesabı sağlanmadan canlı kabul yok.
- Eski geçmişte Instagram binary upload `FINISHED` başarıları bulunabilir; bunlar **`media_publish` sonucu veya platform post ID'si değildir**.

## 2. Açık çalışmalar (çakışma matrisi)

**Bunları güncel GitHub'dan yeniden doğrula.** Kullanıcı onayını almadan PR silme/kapatma/merge etme veya bir başkasının branch'ini ezme.

| Çalışma | Devir gözleminde durum | Sahiplik/çatışma |
| --- | --- | --- |
| [#75 Film Part 6 güvenli kurtarma](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/75) | **Draft, unmerged**; `scheduled_multi_publisher.py`, `test_film_part6_recovery.py`, `FILM_PART6_RECOVERY.md` | **Codex/Film işi**. Yalnız exact claim'e, tam MP4 upload-only + uzaktan gönderi ID uzlaştırmasına bağlı; manuel yayın **onay gerektirir**. |
| [#74 analitik güvenlik](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/74) | **Draft, unmerged**, 8 yeni mock test; CI **runner almamış** | `stats_reporter.py`, `analytics_sheets_sync.yml`, `test_analytics_production_safety.py`. Meta bozuk 200 yanıtının sahte sıfır olması engelleniyor; Sheets için `ANALYTICS_SHEETS_WRITE_ENABLED=true` ayrı aktivasyon şartı. Değişikliklerin canlı doğrulaması yok. |
| [#54 Cloudflare watchdog](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/54) | Açık, unmerged; dış Worker **deploy kanıtı yok** | **Codex/cron işi**: `scheduler_watchdog/**` + `omnichannel_schedule.yml`. |
| [#46 NTFY V3 + Threads](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/46) | Draft, master'dan ayrışmış | `stats_reporter.py`, `ntfy_notifications.py`, publisher/workflows ile **#74/#75/master** çakışabilir; körlemesine merge yok. |
| [#45 Threads opt-in](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/45) | Draft | #46 ile publisher ve `threads_accounts.py` örtüşür. Bağlantı/yayın **ertelendi**. |
| [#18 içerik güvenliği](https://github.com/emirhankaya-AFK/auto-video-publisher/pull/18) | Açık, çatışmalı | Mizah hesaplarında inceleme olmadan yayın açılmamalı; güvenlik kontrollerini zayıflatma. |

**Diğer ajanla paralel çalışma protokolü:** Önce `git diff master...branch`, PR changed-files ve commit timestamp; Film, `scheduled_multi_publisher.py`, publisher workflows, Cloudflare ve claim'ler başka ajandaysa bunların **dosya sahipliğini devralma**. Bağımsız tarama, istatistik, raporlama ve testlerden ilerle. Çakışan bir alan için bir kez kısa koordinasyon notu yaz; her yeni bulgu için başka PR açma.

## 3. Tek geçişte uygulanacak çalışma sırası

### A — Ortam/runner engelini gerçek kanıtla ele al (P0)

- Yukarıdaki zero-step olayını bağımsız doğrula. Son başarılı gerçek runner çalışmasının ve ilk zero-step çalışmanın zamanını ve job ID'sini belirle.
- GitHub check-run Annotations metni erişilebiliyorsa kaydet; değilse `unavailable` yaz, hata uydurma.
- Özel depo billing/quota/policy/runner izinleri **hesap düzeyinde** gerekebilir; bağlanamıyorsan kullanıcı için **tek eylemlik** net yönerge ver.
- Runner çalışmadan Python/Node testini geçmiş sayma ve #74/#75'i master'a alma.
- Bir deneme yapılacaksa yalnız **kimlik bilgisiz ve publish yapmayan tek test işi**; önceki başarısız rerun'lar burada kayıtlıdır, tekrara düşme.

### B — Kod güvenliği ve CI incelemesi (P0/P1)

- #74 içindeki Meta `graph_pages`/HTTP JSON cevap denetimini ve 8 testi **gerçek kaynak koduna karşı** kontrol et: geçerli boş liste ile eksik/malformed liste farklı olmalı; token/log sızıntısı, redirect, pagination döngüsü engellenmeli.
- Sheets opt-in kuralında `--write` yalnız açık kullanıcının etkinleştirdiği `ANALYTICS_SHEETS_WRITE_ENABLED=true` ile mümkün olmalı. Bu değişkeni **kendin ayarlama**. Eski Sheets'te hiçbir hücre güncellenmemeli.
- Python testleri: `python -m unittest discover -p 'test*.py'`; PR #74 için ek `python -m unittest -v test_analytics_production_safety.py`. Ayrıca `test_stats_reporter.py` ve `test_analytics_sheets.py` modüllerindeki **parametresiz fonksiyon biçimli assertion'lar** da CI'daki gibi çağrılmalı.
- Runner düzeldikten sonra aynı **PR head SHA** için NTFY, Sheets ve publisher **no-send/no-publish** CI üçlüsü yeşil olmadan ilgili PR'ı merge etme.
- Yerel çalışma ortamın kullanılamıyorsa açıkça belirt; test iddiası üretme. Çevrimiçi çalışma mümkün olan yerden devam et.

### C — Film/Meta durumu (P0, Codex çatışmasını önle)

- #75 Film Part 6 kurtarma taslağının güvenlik testlerini denetle, özellikle idempotency, Drive claim/intent, Facebook 1/2, Instagram, YouTube ayrımı ve `upload-only FINISHED != published`.
- [Film canlı audit](https://github.com/emirhankaya-AFK/auto-video-publisher/actions/runs/39379915316) sonuçlarını platform gerçek gönderi ID'si için incele. Part 6 için kayıt eşleşmesi yoksa bunu **silinmiş geçmişi kanıtlayan mutlak yokluk** sayma.
- Film/Meta global user token 401 geçmişte görülmüş; sayfa tokenlarının da geçersiz olduğuna dair otomatik çıkarım yapma. Read-only identity/permission audit kullan.
- Video yeniden gönderimi, `claim` silme, part atlama, forced publish/dispatch, gerçek upload, Cloudflare dağıtımı veya credential değiştirme için **ayrı açık izin** gereklidir.

### D — NTFY ve raporlama (P1)

- Akşam 23:59 TRT `daily_stats.yml` için yeni master'daki **gerçek schedule** run ve saatini bul; yoksa doğrulanmadı de. `workflow_dispatch` normal zamanlı run yerine geçmez.
- Ertesi sabah 07:10 TRT `daily_report_watch.yml` başarısız raporu gerçekten denetliyor mu; GitHub schedule tamamen durursa bu watcher da çalışmaz.
- Her altı hesap için aynı gün artan görüntülenme, all-time görüntülenme, farklı FB sayfaları, kısmi/N/A ve gerçek Drive JSONL ölçüm saatini kontrol et.
- NTFY server ACK kanıtı mevcut; Android'e teslimat yalnız kullanıcı cihazından doğrulanabilir. Aynı smoke'u sebepsiz tekrarlama.

### E — İkinci aşama ve UX (P2)

- #45/#46 Threads ve NTFY V3 çatışmasını kademeli olarak çöz; yeni Threads tokenları, yayın, otomatik mesaj veya NTFY gereksiz test bildirimi göndermeden kod üzerinde çalış.
- Sheets aktifleştirme ve Google hesap bağlama ileride kullanıcının güvenli yetkilendirmesiyle yapılacak.
- Yeni başarısızlıkların aynı gün içinde fark edilmesi için bağımsız heartbeat/izleme ihtiyacını raporla; **gerçek harici servis dağıtılmadıysa** varmış gibi davranma.
- Kullanıcıya her başarısız test için ayrı PR listesi veya yeni soru yığma. Güvenli ilişkili düzeltmeleri tek mevcut çalışma dalında grupla; çakışan kritik dosyalarda ayrı tut.

## 4. Son kabul matrisi — kanıt olmadan yeşil olamaz

| Kabul maddesi | Gerekli kanıt |
| --- | --- |
| GitHub Actions altyapısı | Yeni test run'ında gerçek `runner_id != 0`, `steps > 0`, sonuç success; gereksiz prod rerun yok |
| Analytics #74 | Aynı head SHA'da güvenli yeni 8 test + önceki tüm regresyonlar geçti; sahte 0/N/A regresyonu düzeldi; Sheets write kilidi kapalı |
| Film #75 | Mock testleri + üretim güvenlik uzlaştırması; gerçek post ID ve duplicate kontrolü; kullanıcı izni olmadan yeniden paylaşım yok |
| Planlı publisher | Normal `schedule` işinin güncel master'da başarılı gerçek çalışması ve platformda post ID kanıtı; sadece CI değil |
| Meta & YouTube kimlik | Her hedef için beklenen hesap/kanal ve izin doğrulaması; global token ile page token ayrı |
| NTFY | Gerçek günlük rapor sunucu ACK + hesabın günlük/all-time toplamlarının doğruluğu; Android teslimat ayrı onay |
| Drive/Sheets | Eski doğru geçmiş silinmedi; yanlış `0` yazılmadı; Sheets otomatik yazım varsayılan devre dışı |
| Cloudflare | Worker üretimde deploy edildiği ayrı belgelenip watchdog idempotency ve dış dispatch kontrol edildi; #54 kodu tek başına yeterli değil |

Bu maddeler sağlanmıyorsa **'tamamlandı/100-100/üretime hazır' deme**; durumları **kod hazır/test başarılı/canlı doğrulanmadı/engelli** olarak ayrı yaz.

## 5. İzin ve güvenlik

- `AGENTS.md` içindeki tarayıcı kısıtı geçerlidir: kullanıcı izin vermeden GUI browser, Playwright, Selenium veya ekran otomasyonu yok.
- Secret, NTFY topic, OAuth/Meta tokenları, servis hesabı JSON'u, özel kullanıcı verisi, tam HTTP request/response gövdeleri ve signed URL'ler loglanmaz veya paylaşılmaz.
- Gerçek sosyal medya gönderimi, toplu upload, paylaşılan claim mutasyonu, geçmişi sıfırlama, canlı Sheets `--write`, Cloudflare deploy veya ödemeli hesap ayarı için örtük yetki çıkarma.
- Başarıların tümünde `SHA + run_id + job steps + gerçek üretim sonucu` kanıtlarını ayır; 0-step run'da test sonucu yoktur.
- Kritik değişikliklerde rollback belirle, kayıtları silmeden güvenli geri dönüş yolunu yaz.
- Eksik kaynakta `0` yerine `N/A`, gerçek bildirim teslimi yoksa `server ack only` kullan.

## 6. Kullanıcıya tek final rapor şablonu

**Türkçe, en fazla yaklaşık 12-18 satır; teknik detayları repo raporunda bırak:**

1. **✅ Tamamlandı:** gerçek commit/merge ve geçerli test, mümkünse kısa kanıt linki.
2. **🟡 Kod hazır, canlı kanıt yok:** nelerin gerçek üretim verisiyle henüz doğrulanmadığı.
3. **🔴 Bloke:** GitHub runner sorununun *kesin kanıtlanmış* sebebi; bilinmiyorsa `0-step` olgusu ve bilinmeyen anotasyon.
4. **🔑 Senden tek zorunlu işlem:** varsa yalnız kullanıcının hesabında çözülebilen `Actions Billing/Budgets/Annotations` adımı; şifre/anahtar isteme.
5. **⏭ Sonraki güvenli eylem:** sistem yeniden çalışabilir olunca ilk hangi credential'sız CI çalışacak, Film claim'e dokunulmadan.

**Operasyonel hedef:** Sol bu dosyayı okuyup yeni bilgi toplamak için tekrar tekrar kullanıcıyı bölmeden, izin sınırları içinde sonuca kadar ilerlesin. Tek engel üçüncü taraf hesap düzeyindeyse bunu gizlemeyip kullanıcıdan **tek net bilgi/işlem** istesin; kullanıcı yaptıktan sonra aynı işin devamını kanıtla doğrulasın.
