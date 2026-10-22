import unittest

from new_meta_routes import (
    ROUTES, assert_same_film_file, dry_run_route, toonzone_metadata_draft,
    toonzone_asset_dry_run, verified_pages,
)


def auth():
    return {"pages": [
        {"page_name": "Film Mağrası", "page_id": "1239298989276639", "instagram_id": "ig1", "page_token": "x"},
        {"page_name": "Filmmağrası1", "page_id": "854990964375370", "page_token": "y"},
        {"page_name": "ToonZone", "page_id": "p3", "instagram_id": "ig3", "page_token": "z"},
        {"page_name": "Daily Laugh Lab", "page_id": "p4", "instagram_id": "ig4", "page_token": "w"},
        {"page_name": "Dizimaratonu", "page_id": "excluded", "page_token": "e"},
    ]}


class NewMetaRouteTests(unittest.TestCase):
    def test_all_new_routes_are_disabled(self):
        self.assertTrue(all(not route.enabled for route in ROUTES.values()))

    def test_film_uses_same_file_for_three_exact_targets(self):
        video = {"id": "movie-part-1", "parents": [ROUTES["film"].folder_id]}
        plan = dry_run_route("film", auth(), video, rights_approved=True)
        self.assertTrue(assert_same_film_file(plan))
        self.assertEqual([x["target"] for x in plan], ["film_magrasi_fb", "filmmagrasi1_fb", "film_magrasi_ig"])
        self.assertTrue(all(not x["publishing_enabled"] for x in plan))

    def test_wrong_parent_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "parent"):
            dry_run_route("film", auth(), {"id": "x", "parents": ["wrong"]}, rights_approved=True)

    def test_rights_are_required(self):
        video = {"id": "x", "parents": [ROUTES["toonzone"].folder_id]}
        with self.assertRaisesRegex(RuntimeError, "Telif"):
            dry_run_route("toonzone", auth(), video)

    def test_instagram_identity_is_required(self):
        data = auth(); data["pages"][3].pop("instagram_id")
        video = {"id": "x", "parents": [ROUTES["daily_laugh_instagram"].folder_id]}
        with self.assertRaisesRegex(RuntimeError, "Instagram"):
            dry_run_route("daily_laugh_instagram", data, video, rights_approved=True)

    def test_excluded_page_is_never_returned(self):
        self.assertNotIn("Dizimaratonu", verified_pages(auth()))

    def test_duplicate_page_name_fails_closed(self):
        data = auth(); data["pages"].append(dict(data["pages"][0]))
        with self.assertRaisesRegex(RuntimeError, "tekil değil"):
            verified_pages(data)

    def test_toonzone_metadata_requires_verified_turkish_cartoon_and_rights(self):
        valid = {"verified": True, "language": "tr", "concept": "cartoon",
                 "title": "Güç", "summary": "Mordecai ve Rigby yeni bir güç keşfeder."}
        for review, rights in [({}, True), (dict(valid, language="en"), True),
                               (dict(valid, concept="meme"), True), (valid, False)]:
            with self.subTest(review=review, rights=rights), self.assertRaises(RuntimeError):
                toonzone_metadata_draft(review, rights)
        draft = toonzone_metadata_draft(valid, True)
        self.assertEqual(draft["title"], "Güç")
        self.assertIn("#toonzone", draft["description"])

    def test_toonzone_asset_dry_run_pairs_video_and_cover(self):
        video = {"id": "v1", "name": "S01E01_The_Power_Part1.mp4",
                 "parents": [ROUTES["toonzone"].folder_id]}
        cover = {"id": "c1", "name": "S01E01_The_Power_Part1.png",
                 "parents": ["covers"]}
        result = toonzone_asset_dry_run(video, [cover], "covers", True)
        self.assertEqual(result, {"video_id": "v1", "cover_id": "c1",
                                  "publishing_enabled": False})


if __name__ == "__main__":
    unittest.main()
