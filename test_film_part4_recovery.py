"""Part 4's audited partial-success recovery must never resend Facebook."""
import os
import unittest
from unittest.mock import Mock, patch

import scheduled_multi_publisher as publisher
from scheduled_multi_publisher import (
    CLAIM_SLOT, FAILED_SLOT, FILM_DONE_KEY, FILM_USED,
    FILM_PART4_IG_RECOVERY_CLAIM, FILM_PART4_IG_RECOVERY_FILE_ID,
    FILM_PART4_IG_RECOVERY_STEM, FILM_PART4_FB_RESULT_IDS,
    PLATFORM_FAILURE_KEYS, PLATFORM_FAILURE_SLOT_KEYS, PLATFORM_INTENT_KEYS,
    PLATFORM_RESULT_KEYS, PLATFORM_SLOT_KEYS, execute_platform_jobs,
    verify_film_part4_ig_only_recovery,
)


def audited_part4():
    return {
        "id": FILM_PART4_IG_RECOVERY_FILE_ID,
        "name": FILM_PART4_IG_RECOVERY_STEM + ".mp4",
        "appProperties": {
            CLAIM_SLOT: FILM_PART4_IG_RECOVERY_CLAIM,
            FAILED_SLOT: FILM_PART4_IG_RECOVERY_CLAIM,
            PLATFORM_SLOT_KEYS["fb_film_1"]: FILM_PART4_IG_RECOVERY_CLAIM,
            PLATFORM_SLOT_KEYS["fb_film_2"]: FILM_PART4_IG_RECOVERY_CLAIM,
            PLATFORM_RESULT_KEYS["fb_film_1"]: FILM_PART4_FB_RESULT_IDS[0],
            PLATFORM_RESULT_KEYS["fb_film_2"]: FILM_PART4_FB_RESULT_IDS[1],
            PLATFORM_FAILURE_SLOT_KEYS["ig"]: FILM_PART4_IG_RECOVERY_CLAIM,
            PLATFORM_FAILURE_KEYS["ig"]: "3",
        },
    }


class FilmPart4RecoveryTests(unittest.TestCase):
    def setUp(self):
        publisher._LAST_PLATFORM_PUBLISH_AT.clear()

    def tearDown(self):
        publisher._LAST_PLATFORM_PUBLISH_AT.clear()

    def test_exact_readonly_audited_partial_success_is_eligible(self):
        self.assertTrue(verify_film_part4_ig_only_recovery(audited_part4()))

    def test_wrong_file_claim_facebook_evidence_or_existing_ig_state_blocks(self):
        for key, value in (
            ("id", "wrong-id"),
            ("name", "Yoksul_1986_Part_3.mp4"),
        ):
            video = audited_part4()
            video[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part4_ig_only_recovery(video)

        for key in (
            CLAIM_SLOT, FAILED_SLOT, PLATFORM_SLOT_KEYS["fb_film_1"],
            PLATFORM_SLOT_KEYS["fb_film_2"], PLATFORM_RESULT_KEYS["fb_film_1"],
            PLATFORM_RESULT_KEYS["fb_film_2"], PLATFORM_FAILURE_KEYS["ig"],
            PLATFORM_FAILURE_SLOT_KEYS["ig"],
        ):
            video = audited_part4()
            video["appProperties"][key] = "conflicting-evidence"
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part4_ig_only_recovery(video)

        for key in (
            FILM_USED, FILM_DONE_KEY, PLATFORM_SLOT_KEYS["ig"],
            PLATFORM_RESULT_KEYS["ig"], PLATFORM_INTENT_KEYS["ig"],
            "published_ig", "film_part4_ig_recovery_used",
        ):
            video = audited_part4()
            video["appProperties"][key] = "1" if key in (FILM_USED, FILM_DONE_KEY) else "already-present"
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part4_ig_only_recovery(video)

    def test_one_shot_manual_recovery_runs_ig_only_and_preserves_fb_ids(self):
        video = audited_part4()
        props = video["appProperties"]
        slot = "manual-2026-10-20-0900-film"
        props[CLAIM_SLOT] = slot
        props["film_part4_ig_recovery_used"] = "1"
        props["film_part4_ig_recovery_from"] = FILM_PART4_IG_RECOVERY_CLAIM
        drive = Mock()
        ig_job, fb1_job, fb2_job = Mock(return_value="ig-post-id"), Mock(), Mock()
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "instagram",
            "FORCE_STEM": FILM_PART4_IG_RECOVERY_STEM,
            "FILM_CLAIM_TO_CLEAR": FILM_PART4_IG_RECOVERY_CLAIM,
            "MIN_PLATFORM_INTERVAL_SECONDS": "0",
        }, clear=True):
            results, errors = execute_platform_jobs(
                drive, video, slot, ["ig"],
                {"ig": ig_job, "fb_film_1": fb1_job, "fb_film_2": fb2_job}, props,
            )
        self.assertEqual(results, {"ig": "ig-post-id"})
        self.assertEqual(errors, {})
        ig_job.assert_called_once()
        fb1_job.assert_not_called()
        fb2_job.assert_not_called()
        self.assertEqual(props[PLATFORM_RESULT_KEYS["fb_film_1"]], FILM_PART4_FB_RESULT_IDS[0])
        self.assertEqual(props[PLATFORM_RESULT_KEYS["fb_film_2"]], FILM_PART4_FB_RESULT_IDS[1])

    def test_missing_one_shot_marker_does_not_publish(self):
        video = audited_part4()
        video["appProperties"][CLAIM_SLOT] = "manual-next-film"
        job = Mock()
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "instagram",
            "FORCE_STEM": FILM_PART4_IG_RECOVERY_STEM,
            "FILM_CLAIM_TO_CLEAR": FILM_PART4_IG_RECOVERY_CLAIM,
        }, clear=True):
            results, errors = execute_platform_jobs(
                Mock(), video, "manual-next-film", ["ig"], {"ig": job}, video["appProperties"],
            )
        self.assertEqual(results, {})
        self.assertIn("ig", errors)
        job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
