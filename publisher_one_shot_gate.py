"""Fail-closed one-time publisher gate, based on the checked-out commit diff.

No network, token, Meta POST or filesystem state mutation beyond GITHUB_OUTPUT.
"""
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKER = "docs/publisher-one-shot-v2-2026-10-25.md"
SUBJECT = "ops: authorized-once-meta-publish-2026-10-25-v2"
IG_RESCUE_MARKER = "docs/ig-v3-rescue-once-2026-10-26.md"
IG_RESCUE_SUBJECT = "ops: authorized-once-exact-two-ig-v3-2026-10-26"
IG_V4_MARKER = "docs/ig-v4-compact-publish-once-2026-10-26.md"
IG_V4_SUBJECT = "ops: authorized-once-exact-two-ig-v4-compact-2026-10-26"
OWNER_CATCHUP_MARKER = "docs/owner-authorized-catchup-2026-11-01.md"
OWNER_CATCHUP_SUBJECT = "ops: owner-authorized-catchup-2026-11-01"
OWNER_CATCHUP_DATE = "2026-11-01"


def is_owner_catchup_push(event, ref, subject, added_paths, *, today=None, run_attempt=None):
    """One day, one commit, first attempt only; never publish on CI PR or rerun."""
    if today is None:
        today = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    if run_attempt is None:
        run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return (
        event == "push" and ref == "refs/heads/main"
        and subject == OWNER_CATCHUP_SUBJECT
        and OWNER_CATCHUP_MARKER in added_paths
        and today == OWNER_CATCHUP_DATE
        and str(run_attempt) == "1"
    )



def is_v4_recovery_push(event, ref, subject, added_paths):
    return (event == "push" and ref == "refs/heads/main"
            and subject == IG_V4_SUBJECT
            and IG_V4_MARKER in added_paths)



def is_ig_rescue_push(event, ref, subject, added_paths):
    return (event == "push" and ref == "refs/heads/main"
            and subject == IG_RESCUE_SUBJECT
            and IG_RESCUE_MARKER in added_paths)


def determine_mode(event, ref, subject="", added_paths=(), requested_mode="audit"):
    if event == "schedule":
        return "publish"
    if event == "workflow_dispatch":
        return "publish" if requested_mode == "publish" else "audit"
    if event == "push":
        normal = ref == "refs/heads/main" and subject == SUBJECT and MARKER in added_paths
        rescue = is_ig_rescue_push(event, ref, subject, added_paths)
        v4 = is_v4_recovery_push(event, ref, subject, added_paths)
        catchup = is_owner_catchup_push(event, ref, subject, added_paths)
        return "publish" if normal or rescue or v4 or catchup else "audit"
    return "audit"


def _git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def main():
    event = os.getenv("GITHUB_EVENT_NAME", "")
    subject, added = "", ()
    if event == "push":
        # The workflow checks out two commits, so HEAD^ is real, not a shallow
        # synthetic root where all files might look newly added.
        subject = _git("log", "-1", "--format=%s")
        added = tuple(filter(None, _git("diff", "--name-only",
                                         "--diff-filter=A", "HEAD^", "HEAD").splitlines()))
    mode = determine_mode(
        event, os.getenv("GITHUB_REF", ""), subject, added,
        os.getenv("REQUESTED_MODE", "audit"))
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        raise RuntimeError("GitHub gate output path missing")
    rescue = (is_ig_rescue_push(event, os.getenv("GITHUB_REF", ""), subject, added)
              or is_v4_recovery_push(event, os.getenv("GITHUB_REF", ""), subject, added))
    with Path(output).open("a", encoding="utf-8") as stream:
        stream.write(f"mode={mode}\npublish_allowed={'true' if mode == 'publish' else 'false'}\n")
        stream.write(f"recovery_only={'true' if rescue else 'false'}\n")
    print(f"Publisher decision: {mode}; event={event}; reason=checked_commit_and_existing_gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
