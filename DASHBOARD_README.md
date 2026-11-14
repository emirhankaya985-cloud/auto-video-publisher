# Özel Sosyal Medya İstatistik Paneli

Panel günlük ölçüm arşivindeki görüntülenme, takipçi/abone, video sayısı ve hesap/platform dağılımını gösterir. Günlük, haftalık, aylık ve tüm dönem filtreleri; çizgi grafik, dairesel grafik ve hesap kırılımı içerir.

## Güvenlik ve veri kaynağı
- Render'da `DASHBOARD_PASSWORD` zorunlu; parola uygulama koduna veya GitHub'a yazılmaz.
- API yalnızca doğru Bearer parolasıyla veri döndürür; yanıtlar önbelleğe alınmaz.
- Arşiv, günlük istatistik workflow'unun `meta-daily-analytics-history` artifact'ından alınır.
- API/token/secret veya platformlara yazma işlemi yoktur. Geçmişte olmayan veri N/A/boş kalır.
- Artifact eksik veya bozuksa mevcut veri sıfırlanmaz; yalnız değişiklik varsa commit edilir.

## Çalıştırma
```bash
DASHBOARD_PASSWORD='uzun-rastgele-bir-parola' python dashboard_server.py
```

Render Blueprint yapılandırması `render-dashboard.yaml` içindedir. Servisi kurarken Dashboard Password alanına ortak parolayı Render secret olarak gir. Uygulama için ek ücretli veritabanı gerekmiyor.
