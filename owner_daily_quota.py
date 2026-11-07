"""Seven-account daily quota evidence from the immutable publication ledger.

Only 'done' rows with a nonempty platform post ID count as *ledger recorded*.
A ledger record is not a live GET confirmation; Threads and YouTube lack day
binding in this state and must remain N/A, never a fictional zero.
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = "emirhankaya985-cloud/auto-video-publisher"
TR = ZoneInfo("Europe/Istanbul")
NY = ZoneInfo("America/New_York")
OWNER_ACCOUNTS = (
    ("Tarladaki Fasulye", "tarladaki", 5, (("tarladaki", "facebook"),
                                          ("tarladaki", "instagram"))),
    ("Beyinsiz Penguen", "penguen", 5, (("penguen", "facebook"),
                                         ("penguen", "instagram"))),
    ("Gönle Düşen", "gonle", 5, (("gonle", "facebook"),
                                    ("gonle", "instagram"))),
    ("Daily Laugh Lab", "daily_laugh", 8, (("daily_laugh", "facebook"),
                                              ("daily_laugh", "instagram"))),
    ("Film Mağarası", "film", 5, (("film", "facebook"),
                                    ("film_second", "facebook"),
                                    ("film", "instagram"))),
    ("ToonZone", "toonzone", 4, (("toonzone", "facebook"),
                                   ("toonzone", "instagram"))),
    ("OddFrames", "oddframes", None, ()),
)
POST_ID = re.compile(r"[0-9]{8,30}\Z")


def youtube_forbidden_circuit_evidence(state, route):
    """Read only 403 state in the publisher's existing YouTube ledger."""
    if route not in {"tarladaki", "penguen", "gonle", "daily_laugh"}:
        return "N/A"
    ledger = state.get("youtube_entries")
    if not isinstance(ledger, dict):
        return "youtube_ledger_unavailable"
    from youtube_permission_circuit import repeated_youtube_insert_forbidden
    return ("held_after_consecutive_insert_403_forbidden"
            if repeated_youtube_insert_forbidden(ledger, route)
            else "no_consecutive_forbidden_evidence")


def quota_evidence(state, *, now=None):
    if not isinstance(state, dict) or state.get("schema") != 1 or not isinstance(state.get("entries"), dict):
        raise ValueError("publisher_ledger_unavailable")
    now = now or datetime.now(TR)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_required")
    entries = state["entries"]
    if any(not isinstance(row, dict) for row in entries.values()):
        raise ValueError("publisher_entries_invalid")
    report = []
    for name, route, target, configured in OWNER_ACCOUNTS:
        day = (now.astimezone(NY).date() - timedelta(days=1)
               if route == "daily_laugh" else now.astimezone(TR).date()).isoformat()
        platform_rows = []
        for account_route, platform in configured:
            posts, pending, invalid_done = set(), set(), 0
            for key, row in entries.items():
                if (row.get("route") != account_route or row.get("platform") != platform
                        or row.get("day") != day):
                    continue
                pieces = key.split(":", 2) if isinstance(key, str) else ()
                if len(pieces) != 3 or pieces[:2] != [account_route, platform]:
                    invalid_done += 1
                    continue
                post_id = str(row.get("post_id") or "")
                if row.get("status") == "done":
                    if POST_ID.fullmatch(post_id):
                        posts.add(post_id)
                    else:
                        invalid_done += 1
                elif row.get("status") in {"uncertain", "intent", "held", "pending"}:
                    pending.add(pieces[2])
            platform_rows.append({
                "route": account_route, "platform": platform, "day": day,
                "scheduled_target": target, "ledger_post_ids_count": len(posts),
                "not_recorded_against_target": max(0, target - len(posts)),
                "unresolved_sources": len(pending), "invalid_done_rows": invalid_done,
                "live_provider_history_confirmation": "N/A",
                "safe_to_auto_repost": False,
            })
        report.append({
            "account": name,
            "day": day,
            "status": "not_configured" if route == "oddframes" else "ledger_only_not_live_verified",
            "platforms": platform_rows,
            "threads_daily_posts": "N/A",
            "youtube_daily_posts": "N/A",
            "youtube_upload_permission_circuit": youtube_forbidden_circuit_evidence(state, route),
            "requires_provider_reconciliation": True,
        })
    return {"status": "ledger_only_not_live_verified",
            "accounts_expected": 7, "accounts": report,
            "new_provider_posts": 0, "provider_writes": 0,
            "basis": "GitHub Actions preserved state.json; no live API count"}


def main():
    from publication_github_progress import restore_publication_state
    destination = Path("daily-quota-evidence.json")
    try:
        if (os.getenv("GITHUB_REPOSITORY") != REPO
                or os.getenv("GITHUB_REF") != "refs/heads/main"):
            raise RuntimeError("untrusted_repository_context")
        report = quota_evidence(restore_publication_state())
    except Exception as exc:
        report = {"status": "ledger_unavailable", "safe_error_type": type(exc).__name__,
                  "new_provider_posts": 0, "provider_writes": 0}
        destination.write_text(json.dumps(report), encoding="utf-8")
        print(json.dumps(report))
        return 1
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"],
        "accounts_expected": report["accounts_expected"],
        "quota": [{"account": row["account"], "day": row["day"],
                   "counts": {f"{p['route']}:{p['platform']}": p['ledger_post_ids_count']
                              for p in row["platforms"]},
                   "youtube_upload_permission_circuit": row["youtube_upload_permission_circuit"]}
                  for row in report["accounts"]],
        "new_provider_posts": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
