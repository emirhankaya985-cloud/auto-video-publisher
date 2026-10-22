import os
import time
import json
import requests

AUTH_FILE = os.path.join(os.path.dirname(__file__), 'meta_auth.json')

def load_auth():
    if not os.path.exists(AUTH_FILE):
        raise FileNotFoundError(f"{AUTH_FILE} bulunamadı!")
    with open(AUTH_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_page_info(target_name="Tarladaki Fasulye"):
    auth = load_auth()
    pages = auth.get('pages', [])
    if not pages:
        raise ValueError("Kayıtlı Facebook sayfası bulunamadı!")
    
    # Hedef sayfayı ara
    for p in pages:
        if target_name and target_name.lower() in p.get('page_name', '').lower():
            return p, auth.get('long_user_token')
            
    # Eğer hedef bulunamazsa instagram_id olan ilk sayfayı seç
    for p in pages:
        if p.get('instagram_id'):
            return p, auth.get('long_user_token')
            
    return pages[0], auth.get('long_user_token')

def refresh_instagram_id(target_name="Tarladaki Fasulye"):
    """Facebook sayfasına bağlı Instagram hesabını sorgular ve auth dosyasına kaydeder."""
    page, _ = get_page_info(target_name)
    ig_id = page.get('instagram_id')
    if ig_id:
        print(f"✅ Bağlı Instagram Hesabı Aktif: {page.get('page_name')} -> IG ID: {ig_id}")
        return ig_id
        
    page_id = page['page_id']
    page_token = page['page_token']
    url = f"https://graph.facebook.com/v20.0/{page_id}?fields=instagram_business_account&access_token={page_token}"
    res = requests.get(url).json()
    ig_acc = res.get('instagram_business_account')
    if ig_acc and ig_acc.get('id'):
        page['instagram_id'] = ig_acc['id']
        auth = load_auth()
        for p in auth.get('pages', []):
            if p.get('page_id') == page_id:
                p['instagram_id'] = ig_acc['id']
        with open(AUTH_FILE, 'w', encoding='utf-8') as f:
            json.dump(auth, f, indent=2, ensure_ascii=False)
        print(f"✅ Bağlı Instagram Hesabı Tespit Edildi: {page['instagram_id']}")
        return page['instagram_id']
    else:
        print("⚠️ Facebook sayfasına bağlı bir Instagram Business/Creator hesabı henüz bulunamadı.")
        return None

def upload_facebook_reel(video_path: str, caption: str):
    """Facebook Sayfasına doğrudan Reels videosu yükler."""
    page, _ = get_page_info()
    page_id = page['page_id']
    page_token = page['page_token']
    
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video bulunamadı: {video_path}")
        
    file_size = os.path.getsize(video_path)
    print(f"\n[Facebook Reels] Başlatılıyor: {os.path.basename(video_path)} ({file_size / (1024*1024):.2f} MB)")
    
    # Adım 1: Oturum Başlat
    init_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
    init_resp = requests.post(init_url, data={
        'upload_phase': 'start',
        'access_token': page_token
    }).json()
    
    if 'video_id' not in init_resp or 'upload_url' not in init_resp:
        raise RuntimeError(f"FB Reels başlatma hatası: {init_resp}")
        
    video_id = init_resp['video_id']
    upload_url = init_resp['upload_url']
    print(f"  -> Video ID: {video_id}")
    
    # Adım 2: Binary Video Verisini Yükle
    print("  -> Video verisi Facebook sunucusuna aktarılıyor...")
    headers = {
        'Authorization': f'OAuth {page_token}',
        'offset': '0',
        'file_size': str(file_size)
    }
    with open(video_path, 'rb') as f:
        video_data = f.read()
        
    upload_resp = requests.post(upload_url, headers=headers, data=video_data)
    if upload_resp.status_code not in (200, 201):
        raise RuntimeError(f"FB Video yükleme hatası: {upload_resp.text}")
    print("  -> Video aktarımı tamamlandı!")
    
    # Adım 3: Yayına Al (Publish)
    print("  -> Reels olarak yayınlanıyor...")
    finish_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
    finish_data = {
        'upload_phase': 'finish',
        'access_token': page_token,
        'video_id': video_id,
        'video_state': 'PUBLISHED',
        'description': caption
    }
    finish_resp = requests.post(finish_url, data=finish_data).json()
    if not finish_resp.get('success'):
        raise RuntimeError(f"FB Reels yayınlama hatası: {finish_resp}")
        
    print(f"🎉 [Facebook Reels] Başarıyla Yüklendi ve Yayınlandı! (Video ID: {video_id})")
    return video_id

def upload_instagram_reel(video_path: str, caption: str):
    """Instagram Hesabına doğrudan Reels videosu yükler."""
    page, _ = get_page_info()
    ig_user_id = page.get('instagram_id')
    page_token = page['page_token']
    
    if not ig_user_id:
        ig_user_id = refresh_instagram_id()
        if not ig_user_id:
            raise RuntimeError("Instagram hesabı Facebook sayfasına bağlı değil!")

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video bulunamadı: {video_path}")
        
    file_size = os.path.getsize(video_path)
    print(f"\n[Instagram Reels] Başlatılıyor: {os.path.basename(video_path)} ({file_size / (1024*1024):.2f} MB)")
    
    # Adım 1: Resumable Container Başlat
    container_url = f"https://graph.facebook.com/v20.0/{ig_user_id}/media"
    container_data = {
        'access_token': page_token,
        'upload_type': 'resumable',
        'media_type': 'REELS',
        'caption': caption
    }
    init_res = requests.post(container_url, data=container_data).json()
    if 'id' not in init_res or 'uri' not in init_res:
        raise RuntimeError(f"Instagram Container başlatma hatası: {init_res}")
        
    container_id = init_res['id']
    upload_uri = init_res['uri']
    print(f"  -> Container ID: {container_id}")
    
    # Adım 2: Binary Video Verisini Yükle
    print("  -> Video verisi Instagram sunucusuna aktarılıyor...")
    headers = {
        'Authorization': f'OAuth {page_token}',
        'offset': '0',
        'file_size': str(file_size)
    }
    with open(video_path, 'rb') as f:
        video_data = f.read()
        
    upload_resp = requests.post(upload_uri, headers=headers, data=video_data)
    if upload_resp.status_code not in (200, 201):
        raise RuntimeError(f"Instagram Video aktarma hatası: {upload_resp.text}")
    print("  -> Video aktarımı tamamlandı! Sunucunun işlemesi bekleniyor...")
    
    # Adım 3: İşleme Durumunu Kontrol Et (Polling)
    status_url = f"https://graph.facebook.com/v20.0/{container_id}?fields=status_code&access_token={page_token}"
    for _ in range(30):
        time.sleep(5)
        st_res = requests.get(status_url).json()
        status_code = st_res.get('status_code')
        print(f"  -> Instagram İşleme Durumu: {status_code}")
        if status_code == 'FINISHED':
            break
        elif status_code == 'ERROR':
            raise RuntimeError(f"Instagram video işleme hatası: {st_res}")
            
    # Adım 4: Yayınla (Publish)
    print("  -> Instagram'da Reels olarak yayına alınıyor...")
    pub_url = f"https://graph.facebook.com/v20.0/{ig_user_id}/media_publish"
    pub_res = requests.post(pub_url, data={
        'creation_id': container_id,
        'access_token': page_token
    }).json()
    
    if 'id' not in pub_res:
        raise RuntimeError(f"Instagram yayınlama hatası: {pub_res}")
        
    print(f"🎉 [Instagram Reels] Başarıyla Yüklendi ve Yayınlandı! (Reels ID: {pub_res['id']})")
    return pub_res['id']

if __name__ == '__main__':
    raise SystemExit("Eski yardımcı doğrudan çalıştırılamaz. Aktif giriş: scheduled_multi_publisher.py")
