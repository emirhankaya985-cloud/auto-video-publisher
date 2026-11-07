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
    "visual_duplicate_review",
}
_SAFE_STATUSES = {"done", "ready", "uncertain", "intent", "held"}


def build_incident_report(state, run_id, *, plan_text="", errors=None, step_outcomes=None, state_available=True):
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
                              "source_review_required_no_repost" if status == "held" else
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
        "no_eligible_content": "No eligible unpublished item below the daily target.",
    }
    blockers = {name: sum(line.startswith(marker) for line in plan_text.splitlines())
                for name, marker in markers.items()}
    # Journal events are emitted at each individual exception/hold, even if
    # the state is later reconciled or a different account publishes.
    # Never persist raw provider responses or secret-bearing tracebacks.
    events = [event for event in (errors or []) if event.get("run_id") == run_id]
    outcomes = {k: v for k, v in (step_outcomes or {}).items()
                if k in ("preflight", "verify", "plan", "publish", "youtube_prepare", "youtube_publish", "post_verification", "notify")
                and v in ("success", "failure", "skipped", "cancelled")}
    # An early credential gate can fail before any ledger exists. Never present
    # an empty incident list as proof of a healthy publication run.
    if outcomes.get("preflight") == "failure":
        incidents.append({
            "route": "all", "platform": "unknown", "status": "blocked",
            "reason": "meta_preflight_failed",
            "action": "inspect_redacted_preflight_log_no_meta_post",
        })
    # Preserve visibility of earlier uncertain publish attempts. Counts scoped
    # only to the current run otherwise misreport a held queue as fully healthy.
    previous_held = [
        row for row in state["entries"].values()
        if isinstance(row, dict)
        and row.get("status") in ("intent", "uncertain", "held")
        and str(row.get("run_id", "")) != str(run_id)
    ]
    # Old "previous_unreconciled_intents" included local visual-duplicate
    # holds that explicitly prove NO provider POST was attempted. Keep the
    # legacy total field for existing consumers but expose precise categories:
    # an ambiguous POST MUST be checked against remote history, while a
    # local-only duplicate is correctly blocked and must never be resubmitted.
    remote_reconciliation = [
        row for row in previous_held
        if row.get("status") in ("intent", "uncertain")
    ]
    known_nonposted_visual_holds = [
        row for row in previous_held
        if row.get("status") == "held"
        and isinstance(row.get("failure"), dict)
        and row["failure"].get("reason") == "visual_duplicate_review"
        and row["failure"].get("external_post_attempted") is False
        and row["failure"].get("safe_to_repost") is False
    ]
    other_held = len(previous_held) - len(remote_reconciliation) - len(known_nonposted_visual_holds)
    safe_routes = {"tarladaki", "penguen", "gonle", "daily_laugh",
                   "film", "film_second", "toonzone"}
    previous_held_routes = dict(Counter(
        row.get("route") if row.get("route") in safe_routes else "unknown"
        for row in previous_held
    ))
    return {
        "schema": 2, "run_id": run_id,
        "state_available": bool(state_available),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "confirmed_new_posts": counts["done"],
        "unverified_done_entries": counts["unverified_done"],
        "safe_pre_upload_retries": counts["ready"],
        "held_for_review": counts["held"],
        "uncertain_pending_reconciliation": counts["intent"] + counts["uncertain"],
        # Legacy count is all prior pending/held rows, not necessarily POSTs.
        "previous_unreconciled_intents": len(previous_held),
        "previous_unreconciled_by_route": previous_held_routes,
        "previous_remote_reconciliation_required": len(remote_reconciliation),
        "previous_known_nonposted_visual_holds": len(known_nonposted_visual_holds),
        "previous_other_review_holds": other_held,
        "previous_ambiguous_by_route": dict(Counter(
            row.get("route") if row.get("route") in safe_routes else "unknown"
            for row in remote_reconciliation
        )),
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
                for key in ("preflight", "verify", "plan", "publish", "youtube_prepare", "youtube_publish", "post_verification", "notify")}
    summary = build_incident_report(
        state, run_id, plan_text=plan_text,
        errors=read_errors(run_id=run_id), step_outcomes=outcomes,
        state_available=state_path.is_file(),
    )
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "incidents.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("run_id", "confirmed_new_posts",
                      "unverified_done_entries", "safe_pre_upload_retries", "uncertain_pending_reconciliation",
                      "previous_unreconciled_intents", "previous_unreconciled_by_route",
                      "previous_remote_reconciliation_required",
                      "previous_known_nonposted_visual_holds", "previous_other_review_holds",
                      "previous_ambiguous_by_route",
                      "planning_blocker_counts", "error_event_count", "step_outcomes",
                      "state_available")},
                     ensure_ascii=False), flush=True)
    # Do not let an apparently green workflow conceal a completed entry with
    # no verifiable platform post ID. Artifact upload steps use always().
    if summary["unverified_done_entries"]:
        raise SystemExit("Publication evidence anomaly: done entry without post_id")


if __name__ == "__main__":
    main()
