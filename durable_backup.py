"""Private Drive backup with content-addressed writes and download verification.

No media upload, publishing, permissions change, state overwrite or deletion.
"""
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
import zipfile
from pathlib import Path

from publication_operations import validate

FOLDER = 'Auto Video Publisher Recovery Backups'
MARKER = 'publisher-recovery-v1'
MAX_BYTES = 50 * 1024 * 1024
# Never serialize OAuth, API or private-key material into a recovery archive.
SENSITIVE_FIELD_PARTS = (
    'accesstoken', 'refreshtoken', 'clientsecret', 'privatekey',
    'apikey', 'password', 'authorization', 'credential',
    'secret', 'token', 'cookie', 'webhook',
)


def reject_credentials(value):
    """Fail closed on credential-shaped fields; preserve intact ledger data."""
    if isinstance(value, dict):
        for key, item in value.items():
            compact = ''.join(c for c in str(key).lower() if c.isalnum())
            if any(part in compact for part in SENSITIVE_FIELD_PARTS):
                raise ValueError('backup contains sensitive credential field')
            reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            reject_credentials(item)
    elif isinstance(value, str):
        if (value.startswith(('ghp_', 'github_pat_', 'ya29.', 'Bearer ', 'sk-'))
                or '-----BEGIN PRIVATE KEY-----' in value):
            raise ValueError('backup contains sensitive credential value')


def bundle(state, history):
    validate(state)
    reject_credentials(state)
    for line in history.decode('utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('invalid analytics history')
            reject_credentials(row)
    files = {'state.json': json.dumps(state, ensure_ascii=False).encode('utf-8'),
             'daily_video_views.jsonl': history}
    manifest = {'schema': 1, 'files': {name: {'sha256': hashlib.sha256(raw).hexdigest(),
                 'bytes': len(raw)} for name, raw in files.items()}}
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            # Fixed member timestamps make identical data produce identical ZIPs.
            archive.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), raw,
                             compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr(zipfile.ZipInfo('manifest.json', (2026, 1, 1, 0, 0, 0)),
                         json.dumps(manifest, sort_keys=True))
    data = out.getvalue()
    unpack(data)
    return data


def unpack(data):
    if len(data) > MAX_BYTES:
        raise ValueError('backup too large')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = ['state.json', 'daily_video_views.jsonl', 'manifest.json']
        if sorted(archive.namelist()) != sorted(names):
            raise ValueError('invalid backup members')
        if sum(i.file_size for i in archive.infolist()) > MAX_BYTES:
            raise ValueError('expanded backup too large')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema') != 1 or set(manifest.get('files', {})) != set(names[:-1]):
            raise ValueError('invalid manifest')
        files = {name: archive.read(name) for name in names[:-1]}
    for name, raw in files.items():
        proof = manifest['files'][name]
        if proof.get('bytes') != len(raw) or proof.get('sha256') != hashlib.sha256(raw).hexdigest():
            raise ValueError('backup integrity failure')
    state = json.loads(files['state.json'])
    validate(state)
    reject_credentials(state)
    for line in files['daily_video_views.jsonl'].decode('utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('invalid archived history')
            reject_credentials(row)
    return files


def restore_isolated(data, destination):
    files = unpack(data)
    destination = Path(destination)
    destination.mkdir()  # No overwrite or production-state mutation.
    for name, raw in files.items():
        (destination / name).write_bytes(raw)
    return destination


def list_files(drive, query):
    items, seen, token = [], set(), None
    for _ in range(100):
        page = drive.files().list(q=query, fields='nextPageToken,files(id,name,appProperties)',
                                  pageSize=1000, pageToken=token).execute()
        if not isinstance(page.get('files'), list):
            raise ValueError('invalid Drive listing')
        items.extend(page['files'])
        token = page.get('nextPageToken')
        if not token:
            return items
        if token in seen:
            raise ValueError('repeated Drive cursor')
        seen.add(token)
    raise ValueError('Drive listing incomplete')


def private_folder(drive):
    query = ("trashed=false and mimeType='application/vnd.google-apps.folder' and "
             "appProperties has { key='publisher_backup' and value='" + MARKER + "' }")
    matches = list_files(drive, query)
    if len(matches) > 1:
        raise ValueError('ambiguous backup folder')
    if matches:
        folder_id = matches[0]['id']
    else:
        folder_id = drive.files().create(body={'name': FOLDER,
            'mimeType': 'application/vnd.google-apps.folder',
            'appProperties': {'publisher_backup': MARKER}}, fields='id').execute()['id']
    # Never write a state bundle into a shared/public destination.
    permissions = drive.permissions().list(fileId=folder_id, fields='permissions(type,role)').execute()
    if any(p.get('type') != 'user' or p.get('role') != 'owner'
           for p in permissions.get('permissions', [])):
        raise ValueError('backup destination is shared')
    if not permissions.get('permissions'):
        raise ValueError('backup privacy not verified')
    return folder_id


def persist(drive, data, *, media_factory=None):
    unpack(data)
    digest = hashlib.sha256(data).hexdigest()
    folder_id = private_folder(drive)
    matches = list_files(drive, f"'{folder_id}' in parents and trashed=false and "
                         "appProperties has { key='sha256' and value='" + digest + "' }")
    if len(matches) > 1:
        raise ValueError('ambiguous backup files')
    if matches:
        file_id = matches[0]['id']
    else:
        quota = drive.about().get(fields='storageQuota').execute().get('storageQuota', {})
        if quota.get('limit') and int(quota['limit']) - int(quota.get('usage', 0)) < len(data) * 2 + 10_000_000:
            raise ValueError('insufficient free Drive storage')
        if media_factory is None:
            from googleapiclient.http import MediaIoBaseUpload
            media_factory = MediaIoBaseUpload
        file_id = drive.files().create(body={'name': f'publisher-recovery-{digest}.zip',
            'parents': [folder_id], 'appProperties': {'sha256': digest}},
            media_body=media_factory(io.BytesIO(data), mimetype='application/zip', resumable=False),
            fields='id').execute()['id']
    # Verify the real remote identity, content address, creation time and privacy
    # even when the digest matches a previously uploaded file.
    metadata = drive.files().get(
        fileId=file_id, fields='id,mimeType,parents,createdTime,appProperties').execute()
    if (not isinstance(metadata, dict) or metadata.get('id') != file_id
            or metadata.get('mimeType') != 'application/zip'
            or folder_id not in metadata.get('parents', [])
            or (metadata.get('appProperties') or {}).get('sha256') != digest):
        raise ValueError('remote backup metadata mismatch')
    file_created_at = metadata.get('createdTime')
    try:
        parsed_time = datetime.fromisoformat(file_created_at.replace('Z', '+00:00'))
        if parsed_time.tzinfo is None:
            raise ValueError('timezone required')
    except (AttributeError, ValueError, TypeError):
        raise ValueError('remote backup creation time missing') from None
    permissions = drive.permissions().list(
        fileId=file_id, fields='permissions(type,role)').execute()
    if (not isinstance(permissions, dict) or
            not isinstance(permissions.get('permissions'), list) or
            not permissions['permissions'] or
            any(p.get('type') != 'user' or p.get('role') != 'owner'
                for p in permissions['permissions'])):
        raise ValueError('remote backup file is shared or privacy unverified')
    # Always download the actual remote file. Metadata alone is not acceptance.
    downloaded = drive.files().get_media(fileId=file_id).execute()
    if not isinstance(downloaded, bytes) or hashlib.sha256(downloaded).hexdigest() != digest:
        raise ValueError('remote backup mismatch')
    with tempfile.TemporaryDirectory() as temp:
        restored = restore_isolated(downloaded, Path(temp) / 'restored')
        if json.loads((restored / 'state.json').read_bytes()) != json.loads(unpack(data)['state.json']):
            raise ValueError('restore mismatch')
    return dict(status='verified', file_id=file_id, sha256=digest,
                bytes=len(data), file_created_at=file_created_at,
                verified_at=datetime.now(timezone.utc).isoformat(),
                downloaded=True, isolated_restore_verified=True)


def main():
    root = Path('link-runtime')
    root.mkdir(exist_ok=True)
    receipt = {'status': 'failed'}
    try:
        if not os.getenv('DRIVE_TOKEN_JSON', '').strip():
            receipt['reason'] = 'missing_drive_credentials'
            raise RuntimeError('missing credentials')
        from publication_github_progress import restore_publication_state
        from analytics_github_history import restore_history
        from cloud_omnichannel_publisher import get_drive_client
        state = restore_publication_state()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'daily_video_views.jsonl'
            history = restore_history(path)
            if history['status'] != 'restored':
                receipt['reason'] = 'analytics_history_unavailable'
                raise RuntimeError('history unavailable')
            data = bundle(state, path.read_bytes())
        receipt = persist(get_drive_client(), data)
    except Exception as exc:
        receipt['error_type'] = type(exc).__name__
        receipt.setdefault('reason', 'backup_not_verified')
    (root / 'durable-backup-receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))
    if receipt['status'] != 'verified':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
