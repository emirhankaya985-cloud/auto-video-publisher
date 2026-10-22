"""Yoksul Part 3 one-time IG recovery: proof-based and Facebook-safe."""
import os
import unittest
from unittest.mock import Mock, patch

from scheduled_multi_publisher import (
    CLAIM_SLOT, CLAIMED_AT, FAILED_SLOT, FILM_USED, FILM_DONE_KEY,
    FILM_PART3_IG_RECOVERY_CLAIM, FILM_PART3_IG_RECOVERY_FILE_ID,
    FILM_PART3_IG_RECOVERY_STEM, FILM_PART3_FB_RESULT_IDS,
    PLATFORM_SLOT_KEYS, PLATFORM_RESULT_KEYS, PLATFORM_FAILURE_KEYS,
    PLATFORM_FAILURE_SLOT_KEYS, PLATFORM_INTENT_KEYS,
    verify_film_part3_ig_only_recovery, execute_platform_jobs,
)


def original_video():
    claim = FILM_PART3_IG_RECOVERY_CLAIM
    return {
        "id": FILM_PART3_IG_RECOVERY_FILE_ID,
        "name": FILM_PART3_IG_RECOVERY_STEM + ".mp4",
        "appProperties": {
            CLAIM_SLOT: claim,
            FAILED_SLOT: claim,
            PLATFORM_SLOT_KEYS["fb_film_1"]: claim,
            PLATFORM_SLOT_KEYS["fb_film_2"]: claim,
            PLATFORM_RESULT_KEYS["fb_film_1"]: FILM_PART3_FB_RESULT_IDS[0],
            PLATFORM_RESULT_KEYS["fb_film_2"]: FILM_PART3_FB_RESULT_IDS[1],
            PLATFORM_FAILURE_SLOT_KEYS["ig"]: claim,
            PLATFORM_FAILURE_KEYS["ig"]: "3",
        },
    }


class FilmRecoveryTests(unittest.TestCase):
    def test_exact_historical_state_is_eligible(self):
        self.assertTrue(verify_film_part3_ig_only_recovery(original_video()))

    def test_audited_legacy_missing_ig_failure_slot_is_safe(self):
        item = original_video()
        item["appProperties"].pop(PLATFORM_FAILURE_SLOT_KEYS["ig"])
        self.assertTrue(verify_film_part3_ig_only_recovery(item))

    def test_conflicting_ig_failure_slot_is_still_rejected(self):
        item = original_video()
        item["appProperties"][PLATFORM_FAILURE_SLOT_KEYS["ig"]] = "different-claim"
        with self.assertRaises(RuntimeError):
            verify_film_part3_ig_only_recovery(item)

    def test_existing_ig_post_or_intent_blocks_recovery(self):
        for key in (
            PLATFORM_SLOT_KEYS["ig"], PLATFORM_RESULT_KEYS["ig"],
            PLATFORM_INTENT_KEYS["ig"], "published_ig",
        ):
            item = original_video()
            item["appProperties"][key] = "already-exists"
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part3_ig_only_recovery(item)

    def test_mismatched_id_claim_fb_results_or_previous_attempt_blocks(self):
        for key, value in (
            ("id", "wrong-id"),
            ("name", "Yoksul_1986_Part_4.mp4"),
        ):
            item = original_video()
            item[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part3_ig_only_recovery(item)
        for key in (
            CLAIM_SLOT, FAILED_SLOT, PLATFORM_RESULT_KEYS["fb_film_1"],
            PLATFORM_RESULT_KEYS["fb_film_2"], PLATFORM_SLOT_KEYS["fb_film_1"],
            PLATFORM_SLOT_KEYS["fb_film_2"], PLATFORM_FAILURE_SLOT_KEYS["ig"],
        ):
            item = original_video()
            item["appProperties"][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part3_ig_only_recovery(item)
        for key in (FILM_USED, FILM_DONE_KEY, "film_part3_ig_recovery_used"):
            item = original_video()
            item["appProperties"][key] = "1"
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify_film_part3_ig_only_recovery(item)

    def test_only_ig_job_runs_after_one_shot_approval(self):
        video = original_video()
        props = video["appProperties"]
        slot = "manual-2026-10-19-1030-film"
        props[CLAIM_SLOT] = slot
        props["film_part3_ig_recovery_used"] = "1"
        props["film_part3_ig_recovery_from"] = FILM_PART3_IG_RECOVERY_CLAIM
        drive = Mock()
        job_ig, job_fb = Mock(return_value="instagram-post-123"), Mock()
        env = {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film",
            "FORCE_STEM": FILM_PART3_IG_RECOVERY_STEM,
            "FORCE_PLATFORM": "instagram",
            "FILM_CLAIM_TO_CLEAR": FILM_PART3_IG_RECOVERY_CLAIM,
        }
        with patch.dict(os.environ, env, clear=True):
            results, errors = execute_platform_jobs(
                drive, video, slot, ["ig"], {"ig": job_ig, "fb_film_1": job_fb}, props,
            )
        self.assertEqual(results, {"ig": "instagram-post-123"})
        self.assertEqual(errors, {})
        job_ig.assert_called_once()
        job_fb.assert_not_called()
        self.assertEqual(props[PLATFORM_SLOT_KEYS["ig"]], slot)
        self.assertEqual(props[PLATFORM_RESULT_KEYS["fb_film_1"]], FILM_PART3_FB_RESULT_IDS[0])

    def test_without_one_shot_marker_no_new_ig_post_is_sent(self):
        video = original_video()
        props = video["appProperties"]
        props[CLAIM_SLOT] = "manual-2026-10-19-1030-film"
        ig = Mock()
        with patch.dict(os.environ, {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "FORCE_ROUTE": "film", "FORCE_PLATFORM": "instagram",
            "FORCE_STEM": FILM_PART3_IG_RECOVERY_STEM,
            "FILM_CLAIM_TO_CLEAR": FILM_PART3_IG_RECOVERY_CLAIM,
        }, clear=True):
            _result, errors = execute_platform_jobs(
                Mock(), video, props[CLAIM_SLOT], ["ig"], {"ig": ig}, props,
            )
        self.assertIn("ig", errors)
        ig.assert_not_called()


if __name__ == "__main__":
    unittest.main()
