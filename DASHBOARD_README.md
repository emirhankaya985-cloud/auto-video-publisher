# Özel İstatistik Paneli

Render üzerinde çalışan, parola korumalı salt-okunur panel. Günlük, haftalık, aylık ve tüm dönem görünümleri; hesap/platform kırılımı ve çizgi/dairesel grafikler sunar. Veriler yalnız mevcut doğrulanmış istatistik arşivinden alınır; ölçüm bulunmazsa boş bırakılır.

## Güvenlik
- Bu repo public olduğundan gerçek istatistik verisi, token veya parola buraya commit edilmez.
- Panel API'si `DASHBOARD_PASSWORD` Bearer değerini doğrulamadan veri döndürmez.
- Rapor artifact'ı yalnız runner'ın geçici alanında açılır; private Render endpoint'ine gönderilir.
- Gerçek Render dağıtımı, archive push endpoint/token ve ortak erişim parolası Render secrets olarak girildikten sonra etkinleştirilir.
- Bu ayarlar kurulana dek raporlar otomatik aktarılmaz ve panelde veri görünmez.

## Veriler
Günlük snapshotlar platform/API erişimine göre farklı dönemlerde oluşabilir. Aylık değer, son ölçümden 30 gün öncesiyle kıyaslanır; kıyas tabanı yoksa N/A/boş görünür. Etkileşim ve oturum kayıtları bu arşivde olmadığı için uydurulmaz.
