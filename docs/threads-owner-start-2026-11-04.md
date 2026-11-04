# 4 Kasım 2026 Threads yayını

Kullanıcı mevcut Threads hesaplarında elle ilk yayını ve ardından otomatik video yayını istedi. Bu işaret, ana dala alındığında hesap başına en fazla bir uygun gönderiyle ilk kontrollü çalışmayı başlatır. Daha sonra normal Meta zamanlamasının tamamlanması aynı yayın akışını tetikler. GitHub Actions üzerinden elle tetikleme de kullanılabilir.

Yalnız mevcut yayın kayıtlarında gönderi kimliği doğrulanmış ve ilgili Instagram hesabının medya listesinde bulunan yakın tarihli videolar kullanılır. İlk seçim en yeni uygun videodur. Daha sonra kaynak zamanı ileri gider. Özgün Drive MP4 dosyasının SHA-256 değeri önceki yayın kaydıyla doğrulanır. Threads için yalnız mevcut herkese açık Drive indirme yolu kullanılır. İlk Meta yazısından önce Threads niyeti arşivlenir. Belirsiz sonuç, Threads profilinde kesin olarak eşleşene kadar aynı hesapta tekrar denenmez. Yayın kabulü Threads gönderi kimliği ve kalıcı bağlantı gerektirir.

İlk çalışma 41869402302: Beş Threads containerı ERROR döndü ve hiçbirinde threads_publish çağrısı yapılmadı. Penguen kimlik sorgusu HTTP 401 döndü. Bu beş kesin yayın öncesi hata, aynı kaynak doğrulanarak yalnız bir kez alternatif Drive yoluyla yeniden denenebilir.
