# ToonZone ve Film Mağarası — güvenli sıfırdan oynatma ve telafi taslağı

3 Kasım 2026. **Bu PR hiçbir paylaşımı başlatmaz.** Mevcut üretim iş akışı, saatler, tokenlar, Drive geçmişi, gönderi kimlikleri ve yükleme idempotency kuralları değişmez.

## Kullanıcının istediği telafi biçimi

- **ToonZone başlangıcı:** S01E01; her bölüm tam dört parçadır (Part1–4).
- **Normal:** günde bir bölüm / dört kaynak video (12:00, 12:10, 12:20, 12:30 Türkiye saati).
- **Telafi:** günde en çok iki bölüm / sekiz kaynak video. İlk bölüm 12:00–12:30, ikinci bölüm 18:00–18:30 (Türkiye).
- Her video hem FB hem IG'ye gönderiliyorsa bu **en çok 16 platform gönderisi** demektir; "8 toplam gönderi" değil.
- **Otomatik dönüş:** doğrulanmış eski normal yayın akışı bölümüne ulaşınca, sonraki gün tek bölüm/gün düzenine dönmek gerekir. Eski akışın karşılaştırılabilir bölüm kimliği (rejoin episode) kayıtlardan doğrulanmadan canlı hızlandırma açılamaz.
- **Film Mağarası:** eser/film başlığı, tam part sayısı, Facebook/Instagram tarihçesi ve önceki belirsiz niyetler ayrı ayrı uzlaştırılmalı; körlemesine Part1'e dönüş veya "5'ten 10'a" kota artırımı yapılmaz.

## Bu PR ne yapıyor?

`series_catchup_preview.py` bağımsız, salt-okunur sıra/ritim hesaplaması sunar. S01E01, doğrulanmış `rejoin_episode`, Drive `id,name` envanteri ve gerçek yayın geçmişinin önceden denetlenmiş `entries` verisi olmadan çalışma veya güncelleme yapmaz.

İçerik doğrulamalarında tam 4 parça/episode, farklı ID/isimlerin tek parçaymış gibi görülmemesi, en az bir platformda belirsiz veya kısmen paylaşılmış geçmiş varsa tüm sıranın **HELD** olması, eski iki-platform `done+post_id` kayıtlarının **SKIP** edilmesi esastır. Aynı kaynak önce yayımlandı diye kayıt silinmez, ikinci tur otomatik repost yapılmaz. Kod gerçek API veya Drive'a bağlanmaz.

## Canlı yayına geçmeden zorunlu

1. Güncel Meta + Drive + GitHub `link-state-result` kaynak eşleştirmesi: özellikle Film'in mevcut belirsiz kaydı. Önce `post_id` doğrulaması.
2. ToonZone S01E01'in dört gerçek MP4'ü var mı? Daha önce iki platformda yayımlandı mı? Kullanıcı "sıfırdan" ile **bilerek tekrar paylaşımı** kastediyorsa yeni tur ayrı ve açık şekilde onaylanmalı; eski yayımlar otomatik kopyalanmamalı.
3. Yayına alınacak yeni takvim üretim `public_link_runtime.py` + `public_link_schedule.yml` içinde **opt-in**, günlük kota ve seri sırası aynı noktadan doğrulanmalı, değişken kapalıyken eskisi birebir çalışmalı. PR #90'ın genel telafi işiyle çatışma olmamalı.
4. İlk gün gerçek sekiz kaynak yayınları için her platform `post_id`, tarih, sıradaki `SxxExx Partx` ve duplicate-safe tekrar çalıştırma PASS ispatlanmalı. Aksi halde 4 parça/gün veya duraklatma.
5. Sadece kullanım hakları doğrulanmış içerik paylaşılmalı; platform kuralları ve hesap kapasitesi aşılmamalı.

## Durum

- **Planın güvenlik testi:** Bu PR ile CI'da (sahte veriler) doğrulanır.
- **Canlı seri reseti ve 8 parça/gün:** **ETKİN DEĞİL**.
- **Beş Threads hesabının GET erişimi doğrulandı; Penguen Threads HTTP 401:** Threads sorunu bu seri çalışmasını değiştirmez.
