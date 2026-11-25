import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, Mock

import ntfy_smoke_test


class SmokeTests(unittest.TestCase):
    def test_live_smoke_workflow_is_manual_and_uses_active_gate(self):
        workflow = (Path(__file__).parent / ".github" / "workflows" /
                    "ntfy_server_smoke.yml").read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:\n", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertIn("if: vars.LINK_AUTOMATION_ENABLED == 'true'", workflow)
        self.assertNotIn("vars.AUTOMATION_ENABLED", workflow)

    def test_missing_config_does_not_send(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "ntfy_smoke_test.send_ntfy"
        ) as sender, redirect_stdout(output):
            result = ntfy_smoke_test.main()
        self.assertEqual(result, 1)
        self.assertIn("ntfy_secret_missing", output.getvalue())
        sender.assert_not_called()

    def test_good_receipt_is_reported_not_phone_delivery(self):
        output = io.StringIO()
        with patch.dict(os.environ, {
            "NTFY_TOPIC_URL": "https://ntfy.sh/very-secret",
            "GITHUB_RUN_ID": "123",
        }, clear=True), patch(
            "ntfy_smoke_test.send_ntfy",
            return_value={"http_status": 200, "server_ack": True}
        ) as sender, redirect_stdout(output):
            result = ntfy_smoke_test.main()
        self.assertEqual(result, 0)
        self.assertTrue(sender.call_args.kwargs["require_ack"])
        self.assertEqual(sender.call_count, 1)
        self.assertIn('"phone_delivery_verified": false', output.getvalue())
        self.assertNotIn("very-secret", output.getvalue())

    def test_error_never_prints_private_topic(self):
        output = io.StringIO()
        with patch.dict(os.environ, {
            "NTFY_TOPIC_URL": "https://ntfy.sh/very-secret",
        }, clear=True), patch(
            "ntfy_smoke_test.send_ntfy",
            side_effect=RuntimeError("https://ntfy.sh/very-secret")
        ), redirect_stdout(output):
            result = ntfy_smoke_test.main()
        self.assertEqual(result, 1)
        self.assertNotIn("very-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
