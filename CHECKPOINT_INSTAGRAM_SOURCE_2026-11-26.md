# Instagram kaynak toplama ve Drive checkpoint — 26.11.2026

## GitHub durumu

- PR #324 birleştirildi; merge commit: `1e63e0417c35eb04bdd598316245d6b2f4634285`.
- `main` için PR CI'sinde 13 workflow başarılı, 2 kontrol atlandı. PR başlığında 1.506 testin geçtiği ve 16 testin atlandığı raporlanmıştı.
- Birleştirme sonrası Meta publisher health watchdog ayrı bir üretim alarmı verdi: Film ve ToonZone `publication_blocked`; son raporda 14 onaylı yayın makbuzu vardı. Bu alarm PR başlığı CI hatası değil. Tekrar çalıştırılmadı ve üretim ayarlarına dokunulmadı.
- Bu görev için yerel branch: `feat/drive-source-folders-20261126`, taban güncel `origin/main` (`56d3164a`, PR #327 merge sonrası). Yerel commit `da4e969`; GitHub bağlantısı üzerinden aynı dosya ağacını taşıyan branch commit'i `bbf5398` olarak oluştu (tree SHA aynı: `7304185d`). PR #328 açık.
- PR #328 başlığı için GitHub bağlantısı henüz workflow run veya check kaydı döndürmedi. Bu nedenle yeni commit için CI sonucu yok; CI başarılı sayılmadı ve PR birleştirilmedi. PR #324'ün geçmiş kontrolleri bu commit'in CI'si değildir.
- Bu branch için güncel tam yerel test: `python -m unittest discover -q` — 1.508 başarılı, 16 atlandı. Kaynak alım testleri 31 başarılı. Python derleme, iki ilgili Actions YAML dosyasının parse edilmesi ve `git diff --check` geçti.

## Drive denetimi

- Kullanıcının verdiği `Yeniler` klasörü `11zbrunHoiTZyJ8JDsj99ascO66mmCj-M` (`Ortak 2 Mizah`) altında ve boş. Tarladaki Fasulye ile Beyinsiz Penguen için aynı intake klasörü olarak kullanılamaz.
- Altı hesabın mevcut yayın klasörleri doğrulandı; ToonZone'daki `Kapaklar` klasörü mevcut kapak içeriği olarak korundu. Diğer hedeflerin mevcut dosyalarına dokunulmadı.
- Altı yeni intake klasörü oluşturma denemesi Drive API'den `403 insufficientParentPermissions` ile reddedildi. Tarayıcıdaki aynı paylaşılan üst klasörde `Yeni` düğmesi de devre dışıydı. Dolayısıyla altı `collection_folder_id` boş bırakıldı; kimlik uydurulmadı ve yetki/aşım yapılmadı.
- Drive connector'ıyla listeleme ve metadata okuma mümkün; bu, GitHub Actions `DRIVE_TOKEN_JSON` kimliğinin okuma/yazma yetkisini doğrulamıyor. Dosya yükleme veya üretim tokenıyla yazma testi yapılmadı.

## Hesaplar, hedefler ve kapılar

- Altı rota: `tarladaki`, `penguen`, `gonle`, `daily_laugh`, `film`, `toonzone`. Her birinde hedef günlük plan 3 yeni + 3 arşiv video; mevcut limit kaynak başına günde 2.
- Altı rotada toplama/yayın kapalı, kaynak hesap listeleri boş ve intake klasör kimlikleri boş. Kaynak hesap ve yeniden kullanım izinleri henüz verilmediğinden Instagram API çağrısı, medya toplama ve yayın yapılmadı.
- Yayın zamanları değişmedi. Film ve ToonZone seri sırası korunuyor. Film Second aktif rotaya veya kaynak kapsamına eklenmedi.
- Kodda artık bir intake klasörünün birden fazla rota tarafından paylaşılması reddediliyor.
- Yerel güvenlik düzeltmeleri iki rota yapılandırmasının aynı alım klasörünü paylaşmasını engelliyor ve resmi API indirme iznini toplama koşulu olarak zorluyor. Kaynaklar hâlâ boş, bütün kapılar kapalı.

## Bağlantılar ve maliyet

- Google Drive kullanıcı bağlantısı yanıt verdi; üst klasöre yazma yetkisi yetersiz çıktı.
- Neon kontrol panelinde `auto-video-publisher-free` projesi ve `main` branch'i bulundu; mevcut geçmiş denetimde DB adı `auto_video_publisher_live`, şema `public` olarak okundu. SQL bağlantısının endpoint'i uyandırıp maliyet doğurma olasılığı nedeniyle bu görevde yeniden sorgu/migration yapılmadı. GitHub `DASHBOARD_DATABASE_URL` hedefi doğrulanmış değil.
- NTFY/Telegram kod yolları ve yinelenen bildirim koruması denetlendi. Canlı bildirim gönderilmedi; sunucu ACK veya kod denetimi telefon teslimatını kanıtlamaz.
- Yeni ücretli servis, token, topic veya bot oluşturulmadı. Medya yüklemesi yapılmadı. Bu yüzden ek harcama başlatılmadı; platformların genel fatura durumuna dair bağımsız kanıt yok.

## Sonraki adımlar

1. Paylaşılan beş hedef üst klasöre Google Drive'da klasör oluşturma ve dosya ekleme yetkisini, kullanılan Google hesabına verin. Sonra altı ayrı alt klasör oluşturulup ID'leri yapılandırmaya eklenebilir.
2. Altı rota için kaynak Instagram kullanıcı adı/ID, kategori ve yazılı yeniden yayın izni kanıtını sağlayın.
3. GitHub Actions'ta mevcut `DRIVE_TOKEN_JSON`, `DASHBOARD_DATABASE_URL`, `META_ACCESS_TOKEN`, `NTFY_TOPIC`/`NTFY_TOPIC_URL` değerlerinin doğru ve geçerli olduğunu gizli değerleri paylaşmadan doğrulayın; `IG_SOURCE_DISCOVERY_ACTOR_ID` değişkenini kontrol edin.
4. Gerekirse normal çalışma sırasında NTFY'nin telefona ulaştığını kontrol edin; test bildirimi gönderilmedi.
5. PR #328 için CI koşumlarını sağlayın/inceleyin. Kontroller geçerse birleştirin; ardından merge SHA'sini bu dosyaya ekleyin.
