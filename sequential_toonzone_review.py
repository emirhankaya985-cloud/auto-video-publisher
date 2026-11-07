"""Durable, sequential, read-only ToonZone platform review orchestration.

Only one account's notification can be issued per scheduled run. Next account
cannot start until prior stage has a Telegram server ACK. Never sends likes.
"""
import argparse
import json
import os
from datetime import datetime, date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import publisher_alert_history as storage
from telegram_notifications import send_telegram, telegram_configured
from toonzone_daily_review import collect_platforms, build_platform_message

WORKFLOW = ".github/workflows/toonzone_daily_review.yml"
ARTIFACTS = ("toonzone-sequence-intent", "toonzone-sequence-result")
STATE = Path("toonzone-sequence/alert-history.json")
PLAN = Path("toonzone-sequence/plan.json")
ZONE = ZoneInfo("Europe/Istanbul")
START_DAY = date(2026, 11, 9)
ORDER = (
    "ToonZone", "Film Mağarası", "Filmmagrasi", "Beyinsiz Penguen",
    "Tarladaki Fasulye", "Gönle Düşen", "Daily Laugh Lab",
)


def active_day(now):
    local = now.astimezone(ZONE)
    # First job cannot run before 15:00 (after ToonZone's stated 12:40 finish).
    if local.date() < START_DAY or not (15 <= local.hour < 18):
        return None
    return local.date().isoformat()


def slot_ready(now):
    local = now.astimezone(ZONE)
    # Approximate 15-minute cadence; job can begin late, never early.
    return active_day(now) is not None


def prepare(history, now, run_id, discover=collect_platforms):
    storage.validate(history)
    day = active_day(now)
    if day is None:
        return {"status": "outside_window"}
    state = history.setdefault("toonzone_sequence", {})
    if not isinstance(state, dict):
        raise ValueError("invalid sequence state")
    if state.get("day") != day:
        # New day can start only if yesterday has no unresolved ambiguous send.
        if state.get("status") in {"reserved", "attempted", "uncertain"}:
            raise ValueError("prior day unresolved delivery")
        state.clear()
        state.update(day=day, cursor=0, status="ready", last_run="")
    cursor = state.get("cursor")
    if type(cursor) is not int or not 0 <= cursor <= len(ORDER):
        raise ValueError("invalid sequence cursor")
    if state.get("status") in {"reserved", "attempted", "uncertain"}:
        return {"status": "blocked_unresolved_intent", "cursor": cursor}
    if cursor == len(ORDER):
        return {"status": "day_completed", "cursor": cursor}
    actor = ORDER[cursor]
    results, failures = discover(now, actor)
    if not isinstance(results, dict) or not isinstance(failures, dict):
        raise ValueError("invalid platform discovery")
    # A failed platform read is not 'done'; defer this stage rather than advance.
    if failures:
        return {"status": "platform_read_failed", "cursor": cursor,
                "platform_failures": sorted(failures)}
    if not results:
        return {"status": "account_platform_not_configured", "cursor": cursor}
    message = build_platform_message(actor, date.fromisoformat(day), results, failures)
    state.update(status="reserved", last_run=run_id, actor=actor)
    return {"status": "reserved", "day": day, "cursor": cursor,
            "actor": actor, "message": message,
            "platforms": sorted(results), "videos": {p: len(v) for p, v in results.items()}}


def apply_ack(history, plan, run_id, *, delivered):
    storage.validate(history)
    state = history.get("toonzone_sequence")
    if (plan.get("status") != "reserved" or not isinstance(state, dict)
            or state.get("last_run") != run_id or state.get("status") not in {"reserved", "attempted"}
            or state.get("day") != plan.get("day") or state.get("cursor") != plan.get("cursor")
            or state.get("actor") != plan.get("actor")):
        raise ValueError("sequence intent mismatch")
    if not delivered:
        state["status"] = "uncertain"
        return False
    state.update(cursor=state["cursor"] + 1, status="acknowledged")
    return True


def check_runner():
    return (
        os.getenv("GITHUB_REPOSITORY") == storage.REPO
        and os.getenv("GITHUB_REF") == "refs/heads/main"
        and os.getenv("GITHUB_RUN_ATTEMPT") == "1"
        and os.getenv("GITHUB_EVENT_NAME") == "schedule"
        and os.getenv("GITHUB_RUN_ID", "").isdigit()
    )


def run_prepare(now=None, restore=storage.restore, discover=collect_platforms):
    if not check_runner():
        raise ValueError("unverified schedule identity")
    now = now or datetime.now(timezone.utc)
    prior = restore(names=ARTIFACTS, workflow_path=WORKFLOW)
    plan = prepare(prior, now, os.environ["GITHUB_RUN_ID"], discover=discover)
    storage.save(STATE, prior)
    storage.save(PLAN, plan)
    print(json.dumps({k: v for k, v in plan.items() if k != "message"}, ensure_ascii=False),
          flush=True)
    return 0


def run_send(sender=send_telegram):
    if not check_runner() or os.getenv("TOONZONE_INTENT_ARCHIVED") != "true":
        raise ValueError("sequence intent has not been durably archived")
    plan, state = storage.read(PLAN), storage.validate(storage.read(STATE))
    if plan.get("status") != "reserved":
        print(json.dumps({"status": plan.get("status"), "writes": 0}))
        return 0
    intent = state.get("toonzone_sequence")
    if (not isinstance(intent, dict) or intent.get("status") != "reserved"
            or intent.get("last_run") != os.environ["GITHUB_RUN_ID"]):
        raise ValueError("sequence state mismatch")
    # Local marker precedes the one POST. No automatic POST retries.
    intent["status"] = "attempted"
    storage.save(STATE, state)
    try:
        result = sender("🎬 ToonZone sıralı hesap incelemesi", plan["message"])
        accepted = result.get("server_ack") is True
    except Exception:
        accepted = False
    apply_ack(state, plan, os.environ["GITHUB_RUN_ID"], delivered=accepted)
    storage.save(STATE, state)
    print(json.dumps({"status": "telegram_acked" if accepted else "uncertain",
                      "account": plan["actor"], "cursor": state["toonzone_sequence"]["cursor"],
                      "meta_writes": 0}), flush=True)
    return 0 if accepted else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "send"])
    action = parser.parse_args().action
    if action == "prepare":
        return run_prepare()
    return run_send()


if __name__ == "__main__":
    raise SystemExit(main())
