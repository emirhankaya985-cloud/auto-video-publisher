import io
import json
import unittest
import zipfile
from types import SimpleNamespace

from publication_github_progress import ledger_progress, restore_publication_state


def row(route, platform, status="done", post="p"):
    return {"route": route, "platform": platform, "day": "2026-11-01",
            "status": status, "post_id": post}


class PublicationProgressTests(unittest.TestCase):
    def test_independent_platform_sources_and_deduplicates_post(self):
        state = {"entries": {
            "tarladaki:facebook:a": row("tarladaki", "facebook"),
            "tarladaki:facebook:b": row("tarladaki", "facebook"),
            "tarladaki:instagram:b": row("tarladaki", "instagram", post="i"),
            "tarladaki:instagram:c": row("tarladaki", "instagram", "uncertain", ""),
            "tarladaki:facebook:d": row("tarladaki", "facebook", "failed", ""),
        }}
        p = ledger_progress(state, "tarladaki", "2026-11-01", 5)
        self.assertEqual((p["posts"], p["completed"], p["failures"], p["uncertain"]), (2, 1, 1, 1))

    def test_film_three_destinations(self):
        entries = {f"{r}:{p}:{r}-{p}": row(r, p, post=f"{r}-{p}")
                   for r, p in [("film", "facebook"), ("film", "instagram"),
                                ("film_second", "facebook")]}
        p = ledger_progress({"entries": entries}, "film", "2026-11-01", 5)
        self.assertEqual((p["completed"], p["posts"], p["expected_posts"]), (1, 3, 15))

    def test_restore_newer_intent_and_result_tie(self):
        for intent_run, expected in [(11, "intent"), (10, "result")]:
            def get(url, **kwargs):
                if url.endswith("artifacts"):
                    name = kwargs["params"]["name"]
                    run = intent_run if name.endswith("intent") else 10
                    return SimpleNamespace(status_code=200, json=lambda: {"artifacts": [{
                        "id": 2 if name.endswith("intent") else 1, "name": name,
                        "expired": False, "workflow_run": {"id": run, "head_branch": "main"}}]})
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr("state.json", json.dumps({"schema": 1, "entries": {},
                        "picked": "intent" if "/2/" in url else "result"}))
                return SimpleNamespace(status_code=200, content=buffer.getvalue())
            self.assertEqual(restore_publication_state(token="test", get=get)["picked"], expected)

    def test_no_history_is_not_zero(self):
        def get(url, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"artifacts": []})
        with self.assertRaisesRegex(RuntimeError, "history unavailable"):
            restore_publication_state(token="test", get=get)

    def test_done_without_post_id_not_success(self):
        state = {"entries": {"gonle:facebook:a": row("gonle", "facebook", post="")}}
        self.assertEqual(ledger_progress(state, "gonle", "2026-11-01", 5)["posts"], 0)
        self.assertEqual(ledger_progress(state, "gonle", "2026-11-01", 5)["uncertain"], 1)

    def test_alias_order_independent_and_explicit_canonical_source(self):
        entries = {
            "gonle:facebook:a": row("gonle", "facebook", post="fb"),
            "gonle:facebook:b": dict(row("gonle", "facebook", post="fb"), duplicate_of_file_id="a"),
            "gonle:instagram:b": dict(row("gonle", "instagram", post="ig"), duplicate_of_file_id="a"),
            "gonle:instagram:a": row("gonle", "instagram", post="ig"),
        }
        for ordered in (entries, dict(reversed(list(entries.items())))):
            p = ledger_progress({"entries": ordered}, "gonle", "2026-11-01", 5)
            self.assertEqual((p["posts"], p["completed"]), (2, 1))

    def test_unexplained_aliases_cannot_double_count_completion(self):
        entries = {f"gonle:{platform}:{source}": row("gonle", platform, post=platform)
                   for platform in ("facebook", "instagram") for source in ("a", "b")}
        for ordered in (entries, dict(reversed(list(entries.items())))):
            p = ledger_progress({"entries": ordered}, "gonle", "2026-11-01", 5)
            self.assertEqual((p["posts"], p["completed"]), (2, 1))

    def test_preparation_failure_ready_is_counted(self):
        entry = row("gonle", "facebook", "ready", "")
        entry["failure"] = {"reason": "media_preparation_failed"}
        p = ledger_progress({"entries": {"gonle:facebook:a": entry}}, "gonle", "2026-11-01", 5)
        self.assertEqual((p["failures"], p["posts"], p["uncertain"]), (1, 0, 0))


if __name__ == "__main__":
    unittest.main()
