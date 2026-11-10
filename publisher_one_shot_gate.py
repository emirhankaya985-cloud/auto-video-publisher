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
TODAY_CATCHUP_MARKER = "docs/owner-authorized-catchup-2026-11-02.md"
TODAY_CATCHUP_SUBJECT = "ops: owner-authorized-catchup-2026-11-02"
TODAY_CATCHUP_DATE = "2026-11-02"

# Owner explicitly authorized eligible, rights-gated missing posts on Nov 7.
# A unique, ADDED marker commit on main only; never retroactively re-run.
NOV7_CATCHUP_MARKER = "docs/owner-authorized-catchup-2026-11-07.md"
NOV7_CATCHUP_SUBJECT = "ops: owner-authorized-once-meta-catchup-2026-11-07"
NOV7_CATCHUP_DATE = "2026-11-07"

# Owner explicitly authorized today's missing eligible posts on 9 November.
# The marker MUST be added by this exact subject on main (one run only).
NOV9_CATCHUP_MARKER = "docs/owner-authorized-catchup-2026-11-09.md"
NOV9_CATCHUP_SUBJECT = "ops: owner-authorized-once-meta-catchup-2026-11-09"
NOV9_CATCHUP_DATE = "2026-11-09"

# Owner-requested urgent Film Mağarası original Bıçkın 8 recovery.
# Only an ADDED unique marker commit on 10 November can launch real Meta
# publishing; failed rechecks may not be rerun as another authorization.
FILM_PART8_MARKER = "docs/owner-authorized-film-part8-2026-11-10.md"
FILM_PART8_SUBJECT = "ops: authorized-once-film-bickin8-2026-11-10"
FILM_PART8_DATE = "2026-11-10"

def is_film_part8_once(event, ref, subject, added_paths, *, today=None, run_attempt=None):
    if today is None:
        today = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    if run_attempt is None:
        run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return (event == "push" and ref == "refs/heads/main"
            and subject == FILM_PART8_SUBJECT
            and FILM_PART8_MARKER in added_paths
            and today == FILM_PART8_DATE and str(run_attempt) == "1")



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



def is_today_catchup_push(event, ref, subject, added_paths, *, today=None, run_attempt=None):
    """Explicitly authorized 2 Nov only; first run, main, exact new marker."""
    if today is None:
        today = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    if run_attempt is None:
        run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return (event == "push" and ref == "refs/heads/main"
            and subject == TODAY_CATCHUP_SUBJECT
            and TODAY_CATCHUP_MARKER in added_paths
            and today == TODAY_CATCHUP_DATE
            and str(run_attempt) == "1")


def is_nov9_catchup_push(event, ref, subject, added_paths, *, today=None, run_attempt=None):
    """Only the explicitly authorized 9 Nov newly added marker can publish."""
    if today is None:
        today = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    if run_attempt is None:
        run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return (event == "push" and ref == "refs/heads/main"
            and subject == NOV9_CATCHUP_SUBJECT
            and NOV9_CATCHUP_MARKER in added_paths
            and today == NOV9_CATCHUP_DATE and str(run_attempt) == "1")


def is_nov7_catchup_push(event, ref, subject, added_paths, *, today=None, run_attempt=None):
    """One rights-gated due-slot catch-up. A rerun or later date is audit-only."""
    if today is None:
        today = datetime.now(timezone(timedelta(hours=3))).date().isoformat()
    if run_attempt is None:
        run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    return (event == "push" and ref == "refs/heads/main"
            and subject == NOV7_CATCHUP_SUBJECT
            and NOV7_CATCHUP_MARKER in added_paths
            and today == NOV7_CATCHUP_DATE and str(run_attempt) == "1")


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
        catchup = (is_owner_catchup_push(event, ref, subject, added_paths)
                   or is_today_catchup_push(event, ref, subject, added_paths)
                   or is_nov7_catchup_push(event, ref, subject, added_paths)
                   or is_nov9_catchup_push(event, ref, subject, added_paths)
                   or is_film_part8_once(event, ref, subject, added_paths))
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
        # The owner can authorize another catch-up after replacing expired
        # credentials on the same day. Only this dated marker may be modified;
        # historical rescue markers still have to be newly added.
        modified = _git("diff", "--name-only", "--diff-filter=M", "HEAD^", "HEAD").splitlines()
        if OWNER_CATCHUP_MARKER in modified:
            added += (OWNER_CATCHUP_MARKER,)
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

