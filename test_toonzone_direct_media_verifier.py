"""No-network verification of old Meta media GETs; never upload."""
import copy
import unittest
from unittest.mock import Mock

import toonzone_direct_media_verifier as audit


def response(data, code=200):
    r = Mock()
    r.status_code = code
    r.json.return_value = data
    return r


class ToonZoneExactIdTests(unittest.TestCase):
    PAGE = {"page_id": audit.PAGE_ID, "instagram_id": audit.IG_USER_ID,
            "page_token": "DO_NOT_PRINT_SECRET"}

    def make_state(self):
        cap = "Original S01E04 Part1 owner caption"
        record = {"route": "toonzone", "platform": "instagram",
                  "status": "done", "file": "S01E04_Death_Punchies_Part1.mp4",
                  "post_id": "18100507712530539",
                  "caption_hash": audit.caption_digest(cap)}
        return {"schema": 1, "entries": {"source": record}}, cap

    def test_only_archived_source_id_can_be_selected(self):
        state, _ = self.make_state()
        rows = audit.candidates(state)
        self.assertEqual(len(rows), 48)
        valid = [r for r in rows if r["eligible"]]
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["slot"], "S01E04 Part1")
        self.assertEqual(valid[0]["post_id"], "18100507712530539")
        self.assertFalse(rows[0]["eligible"])
        self.assertEqual(rows[0]["archive_issue"], "archive_source_slot_missing")

    def test_verified_only_by_id_owner_caption_video_and_timestamp(self):
        state, caption = self.make_state()
        entry = next(r for r in audit.candidates(state) if r["eligible"])
        media = {"id": entry["post_id"], "username": "toonzone.tr",
                 "caption": caption, "media_type": "VIDEO",
                 "timestamp": "2026-11-01T15:20:00+0000"}
        get = Mock(return_value=response(media))
        result = audit.inspect_post(entry, owner_username="toonzone.tr",
                                    token="CREDENTIAL", get=get)
        self.assertEqual(result["status"], "verified_live_exact_id_owner_caption_time")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], audit.API + entry["post_id"])
        self.assertNotIn("CREDENTIAL", str(result))

    def test_owner_caption_or_media_mismatch_always_held(self):
        state, caption = self.make_state()
        candidate = next(r for r in audit.candidates(state) if r["eligible"])
        base = {"id": candidate["post_id"], "username": "toonzone.tr",
                "caption": caption, "media_type": "VIDEO",
                "timestamp": "2026-11-01T15:20:00+00:00"}
        for change in ({"id": "18100000000000000"},
                       {"username": "someone_else"},
                       {"caption": "different words"},
                       {"media_type": "IMAGE"},
                       {"timestamp": "bogus"}):
            with self.subTest(change=change):
                data = dict(base, **change)
                result = audit.inspect_post(candidate, owner_username="toonzone.tr",
                                            token="SECRET", get=Mock(return_value=response(data)))
                self.assertEqual(result["status"], "held")
                self.assertNotIn("SECRET", str(result))

    def test_provider_errors_never_authorize_republish(self):
        state, _ = self.make_state()
        candidate = next(r for r in audit.candidates(state) if r["eligible"])
        get = Mock(return_value=response({"error": {"code": 190,
                                                    "message": "token=SHOULD_NOT_APPEAR"}}, 401))
        record = audit.inspect_post(candidate, owner_username="toonzone.tr",
                                    token="SECRET", get=get)
        self.assertEqual(record["status"], "held")
        self.assertEqual(record["reason"], "provider_get_rejected")
        self.assertEqual(record["graph_code"], 190)
        self.assertEqual(record["http_status"], 401)
        self.assertNotIn("SHOULD_NOT_APPEAR", str(record))

    def test_wrong_page_identity_uses_no_provider_calls(self):
        get = Mock()
        bad = dict(self.PAGE, instagram_id="wrong")
        self.assertEqual(audit.identity_username(bad, get=get)[1], "page_identity_not_pinned")
        get.assert_not_called()

    def test_missing_or_malformed_archive_is_not_a_reupload_signal(self):
        state, _ = self.make_state()
        broken = copy.deepcopy(state)
        broken["entries"]["source"]["post_id"] = ""
        assert audit.candidates(broken)[12]["eligible"] is False
        duplicate = copy.deepcopy(state)
        duplicate["entries"]["same"] = dict(state["entries"]["source"])
        with self.assertRaisesRegex(ValueError, "duplicate_archived_source_slot"):
            audit.candidates(duplicate)

    def test_historical_non_sha256_caption_digest_is_not_a_deleted_post(self):
        state, _ = self.make_state()
        entry = state["entries"]["source"]
        entry["caption_hash"] = "historical-legacy-id"
        rows = audit.candidates(state)
        candidate = next(x for x in rows if x["slot"] == "S01E04 Part1")
        self.assertFalse(candidate["eligible"])
        self.assertEqual(candidate["archive_issue"], "archive_caption_digest_not_sha256")
        self.assertEqual(candidate["post_id"], entry["post_id"])
        get = Mock()
        result = audit.inspect_post(candidate, owner_username="toonzone.tr", token="secret", get=get)
        self.assertEqual(result["reason"], "archive_caption_digest_not_sha256")
        get.assert_not_called()

    def test_graph_permission_subcode_sanitized(self):
        state, _ = self.make_state()
        candidate = next(x for x in audit.candidates(state) if x["eligible"])
        fake = {"error": {"message": "secret-key-would-be-sensitive",
                          "code": 100, "error_subcode": 33}}
        record = audit.inspect_post(candidate, owner_username="toonzone.tr",
                                    token="secret", get=Mock(return_value=response(fake, 400)))
        self.assertEqual(record["graph_code"], 100)
        self.assertEqual(record["graph_subcode"], 33)
        self.assertNotIn("secret-key-would-be-sensitive", str(record))

    def test_full_audit_preserves_missing_receipts_and_never_posts(self):
        state, caption = self.make_state()
        source = next(r for r in audit.candidates(state) if r["eligible"])
        count = {"get": 0}
        def get(url, **kwargs):
            count["get"] += 1
            self.assertEqual(kwargs.get("allow_redirects"), False)
            self.assertEqual(kwargs.get("headers", {}).get("Authorization"),
                             "Bearer " + self.PAGE["page_token"])
            if url.endswith(audit.IG_USER_ID):
                return response({"id": audit.IG_USER_ID, "username": "toonzone.tr"})
            self.assertEqual(url, audit.API + source["post_id"])
            return response({"id": source["post_id"], "username": "toonzone.tr",
                             "caption": caption, "media_type": "VIDEO",
                             "timestamp": "2026-11-01T15:20:00+00:00"})
        result = audit.audit(state, self.PAGE, get=get)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["episodes_4_to_12_verified"], 1)
        self.assertEqual(result["episodes_4_to_12_missing_or_unverified"], 35)
        self.assertEqual(count["get"], 2)
        self.assertEqual(result["media_posts_created"], 0)
        self.assertEqual(result["state_mutations"], 0)


if __name__ == "__main__":
    unittest.main()
