"""Durable analytics snapshot storage in a dedicated Google Drive folder."""
import io
import json
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


FOLDER_NAME = "Auto Video Publisher Analytics"
HISTORY_NAME = "daily_video_views.jsonl"
CSV_NAME = "daily_video_views.csv"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _list_all(drive, query, fields):
    items = []
    page_token = None
    while True:
        result = drive.files().list(
            q=query, pageSize=1000, pageToken=page_token,
            fields=f"nextPageToken,files({fields})", includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        items.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return items


def get_or_create_archive_folder(drive):
    escaped = FOLDER_NAME.replace("'", "\\'")
    folders = _list_all(
        drive, f"name='{escaped}' and mimeType='{FOLDER_MIME}' and trashed=false", "id,name",
    )
    if folders:
        return folders[0]["id"]
    created = drive.files().create(
        body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME},
        fields="id", supportsAllDrives=True,
    ).execute()
    return created["id"]


def download_history(drive, folder_id, target_path):
    matches = _list_all(
        drive, f"'{folder_id}' in parents and name='{HISTORY_NAME}' and trashed=false", "id,modifiedTime",
    )
    if not matches:
        return None
    item = max(matches, key=lambda x: x.get("modifiedTime", ""))
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, drive.files().get_media(fileId=item["id"]), chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    Path(target_path).write_bytes(buffer.getvalue())
    return item["id"]


def upload_file(drive, folder_id, name, path, mime_type):
    matches = _list_all(
        drive, f"'{folder_id}' in parents and name='{name}' and trashed=false", "id,modifiedTime",
    )
    with open(path, "rb") as source:
        media = MediaIoBaseUpload(source, mimetype=mime_type, resumable=True)
        if matches:
            item = max(matches, key=lambda x: x.get("modifiedTime", ""))
            return drive.files().update(
                fileId=item["id"], media_body=media, fields="id", supportsAllDrives=True,
            ).execute()
        return drive.files().create(
            body={"name": name, "parents": [folder_id]}, media_body=media,
            fields="id", supportsAllDrives=True,
        ).execute()


def save_history_and_csv(drive, folder_id, jsonl_path, csv_path):
    upload_file(drive, folder_id, HISTORY_NAME, jsonl_path, "application/x-ndjson")
    upload_file(drive, folder_id, CSV_NAME, csv_path, "text/csv")
