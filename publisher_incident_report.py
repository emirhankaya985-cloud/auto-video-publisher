"""Tamper-resistant-ish, credential-free incident summary for each publisher run.

The source of truth is the persisted publication ledger, not CI green badges.
Output is an artifact, not an extra publishing action.
"""
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from publisher_error_journal import read_errors

ROOT = Path("link-runtime")
_SAFE_REASONS = {
    "source_or_cover_preparation_failed", "media_preparation_failed",
    "credentials_or_permissions", "rate_limit", "meta_server_or_network",
    "invalid_media_or_graph_request", "unclassified_upload_result",
}
_SAFE_STATUSES = {"done", "ready", "uncertain", "intent"}


def build_incident_report(state, run_id, *, plan_text="", errors=None, step_outcomes=None):
    if not str(run_id).isdigit():
        raise ValueError("GitHub run ID invalid")
    if not isinstance(state, dict) or not isinstance(state.get("entries"), dict):
        raise ValueError("Publication ledger invalid")
    counts, incidents = Counter(), []
    for key, row in state["entries"].items():
        if not isinstance(row, dict) or str(row.get("run_id", "")) != run_id:
            continue
        status = row.get("status")
        if status not in _SAFE_STATUSES:
            raise ValueError("Unknown ledger status")
        # A green result needs a real platform post identifier.
        if status == "done" and not str(row.get("post_id", "")).strip():
            counts["unverified_done"] += 1
            incidents.append({
                "route": str(row.get("route", ""))[:45],
                "platform": row.get("platform") if row.get("platform") in ("facebook", "instagram") else "unknown",
                "status": "done",
                "reason": "missing_confirmed_post_id",
                "action": "verify_remote_post_before_claiming_success",
            })
        else:
            counts[status] += 1
        detail = row.get("failure")
        if not isinstance(detail, dict):
            continue
        reason = detail.get("reason")
        reason = reason if reason in _SAFE_REASONS else "unknown"
        # Deliberately avoid raw Meta error messages, OAuth values and URLs.
        incident = {"route": str(row.get("route", ""))[:45],
                    "platform": row.get("platform") if row.get("platform") in ("facebook", "instagram") else "unknown",
                    "status": status, "reason": reason,
                    "action": "remote_reconciliation_required" if status in ("intent", "uncertain") else
                              "safe_to_reprepare_next_tick"}
        for field in ("http_status", "graph_code", "graph_subcode"):
            value = detail.get(field)
            if type(value) is int and 0 <= value <= 99999999:
                incident[field] = value
        incidents.append(incident)
    markers = {
        "missing_drive_folder": "HELD source ",
        "txt_or_caption_blocked": "HELD TXT/caption:",
        "toonzone_exact_cover_missing": "HELD: exact ToonZone cover missing.",
        "disabled_route": "HELD: existing route/rights switch is disabled.",
        "meta_history_blocked": "HELD: Meta geçmişi",
    }
    blockers = {name: sum(line.startswith(marker) for line in plan_text.splitlines())
                for name, marker in markers.items()}
    # Journal events are emitted at each individual exception/hold, even if
    # the state is later reconciled or a different account publishes.
    # Never persist raw provider responses or secret-bearing tracebacks.
    events = [event for event in (errors or []) if event.get("run_id") == run_id]
    outcomes = {k: v for k, v in (step_outcomes or {}).items()
                if k in ("verify", "plan", "publish", "notify")
                and v in ("success", "failure", "skipped", "cancelled")}
    # Preserve visibility of earlier uncertain publish attempts. Counts scoped
    # only to the current run otherwise misreport a held queue as fully healthy.
    previous_held = [
        row for row in state["entries"].values()
        if isinstance(row, dict)
        and row.get("status") in ("intent", "uncertain")
        and str(row.get("run_id", "")) != str(run_id)
    ]
    safe_routes = {"tarladaki", "penguen", "gonle", "daily_laugh",
                   "film", "film_second", "toonzone"}
    previous_held_routes = dict(Counter(
        row.get("route") if row.get("route") in safe_routes else "unknown"
        for row in previous_held
    ))
    return {
        "schema": 2, "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "confirmed_new_posts": counts["done"],
        "unverified_done_entries": counts["unverified_done"],
        "safe_pre_upload_retries": counts["ready"],
        "uncertain_pending_reconciliation": counts["intent"] + counts["uncertain"],
        "previous_unreconciled_intents": len(previous_held),
        "previous_unreconciled_by_route": previous_held_routes,
        "incidents": incidents, "planning_blocker_counts": blockers,
        "all_error_events": events, "error_event_count": len(events),
        "step_outcomes": outcomes,
        "run_url": f"https://github.com/emirhankaya985-cloud/auto-video-publisher/actions/runs/{run_id}",
        "message": "No automatic Meta POST retries. Confirm remote history before reattempting an ambiguous upload.",
    }


def main():
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    state_path = ROOT / "state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"entries": {}}
    report_path = ROOT / "report.md"
    plan_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    outcomes = {key: os.getenv("OUTCOME_" + key.upper(), "")
                for key in ("verify", "plan", "publish", "notify")}
    summary = build_incident_report(
        state, run_id, plan_text=plan_text,
        errors=read_errors(run_id=run_id), step_outcomes=outcomes,
    )
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "incidents.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("run_id", "confirmed_new_posts",
                      "unverified_done_entries", "safe_pre_upload_retries", "uncertain_pending_reconciliation",
                      "previous_unreconciled_intents", "previous_unreconciled_by_route",
                      "planning_blocker_counts", "error_event_count", "step_outcomes")},
                     ensure_ascii=False), flush=True)
    # Do not let an apparently green workflow conceal a completed entry with
    # no verifiable platform post ID. Artifact upload steps use always().
    if summary["unverified_done_entries"]:
        raise SystemExit("Publication evidence anomaly: done entry without post_id")


if __name__ == "__main__":
    main()
