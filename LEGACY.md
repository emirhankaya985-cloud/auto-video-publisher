# Eski yayın motorları

Aktif üretim girişi `scheduled_multi_publisher.py` dosyasıdır.

`cloud_uploader.py`, `cloud_meta_publisher.py`, `meta_uploader.py` ve
`cloud_omnichannel_publisher.py` içindeki eski toplu çalıştırıcılar doğrudan
çalıştırmaya karşı kapatılmıştır. `cloud_omnichannel_publisher.py`, aktif
sistemin kullandığı API ve video yardımcılarını barındırdığı için yerinde
tutulmuştur.

Eski motorları yalnızca bilinçli kurtarma işlemi için çalıştırmak gerekirse
`ENABLE_LEGACY_PUBLISHER=I_UNDERSTAND` değişkeni açıkça verilmelidir.
