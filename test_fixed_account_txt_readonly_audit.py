"""Pure tests for per-account original TXT, including shared Humor Drive."""
import hashlib
import unittest

import fixed_account_txt_readonly_audit as audit
from account_fixed_txt import FIXED_FILES


class FixedTxtEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folders = {"humor": "H", "gonle": "G", "daily_laugh": "D"}
        self.keys = {name: f"DriveFileOwner{i:03d}abcdefghijklmn"
                     for i, (route, (_prefix, name)) in enumerate(FIXED_FILES.items())}
        self.texts = {name: f"Owner-approved static caption for {name}"
                      for name in self.keys}
        self.catalog = {
            "H": {name: {"id": self.keys[name]} for name in
                  ("Tarladaki_Fasulye_ACCOUNT.txt", "Beyinsiz_Penguen_ACCOUNT.txt")},
            "G": {"Gonle_Dusen_ACCOUNT.txt": {"id": self.keys["Gonle_Dusen_ACCOUNT.txt"]}},
            "D": {"Daily_Laugh_Lab_ACCOUNT.txt": {"id": self.keys["Daily_Laugh_Lab_ACCOUNT.txt"]}},
        }
        self.listed = []
        self.downloaded = []

    def inv(self, folder):
        self.listed.append(folder)
        return self.catalog[folder]

    def dl(self, file_id, path):
        self.downloaded.append(file_id)
        for name, did in self.keys.items():
            if file_id == did:
                path.write_text(self.texts[name], encoding="utf-8")
                return path
        raise AssertionError("unknown Drive file")

    def pinned_env(self):
        return {f"FIXED_{prefix}_TXT_SHA256":
                hashlib.sha256(self.texts[name].encode("utf-8")).hexdigest()
                for route, (prefix, name) in FIXED_FILES.items()}

    def test_owner_evidence_only_and_two_humor_files_are_isolated(self):
        out = audit.audit(folders=self.folders, inventory_fn=self.inv,
                          download_fn=self.dl, environ=self.pinned_env())
        self.assertEqual(out["status"], "verified_all")
        self.assertEqual(out["verified_files"], 4)
        self.assertEqual(len(self.downloaded), 4)
        self.assertEqual(self.listed.count("H"), 1)
        self.assertFalse(out["safe_to_enable_without_owner_review"])
        self.assertEqual(out["publishes"], 0)
        self.assertNotIn(self.texts["Daily_Laugh_Lab_ACCOUNT.txt"], str(out))

    def test_missing_file_cannot_fallback_to_another_account(self):
        self.catalog["H"].pop("Beyinsiz_Penguen_ACCOUNT.txt")
        out = audit.audit(folders=self.folders, inventory_fn=self.inv,
                          download_fn=self.dl, environ=self.pinned_env())
        row = next(x for x in out["rows"] if x["route"] == "penguen")
        self.assertEqual(row["status"], "owner_fixed_txt_not_present")
        self.assertEqual(out["verified_files"], 3)
        self.assertEqual(len(self.downloaded), 3)

    def test_wrong_account_txt_is_sha_mismatch_and_not_enabled(self):
        self.texts["Beyinsiz_Penguen_ACCOUNT.txt"] = self.texts["Tarladaki_Fasulye_ACCOUNT.txt"]
        out = audit.audit(folders=self.folders, inventory_fn=self.inv,
                          download_fn=self.dl, environ=self.pinned_env() | {
                          "FIXED_PENGUEN_TXT_SHA256": hashlib.sha256(b"expected owner caption").hexdigest()})
        row = next(x for x in out["rows"] if x["route"] == "penguen")
        self.assertEqual(row["status"], "sha256_pin_mismatch")
        self.assertFalse(out["safe_to_enable_without_owner_review"])

    def test_unpinned_text_not_treated_as_active(self):
        out = audit.audit(folders=self.folders, inventory_fn=self.inv,
                          download_fn=self.dl, environ={})
        self.assertEqual(out["verified_files"], 0)
        self.assertTrue(all(x["status"] == "sha256_pin_not_configured" for x in out["rows"]))

    def test_inventory_failure_is_unavailable_not_missing(self):
        def unavailable(folder):
            if folder == "H":
                raise OSError("secret provider body should not leak")
            return self.catalog[folder]
        out = audit.audit(folders=self.folders, inventory_fn=unavailable,
                          download_fn=self.dl, environ=self.pinned_env())
        self.assertEqual([x["status"] for x in out["rows"][:2]],
                         ["folder_inventory_unavailable", "folder_inventory_unavailable"])
        self.assertNotIn("secret provider body", str(out))


if __name__ == "__main__":
    unittest.main()
