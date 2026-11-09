"""Reconcile independent account artifacts into the legacy read-only report.

Publishing jobs never consume this combined report once scoped artifacts exist.
A sibling failure cannot overwrite another account's authoritative state.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

SCOPES = ("tarladaki", "penguen", "gonle", "daily_laugh",
          "film", "film_second", "toonzone")


def _check(state):
    if not isinstance(state, dict) or state.get("schema") != 1:
        raise ValueError("Invalid state schema")
    if not isinstance(state.get("entries"), dict):
        raise ValueError("Invalid publication entries")
    if not isinstance(state.get("episode_days", {}), dict):
        raise ValueError("Invalid episode cursor")
    return state


def merge_account_states(base, account_states):
    """Merge ONLY the chosen route's entries, never foreign/stale snapshots."""
    merged = copy.deepcopy(_check(base))
    if not isinstance(account_states, dict):
        raise ValueError("Invalid scoped result set")
    for scope, incoming in account_states.items():
        if scope not in SCOPES:
            raise ValueError("Unrecognized account scope")
        incoming = _check(incoming)
        for key, row in incoming["entries"].items():
            if not isinstance(row, dict) or not isinstance(row.get("route"), str):
                raise ValueError("Invalid publication entry")
            if row["route"] == scope:
                if not key.startswith(scope + ":"):
                    raise ValueError("Entry key does not match account")
                merged["entries"][key] = copy.deepcopy(row)
        alerts = incoming.get("queue_alert_days", {})
        if alerts:
            if not isinstance(alerts, dict):
                raise ValueError("Invalid scoped alert days")
            if scope in alerts:
                merged.setdefault("queue_alert_days", {})[scope] = alerts[scope]
        if scope == "toonzone":
            merged.setdefault("episode_days", {}).update(
                copy.deepcopy(incoming.get("episode_days", {})))
    return merged


def read_scoped_results(root):
    """Result beats intent within each job, including partial publish failures."""
    results = {}
    for scope in SCOPES:
        for kind in ("result", "intent"):
            candidate = root / ("link-state-" + kind + "-" + scope)
            if not candidate.is_dir():
                continue
            matches = list(candidate.rglob("state.json"))
            if len(matches) != 1:
                raise ValueError("Ambiguous scoped publication state")
            results[scope] = json.loads(matches[0].read_text(encoding="utf-8"))
            break
    return results


def main():
    from public_link_runtime import restore, save, STATE

    # Only the aggregator can write the combined legacy receipt. Never use a
    # scoped environment value here or accidentally read a sibling's archive.
    if os.getenv("PUBLISH_ACCOUNT_SCOPE"):
        raise RuntimeError("Account-scoped job cannot aggregate other accounts")
    scoped = read_scoped_results(Path("link-runtime/account-artifacts"))
    if not scoped:
        raise RuntimeError("No account artifacts to aggregate")
    prior = restore()
    combined = merge_account_states(prior, scoped)
    save(STATE, combined)
    Path("link-runtime/merge-account-report.json").write_text(
        json.dumps({"schema": 1, "merged_accounts": sorted(scoped),
                    "missing_accounts": sorted(set(SCOPES) - set(scoped)),
                    "publication_verified": False}, indent=2),
        encoding="utf-8")
    print("Merged read-only account receipts:", ", ".join(sorted(scoped)))


if __name__ == "__main__":
    main()
