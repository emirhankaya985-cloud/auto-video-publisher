"""Read-only health check for the 985 Meta-only publisher.

A green CI run is NOT evidence of a published video. This watchdog only checks
whether scheduled publishing jobs actually completed successfully. It cannot
claim individual posts or their view counts.
"""
import io
import zipfile
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from ntfy_notifications import send_ntfy
from telegram_notifications import send_telegram, telegram_configured
import publisher_alert_history as alert_history

EXPECTED_REPO = "emirhankaya985-cloud/auto-video-publisher"
WORKFLOW = "public_link_schedule.yml"


def parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def check_publication_receipts(recent, *, get, headers):
    """Read latest per-account receipts; green Actions alone is insufficient."""
    run_ids = {str(run.get("id")) for _, run in recent if str(run.get("id", "")).isdigit()}
    if not run_ids:
        return {"status": "unknown", "reason": "publication_receipts_unavailable"}
    try:
        completed = [(stamp, run) for stamp, run in recent if run.get("status") == "completed"]
        if len(completed) > 64:
            raise ValueError("receipt coverage limit exceeded")
        latest = {}
        # Query every completed run in the time window. The repository-wide
        # 100-artifact page can cover only minutes when account jobs fan out.
        expected_routes = {"tarladaki", "penguen", "gonle", "daily_laugh", "film", "film_second", "toonzone"}
        for _, run in sorted(completed, key=lambda item: item[0], reverse=True):
            if set(latest) == expected_routes:
                break
            run_id = str(run.get("id", ""))
            if run_id not in run_ids:
                raise ValueError("invalid receipt origin")
            response = get(f"https://api.github.com/repos/{EXPECTED_REPO}/actions/runs/{run_id}/artifacts",
                           headers=headers, params={"per_page": 100}, timeout=5, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError("receipt index unavailable")
            body = response.json()
            artifacts = body.get("artifacts")
            if (not isinstance(artifacts, list) or type(body.get("total_count", len(artifacts))) is not int
                    or body.get("total_count", len(artifacts)) > 100):
                raise ValueError("incomplete receipt index")
            receipt_found = False
            for artifact in sorted(artifacts, key=lambda row: int(row.get("id", 0)), reverse=True):
                name = artifact.get("name", "")
                origin = str(artifact.get("workflow_run", {}).get("id", ""))
                if (not name.startswith("link-incident-report-") or origin != run_id
                        or artifact.get("expired")):
                    continue
                route = name.removeprefix("link-incident-report-")
                if route not in {"tarladaki", "penguen", "gonle", "daily_laugh", "film", "film_second", "toonzone"}:
                    continue
                latest.setdefault(route, artifact)
                receipt_found = True
            if not receipt_found:
                raise ValueError("completed run has no account receipt")
        if not latest:
            raise ValueError("no verified receipts")
        blocked, posts = [], 0
        for route, artifact in latest.items():
            aid = artifact.get("id")
            if type(aid) is not int or aid <= 0:
                raise ValueError("invalid receipt id")
            response = get(f"https://api.github.com/repos/{EXPECTED_REPO}/actions/artifacts/{aid}/zip",
                           headers=headers, timeout=5, allow_redirects=True)
            if response.status_code != 200 or len(response.content) > 4_000_000:
                raise ValueError("receipt download unavailable")
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.namelist() != ["incidents.json"] or archive.getinfo("incidents.json").file_size > 4_000_000:
                    raise ValueError("invalid receipt archive")
                receipt = json.loads(archive.read("incidents.json"))
            if str(receipt.get("run_id")) != str(artifact["workflow_run"]["id"]):
                raise ValueError("receipt run mismatch")
            count = receipt.get("confirmed_new_posts")
            blockers = receipt.get("planning_blocker_counts")
            outcomes = receipt.get("step_outcomes")
            if type(count) is not int or count < 0 or not isinstance(blockers, dict) or not isinstance(outcomes, dict):
                raise ValueError("invalid receipt evidence")
            posts += count
            if (receipt.get("state_available") is False
                    or any(type(value) is int and value > 0 for value in blockers.values())
                    or any(value == "failure" for key, value in outcomes.items()
                           if key in {"preflight", "verify", "plan", "publish", "post_verification", "notify"})
                    or receipt.get("unverified_done_entries", 0)):
                blocked.append(route)
        return {"status": "unhealthy" if blocked else "healthy",
                "reason": "publication_blocked" if blocked else "publication_receipts_checked",
                "blocked_routes": sorted(blocked), "receipt_accounts": len(latest),
                "confirmed_new_posts_in_latest_receipts": posts}
    except (requests.RequestException, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        return {"status": "unknown", "reason": "publication_receipts_unavailable"}


def check_publisher(*, now=None, token=None, get=requests.get):
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    token = token if token is not None else os.getenv("GITHUB_TOKEN", "")
    if not token:
        return {"status": "unknown", "reason": "github_token_missing"}
    try:
        response = get(
            f"https://api.github.com/repos/{EXPECTED_REPO}/actions/workflows/{WORKFLOW}/runs",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            params={"event": "schedule", "branch": "main", "per_page": 100},
            timeout=20, allow_redirects=False,
        )
        if response.status_code != 200:
            return {"status": "unknown", "reason": "github_api_unavailable",
                    "http_status": response.status_code}
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
            return {"status": "unknown", "reason": "invalid_github_response"}
        recent = []
        evidence_runs = []
        for run in payload["workflow_runs"]:
            if not isinstance(run, dict):
                return {"status": "unknown", "reason": "invalid_github_response"}
            stamp = parse_utc(run.get("created_at"))
            if (stamp and now - timedelta(hours=26) <= stamp <= now
                    and run.get("event") == "schedule"
                    and run.get("head_branch") == "main"
                    and run.get("path") == f".github/workflows/{WORKFLOW}"):
                evidence_runs.append((stamp, run))
                # The configured overnight gap is three hours. Allow an hour
                # for GitHub's scheduled-run queue without inventing an outage.
                if now - timedelta(hours=4) <= stamp:
                    recent.append((stamp, run))
        recent.sort(key=lambda row: row[0], reverse=True)
        if not recent:
            return {"status": "unhealthy", "reason": "no_recent_scheduled_runs", "recent_runs": 0}
        completed = [r for _, r in recent if r.get("status") == "completed"]
        failed_ids = [str(r["id"]) for r in completed
                      if r.get("conclusion") == "failure" and str(r.get("id", "")).isdigit()]
        # A matrix workflow can be red because one account failed while sibling
        # accounts posted successfully. Trust the per-account incident receipts
        # before classifying any workflow-level failure as a publisher outage.
        evidence = check_publication_receipts(evidence_runs, get=get, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        evidence["recent_runs"] = len(recent)
        if failed_ids:
            evidence["failed_run_ids"] = failed_ids[:8]
        return evidence
    except requests.RequestException:
        return {"status": "unknown", "reason": "github_request_failed"}
    except (TypeError, ValueError):
        return {"status": "unknown", "reason": "invalid_github_response"}


def blocked_route_alerts_acknowledged(routes, *, now=None):
    """A daily watchdog adds no message when every account deficit was ACKed today."""
    if not routes:
        return False
    now = now or datetime.now(timezone.utc)
    local_day = now.astimezone(ZoneInfo("Europe/Istanbul")).date().isoformat()
    for route in routes:
        if route not in {"tarladaki", "penguen", "gonle", "daily_laugh", "film", "film_second", "toonzone"}:
            return False
        try:
            history = alert_history.restore(names=(f"link-alert-intent-{route}", f"link-alert-result-{route}"))
            rows = alert_history.validate(history)["records"].values()
            if not any(row.get("route") == route and row.get("family") == "publication_deficit"
                       and row.get("local_day") == local_day and row.get("server_acks")
                       and not row.get("resolved") for row in rows):
                return False
        except Exception:
            return False  # Missing or corrupt ACK evidence must preserve the alarm.
    return True


def main():
    verdict = check_publisher()
    print(json.dumps(verdict, sort_keys=True), flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write(f"### Meta-only publisher health\n\n"
                         f"- Result: {verdict['status']}\n"
                         f"- Reason: {verdict.get('reason', 'unverified')}\n"
                         f"- This is an Actions health check, not proof of individual published posts.\n")
    if verdict["status"] == "healthy":
        return 0
    repeat_alerts = os.getenv("META_OUTAGE_REPEAT_ALERTS", "").strip().lower() == "true"
    if (not repeat_alerts and os.getenv("CORRELATE_PUBLISHER_ALERTS") == "true"
            and verdict.get("reason") == "publication_blocked"
            and blocked_route_alerts_acknowledged(verdict.get("blocked_routes"))):
        print('{"notification":"duplicate_health_alert_suppressed","health":"unhealthy","reason":"account_deficits_already_acknowledged_today"}', flush=True)
        return 1
    if not repeat_alerts and os.getenv("CORRELATE_PUBLISHER_ALERTS")=="true" and verdict.get("failed_run_ids"):
        try:
            if alert_history.covered(alert_history.restore(),run_ids=verdict["failed_run_ids"]):
                print('{"notification":"duplicate_health_alert_suppressed","health":"unhealthy","reason":"publisher_incident_already_acknowledged"}',flush=True)
                return 1
        except Exception:
            print('{"correlation":"unavailable","new_health_alert_preserved":true}',flush=True)
    title = "🚨 985 Meta video yayıncısı kontrolü"
    message = ("985 hesabındaki otomatik Meta yayınlarında devam eden bir engel "
               "veya doğrulanamayan çalışma kaydedildi. "
               f"Durum: {verdict['status']}; neden: {verdict.get('reason', 'unknown')}. " +
               ("Engelli hesaplar: " + ", ".join(verdict["blocked_routes"]) + ". "
                if verdict.get("blocked_routes") else "") +
               "Bu bir otomasyon arızası uyarısıdır, paylaşım sonucu değildir.")
    if os.getenv("NTFY_TOPIC", "").strip() or os.getenv("NTFY_TOPIC_URL", "").strip():
        try:
            result = send_ntfy(
                title, message, priority=4, tags=["warning"], timeout=20, require_ack=True,
                click=f"https://github.com/{EXPECTED_REPO}/actions/workflows/{WORKFLOW}",
            )
            if not isinstance(result, dict) or result.get("server_ack") is not True:
                raise RuntimeError("ntfy acknowledgment missing")
            print('{"alert": "ntfy_server_ack", "phone_delivery_verified": false}', flush=True)
        except Exception as exc:
            # Private ntfy topics and authorization URLs must not appear in logs.
            print(json.dumps({"alert": "ntfy_failed", "error_type": type(exc).__name__}), flush=True)
    else:
        print('{"alert": "ntfy_not_configured"}', flush=True)
    if telegram_configured():
        try:
            result = send_telegram(title, message)
            if not isinstance(result, dict) or result.get("server_ack") is not True:
                raise RuntimeError("telegram acknowledgment missing")
            print('{"alert": "telegram_server_ack", "phone_delivery_verified": false}', flush=True)
        except Exception as exc:
            print(json.dumps({"alert": "telegram_failed", "error_type": type(exc).__name__}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
