# Çalışma kuralları

- Kullanıcının açık izni olmadan grafik tarayıcı açma; Brave, Chrome, Playwright, Selenium ve görsel tarayıcı otomasyonu kullanma.
- Öncelikle terminal, mevcut kaynak kodu, GitHub CLI, GitHub Actions logları ve doğrudan API isteklerini kullan.
- Gereksiz ekran görüntüsü, sayfa gezintisi, tekrar araştırma ve uzun log çıktısından kaçın; sonuçları filtrele.
- Daha önce doğrulanmış bilgileri yeniden araştırma.
- Üretim yayını, secret değişikliği veya kapsam dışı kanal değişikliği için yetki sınırlarını koru.

- Yeni ajan veya model devralmasında önce **`SOL_6_1_ONE_SHOT.md`**, ardından `SOL_6_1_HANDOFF.md` ve `README.md` dosyalarını oku; güncel master SHA ve açık PR durumunu yeniden doğrula.
- Ayrı ajanlar aynı dosyalarda çalışıyorsa önce sahiplik/çakışma kontrolü yap; gerçek yayın, token yenileme ve veri silme yapmadan önce izin sınırlarını koru.
- İşler GitHub'da runner atanmadan 0 adımda bitiyorsa bunu kaynak kodu testi sanma; `SOL_6_1_ONE_SHOT.md` içindeki kanıtları ve GitHub Actions hesap bütçesi/Annotations engelini incele. Gerçek yayın workflow'unu test için zorla tetikleme.
