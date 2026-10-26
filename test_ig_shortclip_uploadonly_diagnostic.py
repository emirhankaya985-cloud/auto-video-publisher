"""No external Meta/Drive writes: verify source, account, rights and no-publish."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ig_shortclip_uploadonly_diagnostic as diag

APPROVED = {
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_REPOSITORY": "emirhankaya985-cloud/auto-video-publisher",
    "IG_SHORTCLIP_UPLOADONLY_APPROVED": "true",
}

def accounts():
    return {"pages": [
        {"page_id": pid, "instagram_id": ig, "page_token": "PRIVATE-TOKEN"}
        for _, _, pid, ig in diag.SOURCES
    ]}


class IGDiagnosticSafetyTests(unittest.TestCase):
    def test_unpublished_diagnostic_cannot_be_starved_by_publisher_queue(self):
        from pathlib import Path
        yaml_text = Path(".github/workflows/ig_shortclip_uploadonly.yml").read_text()
        self.assertIn("group: ig-shortclip-uploadonly-no-publish", yaml_text)
        self.assertNotIn("group: public-drive-recovery", yaml_text)
        self.assertIn("cancel-in-progress: false", yaml_text)
        self.assertIn("if: github.event_name == 'push'", yaml_text)
        source = Path(diag.__file__).read_text()
        self.assertIn("publish=False", source)
        self.assertNotIn("media_publish(", source)

    def test_gate_rejects_unapproved_event_and_repo(self):
        for override in ({"GITHUB_EVENT_NAME": "pull_request"},
                         {"GITHUB_REF": "refs/heads/random"},
                         {"GITHUB_REPOSITORY": "third-party/repo"},
                         {"IG_SHORTCLIP_UPLOADONLY_APPROVED": "false"}):
            with self.subTest(override=override), patch.dict(
                    os.environ, dict(APPROVED, **override), clear=True):
                with self.assertRaisesRegex(RuntimeError, "requires approved|repo identity"):
                    diag.require_explicit_one_shot()

    def test_only_exact_source_name_is_accepted(self):
        name = diag.SOURCES[0][1]
        self.assertEqual(diag.selected_video({name: {"name": name, "id": "real-id"}}, name)["id"], "real-id")
        with self.assertRaisesRegex(RuntimeError, "missing or ambiguous"):
            diag.selected_video({"unexpected.mp4": {"name": "unexpected.mp4", "id": "x"}}, name)

    def test_upload_wrapper_always_sets_publish_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "actual.mp4"
            source.write_bytes(b"source")
            def short_clip(_src, dst, seconds):
                self.assertEqual(seconds, 15)
                dst.write_bytes(b"video-only-unpublished")
                return dst
            upload = Mock(return_value={"status": "FINISHED", "published": False,
                                        "container_id": "17903621700599675"})
            result = diag.upload_only_trial(accounts()["pages"][0], source,
                                             diag.SOURCES[0][1], root,
                                             diagnostic_clip=short_clip, upload=upload)
            self.assertEqual(result["status"], "FINISHED_NOT_PUBLISHED")
            self.assertIsNone(result["post_id"])
            self.assertIs(upload.call_args.kwargs["publish"], False)
            self.assertIs(upload.call_args.kwargs["append_store_link"], False)

    def test_wrapper_cannot_accept_published_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "clip.mp4"
            media.write_bytes(b"unpublished")
            for state in ({"status": "FINISHED", "published": True, "container_id": "123"},
                          {"status": "ERROR", "published": False, "container_id": "123"}):
                with self.subTest(state=state), self.assertRaises(RuntimeError):
                    diag.upload_only_trial(accounts()["pages"][0], media, "clip.mp4", root,
                                            diagnostic_clip=lambda *args: media,
                                            upload=Mock(return_value=state))

    def test_route_rights_denied_before_inventory_and_upload(self):
        with patch.dict(os.environ, APPROVED, clear=True):
            inv = Mock()
            trial = Mock()
            with self.assertRaisesRegex(RuntimeError, "rights/route"):
                diag.execute(inventory=inv, download=Mock(), trial=trial,
                             paused=lambda route: route == "toonzone", loader=accounts)
            inv.assert_not_called()
            trial.assert_not_called()

    def test_ig_identity_denied_before_inventory_or_post(self):
        with patch.dict(os.environ, APPROVED, clear=True):
            inv, trial = Mock(), Mock()
            bad = accounts()
            bad["pages"][1]["instagram_id"] = "another-ig-id"
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                diag.execute(inventory=inv, download=Mock(), trial=trial,
                             paused=lambda route: False, loader=lambda: bad)
            inv.assert_not_called()
            trial.assert_not_called()

    def test_two_exact_clips_do_not_touch_or_publish_existing_intents(self):
        def inventory(folder):
            return {name: {"name": name, "id": name + "-drive-id"}
                    for _, name, _, _ in diag.SOURCES}
        def download(file_id, path):
            path.write_bytes(b"original mp4")
            return path
        def trial(page, source, name, root):
            self.assertEqual(source.read_bytes(), b"original mp4")
            self.assertTrue(name in [s[1] for s in diag.SOURCES])
            return {"status": "FINISHED_NOT_PUBLISHED", "container_id": "1234567"}
        with patch.dict(os.environ, APPROVED, clear=True):
            report = diag.execute(inventory=inventory, download=download,
                                  paused=lambda route: False, loader=accounts, trial=trial)
        self.assertEqual(len(report["files"]), 2)
        self.assertTrue(all(row["published"] is False for row in report["files"]))
        self.assertEqual(report["media_publish_calls"], 0)
        self.assertIs(report["existing_intents_changed"], False)
        self.assertNotIn("PRIVATE-TOKEN", str(report))

    def test_meta_exception_is_sanitized_without_provider_body(self):
        def inventory(folder):
            return {name: {"name": name, "id": "id"} for _, name, _, _ in diag.SOURCES}
        def download(file_id, path):
            path.write_bytes(b"source")
            return path
        def failing_trial(page, source, name, temp):
            raise RuntimeError("PRIVATE-TOKEN: raw Meta error includes URL")
        with patch.dict(os.environ, APPROVED, clear=True):
            report = diag.execute(inventory=inventory, download=download,
                                  paused=lambda route: False, loader=accounts,
                                  trial=failing_trial)
        self.assertEqual(len(report["files"]), 2)
        self.assertTrue(all(row["status"] == "FAILED" for row in report["files"]))
        self.assertNotIn("PRIVATE-TOKEN", str(report))
        self.assertNotIn("raw Meta", str(report))


if __name__ == "__main__":
    unittest.main()
