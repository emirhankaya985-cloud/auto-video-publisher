"""GET-only Film Mağarası source-to-post byte identity preflight.

Never clears historical intent, changes the publication ledger or posts to Meta.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

REPORT = Path("unresolved-live-readonly.json")
OUTPUT = Path("film-source-hash-readonly.json")
SOURCE_RE = re.compile(r"[A-Za-z0-9_-]{15,128}")


def source_id(key, row):
    if not isinstance(key, str) or not isinstance(row, dict):
        return None
    prefix = f"{row.get('route')}:{row.get('platform')}:"
    value = key[len(prefix):] if key.startswith(prefix) else ""
    return value if SOURCE_RE.fullmatch(value) else None


def compare_film_sources(state, audit, *, catalog, digest):
    """Compare only a uniquely bound existing confirmed post and its new candidate.

    The audit row order and fingerprints must match the saved state to avoid
    accidentally identifying a different Drive video as the candidate.
    Digest reads can fail closed; no result here authorizes a new POST.
    """
    all_entries = state.get("entries") if isinstance(state, dict) else None
    rows = audit.get("rows") if isinstance(audit, dict) else None
    if not isinstance(all_entries, dict) or not isinstance(rows, list):
        raise ValueError("invalid_probe_inputs")
    unresolved = [(k, v) for k, v in all_entries.items()
                  if isinstance(v, dict) and v.get("status") in ("intent", "uncertain", "held")]
    if len(rows) != len(unresolved):
        raise ValueError("probe_state_drift")
    results = []
    for (key, entry), observation in zip(unresolved, rows):
        if not isinstance(observation, dict):
            raise ValueError("invalid_probe_row")
        identity = hashlib.sha256(str(key).encode()).hexdigest()[:16]
        if (observation.get("source_evidence", {}).get("entry_fingerprint") != identity
                or observation.get("route") != entry.get("route")
                or observation.get("platform") != entry.get("platform")):
            raise ValueError("probe_identity_drift")
        if entry.get("route") not in ("film", "film_second"):
            continue
        outcome = {"route": entry["route"], "platform": entry.get("platform"),
                   "finding": "requires_manual_source_review", "safe_to_repost": False}
        if observation.get("reason") != "caption_candidate_requires_source_proof":
            results.append(outcome)
            continue
        candidate = str(observation.get("candidate_post_id", ""))
        competing = [(k, v) for k, v in all_entries.items()
                     if isinstance(v, dict) and v.get("status") == "done"
                     and v.get("route") == entry.get("route")
                     and v.get("platform") == entry.get("platform")
                     and str(v.get("post_id", "")) == candidate]
        if len(competing) != 1:
            outcome["finding"] = "candidate_has_no_unique_confirmed_source"
            results.append(outcome)
            continue
        other_key, other = competing[0]
        a, b = source_id(key, entry), source_id(other_key, other)
        catalog_by_id = {v["id"]: v for v in catalog.values()
                         if isinstance(v, dict) and isinstance(v.get("id"), str)}
        if (not a or not b or a == b or a not in catalog_by_id
                or b not in catalog_by_id
                or catalog_by_id[a]["name"] != entry.get("file")
                or catalog_by_id[b]["name"] != other.get("file")):
            outcome["finding"] = "source_catalog_identity_unverified"
            results.append(outcome)
            continue
        # Persisted digests were measured from the exact original Drive bytes.
        # They can avoid downloading large copies when *both* are present.
        def trusted_sha(value):
            return value if isinstance(value, str) and re.fullmatch(
                r"[0-9a-f]{64}", value) else None

        saved_a, saved_b = (trusted_sha(entry.get("source_sha256")),
                            trusted_sha(other.get("source_sha256")))
        if saved_a is not None and saved_b is not None:
            outcome["finding"] = (
                "identical_recorded_sha256_no_repost"
                if saved_a == saved_b
                else "different_recorded_sha256_still_held"
            )
            results.append(outcome)
            continue
        try:
            hash_a = saved_a or digest(a)
            hash_b = saved_b or digest(b)
            outcome["finding"] = (
                "identical_bytes_to_confirmed_post_no_repost"
                if hash_a == hash_b
                else "different_bytes_from_confirmed_post_still_held"
            )
        except Exception as exc:
            outcome["finding"] = "source_download_or_digest_unavailable"
            # Only a Python exception class; never emit untrusted provider
            # URLs, filenames, response bodies or access tokens.
            outcome["failure_type"] = type(exc).__name__
        results.append(outcome)
    return results


def main():
    import os
    if (os.getenv("GITHUB_REPOSITORY") != "emirhankaya985-cloud/auto-video-publisher"
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        raise RuntimeError("untrusted_probe_context")
    from publication_github_progress import restore_publication_state
    from public_link_runtime import FOLDERS, inventory, download_verified_publication_video

    audit = json.loads(REPORT.read_text(encoding="utf-8"))
    if audit.get("run_id") != os.getenv("GITHUB_RUN_ID") or audit.get("mode") != "readonly":
        raise RuntimeError("probe_run_mismatch")
    state = restore_publication_state()
    folder = inventory(FOLDERS["film"])
    cache = {}

    def digest(file_id):
        if file_id not in cache:
            with tempfile.TemporaryDirectory(prefix="film-readonly-") as d:
                path = download_verified_publication_video(file_id, Path(d) / "source.mp4")
                with path.open("rb") as source:
                    cache[file_id] = hashlib.file_digest(source, "sha256").hexdigest()
        return cache[file_id]

    results = compare_film_sources(state, audit, catalog=folder, digest=digest)
    report = {"mode": "readonly", "run_id": os.getenv("GITHUB_RUN_ID"),
              "film_findings": dict(Counter(row["finding"] for row in results)),
              "film_scope": dict(Counter(row["route"] for row in results)),
              "safe_to_repost": False, "provider_post_requests": 0,
              "ledger_writes": 0, "results": results}
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("mode", "film_findings", "film_scope", "safe_to_repost",
                       "provider_post_requests", "ledger_writes")}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("film_source_hash_readonly_failed: " + type(exc).__name__)
        raise SystemExit(1)
