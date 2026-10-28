# Telegram + NVIDIA analiz yardımcısı

Model varsayılanı NVIDIA kataloğundaki `nvidia/nemotron-3.5-super-vl-120b-a12b`; farklı model
seçilirse `NVIDIA_MODEL` değiştirilebilir. Endpoint sabit NVIDIA HTTPS API'sidir.
Bu entegrasyon ücretsiz/sınırsız kullanım garantisi vermez; hesabın sağlayıcı
limitleri geçerlidir. Otomatik ücretli sağlayıcı geçişi veya POST retry yoktur.
Nemotron için metin örneğindeki temperature=1/top_p=0.95 kullanılır. Sohbet ve
özetlerde düşünme çıktısı kapalıdır (`chat_template_kwargs.enable_thinking=false`),
yalnız son yanıt Telegram'a gönderilir. Görsel örneği ve tool çağrısı kullanılmaz.

## Gece özeti

GitHub repository Secrets: `NVIDIA_API_KEY`. Repository Variables:
`NVIDIA_AI_ENABLED=true`, isteğe bağlı `NVIDIA_MODEL`.
Mevcut Telegram secret'ları kullanılır. Anahtarı sohbete veya depoya yazmayın.
23:15 TRT raporu mevcut üç tabloyu gönderdikten sonra ek AI yorumu gönderir.
AI kapalı veya erişilemezse normal hesap tabloları bağımsız kalır.
Model yorumu ölçüm kaydı değildir; doğrulanmış tablolar asıl kaynaktır.

## Karşılıklı sohbet

Sürekli açık tek bir Python süreci gerekir. GitHub cron anlık sohbet sunucusu
değildir. Ücretsiz mevcut bilgisayar/sunucuda, kilitli requirements kurulumu
sonrasında `python telegram_ai_worker.py` çalıştırın. Bilgisayar kapalıysa
sohbet cevap vermez. Bu PR herhangi bir ücretli host oluşturmaz.

Süreç ortamı:

| Değişken | Gereken değer |
| --- | --- |
| `NVIDIA_AI_ENABLED` | `true` |
| `NVIDIA_API_KEY` | NVIDIA anahtarı (gizli) |
| `NVIDIA_MODEL` | varsayılan `nvidia/nemotron-3.5-super-vl-120b-a12b` |
| `TELEGRAM_BOT_TOKEN` | mevcut bot token'ı (gizli) |
| `TELEGRAM_CHAT_ID` | izinli sohbet kimliği |
| `TELEGRAM_AI_OWNER_ID` | yalnız sahibin sayısal kullanıcı kimliği |
| `GITHUB_TOKEN` | yalnız bu deponun Actions artifact'larını okuyabilen token |
| `TELEGRAM_AI_DB` | kalıcı diskte SQLite yolu; varsayılan `ai-runtime/telegram.sqlite3` |

Sadece ortam değişkenleri okunur; `.env` otomatik yüklenmez. SQLite sohbetin
son üç soru/yanıtını ve işlenen Telegram offset'ini tutar. Ölçüm arşivini
değiştirmez. Aynı botu başka `getUpdates` tüketicisiyle çalıştırmayın. Aktif
webhook varsa süreç onu silmeden durur. Başlangıçta Telegram'ın bekleyen
mesajları işlenebilir. En fazla 24 saatlik bekleyen mesaj tutulur.

Komutlar: `/start`, `/help`, `/ozet`, `/durum`, `/sifirla`; normal Türkçe
sorular da yanıtlanır. Hem chat hem kullanıcı kimliği doğrulanır. Modelin
hesaplara yazma/yayınlama aracı yoktur. Kaynak sabit main branch'teki başarılı
`daily_stats.yml` karşılaştırma artifact'ı ve son 30 günlük hesap arşividir.
Video açıklamaları ve kimlikleri modele gönderilmez. Ölçüm tarihi yanıtın
bağlamındadır; son arşiv canlı sayaç gibi sunulmaz. Yayın sonuçları bu ilk
bağlamda yoktur; model yayın başarı sayısı çıkarmamalıdır.

Offset, API çağrılarından önce kalıcı kaydedilir. Süreç çökmesi/belirsiz
Telegram teslimatı durumunda aynı soru otomatik tekrar gönderilmez; kullanıcı
yeniden sorabilir. Birden fazla worker aynı anda başlatılmamalıdır.

## Canlı kabul ve geri alma

Anahtar ve sürekli süreç olmadan canlı sohbet hazır sayılmaz. Etkinleştirdikten
sonra `/durum` ile gerçek ölçüm tarihi, `/ozet` ile model yanıtı ve ikinci bir
soruyla sohbet devamı doğrulanmalı. Yetkisiz kullanıcı yanıt alamamalı.
Anahtarı/logları paylaşmayın. Model yanıtı sayısal tablolarla karşılaştırılmalı.
Kapatma: `NVIDIA_AI_ENABLED=false` ve worker'ı durdurma. Yayıncı, arşiv ve
normal Telegram tablolarına dokunulmaz. Canlı mesaj testleri kendiliğinden
tetiklenmez; API erişimi kurulmadan kabul edilmez.
