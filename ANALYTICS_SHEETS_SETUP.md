# Google Sheets analitik senkronizasyonu

Bu entegrasyon mevcut `daily_video_views.jsonl` arşivini salt-okunur kaynak olarak kullanır; mevcut JSONL/CSV'yi silmez veya güncellemez. İçerik yayınlamaz, production kuyruğu/claim'leri değiştirmez ve ham Actions loglarını Sheet'e kopyalamaz. Şema sürümü `1.2`'dir; özet sekmelerinde verinin JSONL arşivi ve Drive yayın metadata'sından geldiği ayrıca belirtilir.

## Hazır sekmeler

`analytics_sheets.py` şu sekmeleri oluşturur (yoksa) ve ilk sütundaki sabit kayıt anahtarıyla satırları günceller: `PANEL`, `HESAPLAR`, `YAYINLAR`, `GÜNLÜK METRİKLER`, `HESAP TOPLAMLARI`, `İŞLEM LOGLARI`, `HATALAR`, `KAYNAK SAĞLIĞI`, `GEÇMİŞ KANIT`, `KURULUM`. Başlıklar eşleşmiyorsa mevcut sayfayı ezmek yerine senkronizasyon hata verir. Canlı senkronizasyondan önce var olan tüm sekmelerin başlıkları ve kayıt anahtarı sütunları **salt-okunur ön kontrolden** geçer. Geç bir sekmede şema uyuşmazlığı veya yinelenen kayıt anahtarı bulunursa hiçbir sekmede satır yazımına başlamaz; var olan veriler korunur. API kesintileri gibi yazım sırasında oluşabilecek sorunlarda işlemler tamamen atomik değildir, ancak sabit satır/anahtar eşlemesi nedeniyle sonraki çalışmada tekrar güvenli senkronizasyon yapılabilir. Değerler `RAW` olarak yazılır; hücreler formül çalıştırmaz. Mevcut sayısal hücreler `UNFORMATTED_VALUE` ile okunur; böylece örneğin `1234` sayısının Türkçe biçimlendirilmiş `1.234` metni olarak dönmesi gereksiz tekrar yazımına yol açmaz. Yeni kayıtlar önceden hesaplanmış sabit aralıklara `update` ile yazıldığı için HTTP yanıtı kaybolup retry olsa da aynı satır tekrar kullanılır. Workflow concurrency grubu eşzamanlı senkronları sıraya alır.

## GitHub ayarları

Önce özel bir Google Spreadsheet oluşturup erişimini yalnızca gerekli kişilerle sınırla. Sonra:

1. `Settings → Secrets and variables → Actions → Variables` içine `ANALYTICS_SHEET_ID` değişkenini ekle. Değer yalnızca gerçek Spreadsheet ID olmalı; bu repo için henüz ayarlanmamıştır.
2. Google Cloud projesinde Google Sheets API'yi etkinleştir ve yalnızca bu iş için service account oluştur; anahtar JSON'unu GitHub Actions repository secret `ANALYTICS_SHEETS_CREDENTIALS_JSON` olarak ekle. Bu kod credential'ı sadece `https://www.googleapis.com/auth/spreadsheets` scope'u ile kullanır. Service account e-posta adresini Sheet'te düzenleyici olarak paylaş; Sheet'i herkese açık yapma. Özel anahtarı sohbete veya loglara yapıştırma.
3. Drive JSONL arşivini okumak için workflow mevcut `DRIVE_TOKEN_JSON` credential'ını kullanır. Kod Drive üzerinde yazma çağrısı yapmaz. Mevcut Drive OAuth scope'u geniş olsa da yeni Sheets istemcisine aktarılmaz; Drive OAuth scope'unu genişletmeye gerek yoktur.
4. İsteğe bağlı `ANALYTICS_DRIVE_FOLDER_ID` Actions variable'ı varsayılan olarak görevde verilen klasör ID'sini kullanır. JSONL burada yoksa modül, mevcut reporter'ın `Auto Video Publisher Analytics` klasörünü Drive API ile salt-okunur arar. Drive arşiv dosyası bulunamazsa uydurma veri aktarılmaz.

Sheet ID ve Sheets credential secret'ı girilene kadar canlı yazma yapılamaz. `workflow_dispatch` varsayılanı `dry_run=true`; ilk önizleme için bu şekilde bırak. Zamanlanmış iş/`daily_stats` tamamlanma tetiklemesi, iki ayar da mevcut olduğunda senkronizasyonu otomatik yapar. ID ya da credential eksikse güvenli biçimde `disabled`/dry-run çıkar.

Var olan bir sekmenin başlığı beklenen şemadan farklıysa senkronizasyon o sekmede durur; kolonları tahmin ederek yeniden sıralamaz, hücreleri silmez veya üstüne yazmaz. Bu bilinçli veri-koruma davranışıdır. Özel Excel şablonunu bağlamadan önce kopya üzerinde kolon eşlemesi ve başlıklar doğrulanmalıdır; eşleşmeyen şemayı otomatik uyarladığı iddia edilmez.

Yerelde, test/önizleme için:

```powershell
python analytics_sheets.py --dry-run
```

`--write`, gerçek Sheet ID'si ve ayrı Sheets service-account secret'ı yoksa canlı API çağrısı yapmaz. Canlı ilk senkron öncesi workflow_dispatch ile `dry_run=true` sonucu incelenmelidir. Uygulanan mekanizma Drive/Actions okumalarını ve Sheet yazımını birbirinden ayırır.

## Kaynakların kapsamı ve veri kalitesi

- Facebook/Instagram/YouTube görüntülenme snapshot'ları mevcut arşivden gelir. Günlük görüntülenme yalnızca birbirini izleyen günlük video snapshot'larından hesaplanır; 7/30 günlük değişim yalnızca tam envanter ve tam 7/30 günlük baseline varsa hesaplanır. Reset, eksik video veya eksik snapshot varsa `N/A` olur. Negatif fark gerçek düşüş gibi sunulmaz.
- `HESAP TOPLAMLARI` içindeki `önceki_güne_göre_değişim`, bugünkü kazanılan görüntülenme ile önceki gün kazanılan görüntülenmenin **işaretli farkıdır**. Örneğin dün +100, bugün +30 ise değer `-70` olur; bu toplam görüntülenme kaybı anlamına gelmez. Önceki günün eksiksiz verisi yoksa `N/A` yazılır.
- Takipçi, beğeni, yorum, paylaşım, Threads ve platformda gerçek yayın zamanı mevcut kaynaklarda yoksa `N/A` kalır. Film Mağarası Threads kimliği `film_magrasi` / `28752898447698066` olarak kaydedilmiştir; bu workflow token/izin sağlığı denetimi yapmaz ve Threads metrik collector'ı sağlamaz.
- Yayın kanıtları Drive `appProperties` içindeki doğrulanmış sonuç/slot alanlarından alınır. Yalnızca herkese açık, bilinen platform alan adlarına ait URL'ler saklanır; URL sorgu parametreleri/fragment'leri atılır. Hata ayrıntısı yoksa yalnızca hata/belirsiz slot kanıtı yazılır.
- Workflow run tablosu GitHub Actions API metadata'sından (son 30 gün, 100 sayfa × 100 run üst sınırı) oluşturulur. Ham log veya HTTP yanıt gövdesi aktarılmaz. Daha eski, başarıyla Sheet'e yazılmış satırlar silinmez. Run-Drive yayın eşlemesi mevcut kaynakta yoksa `N/A` olur.
- PR #46 (Threads) ve PR #50 (cron/HTTP 400) dosyaları bu branch'te değiştirilmez. Threads hesabı satırları görünür, ancak master'da Threads istatistik collector'ı olmadığı için metrikler `N/A` olarak belirtilir.

## Eksik kaynak durumunda güvenli durdurma

Canlı `--write` çalışmasında Drive JSONL arşivi bulunamazsa, okunamazsa,
boşsa veya GitHub Actions API metadatası eksik/hatalı gelirse
sistem `source_unavailable`, `writes=0` ile durur. Eski Google Sheets
satırlarının üzerine yanlış `N/A` değerleri yazılmaz. Zamanlanmış
Actions görevi bu durumda başarısız görünür; hata çözülüp yeniden
çalıştırıldığında sabit kayıt anahtarlarıyla aynı satırlar güncellenir.
`--dry-run` bu koşullarda da salt-okunur önizleme sunar. İki Sheets
kimlik bilgisi eksikken önceki `disabled` davranışı korunur.

## Hata ve telafi davranışı

Google Sheets 429 ve geçici 5xx/bağlantı hatalarında sınırlı exponential retry uygulanır. İstek başarısız olursa mevcut Drive arşivi değişmez; aynı zaman aralığı sonraki çalışma tarafından yeniden okunabilir. Her sekmede stable key ile upsert yapılır, satır silinmez. Yetkisiz 4xx veya şema başlığı uyuşmazlığında otomatik retry/overwrite yapılmaz; Actions run hatası incelenmelidir.
