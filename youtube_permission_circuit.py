"""Dependency-free pure YouTube permission circuit; no provider network calls.

The publisher imports this same logic for its persisted intent gate and the
owner's daily read-only report imports it without googleapiclient dependencies.
"""
import re

SUPPORTED_ROUTES = frozenset({"tarladaki", "penguen", "daily_laugh", "gonle"})


def repeated_youtube_insert_forbidden(ledger, route, threshold=3):
    """Only three consecutive distinct stored 403/forbidden INSERT failures."""
    if route not in SUPPORTED_ROUTES or not isinstance(ledger, dict):
        return False
    streak, sources = 0, set()
    for key, row in reversed(list(ledger.items())):
        if not isinstance(row, dict) or row.get("route") != route:
            continue
        status = row.get("status")
        if status == "done" and row.get("post_id"):
            break
        proof = row.get("upload_error")
        if (status == "uncertain" and isinstance(proof, dict)
                and proof.get("http_status") == 403
                and proof.get("reasons") == ["forbidden"]
                and proof.get("unrecognized_reason") is False
                and isinstance(key, str) and key.startswith(route + ":")
                and key not in sources):
            sources.add(key)
            streak += 1
            if streak >= threshold:
                return True
        elif status in {"uncertain", "done", "accepted"}:
            break
    return False


def authorize_single_recheck(state, route, release_id):
    """A distinct owner-approved ID grants only one new source attempt."""
    if (route not in SUPPORTED_ROUTES or not isinstance(release_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,48}", release_id)):
        return False
    releases = state.setdefault("youtube_forbidden_release_ids", {})
    if not isinstance(releases, dict):
        raise RuntimeError("YouTube circuit state invalid")
    if releases.get(route) == release_id:
        return False
    releases[route] = release_id
    return True
