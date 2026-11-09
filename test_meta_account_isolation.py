"""Account fault isolation: zero Meta writes when any account is held."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from meta_page_token_health import archive_partial_preflight, verified_pages, main
from test_public_link_runtime import runtime


class MetaAccountIsolationTests(unittest.TestCase):
    def test_film_failure_keeps_other_verified_pages(self):
        report = {"status": "attention_needed", "accounts": [
            {"page_name": "Film Mağarası", "status": "blocked"},
            {"page_name": "ToonZone", "status": "identity_verified"},
            {"page_name": "Daily Laugh Lab", "status": "identity_verified"}]}
        self.assertEqual(verified_pages(report), ["Daily Laugh Lab", "ToonZone"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meta-preflight.json"
            with patch.dict(os.environ, {"META_PREFLIGHT_PARTIAL_OK": "true",
                                         "META_PREFLIGHT_REPORT_PATH": str(path)}):
                self.assertTrue(archive_partial_preflight(report))
                self.assertEqual(runtime.preflight_verified_pages(),
                                 {"ToonZone", "Daily Laugh Lab"})
            contents = path.read_text()
            self.assertNotIn("page_token", contents)
            self.assertNotIn("Film Mağarası", contents)

    def test_duplicate_page_identity_never_becomes_eligible(self):
        result = {"status": "attention_needed", "accounts": [
            {"page_name": "ToonZone", "status": "identity_verified"},
            {"page_name": "ToonZone", "status": "blocked", "reason": "duplicate_configuration"}]}
        self.assertEqual(verified_pages(result), [])

    def test_none_healthy_fails_closed_without_writing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meta-preflight.json"
            result = {"status": "attention_needed", "accounts": [
                {"page_name": "Film Mağarası", "status": "blocked"}]}
            with patch.dict(os.environ, {"META_PREFLIGHT_PARTIAL_OK": "true",
                                         "META_PREFLIGHT_REPORT_PATH": str(path)}), \
                    patch("meta_auth_loader.load_meta_auth", return_value={"pages": []}), \
                    patch("meta_page_token_health.audit", return_value=result), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            self.assertFalse(path.exists())

    def test_absent_or_tampered_allowlist_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            with patch.dict(os.environ, {"META_PREFLIGHT_PARTIAL_OK": "true",
                                         "META_PREFLIGHT_REPORT_PATH": str(path)}):
                with self.assertRaises(RuntimeError):
                    runtime.preflight_verified_pages()
                for data in ({"schema": 1, "status": "partial_identity_verified",
                              "verified_pages": ["unrecognized"]},
                             {"schema": 1, "status": "identity_verified",
                              "verified_pages": []}):
                    path.write_text(json.dumps(data))
                    with self.assertRaises(RuntimeError):
                        runtime.preflight_verified_pages()

    def test_legacy_mode_does_not_require_preflight_evidence(self):
        with patch.dict(os.environ, {"META_PREFLIGHT_PARTIAL_OK": "false"}):
            self.assertIsNone(runtime.preflight_verified_pages())


if __name__ == "__main__":
    unittest.main()
