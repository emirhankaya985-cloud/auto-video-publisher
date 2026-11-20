"""Film17 exact source/caption evidence: GET only and always held."""
import copy
import unittest
from unittest.mock import Mock

import film_part17_readonly_reconcile as a
from expired_ig_container_recovery import (
    FILM17_SOURCE_ID, FILM17_FILENAME, FILM17_SOURCE_SHA256, FILM17_CAPTION_HASH,
    FILM17_CONTAINER_ID, FILM17_ORIGIN_RUN,
)

CAPTION = (
    "En Büyük Şaban | Part 17 🤵😂\nhttps://miroviastudio.etsy.com\n"
    "Şaban yine bildiğin gibi: saf, dobra ve olayların tam göbeğinde! "
    "Yanlış anlaşılmalar, absürt tesadüfler ve Yeşilçam’ın efsane komedisi… "
    "Kahkaha garantili 🎬🤣\n"
    "Devamı geliyor — takipte kal!\n"
    "👇 Bu unutulmaz sahne hakkında ne düşünüyorsun? Yorumlarda buluşalım!\n\n"
    "#AbsürtMizah #Nostalji #Yeşilçam #YeşilçamKlasikleri #KlasikTürkFilmleri"
)


def fake_json(data, status=200):
    resp = Mock(status_code=status)
    resp.json.return_value = data
    return resp


class Film17ReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(a.caption_digest(CAPTION), FILM17_CAPTION_HASH)
        self.page = {"page_name": "Film Mağarası", "page_id": a.FILM_PAGE_ID,
                     "instagram_id": a.FILM_IG_ID, "page_token": "PRIVATE_TOKEN",
                     "instagram_username": "film_magrasi"}
        self.entry = {
            "route": "film", "platform": "instagram", "file": FILM17_FILENAME,
            "source_sha256": FILM17_SOURCE_SHA256, "caption_hash": FILM17_CAPTION_HASH,
            "publish_caption": CAPTION, "run_id": FILM17_ORIGIN_RUN,
            "status": "uncertain", "post_id": None,
            "failure": {"reason": "invalid_media_or_graph_request",
                        "container_id": FILM17_CONTAINER_ID,
                        "http_status": 400, "safe_to_repost": False},
        }
        self.state = {"schema": 1,
                      "entries": {f"film:instagram:{FILM17_SOURCE_ID}": self.entry}}
        self.old = repr(self.state)

    def get(self, url, **kwargs):
        self.assertTrue(url.startswith("https://graph.facebook.com/v24.0/"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer PRIVATE_TOKEN")
        self.assertFalse(kwargs["allow_redirects"])
        if url.endswith(FILM17_CONTAINER_ID):
            return fake_json({"id": FILM17_CONTAINER_ID, "status_code": "EXPIRED"})
        if url.endswith("18198712345670000"):
            return fake_json({"id": "18198712345670000", "caption": CAPTION,
                              "username": "film_magrasi", "media_type": "VIDEO",
                              "timestamp": "2026-11-12T08:30:00+00:00"})
        raise AssertionError("unexpected provider API endpoint")

    def row(self, caption=CAPTION, mid="18198712345670000"):
        return {"id": mid, "caption": caption, "media_type": "VIDEO",
                "timestamp": "2026-11-12T08:30:00+00:00"}

    def test_unique_caption_video_still_not_a_binary_source_proof(self):
        result = a.reconcile(self.state, self.page, get=self.get, rows=[self.row()])
        self.assertEqual(result["status"], "uncertain_single_matching_live_caption")
        self.assertEqual(result["instagram_candidate_post_id"], "18198712345670000")
        self.assertTrue(result["live_unique_media_owner_verified"])
        self.assertFalse(result["original_source_binary_verified_by_meta"])
        self.assertFalse(result["reupload_authorized"])
        self.assertEqual(result["old_container_status"], "EXPIRED")
        self.assertEqual(repr(self.state), self.old)
        self.assertNotIn("PRIVATE_TOKEN", str(result))

    def test_original_container_published_cannot_imply_original_film_bytes(self):
        def published_status_get(url, **kwargs):
            if url.endswith(FILM17_CONTAINER_ID):
                return fake_json({"id": FILM17_CONTAINER_ID, "status_code": "PUBLISHED"})
            return self.get(url, **kwargs)
        report = a.reconcile(self.state, self.page,
                             get=published_status_get, rows=[])
        self.assertEqual(report["old_container_status"], "PUBLISHED")
        self.assertEqual(report["status"], "uncertain_no_matching_live_caption")
        self.assertFalse(report["original_source_binary_verified_by_meta"])
        self.assertFalse(report["reupload_authorized"])
        self.assertEqual(self.entry["status"], "uncertain")

    def test_no_caption_match_is_uncertain_not_missing_post(self):
        result = a.reconcile(self.state, self.page, get=self.get, rows=[self.row("other caption")])
        self.assertEqual(result["status"], "uncertain_no_matching_live_caption")
        self.assertFalse(result["reupload_authorized"])
        self.assertIsNone(result["instagram_candidate_post_id"])
        self.assertEqual(result["next_action"], "normal_publisher_exact_expired_container_gate")
        self.assertTrue(result["next_action_requires_fresh_live_checks"])

    def test_two_caption_matches_remain_ambiguous(self):
        rows = [self.row(), self.row(mid="18198712345670002")]
        result = a.reconcile(self.state, self.page, get=self.get, rows=rows)
        self.assertEqual(result["status"], "uncertain_multiple_caption_matches")
        self.assertIsNone(result["instagram_candidate_post_id"])
        self.assertFalse(result["reupload_authorized"])

    def test_wrong_source_binding_fails_before_api_call(self):
        for name, value in (("file", "Saban_Part_18.mp4"),
                            ("source_sha256", "bad"), ("status", "done"),
                            ("caption_hash", "wrong"), ("post_id", "18112345678900000")):
            with self.subTest(name=name):
                old = self.entry[name]
                self.entry[name] = value
                get = Mock()
                with self.assertRaises(ValueError):
                    a.reconcile(self.state, self.page, get=get, rows=[])
                get.assert_not_called()
                self.entry[name] = old

    def test_wrong_owner_is_denied_before_api_call(self):
        bad = dict(self.page, instagram_id="unknown")
        get = Mock()
        with self.assertRaises(ValueError):
            a.reconcile(self.state, bad, get=get, rows=[])
        get.assert_not_called()

    def test_unique_caption_but_wrong_username_not_live_owner_proof(self):
        def get(url, **kwargs):
            if url.endswith(FILM17_CONTAINER_ID):
                return fake_json({"id": FILM17_CONTAINER_ID, "status_code": "EXPIRED"})
            return fake_json({"id": "18198712345670000", "caption": CAPTION,
                              "username": "somebody_else", "media_type": "VIDEO"})
        result = a.reconcile(self.state, self.page, get=get, rows=[self.row()])
        self.assertEqual(result["status"], "uncertain_direct_media_unverified")
        self.assertFalse(result["live_unique_media_owner_verified"])
        self.assertIsNone(result["instagram_candidate_post_id"])
        self.assertFalse(result["reupload_authorized"])


if __name__ == "__main__":
    unittest.main()
