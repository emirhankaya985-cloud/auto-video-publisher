# 985 hesabına aktarım

Hedef: `emirhankaya985-cloud/auto-video-publisher`, varsayılan dal `main`.
Kaynak anlık görüntüsü: AFK/master `107c623f4dc15e72f1ecdf31c470b84a025a35a1`. Eski Git geçmişi aktarılmadı.

## Kurulum durumu

- Kaynak kodu ve workflow dosyaları aktarıldı.
- ToonZone manuel slot eşleştirmesindeki regex ve zaman dilimi karşılaştırması düzeltildi.
- Workflow/ref kontrolleri yeni `main` dalına uyarlandı.
- Gerçek servis erişimi kullanan işler `AUTOMATION_ENABLED == 'true'` değişkenine bağlı; varsayılan kapalı.
- 985 Migration CI, üretim kimlik bilgisi olmadan Python ve Node testlerini çalıştırır; ayrı iş yalnız secret adlarının mevcut olup olmadığını özetler.
- Eski AFK workflow'larının kapatılması ve canlı Drive durumunun salt-okunur uzlaştırılması sonrasında yayın açılmalı. İki bağımsız GitHub deposunun concurrency grubu birbirini kilitlemez.
- Önceden tanımlanan route/content approval değişkenleri yeni depoya otomatik taşınmaz; kanıt olmadan açılmadı.
- Cloudflare kaynakları 985/main için hazırlandı; dış worker deploy edilmedi. `FALLBACK_MODE=disabled`; workflow ID'leri yeni depodan alınarak 0 değerlerinin yerine konmalı.
- `assets/instagram_tarladaki_fasulye_cover.png` kaynak ZIP'te yok. Eski film dosya-adı audit raporu taşınmadı.

## Secrets

GitHub Settings → Secrets and variables → Actions. Değerleri yalnız GitHub Secrets'a girin; koda veya sohbete eklemeyin. Eski deponun secret değerleri GitHub üzerinden okunamaz. Aşağıdaki liste tüm workflow referanslarının envanteridir; her değer her kanal için zorunlu değildir. Kullanılacak kanallar seçildikten sonra gerekli değerler tamamlanmalı.

- `ANALYTICS_SHEETS_CREDENTIALS_JSON`
- `BATCH_API_TOKEN`
- `DAILY_LAUGH_DRIVE_FOLDER_ID`
- `DRIVE_FOLDER_ID`
- `DRIVE_TOKEN_JSON`
- `FILM_DRIVE_FOLDER_ID`
- `GONLE_DUSEN_DRIVE_FOLDER_ID`
- `META_ACCESS_TOKEN`
- `META_APP_ID`
- `META_APP_SECRET`
- `META_AUTH_JSON`
- `NTFY_TOPIC`
- `NTFY_TOPIC_URL`
- `PENGUEN_THREADS_VIDEO_URL_TEMPLATE`
- `THREADS_ACCESS_TOKEN`
- `TOKEN_CHANNEL1_JSON`
- `TOKEN_CHANNEL2_JSON`
- `TOKEN_DAILY_LAUGH_LAB_JSON`
- `TOKEN_FILM_YOUTUBE_JSON`
- `TOKEN_GONLE_DUSEN_JSON`

## Etkinleştirme

1. CI ve setup-status özetini kontrol et.
2. Kullanılacak kanalların Drive/Meta/YouTube/Threads kimlik bilgilerini ve route değişkenlerini tamamla.
3. Eski depodaki yayıncı ve yedek yayıncıyı durdur; platform kimlikleri ve Drive claim/intent durumunu salt-okunur doğrula.
4. Yayın açılması onaylandığında yeni depoda `AUTOMATION_ENABLED=true` ayarla. Sheets yazımı ve Cloudflare deploy ayrıca kurulmalı.

Geri alma: Yeni depoda `AUTOMATION_ENABLED` değişkenini kaldır veya `false` yap. Devam eden yayın işlerini ayrıca kontrol et; Drive durum/claim kayıtlarını silme.

## 22 Ekim ek yapılandırma

AFK deposundaki 19 Actions değişkeni 985 deposuna aynı değerlerle aktarıldı ve karşılaştırıldı. `AUTOMATION_ENABLED=false` ayrıca kaydedildi. Günlük rapor watchdog hedefi 985/main olarak düzeltildi. `GITHUB_TOKEN` GitHub tarafından otomatik sağlanır; kullanıcı secret olarak eklememelidir. Ana ve yedek GitHub zamanlayıcıları aktarılmıştır. Harici Cloudflare worker bu geçişte deploy edilmemiştir; ana GitHub yayın akışı bu workera ihtiyaç duymaz (isteğe bağlı batch API ayrı). Tokenler sonrası eski yayıncı durumu ve Drive claim kayıtları denetlenerek kontrollü geçiş yapılmalıdır.

## Kullanıcı tokenı ile Meta bağlantısı

`META_AUTH_JSON` isteğe bağlıdır. JSON veya yerel dosya yoksa `META_ACCESS_TOKEN` ile `/me/accounts` salt-okunur sorgulanır. Yalnız tanımlı hesap adları ve mevcut sabit sayfa kimlikleri kabul edilir. Sayfa tokenları bellekte tutulur; dosyaya veya loga yazılmaz. Read-only Meta Page Token Health yayın kilidi kapalıyken main dalından manuel çalıştırılabilir.

## Public runner ve Meta-only yayın

985 deposu 22 Ekim 2026 tarihinde public yapıldı. Ana/yedek publisher standart `ubuntu-latest` kullanır. Publisher workflow ortamı `YOUTUBE_PUBLISHING_ENABLED=false` ve `ENABLE_NEW_YOUTUBE_ROUTES=false` uygular; YouTube işleri plana alınmaz ve istemci kimlik bilgileri yüklenmeden durdurulur. Tokenlar kaynak kodunda tutulmaz. Meta kimlik denetimi başarılıdır. Drive erişimi kurulmadan gerçek yayın veya geçmiş uzlaştırması tamamlanmış sayılmaz.
