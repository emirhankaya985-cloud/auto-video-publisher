import unittest

from cover_drive_setup import CHANNELS, audit_or_create, upload_covers


class _Request:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class _Files:
    def __init__(self): self.created = []
    def get(self, **kwargs): return _Request({"id": kwargs["fileId"], "name": "Video Kapakları", "mimeType": "application/vnd.google-apps.folder"})
    def list(self, **kwargs): return _Request({"files": []})
    def create(self, body, fields, media_body=None):
        self.created.append(body)
        return _Request({"id": f"id-{len(self.created)}", "name": body["name"]})


class _Drive:
    def __init__(self): self.api = _Files()
    def files(self): return self.api


class CoverDriveSetupTests(unittest.TestCase):
    def test_read_only_does_not_create(self):
        drive = _Drive()
        _, folders, _ = audit_or_create(drive, "root", create=False)
        self.assertEqual(folders, {})
        self.assertEqual(drive.api.created, [])

    def test_create_adds_each_channel_once(self):
        drive = _Drive()
        _, folders, _ = audit_or_create(drive, "root", create=True)
        self.assertEqual(set(folders), set(CHANNELS))
        self.assertEqual(len(drive.api.created), len(CHANNELS))

    def test_upload_requires_all_known_files(self):
        import tempfile
        drive = _Drive()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "Yüklenecek kapak eksik"):
                upload_covers(drive, {name: f"id-{name}" for name in CHANNELS}, folder)


if __name__ == "__main__": unittest.main()
