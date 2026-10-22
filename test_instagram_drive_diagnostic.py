import os
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
import yaml

import instagram_drive_diagnostic as diagnostic


class InstagramDriveDiagnosticTests(unittest.TestCase):
    def test_wrong_event_or_ref_stops_before_drive_auth(self):
        for event, ref in (
            ("schedule", diagnostic.ALLOWED_REF),
            ("workflow_dispatch", "refs/heads/master"),
        ):
            with self.subTest(event=event, ref=ref), patch.dict(
                os.environ,
                {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref},
                clear=True,
            ), patch.object(diagnostic, "get_drive_client") as get_drive:
                with self.assertRaises(SystemExit):
                    diagnostic.main()
                get_drive.assert_not_called()

    def test_download_refuses_a_file_outside_gonle_folder(self):
        drive = Mock()
        drive.files.return_value.get.return_value.execute.return_value = {
            "name": "private.mp4",
            "parents": ["different-folder"],
        }
        with self.assertRaisesRegex(ValueError, "Gönle Drive klasöründe değil"):
            diagnostic._download_mp4(drive, "gonle-folder", "id", Path("unused.mp4"))
        drive.files.return_value.get_media.assert_not_called()

    def test_selects_only_known_failed_slot_and_optional_successful_comparison(self):
        files = [
            {"id": "unrelated", "name": "unrelated.mp4", "appProperties": {}},
            {
                "id": "failed",
                "name": "private-name.mp4",
                "appProperties": {"claimed_route_slot": diagnostic.KNOWN_FAILED_SLOT},
            },
            {
                "id": "success",
                "name": "another-private-name.mp4",
                "appProperties": {"done_ig_slot": "previous-gonle-slot"},
            },
        ]
        self.assertEqual(diagnostic.select_diagnostic_files(files), ("failed", "success"))

    def test_diagnostic_job_is_ref_locked_and_publisher_skips_diagnostic(self):
        path = Path(__file__).parent / ".github" / "workflows" / "omnichannel_schedule.yml"
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        diagnostic_job = jobs["instagram-video-diagnostic"]
        publisher_job = jobs["omnichannel-upload"]
        condition = diagnostic_job["if"]
        self.assertIn("workflow_dispatch", condition)
        self.assertIn(diagnostic.ALLOWED_REF, condition)
        self.assertIn("inputs.diagnostic_only == true", condition)
        publisher_condition = publisher_job["if"]
        self.assertIn("inputs.diagnostic_only != true", publisher_condition)
        self.assertIn("github.event_name != 'workflow_dispatch'", publisher_condition)
        self.assertIn("github.ref == 'refs/heads/master'", publisher_condition)
        diagnostic_env = next(
            step["env"]
            for step in diagnostic_job["steps"]
            if step.get("run") == "python instagram_drive_diagnostic.py"
        )
        self.assertEqual(
            set(diagnostic_env),
            {
                "DRIVE_TOKEN_JSON",
                "GONLE_DUSEN_DRIVE_FOLDER_ID",
                "FILM_DRIVE_FOLDER_ID",
                "TOKEN_FILM_YOUTUBE_JSON",
                "DIAGNOSTIC_FAILED_FILE_ID",
                "DIAGNOSTIC_COMPARISON_FILE_ID",
            },
        )

    def test_diagnostic_script_contains_no_drive_mutation_or_publish_call(self):
        source = Path(diagnostic.__file__).read_text(encoding="utf-8")
        self.assertNotIn("files().update", source)
        self.assertNotIn("media_publish", source)
        self.assertNotIn("upload_instagram", source)


if __name__ == "__main__":
    unittest.main()
