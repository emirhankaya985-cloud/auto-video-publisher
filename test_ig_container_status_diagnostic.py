import unittest
from unittest.mock import Mock
import ig_container_status_diagnostic as diag

class ReadOnlyIGTests(unittest.TestCase):
    def test_film_read_is_get_only_and_redacted(self):
        pid, ig, cid = diag.PINNED["film_part16"]
        page = [{"page_id":pid, "instagram_id":ig, "page_token":"SENSITIVE"}]
        response = Mock(status_code=200)
        response.json.return_value = {"id":cid, "status_code":"ERROR", "status":"ProcessingFailed"}
        get = Mock(return_value=response)
        result = diag.inspect(page, "film_part16", get=get)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["posts_sent"], 0)
        self.assertNotIn("SENSITIVE", str(result))
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
    def test_wrong_ig_identity_has_no_network(self):
        pid, ig, cid = diag.PINNED["toonzone_part3"]
        get = Mock()
        self.assertEqual(diag.inspect([{"page_id":pid, "instagram_id":"wrong",
            "page_token":"SENSITIVE"}], "toonzone_part3", get=get)["status"], "BLOCKED")
        get.assert_not_called()
    def test_meta_error_never_exposes_body_or_token(self):
        pid, ig, cid = diag.PINNED["toonzone_part3"]
        response = Mock(status_code=400)
        response.json.return_value = {"error": {"code":100, "message":"TOKEN-PASSWORD"}}
        result = diag.inspect([{"page_id":pid, "instagram_id":ig,
             "page_token":"SENSITIVE"}], "toonzone_part3", get=Mock(return_value=response))
        self.assertEqual(result["graph_code"],100)
        self.assertNotIn("TOKEN-PASSWORD",str(result))
        self.assertNotIn("SENSITIVE",str(result))
    def test_daily_check_keeps_strict_read_only_workflow(self):
        from pathlib import Path
        workflow = Path(".github/workflows/ig_container_status_diagnostic.yml").read_text()
        self.assertIn("cron: '18 6 * * *'", workflow)
        self.assertIn("python ig_container_status_diagnostic.py", workflow)
        self.assertIn("if: github.event_name != 'pull_request'", workflow)
        self.assertNotIn("python public_link_runtime.py publish", workflow)

    def test_exact_named_containers_verify_live_page_before_read(self):
        for key, (name, cid) in diag.NAMED_PINNED.items():
            with self.subTest(key=key):
                page = {"page_name": name, "page_id": "12345", "instagram_id": "67890", "page_token": "SECRET"}
                identity = Mock(ok=True, status_code=200)
                identity.json.return_value = {"id": "12345", "name": name, "instagram_business_account": {"id": "67890"}}
                status = Mock(status_code=200)
                status.json.return_value = {"id": cid, "status_code": "EXPIRED", "status": "SECRET"}
                get = Mock(side_effect=[identity, status])
                result = diag.inspect_named([page], key, get=get)
                self.assertEqual(result["status"], "EXPIRED")
                self.assertEqual(result["posts_sent"], 0)
                self.assertEqual(get.call_count, 2)
                self.assertTrue(get.call_args_list[0].args[0].endswith("/12345"))
                self.assertTrue(get.call_args_list[1].args[0].endswith("/" + cid))
                self.assertNotIn("SECRET", str(result))

    def test_wrong_named_page_identity_never_reads_container(self):
        key = "tarladaki_192_nov01"
        name, cid = diag.NAMED_PINNED[key]
        page = {"page_name": name, "page_id": "12345", "instagram_id": "67890", "page_token": "SECRET"}
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"id": "WRONG", "name": name}
        get = Mock(return_value=response)
        result = diag.inspect_named([page], key, get=get)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(get.call_count, 1)
        self.assertNotIn("SECRET", str(result))

    def test_source_has_no_write_functions(self):
        from pathlib import Path
        src = Path(diag.__file__).read_text()
        self.assertNotIn("requests.post(", src)
        self.assertNotIn("media_publish(", src)
        self.assertNotIn("requests.put(", src)

if __name__ == "__main__":
    unittest.main()
