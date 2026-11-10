"""Offline non-publishing Film Bickin 8 source and one-shot security tests."""
import subprocess
import unittest

import film_part8_recovery as fix
import publisher_one_shot_gate as gate


def old_record(platform, file="Bickin_Part_3.mp4", status="done",
               sha=fix.OLDER_PART3_SHA):
    return {"route": "film", "platform": platform,
            "file": file, "status": status,
            "post_id": "123456789" if status == "done" else None,
            "source_sha256": sha,
            "visual_fingerprint": {"version": 1, "duration_ms": 180118,
                                   "frames": ["00008f2763320000",
                                              "00001f4783b62300",
                                              "0000177706060000"]}}


def original_hold(platform):
    return {"route":"film", "platform":platform, "file": fix.SOURCE_NAME,
            "status":"held", "source_sha256":fix.SOURCE_SHA,
            "failure":{"reason":"visual_duplicate_review",
                       "external_post_attempted":False,
                       "safe_to_repost":False,
                       "conflicting_platforms":[platform]}}


class FilmPart8RecoveryTests(unittest.TestCase):
    def test_only_exact_original_held_without_external_post_can_rearm(self):
        item = {"id": fix.SOURCE_ID, "name": fix.SOURCE_NAME}
        self.assertTrue(fix.eligible_original_held(item, original_hold("facebook")))
        cases = [
            (dict(item, id="other"), original_hold("facebook")),
            (item, dict(original_hold("facebook"), status="uncertain")),
            (item, dict(original_hold("facebook"), post_id="12345678")),
            (item, dict(original_hold("facebook"), source_sha256="a" * 64)),
        ]
        for source, row in cases:
            with self.subTest(source=source, row=row):
                self.assertFalse(fix.eligible_original_held(source, row))
        attempted = original_hold("instagram")
        attempted["failure"]["external_post_attempted"] = True
        self.assertFalse(fix.eligible_original_held(item, attempted))

    def test_expected_part3_and_unposted_export_collisions_only(self):
        fp = old_record("facebook")["visual_fingerprint"]
        item = {"route":"film", "id":fix.SOURCE_ID, "name":fix.SOURCE_NAME,
                "platforms":["facebook", "instagram"],
                "film_part8_strict_recheck":True}
        state = {"entries": {}}
        for p in item["platforms"]:
            state["entries"][f"film:{p}:older"] = old_record(p)
        state["entries"]["film:facebook:old-export"] = old_record(
            "facebook", file="Bickin_Part_8 (1).mp4", status="held",
            sha=fix.SOURCE_SHA)
        state["entries"]["film:facebook:old-export"]["failure"] = {
            "reason":"visual_duplicate_review",
            "external_post_attempted":False}
        self.assertTrue(fix.allowed_visual_collisions(item, state, fp))
        # A source with real Part 8 publication ID must never be uploaded again.
        state["entries"]["film:facebook:existing8"] = old_record(
            "facebook", file="Bickin_Part_8 (1).mp4", status="done",
            sha=fix.SOURCE_SHA)
        self.assertFalse(fix.allowed_visual_collisions(item, state, fp))
        state["entries"].pop("film:facebook:existing8")
        self.assertFalse(fix.allowed_visual_collisions(
            dict(item, film_part8_strict_recheck=False), state, fp))

    def test_extra_sample_difference_must_be_strong(self):
        def make_runner(same):
            def runner(argv, **kwargs):
                if argv[0] == "ffprobe":
                    return subprocess.CompletedProcess(argv, 0, b"180.118\n")
                if argv[0] == "ffmpeg":
                    path = argv[argv.index("-i") + 1]
                    data = bytes([10 if "part8" in path else (10 if same else 210)]) * 576
                    return subprocess.CompletedProcess(argv, 0, data)
                raise AssertionError("Unexpected offline command")
            return runner
        self.assertTrue(fix.clearly_distinct_sources(
            "part8.mp4", "part3.mp4", runner=make_runner(False))["distinct"])
        self.assertFalse(fix.clearly_distinct_sources(
            "part8.mp4", "part3.mp4", runner=make_runner(True))["distinct"])

    def test_one_shot_requires_exact_added_marker_and_day(self):
        args=("push","refs/heads/main",gate.FILM_PART8_SUBJECT,
              [gate.FILM_PART8_MARKER])
        self.assertTrue(gate.is_film_part8_once(*args,today="2026-11-10",run_attempt="1"))
        self.assertFalse(gate.is_film_part8_once(*args,today="2026-11-11",run_attempt="1"))
        self.assertFalse(gate.is_film_part8_once(*args,today="2026-11-10",run_attempt="2"))
        self.assertEqual(gate.determine_mode(*args),"publish")
        self.assertEqual(gate.determine_mode(
            "push","refs/heads/main",gate.FILM_PART8_SUBJECT,()),"audit")



    def test_known_20261110_preupload_crash_repairs_only_exact_intents(self):
        state = {"entries": {}}
        for platform in ("facebook", "instagram"):
            state["entries"][f"film:{platform}:{fix.SOURCE_ID}"] = {
                "route": "film", "platform": platform, "file": fix.SOURCE_NAME,
                "status": "intent", "run_id": "42805359391",
                "source_sha256": fix.SOURCE_SHA}
        state["entries"]["film:facebook:other"] = {
            "route":"film","platform":"facebook","file":"Bickin_Part_9.mp4",
            "status":"intent","run_id":"42805359391"}
        self.assertEqual(fix.reconcile_known_preupload_crash(state), 2)
        self.assertEqual(fix.reconcile_known_preupload_crash(state), 0)
        for platform in ("facebook", "instagram"):
            row = state["entries"][f"film:{platform}:{fix.SOURCE_ID}"]
            self.assertEqual(row["status"], "held")
            self.assertIs(row["failure"]["external_post_attempted"], False)
            self.assertIs(row["failure"]["safe_to_repost"], False)
        self.assertEqual(state["entries"]["film:facebook:other"]["status"], "intent")

    def test_identical_whole_audio_blocks_even_if_visual_samples_seem_distinct(self):
        import tempfile
        import json
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "comparison.json"
            item = {"route": "film", "platforms": ["facebook"],
                    "id": fix.SOURCE_ID, "name": fix.SOURCE_NAME}
            with patch.object(fix, "source_digest", side_effect=[fix.SOURCE_SHA, fix.OLDER_PART3_SHA]), \
                 patch.object(fix, "visual_fingerprint", return_value={"version": 1}), \
                 patch.object(fix, "allowed_visual_collisions", return_value=True), \
                 patch.object(fix, "clearly_distinct_sources", return_value={
                     "schema": 1, "distinct": True, "substantially_different_samples": 6}), \
                 patch.object(fix, "pcm_audio_digest", return_value="same-audio"):
                with self.assertRaisesRegex(RuntimeError, "source_is_prior_part_duplicate"):
                    fix.audit_part8_before_publish(
                        item, {"entries": {}}, Path(folder) / "8.mp4",
                        lambda _id, output: output, folder,
                        evidence_path=target)
            proof = json.loads(target.read_text())
            self.assertTrue(proof["complete_decoded_audio_identical"])
            self.assertFalse(proof["distinct"])
            self.assertFalse(proof["published_by_this_audit"])

if __name__ == "__main__":
    unittest.main()
