# Kullanıcıdan gereken işlemler

Teknik kod yerel branch'te hazırlandı. Canlı toplama ve yayın, aşağıdaki bilgiler ve izinler doğrulanana kadar kapalı kalacak. Film Second yeni kaynak toplama ve publisher workflow matrisinden çıkarıldı; eski verileri ve yayın geçmişi korunuyor.

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

Google Drive bağlantısı yanıt verdi ve beş ayrı mevcut yayın parent klasörü klasör metaverisi olarak çözümlendi. Ancak connector `source_visibility_status=access_not_verified` döndürdü; bu, GitHub Actions `DRIVE_TOKEN_JSON` erişimini doğrulamaz. Her aktif rota için uygun ayrı bir intake alt klasörü seçin; yoksa açıkça izin verip oluşturun. Klasör kimliğini ilgili `collection_folder_id` alanına ekleyin. Altı intake klasör ID'si şu anda boş; parent ilişkisi, üretim token erişimi ve kota doğrulanmadan toplama açılmamalı.

## 4. GitHub Actions ayarları ve entegrasyon

[Repository Actions secrets](https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/secrets/actions) içinde mevcut olması gereken secret adları: `META_ACCESS_TOKEN`, `DRIVE_TOKEN_JSON`, `DASHBOARD_DATABASE_URL`, `NTFY_TOPIC` veya `NTFY_TOPIC_URL`. Secret değerlerini paylaşmayın. [Actions variables](https://github.com/emirhankaya985-cloud/auto-video-publisher/settings/variables/actions) tarafında `IG_SOURCE_DISCOVERY_ACTOR_ID` gerekir. Bu secret/variable adlarının varlığı ve geçerliliği bağlantılı GitHub API'den okunamıyor.

Neon connector bağlantısı salt-okunur sorguyla doğrulandı: `auto-video-publisher-free` projesinin `main` branch'inde DB adı `auto_video_publisher_live`, schema `public`. Bu, GitHub `DASHBOARD_DATABASE_URL` değerinin aynı veritabanına işaret ettiğini kanıtlamaz. Repo secret'ının doğru DB'yi hedeflediğini, değeri paylaşmadan GitHub Actions ayarlarından kontrol edin. Migration çalıştırılmadı.

PR #324 oluşturuldu ve ilk düzeltilmiş branch'te 13 otomatik no-publish/read-only CI workflow'u geçti. `main` sonrasında yeni bir commit aldığı için branch yeniden hizalanıyor ve latest-head CI bekleniyor. Merge ancak güncel branch kontrolleri geçerse yapılacak. Kaynak toplama/yayın anahtarları kapalı; production secret değerleri değiştirilmedi.

## 5. NTFY telefon teslimatı

Mevcut gece raporu NTFY yoluna kaynak özeti eklendi; yeni workflow veya yeni ücretli bildirim servisi eklenmedi. GitHub secret'larında geçerli `NTFY_TOPIC` veya `NTFY_TOPIC_URL` olduğunu doğrulayın. NTFY uygulamasında ilgili topic'e abone olun ve bir sonraki normal gece raporunda sunucu onayı ile telefon ekranındaki görünür bildirimi ayrı ayrı kontrol edin. Sunucu ACK telefonda teslimi kanıtlamaz.

## Etkinleştirme sırası

1. Her kaynak için username, Instagram user ID, kategori ve yayın izni kanıtını ekleyin.
2. Her aktif hedef için ayrı Drive alt klasörünü ve parent ilişkisini doğrulayın.
3. Meta actor ID ve mevcut GitHub secrets/variables adlarını kontrol edin.
4. PR #324 latest-head CI tamamlandıktan sonra merge durumunu kontrol edin.
5. Önce yalnız `IG_SOURCE_COLLECTION_ENABLED=true` ile toplamayı etkinleştirin; sonuçlar doğru görünürse rota bazlı anahtarları açın. `IG_SOURCE_PUBLISHING_ENABLED` ve mevcut publisher anahtarı izinler, sıralama ve raporlar doğrulanana kadar kapalı kalsın.
