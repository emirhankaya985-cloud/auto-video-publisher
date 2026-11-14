import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notification_dedup as dedup


class NotificationDedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = patch.object(dedup, "LEDGER", Path(self.tmp.name) / "ledger.json")
        self.ledger.start()
        self.addCleanup(self.ledger.stop)
        self.addCleanup(self.tmp.cleanup)
        self.db_url = patch.dict("os.environ", {}, clear=True)
        self.db_url.start()
        self.addCleanup(self.db_url.stop)

    def test_failed_delivery_is_retryable_but_acknowledged_incident_is_deduplicated(self):
        key = "social-report|failure"
        self.assertTrue(dedup.should_send(key))
        dedup.mark_result(key, False, "network")
        self.assertTrue(dedup.should_send(key))
        dedup.mark_result(key, True)
        self.assertFalse(dedup.should_send(key))
        dedup.resolve(key)
        self.assertTrue(dedup.should_send(key))


if __name__ == "__main__":
    unittest.main()
