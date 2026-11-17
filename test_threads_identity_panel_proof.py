"""No API / no publisher tests for live Threads identity evidence."""
import unittest
from threads_identity_panel_proof import audit,ROUTE_NAMES


class PanelThreadsIdentityProofTests(unittest.TestCase):
    def test_five_verifiable_accounts_survive_penguen_401_without_fallback(self):
        def check(route):
            if route=="penguen":
                raise RuntimeError("401 text might contain secret--MUST NOT LEAK")
            return {"id":str(100000000000000+list(ROUTE_NAMES).index(route)),
                    "username":route}
        data=audit(probe=check)
        self.assertEqual(data["status"],"verified_partial")
        self.assertEqual(data["verified"],5)
        self.assertEqual(data["expected"],6)
        self.assertNotIn("MUST NOT LEAK",str(data))
        self.assertFalse(data["publishing_performed"])
        self.assertFalse(data["crm_mutated"])
        self.assertEqual(next(x for x in data["identities"] if x["route"]=="penguen")["status"],"unverified")
    def test_duplicate_provider_id_is_global_fail_closed(self):
        result=audit(probe=lambda route:{"id":"12345678912345","username":route})
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(result["identities"],[])
    def test_non_numeric_id_never_accepted(self):
        result=audit(probe=lambda route:{"id":"unexpected-PRIVATE-id"})
        self.assertEqual(result["verified"],0)
        self.assertEqual(result["status"],"verified_partial")
        self.assertNotIn("PRIVATE",str(result))


if __name__=="__main__":
    unittest.main()
