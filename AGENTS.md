# Çalışma kuralları

- Kullanıcının açık izni olmadan grafik tarayıcı açma; Brave, Chrome, Playwright, Selenium ve görsel tarayıcı otomasyonu kullanma.
- Öncelikle terminal, mevcut kaynak kodu, GitHub CLI, GitHub Actions logları ve doğrudan API isteklerini kullan.
- Gereksiz ekran görüntüsü, sayfa gezintisi, tekrar araştırma ve uzun log çıktısından kaçın; sonuçları filtrele.
- Daha önce doğrulanmış bilgileri yeniden araştırma.
- Üretim yayını, secret değişikliği veya kapsam dışı kanal değişikliği için yetki sınırlarını koru.

- Yeni ajan veya model devralmasında önce **`SOL_6_1_ONE_SHOT.md`**, ardından `SOL_6_1_HANDOFF.md` ve `README.md` dosyalarını oku; güncel master SHA ve açık PR durumunu yeniden doğrula.
- Ayrı ajanlar aynı dosyalarda çalışıyorsa önce sahiplik/çakışma kontrolü yap; gerçek yayın, token yenileme ve veri silme yapmadan önce izin sınırlarını koru.
- İşler GitHub'da runner atanmadan 0 adımda bitiyorsa bunu kaynak kodu testi sanma; `SOL_6_1_ONE_SHOT.md` içindeki kanıtları ve GitHub Actions hesap bütçesi/Annotations engelini incele. Gerçek yayın workflow'unu test için zorla tetikleme.

## Üretim arızalarını unutma — zorunlu kurtarma defteri

**Her yeni ajan, Codex görevi, PR ve prod müdahalesi öncesinde
[`docs/PRODUCTION_RECOVERY_RUNBOOK.md`](docs/PRODUCTION_RECOVERY_RUNBOOK.md)
dosyasını oku.** 22–24 Ekim 2026'da gerçek loglarla kanıtlanan başarısız
çalışmaları, HTTP 400/429/5xx, Drive FileURLRetrievalError, IG ffmpeg,
gece-yarısı/TXT/kapak, ToonZone sıralaması ve eski-yeni workflow farkını
yeni bir işte silme veya göz ardı etme.

- Her yeni gerçek arıza için bu runbook'a tarih, çalıştırma linki, açık neden,
  güvenli aksiyon, test ve canlı kanıt ekle; önceki olay kayıtlarını koru.
- `public_link_schedule.yml` yayın yolu; geçmiş yayıncıları
  `AUTOMATION_ENABLED` ile açma. Hak onayı ve API kimliği kontrolünü atlama.
- Kural: **Salt-okunur GET ve video hazırlığını sınırla/yeniden dene;
  sonucu belirsiz Meta POST'u asla körlemesine yineleme.**
- `link-state-intent`, `link-state-result`, `link-incident-report`
  artifact'larını kontrol et. Hata sonrası state'i sıfırlama.
- CI yeşil ama post ID yoksa "yayın tamam" deme. Canlı post ID ve
  hesap geçmişi olmadan prod kabul: **UNVERIFIED**.
- Kullanıcı NTFY, eski Drive/YouTube OAuth ve eski yayıncı yetkilendirmesini
  başka sohbette yürütüyor. ToonZone sezon 2 kapakları da kullanıcıya ait;
  bu alanlarda kullanıcıya aynı soruları tekrar sorma.

## Kullanıcının 1 Kasım 2026 Meta bağlantı tercihi

- Kullanıcı Meta bağlantısını yalnız `META_ACCESS_TOKEN` ile yönetmek istiyor. Kullanıcıdan Page-token JSON oluşturmasını, kopyalamasını veya `META_AUTH_JSON` secret'ı eklemesini tekrar isteme.
- Token tabanlı keşif ve kimlik denetimini kullan. Kullanıcı bu tercihi açıkça değiştirmedikçe JSON yedeğini zorunlu kurulum veya kurtarma adımı yapma.
- Bu tercih kaydı canlı erişimin düzeldiği anlamına gelmez; kimlik GET ve normal schedule yayın kanıtını ayrı doğrula.
