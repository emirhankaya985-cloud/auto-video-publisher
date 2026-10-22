import io
from drive_handler import get_drive_client
from googleapiclient.http import MediaIoBaseDownload

service = get_drive_client()
res = service.files().list(q="'11zbrunHoiTZyJ8JDsj99ascO66mmCj-M' in parents and name = '47.txt'", fields='files(id, name)').execute()
f = res['files'][0]
req = service.files().get_media(fileId=f['id'])
fh = io.BytesIO()
downloader = MediaIoBaseDownload(fh, req)
downloader.next_chunk()
content = fh.getvalue().decode('utf-8', errors='ignore')
print("47.txt ICERIK:\n", content)
