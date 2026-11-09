"""Offline invariants for seven isolated Meta account workers."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from merge_account_states import merge_account_states, read_scoped_results
from public_link_runtime import account_scope, owned_humor_source


def state(entries=None):
    return {"schema": 1, "entries": entries or {}, "episode_days": {}}


class IsolatedAccountTests(unittest.TestCase):
    def test_invalid_scope_fails_closed(self):
        with patch.dict("os.environ", {"PUBLISH_ACCOUNT_SCOPE": "unknown"}):
            with self.assertRaises(RuntimeError):
                account_scope()

    def test_explicit_scope(self):
        with patch.dict("os.environ", {"PUBLISH_ACCOUNT_SCOPE": "film"}):
            self.assertEqual(account_scope(), "film")

    def test_shared_humor_drive_files_are_disjoint(self):
        for i in range(100):
            f = "drive-id-" + str(i)
            self.assertNotEqual(owned_humor_source("tarladaki", f),
                                owned_humor_source("penguen", f))
            self.assertEqual(owned_humor_source("tarladaki", f),
                             owned_humor_source("tarladaki", f))

    def test_failed_film_cannot_erase_toonzone(self):
        base = state({"toonzone:facebook:x": {
            "route": "toonzone", "platform": "facebook", "status": "done", "post_id": "10"},
            "film:instagram:z": {"route": "film", "platform": "instagram",
                                  "status": "uncertain"}})
        film = state({"toonzone:facebook:x": {
            "route": "toonzone", "platform": "facebook", "status": "uncertain"},
            "film:instagram:z": {"route": "film", "platform": "instagram",
                                 "status": "ready"}})
        merged = merge_account_states(base, {"film": film})
        self.assertEqual(merged["entries"]["toonzone:facebook:x"]["post_id"], "10")
        self.assertEqual(merged["entries"]["film:instagram:z"]["status"], "ready")

    def test_reports_merge_disjoint_route_results(self):
        base = state()
        one = state({"film:facebook:1": {"route": "film", "status": "uncertain"}})
        two = state({"toonzone:instagram:2": {"route": "toonzone",
                                               "status": "done", "post_id": "42"}})
        merged = merge_account_states(base, {"film": one, "toonzone": two})
        self.assertEqual(len(merged["entries"]), 2)
        self.assertEqual(merged["entries"]["toonzone:instagram:2"]["post_id"], "42")

    def test_foreign_or_corrupt_scope_rejected(self):
        with self.assertRaises(ValueError):
            merge_account_states(state(), {"unknown": state()})
        with self.assertRaises(ValueError):
            merge_account_states(state(), {"film": state({"wrong:x": {
                "route": "film", "status": "done"}})})

    def test_result_wins_over_intent_per_account(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for kind, status in (("intent", "intent"), ("result", "done")):
                p = root / ("link-state-" + kind + "-film") / "link-runtime" / "state.json"
                p.parent.mkdir(parents=True)
                p.write_text(json.dumps(state({"film:facebook:1": {
                    "route": "film", "status": status}})), encoding="utf-8")
            selected = read_scoped_results(root)
            self.assertEqual(selected["film"]["entries"]["film:facebook:1"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
