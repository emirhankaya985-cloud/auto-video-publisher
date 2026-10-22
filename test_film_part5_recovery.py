"""Exact, one-shot Film Part 5 recovery remains manual and all-Meta only."""
import os
import unittest
from unittest.mock import Mock, patch

import scheduled_multi_publisher as publisher
from scheduled_multi_publisher import (
    CLAIM_SLOT, FAILED_SLOT, FILM_DONE_KEY, FILM_USED,
    FILM_PART5_RECOVERY_CLAIM, FILM_PART5_RECOVERY_FILE_ID,
    FILM_PART5_RECOVERY_STEM, PLATFORM_FAILURE_KEYS,
    PLATFORM_FAILURE_SLOT_KEYS, PLATFORM_INTENT_KEYS, PLATFORM_RESULT_KEYS,
    PLATFORM_SLOT_KEYS, execute_platform_jobs,
    valid_film_part5_recovery_request, verify_film_part5_recovery,
)


def audited_part5():
    return {
        "id": FILM_PART5_RECOVERY_FILE_ID,
        "name": FILM_PART5_RECOVERY_STEM + ".mp4",
        "appProperties": {
            CLAIM_SLOT: FILM_PART5_RECOVERY_CLAIM,
            FAILED_SLOT: FILM_PART5_RECOVERY_CLAIM,
            PLATFORM_FAILURE_KEYS["ig"]: "3",
            PLATFORM_FAILURE_SLOT_KEYS["ig"]: FILM_PART5_RECOVERY_CLAIM,
        },
    }


class FilmPart5RecoveryTests(unittest.TestCase):
    def setUp(self):
        publisher._LAST_PLATFORM_PUBLISH_AT.clear()

    def tearDown(self):
        publisher._LAST_PLATFORM_PUBLISH_AT.clear()

    def test_exact_unpublished_claim_is_eligible(self):
        self.assertTrue(verify_film_part5_recovery(audited_part5()))

    def test_conflicting_or_partial_platform_state_fails_closed(self):
        for key, value in (
            ("id", "wrong-id"),
            ("name", "Yoksul_1986_Part_6.mp4"),
        ):
            video = audited_part5()
            video[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part5_recovery(video)

        for key in (
            CLAIM_SLOT, FAILED_SLOT, PLATFORM_FAILURE_KEYS["ig"],
            PLATFORM_SLOT_KEYS["fb_film_1"], PLATFORM_RESULT_KEYS["fb_film_1"],
            PLATFORM_INTENT_KEYS["fb_film_1"], PLATFORM_SLOT_KEYS["fb_film_2"],
            PLATFORM_RESULT_KEYS["fb_film_2"], PLATFORM_INTENT_KEYS["fb_film_2"],
            PLATFORM_SLOT_KEYS["ig"], PLATFORM_RESULT_KEYS["ig"],
            PLATFORM_INTENT_KEYS["ig"], FILM_USED, FILM_DONE_KEY,
            "film_part5_recovery_used",
        ):
            video = audited_part5()
            video["appProperties"][key] = "1" if key in (FILM_USED, FILM_DONE_KEY) else "conflicting"
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part5_recovery(video)

    def test_manual_request_is_exact_all_meta_and_no_youtube(self):
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "",
            "FORCE_STEM": FILM_PART5_RECOVERY_STEM,
            "FILM_CLAIM_TO_CLEAR": FILM_PART5_RECOVERY_CLAIM,
        }, clear=True):
            self.assertTrue(valid_film_part5_recovery_request("film", False))
            self.assertFalse(valid_film_part5_recovery_request("film", True))
            for key, value in (
                ("FORCE_ROUTE", "toonzone"),
                ("FORCE_PLATFORM", "instagram"),
                ("FORCE_STEM", "Yoksul_1986_Part_4"),
                ("FILM_CLAIM_TO_CLEAR", "other-claim"),
                ("BACKFILL_ROUTE", "film"),
                ("TOKEN_FILM_YOUTUBE_JSON", "configured"),
                ("GITHUB_EVENT_NAME", "schedule"),
            ):
                env = {
                    "GITHUB_EVENT_NAME": "workflow_dispatch",
                    "FORCE_ROUTE": "film", "FORCE_PLATFORM": "",
                    "FORCE_STEM": FILM_PART5_RECOVERY_STEM,
                    "FILM_CLAIM_TO_CLEAR": FILM_PART5_RECOVERY_CLAIM,
                }
                env[key] = value
                with self.subTest(key=key), patch.dict(os.environ, env, clear=True):
                    self.assertFalse(valid_film_part5_recovery_request("film", False))

    def test_one_shot_recovery_runs_both_facebook_pages_and_instagram(self):
        video = audited_part5()
        props = video["appProperties"]
        props[CLAIM_SLOT] = "manual-2026-10-20-1010-film"
        props["film_part5_recovery_used"] = "1"
        props["film_part5_recovery_from"] = FILM_PART5_RECOVERY_CLAIM
        drive = Mock()
        jobs = {
            "fb_film_1": Mock(return_value="fb1-id"),
            "fb_film_2": Mock(return_value="fb2-id"),
            "ig": Mock(return_value="ig-id"),
        }
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "",
            "FORCE_STEM": FILM_PART5_RECOVERY_STEM,
            "FILM_CLAIM_TO_CLEAR": FILM_PART5_RECOVERY_CLAIM,
            "MIN_PLATFORM_INTERVAL_SECONDS": "0",
        }, clear=True):
            results, errors = execute_platform_jobs(
                drive, video, "manual-2026-10-20-1010-film",
                ["fb_film_1", "fb_film_2", "ig"], jobs, props,
            )

        self.assertEqual(results, {"fb_film_1": "fb1-id", "fb_film_2": "fb2-id", "ig": "ig-id"})
        self.assertEqual(errors, {})
        for job in jobs.values():
            job.assert_called_once()
        self.assertEqual(props[PLATFORM_RESULT_KEYS["fb_film_1"]], "fb1-id")
        self.assertEqual(props[PLATFORM_RESULT_KEYS["fb_film_2"]], "fb2-id")
        self.assertEqual(props[PLATFORM_RESULT_KEYS["ig"]], "ig-id")
        with self.assertRaises(RuntimeError):
            verify_film_part5_recovery(video)

    def test_exhausted_ig_without_one_shot_marker_is_not_called(self):
        video = audited_part5()
        job = Mock()
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "",
            "FORCE_STEM": FILM_PART5_RECOVERY_STEM,
            "FILM_CLAIM_TO_CLEAR": FILM_PART5_RECOVERY_CLAIM,
        }, clear=True):
            results, errors = execute_platform_jobs(
                Mock(), video, "manual-next-film", ["ig"], {"ig": job}, video["appProperties"],
            )
        self.assertEqual(results, {})
        self.assertIn("ig", errors)
        job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
