import unittest
from telegram_status_evidence import status_evidence

class StatusEvidenceTests(unittest.TestCase):
    def test_only_real_done_posts_and_unresolved(self):
        state={"schema":1,"entries":{
            "film:facebook:one":{"route":"film","platform":"facebook","file":"Bickin_Part_1.mp4","status":"done","post_id":"111","day":"2026-11-02"},
            "film:facebook:two":{"route":"film","platform":"facebook","file":"Bickin_Part_2.mp4","status":"uncertain","day":"2026-11-02"},
            "film:facebook:three":{"route":"film","platform":"facebook","file":"Bickin_Part_3.mp4","status":"ready","failure":{"reason":"prepare"}},
        }}
        s=status_evidence(state)
        self.assertIn("111",s)
        self.assertIn("Belirsiz/bekleyen kayıt: 1",s)
        self.assertIn("hazırlık hatası: 1",s)
        self.assertIn("eksik [2, 3]",s)
        self.assertNotIn("222",s)

    def test_unavailable_fails_closed(self):
        self.assertIn("N/A",status_evidence(None))

if __name__=="__main__":
    unittest.main()
