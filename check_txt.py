import io
from drive_handler import get_drive_client
from googleapiclient.http import MediaIoBaseDownload

service = get_drive_client()
folder_id = '11zbrunHoiTZyJ8JDsj99ascO66mmCj-M'

query = f"'{folder_id}' in parents and name contains '.txt' and trashed = false"
res = service.files().list(q=query, fields='files(id, name)', pageSize=5).execute()
files = res.get('files', [])

if files:
    f = files[0]
    print(f"Dosya: {f['name']}")
    req = service.files().get_media(fileId=f['id'])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    downloader.next_chunk()
    content = fh.getvalue().decode('utf-8', errors='ignore')
    print("--- ICERIK ---")
    print(content[:500])
