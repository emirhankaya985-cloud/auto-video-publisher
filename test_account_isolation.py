"""Offline account-worker safety tests: no live Meta or Drive calls."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from test_public_link_runtime import runtime


class AccountIsolationTests(unittest.TestCase):
    def test_unknown_account_route_is_fail_closed(self):
        with patch.dict(os.environ, {"ACCOUNT_ROUTE": "film_typo"}):
            with self.assertRaisesRegex(RuntimeError, "Unknown ACCOUNT_ROUTE"):
                runtime.selected_account_route()

    def test_isolated_worker_only_plans_selected_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = {"schema": 1, "entries": {}, "episode_days": {}}
            routes = {"gonle": ("gonle", "Gönle Düşen"),
                      "film": ("film", "Film Mağarası")}
            with patch.dict(os.environ, {
                "ACCOUNT_ROUTE": "film",
                "GITHUB_RUN_ID": "offline-only",
                "ADAPTIVE_SCHEDULE_ENABLED": "false",
                "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
            }), patch.object(runtime, "ROOT", root), \
                 patch.object(runtime, "STATE", root / "state.json"), \
                 patch.object(runtime, "PLAN", root / "plan.json"), \
                 patch.object(runtime, "ROUTES", routes), \
                 patch.object(runtime, "FOLDERS", {"gonle": "x", "film": "y"}), \
                 patch.object(runtime, "restore", return_value=state), \
                 patch.object(runtime, "apply_verified_migration"), \
                 patch.object(runtime, "quarantine_weak_caption_aliases"), \
                 patch.object(runtime, "preflight_verified_pages", return_value=None), \
                 patch.object(runtime, "load_meta_auth", return_value={
                     "pages": [{"page_name": n} for _, n in routes.values()]}), \
                 patch.object(runtime, "inventory", return_value={}), \
                 patch.object(runtime, "prioritized_route_items",
                              return_value=[("gonle", routes["gonle"]), ("film", routes["film"])]), \
                 patch.object(runtime, "route_enabled", return_value=False) as enabled, \
                 patch("content_stock.build_stock", return_value={}), \
                 patch("content_stock.stock_markdown", return_value=""):
                runtime.plan()
            self.assertEqual([call.args[0] for call in enabled.call_args_list], ["film"])
            self.assertEqual(json.loads((root / "plan.json").read_text()), [])
            self.assertNotIn("## Gönle Düşen", (root / "report.md").read_text())
            self.assertIn("## Film Mağarası", (root / "report.md").read_text())

    def test_cross_account_intent_never_reaches_meta_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state.json").write_text(json.dumps({"schema": 1, "entries": {}}))
            (root / "plan.json").write_text(json.dumps([{"route": "gonle"}]))
            with patch.dict(os.environ, {"ACCOUNT_ROUTE": "film"}), \
                 patch.object(runtime, "STATE", root / "state.json"), \
                 patch.object(runtime, "PLAN", root / "plan.json"), \
                 patch.object(runtime, "load_meta_auth") as auth:
                with self.assertRaisesRegex(RuntimeError, "Cross-account publication plan rejected"):
                    runtime.publish()
                auth.assert_not_called()

    @staticmethod
    def _artifact(state):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("link-runtime/state.json", json.dumps(state))
        return buffer.getvalue()

    def test_scoped_restore_uses_own_artifact_not_global_newest(self):
        state = {"schema": 1, "entries": {"film:facebook:one": {
            "route": "film", "status": "uncertain"}}, "episode_days": {}}
        calls = []
        def fake_get(path):
            calls.append(path)
            if path.startswith("actions/artifacts?"):
                if "link-state-result-film" in path:
                    return Mock(json=lambda: {"artifacts": [{
                        "id": 17, "name": "link-state-result-film", "expired": False,
                        "workflow_run": {"id": 100}}]})
                return Mock(json=lambda: {"artifacts": []})
            if path == "actions/artifacts/17/zip":
                return Mock(content=self._artifact(state))
            raise AssertionError("Unexpected artifact read " + path)
        with patch.dict(os.environ, {"ACCOUNT_ROUTE": "film"}), \
             patch.object(runtime, "github_get", side_effect=fake_get):
            self.assertEqual(runtime.restore(), state)
        self.assertFalse(any(p.endswith("name=link-state-result") for p in calls))

    def test_expired_account_evidence_never_reverts_to_global(self):
        calls = []
        def fake_get(path):
            calls.append(path)
            if "name=link-state-result-film" in path:
                return Mock(json=lambda: {"artifacts": [{
                    "id": 17, "name": "link-state-result-film", "expired": True,
                    "workflow_run": {"id": 100}}]})
            if "name=link-state-intent-film" in path:
                return Mock(json=lambda: {"artifacts": []})
            raise AssertionError("Legacy fallback must remain forbidden")
        with patch.dict(os.environ, {"ACCOUNT_ROUTE": "film"}), \
             patch.object(runtime, "github_get", side_effect=fake_get):
            with self.assertRaisesRegex(RuntimeError, "süresi dolmuş"):
                runtime.restore()
        self.assertEqual(len(calls), 2)

    def test_first_isolated_run_migrates_existing_uncertain_intent(self):
        state = {"schema": 1, "entries": {"film:instagram:old": {
            "route": "film", "status": "uncertain"}}, "episode_days": {}}
        def fake_get(path):
            if path.startswith("actions/artifacts?"):
                if path.endswith("name=link-state-result"):
                    return Mock(json=lambda: {"artifacts": [{
                        "id": 25, "name": "link-state-result", "expired": False,
                        "workflow_run": {"id": 200}}]})
                return Mock(json=lambda: {"artifacts": []})
            if path == "actions/artifacts/25/zip":
                return Mock(content=self._artifact(state))
            raise AssertionError(path)
        with patch.dict(os.environ, {"ACCOUNT_ROUTE": "film"}), \
             patch.object(runtime, "github_get", side_effect=fake_get):
            self.assertEqual(runtime.restore()["entries"]["film:instagram:old"]["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
