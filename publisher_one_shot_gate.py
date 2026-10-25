"""Fail-closed one-time publisher gate, based on the checked-out commit diff.

No network, token, Meta POST or filesystem state mutation beyond GITHUB_OUTPUT.
"""
import os
import subprocess
from pathlib import Path

MARKER = "docs/publisher-one-shot-v2-2026-10-25.md"
SUBJECT = "ops: authorized-once-meta-publish-2026-10-25-v2"


def determine_mode(event, ref, subject="", added_paths=(), requested_mode="audit"):
    if event == "schedule":
        return "publish"
    if event == "workflow_dispatch":
        return "publish" if requested_mode == "publish" else "audit"
    if event == "push":
        return ("publish" if ref == "refs/heads/main"
                and subject == SUBJECT and MARKER in added_paths else "audit")
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
    with Path(output).open("a", encoding="utf-8") as stream:
        stream.write(f"mode={mode}\npublish_allowed={'true' if mode == 'publish' else 'false'}\n")
    print(f"Publisher decision: {mode}; event={event}; reason=checked_commit_and_existing_gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
