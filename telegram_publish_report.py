"""Post-run Telegram summary for the 985 Meta-only video publisher.

Only confirmed post IDs from the *current* GitHub Actions run count as
successful publications. Silent no-op schedule checks generate no message.
This module never uploads video or mutates the publishing state.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

from telegram_notifications import send_telegram, telegram_configured

STATE_PATH = Path("link-runtime/state.json")
ALLOWED_STEP_RESULTS = {"success", "failure", "skipped", "cancelled", ""}


def publication_summary(state, run_id, *, plan_outcome="success", publish_outcome="success"):
    """Return text and category; never claim publication from workflow status."""
    if not run_id or not run_id.isdigit():
        return None, "invalid_run_id"
    if plan_outcome not in ALLOWED_STEP_RESULTS or publish_outcome not in ALLOWED_STEP_RESULTS:
        return None, "invalid_step_outcome"
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        return None, "invalid_state"
    matched = []
    for entry in state["entries"].values():
        if isinstance(entry, dict) and str(entry.get("run_id", "")) == run_id:
            matched.append(entry)

    done = [row for row in matched
            if row.get("status") == "done" and str(row.get("post_id", "")).strip()]
    unknown = [row for row in matched if row.get("status") in {"intent", "uncertain"}]
    # A failed planning step can have left an older valid state untouched.
    failed = plan_outcome == "failure" or publish_outcome == "failure"
    if not failed and not unknown and not done:
        return None, "nothing_to_report"
    lines = ["🚨 985 Meta yayın uyarısı" if failed or unknown else "✅ 985 Meta video yayınları",
             f"GitHub çalışma: {run_id}"]
    if done:
        lines.append(f"✅ Yeni doğrulanan gönderi: {len(done)}")
        counts = Counter((row.get("route", "unknown"), row.get("platform", "unknown")) for row in done)
        for (route, platform), count in sorted(counts.items()):
            lines.append(f"• {route} / {platform}: {count} gönderi")
    if unknown:
        lines.append(f"⚠️ Belirsiz yükleme: {len(unknown)} (otomatik tekrar yayın yok)")
    if failed:
        lines.append("❌ Yayın iş akışı adımlarından biri başarısız.")
    lines.append(f"🔎 https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}")
    return "\n".join(lines), "alert" if failed or unknown else "published"


def main():
    # A workflow without configured secrets should keep publishing unaffected.
    if not telegram_configured():
        print('{"status":"telegram_not_configured"}', flush=True)
        return 0
    run_id = os.getenv("GITHUB_RUN_ID", "")
    plan_outcome = os.getenv("PLAN_STEP_OUTCOME", "")
    publish_outcome = os.getenv("PUBLISH_STEP_OUTCOME", "")
    if plan_outcome == "skipped" and publish_outcome == "skipped":
        return 0
    state = {"entries": {}}
    if STATE_PATH.is_file():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            print('{"status":"telegram_report_invalid_state"}', flush=True)
            return 1
    message, category = publication_summary(
        state, run_id, plan_outcome=plan_outcome, publish_outcome=publish_outcome
    )
    if not message:
        print(json.dumps({"status": category, "message_sent": False}), flush=True)
        return 0 if category == "nothing_to_report" else 1
    try:
        response = send_telegram(
            "Meta publisher", message,
        )
        print(json.dumps({"status": "telegram_server_acknowledged",
                          "type": category,
                          "server_ack": response["server_ack"],
                          "phone_delivery_verified": False}), flush=True)
        return 0
    except Exception as exc:
        # Never print sensitive bot-token, chat ID, or response text.
        print(json.dumps({"status": "telegram_notification_failed",
                          "error_type": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
