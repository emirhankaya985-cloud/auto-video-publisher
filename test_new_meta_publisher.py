import unittest
from unittest.mock import patch
from unittest.mock import patch

from new_meta_publisher import (
    FILM_TARGETS, build_meta_callbacks, execute_plan, film_reconciliation_candidate,
    target_status_key, toonzone_candidate,
)
from new_meta_routes import ROUTES


def file_pair(stem, props=None, folder=None, fid="v"):
    return [
        {"id": fid, "name": stem + ".mp4", "parents": [folder] if folder else [], "appProperties": props or {}},
        {"id": fid + "t", "name": stem + ".txt", "parents": [folder] if folder else []},
    ]


class Gate:
    enabled = True
    def __init__(self, *args): self.finished = []
    def claim(self): return True
    def finish(self, *args, **kwargs): self.finished.append((args, kwargs))


class NewMetaPublisherTests(unittest.TestCase):
    def test_partial_film_success_reuses_same_file_only_for_missing_targets(self):
        props = {target_status_key(FILM_TARGETS[0]): "confirmed"}
        files = file_pair("Avanak_Apti_Part_1", props, ROUTES["film"].folder_id)
        result = film_reconciliation_candidate(files)
        self.assertEqual(result["video"]["id"], "v")
        self.assertEqual(result["pending_targets"], list(FILM_TARGETS[1:]))

    def test_unknown_or_failed_film_target_blocks_automatic_progress(self):
        for status in ("submitted", "unknown", "failed"):
            files = file_pair("Avanak_Apti_Part_1", {target_status_key(FILM_TARGETS[0]): status})
            self.assertTrue(film_reconciliation_candidate(files)["blocked"])

    def test_completed_part_advances_in_numeric_order(self):
        done = {target_status_key(t): "confirmed" for t in FILM_TARGETS}
        files = file_pair("Movie_Part_2", fid="v2") + file_pair("Movie_Part_1", done, fid="v1")
        self.assertEqual(film_reconciliation_candidate(files)["stem"], "Movie_Part_2")

    def test_toonzone_uses_no_txt_but_requires_review_and_rights(self):
        video = {"id":"c1", "name":"S01E01_The_Power_Part1.mp4", "appProperties":{}}
        self.assertIsNone(toonzone_candidate([video], {}))
        review = {"c1":{"verified":True,"rights_approved":True,"language":"tr","concept":"cartoon",
                        "title":"Güç","summary":"Doğrulanmış bölüm özeti."}}
        self.assertEqual(toonzone_candidate([video], review)["video"]["id"], "c1")

    def test_execution_keeps_film_closed_even_when_legacy_global_flags_are_true(self):
        auth={"pages":[
            {"page_name":"Film Mağrası","page_id":"1239298989276639","instagram_id":"i1","page_token":"x"},
            {"page_name":"Filmmağrası1","page_id":"854990964375370","page_token":"y"},
        ]}
        video={"id":"v","parents":[ROUTES["film"].folder_id],"appProperties":{}}
        states={}
        callbacks={FILM_TARGETS[0]:lambda _:{"id":"r1","url":"u1"},
                   FILM_TARGETS[1]:lambda _:(_ for _ in ()).throw(TimeoutError()),
                   FILM_TARGETS[2]:lambda _:{"id":"r3","url":"u3"}}
        with patch.dict("os.environ", {"ENABLE_NEW_META_ROUTES":"true",
                                        "META_NEW_ROUTES_RIGHTS_APPROVED":"true"}, clear=True):
            result=execute_plan("film",auth,video,callbacks,{},True,
                                lambda k,s:states.__setitem__(k,s),Gate,
                                publishing_enabled=True)
        self.assertTrue(all(r["status"] == "skipped" for r in result))
        self.assertTrue(all(r["reason"] == "route_disabled" for r in result))

    def test_production_execution_is_fail_closed_for_new_meta_routes(self):
        video = {"id": "c1", "parents": [ROUTES["toonzone"].folder_id], "appProperties": {}}
        auth = {"pages": [{"page_name": "ToonZone", "page_id": "p3", "instagram_id": "i3", "page_token": "x"}]}
        with patch.dict("os.environ", {}, clear=True):
            result = execute_plan("toonzone", auth, video, {}, {}, True, lambda *_: None,
                                  publishing_enabled=True)
        self.assertTrue(all(row["reason"] == "route_disabled" for row in result))

    def test_callbacks_are_empty_by_default(self):
        auth={"pages":[
            {"page_name":"ToonZone","page_id":"p1","instagram_id":"i1","page_token":"x"},
        ]}
        self.assertEqual(build_meta_callbacks("toonzone", auth, "clip.mp4"), {})

    def test_callback_adapter_passes_page_path_and_caption(self):
        auth={"pages":[
            {"page_name":"ToonZone","page_id":"p1","instagram_id":"i1","page_token":"x"},
        ]}
        calls=[]
        def fake_fb(page, path, caption):
            calls.append((page["page_id"], path, caption))
            return "remote-1"
        callbacks = build_meta_callbacks("toonzone", auth, "clip.mp4",
                                        publishing_enabled=True,
                                        facebook_uploader=fake_fb,
                                        instagram_uploader=fake_fb)
        result = callbacks["toonzone_fb"]({"title":"Başlık", "summary":"Özet"})
        self.assertEqual(result, {"id":"remote-1"})
        self.assertEqual(calls, [("p1", "clip.mp4", "Başlık\n\nÖzet")])


if __name__ == "__main__": unittest.main()
