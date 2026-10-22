import json
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout
from io import StringIO

import connection_audit
from meta_connection_audit import (
    FILM_AUDIT_FILES, FILM_CLAIM_FILE_ID, FILM_KNOWN_FB_IDS, REQUIRED_PERMISSIONS,
    audit_film_claim, audit_film_publications, audit_meta,
    safe_meta_error, token_format_flags,
)


class MetaConnectionAuditTests(unittest.TestCase):
    def test_token_format_flags_are_boolean_and_never_echo_value(self):
        flags = token_format_flags(' "synthetic-token"\n')
        self.assertEqual(flags, {
            "empty": False,
            "leading_whitespace": True,
            "trailing_whitespace": True,
            "contains_line_break": True,
            "surrounded_by_quote": False,
        })
        self.assertTrue(token_format_flags("")["empty"])
        self.assertTrue(token_format_flags('"synthetic-token"')["surrounded_by_quote"])
        self.assertNotIn("synthetic-token", str(flags))

    def test_http_status_is_recorded_before_json_parse_and_error_is_redacted(self):
        diagnostic = {"token_format": token_format_flags("SENSITIVE_TOKEN")}
        response = Mock(status_code=401, ok=False)

        def parse_json():
            self.assertEqual(diagnostic["http_status"], 401)
            self.assertEqual(diagnostic["phase"], "response_json_parse")
            raise ValueError("SENSITIVE_TOKEN and private response content")

        response.json.side_effect = parse_json
        session = Mock()
        session.send.return_value = response
        stdout = StringIO()
        with patch.object(connection_audit.requests, "Session", return_value=session), redirect_stdout(stdout):
            try:
                connection_audit.graph_get("me/accounts", "SENSITIVE_TOKEN", diagnostic=diagnostic)
            except ValueError as exc:
                safe = safe_meta_error(exc, diagnostic)
            else:
                self.fail("expected JSON parsing error")

        output = stdout.getvalue() + str(safe)
        self.assertEqual(safe["phase"], "response_json_parse")
        self.assertEqual(safe["http_status"], 401)
        self.assertEqual(safe["error_type"], "ValueError")
        self.assertTrue(any(frame["file"] == "connection_audit.py" for frame in safe["traceback"]), safe["traceback"])
        self.assertNotIn("SENSITIVE_TOKEN", output)
        self.assertNotIn("private response content", output)
        self.assertIn('"http_status": 401', stdout.getvalue())
        phases = [
            line.split("META_DIAGNOSTIC ", 1)[1]
            for line in stdout.getvalue().splitlines()
            if "META_DIAGNOSTIC " in line
        ]
        self.assertEqual([json.loads(row)["phase"] for row in phases], [
            "request_preparation", "http_call", "response_json_parse",
        ])

    def test_http_call_error_is_separated_from_preparation(self):
        diagnostic = {"token_format": token_format_flags("SENSITIVE_TOKEN")}
        session = Mock()
        session.send.side_effect = ValueError("SENSITIVE_TOKEN")
        stdout = StringIO()
        with patch.object(connection_audit.requests, "Session", return_value=session), redirect_stdout(stdout):
            try:
                connection_audit.graph_get("me/accounts", "SENSITIVE_TOKEN", diagnostic=diagnostic)
            except ValueError as exc:
                safe = safe_meta_error(exc, diagnostic)
            else:
                self.fail("expected HTTP-call error")
        self.assertEqual(safe["phase"], "http_call")
        self.assertIsNone(safe["http_status"])
        self.assertNotIn("SENSITIVE_TOKEN", stdout.getvalue() + str(safe))

    def test_request_preparation_error_has_no_http_status(self):
        diagnostic = {"token_format": token_format_flags("SENSITIVE_TOKEN")}
        session = Mock()
        session.prepare_request.side_effect = ValueError("SENSITIVE_TOKEN")
        with patch.object(connection_audit.requests, "Session", return_value=session), redirect_stdout(StringIO()):
            try:
                connection_audit.graph_get("me/accounts", "SENSITIVE_TOKEN", diagnostic=diagnostic)
            except ValueError as exc:
                safe = safe_meta_error(exc, diagnostic)
            else:
                self.fail("expected request-preparation error")
        self.assertEqual(safe["phase"], "request_preparation")
        self.assertIsNone(safe["http_status"])
        self.assertNotIn("SENSITIVE_TOKEN", str(safe))

    @patch("meta_connection_audit.graph_get")
    @patch("meta_connection_audit.graph_list")
    def test_film_claim_audit_matches_exact_saved_media_id_read_only(self, listing, get):
        from unittest.mock import Mock
        from ordered_channels import FILM_FOLDER_ID

        drive = Mock()
        drive.files().get().execute.return_value = {
            "id": FILM_CLAIM_FILE_ID,
            "name": "Yoksul_1986_Part_2.mp4",
            "parents": [FILM_FOLDER_ID],
            "appProperties": {
                "claimed_route_slot": "manual-2026-10-17-0819-film",
                "claimed_at": "2026-10-17T08:19:42+03:00",
                "result_ig": "media-123",
            },
        }
        get.return_value = {
            "id": "1239298989276639",
            "instagram_business_account": {"id": "ig-film"},
        }
        listing.return_value = [{
            "id": "media-123", "permalink": "https://www.instagram.com/reel/public/",
            "timestamp": "2026-10-17T05:20:00+0000", "caption": "Yoksul Part 2",
        }]
        result = audit_film_claim(
            file_id=FILM_CLAIM_FILE_ID,
            meta_auth={"pages": [{
                "page_name": "Film Mağarası", "page_id": "1239298989276639",
                "instagram_id": "ig-film", "page_token": "secret",
            }]},
            drive=drive,
        )
        self.assertEqual(result["result"], "published_id_match")
        self.assertEqual(result["id_matches"][0]["id"], "media-123")
        self.assertEqual(result["claim"], "manual-2026-10-17-0819-film")
        self.assertFalse(result["publishing_performed"])
        self.assertFalse(result["historical_deletions_verifiable"])
        listing.assert_called_once()

    @patch("meta_connection_audit.graph_get")
    @patch("meta_connection_audit.graph_list")
    def test_film_publication_audit_is_read_only_and_verifies_exact_pages(self, listing, get):
        from ordered_channels import FILM_FOLDER_ID

        drive = Mock()
        drive.files().get().execute.return_value = {
            "id": FILM_FOLDER_ID, "appProperties": {"film_active_key": "Yoksul_1986"},
        }
        canonical_items = [
            {"id": file_id, "name": name, "mimeType": "video/mp4", "parents": [FILM_FOLDER_ID],
             "size": "1000", "videoMediaMetadata": {"durationMillis": "180000"},
             "appProperties": {"claimed_route_slot": "manual-old-film"}}
            for name, file_id in FILM_AUDIT_FILES.items()
        ] + [
            {"id": "synthetic-part-6", "name": "Yoksul_1986_Part_6.mp4", "mimeType": "video/mp4",
             "parents": [FILM_FOLDER_ID], "appProperties": {"intent_ig_slot": "manual-p6"}},
            {"id": "synthetic-part-10", "name": "Yoksul_1986_Part_10.mp4", "mimeType": "video/mp4",
             "parents": [FILM_FOLDER_ID], "appProperties": {"failure_ig_count": "3"}},
        ]
        drive.files().list().execute.return_value = {"files": canonical_items}

        page1_ids = {values[0] for values in FILM_KNOWN_FB_IDS.values()}

        def graph_get_result(path, _token, **_kwargs):
            if path == "1239298989276639":
                return {"id": path, "instagram_business_account": {"id": "ig-film"}}
            page_id = "1239298989276639" if str(path) in page1_ids else "854990964375370"
            return {"id": str(path), "from": {"id": page_id},
                    "permalink_url": f"https://fb.test/{path}", "created_time": "2026-10-18T01:00:00+0000"}

        get.side_effect = graph_get_result
        listing.return_value = [
            {"id": "ig-part-2", "caption": "Yoksul 1986 Part 2", "permalink": "https://ig.test/2", "timestamp": "t2"},
            {"id": "ig-part-3", "caption": "Yoksul_1986_Part_3", "permalink": "https://ig.test/3", "timestamp": "t3"},
        ]
        auth = {"pages": [
            {"page_name": "Film Mağarası", "page_id": "1239298989276639", "instagram_id": "ig-film", "page_token": "secret1"},
            {"page_name": "Filmmagrasi", "page_id": "854990964375370", "page_token": "secret2"},
        ]}

        result = audit_film_publications(auth, drive)
        self.assertFalse(result["publishing_performed"])
        self.assertFalse(result["drive_mutations_performed"])
        self.assertEqual(result["film_active_key"], "Yoksul_1986")
        self.assertEqual(
            [row["part"] for row in result["selected_part_audits"]],
            [1, 2, 3, 4, 5, 6, 10],
        )
        part3 = next(row for row in result["selected_part_audits"] if row["file_id"] == "1IJloVdio5n6NY4UpxQTgIps7peZ8dv7c")
        self.assertEqual([row["status"] for row in part3["facebook"]], ["verified", "verified"])
        self.assertTrue(part3["instagram"]["caption_candidates"])
        part5 = next(row for row in result["selected_part_audits"] if row["file_id"] == "1FlxhrUoqtmpNGU68C-8HNVJCcRy2KBdx")
        self.assertEqual([row["status"] for row in part5["facebook"]], ["no_recorded_id", "no_recorded_id"])
        self.assertEqual(part5["instagram"]["id_matches"], [])
        self.assertEqual(part5["instagram"]["caption_candidates"], [])
        part6 = next(row for row in result["selected_part_audits"] if row["part"] == 6)
        self.assertEqual(part6["state"]["intent_ig_slot"], "manual-p6")
        part10 = next(row for row in result["selected_part_audits"] if row["part"] == 10)
        self.assertEqual(part10["state"]["failure_ig_count"], "3")
        drive.files().update.assert_not_called()
        self.assertNotIn("secret1", str(result))
        self.assertNotIn("secret2", str(result))

    @patch("meta_connection_audit.graph_get")
    @patch("meta_connection_audit.graph_list")
    def test_film_publication_audit_fails_closed_when_file_id_or_name_mismatches(self, listing, get):
        from ordered_channels import FILM_FOLDER_ID

        drive = Mock()
        drive.files().get().execute.return_value = {"id": FILM_FOLDER_ID, "appProperties": {}}
        drive.files().list().execute.return_value = {"files": [
            {"id": "wrong-id", "name": "Yoksul_1986_Part_2.mp4", "parents": [FILM_FOLDER_ID]}
        ]}
        with self.assertRaises(Exception):
            audit_film_publications({"pages": [
                {"page_name": "Film Mağarası", "page_id": "1239298989276639",
                 "instagram_id": "ig-film", "page_token": "secret1"},
                {"page_name": "Filmmagrasi", "page_id": "854990964375370", "page_token": "secret2"},
            ]}, drive)
        get.assert_not_called()
        listing.assert_not_called()
        drive.files().update.assert_not_called()

    @patch("meta_connection_audit.graph_get")
    @patch("meta_connection_audit.graph_list")
    def test_film_publication_audit_rejects_duplicate_canonical_part_numbers(self, listing, get):
        from ordered_channels import FILM_FOLDER_ID

        drive = Mock()
        drive.files().get().execute.return_value = {
            "id": FILM_FOLDER_ID, "appProperties": {"film_active_key": "Yoksul_1986"},
        }
        drive.files().list().execute.return_value = {"files": [
            {"id": file_id, "name": name, "mimeType": "video/mp4", "parents": [FILM_FOLDER_ID]}
            for name, file_id in FILM_AUDIT_FILES.items()
        ] + [
            {"id": "duplicate-part-5", "name": "Yoksul_1986_Part_5.mp4", "mimeType": "video/mp4",
             "parents": [FILM_FOLDER_ID]},
        ]}

        with self.assertRaisesRegex(Exception, "film_yoksul_duplicate_part_number"):
            audit_film_publications({"pages": [
                {"page_name": "Film Mağarası", "page_id": "1239298989276639",
                 "instagram_id": "ig-film", "page_token": "secret1"},
                {"page_name": "Filmmagrasi", "page_id": "854990964375370", "page_token": "secret2"},
            ]}, drive)
        get.assert_not_called()
        listing.assert_not_called()
        drive.files().update.assert_not_called()

    @patch("meta_connection_audit.graph_get")
    @patch("meta_connection_audit.graph_list")
    def test_exact_accounts_and_permissions_pass_without_publish(self, listing, get):
        listing.return_value = [
            {"id":"1239298989276639","name":"Film Mağarası","instagram_business_account":{"id":"i1","username":"film_magrasi"}},
            {"id":"854990964375370","name":"Filmmagrasi"},
            {"id":"p3","name":"ToonZone","instagram_business_account":{"id":"i3","username":"toonzone.tr"}},
            {"id":"p4","name":"Daily Laugh Lab","instagram_business_account":{"id":"i4","username":"daily.laughlab"}},
            {"id":"excluded","name":"Dizimaratonu"},
        ]
        get.return_value={"data":[{"permission":p,"status":"granted"} for p in REQUIRED_PERMISSIONS]}
        auth={"pages":[
            # Saved labels may be stale or differently accented; IDs are authoritative.
            {"page_name":"Film Mağrası","page_id":"1239298989276639","instagram_id":"i1","page_token":"x"},
            {"page_name":"Filmmağrası1","page_id":"854990964375370","page_token":"x"},
            {"page_name":"ToonZone","page_id":"p3","instagram_id":"i3","page_token":"x"},
            {"page_name":"Daily Laugh Lab","page_id":"p4","instagram_id":"i4","page_token":"x"},
        ]}
        result=audit_meta("secret",auth)
        self.assertTrue(result["required_permissions_complete"])
        self.assertTrue(all(x["status"]=="passed" for x in result["accounts"]))
        self.assertFalse(result["publishing_performed"])

    @patch("meta_connection_audit.graph_get", return_value={"data":[]})
    @patch("meta_connection_audit.graph_list", return_value=[])
    def test_missing_accounts_and_permissions_fail_closed(self, _listing, _get):
        result=audit_meta("secret",{"pages":[]})
        self.assertFalse(result["required_permissions_complete"])
        self.assertTrue(all(x["status"]=="blocked" for x in result["accounts"]))

    @patch("meta_connection_audit.graph_get")
    @patch("meta_connection_audit.graph_list")
    def test_film_identity_uses_page_id_when_meta_display_name_differs(self, listing, get):
        listing.return_value = [
            {"id":"1239298989276639","name":"Film Mağarası",
             "instagram_business_account":{"id":"i-film","username":"film_magrasi"}},
            {"id":"854990964375370","name":"Filmmagrasi"},
            {"id":"p3","name":"ToonZone","instagram_business_account":{"id":"i3"}},
            {"id":"p4","name":"Daily Laugh Lab","instagram_business_account":{"id":"i4"}},
        ]
        get.return_value={"data":[{"permission":p,"status":"granted"} for p in REQUIRED_PERMISSIONS]}
        auth={"pages":[
            {"page_name":"Eski Film Etiketi","page_id":"1239298989276639","instagram_id":"i-film","page_token":"x"},
            {"page_name":"Eski İkinci Etiket","page_id":"854990964375370","page_token":"y"},
            {"page_name":"ToonZone","page_id":"p3","instagram_id":"i3","page_token":"z"},
            {"page_name":"Daily Laugh Lab","page_id":"p4","instagram_id":"i4","page_token":"w"},
        ]}
        result=audit_meta("secret",auth)
        film_rows={row["page_name"]:row for row in result["accounts"]}
        self.assertEqual(film_rows["Film Mağarası"]["status"],"passed")
        self.assertEqual(film_rows["Filmmagrasi"]["status"],"passed")


if __name__ == "__main__": unittest.main()
