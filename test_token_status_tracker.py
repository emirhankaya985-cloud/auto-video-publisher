import json
import tempfile
import unittest
from pathlib import Path

from token_status_tracker import (
    build_inventory, expiry_warning_threshold, account_summary,
)


class TokenStatusTrackerTests(unittest.TestCase):
    def test_expiry_thresholds_only_use_provider_supplied_integer_days(self):
        self.assertEqual([expiry_warning_threshold(n) for n in (30, 20, 15, 8, 7, 3, 1, 0)],
                         [30, 30, 15, 15, 7, 3, 1, 0])
        self.assertIsNone(expiry_warning_threshold(None))
        self.assertIsNone(expiry_warning_threshold("7"))

    def test_status_inventory_is_redacted_and_never_infers_expiry(self):
        secret_value = "TOKEN_DO_NOT_SERIALIZE"
        env = {
            "META_ACCESS_TOKEN": secret_value,
            "TARLADAKI_THREADS_ACCESS_TOKEN": secret_value,
            "PENGUEN_THREADS_ACCESS_TOKEN": secret_value,
            "GONLE_THREADS_ACCESS_TOKEN": secret_value,
            "DAILY_LAUGH_THREADS_ACCESS_TOKEN": secret_value,
            "FILM_THREADS_ACCESS_TOKEN": secret_value,
            "TOONZONE_THREADS_ACCESS_TOKEN": secret_value,
        }
        snapshot = {
            ("🌱 Tarladaki Fasulye", "Facebook"): {},
            ("🌱 Tarladaki Fasulye", "Instagram"): {},
            ("🐧 Beyinsiz Penguen", "Facebook"): None,
            ("🐧 Beyinsiz Penguen", "Instagram"): None,
            ("🐧 Beyinsiz Penguen", "Threads"): None,
        }
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / "history.jsonl"
            history.write_text(json.dumps({
                "account": "🐧 Beyinsiz Penguen", "platform": "Facebook",
                "metric": "snapshot_status", "status": "ok",
                "measured_at": "2026-11-24T23:59:00+03:00",
            }) + "\n", encoding="utf-8")
            inventory = build_inventory(
                snapshot=snapshot,
                errors=["🐧 Beyinsiz Penguen / Facebook: HTTP 401 code=190"],
                measured_at="2026-11-25T23:59:00+03:00", history_path=history,
                environ=env,
            )
        data = json.dumps(inventory, ensure_ascii=False)
        self.assertNotIn(secret_value, data)
        self.assertIn('"connection_status": "VERIFIED_WORKING"', data)
        self.assertIn('"connection_status": "ACTION_REQUIRED"', data)
        self.assertIn('"expires_at_utc": null', data)
        self.assertIn('"days_remaining": null', data)
        penguin_fb = next(row for row in inventory["connections"]
                          if row["account"] == "🐧 Beyinsiz Penguen" and row["platform"] == "Facebook")
        self.assertEqual(penguin_fb["last_successful_validation_at"], "2026-11-24T23:59:00+03:00")
        self.assertEqual(penguin_fb["publish_permission"], "NOT_TESTED")

    def test_explicit_api_expiry_produces_warning_window(self):
        inventory = build_inventory(
            snapshot={("🌱 Tarladaki Fasulye", "Facebook"): {}}, errors=[],
            measured_at="2026-11-25T00:00:00Z",
            meta_expiry_metadata={"META_PAGE_TOKEN:tarladaki": "2026-12-25T00:00:00Z"},
            environ={"META_ACCESS_TOKEN": "value"},
        )
        row = next(item for item in inventory["connections"] if item["platform"] == "Facebook")
        self.assertEqual(row["days_remaining"], 30)
        self.assertEqual(row["expiry_warning_days"], 30)

    def test_summary_lists_six_accounts_with_publish_permission_separate(self):
        inventory = build_inventory(snapshot={}, errors=[], measured_at="2026-11-25T00:00:00Z", environ={})
        lines = account_summary(inventory)
        self.assertEqual(len([line for line in lines if line.startswith("• ")]), 6)
        self.assertIn("Film Mağarası", "\n".join(lines))
        self.assertNotIn("Film Second", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
