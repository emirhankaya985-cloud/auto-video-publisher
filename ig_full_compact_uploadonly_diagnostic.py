"""Single guarded full-length, low-bandwidth IG upload-only diagnosis.

Two existing 180-second source clips, no media_publish and no queue mutation.
"""
import json
import os
import subprocess
from pathlib import Path

from ig_shortclip_uploadonly_diagnostic import execute, SOURCES

MARKER = "docs/ig-full-compact-uploadonly-2026-10-26.md"
SUBJECT = "diag: authorized-once-full-compact-unpublished-ig-2026-10-26"


def require_exact_commit_gate():
    if (os.getenv("GITHUB_EVENT_NAME") != "push" or
        os.getenv("GITHUB_REF") != "refs/heads/main" or
        os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher" or
        os.getenv("IG_FULL_COMPACT_APPROVED") != "true"):
        raise RuntimeError("Exact full-length unpublished IG diagnosis not authorized")
    title = subprocess.check_output(
        ["git", "log", "-1", "--format=%s"], text=True).strip()
    added = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=A", "HEAD^", "HEAD"],
        text=True).splitlines()
    if title != SUBJECT or MARKER not in added:
        raise RuntimeError("Full-length upload-only release marker missing")


def full_compact_trial(page, source, filename, workdir):
    from instagram_media_compat import prepare_instagram_upload, probe
    from cloud_omnichannel_publisher import upload_instagram_reel
    source = Path(source)
    full = Path(workdir) / "full_compact_unpublished.mp4"
    converted, method = prepare_instagram_upload(
        source, full, film_compact=True, return_method=True)
    if converted != full or method != "transcode":
        raise RuntimeError("Full-length diagnosis requires validated compact re-encode")
    media = probe(converted)
    duration = float(media.get("format", {}).get("duration") or 0)
    if not 175 <= duration <= 185:
        raise RuntimeError("Full diagnostic lost original 180-second duration")
    result = upload_instagram_reel(
        page, str(converted),
        "Unpublished full-length upload compatibility check",
        append_store_link=False, publish=False)
    if (not isinstance(result, dict) or result.get("published") is not False
        or result.get("status") != "FINISHED"
        or not str(result.get("container_id") or "").isdecimal()):
        raise RuntimeError("Full 180s diagnostic not confirmed FINISHED")
    return {"status": "FINISHED_NOT_PUBLISHED", "container_id": str(result["container_id"]),
            "post_id": None}


def main():
    result = execute(trial=full_compact_trial, gate=require_exact_commit_gate)
    result["mode"] = "180s_compact_upload_only_no_publish"
    result["media_publish_calls"] = 0
    message = json.dumps(result, ensure_ascii=False, indent=2)
    print(message)
    Path("ig-full-compact-uploadonly-result.json").write_text(message+"\n", encoding="utf-8")
    return 0 if result["files"] and all(
        row["status"] == "FINISHED_NOT_PUBLISHED" for row in result["files"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
