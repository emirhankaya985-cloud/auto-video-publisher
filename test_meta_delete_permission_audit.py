import unittest
from unittest.mock import Mock

from meta_delete_permission_audit import API, REQUIRED, audit


class MetaDeletePermissionAuditTests(unittest.TestCase):
    def test_reports_only_granted_required_scopes(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": [
            {"permission": name, "status": "granted"} for name in REQUIRED
        ]}
        get = Mock(return_value=response)
        result = audit("never-print-this", get=get)
        self.assertEqual(result["status"], "required_scopes_granted")
        self.assertTrue(all(result["permissions"].values()))
        get.assert_called_once_with(API, headers={"Authorization": "Bearer never-print-this"},
                                    timeout=20, allow_redirects=False)

    def test_missing_delete_scope_is_not_granted(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": [
            {"permission": name, "status": "granted"}
            for name in REQUIRED if name != "instagram_manage_contents"
        ]}
        result = audit("token", get=Mock(return_value=response))
        self.assertEqual(result["status"], "scopes_missing")
        self.assertFalse(result["permissions"]["instagram_manage_contents"])

    def test_refuses_missing_token_without_network(self):
        get = Mock()
        result = audit("", get=get)
        self.assertEqual(result["status"], "blocked")
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
