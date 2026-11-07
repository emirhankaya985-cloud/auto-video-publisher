"""Credential-free, fail-closed gate for the one-time owner Threads catch-up.

Use checked-out *git diff*, not a possibly incomplete webhook head_commit list.
No Threads/Meta API calls. A failed check stops before token use or post intents.
"""
import os
import subprocess
from datetime import datetime, timedelta, timezone

REPO = "emirhankaya985-cloud/auto-video-publisher"
OWNER_MARKER = "docs/threads-owner-catchup-2026-11-07-v2.md"
OWNER_SUBJECT = "ops: owner-authorized-once-threads-catchup-v2-2026-11-07"
LEGACY_MARKER = "docs/threads-owner-start-2026-11-04.md"
RELEASE_DAY = "2026-11-07"
TR = timezone(timedelta(hours=3))


def _git(*args):
    return subprocess.check_output(["git", *args], text=True, timeout=10).strip()


def allowed(*, env=None, day=None, git=_git):
    values = os.environ if env is None else env
    if values.get("GITHUB_REPOSITORY") != REPO:
        return False
    if values.get("GITHUB_REF") != "refs/heads/main":
        return False
    if str(values.get("GITHUB_RUN_ATTEMPT", "")) != "1":
        return False
    event = values.get("GITHUB_EVENT_NAME")
    if event in ("workflow_dispatch", "workflow_run"):
        # The workflow has its own upstream event, branch and repository guard.
        return True
    if event != "push":
        return False
    try:
        subject = git("log", "-1", "--format=%s")
        added = set(filter(None, git("diff", "--name-only", "--diff-filter=A",
                                     "HEAD^", "HEAD").splitlines()))
        modified = set(filter(None, git("diff", "--name-only", "--diff-filter=M",
                                        "HEAD^", "HEAD").splitlines()))
    except (subprocess.SubprocessError, OSError):
        return False
    today = day if day is not None else datetime.now(TR).date().isoformat()
    one_shot = (subject == OWNER_SUBJECT and OWNER_MARKER in added
                and OWNER_MARKER not in modified and today == RELEASE_DAY)
    # Preserve existing explicitly named legacy marker workflow behavior.
    legacy = LEGACY_MARKER in added or LEGACY_MARKER in modified
    return one_shot or legacy


def main():
    result = allowed()
    print("THREADS_RELEASE_GATE " + ("AUTHORIZED" if result else "BLOCKED"))
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
