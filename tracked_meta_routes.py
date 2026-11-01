"""Read-only deadline check for the two monitored Meta routes.

Never submits media, alters the publication ledger, changes a route switch, or
confuses a successful GitHub run with a verified Meta video. A route is checked
only AFTER its complete daily schedule plus queue grace time.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import publisher_alert_history as alert_history

from meta_auth_loader import load_meta_auth
from ntfy_notifications import send_ntfy
from publication_safety import route_paused
# Keep Drive/gdown imports out of this read-only watchdog's import path.
# The production-only Graph reader is loaded lazily after route checks.
from telegram_notifications import send_telegram, telegram_configured

ISTANBUL = ZoneInfo("Europe/Istanbul")
NEW_YORK = ZoneInfo("America/New_York")
TARGETS = {"toonzone": ("ToonZone", 4), "daily_laugh": ("Daily Laugh Lab", 8)}
WORKFLOW_URL = (
    "https://github.com/emirhankaya985-cloud/auto-video-publisher/"
    "actions/workflows/tracked_meta_routes.yml"
)


def target_day(route, now):
    """Daily Laugh follows New York's previous day, ToonZone Istanbul today."""
    if route == "daily_laugh":
        return now.astimezone(NEW_YORK).date() - timedelta(days=1)
    return now.astimezone(ISTANBUL).date()


def _platform_day(route, row):
    raw = row.get("created_time") or row.get("timestamp")
    if not isinstance(raw, str) or not raw:
        raise ValueError("Missing publication timestamp")
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Publication timestamp must have timezone")
    return stamp.astimezone(NEW_YORK if route == "daily_laugh" else ISTANBUL).date()


def check_route(route, *, now=None, page_loader=load_meta_auth,
                history_reader=None, paused=route_paused):
    if route not in TARGETS:
        raise ValueError("Unapproved monitored route")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Monitoring needs an aware timestamp")
    page_name, expected = TARGETS[route]
    day = target_day(route, now).isoformat()
    result = {"route": route, "day": day, "target_per_platform": expected}
    if paused(route):
        return dict(result, status="disabled", reason="route_not_authorized")
    platforms = ["facebook"]
    if route == "toonzone" or not paused("daily_laugh_instagram"):
        platforms.append("instagram")
    else:
        result["instagram"] = {"status": "disabled"}

    try:
        if history_reader is None:
            # Production workflow installs gdown for the existing publisher
            # Graph reader. Offline monitoring tests never need Drive.
            from public_link_runtime import graph_rows
            history_reader = graph_rows
        auth = page_loader()
        pages = auth.get("pages") if isinstance(auth, dict) else None
        if not isinstance(pages, list):
            raise ValueError("Invalid Meta account inventory")
        candidates = [page for page in pages
                      if isinstance(page, dict) and page.get("page_name") == page_name]
        if len(candidates) != 1:
            raise ValueError("Meta account absent or ambiguous")
        page = candidates[0]
        counts = {}
        for platform in platforms:
            if platform == "instagram" and not page.get("instagram_id"):
                raise ValueError("Required Instagram account absent")
            rows = history_reader(page, platform)
            if not isinstance(rows, list):
                raise ValueError("Invalid media history")
            verified_ids = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Malformed media")
                post_id = str(row.get("id") or "")
                if not post_id.isdecimal():
                    raise ValueError("Unverifiable post ID")
                if _platform_day(route, row).isoformat() == day:
                    verified_ids.add(post_id)
            counts[platform] = len(verified_ids)
        result["counts"] = counts
        result["missing"] = {p: max(0, expected - count)
                             for p, count in counts.items()}
        result["status"] = (
            "healthy" if all(count >= expected for count in counts.values())
            else "behind"
        )
        return result
    except Exception as exc:
        # Never log raw provider exceptions (may contain URLs, credentials).
        return dict(result, status="unknown", reason="meta_read_failed",
                    error_type=type(exc).__name__)


def main():
    route = os.getenv("TARGET_ROUTE", "").strip()
    if route not in TARGETS:
        print('{"status":"configuration_error","reason":"invalid_target_route"}',
              flush=True)
        return 1
    verdict = check_route(route)
    Path("target-verdict.json").write_text(json.dumps(verdict,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, sort_keys=True), flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a", encoding="utf-8") as report:
            report.write(
                f"### Verified Meta video target — {route}\n\n"
                f"- Date ({'New York' if route == 'daily_laugh' else 'Istanbul'}): "
                f"{verdict['day']}\n"
                f"- Status: {verdict['status']}\n"
                f"- Confirmed platform video counts: {verdict.get('counts', 'unavailable')}\n"
                "- Read-only Meta history; no uploads, no retry, no ledger edits.\n"
            )
    if verdict["status"] in ("healthy", "disabled"):
        return 0
    if os.getenv("CORRELATE_PUBLISHER_ALERTS")=="true" and verdict.get("status")=="behind":
        missing=[p for p,n in verdict.get("missing",{}).items() if n]
        try:
            if alert_history.covered(alert_history.restore(),route=route,platforms=missing):
                print('{"notification":"duplicate_target_alert_suppressed","target":"behind","reason":"publisher_incident_already_acknowledged"}',flush=True)
                return 1
        except Exception:
            print('{"correlation":"unavailable","new_target_alert_preserved":true}',flush=True)

    missing = verdict.get("missing")
    deficits = ", ".join(f"{p}: {n} eksik" for p, n in (missing or {}).items() if n)
    subject = "ToonZone" if route == "toonzone" else "Daily Laugh Lab"
    title = f"⚠️ {subject} günlük yayın kontrolü"
    if verdict["status"] == "unknown":
        title = f"⚠️ {subject} Meta erişim kontrolü"
        message = (
            f"{subject} — {verdict['day']}: Meta yayın geçmişi okunamadı "
            f"({verdict.get('reason', 'read_unavailable')}). "
            "Hedefte video eksikliği kanıtlanmadı; körlemesine yeniden yayın yapmayın. "
            "META_ACCESS_TOKEN üzerinden keşfedilen Page erişimini salt-okunur doğrulayın. "
            f"Kontrol: {WORKFLOW_URL}"
        )
    else:
        message = (
            f"{subject} — {verdict['day']}: planlanan saatler geçti. "
            f"Durum: {verdict['status']}. "
            f"Platform video hedefi: {verdict['target_per_platform']}. "
            f"{deficits or verdict.get('reason', 'Meta geçmişi doğrulanamadı')}. "
            "Bu yalnızca okuma/uyarı kontrolüdür; video yeniden gönderilmedi. "
            f"Kontrol: {WORKFLOW_URL}"
        )
    if os.getenv("NTFY_TOPIC_URL", "").strip() or os.getenv("NTFY_TOPIC", "").strip():
        try:
            send_ntfy(title, message, priority=4, tags=["warning"],
                      timeout=20, require_ack=True, click=WORKFLOW_URL)
            print('{"notification":"ntfy_server_ack","phone_delivery_verified":false}', flush=True)
        except Exception as exc:
            print(json.dumps({"notification": "ntfy_failed",
                              "error_type": type(exc).__name__}), flush=True)
    if telegram_configured():
        try:
            send_telegram(title, message)
            print('{"notification":"telegram_server_ack","phone_delivery_verified":false}', flush=True)
        except Exception as exc:
            print(json.dumps({"notification": "telegram_failed",
                              "error_type": type(exc).__name__}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
