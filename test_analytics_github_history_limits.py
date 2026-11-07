"""Regression tests for compressed and expanded analytics artifact limits."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import analytics_github_history as history


class Response:
    def __init__(self, status_code, *, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


class HistoryArchiveLimitTests(unittest.TestCase):
    @staticmethod
    def _zip(raw):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(history.HISTORY_FILE, raw)
        return data.getvalue()

    @staticmethod
    def _read_with_archive(archive):
        def get(url, **kwargs):
            if url.endswith("/actions/artifacts"):
                return Response(200, payload={"artifacts": [{
                    "id": 123, "name": history.ARTIFACT_NAME,
                    "expired": False, "created_at": "2026-11-07T20:00:00Z",
                    "workflow_run": {"id": 77, "head_branch": "main"}
                }]})
            return Response(200, content=archive)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / history.HISTORY_FILE
            result = history.restore_history(target, token="test", get=get)
            return result, target.read_bytes()

    def test_expanded_analytics_history_over_20mib_is_restored(self):
        raw = json.dumps({"day": "2026-11-07", "extra": "x" * (21 * 1024 * 1024)}).encode() + b"\n"
        outcome, restored = self._read_with_archive(self._zip(raw))
        self.assertEqual(outcome["status"], "restored")
        self.assertEqual(restored, raw)

    def test_long_lived_history_over_64mib_is_restored(self):
        raw = json.dumps({"day": "2026-11-07", "extra": "x" * (65 * 1024 * 1024)}).encode() + b"\n"
        outcome, restored = self._read_with_archive(self._zip(raw))
        self.assertEqual(outcome["status"], "restored")
        self.assertEqual(restored, raw)

    def test_expanded_archive_over_configured_limit_is_rejected(self):
        from unittest.mock import patch
        raw = json.dumps({"day": "2026-11-07", "extra": "x" * 2048}).encode() + b"\n"
        with patch.object(history, "MAX_ARCHIVE_BYTES", 1024):
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                self._read_with_archive(self._zip(raw))


if __name__ == "__main__":
    unittest.main()
