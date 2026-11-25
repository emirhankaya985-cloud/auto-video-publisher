# Kullanıcıdan gereken işlemler

PR #324 birleştirildi. Bu görevde Drive üst klasörlerine yazma denemesi, Google Drive tarafından `403 insufficientParentPermissions` ile reddedildi; aynı klasör tarayıcıda salt okunurdu. Bu nedenle Drive alım klasörleri ve GitHub yapılandırmasına klasör ID'leri eklenmesi tamamlanamadı. Canlı toplama ve yayın kapalı. Film Second etkinleştirilmedi; eski verileri ve yayın geçmişi korunuyor.

## 1. Kaynak Instagram hesapları ve içerik izinleri

Altı aktif hedef için kullanılacak kaynak Instagram kullanıcı adlarını, içerik kategorisini ve her kaynak için yeniden yayın iznini belirleyin:

- Tarladaki Fasulye — kaynaklar: eklenmedi
- Gönle Düşen — kaynaklar: eklenmedi
- Beyinsiz Penguen — kaynaklar: eklenmedi
- Daily Laugh Lab — kaynaklar: eklenmedi
- Film Mağarası — kaynaklar: eklenmedi; seri sırası korunana kadar otomatik kaynak yayını kapalı
- ToonZone — kaynaklar: eklenmedi; bölüm/part sırası korunana kadar otomatik kaynak yayını kapalı

Kaynak sahibinden yazılı izin veya lisans alın. Meta'nın resmi API erişimi yeniden yayın hakkı vermez. İzin kaydı hazır olduğunda username, resmi Instagram user ID, kategori ve izin belgesi/referansını `instagram_source_accounts.json` içindeki ilgili rota kaydına ekleyin. Yetki kanıtı olmayan kaynakları etkinleştirmeyin.

## 2. Meta API yetkilendirmesi

Meta for Developers [uygulama paneli](https://developers.facebook.com/apps/) içinde mevcut uygulamanın Instagram Graph API erişimini ve Business Discovery kullanacak yetkili profesyonel hesabı kontrol edin. Kaynak profiller Business veya Creator olmalı ve API'de bulunabilmelidir. Mevcut `META_ACCESS_TOKEN` secret'ının bu izinlerle geçerli olduğunu doğrulayın; token değerini dosyaya veya sohbete koymayın.

GitHub Actions variable `IG_SOURCE_DISCOVERY_ACTOR_ID` için yetkili keşif aktörünün Instagram user ID'si gerekir. Kullanıcı adı, ID ve Meta erişimi doğrulanmadan kaynak tarama anahtarını açmayın.

## 3. Google Drive alım klasörleri

Kolektör her hedef için mevcut yayın klasörünün altında ayrı bir alım alt klasörü bekler. Tarladaki ve Penguen aynı üst klasörü paylaşır ama alt klasörleri ayrı olmalıdır. Mevcut üst klasör bağlantıları:

- Tarladaki Fasulye: [Drive klasörünü aç](https://drive.google.com/drive/folders/11zbrunHoiTZyJ8JDsj99ascO66mmCj-M)
- Beyinsiz Penguen: [Drive klasörünü aç](https://drive.google.com/drive/folders/11zbrunHoiTZyJ8JDsj99ascO66mmCj-M)
- Gönle Düşen: [Drive klasörünü aç](https://drive.google.com/drive/folders/1OA-qvfBEcCKBCTSMj4dCz8rg2p6t0aKt)
- Daily Laugh Lab: [Drive klasörünü aç](https://drive.google.com/drive/folders/137--TeBht1yikZpMfV9VSEADbKuXZtLT)
- Film Mağarası: [Drive klasörünü aç](https://drive.google.com/drive/folders/1NvEuGQ83BmCMrzdK6ziI1nC_0zzshqJW)
- ToonZone: [Drive klasörünü aç](https://drive.google.com/drive/folders/14ee4AnUdf03dYUAdtfpHa-E9Zxyh4UZF)

Google Drive'da `Ortak 2 Mizah`, `islam olan`, `İngilizce Mizahh`, `Film` ve `cizgi film` klasörleri görüldü. `Yeniler` boş, Tarladaki/Penguen ortak üst klasöründe; iki hesap için ortak kullanılmamalı. ToonZone'daki `Kapaklar` klasörünü koruyun. Altı ayrı alt klasör oluşturabilmemiz için bu beş üst klasörde bağlı Google hesabına klasör oluşturma ve dosya ekleme yetkisi verin. Connector denemesi 403 ile reddedildi; klasörler oluşturulmadı, mevcut medya değişmedi. Sonrasında altı klasör ID'si ayrı ayrı `collection_folder_id` alanlarına yazılıp parent ve üretim token erişimi doğrulanmalı. Üretim `DRIVE_TOKEN_JSON` yazma testi henüz yapılmadı.

## 4. GitHub Actions ayarları ve entegrasyon

[Repository Actions secrets](https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/secrets/actions) içinde mevcut olması gereken secret adları: `META_ACCESS_TOKEN`, `DRIVE_TOKEN_JSON`, `DASHBOARD_DATABASE_URL`, `NTFY_TOPIC` veya `NTFY_TOPIC_URL`. Secret değerlerini paylaşmayın. [Actions variables](https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/variables/actions) tarafında `IG_SOURCE_DISCOVERY_ACTOR_ID` gerekir. Bu secret/variable adlarının varlığı ve geçerliliği bağlantılı GitHub API'den okunamıyor.

Neon bağlantısının geçmiş salt-okunur denetiminde `auto-video-publisher-free` / `main` için DB `auto_video_publisher_live`, şema `public` görülmüştü. Bu görevde endpoint'i uyandırıp maliyet doğurmamak için SQL tekrarlanmadı. GitHub `DASHBOARD_DATABASE_URL` hedefi doğrulanmış değil. Secret'ın doğru DB'yi hedeflediğini gizli değeri paylaşmadan Actions ayarlarından kontrol edin. Migration çalıştırılmadı.

PR #324 zaten birleştirildi (merge SHA `1e63e0417c35eb04bdd598316245d6b2f4634285`). PR başlığı CI'sinde 13 workflow başarılı, 2 kontrol atlandı. Birleştirme sonrası watchdog Film ve ToonZone için `publication_blocked` üretim uyarısı verdi; bu CI sonucu değildir ve tekrar çalıştırılmadı. Kaynak toplama/yayın anahtarları kapalı; production ayarlarına dokunulmadı.

## 5. NTFY telefon teslimatı

Mevcut gece raporunun NTFY gönderimi dedupe anahtarıyla yinelenmeye karşı korunuyor; hata yolu mevcut Telegram bağlantısını kullanabiliyor. Yeni workflow, topic veya bot oluşturulmadı. Canlı bildirim gönderilmedi; gerçek telefon teslimi doğrulanmadı. Bir sonraki normal gece raporunda sunucu onayını ve telefondaki bildirimi ayrı ayrı kontrol edin.

## Etkinleştirme sırası

1. Drive paylaşım ayarlarında bağlı Google hesabına klasör oluşturma ve dosya ekleme izni verin.
2. Her kaynak için username, Instagram user ID, kategori ve yazılı yayın izni kanıtını sağlayın.
3. Altı ayrı Drive alt klasörü ve parent ilişkisini doğrulayın; GitHub Actions `DRIVE_TOKEN_JSON` ve `DASHBOARD_DATABASE_URL` hedeflerini gizli değerleri açmadan teyit edin.
4. Meta actor ID'si ile mevcut GitHub secrets/variables adlarını kontrol edin; NTFY telefon teslimini normal raporda doğrulayın.
5. Kaynak toplama/yayın anahtarlarını ancak izinler ve Drive/Neon bağlantıları doğrulandıktan sonra açın. Mevcut yayın saatleri değiştirilmemeli; Film Second kapalı kalmalı.
