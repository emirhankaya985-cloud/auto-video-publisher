"""Mock-only proof of fail-closed git based Threads push release."""
import unittest
from pathlib import Path
from threads_owner_release_gate import (
    allowed, REPO, OWNER_MARKER, OWNER_SUBJECT, LEGACY_MARKER,
)

WORKFLOW = Path(__file__).parent / ".github/workflows/threads_live_publish.yml"
BASE = {
    "GITHUB_REPOSITORY": REPO,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_EVENT_NAME": "push",
}


def git_proof(*, subject=OWNER_SUBJECT, added=OWNER_MARKER, modified=""):
    def call(*args):
        if args[0] == "log":
            return subject
        if "--diff-filter=A" in args:
            return added
        if "--diff-filter=M" in args:
            return modified
        raise RuntimeError("unexpected git command")
    return call


class ThreadsOwnerCatchupContract(unittest.TestCase):
    def test_exact_added_marker_and_owner_subject_first_run_only(self):
        self.assertTrue(allowed(env=BASE, day="2026-11-07",
                                git=git_proof()))
        for day in ("2026-11-06", "2026-11-08"):
            self.assertFalse(allowed(env=BASE, day=day, git=git_proof()))
        for kwargs in (
            {"subject": "unrelated commit"},
            {"added": ""},
            {"added": "", "modified": OWNER_MARKER},
            {"added": "docs/other.md"},
            {"added": OWNER_MARKER, "modified": OWNER_MARKER},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(allowed(env=BASE, day="2026-11-07",
                                         git=git_proof(**kwargs)))

    def test_wrong_repository_branch_attempt_or_event_fails_closed(self):
        for k, value in (
            ("GITHUB_REPOSITORY", "attacker/repo"),
            ("GITHUB_REF", "refs/heads/feature"),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_EVENT_NAME", "pull_request"),
        ):
            with self.subTest(field=k, value=value):
                self.assertFalse(allowed(env=dict(BASE, **{k: value}),
                                         day="2026-11-07", git=git_proof()))

    def test_git_error_returns_blocked_not_green(self):
        import subprocess
        def broken(*args):
            raise subprocess.CalledProcessError(1, args)
        self.assertFalse(allowed(env=BASE, day="2026-11-07", git=broken))

    def test_existing_legacy_push_remains_supported_without_new_marker(self):
        self.assertTrue(allowed(env=BASE, day="2026-11-08",
                                git=git_proof(subject="legacy message",
                                              added="", modified=LEGACY_MARKER)))
        self.assertTrue(allowed(env=BASE, day="2026-11-08",
                                git=git_proof(subject="legacy message",
                                              added=LEGACY_MARKER, modified="")))

    def test_trusted_schedule_and_dispatch_paths_preserved(self):
        for event in ("workflow_run", "workflow_dispatch"):
            self.assertTrue(allowed(env=dict(BASE, GITHUB_EVENT_NAME=event),
                                    day="2026-11-08", git=lambda *args: None))
        self.assertFalse(allowed(env=dict(BASE, GITHUB_EVENT_NAME="workflow_run",
                                          GITHUB_RUN_ATTEMPT="2")))

    def test_workflow_gate_runs_before_source_read_and_provider_post(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("- 'docs/threads-owner-catchup-2026-11-07-v2.md'", workflow)
        self.assertIn("github.run_attempt == 1", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("github.event.workflow_run.event == 'schedule'", workflow)
        self.assertIn("fetch-depth: 2", workflow)
        self.assertLess(workflow.index("run: python threads_owner_release_gate.py"),
                        workflow.index("run: python threads_live_publish.py prepare"))
        for marker in (
            "ENABLE_TOONZONE_ROUTES: ${{ vars.ENABLE_TOONZONE_ROUTES }}",
            "FILM_RIGHTS_APPROVED: ${{ vars.FILM_RIGHTS_APPROVED }}",
            "ENABLE_PENGUEN_THREADS: ${{ vars.ENABLE_PENGUEN_THREADS }}",
            "Archive publication reservations before writing",
            "THREADS_INTENT_ARCHIVED",
            "Preserve post IDs and ambiguous attempts",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, workflow)


if __name__ == "__main__":
    unittest.main()
