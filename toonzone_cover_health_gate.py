"""Fail a due ToonZone job if its strict original-cover gate blocked publication.

The publisher already preserves the report, state and incident artifacts before
this check. No Meta API calls, retries, captions or claims are modified.
"""
from pathlib import Path


def status(report):
    if not isinstance(report, str):
        return "unavailable"
    if "HELD: exact ToonZone cover missing;" in report:
        return "blocked_missing_original_cover"
    return "not_cover_blocked"


def main():
    path = Path("link-runtime/report.md")
    if not path.is_file():
        print("ToonZone health: publisher report missing")
        return 1
    result = status(path.read_text(encoding="utf-8"))
    print("ToonZone health: " + result)
    return 1 if result != "not_cover_blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
