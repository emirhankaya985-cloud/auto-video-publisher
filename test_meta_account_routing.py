import unittest
from unittest.mock import Mock, patch

from cloud_omnichannel_publisher import get_meta_page_info


def response(payload):
    item = Mock()
    item.raise_for_status.return_value = None
    item.json.return_value = payload
    return item


class MetaAccountRoutingTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            "pages": [{
                "page_id": "page-penguen",
                "page_name": "Beyinsiz Penguen",
                "page_token": "saved-page-token",
                "instagram_id": "ig-penguen",
            }]
        }

    def test_exact_saved_account_name_is_required(self):
        changed = {"pages": [{**self.saved["pages"][0], "page_name": "Kova Post"}]}
        with patch("cloud_omnichannel_publisher.get_meta_auth", return_value=changed), patch.dict(
            "os.environ", {"META_ACCESS_TOKEN": ""}, clear=True
        ), self.assertRaisesRegex(RuntimeError, "tam hesap kimliği"):
            get_meta_page_info("Beyinsiz Penguen")

    def test_live_page_and_instagram_ids_must_match_allowlist(self):
        live = {"data": [{
            "id": "wrong-page", "name": "Beyinsiz Penguen", "access_token": "live-token",
            "instagram_business_account": {"id": "ig-penguen", "username": "penguen"},
        }]}
        with patch("cloud_omnichannel_publisher.get_meta_auth", return_value=self.saved), patch.dict(
            "os.environ", {"META_ACCESS_TOKEN": "user-token"}, clear=True
        ), patch("cloud_omnichannel_publisher.requests.get", return_value=response(live)), self.assertRaisesRegex(
            RuntimeError, "sayfa kimliği"
        ):
            get_meta_page_info("Beyinsiz Penguen")

    def test_verified_ids_return_the_live_account(self):
        live = {"data": [{
            "id": "page-penguen", "name": "Beyinsiz Penguen", "access_token": "live-token",
            "instagram_business_account": {"id": "ig-penguen", "username": "penguen"},
        }]}
        with patch("cloud_omnichannel_publisher.get_meta_auth", return_value=self.saved), patch.dict(
            "os.environ", {"META_ACCESS_TOKEN": "user-token"}, clear=True
        ), patch("cloud_omnichannel_publisher.requests.get", return_value=response(live)):
            page = get_meta_page_info("Beyinsiz Penguen")
        self.assertEqual(page["page_id"], "page-penguen")
        self.assertEqual(page["instagram_id"], "ig-penguen")

    def test_film_page_uses_id_and_follows_me_accounts_pagination(self):
        configured = {"pages": [{
            "page_id": "1239298989276639", "page_name": "Film Mağrası",
            "page_token": "saved-page-token", "instagram_id": "ig-film",
        }]}
        first = response({"data": [{"id": "other", "name": "Other", "access_token": "x"}],
                          "paging": {"next": "opaque", "cursors": {"after": "cursor-2"}}})
        second = response({"data": [{
            "id": "1239298989276639", "name": "Film Mağarası", "access_token": "live-token",
            "instagram_business_account": {"id": "ig-film", "username": "film_magrasi"},
        }]})
        with patch("cloud_omnichannel_publisher.get_meta_auth", return_value=configured), patch.dict(
            "os.environ", {"META_ACCESS_TOKEN": "user-token"}, clear=True
        ), patch("cloud_omnichannel_publisher.requests.get", side_effect=[first, second]) as get:
            page = get_meta_page_info("Film Mağarası")
        self.assertEqual(page["page_id"], "1239298989276639")
        self.assertEqual(page["page_name"], "Film Mağarası")
        self.assertEqual(get.call_count, 2)

    def test_film_second_page_alias_resolves_by_id(self):
        configured = {"pages": [{
            "page_id": "854990964375370", "page_name": "Filmmağrası1", "page_token": "saved-page-token",
        }]}
        live = response({"data": [{
            "id": "854990964375370", "name": "Filmmagrasi", "access_token": "live-token",
        }]})
        with patch("cloud_omnichannel_publisher.get_meta_auth", return_value=configured), patch.dict(
            "os.environ", {"META_ACCESS_TOKEN": "user-token"}, clear=True
        ), patch("cloud_omnichannel_publisher.requests.get", return_value=live):
            page = get_meta_page_info("Filmmagrasi")
        self.assertEqual(page["page_id"], "854990964375370")


if __name__ == "__main__":
    unittest.main()
