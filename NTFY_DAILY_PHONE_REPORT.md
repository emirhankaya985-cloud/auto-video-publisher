# NTFY Gün Sonu Telefon Raporu — Güvenlik ve Doğrulama

Bu belge `ntfy_notifications.py`, `ntfy_phone_report.py` ve
`stats_reporter.py` içindeki mevcut davranışı tarif eder.

## Kullanıcıya gelen bilgi

- Her hesap için **📈 Bugün** ve **👀 Genel** değerleri ayrı ayrı sunulur.
- Instagram, Facebook 1/2, YouTube metrikleri ilgili platformun sayaç
  tanımlarından alınır; eksik kaynaklar sıfır değil **N/A**, hata veya
  **Kısmi** olarak işaretlenir. Farklı platform sayaçlarını aynı kişi sayısı
  gibi yorumlamayın.
- Normal rapor 3.800 UTF-8 bayt sınırındaysa tüm metin gönderilir. Rapor
  uzunsa isteğe bağlı platform ayrıntısı ve ham hata satırları telefondaki
  bildirime sığdırılmak için atlanır; **altı hesabın günlük ve toplam
  izlenmesi**, sistem toplamları ve veri eksikliği uyarıları korunur.
- NTFY sınırı 4.096 bayttır; daha büyük metin otomatik dosya eki
  olabileceği için gönderici bunu reddeder.

## GitHub gecikirse hangi gün raporlanır?

Planlı rapor 23:59 TRT'ye ayarlıdır. GitHub Actions kuyruğu nedeniyle
çalışma **00:00–05:59 TRT** arasında başlarsa, `GITHUB_EVENT_NAME=schedule`
olan çalışma *bir önceki takvim gününün* raporu olarak etiketlenir.
İstatistiklerin `measured_at` alanı gerçeği yansıtır; ölçüm saatini
23:59'muş gibi uydurmaz. Gece yarısından sonra izlenme sayaçlarına
yeni günün görüntülenmeleri de eklenmiş olabileceğinden:
- **👀 Genel** ölçüm anındaki gerçek sayacı gösterir ve gecikme uyarısı taşır.
- **📈 Bugün** değerleri, doğru ayrıştırılamadıklarında `N/A` olur.
- Gecikmeli ölçüm, Drive'daki günlük arşive ilgili planlı günün
  `period` bilgisi ve *gerçek ölçüm saati* ile kaydedilir.
- Manuel `workflow_dispatch` testleri asla otomatik olarak bir önceki
  güne taşınmaz. Altı saati aşan olağan dışı gecikmeler ayrıca
  watchdog kontrolünden izlenmelidir.

## Geçmiş veriyi koruma

- Önceki günün başarılı örneklemindeki bir video bugünkü listeden
  kaybolursa toplam ve günlük artış güvenilir kabul edilmez (**N/A**).
- YouTube yükleme listesinde video kimliği eksikse, listeye karşılık
  gelen `videos.list` yanıtı eksikse ya da herhangi bir videonun
  `viewCount` değeri yoksa YouTube metrikleri **hata / N/A** sayılır;
  eksik kalan videoların sayıları sıfır varsayılmaz.
- Önceki günün video kayıt sayısı `snapshot_status` ile uyuşmuyorsa veya
  bir baz video görüntülenme kaydı geçersizse günlük fark **N/A** olur.
- Aynı gün tekrar çalıştırılan raporun API yanıtı hata verirse veya daha önceki başarılı ölçüme göre video envanteri küçülürse, **önceki sağlam gün içi arşiv** korunur. Başka araçların varsayılan JSONL güncelleme davranışı değişmez.
- Drive geçmiş arşivi okunamazsa eski arşiv **asla kısmi yerel geçmişle
  güncellenmez**; rapor eksik veri uyarısı taşır. Arşiv ilk kez yoksa
  normal ilk kurulum akışı devam eder.

## NTFY bağlantısı

GitHub Actions Secrets altında `NTFY_TOPIC_URL` (örneğin özel
`https://ntfy.sh/<konu>`) ya da eski `NTFY_TOPIC` bulunmalıdır.
Bu değerleri sohbetlere veya loglara yapıştırmayın.

JSON gönderiminde özel konu, URL yolundan ayrıştırılıp JSON `topic`
alanına taşınır; POST sunucu kök adresine yapılır. Sunucu HTTP 2xx
dönerse HTTP isteği başarılıdır; gün sonu raporu ayrıca JSON yanıtındaki mesaj kimliğini ve doğru konu eşleşmesini zorunlu tutar. Yanlış konu veya eksik sunucu alındısı, HTTP 200 olsa bile raporu başarısız sayar. Bu, Android cihazın bildirimi
aldığını garanti **etmez**.

### Otomatik tek seferlik NTFY test bildirimi

`ntfy_server_smoke.yml` master'a ilk eklendiğinde bir kere çalışarak
`ntfy_smoke_test.py` üzerinden kısa bir test bildirimi gönderir. Sunucunun
döndürdüğü JSON'daki `event=message`, `topic` eşleşmesi ve `id`
doğrulanır; JSON gövdesi, konu adı, tokenlar ve URL loglanmaz.
GitHub Actions logunda sadece `status=ntfy_server_acknowledged`,
`server_ack=true` ve `phone_delivery_verified=false` görülür.

- Secret yoksa otomasyon `ntfy_secret_missing` koduyla başarısız olur.
- Sunucuya ulaşamazsa veya farklı konu dönerse **başarısız** görünür.
- Başarılı olsa da Android telefonun doğru konuya abone olması ve
  Android bildirim izinleri ayrıca kontrol edilmelidir.
- Workflow manuel çalıştırılabilir; her manuel çalıştırma bir test
  bildirimi gönderir. Gerçek günlük raporun yerine geçmez.


Testler: `python -m unittest -v test_ntfy_notifications.py
test_ntfy_phone_report.py` ve GitHub Actions **NTFY delivery safety tests**.
Bunlar gerçek NTFY mesajı göndermez; canlı cihaz doğrulaması için
bir sonraki doğal günlük raporun cihazda görülmesi gerekir.

## Günlük rapor başarısızsa uyarı

`.github/workflows/daily_stats.yml` işinde herhangi bir adım başarısız
olduğunda `ntfy_report_failure_alert.py` tek bir kısa ve
yüksek öncelikli uyarı dener. Uyarıda yalnızca GitHub Actions çalışması
bağlantısı bulunur; özel konu URL'si ve hata gövdeleri paylaşılmaz.
`failure()` adımı önceki hatayı yeşile çevirmez.
NTFY sunucusu da erişilemiyorsa bu uyarı da ulaşamaz; GitHub Actions
hata durumu asıl kanıt olarak kalır. Çalışmayan veya hiç tetiklenmeyen
bir GitHub schedule, kendi başına bu fallback adımını başlatamaz.

## Günlük rapor hiç tetiklenmediyse

`.github/workflows/daily_report_watch.yml`, her sabah yaklaşık
**07:10 TRT** saatinde GitHub Actions API'sinden *bir önceki gece*
**23:59 TRT** planlı rapor çalışmasını salt-okunur denetler.
Yalnızca `event=schedule`, `head_branch=master`, beklenen UTC
zaman penceresi ve `conclusion=success` koşulları sağlanırsa
sağlıklı sayılır. Manuel çalıştırılan rapor başarısı bu kanıtın
yerine geçmez.

Planlı rapor hiç çalışmadıysa, geç kaldıysa veya başarısızsa
NTFY üzerinden bir yüksek öncelikli uyarı gönderilir; watchdog
kendi Actions işini **başarısız** durumda bırakır. GitHub API
erişilemezse kesin eksik rapor iddiası yerine sağlık denetiminin
yapılamadığı bildirilir. Özel konu ve API yanıtları loglanmaz.
Bu kontrol yalnızca raporlama workflow'unu inceler; videoları
tekrar paylaşmaz ve Drive arşivine yazmaz.

**Sınır:** Watchdog da GitHub Actions schedule ile çalışır.
GitHub iki schedule olayını da kaçırırsa uyarı üretilemez.
Gerçek bağımsız zamanlayıcı ancak dış servisle sağlanabilir.
NTFY veya Android çevrimdışıysa bildirim teslimatı da
ayrıca garanti edilemez.

## Değişiklik sınırı

Film, ToonZone, cron, Cloudflare, sosyal medya paylaşım kuyruğu, Threads
ve Google Sheets kimlik bilgileri bu çalışmada değiştirilmez.
