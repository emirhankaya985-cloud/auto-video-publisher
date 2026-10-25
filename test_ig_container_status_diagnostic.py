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
    def test_source_has_no_write_functions(self):
        from pathlib import Path
        src = Path(diag.__file__).read_text()
        self.assertNotIn("requests.post(", src)
        self.assertNotIn("media_publish(", src)
        self.assertNotIn("requests.put(", src)

if __name__ == "__main__":
    unittest.main()
