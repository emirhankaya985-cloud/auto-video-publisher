"""Read-only, redacted summary from the isolated Meta health workflow."""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = "emirhankaya985-cloud/auto-video-publisher"
WORKFLOW = "meta_engagement_isolated.yml"
OUTPUT = Path(os.getenv("ENGAGEMENT_HEALTH_REPORT_PATH", "link-runtime/engagement-health-report.json"))
ACCOUNTS = (
    "Tarladaki Fasulye", "Gönle Düşen", "Beyinsiz Penguen",
    "Daily Laugh Lab", "Film Mağarası", "ToonZone",
)
PLATFORMS = ("facebook", "instagram")
HISTORICAL_COUNT = "Hesap bazında bilinmiyor"
SAFE_RUNTIME_REASONS = {
    "meta_user_token_expired", "no_verified_enabled_accounts",
    "source_not_ready", "preflight_validation_failed",
    "read_or_runtime_failure", "audit_report_missing", "audit_report_invalid",
    "audit_evidence_incomplete",
}


def unknown_report(reason="evidence_unavailable"):
    return {
        "status": "unknown", "reason": reason,
        "latest_readonly_run": None, "latest_natural_schedule": None,
        "accounts": [
            {"account": account, "platform": platform,
             "connection": "unknown", "token_permission": "unknown",
             "historical_verified_interactions": HISTORICAL_COUNT,
             "failed_operations": "unknown", "blocked_operations": "unknown",
             "last_runtime": "unknown", "user_intervention": "unknown"}
            for account in ACCOUNTS for platform in PLATFORMS
        ],
    }


def _get_json(url, token, *, session=requests):
    response = session.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, timeout=15)
    response.raise_for_status()
    return response.json()


def _report_from_artifact(artifact, token, *, session=requests):
    url = artifact.get("archive_download_url")
    if not isinstance(url, str) or not url.startswith("https://api.github.com/"):
        return None
    response = session.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, timeout=20, allow_redirects=True)
    response.raise_for_status()
    if len(response.content) > 8_000_000:
        return None
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        entries = [name for name in bundle.namelist()
                   if name == "report.json" or name.endswith("/report.json")]
        if len(entries) != 1:
            return None
        info = bundle.getinfo(entries[0])
        if info.file_size > 1_000_000:
            return None
        value = json.loads(bundle.read(info))
    return value if isinstance(value, dict) else None


def _safe_count(value):
    return value if type(value) is int and value >= 0 else None


def collect_report(*, session=requests, repository=None, current_sha=None):
    """Read the latest main-branch audit artifact; never calls Meta or writes data."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = repository or os.getenv("GITHUB_REPOSITORY", REPO)
    current_sha = current_sha or os.getenv("GITHUB_SHA", "")
    if not token or repository != REPO:
        return unknown_report("github_read_access_unavailable")
    base = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=20"
    try:
        payload = _get_json(base, token, session=session)
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            return unknown_report("workflow_run_inventory_unavailable")
        trusted = [run for run in runs if isinstance(run, dict)
                   and run.get("head_branch") == "main"
                   and (run.get("head_repository") or {}).get("full_name") == REPO
                   and run.get("status") == "completed"]
        trusted.sort(key=lambda run: run.get("created_at", ""), reverse=True)
        latest = trusted[0] if trusted else None
        scheduled = next((run for run in trusted if run.get("event") == "schedule"), None)
        if latest is None:
            return unknown_report("no_completed_main_health_run")

        def run_summary(run):
            if not run:
                return None
            return {key: run.get(key) for key in
                    ("id", "event", "conclusion", "created_at", "updated_at", "head_sha")}

        if latest.get("conclusion") != "success":
            report = unknown_report("latest_readonly_run_failed")
            report["latest_readonly_run"] = run_summary(latest)
            report["latest_natural_schedule"] = run_summary(scheduled)
            return report

        run_id = latest.get("id")
        artifacts_payload = _get_json(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100",
            token, session=session)
        artifacts = artifacts_payload.get("artifacts") if isinstance(artifacts_payload, dict) else None
        if not isinstance(artifacts, list):
            report = unknown_report("health_artifacts_unavailable")
            report["latest_readonly_run"] = run_summary(latest)
            report["latest_natural_schedule"] = run_summary(scheduled)
            return report
        artifact_by_focus = {}
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("expired") is True:
                continue
            name = artifact.get("name", "")
            if name.startswith("account-audit-"):
                artifact_by_focus[name.removeprefix("account-audit-")] = artifact
        expected_focus = {"tarladaki", "gonle", "penguen", "daily_laugh", "film", "toonzone"}
        if set(artifact_by_focus) != expected_focus:
            report = unknown_report("account_health_artifacts_incomplete")
            report["latest_readonly_run"] = run_summary(latest)
            report["latest_natural_schedule"] = run_summary(scheduled)
            return report

        reports = {}
        for focus, artifact in artifact_by_focus.items():
            value = _report_from_artifact(artifact, token, session=session)
            if value is None or value.get("mode") != "dry_run":
                report = unknown_report("account_health_artifact_invalid")
                report["latest_readonly_run"] = run_summary(latest)
                report["latest_natural_schedule"] = run_summary(scheduled)
                return report
            reports[focus] = value

        canonical_focus = {
            "tarladaki": "Tarladaki Fasulye", "gonle": "Gönle Düşen",
            "penguen": "Beyinsiz Penguen", "daily_laugh": "Daily Laugh Lab",
            "film": "Film Mağarası", "toonzone": "ToonZone",
        }
        data = reports.get("tarladaki", {})
        names = set(data.get("verified_account_names", []))
        fb_missing = set(data.get("facebook_unverified_routes", []))
        ig_missing = set(data.get("instagram_unverified_routes", []))
        coverage = data.get("verified_like_coverage", {})
        fb_coverage = coverage.get("facebook", {}) if isinstance(coverage, dict) else {}
        fb_permissions = set(fb_coverage.get("permission_eligible_actor_routes", []))
        platform_acks = {
            platform: _safe_count((coverage.get(platform) or {}).get(
                "historical_api_ack_count_in_retained_ledger"))
            for platform in PLATFORMS
        } if isinstance(coverage, dict) else {platform: None for platform in PLATFORMS}

        complete = (names == set(ACCOUNTS) and not fb_missing and not ig_missing
                    and data.get("verified_facebook_identities") == len(ACCOUNTS)
                    and data.get("verified_instagram_identities") == len(ACCOUNTS))
        stale_sha = bool(current_sha and latest.get("head_sha") != current_sha)
        freshness = "stale_code" if stale_sha else "latest_code"
        latest_time = latest.get("updated_at") or latest.get("created_at") or "unknown"
        rows = []
        for focus, account in canonical_focus.items():
            scoped = reports[focus]
            block_counts = scoped.get("blocked_counts", {})
            for platform in PLATFORMS:
                missing = fb_missing if platform == "facebook" else ig_missing
                connection_ok = complete and account in names and account not in missing
                if platform == "facebook":
                    grant = ("pages_manage_engagement: present" if account in fb_permissions
                             else "permission not confirmed")
                    write_status = "disabled_by_policy"
                else:
                    grant = "read identity checked; like-write permission not applicable"
                    write_status = "unsupported_by_verified_api"
                per_platform_blocks = {
                    key: _safe_count(value) for key, value in block_counts.items()
                    if key.startswith(f"{platform}/") and _safe_count(value) is not None
                }
                rows.append({
                    "account": account, "platform": platform,
                    "connection": "ok_at_last_read" if connection_ok else "unknown",
                    "token_permission": grant if connection_ok else "unknown",
                    "write_status": write_status,
                    "historical_verified_interactions": HISTORICAL_COUNT,
                    "platform_historical_api_ack_count": platform_acks.get(platform),
                    "failed_operations": "none reported by successful health run" if connection_ok else "unknown",
                    "blocked_operations": per_platform_blocks or "none reported" if connection_ok else "unknown",
                    "last_runtime": latest_time,
                    "user_intervention": "none flagged at last read" if connection_ok else "check current token/permissions",
                })
        return {
            "status": "complete" if complete else "partial",
            "freshness": freshness,
            "latest_readonly_run": run_summary(latest),
            "latest_natural_schedule": run_summary(scheduled),
            "natural_schedule_on_current_sha": bool(scheduled and current_sha and scheduled.get("head_sha") == current_sha),
            "current_main_sha": current_sha or None,
            "platform_historical_api_ack": platform_acks,
            "account_historical_count_note": HISTORICAL_COUNT,
            "accounts": rows,
            "source_artifact_count": len(reports),
        }
    except (requests.RequestException, ValueError, KeyError, TypeError, zipfile.BadZipFile, OSError):
        return unknown_report("health_evidence_read_failed")


def format_report(report):
    lines = ["🔎 ETKİLEŞİM SAĞLIK DENETİMİ"]
    run = report.get("latest_readonly_run")
    if isinstance(run, dict):
        lines.append(f"Son salt-okunur koşum: {run.get('id', 'unknown')} / {run.get('event', 'unknown')} / {run.get('updated_at') or run.get('created_at', 'unknown')}")
        if report.get("freshness") == "stale_code":
            lines.append("Durum: son hesap kanıtı mevcut main commit'inden eski.")
    else:
        lines.append("Son koşum: bilinmiyor; sağlık verisi eksik.")
    schedule = report.get("latest_natural_schedule")
    if isinstance(schedule, dict):
        lines.append(f"Son doğal zamanlama: {schedule.get('id', 'unknown')} / {schedule.get('updated_at') or schedule.get('created_at', 'unknown')}")
    else:
        lines.append("Son doğal zamanlama: bilinmiyor.")
    lines.append("Doğal zamanlama güncel main commit'inde görüldü: "
                 + ("evet" if report.get("natural_schedule_on_current_sha") is True else "hayır / doğrulanmadı"))
    lines.append("Beğeni yazımı: Facebook otomatik beğeni politika gereği kapalı; Instagram API yazımı desteklemiyor.")
    acknowledgements = report.get("platform_historical_api_ack", {})
    fb_ack = acknowledgements.get("facebook") if isinstance(acknowledgements, dict) else None
    lines.append("Tarihî API yanıtı (platformda beğeni kanıtı değildir): Facebook "
                 + (str(fb_ack) if type(fb_ack) is int else "bilinmiyor")
                 + "; Instagram desteklenmeyen yazma olarak sayılmıyor.")
    lines.append("Tarihî hesap bazlı beğeni sayısı: mevcut makbuzlarda hesap eşleşmesi yok, bilinmiyor (sıfır değil).")
    lines.append("Doğal zamanlama güncel main commit'inde görüldü: "
                 + ("evet" if report.get("natural_schedule_on_current_sha") is True else "hayır / doğrulanmadı"))
    lines.append("Beğeni yazımı: Facebook otomatik beğeni politika gereği kapalı; Instagram API yazımı desteklemiyor.")
    acknowledgements = report.get("platform_historical_api_ack", {})
    fb_ack = acknowledgements.get("facebook") if isinstance(acknowledgements, dict) else None
    lines.append("Tarihî API yanıtı (platformda beğeni kanıtı değildir): Facebook "
                 + (str(fb_ack) if type(fb_ack) is int else "bilinmiyor")
                 + "; Instagram desteklenmeyen yazma olarak sayılmıyor.")
    lines.append("Tarihî hesap bazlı beğeni sayısı: mevcut makbuzlarda hesap eşleşmesi yok, bilinmiyor (sıfır değil).")
    for row in report.get("accounts", []):
        if not isinstance(row, dict):
            continue
        connection = row.get("connection", "unknown")
        permission = row.get("token_permission", "unknown")
        intervention = row.get("user_intervention", "unknown")
        history = row.get("historical_verified_interactions", HISTORICAL_COUNT)
        lines.append(
            f"• {row.get('account', 'unknown')} / {row.get('platform', 'unknown')}: "
            f"bağlantı={connection}; token/izin={permission}; geçmiş={history}; "
            f"hata={row.get('failed_operations', 'unknown')}; "
            f"engelli={row.get('blocked_operations', 'unknown')}; "
            f"son çalışma={row.get('last_runtime', 'unknown')}; müdahale={intervention}"
        )
    return "\n".join(lines)


def format_digest(report):
    """Fit the complete 12-route health summary into ntfy's 4 KiB body limit."""
    body = format_report(report)
    if len(body.encode("utf-8")) <= 4096:
        return body
    accounts = report.get("accounts")
    if not isinstance(accounts, list):
        return body.encode("utf-8")[:4096].decode("utf-8", errors="ignore")
    lines = ["🔎 ETKİLEŞİM SAĞLIK DENETİMİ", "Rapor kısaltıldı; ayrıntılı JSON Actions artifact'ında."]
    for row in accounts:
        if not isinstance(row, dict):
            continue
        line = (f"• {row.get('account', 'unknown')} / {row.get('platform', 'unknown')}: "
                f"bağlantı={row.get('connection', 'unknown')}; "
                f"token/izin={row.get('token_permission', 'unknown')}; "
                f"geçmiş={row.get('historical_verified_interactions', HISTORICAL_COUNT)}; "
                f"hata={row.get('failed_operations', 'unknown')}; "
                f"engelli={row.get('blocked_operations', 'unknown')}; "
                f"son çalışma={row.get('last_runtime', 'unknown')}; "
                f"müdahale={row.get('user_intervention', 'unknown')}")
        lines.append(line)
    lines.extend([
        "Facebook beğeni yazımı kapalı; Instagram beğeni yazımı desteklenmiyor.",
        "Tarihî hesap bazlı beğeni sayısı bilinmiyor; API yanıtları platform kanıtı değildir.",
    ])
    while len("\n".join(lines).encode("utf-8")) > 4096 and len(lines) > 2:
        lines.pop(-3)
    return "\n".join(lines)


def persist_artifact(report, path=None):
    path = Path(path or OUTPUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path

