# 31 Ekim 2026 salt-okunur Meta kimlik doğrulama tetikleyicisi

Bu işaretçi dosyanın `main` dalına tek seferlik eklenmesi yalnız
`.github/workflows/meta_page_token_health.yml` içindeki read-only `audit`
job'unu başlatır. Bunun dışındaki video yayınlama veya etkileşim workflow'u
bu dosyaya bağlı değildir.

Amaç: aynı kod sürümünde yayın başarılıyken yaklaşık bir saat sonra
`/me/accounts` GET ile alınan `HTTP 401 / Graph code 190` hatasının
varsa sayısal `error_subcode` değerini güvenli bir GitHub Actions
günlüğünde görmek. Ham hata yanıtı, bearer, token, gizli anahtar veya
konfigürasyon JSON'u hiçbir zaman dosyaya ya da loga yazılmaz.

Kimlik doğrulama başarısızsa kod fail-closed kalır; hiçbir eski video
yeniden yüklenmez, belirsiz Instagram container temizlenmez ve
100/100 kabul verilmez. Çalıştırma yalnız kimlik okuma GET yapar.

1 Kasım: malformed saved JSON fallback regression fixed; rerun GET-only identity audit on this merge. No media POST, secret mutation or publication.
