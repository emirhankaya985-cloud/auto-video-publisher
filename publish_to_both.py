import os
import re
import json
from pathlib import Path
from upload_to_both_channels import upload_and_report

VIDEOS_DIR = Path(r"C:\Users\emirh\Desktop\mahmut\Sosyal Medya 5\videos\mizah")
HISTORY_FILE = Path(r"C:\Users\emirh\Desktop\mahmut\video-automation\upload_history.json")

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def parse_txt_file(txt_path: Path) -> dict:
    content = txt_path.read_text(encoding="utf-8", errors="ignore").strip()
    
    title = ""
    description = ""
    tags = []

    # Format 1: Başlık / Açıklama / Etiketler
    if "başlık:" in content.lower() or "baslik:" in content.lower():
        lines = content.splitlines()
        desc_lines = []
        for line in lines:
            ls = line.strip()
            if ls.lower().startswith("başlık:") or ls.lower().startswith("baslik:"):
                title = ls.split(":", 1)[1].strip().strip('"').strip('“').strip('”')
            elif ls.lower().startswith("açıklama:") or ls.lower().startswith("aciklama:"):
                desc_lines.append(ls.split(":", 1)[1].strip())
            elif ls.lower().startswith("etiketler:") or ls.lower().startswith("tags:"):
                tags = re.findall(r'#(\w+)', ls)
            elif ls:
                desc_lines.append(ls)
        description = "\n".join(desc_lines)
    else:
        # Format 2: Düz metin (İlk cümleyi başlık yap)
        sentences = re.split(r'[.!?\n]', content)
        first_sentence = sentences[0].strip() if sentences else content[:60]
        title = first_sentence[:60]
        description = content
        tags = ["Mizah", "Shorts", "Komik", "Eglence"]

    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"

    title = title[:100]

    return {
        "title": title,
        "description": description,
        "tags": tags
    }

def publish_next_video_to_both(privacy="public"):
    history = load_history()
    
    mp4_files = sorted(
        list(VIDEOS_DIR.glob("*.mp4")),
        key=lambda x: int(x.stem) if x.stem.isdigit() else x.stem
    )

    target_pair = None
    for mp4 in mp4_files:
        if mp4.name not in history:
            txt = VIDEOS_DIR / f"{mp4.stem}.txt"
            if txt.exists():
                target_pair = (mp4, txt)
                break

    if not target_pair:
        print("[BILGI] Yuklenecek yeni video bulunamadi!")
        return None

    mp4_file, txt_file = target_pair
    meta = parse_txt_file(txt_file)

    print("=" * 65)
    print(f"🎬 AYNI VİDEO HER İKİ KANALA YÜKLENİYOR: {mp4_file.name}")
    print(f"📌 Başlık : {meta['title']}")
    print(f"🌐 Durum  : {privacy}")
    print("=" * 65)

    tag_str = " ".join(["#" + t for t in meta["tags"] if not t.startswith("#")])
    full_desc = f"{meta['description']}\n\n{tag_str}".strip()

    # 1. Kanala yukle (Film Magarasi)
    res1 = upload_and_report(
        token_file="token_channel1.json",
        channel_label="1. KANAL (Film Mağarası)",
        video_path=str(mp4_file),
        title=meta["title"],
        description=full_desc,
        privacy=privacy
    )

    # 2. Kanala yukle (Velvet Rain Jazz Music)
    res2 = upload_and_report(
        token_file="token_channel2.json",
        channel_label="2. KANAL (Velvet Rain Jazz Music)",
        video_path=str(mp4_file),
        title=meta["title"],
        description=full_desc,
        privacy=privacy
    )

    # Gecmise kaydet (Mukerrer yuklemeyi onle)
    history[mp4_file.name] = {
        "channel1": res1,
        "channel2": res2,
        "title": meta["title"]
    }
    save_history(history)

    print("\n" + "=" * 65)
    print("🎉 HARİKA! AYNI VİDEO HER İKİ KANALA DA BAŞARIYLA YAYINLANDI!")
    print(f"1. Kanal ({res1['channel_title']}): {res1['link']}")
    print(f"2. Kanal ({res2['channel_title']}): {res2['link']}")
    print("=" * 65)

    return history[mp4_file.name]

if __name__ == "__main__":
    publish_next_video_to_both(privacy="public")
