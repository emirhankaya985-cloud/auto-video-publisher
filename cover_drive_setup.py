"""Audit or create channel-scoped cover folders without publishing media."""

import argparse
import hashlib
import os
from pathlib import Path

from cloud_omnichannel_publisher import SCOPES_YOUTUBE, get_drive_client
from googleapiclient.http import MediaFileUpload


COVER_ROOT_ID = "1iocIhLVvvRVOsISsSzrA_uRORv-7tBHh"
CHANNELS = (
    "Tarladaki Fasulye",
    "Beyinsiz Penguen",
    "Gönle Düşen",
    "Daily Laugh Lab",
    "Film",
    "Türkçe Çizgi Film",
    "OddFrames",
)
FOLDER_MIME = "application/vnd.google-apps.folder"
UPLOAD_MAP = {
    "tarladaki.jpg": "Tarladaki Fasulye",
    "penguen.jpg": "Beyinsiz Penguen",
    "gonle.jpg": "Gönle Düşen",
    "daily.jpg": "Daily Laugh Lab",
    "cizgifilm.jpg": "Türkçe Çizgi Film",
    "oddframes.jpg": "OddFrames",
}


def list_children(drive, root_id):
    result = drive.files().list(
        q=f"'{root_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,parents)",
        pageSize=1000,
    ).execute()
    return result.get("files", [])


def audit_or_create(drive, root_id, create=False):
    root = drive.files().get(fileId=root_id, fields="id,name,mimeType").execute()
    if root.get("mimeType") != FOLDER_MIME:
        raise RuntimeError("COVER_DRIVE_FOLDER_ID bir Drive klasörü değil")
    children = list_children(drive, root_id)
    folders = {}
    for item in children:
        if item.get("mimeType") == FOLDER_MIME and item.get("name") in CHANNELS:
            if item["name"] in folders:
                raise RuntimeError(f"Aynı adlı birden fazla kapak alt klasörü var: {item['name']}")
            folders[item["name"]] = item["id"]
    if create:
        for name in CHANNELS:
            if name not in folders:
                created = drive.files().create(
                    body={"name": name, "mimeType": FOLDER_MIME, "parents": [root_id]},
                    fields="id,name",
                ).execute()
                folders[name] = created["id"]
    return root, folders, children


def audit_images(drive, folders):
    results = {}
    for channel, folder_id in folders.items():
        items = list_children(drive, folder_id)
        images = [item for item in items if item.get("mimeType") in {"image/jpeg", "image/png"}]
        by_stem = {}
        for item in images:
            stem = item.get("name", "").rsplit(".", 1)[0]
            by_stem.setdefault(stem, []).append(item)
        duplicates = sorted(stem for stem, matches in by_stem.items() if len(matches) > 1)
        results[channel] = {"images": len(images), "duplicates": duplicates}
    return results


def upload_covers(drive, folders, upload_dir):
    results = []
    for filename, channel in UPLOAD_MAP.items():
        path = Path(upload_dir, filename)
        if not path.is_file():
            raise RuntimeError(f"Yüklenecek kapak eksik: {filename}")
        folder_id = folders.get(channel)
        if not folder_id:
            raise RuntimeError(f"Kapak alt klasörü eksik: {channel}")
        existing = [item for item in list_children(drive, folder_id) if item.get("name") == filename]
        if len(existing) > 1:
            raise RuntimeError(f"Aynı adlı birden fazla Drive kapağı var: {channel}/{filename}")
        local_md5 = hashlib.md5(path.read_bytes()).hexdigest()
        if existing:
            remote = drive.files().get(fileId=existing[0]["id"], fields="id,name,md5Checksum").execute()
            if remote.get("md5Checksum") == local_md5:
                results.append((channel, filename, "zaten_mevcut", remote["id"]))
                continue
            raise RuntimeError(f"Aynı isimde farklı içerik var; üzerine yazılmadı: {channel}/{filename}")
        created = drive.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=MediaFileUpload(str(path), mimetype="image/jpeg", resumable=False),
            fields="id,name,md5Checksum",
        ).execute()
        results.append((channel, filename, "yüklendi", created["id"]))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-subfolders", action="store_true")
    parser.add_argument("--upload-dir")
    args = parser.parse_args()
    configured = os.getenv("COVER_DRIVE_FOLDER_ID", COVER_ROOT_ID).strip()
    if configured != COVER_ROOT_ID:
        raise RuntimeError("Beklenmeyen kapak kök klasörü; işlem durduruldu")
    drive = get_drive_client()
    root, folders, children = audit_or_create(drive, configured, args.create_subfolders)
    if args.upload_dir:
        for channel, filename, status, file_id in upload_covers(drive, folders, args.upload_dir):
            print(f"KAPAK_YÜKLEME {channel}: {filename} | {status} | {file_id}")
    audits = audit_images(drive, folders)
    images = [item for item in children if item.get("mimeType") in {"image/jpeg", "image/png"}]
    print(f"Kapak kökü doğrulandı: {root.get('name')} | alt_klasör={len(folders)} | kök_görsel={len(images)}")
    for name in CHANNELS:
        print(f"KAPAK_ALT_KLASÖR {name}: {folders.get(name, 'EKSİK')}")
        if name in audits:
            duplicate_text = ",".join(audits[name]["duplicates"]) or "yok"
            print(f"KAPAK_DENETİM {name}: görsel={audits[name]['images']} çakışan_ad={duplicate_text}")
    print(f"YouTube OAuth kapsamı hazır: {'https://www.googleapis.com/auth/youtube.upload' in SCOPES_YOUTUBE}")
    print("COVER_FEATURE_ENABLED=false; platform kapak uygulaması veya video yayını yapılmadı.")


if __name__ == "__main__":
    main()
