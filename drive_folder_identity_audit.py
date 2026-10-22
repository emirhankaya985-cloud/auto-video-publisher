"""Read-only Drive folder identity audit; never publishes or mutates Drive."""
import json, os, sys
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

def main():
    token = os.environ.get("DRIVE_TOKEN_JSON")
    ids = [x.strip() for x in os.environ.get("DRIVE_FOLDER_IDS", "").split(",") if x.strip()]
    if not token or not ids:
        raise SystemExit("DRIVE_TOKEN_JSON and DRIVE_FOLDER_IDS are required")
    data = json.loads(token)
    creds = Credentials.from_authorized_user_info(data)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    for folder_id in ids:
        folder = drive.files().get(fileId=folder_id, fields="id,name,mimeType,trashed,parents").execute()
        print(json.dumps({"folder": folder}, ensure_ascii=False, sort_keys=True))
        q = f"'{folder_id}' in parents and trashed = false and mimeType = 'video/mp4'"
        page = None
        while True:
            resp = drive.files().list(q=q, spaces="drive", fields="nextPageToken,files(id,name,parents,md5Checksum,size,videoMediaMetadata)", pageToken=page, pageSize=1000).execute()
            for item in resp.get("files", []):
                print(json.dumps({"mp4": item}, ensure_ascii=False, sort_keys=True))
            page = resp.get("nextPageToken")
            if not page:
                break

if __name__ == "__main__":
    main()
