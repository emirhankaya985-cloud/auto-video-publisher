"""One-shot, GET-only live acceptance for historical Meta publication intents.

Never modifies the saved state, publishes, retries a POST, or emits credentials.
"""
import json
import os
import re
from collections import Counter
from pathlib import Path

from publication_operations import audit_unresolved_remote
from publication_github_progress import restore_publication_state


REPORT = Path("unresolved-live-readonly.json")


def remote_evidence(state, pages, *, history_reader, status_reader):
    from public_link_runtime import ROUTES
    if not isinstance(pages, dict):
        raise ValueError("invalid_meta_pages")
    def page_for(route):
        if route not in ROUTES:
            raise ValueError("unknown_source_route")
        name = ROUTES[route][1]
        page = pages[name]
        if (not isinstance(page, dict) or not str(page.get("page_id") or "").isdecimal()
                or not page.get("page_token")):
            raise ValueError("invalid_page_identity")
        return page
    def history(route, platform):
        return history_reader(page_for(route), platform)
    def status(route, container_id):
        if not isinstance(container_id, str) or not re.fullmatch(r"[0-9]{1,32}", container_id):
            raise ValueError("invalid_container_id")
        return status_reader(page_for(route), container_id)
    return audit_unresolved_remote(state, history, read_container=status)


def summarize_film_blockers(rows):
    """Non-sensitive counts only; source identity remains unresolved."""
    film_blockers = {}
    for route in ("film", "film_second"):
        entries = [row for row in rows if row["route"] == route]
        film_blockers[route] = {
            "unresolved": len(entries),
            "reasons": dict(Counter(row["reason"] for row in entries)),
            "platforms": dict(Counter(row["platform"] for row in entries)),
            "source_proof_required": sum(
                row["reason"] == "caption_candidate_requires_source_proof"
                for row in entries),
            "safe_to_repost": False,
        }
    return film_blockers


CRITICAL_IG_INTENTS = {
    "tarladaki": ("192.mp4", "41301342606", "18111440750133751"),
    "film": ("En_Buyuk_Saban_Part_17.mp4", "43235604132", "17906869221599675"),
}


def critical_ig_intent_evidence(state, remote_rows):
    """Bind old IG intent + recent read-only Graph result without releasing it.

    A Facebook receipt, expired creation container or matching caption NEVER
    proves that an Instagram post exists (or is absent). No state mutation.
    """
    import hashlib
    entries = state.get("entries") if isinstance(state, dict) else None
    if not isinstance(entries, dict) or not isinstance(remote_rows, list):
        raise ValueError("critical_ig_evidence_invalid")
    summary = {}
    for route, (filename, origin_run, container_id) in CRITICAL_IG_INTENTS.items():
        matches = [(key, row) for key, row in entries.items()
                   if isinstance(row, dict) and row.get("route") == route
                   and row.get("platform") == "instagram"
                   and row.get("file") == filename
                   and str(row.get("run_id")) == origin_run]
        record = {"route": route, "platform": "instagram",
                  "source_file": filename, "origin_run_id": origin_run,
                  "safe_to_repost": False, "state_mutations": 0,
                  "instagram_post_confirmed": False,
                  "facebook_post_not_instagram_proof": True}
        if len(matches) != 1:
            record["status"] = "blocked_original_ig_ledger_not_unique"
            summary[route] = record
            continue
        key, row = matches[0]
        failure = row.get("failure") if isinstance(row.get("failure"), dict) else {}
        record["ledger_status"] = row.get("status") if row.get("status") in (
            "done", "intent", "uncertain", "held", "ready") else "unknown"
        record["original_container_binding_verified"] = failure.get("container_id") == container_id
        record["original_sha256_present"] = bool(
            isinstance(row.get("source_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]))
        record["has_ig_post_id_in_ledger"] = bool(str(row.get("post_id") or "").isdecimal())
        # Cross-platform same-Drive/source evidence is just a clue, never an IG receipt.
        source_ref = key.split(":", 2)[2] if key.startswith(route + ":instagram:") else ""
        record["facebook_sibling_done"] = any(
            isinstance(other, dict) and other.get("route") == route
            and other.get("platform") == "facebook" and other.get("status") == "done"
            and str(other.get("post_id") or "").isdecimal()
            for other_key, other in entries.items()
            if other_key.startswith(route + ":facebook:" + source_ref) and source_ref)
        fingerprint = hashlib.sha256(key.encode()).hexdigest()[:16]
        related = [x for x in remote_rows if isinstance(x, dict)
                   and x.get("route") == route and x.get("platform") == "instagram"
                   and (x.get("source_evidence") or {}).get("entry_fingerprint") == fingerprint]
        if len(related) == 1:
            evidence = related[0]
            record["remote_reason"] = evidence.get("reason", "read_result_unclassified")
            record["container_phase"] = evidence.get("existing_container_phase", "not_read")
            if str(evidence.get("candidate_post_id") or "").isdecimal():
                record["unverified_caption_candidate_id"] = evidence["candidate_post_id"]
            record["status"] = "held_requires_exact_ig_source_proof"
        else:
            record["status"] = "blocked_remote_evidence_unavailable"
        summary[route] = record
    return summary


def main():
    if (os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher"
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        raise RuntimeError("untrusted_readonly_probe_context")
    from meta_auth_loader import load_meta_auth
    from public_link_runtime import graph_rows
    from cloud_omnichannel_publisher import GRAPH_API_VERSION
    from publisher_recovery import read_with_retry
    import requests

    state = restore_publication_state()
    pages = {row["page_name"]: row for row in load_meta_auth()["pages"]}
    def container_status(page, container_id):
        response = read_with_retry(requests.get,
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
            params={"fields": "status_code,status", "access_token": page["page_token"]},
            timeout=20, allow_redirects=False, graph_read=True)
        if response.status_code != 200:
            raise RuntimeError("provider_container_read_failed")
        data = response.json()
        if (not isinstance(data, dict)
                or str(data.get("id") or container_id) != container_id):
            raise RuntimeError("provider_container_identity_invalid")
        return data.get("status_code") or data.get("status")

    rows = remote_evidence(state, pages,
        history_reader=graph_rows, status_reader=container_status)
    film_blockers = summarize_film_blockers(rows)
    critical_intents = critical_ig_intent_evidence(state, rows)
    payload = {"run_id": os.getenv("GITHUB_RUN_ID"), "mode": "readonly",
               "source": "saved_GitHub_actions_publication_ledger",
               "previous_unresolved_count": len(rows),
               "reason_counts": dict(Counter(row["reason"] for row in rows)),
               "container_phase_counts": dict(Counter(
                   row["existing_container_phase"] for row in rows
                   if "existing_container_phase" in row)),
               "safe_to_repost": False, "state_mutations": 0,
               "provider_post_requests": 0,
               "film_blockers": film_blockers,
               "critical_ig_intents": critical_intents,
               "rows": rows}
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: payload[k] for k in
        ("mode", "previous_unresolved_count", "reason_counts",
         "container_phase_counts", "safe_to_repost",
         "state_mutations", "provider_post_requests", "film_blockers",
         "critical_ig_intents")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Absolutely never print provider exception body, credential or URL.
        print("unresolved_readonly_probe_failed: " + type(exc).__name__)
        raise SystemExit(1)
