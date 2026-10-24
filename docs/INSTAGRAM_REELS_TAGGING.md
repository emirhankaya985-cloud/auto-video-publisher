# Instagram @mention, hashtag ve gerçek Reels kişi etiketi

Bu sistem **yalnızca** Instagram'ı etkiler. `instagram_tagging.py` ve
`instagram_tag_rules.json` kullanılır. Yayın öncesi TXT açıklaması
yüklenir, doğru video için ekleme yapılır ve yeni açıklamanın hash'i
Meta geçmişiyle karşılaştırılır. Facebook açıklaması değiştirilmez.

## Neler desteklenir?

- Açıklamada `@cristiano` ve `#CR7` gibi etiketler.
- Gerçek Instagram Reels kişi etiketi: Media container oluştururken
  `user_tags=[{"username":"cristiano"}]`; Reels'te x/y koordinat
  gerekmez. Hedef hesabın etiketleme tercihleri nedeniyle görünme /
  bildirim garantili değildir.
- Yanlış eşleşmeleri engellemek için **route + tam video dosyası adı**
  zorunludur. Herhangi bir video otomatik olarak 'Ronaldo videosu'
  varsayılmaz. Onaysız kullanıcı etiketi eklenmez.
- Aynı @mention veya hashtag iki kere eklenmez; 2200 karakter
  aşılıyorsa açıklama kırpılıp sessiz yayınlanmaz, açık hata verilir.

## Örnek — yalnız bir Ronaldo videosu için (varsayımsal)

`instagram_tag_rules.json` dosyasını şu şekilde düzenle:

```json
{
  "schema": 1,
  "rules": [
    {
      "route": "film",
      "stem": "ronaldo_goal_01",
      "usernames": ["cristiano"],
      "hashtags": ["Ronaldo", "CR7", "Football"]
    }
  ]
}
```

Bu örnek kural **gerçek videolara bağlanmış değildir**. Dosya adı
`ronaldo_goal_01.mp4` ve rota `film` gerçekten mevcutsa geçerlidir.
Kendi içeriklerine uygun kuralı eklemeden bütün canlı hesaplara Ronaldo
etiketi göndermek yasaktır.

## Meta ve güvenli yayın

- Aktif kullanıcı izinleri: `instagram_basic`,
  `instagram_content_publish`, `pages_read_engagement`,
  `pages_show_list`. Gerçek etiketleme için izin tek başına yeterli
  olmayabilir; hedef hesap açık profil ve etiketlere izin veriyor olmalıdır.
- Media container'da yalnız **onaylanmış video** için `user_tags` kullanılır.
- Yeni JSON kuralları boş başladığı için geçmişteki veya alakasız
  hiçbir videonun açıklaması değişmez. Bu, caption hash'e dayalı
  tekrar-yayın güvenliğini korur.
- Media publish gönderildikten sonra sonuç belirsiz kalırsa yeniden
  POST **yapılmaz**. `docs/PRODUCTION_RECOVERY_RUNBOOK.md` geçerlidir.
- Testler: `python -m unittest test_instagram_tagging test_instagram_binary_upload test_public_link_runtime`.
- Testlerin yeşil olması `@cristiano` etiketinin Ronaldo'nun
  profilindeki Etiketlenenler bölümünde göründüğünü kanıtlamaz; bunun
  için açıkça seçilmiş tek yeni videoda gerçek post-ID ve etiket
  görünürlüğü ayrıca kontrol edilmelidir.

Kaynak: Meta Instagram Content Publishing API
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/content-publishing/
