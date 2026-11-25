"""Safe dashboard identity bridge: no writes and no label-only acceptance."""
import unittest
from meta_identity_panel_proof import verify

class IdentityProofTests(unittest.TestCase):
    def test_complete_verified_page_and_instagram_pairs(self):
        from stats_reporter import META_TARGETS
        pages={label:{"page_id":str(100000000000000+i),
                      "page_name":label,
                      "instagram_id":str(200000000000000+i),
                      "page_token":"PRIVATE_NOT_PRINTED"}
               for i,label in enumerate(sorted({z[1] for z in META_TARGETS}))}
        def check(row):
            return {"status":"identity_verified","instagram_identity_checked":True}
        result=verify({"pages":list(pages.values())},check=check)
        self.assertEqual(result["status"],"verified_all")
        self.assertEqual(result["expected"],13)
        self.assertEqual(result["verified"],13)
        self.assertTrue(all(x["status"]=="identity_verified" for x in result["identities"]))
        self.assertNotIn("PRIVATE_NOT_PRINTED",str(result))
        self.assertFalse(result["publishing_performed"])
        self.assertFalse(result["crm_mutated"])
    def test_rejected_page_not_assigned_to_unrelated_label(self):
        result=verify({"pages":[{"page_name":"ToonZone",
                 "page_id":"123456789123456","instagram_id":"67890123456789",
                 "page_token":"PRIVATE"}]},
                 check=lambda p:{"status":"blocked","reason":"page_id_mismatch"})
        self.assertEqual(result["verified"],0)
        self.assertEqual(result["status"],"verified_partial")
        self.assertNotIn("PRIVATE",str(result))
    def test_duplicate_or_missing_ig_id_not_marked_verified(self):
        x={"page_name":"ToonZone","page_id":"1298191963387372",
           "page_token":"PRIVATE"}
        result=verify({"pages":[x]},check=lambda p:{"status":"identity_verified",
                         "instagram_identity_checked":False})
        rows=[r for r in result["identities"] if r["page"]=="ToonZone"]
        self.assertEqual(rows[0]["status"],"identity_verified")
        self.assertEqual(rows[1]["status"],"unverified")
    def test_unknown_config_never_accepted(self):
        self.assertEqual(verify({"pages":None})["status"],"blocked")
    def test_two_labels_claiming_same_page_fail_closed(self):
        from stats_reporter import META_TARGETS
        rows=[{"page_name":name,"page_id":"12345678912345",
               "instagram_id":str(50000000000+i),"page_token":"PRIVATE"}
              for i,name in enumerate(sorted({t[1] for t in META_TARGETS}))]
        result=verify({"pages":rows},
            check=lambda r:{"status":"identity_verified","instagram_identity_checked":True})
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(result["identities"],[])
if __name__=="__main__":
    unittest.main()
