import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from durable_backup import bundle, unpack, restore_isolated, persist


class Response:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeDrive:
    def __init__(self):
        self.folder = None
        self.blobs = {}
        self.created = 0
        self.permission_rows = [{'type': 'user', 'role': 'owner'}]
        self.quota = {'limit': '1000000000', 'usage': '0'}
        self.corrupt = False

    def files(self):
        return self

    def permissions(self):
        return SimpleNamespace(list=lambda **kwargs: Response({'permissions': self.permission_rows}))

    def about(self):
        return SimpleNamespace(get=lambda **kwargs: Response({'storageQuota': self.quota}))

    def list(self, q, **kwargs):
        if 'mimeType=' in q:
            return Response({'files': [{'id': self.folder}] if self.folder else []})
        return Response({'files': [{'id': key} for key, (digest, raw) in self.blobs.items() if digest in q]})

    def create(self, body, media_body=None, **kwargs):
        if media_body is None:
            self.folder = 'private-folder'
            return Response({'id': self.folder})
        self.created += 1
        key = str(self.created)
        self.blobs[key] = (body['appProperties']['sha256'], media_body.read())
        return Response({'id': key})

    def get_media(self, fileId):
        return Response(b'corrupt' if self.corrupt else self.blobs[fileId][1])


class DurableBackupTests(unittest.TestCase):
    def data(self):
        return bundle({'schema': 1, 'entries': {'held': {'status': 'uncertain'}},
                       'youtube_entries': {'x': {'status': 'accepted', 'post_id': 'saved'}},
                       'future': {'preserved': True}}, b'{"metric":"views","value":42}\n')

    def test_complete_restore_is_lossless_and_refuses_existing_directory(self):
        data = self.data()
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'new'
            restore_isolated(data, dest)
            self.assertEqual(json.loads((dest / 'state.json').read_bytes())['future'], {'preserved': True})
            self.assertEqual((dest / 'daily_video_views.jsonl').read_bytes(), b'{"metric":"views","value":42}\n')
            with self.assertRaises(FileExistsError):
                restore_isolated(data, dest)

    def test_identical_payload_is_deterministic_and_uploaded_once(self):
        drive = FakeDrive()
        data = self.data()
        self.assertEqual(data, self.data())
        for _ in range(2):
            receipt = persist(drive, data, media_factory=lambda source, **k: source)
            self.assertTrue(receipt['isolated_restore_verified'])
        self.assertEqual(drive.created, 1)

    def test_download_corruption_never_reports_success(self):
        drive = FakeDrive()
        drive.corrupt = True
        with self.assertRaisesRegex(ValueError, 'remote backup mismatch'):
            persist(drive, self.data(), media_factory=lambda source, **k: source)

    def test_shared_destination_and_low_quota_never_upload(self):
        drive = FakeDrive()
        drive.permission_rows.append({'type': 'anyone', 'role': 'reader'})
        with self.assertRaisesRegex(ValueError, 'shared'):
            persist(drive, self.data())
        self.assertEqual(drive.created, 0)
        drive = FakeDrive()
        drive.quota = {'limit': '100', 'usage': '90'}
        with self.assertRaisesRegex(ValueError, 'storage'):
            persist(drive, self.data())
        self.assertEqual(drive.created, 0)

    def test_modified_member_and_unexpected_paths_are_rejected(self):
        source = zipfile.ZipFile(io.BytesIO(self.data()))
        for extra in (False, True):
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w') as target:
                for name in source.namelist():
                    target.writestr(name, source.read(name) if extra else b'{}')
                if extra:
                    target.writestr('../escape', b'data')
            with self.assertRaises(ValueError):
                unpack(out.getvalue())

    def test_live_acceptance_only_calls_audit_not_publish(self):
        import ast
        tree = ast.parse(Path(__file__).with_name('publication_live_acceptance.py').read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        for call in calls:
            if isinstance(call.func, ast.Attribute):
                self.assertNotIn(call.func.attr, ['publish', 'upload_video', 'upload_facebook_reel', 'upload_instagram_reel'])
                if call.func.attr == 'plan':
                    self.assertTrue(any(k.arg == 'audit' and k.value.value is True for k in call.keywords))


if __name__ == '__main__':
    unittest.main()
