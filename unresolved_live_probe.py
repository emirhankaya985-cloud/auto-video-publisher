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
# Surface Film-specific blockers in public CI logs without exposing media
# captions, Drive IDs, post IDs, token-bearing URLs, or changing the ledger.
film_blockers = {}
for route in ("film", "film_second"):
    entries = [row for row in rows if row["route"] == route]
    film_blockers[route] = {
        "unresolved": len(entries),
        "reasons": dict(Counter(row["reason"] for row in entries)),
        "platforms": dict(Counter(row["platform"] for row in entries)),
        "source_proof_required": sum(row["reason"] ==
            "caption_candidate_requires_source_proof" for row in entries),
        "safe_to_repost": False,
    }
    return film_blockers


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
               "rows": rows}
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: payload[k] for k in
        ("mode", "previous_unresolved_count", "reason_counts",
         "container_phase_counts", "safe_to_repost",
         "state_mutations", "provider_post_requests", "film_blockers")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Absolutely never print provider exception body, credential or URL.
        print("unresolved_readonly_probe_failed: " + type(exc).__name__)
        raise SystemExit(1)
